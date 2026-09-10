"""
TraderReqHandler 策略与换仓请求单元测试

覆盖 test_trader_req.py 未触及的处理器块：策略列表/详情/参数/信号/持仓调整/
启停/初始化/报单指令，以及换仓指令的查询与操作。全部基于 mock，不经过 IPC。
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.models.object import PositionData
from qtrader.trader.req import TraderReqHandler


def make_strat_pos(symbol: str = "IM2603"):
    """策略持仓视图对象（duck-typed）"""
    return SimpleNamespace(
        symbol=symbol,
        pos=2,
        total_pos=2,
        pos_long=2,
        pos_long_td=2,
        pos_long_yd=0,
        pos_short=0,
        pos_short_td=0,
        pos_short_yd=0,
        hold_price_long=3800.0,
        hold_price_short=0.0,
        close_profit_long=0.0,
        close_profit_short=0.0,
        multiple=10,
    )


def make_strategy(strategy_id: str = "rsi_001") -> MagicMock:
    s = MagicMock()
    s.strategy_id = strategy_id
    s.enabled = True
    s.opening_paused = False
    s.closing_paused = False
    s.inited = True
    s.symbol = "IM2603"
    s.config = MagicMock()
    s.config.model_dump.return_value = {"symbol": "IM2603", "type": "rsi"}
    # symbol 属 BaseParam 基础字段，custom_k 属扩展字段
    s.get_params.return_value = [
        {"key": "symbol", "label": "合约", "type": "string", "value": "IM2603"},
        {"key": "custom_k", "label": "自定义", "type": "int", "value": 5},
    ]
    s.get_all_positions.return_value = {"IM2603": make_strat_pos()}
    s.get_position.return_value = make_strat_pos()
    s.get_signal.return_value = {"side": 1}
    s.get_trading_status.return_value = "RUNNING"
    s.send_order_cmds = AsyncMock()
    return s


def make_instruction(
    ins_id: int = 1, status: str = "RUNNING", current_order_id: str | None = "cmd_1"
):
    """换仓指令视图对象（duck-typed RotationInstructionPo）"""
    return SimpleNamespace(
        id=ins_id,
        account_id="test_account_001",
        strategy_id="rsi_001",
        symbol="IM2603",
        offset="CLOSETODAY",
        direction="SELL",
        volume=2,
        filled_volume=1,
        price=3900.0,
        order_time="09:31:00",
        trading_date="2026-09-04",
        enabled=True,
        status=status,
        attempt_count=1,
        remaining_attempts=4,
        remaining_volume=1,
        current_order_id=current_order_id,
        order_placed_time=datetime(2026, 9, 4, 9, 31),
        last_attempt_time=None,
        error_message="",
        source="csv",
        created_at=datetime(2026, 9, 4, 9, 0),
        updated_at=datetime(2026, 9, 4, 9, 31),
    )


@pytest.fixture
def mock_trader() -> MagicMock:
    t = MagicMock()
    t.account_id = "test_account_001"
    t.trading_engine = None
    t.strategy_manager = None
    t.switchPos_manager = None
    return t


@pytest.fixture
def handler(mock_trader) -> TraderReqHandler:
    return TraderReqHandler(mock_trader)


def with_strategy(mock_trader, strategy: MagicMock) -> MagicMock:
    """装配 strategy_manager + 引擎（含行情），返回引擎 mock"""
    engine = MagicMock()
    engine.account_id = "test_account_001"
    engine.quotes = {"IM2603": SimpleNamespace(last_price=4000.0)}
    engine.positions = {
        "IM2603": PositionData(symbol="IM2603", exchange="CFFEX", pos_long_td=5, pos_long_yd=1)
    }
    sm = MagicMock()
    sm.strategies = {strategy.strategy_id: strategy}
    sm.replay_all_strategies = AsyncMock(return_value={"success": True, "replayed_count": 1})
    sm.init_strategy = AsyncMock()
    mock_trader.trading_engine = engine
    mock_trader.strategy_manager = sm
    return engine


@pytest.mark.unit
class TestListStrategies:
    """策略列表"""

    @pytest.mark.asyncio
    async def test_no_strategy_manager(self, mock_trader, handler):
        assert await handler._req_list_strategies({}) == []

    @pytest.mark.asyncio
    async def test_full_structure(self, mock_trader, handler):
        s = make_strategy()
        with_strategy(mock_trader, s)

        result = await handler._req_list_strategies({})

        assert len(result) == 1
        item = result[0]
        assert item["strategy_id"] == "rsi_001"
        assert item["symbol"] == "IM2603"
        assert item["pos_long"] == 2
        # 基础/扩展参数拆分
        keys_base = [p["key"] for p in item["base_params"]]
        keys_ext = [p["key"] for p in item["ext_params"]]
        assert "symbol" in keys_base
        assert keys_ext == ["custom_k"]
        # 有持仓的合约进入列表，盈亏 = (4000-3800)*2*10
        assert item["positions"][0]["position_profit"] == pytest.approx(4000.0)

    @pytest.mark.asyncio
    async def test_zero_position_filtered(self, mock_trader, handler):
        s = make_strategy()
        pos = make_strat_pos()
        pos.total_pos = 0
        s.get_all_positions.return_value = {"IM2603": pos}
        with_strategy(mock_trader, s)

        result = await handler._req_list_strategies({})

        assert result[0]["positions"] == []
        assert result[0]["pos_long"] == 0


@pytest.mark.unit
class TestGetStrategy:
    """策略详情"""

    @pytest.mark.asyncio
    async def test_no_strategy_manager(self, handler):
        assert await handler._req_get_strategy({"strategy_id": "rsi_001"}) is None

    @pytest.mark.asyncio
    async def test_found(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())

        result = await handler._req_get_strategy({"strategy_id": "rsi_001"})

        assert result is not None
        assert result["strategy_id"] == "rsi_001"
        assert result["trading_status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_missing(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())
        assert await handler._req_get_strategy({"strategy_id": "ghost"}) is None


@pytest.mark.unit
class TestReplayAllStrategies:
    """回播全部策略"""

    @pytest.mark.asyncio
    async def test_no_strategy_manager(self, handler):
        result = await handler._req_replay_all_strategies({})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_success(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())

        result = await handler._req_replay_all_strategies({})

        assert result["success"] is True
        assert result["replayed_count"] == 1
        mock_trader.strategy_manager.replay_all_strategies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_result(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())
        mock_trader.strategy_manager.replay_all_strategies = AsyncMock(
            return_value={"success": False, "message": "无历史数据"}
        )

        result = await handler._req_replay_all_strategies({})

        assert result["success"] is False
        assert "无历史数据" in result["message"]

    @pytest.mark.asyncio
    async def test_exception(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())
        mock_trader.strategy_manager.replay_all_strategies = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        result = await handler._req_replay_all_strategies({})

        assert result["success"] is False
        assert "boom" in result["message"]


@pytest.mark.unit
class TestStrategyParamSignal:
    """参数更新 / 信号更新 / 信号清除（同一套守卫）"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method",
        [
            "_req_update_strategy_params",
            "_req_update_strategy_signal",
            "_req_clear_strategy_signal",
        ],
    )
    async def test_guards(self, mock_trader, handler, method):
        call = getattr(handler, method)
        # 无策略管理器
        r = await call({"strategy_id": "rsi_001"})
        assert r["success"] is False and "策略管理器" in r["message"]
        # 无引擎
        mock_trader.strategy_manager = MagicMock()
        r = await call({"strategy_id": "rsi_001"})
        assert r["success"] is False and "交易引擎" in r["message"]
        # 缺少 strategy_id
        with_strategy(mock_trader, make_strategy())
        r = await call({})
        assert r["success"] is False and "strategy_id" in r["message"]
        # 策略不存在
        r = await call({"strategy_id": "ghost"})
        assert r["success"] is False and "不存在" in r["message"]

    @pytest.mark.asyncio
    async def test_update_params_success(self, mock_trader, handler):
        s = make_strategy()
        s.update_params = Mock()
        with_strategy(mock_trader, s)

        r = await handler._req_update_strategy_params(
            {"strategy_id": "rsi_001", "params": {"volume": 3}}
        )

        assert r["success"] is True
        s.update_params.assert_called_once_with({"volume": 3})

    @pytest.mark.asyncio
    async def test_update_signal_success(self, mock_trader, handler):
        s = make_strategy()
        s.update_signal = Mock()
        with_strategy(mock_trader, s)

        r = await handler._req_update_strategy_signal(
            {"strategy_id": "rsi_001", "signal": {"side": -1}}
        )

        assert r["success"] is True
        s.update_signal.assert_called_once_with({"side": -1})

    @pytest.mark.asyncio
    async def test_clear_signal_success(self, mock_trader, handler):
        s = make_strategy()
        s.clear_signal = Mock()
        with_strategy(mock_trader, s)

        r = await handler._req_clear_strategy_signal({"strategy_id": "rsi_001"})

        assert r["success"] is True
        s.clear_signal.assert_called_once()


