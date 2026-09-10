"""
SwitchPosManager 换仓执行流程补充单元测试

覆盖：
- 初始化/start/stop_rotation/指令加载
- update_instruction/delete_instruction
- import_csv 各校验分支与入库模式
- execute_position_rotation 主流程（无指令/异常/价格透传/已完成指令）
- _monitor_order_commands 监控循环（完成/失败/部分成交/停止请求/指令缺失）
- _check_instruction / _snapshot_instruction / _update_instructions
"""

import os
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.models.po import RotationInstructionPo
from qtrader.trader.order_cmd import OrderCmdFinishReason
from qtrader.trader.switch_mgr import SwitchPosManager

TODAY = datetime.now().strftime("%Y%m%d")


def build_manager(account_id: str = "DQ") -> SwitchPosManager:
    """构造一个不依赖数据库/配置文件的 SwitchPosManager"""
    mgr = SwitchPosManager.__new__(SwitchPosManager)
    mgr.config = MagicMock()
    mgr.config.account_id = account_id
    mgr.trading_engine = MagicMock()
    mgr.switchPos_files_dir = ""
    mgr.working = False
    mgr.running_instructions = None
    mgr.is_manual = False
    mgr.all_instructions = []
    mgr._stop_requested = False
    return mgr


def make_instruction(**overrides) -> RotationInstructionPo:
    """构造一条默认可执行的换仓指令 PO"""
    defaults = dict(
        id=1,
        account_id="DQ",
        strategy_id="S1",
        symbol="SHFE.rb2509",
        offset="CLOSE",
        direction="SELL",
        volume=2,
        filled_volume=0,
        remaining_volume=2,
        price=0,
        order_time=None,
        trading_date=TODAY,
        enabled=True,
        status="PENDING",
        is_deleted=False,
        current_order_id=None,
        error_message=None,
        order_placed_time=None,
        source="20260818_DQ.csv",
    )
    defaults.update(overrides)
    return RotationInstructionPo(**defaults)


def scope_with(session: MagicMock) -> MagicMock:
    """返回一个模拟的 get_async_session，进入时返回给定 session"""
    cm = MagicMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return MagicMock(return_value=cm)


def async_session() -> MagicMock:
    """构造 AsyncSession 模拟对象（merge/execute 为 await 调用）"""
    session = MagicMock()
    session.merge = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.mark.unit
class TestSwitchMgrInit:
    """初始化与生命周期"""

    def test_init_loads_paths_from_app_config(self):
        """初始化时应从全局配置读取换仓目录并重置各状态位"""
        with patch("qtrader.trader.switch_mgr.get_config_loader") as loader:
            loader.return_value._load_app_config.return_value = Mock(
                paths=Mock(switch_pos="/tmp/orders")
            )
            mgr = SwitchPosManager(MagicMock(), MagicMock())
        assert mgr.switchPos_files_dir == "/tmp/orders"
        assert mgr.working is False
        assert mgr.is_manual is False
        assert mgr.all_instructions == []
        assert mgr._stop_requested is False

    async def test_start_loads_instructions(self):
        """start() 应触发指令加载"""
        mgr = build_manager()
        mgr.load_rotation_instructions = AsyncMock()
        await mgr.start()
        mgr.load_rotation_instructions.assert_called_once()

    def test_stop_rotation_without_working(self):
        """未在换仓时请求停止不应置位停止标记"""
        mgr = build_manager()
        mgr.working = False
        mgr.stop_rotation()
        assert mgr._stop_requested is False

    def test_stop_rotation_requests_stop(self):
        """换仓进行中请求停止应置位停止标记"""
        mgr = build_manager()
        mgr.working = True
        mgr.stop_rotation()
        assert mgr._stop_requested is True

    def test_get_today_instructions_filters_by_date(self):
        """get_today_instructions 只返回交易日为今日的指令"""
        mgr = build_manager()
        mgr.all_instructions = [
            make_instruction(id=1, trading_date=TODAY),
            make_instruction(id=2, trading_date="20200101"),
        ]
        today = mgr.get_today_instructions()
        assert [x.id for x in today] == [1]


@pytest.mark.unit
class TestSwitchMgrLoadInstructions:
    """load_rotation_instructions 加载与订阅"""

    async def test_load_populates_and_subscribes_symbols(self):
        """加载成功后应填充指令列表并订阅去重后的合约"""
        mgr = build_manager()
        instructions = [
            make_instruction(id=1, symbol="SHFE.rb2509"),
            make_instruction(id=2, symbol="SHFE.rb2509"),
            make_instruction(id=3, symbol="SHFE.hc2509"),
        ]
        session = async_session()
        with (
            patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)),
            patch("qtrader.trader.switch_mgr.fetch_all", AsyncMock(return_value=instructions)),
        ):
            await mgr.load_rotation_instructions()
        assert mgr.all_instructions == instructions
        mgr.trading_engine.subscribe_symbol.assert_called_once()
        assert set(mgr.trading_engine.subscribe_symbol.call_args[0][0]) == {
            "SHFE.rb2509",
            "SHFE.hc2509",
        }

    async def test_load_with_db_error_keeps_empty_list(self):
        """数据库异常时不应抛出，指令列表保持为空"""
        mgr = build_manager()
        with patch(
            "qtrader.trader.switch_mgr.get_async_session",
            MagicMock(side_effect=RuntimeError("db down")),
        ):
            await mgr.load_rotation_instructions()
        assert mgr.all_instructions == []
        mgr.trading_engine.subscribe_symbol.assert_not_called()


@pytest.mark.unit
class TestSwitchMgrUpdateDeleteInstruction:
    """update_instruction / delete_instruction"""

    async def test_update_instruction_requires_id(self):
        """缺少指令ID时应抛出 ValueError"""
        mgr = build_manager()
        with pytest.raises(ValueError, match="缺少指令ID"):
            await mgr.update_instruction({})

    async def test_update_instruction_unknown_id(self):
        """指令不存在时应抛出 ValueError"""
        mgr = build_manager()
        mgr.all_instructions = [make_instruction(id=1)]
        with pytest.raises(ValueError, match="指令不存在"):
            await mgr.update_instruction({"instruction_id": 99})

    async def test_update_instruction_applies_fields_and_persists(self):
        """应更新字段、同步剩余手数并 merge 入库"""
        mgr = build_manager()
        inst = make_instruction(id=7, volume=5, filled_volume=2, remaining_volume=3)
        mgr.all_instructions = [inst]
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            updated = await mgr.update_instruction(
                {
                    "instruction_id": 7,
                    "enabled": False,
                    "status": "FAILED",
                    "filled_volume": 2,
                    "direction": "BUY",
                    "offset": "OPEN",
                    "volume": 4,
                }
            )
        assert updated is inst
        assert inst.enabled is False
        assert inst.status == "FAILED"
        assert inst.direction == "BUY"
        assert inst.offset == "OPEN"
        # volume 更新时同步剩余手数: max(0, 4-2) = 2
        assert inst.remaining_volume == 2
        assert inst.updated_at is not None
        session.merge.assert_awaited_once_with(inst)

    async def test_delete_instruction_filters_memory_and_db(self):
        """删除指令应同时过滤内存列表并标记入库 is_deleted"""
        mgr = build_manager()
        mgr.all_instructions = [
            make_instruction(id=1),
            make_instruction(id=2),
            make_instruction(id=3),
        ]
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            await mgr.delete_instruction([1, 3])
        assert [x.id for x in mgr.all_instructions] == [2]
        session.execute.assert_awaited_once()
        assert session.execute.await_args[0][0].compile().params["is_deleted"] is True