@pytest.mark.unit
class TestUpdateStrategyPositionDetail:
    """策略持仓手工调整（含账户持仓上限校验）"""

    @pytest.mark.asyncio
    async def test_missing_symbol(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())

        r = await handler._req_update_strategy_position_detail(
            {"strategy_id": "rsi_001", "position": {"pos_long_td": 1}}
        )

        assert r["success"] is False
        assert "合约代码" in r["message"]

    @pytest.mark.asyncio
    async def test_exceeds_account_position(self, mock_trader, handler):
        # 账户 IM2603 今多 5 手，请求 6 手应被拒
        with_strategy(mock_trader, make_strategy())

        r = await handler._req_update_strategy_position_detail(
            {
                "strategy_id": "rsi_001",
                "position": {"symbol": "IM2603", "pos_long_td": 6},
            }
        )

        assert r["success"] is False
        assert "不能超过" in r["message"]

    @pytest.mark.asyncio
    async def test_account_has_no_position(self, mock_trader, handler):
        engine = with_strategy(mock_trader, make_strategy())
        engine.positions = {}

        r = await handler._req_update_strategy_position_detail(
            {
                "strategy_id": "rsi_001",
                "position": {"symbol": "IM2603", "pos_long_td": 1},
            }
        )

        assert r["success"] is False
        assert "无法设置策略持仓" in r["message"]

    @pytest.mark.asyncio
    async def test_success_within_limit(self, mock_trader, handler):
        s = make_strategy()
        holder = SimpleNamespace(pos_long=0, pos_short=0)  # logger 会读取派生字段
        s._get_or_create_position = Mock(return_value=holder)
        s.save_positions = Mock()
        with_strategy(mock_trader, s)

        r = await handler._req_update_strategy_position_detail(
            {
                "strategy_id": "rsi_001",
                "position": {
                    "symbol": "IM2603",
                    "pos_long_td": 2,
                    "pos_long_yd": 1,
                    "hold_price_long": 3850.0,
                },
            }
        )

        assert r["success"] is True
        assert holder.pos_long_td == 2
        assert holder.pos_long_yd == 1
        assert holder.hold_price_long == 3850.0
        s.save_positions.assert_called_once()