@pytest.mark.unit
class TestSwitchMgrImportCsvValidation:
    """import_csv 输入校验分支"""

    def setup_method(self):
        self.mgr = build_manager()
        self.mgr.trading_engine.std_symbol = lambda s: s
        self.mgr.load_rotation_instructions = AsyncMock()

    async def test_import_csv_empty_text_raises(self):
        """只有表头时视为空文件，抛出 ValueError"""
        with pytest.raises(ValueError, match="CSV文件为空"):
            await self.mgr.import_csv("account,strategy\n", "20260818_DQ.csv")

    async def test_import_csv_filename_without_date_raises(self):
        """文件名中无 8 位日期时抛出 ValueError"""
        with pytest.raises(ValueError, match="无法提取交易日"):
            await self.mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\nDQ,S1,rb2509,Open,Buy,1\n",
                "rotation.csv",
            )

    async def test_import_csv_incomplete_row_skipped(self):
        """列数不足 6 的行跳过并计入失败"""
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await self.mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\nDQ,S1\n",
                "20260818_DQ.csv",
            )
        assert result["imported"] == 0
        assert result["failed"] == 1

    async def test_import_csv_account_mismatch_skipped(self):
        """账户 ID 与配置不一致的行跳过"""
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await self.mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\nXX,S1,rb2509,Open,Buy,1\n",
                "20260818_DQ.csv",
            )
        assert result["imported"] == 0
        assert result["failed"] == 1

    async def test_import_csv_invalid_volume_skipped(self):
        """手数非数字时跳过"""
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await self.mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\nDQ,S1,rb2509,Open,Buy,abc\n",
                "20260818_DQ.csv",
            )
        assert result["imported"] == 0
        assert result["failed"] == 1

    async def test_import_csv_nonpositive_volume_skipped(self):
        """手数小于等于 0 时跳过"""
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await self.mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\nDQ,S1,rb2509,Open,Buy,0\n",
                "20260818_DQ.csv",
            )
        assert result["imported"] == 0
        assert result["failed"] == 1

    async def test_import_csv_row_error_recorded(self):
        """行内解析异常时应记入 errors 并计入失败"""
        self.mgr.trading_engine.std_symbol = MagicMock(side_effect=ValueError("bad symbol"))
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await self.mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\nDQ,S1,rb2509,Open,Buy,1\n",
                "20260818_DQ.csv",
            )
        assert result["imported"] == 0
        assert result["failed"] == 1
        assert result["errors"][0]["row"] == 2


@pytest.mark.unit
class TestSwitchMgrImportCsvModes:
    """import_csv 成功入库路径与字段映射"""

    def setup_method(self):
        self.mgr = build_manager()
        self.mgr.trading_engine.std_symbol = lambda s: s
        self.mgr.load_rotation_instructions = AsyncMock()

    async def _import_two_rows(self, mode):
        """导入两行数据并返回 (result, session)"""
        csv_text = (
            "account,strategy,symbol,offset,direction,volume,order_time\n"
            "DQ,S1,rb2509,开仓,买入,1,09:00:00\n"
            "DQ,S2,rb2509,平仓,卖出,2,09:30:00\n"
        )
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await self.mgr.import_csv(csv_text, "20260818_DQ.csv", mode=mode)
        return result, session

    async def test_import_csv_replace_mode(self):
        """replace 模式应先软删除已有记录再批量写入"""
        result, session = await self._import_two_rows("replace")
        assert result["imported"] == 2
        assert result["failed"] == 0
        session.execute.assert_awaited_once()
        assert session.execute.await_args[0][0].compile().params["is_deleted"] is True
        saved = session.add_all.call_args[0][0]
        assert len(saved) == 2

    async def test_import_csv_append_mode_keeps_existing(self):
        """append 模式不应触发删除，只批量写入"""
        result, session = await self._import_two_rows("append")
        assert result["imported"] == 2
        session.execute.assert_not_awaited()
        assert len(session.add_all.call_args[0][0]) == 2

    async def test_import_csv_maps_chinese_and_english_terms(self):
        """开平/方向应完成中文与英文关键字到枚举值的映射"""
        _, session = await self._import_two_rows("append")
        saved = session.add_all.call_args[0][0]
        by_strategy = {po.strategy_id: po for po in saved}
        assert by_strategy["S1"].offset == "OPEN"
        assert by_strategy["S1"].direction == "BUY"
        assert by_strategy["S2"].offset == "CLOSE"
        assert by_strategy["S2"].direction == "SELL"

    async def test_import_csv_builds_po_fields(self):
        """生成的 PO 应带齐解析出的字段与文件来源信息"""
        _, session = await self._import_two_rows("append")
        po = session.add_all.call_args[0][0][0]
        assert po.account_id == "DQ"
        assert po.symbol == "rb2509"
        assert po.volume == 1
        assert po.filled_volume == 0
        assert po.remaining_volume == 1
        assert po.price == 0
        assert po.order_time == "09:00:00"
        assert po.trading_date == "20260818"
        assert po.enabled is True
        assert po.status == "PENDING"
        assert po.source == "20260818_DQ.csv"
        assert po.is_deleted is False