@pytest.mark.unit
class TestDeleteStrategyPosition:
    """删除策略持仓"""

    @pytest.mark.asyncio
    async def test_missing_symbol(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())

        r = await handler._req_delete_strategy_position({"strategy_id": "rsi_001"})

        assert r["success"] is False
        assert "合约代码" in r["message"]

    @pytest.mark.asyncio
    async def test_success_clears_db(self, mock_trader, handler):
        s = make_strategy()
        s._positions = {"IM2603": make_strat_pos()}
        engine = with_strategy(mock_trader, s)
        # strategy.strategy_manager 链路存在 → 走 DB 清理
        s.strategy_manager = MagicMock()
        s.strategy_manager.trading_engine = engine
        with patch("qtrader.trader.dao.position_dao.StrategyPositionService") as svc_cls:
            svc = svc_cls.return_value

            r = await handler._req_delete_strategy_position(
                {"strategy_id": "rsi_001", "symbol": "IM2603"}
            )

            assert r["success"] is True
            assert "IM2603" not in s._positions
            svc.clear_position.assert_called_once_with("test_account_001", "rsi_001", "IM2603")

    @pytest.mark.asyncio
    async def test_success_without_strategy_manager(self, mock_trader, handler):
        s = make_strategy()
        s._positions = {"IM2603": make_strat_pos()}
        s.strategy_manager = None
        with_strategy(mock_trader, s)

        r = await handler._req_delete_strategy_position(
            {"strategy_id": "rsi_001", "symbol": "IM2603"}
        )

        assert r["success"] is True
        assert "IM2603" not in s._positions


@pytest.mark.unit
class TestStrategySwitches:
    """启停/交易状态/初始化"""

    @pytest.mark.asyncio
    async def test_set_trading_status_both(self, mock_trader, handler):
        s = make_strategy()
        with_strategy(mock_trader, s)

        r = await handler._req_set_strategy_trading_status(
            {"strategy_id": "rsi_001", "status": {"opening_paused": True, "closing_paused": True}}
        )

        assert r["success"] is True
        assert r["data"] == {"opening_paused": True, "closing_paused": True}
        s.set_opening_paused.assert_called_once_with(True)
        s.set_closing_paused.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_enable_and_disable(self, mock_trader, handler):
        s = make_strategy()
        with_strategy(mock_trader, s)

        assert (await handler._req_enable_strategy({"strategy_id": "rsi_001"}))["success"] is True
        s.enable.assert_called_once_with()

        assert (await handler._req_disable_strategy({"strategy_id": "rsi_001"}))["success"] is True
        s.enable.assert_called_with(False)

    @pytest.mark.asyncio
    async def test_init_strategy(self, mock_trader, handler):
        s = make_strategy()
        with_strategy(mock_trader, s)

        r = await handler._req_init_strategy({"strategy_id": "rsi_001"})

        assert r["success"] is True
        mock_trader.strategy_manager.init_strategy.assert_awaited_once_with(s)

    @pytest.mark.asyncio
    async def test_init_strategy_not_found(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())

        r = await handler._req_init_strategy({"strategy_id": "ghost"})

        assert r["success"] is False