@pytest.mark.unit
class TestExecutePositionRotation:
    """execute_position_rotation 主流程"""

    def setup_method(self):
        self.mgr = build_manager()
        self.mgr.config.trading.risk_control.max_split_volume = 10
        self.mgr._update_instructions = AsyncMock()

    @pytest.mark.asyncio
    async def test_skips_when_already_working(self):
        """换仓进行中重复触发应直接跳过"""
        self.mgr.working = True
        self.mgr.get_today_instructions = MagicMock()
        await self.mgr.execute_position_rotation(is_manual=True)
        self.mgr.get_today_instructions.assert_not_called()
        assert self.mgr.working is True

    @pytest.mark.asyncio
    async def test_no_instructions_resets_working(self):
        """今日无指令时应直接结束并复位 working"""
        self.mgr.get_today_instructions = MagicMock(return_value=[])
        await self.mgr.execute_position_rotation()
        assert self.mgr.working is False
        self.mgr.trading_engine.insert_order_cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_filtered_instructions_no_orders(self):
        """指令被过滤（已完成/禁用/已删除/账户不符）时不创建报单"""
        self.mgr.get_today_instructions = MagicMock(
            return_value=[
                make_instruction(id=1, status="COMPLETED"),
                make_instruction(id=2, enabled=False),
                make_instruction(id=3, is_deleted=True),
                make_instruction(id=4, account_id="XX"),
            ]
        )
        await self.mgr.execute_position_rotation(is_manual=True)
        self.mgr.trading_engine.insert_order_cmd.assert_not_called()
        assert self.mgr.working is False

    @pytest.mark.asyncio
    async def test_insert_error_is_caught_and_working_reset(self):
        """插入报单指令抛异常时应记录日志并在 finally 中复位状态"""
        inst = make_instruction(id=1)
        self.mgr.get_today_instructions = MagicMock(return_value=[inst])
        self.mgr._check_instruction = MagicMock(return_value=True)
        self.mgr.trading_engine.insert_order_cmd = MagicMock(side_effect=ValueError("engine down"))
        await self.mgr.execute_position_rotation(is_manual=True)
        assert self.mgr.working is False
        # finally 中仍会持久化指令快照
        self.mgr._update_instructions.assert_called_once()

    @pytest.mark.asyncio
    async def test_price_passthrough(self):
        """指令价格大于 0 时透传给 OrderCmd，为 0 时转 None（市价）"""
        priced = make_instruction(id=1, offset="OPEN", price=3500.5, remaining_volume=1, volume=1)
        market = make_instruction(id=2, offset="OPEN", price=0, remaining_volume=1, volume=1)
        self.mgr.get_today_instructions = MagicMock(return_value=[priced, market])
        self.mgr._check_instruction = MagicMock(return_value=True)
        cmds = []

        def fake_insert(cmd):
            cmds.append(cmd)
            return cmd

        self.mgr.trading_engine.insert_order_cmd = fake_insert
        self.mgr._monitor_order_commands = AsyncMock()
        await self.mgr.execute_position_rotation(is_manual=True)
        assert [c.price for c in cmds] == [3500.5, None]
        assert all(c.source == "换仓:SHFE.rb2509" for c in cmds)

    @pytest.mark.asyncio
    async def test_filled_instruction_marked_completed(self):
        """已成交手数达到目标时应标记 COMPLETED 且不再报单"""
        inst = make_instruction(id=1, volume=2, filled_volume=2, remaining_volume=0)
        self.mgr.get_today_instructions = MagicMock(return_value=[inst])
        await self.mgr.execute_position_rotation(is_manual=True)
        assert inst.status == "COMPLETED"
        self.mgr.trading_engine.insert_order_cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_failed_instruction_skipped(self):
        """不满足执行条件（如时间未到）的指令本轮跳过"""
        inst = make_instruction(id=1)
        self.mgr.get_today_instructions = MagicMock(return_value=[inst])
        self.mgr._check_instruction = MagicMock(return_value=False)
        self.mgr.trading_engine.insert_order_cmd = MagicMock()
        await self.mgr.execute_position_rotation(is_manual=True)
        self.mgr.trading_engine.insert_order_cmd.assert_not_called()
        assert inst.status == "PENDING"

    @pytest.mark.asyncio
    async def test_manual_overrides_order_time_check(self):
        """手动换仓时 is_manual 应透传并跳过时间限制"""
        inst = make_instruction(id=1, order_time="23:59:59")
        self.mgr.get_today_instructions = MagicMock(return_value=[inst])
        self.mgr._monitor_order_commands = AsyncMock()
        self.mgr.trading_engine.insert_order_cmd = lambda cmd: cmd
        await self.mgr.execute_position_rotation(is_manual=True)
        assert inst.status == "RUNNING"
        assert inst.current_order_id is not None
        assert self.mgr.is_manual is True


@pytest.mark.unit
class TestMonitorOrderCommands:
    """_monitor_order_commands 监控循环"""

    def setup_method(self):
        self.mgr = build_manager()
        self.mgr._update_instructions = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_when_no_active_instructions(self):
        """没有 RUNNING 指令时直接返回"""
        inst = make_instruction(id=1, status="PENDING")
        await self.mgr._monitor_order_commands([inst])
        self.mgr.trading_engine.get_order_cmd.assert_not_called()
        self.mgr._update_instructions.assert_not_called()

    @pytest.mark.asyncio
    async def test_marks_completed_on_all_filled(self):
        """全部成交时应标记 COMPLETED 并写库快照"""
        inst = make_instruction(
            id=5,
            status="RUNNING",
            volume=2,
            filled_volume=0,
            remaining_volume=2,
            current_order_id="cmd-1",
        )
        self.mgr.trading_engine.get_order_cmd = MagicMock(
            return_value={
                "remaining_volume": 0,
                "is_active": False,
                "finish_reason": OrderCmdFinishReason.ALL_COMPLETED,
            }
        )
        await self.mgr._monitor_order_commands([inst])
        assert inst.status == "COMPLETED"
        assert inst.filled_volume == 2
        assert inst.remaining_volume == 0
        assert inst.current_order_id is None
        snapshots = self.mgr._update_instructions.call_args[0][0]
        assert snapshots[0]["id"] == 5
        assert snapshots[0]["status"] == "COMPLETED"
        assert snapshots[0]["filled_volume"] == 2

    @pytest.mark.asyncio
    async def test_marks_failed_on_timeout(self):
        """非全部完成的结束原因应标记 FAILED 并记录原因"""
        inst = make_instruction(id=1, status="RUNNING", current_order_id="cmd-1")
        self.mgr.trading_engine.get_order_cmd = MagicMock(
            return_value={
                "remaining_volume": 1,
                "is_active": False,
                "finish_reason": OrderCmdFinishReason.TIMEOUT,
            }
        )
        await self.mgr._monitor_order_commands([inst])
        assert inst.status == "FAILED"
        assert inst.error_message == OrderCmdFinishReason.TIMEOUT

    @pytest.mark.asyncio
    async def test_missing_cmd_keeps_status(self):
        """查不到 OrderCmd 时保持原状态并退出循环"""
        inst = make_instruction(id=1, status="RUNNING", current_order_id="cmd-x")
        self.mgr.trading_engine.get_order_cmd = MagicMock(return_value=None)
        await self.mgr._monitor_order_commands([inst])
        assert inst.status == "RUNNING"

    @pytest.mark.asyncio
    async def test_partial_fill_then_complete(self):
        """部分成交时应持续监控，随后全部完成时结束"""
        inst = make_instruction(
            id=1,
            status="RUNNING",
            volume=2,
            filled_volume=0,
            remaining_volume=2,
            current_order_id="cmd-1",
        )
        self.mgr.trading_engine.get_order_cmd = MagicMock(
            side_effect=[
                {"remaining_volume": 1, "is_active": True, "finish_reason": None},
                {"remaining_volume": 0, "is_active": False, "finish_reason": "ALL_COMPLETED"},
            ]
        )
        with patch("qtrader.trader.switch_mgr.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await self.mgr._monitor_order_commands([inst])
        mock_sleep.assert_awaited_once_with(2.0)
        assert inst.status == "COMPLETED"
        assert inst.filled_volume == 2
        # 每轮循环都会写一次快照
        assert self.mgr._update_instructions.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_request_cancels_cmds(self):
        """收到停止请求时应撤销所有报单指令并复位停止标记"""
        inst = make_instruction(id=1, status="RUNNING", current_order_id="cmd-1")
        self.mgr._stop_requested = True
        self.mgr.trading_engine.cancel_order_cmd = AsyncMock()
        self.mgr.trading_engine.get_order_cmd = MagicMock(
            return_value={
                "remaining_volume": 2,
                "is_active": False,
                "finish_reason": OrderCmdFinishReason.CANCELLED,
            }
        )
        await self.mgr._monitor_order_commands([inst])
        self.mgr.trading_engine.cancel_order_cmd.assert_awaited_once_with("cmd-1")
        assert self.mgr._stop_requested is False
        assert inst.status == "FAILED"


@pytest.mark.unit
class TestCheckInstruction:
    """_check_instruction 执行条件判定"""

    def setup_method(self):
        self.mgr = build_manager()

    def test_disabled_instruction_rejected(self):
        inst = make_instruction(enabled=False)
        assert self.mgr._check_instruction(inst) is False

    def test_completed_instruction_rejected(self):
        inst = make_instruction(status="COMPLETED")
        assert self.mgr._check_instruction(inst) is False

    def test_failed_instruction_rejected(self):
        inst = make_instruction(status="FAILED")
        assert self.mgr._check_instruction(inst) is False

    def test_no_remaining_volume_rejected(self):
        inst = make_instruction(remaining_volume=0)
        assert self.mgr._check_instruction(inst) is False

    def test_future_order_time_rejected_when_not_manual(self):
        """非手动换仓时报单时间未到应拒绝"""
        inst = make_instruction(order_time="23:59:59")
        assert self.mgr._check_instruction(inst, is_manual=False) is False

    def test_past_order_time_allowed_when_not_manual(self):
        """报单时间已过应放行"""
        inst = make_instruction(order_time="00:00:01")
        assert self.mgr._check_instruction(inst, is_manual=False) is True

    def test_manual_ignores_order_time(self):
        """手动换仓时忽略报单时间限制"""
        inst = make_instruction(order_time="23:59:59")
        assert self.mgr._check_instruction(inst, is_manual=True) is True

    def test_default_instruction_allowed(self):
        inst = make_instruction()
        assert self.mgr._check_instruction(inst) is True


@pytest.mark.unit
class TestSnapshotAndUpdateInstructions:
    """_snapshot_instruction / _update_instructions"""

    def test_snapshot_contains_expected_fields(self):
        inst = make_instruction(
            id=9,
            status="RUNNING",
            filled_volume=1,
            remaining_volume=1,
            current_order_id="cmd-9",
            error_message=None,
        )
        snap = SwitchPosManager._snapshot_instruction(inst)
        assert snap["id"] == 9
        assert snap["status"] == "RUNNING"
        assert snap["filled_volume"] == 1
        assert snap["remaining_volume"] == 1
        assert snap["current_order_id"] == "cmd-9"
        assert snap["error_message"] is None
        assert snap["updated_at"] is not None

    async def test_update_empty_snapshots_is_noop(self):
        mgr = build_manager()
        with patch("qtrader.trader.switch_mgr.get_async_session") as mock_scope:
            await mgr._update_instructions([])
        mock_scope.assert_not_called()

    async def test_update_builds_query_without_id(self):
        mgr = build_manager()
        session = async_session()
        snapshots = [{"id": 1, "status": "COMPLETED", "filled_volume": 2}]
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            await mgr._update_instructions(snapshots)
        session.execute.assert_awaited_once()
        params = session.execute.await_args[0][0].compile().params
        assert params["status"] == "COMPLETED"
        assert params["filled_volume"] == 2

    async def test_update_db_error_swallowed(self):
        """写库异常不应向外抛出"""
        mgr = build_manager()
        with patch(
            "qtrader.trader.switch_mgr.get_async_session",
            MagicMock(side_effect=RuntimeError("db down")),
        ):
            await mgr._update_instructions([{"id": 1, "status": "FAILED"}])


@pytest.mark.unit
class TestSwitchMgrEdgeBranches:
    """其余边界分支：必填字段缺失、_on_cmd_changed、_update_instruction"""

    async def test_import_csv_blank_required_field_skipped(self):
        """必填字段（账户/策略/合约）为空时跳过该行"""
        mgr = build_manager()
        mgr.trading_engine.std_symbol = lambda s: s
        mgr.load_rotation_instructions = AsyncMock()
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            result = await mgr.import_csv(
                "account,strategy,symbol,offset,direction,volume\n ,S1,rb2509,Open,Buy,1\n",
                "20260818_DQ.csv",
            )
        assert result["imported"] == 0
        assert result["failed"] == 1

    def test_on_cmd_changed_ignores_unfinished(self):
        """未结束的报单指令不处理"""
        mgr = build_manager()
        mgr._on_cmd_changed(Mock(is_finished=False))

    def test_on_cmd_changed_accepts_finished(self):
        """已结束的报单指令正常处理（当前无后续动作）"""
        mgr = build_manager()
        mgr._on_cmd_changed(Mock(is_finished=True))

    async def test_update_instruction_merges_to_db(self):
        """旧版 _update_instruction 应 merge 入库"""
        mgr = build_manager()
        inst = make_instruction(id=3)
        session = async_session()
        with patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)):
            await mgr._update_instruction(inst)
        session.merge.assert_awaited_once_with(inst)

    async def test_update_instruction_db_error_swallowed(self):
        """旧版 _update_instruction 写库异常不应抛出"""
        mgr = build_manager()
        with patch(
            "qtrader.trader.switch_mgr.get_async_session",
            MagicMock(side_effect=RuntimeError("db down")),
        ):
            await mgr._update_instruction(make_instruction(id=3))

    def test_check_instruction_error_returns_true(self):
        """检查过程抛异常时应返回 True（放行由后续流程兜底）"""

        class BoomInstruction:
            @property
            def enabled(self):
                raise RuntimeError("boom")

        mgr = build_manager()
        assert mgr._check_instruction(BoomInstruction()) is True