@pytest.mark.unit
class TestStrategyOrderCmds:
    """策略报单指令查询与下发"""

    @pytest.mark.asyncio
    async def test_no_engine(self, mock_trader, handler):
        assert await handler._req_get_strategy_order_cmds({"strategy_id": "rsi_001"}) == []

    @pytest.mark.asyncio
    async def test_no_executor(self, mock_trader, handler):
        engine = with_strategy(mock_trader, make_strategy())
        engine._order_cmd_executor = None

        assert await handler._req_get_strategy_order_cmds({"strategy_id": "rsi_001"}) == []

    @pytest.mark.asyncio
    async def test_filters_by_source_and_status(self, mock_trader, handler):
        engine = with_strategy(mock_trader, make_strategy())
        engine._order_cmd_executor = MagicMock()
        engine._order_cmd_executor.get_hist_cmds.return_value = {
            "c1": SimpleNamespace(
                source="策略-rsi_001-1",
                is_active=True,
                is_finished=False,
                to_dict=lambda: {"cmd_id": "c1"},
            ),
            "c2": SimpleNamespace(
                source="策略-rsi_001-2",
                is_active=False,
                is_finished=True,
                to_dict=lambda: {"cmd_id": "c2"},
            ),
            "c3": SimpleNamespace(
                source="手动-xxx",
                is_active=True,
                is_finished=False,
                to_dict=lambda: {"cmd_id": "c3"},
            ),
        }

        all_cmds = await handler._req_get_strategy_order_cmds({"strategy_id": "rsi_001"})
        assert [c["cmd_id"] for c in all_cmds] == ["c1", "c2"]

        active = await handler._req_get_strategy_order_cmds(
            {"strategy_id": "rsi_001", "status": "active"}
        )
        assert [c["cmd_id"] for c in active] == ["c1"]

    @pytest.mark.asyncio
    async def test_send_strategy_order_cmd_success(self, mock_trader, handler):
        s = make_strategy()
        with_strategy(mock_trader, s)

        r = await handler._req_send_strategy_order_cmd(
            {
                "strategy_id": "rsi_001",
                "order_cmd": {
                    "symbol": "IM2603",
                    "direction": "BUY",
                    "offset": "OPEN",
                    "volume": 1,
                    "price": 3900,
                },
            }
        )

        assert r["success"] is True
        assert r["cmd_id"]
        s.send_order_cmds.assert_awaited_once()
        sent = s.send_order_cmds.await_args.args[0][0]
        assert sent.symbol == "IM2603"
        assert sent.volume_per_order == 5  # OrderCmd 默认拆分手数

    @pytest.mark.asyncio
    async def test_send_strategy_order_cmd_missing(self, mock_trader, handler):
        with_strategy(mock_trader, make_strategy())

        r = await handler._req_send_strategy_order_cmd({"strategy_id": "rsi_001"})

        assert r["success"] is False
        assert "order_cmd" in r["message"]

    @pytest.mark.asyncio
    async def test_send_order_cmd_uses_risk_split_volume(self, mock_trader, handler):
        engine = with_strategy(mock_trader, make_strategy())
        engine.risk_control = MagicMock()
        engine.risk_control.config = SimpleNamespace(max_split_volume=7)
        engine.insert_order_cmd = Mock()

        r = await handler._req_send_order_cmd(
            {
                "order_cmd": {
                    "symbol": "IM2603",
                    "direction": "SELL",
                    "offset": "CLOSETODAY",
                    "volume": 3,
                }
            }
        )

        assert r["success"] is True
        cmd = engine.insert_order_cmd.call_args[0][0]
        assert cmd.volume_per_order == 7  # 风控拆分手数生效
        assert cmd.source == "手动报单"  # 未显式传 source 时默认手动报单

    @pytest.mark.asyncio
    async def test_send_order_cmd_no_engine(self, mock_trader, handler):
        r = await handler._req_send_order_cmd({"order_cmd": {"symbol": "IM2603"}})
        assert r["success"] is False