@pytest.mark.unit
class TestMonitorOrderCommandsEdge:
    """监控循环边界：无 cmd_id、总超时"""

    def setup_method(self):
        self.mgr = build_manager()
        self.mgr._update_instructions = AsyncMock()

    @pytest.mark.asyncio
    async def test_running_instruction_without_cmd_id_skipped(self):
        """RUNNING 指令缺少 current_order_id 时跳过检查并正常退出"""
        inst = make_instruction(id=1, status="RUNNING", current_order_id=None)
        await self.mgr._monitor_order_commands([inst])
        self.mgr.trading_engine.get_order_cmd.assert_not_called()
        assert inst.status == "RUNNING"

    @pytest.mark.asyncio
    async def test_monitor_exits_on_total_timeout(self):
        """超过总等待时间时应强制退出监控循环"""
        inst = make_instruction(id=1, status="RUNNING", current_order_id="cmd-1")
        self.mgr.trading_engine.get_order_cmd = MagicMock(
            return_value={"remaining_volume": 1, "is_active": True, "finish_reason": None}
        )
        with (
            patch("qtrader.trader.switch_mgr.time.time", side_effect=[1000.0, 5000.0, 5000.0]),
            patch("qtrader.trader.switch_mgr.asyncio.sleep", new_callable=AsyncMock),
        ):
            await self.mgr._monitor_order_commands([inst])
        assert inst.status == "RUNNING"


@pytest.mark.unit
class TestScanAndProcessOrdersEdge:
    """scan_and_process_orders 边界分支"""

    def _make_file(self, tmp_path, name, mtime, content="header\n"):
        """在今日目录下创建一个换仓 CSV 文件并设定修改时间"""
        today = datetime.now().strftime("%Y%m%d")
        today_dir = tmp_path / today
        today_dir.mkdir(exist_ok=True)
        f = today_dir / name
        f.write_text(content, encoding="gbk")
        os.utime(f, (mtime, mtime))
        return f

    def setup_method(self):
        self.mgr = build_manager()
        self.today = datetime.now().strftime("%Y%m%d")

    async def test_scan_no_directory_returns(self, tmp_path):
        """目录不存在时直接返回"""
        self.mgr.switchPos_files_dir = str(tmp_path / "missing")
        self.mgr.import_csv = AsyncMock()
        with patch("qtrader.trader.switch_mgr.get_async_session"):
            await self.mgr.scan_and_process_orders()
        self.mgr.import_csv.assert_not_called()

    async def test_scan_all_files_fresh_returns(self, tmp_path):
        """全部文件均为新写入时不导入"""
        self.mgr.switchPos_files_dir = str(tmp_path)
        self.mgr.import_csv = AsyncMock()
        self._make_file(tmp_path, f"{self.today}_DQ_fresh.csv", time.time())
        with patch("qtrader.trader.switch_mgr.get_async_session"):
            await self.mgr.scan_and_process_orders()
        self.mgr.import_csv.assert_not_called()

    async def test_scan_skips_already_imported_file(self, tmp_path):
        """已导入过的文件不再导入"""
        self.mgr.switchPos_files_dir = str(tmp_path)
        self.mgr.import_csv = AsyncMock()
        self._make_file(tmp_path, f"{self.today}_DQ_done.csv", time.time() - 100)
        session = MagicMock()
        with (
            patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)),
            patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=Mock())),
        ):
            await self.mgr.scan_and_process_orders()
        self.mgr.import_csv.assert_not_called()
        session.add.assert_not_called()

    async def test_scan_unreadable_file_skipped(self, tmp_path):
        """读取文件失败（编码错误）时跳过且不写导入记录"""
        self.mgr.switchPos_files_dir = str(tmp_path)
        self.mgr.import_csv = AsyncMock()
        f = self._make_file(tmp_path, f"{self.today}_DQ_bad.csv", time.time() - 100)
        # 写入无法用 gbk 解码的内容，并回设稳定修改时间
        f.write_bytes(b"\xff\x00\xff\x00")
        old = time.time() - 100
        os.utime(f, (old, old))
        session = MagicMock()
        with (
            patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)),
            patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        ):
            await self.mgr.scan_and_process_orders()
        self.mgr.import_csv.assert_not_called()
        session.add.assert_not_called()

    async def test_scan_import_failure_not_recorded(self, tmp_path):
        """导入失败时不写导入记录（下轮重试）"""
        self.mgr.switchPos_files_dir = str(tmp_path)
        self.mgr.import_csv = AsyncMock(side_effect=ValueError("bad csv"))
        self._make_file(tmp_path, f"{self.today}_DQ_err.csv", time.time() - 100)
        session = MagicMock()
        with (
            patch("qtrader.trader.switch_mgr.get_async_session", scope_with(session)),
            patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        ):
            await self.mgr.scan_and_process_orders()
        session.add.assert_not_called()

    async def test_scan_session_error_swallowed(self, tmp_path):
        """会话异常由外层捕获，不向外抛出"""
        self.mgr.switchPos_files_dir = str(tmp_path)
        self.mgr.import_csv = AsyncMock()
        self._make_file(tmp_path, f"{self.today}_DQ_x.csv", time.time() - 100)
        with patch(
            "qtrader.trader.switch_mgr.get_async_session",
            MagicMock(side_effect=RuntimeError("db down")),
        ):
            await self.mgr.scan_and_process_orders()