@pytest.mark.unit
class TestRotationHandlers:
    """换仓指令查询与操作"""

    @pytest.mark.asyncio
    async def test_get_instructions_without_manager(self, handler):
        result = await handler._req_get_rotation_instructions({})
        assert result == {
            "instructions": [],
            "rotation_status": {"working": False, "is_manual": False},
        }

    @pytest.mark.asyncio
    async def test_get_instructions_with_pending_volume(self, mock_trader, handler):
        spm = MagicMock()
        spm.working = True
        spm.is_manual = False
        spm.get_today_instructions.return_value = [
            make_instruction(status="RUNNING", current_order_id="cmd_1"),
            make_instruction(ins_id=2, status="FINISHED", current_order_id=None),
        ]
        mock_trader.switchPos_manager = spm
        engine = MagicMock()
        engine.get_order_cmd.return_value = {"pending_volume": 1}
        mock_trader.trading_engine = engine

        result = await handler._req_get_rotation_instructions({})

        assert result["rotation_status"] == {"working": True, "is_manual": False}
        assert len(result["instructions"]) == 2
        running = result["instructions"][0]
        assert running["pending_volume"] == 1
        assert running["order_placed_time"] == "2026-09-04T09:31:00"
        # FINISHED 且无挂单 → pending 0
        assert result["instructions"][1]["pending_volume"] == 0

    @pytest.mark.asyncio
    async def test_get_instruction_not_found(self, mock_trader, handler):
        spm = MagicMock()
        spm.get_today_instructions.return_value = []
        mock_trader.switchPos_manager = spm

        assert await handler._req_get_rotation_instruction({"instruction_id": 99}) is None

    @pytest.mark.asyncio
    async def test_get_instruction_found(self, mock_trader, handler):
        spm = MagicMock()
        spm.get_today_instructions.return_value = [make_instruction(ins_id=1)]
        mock_trader.switchPos_manager = spm

        result = await handler._req_get_rotation_instruction({"instruction_id": 1})

        assert result is not None
        assert result["id"] == 1
        assert result["strategy_id"] == "rsi_001"

    @pytest.mark.asyncio
    async def test_update_instruction(self, mock_trader, handler):
        spm = MagicMock()
        spm.update_instruction.return_value = "po_obj"
        mock_trader.switchPos_manager = spm

        r = await handler._req_update_rotation_instruction(
            {"instruction_id": 1, "status": "CANCELLED"}
        )

        assert r == "po_obj"
        spm.update_instruction.assert_called_once_with({"instruction_id": 1, "status": "CANCELLED"})

    @pytest.mark.asyncio
    async def test_import_csv(self, mock_trader, handler):
        spm = MagicMock()
        spm.import_csv.return_value = {"imported": 2, "skipped": 0, "errors": []}
        mock_trader.switchPos_manager = spm

        r = await handler._req_import_rotation_instructions(
            {"csv_text": "a,b", "filename": "x.csv", "mode": "append"}
        )

        assert r["imported"] == 2
        spm.import_csv.assert_called_once_with("a,b", "x.csv", "append")

    @pytest.mark.asyncio
    async def test_import_csv_without_manager(self, handler):
        r = await handler._req_import_rotation_instructions({"csv_text": "a", "filename": "x.csv"})
        assert r == {"imported": 0, "skipped": 0, "errors": []}

    @pytest.mark.asyncio
    async def test_execute_rotation(self, mock_trader, handler):
        spm = MagicMock()
        spm.execute_position_rotation = AsyncMock()
        mock_trader.switchPos_manager = spm

        assert await handler._req_execute_rotation({}) is True
        # 后台任务跑一轮
        await asyncio.sleep(0)
        spm.execute_position_rotation.assert_awaited_once_with(is_manual=True)

    @pytest.mark.asyncio
    async def test_execute_rotation_without_manager(self, handler):
        assert await handler._req_execute_rotation({}) is False

    @pytest.mark.asyncio
    async def test_stop_rotation(self, mock_trader, handler):
        spm = MagicMock()
        mock_trader.switchPos_manager = spm

        assert await handler._req_stop_rotation({}) is True
        spm.stop_rotation.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_rotation_without_manager(self, handler):
        assert await handler._req_stop_rotation({}) is False

    @pytest.mark.asyncio
    async def test_batch_delete_without_manager(self, handler):
        assert await handler._req_batch_delete_instructions({"ids": [1, 2]}) == {"deleted": 0}
