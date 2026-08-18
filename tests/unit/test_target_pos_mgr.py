"""
TargetPosManager 单元测试

覆盖：
- CSV 解析（strategy/stragegy 表头、账户过滤、非法行）
- 差值计算（开仓/减仓/平仓、多空同列锁仓、差值为0生成COMPLETED跟踪行、先平后开顺序）
- 执行防重复（RUNNING 且报单仍活跃 → 不重复创建 OrderCmd）
- N/D 盘次文件名兼容与交易日口径（网关交易日，夜盘为次一交易日）
- 页面导入记录 file_path（与扫描导入一致）且强制重算（不受文件级幂等限制）
"""

import asyncio
import hashlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import qtrader.trader.target_pos_mgr as tpm
from qtrader.trader.target_pos_mgr import TargetPosManager


def build_manager(account_id: str = "DQ") -> TargetPosManager:
    """构造一个不依赖数据库/配置文件的 TargetPosManager"""
    mgr = TargetPosManager.__new__(TargetPosManager)
    mgr.account_id = account_id
    mgr.config = MagicMock()
    te = MagicMock()
    te.std_symbol = lambda s: s  # 测试中不改变合约名
    mgr.trading_engine = te
    mgr._position_service = MagicMock()
    mgr.working = False
    mgr.is_manual = False
    mgr._stop_requested = False
    mgr.target_pos_dir = ""
    return mgr


# ==================== CSV 解析 ====================


def test_parse_csv_accepts_both_headers():
    mgr = build_manager()
    csv_text = (
        "account,stragegy,symbol,direction,volume\n"
        "DQ,StrategyFix_A,A2611,Sell,2\n"
        "DQ,StrategyFix_B,AL2609,Buy,6\n"
    )
    rows = mgr._parse_csv(csv_text)
    assert len(rows) == 2
    assert rows[0] == {
        "strategy_id": "StrategyFix_A",
        "symbol": "A2611",
        "direction": "SELL",
        "volume": 2,
    }
    assert rows[1]["direction"] == "BUY"


def test_parse_csv_filters_other_account_and_bad_direction():
    mgr = build_manager()
    csv_text = (
        "account,strategy,symbol,direction,volume\n"
        "RF,StrategyFix_A,A2611,Buy,2\n"  # 其他账户 → 跳过
        "DQ,StrategyFix_B,AL2609,Up,6\n"  # 非法方向 → 跳过
        "DQ,StrategyFix_C,AG2605,Buy,3\n"
    )
    rows = mgr._parse_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "StrategyFix_C"


# ==================== 差值计算 ====================


def make_position(long_vol: int = 0, short_vol: int = 0):
    pos = MagicMock()
    pos.pos_long = long_vol
    pos.pos_short = short_vol
    return pos


def compute(mgr, rows, current_map):
    """用 current_map(symbol->position) 替代账户持仓查询"""

    def fake_get(symbol):
        return current_map.get(symbol)

    mgr._get_account_position = fake_get
    return mgr._compute_instructions(rows, "20260811", "plan-1", "TargetPos-DQ.csv")


def test_compute_open_long_and_short_from_zero():
    mgr = build_manager()
    rows = [
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 5},
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "SELL", "volume": 6},
    ]
    instructions = compute(mgr, rows, {})
    by_side = {i.side: i for i in instructions}
    assert by_side["LONG"].offset == "OPEN" and by_side["LONG"].direction == "BUY"
    assert by_side["LONG"].volume == 5
    assert by_side["SHORT"].offset == "OPEN" and by_side["SHORT"].direction == "SELL"
    assert by_side["SHORT"].volume == 6


def test_compute_only_adjust_specified_side():
    """用户场景：账户 rb2609 持 6多+6空，目标文件只有 Buy 3 → 仅平3手多，空头不动"""
    mgr = build_manager()
    rows = [{"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 3}]
    instructions = compute(mgr, rows, {"rb2609": make_position(long_vol=6, short_vol=6)})
    # 仅多头侧：目标3、当前6 → 平多3；空头侧未在文件中出现 → 不操作
    assert len(instructions) == 1
    inst = instructions[0]
    assert inst.side == "LONG" and inst.offset == "CLOSE" and inst.direction == "SELL"
    assert inst.volume == 3


def test_compute_close_when_target_zero_and_position_exists():
    """明确写出某侧目标0才会平掉该侧"""
    mgr = build_manager()
    # 文件显式给空头目标 3，且显式给多头目标 0（平多）；当前多头 5、空头 0
    rows = [
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "SELL", "volume": 3},
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 0},
    ]
    instructions = compute(mgr, rows, {"rb2609": make_position(long_vol=5)})
    by_side = {i.side: i for i in instructions}
    # 多头显式目标 0、当前 5 → 平多 5
    assert by_side["LONG"].offset == "CLOSE" and by_side["LONG"].direction == "SELL"
    assert by_side["LONG"].volume == 5
    # 空头目标 3、当前 0 → 开空 3
    assert by_side["SHORT"].offset == "OPEN" and by_side["SHORT"].direction == "SELL"
    assert by_side["SHORT"].volume == 3


def test_compute_reduce_side():
    mgr = build_manager()
    # 目标多头 2、当前多头 5 → 平多 3
    rows = [{"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 2}]
    instructions = compute(mgr, rows, {"rb2609": make_position(long_vol=5)})
    assert len(instructions) == 1
    inst = instructions[0]
    assert inst.side == "LONG" and inst.offset == "CLOSE" and inst.direction == "SELL"
    assert inst.volume == 3


def test_compute_zero_diff_creates_completed_tracking_row():
    """目标已到位（差值0）仍生成跟踪行：volume=0、COMPLETED，重复导入不再生成 0 条"""
    mgr = build_manager()
    rows = [{"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 5}]
    instructions = compute(mgr, rows, {"rb2609": make_position(long_vol=5)})
    assert len(instructions) == 1
    inst = instructions[0]
    assert inst.status == "COMPLETED"
    assert inst.volume == 0
    assert inst.remaining_volume == 0
    assert inst.target_volume == 5


def test_compute_close_before_open_order():
    mgr = build_manager()
    # 两侧均显式指定：多头目标5(开多3)、空头目标3(平空2)；当前多2空5
    rows = [
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 5},
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "SELL", "volume": 3},
    ]
    instructions = compute(mgr, rows, {"rb2609": make_position(long_vol=2, short_vol=5)})
    offsets = [i.offset for i in instructions]
    # CLOSE 应排在 OPEN 之前
    assert offsets.index("CLOSE") < offsets.index("OPEN")


def test_compute_account_level_grouping_across_strategies():
    """strategy_id 仅作显示：同 symbol 多策略行合并到账户级差值"""
    mgr = build_manager()
    rows = [
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 2},
        {"strategy_id": "S2", "symbol": "rb2609", "direction": "BUY", "volume": 3},
    ]
    instructions = compute(mgr, rows, {"rb2609": make_position(long_vol=0)})
    # 合并目标多头 5、当前 0 → 一条开多5指令；strategy_id 为两个策略拼接
    assert len(instructions) == 1
    inst = instructions[0]
    assert inst.side == "LONG" and inst.offset == "OPEN" and inst.volume == 5
    assert set(inst.strategy_id.split(",")) == {"S1", "S2"}


def test_compute_instruction_key_unique():
    mgr = build_manager()
    rows = [
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 5},
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "SELL", "volume": 6},
    ]
    instructions = compute(mgr, rows, {})
    keys = [i.instruction_key for i in instructions]
    assert len(keys) == len(set(keys))


# ==================== 执行防重复 ====================


def test_execute_skips_running_with_active_cmd() -> None:
    mgr = build_manager()
    inst = SimpleNamespace(
        id=1,
        status="RUNNING",
        current_order_id="cmd-1",
        filled_volume=0,
        volume=5,
        remaining_volume=5,
        direction="BUY",
        offset="OPEN",
        side="LONG",
        enabled=True,
        symbol="rb2609",
        price=0,
        strategy_id="S1",
        error_message=None,
        order_placed_time=None,
    )
    mgr._load_today_instructions = lambda: [inst]
    mgr._is_cmd_active = lambda cid: True
    mgr._update_instructions = lambda x: None

    launched = []

    async def fake_launch(i):
        launched.append(i)

    async def fake_monitor(i_list):
        return None

    mgr._launch_order_cmd = fake_launch
    mgr._monitor_order_commands = fake_monitor

    asyncio.run(mgr.execute_target_position(is_manual=False))
    assert launched == []  # 活跃报单存在 → 不重复创建
    assert inst.status == "RUNNING"


def test_execute_launches_pending_instruction() -> None:
    mgr = build_manager()
    inst = SimpleNamespace(
        id=1,
        status="PENDING",
        current_order_id=None,
        filled_volume=0,
        volume=5,
        remaining_volume=5,
        direction="BUY",
        offset="OPEN",
        side="LONG",
        target_volume=5,
        enabled=True,
        symbol="rb2609",
        price=0,
        strategy_id="S1",
        error_message=None,
        order_placed_time=None,
    )
    mgr._load_today_instructions = lambda: [inst]
    mgr._is_cmd_active = lambda cid: False
    mgr._update_instructions = lambda x: None
    # 重算差值时按当前持仓(这里 0)计算，确保 diff>0 走开仓分支
    mgr._side_position_volume = lambda symbol, side: 0

    launched = []

    async def fake_launch(i):
        launched.append(i)
        i.status = "RUNNING"

    async def fake_monitor(i_list):
        return None

    mgr._launch_order_cmd = fake_launch
    mgr._monitor_order_commands = fake_monitor

    asyncio.run(mgr.execute_target_position(is_manual=False))
    assert len(launched) == 1


def test_execute_recalculates_deviation_on_start() -> None:
    """点开始换仓时按当前实时持仓重算差值，刷新换仓前偏差(volume)。"""
    mgr = build_manager()
    # 导入时按持仓 7 算出平 6 手(volume=6)；点击时持仓已变为 3
    inst = SimpleNamespace(
        id=1,
        status="PENDING",
        current_order_id=None,
        filled_volume=0,
        volume=6,
        remaining_volume=6,
        direction="SELL",
        offset="CLOSE",
        side="LONG",
        target_volume=1,
        enabled=True,
        symbol="a2611",
        price=0,
        strategy_id="S1",
        error_message=None,
        order_placed_time=None,
    )
    mgr._load_today_instructions = lambda: [inst]
    mgr._is_cmd_active = lambda cid: False
    mgr._update_instructions = lambda x: None
    mgr._side_position_volume = lambda symbol, side: 3  # 点击时刻实时持仓

    launched = []

    async def fake_launch(i):
        launched.append(i)

    async def fake_monitor(i_list):
        return None

    mgr._launch_order_cmd = fake_launch
    mgr._monitor_order_commands = fake_monitor

    asyncio.run(mgr.execute_target_position(is_manual=False))
    # 重算：目标 1 - 持仓 3 = -2 → 平 2 手
    assert len(launched) == 1
    assert inst.volume == 2
    assert inst.offset == "CLOSE"
    assert inst.direction == "SELL"
    assert inst.remaining_volume == 2
    assert inst.filled_volume == 0


def test_execute_marks_completed_when_already_at_target() -> None:
    """点击时持仓已到目标，重算 diff=0，标记完成不下单。"""
    mgr = build_manager()
    inst = SimpleNamespace(
        id=1,
        status="PENDING",
        current_order_id=None,
        filled_volume=0,
        volume=2,
        remaining_volume=2,
        direction="SELL",
        offset="CLOSE",
        side="LONG",
        target_volume=1,
        enabled=True,
        symbol="a2611",
        price=0,
        strategy_id="S1",
        error_message=None,
        order_placed_time=None,
    )
    mgr._load_today_instructions = lambda: [inst]
    mgr._is_cmd_active = lambda cid: False
    mgr._update_instructions = lambda x: None
    mgr._side_position_volume = lambda symbol, side: 1  # 持仓 = 目标 = 1

    launched = []

    async def fake_launch(i):
        launched.append(i)

    async def fake_monitor(i_list):
        return None

    mgr._launch_order_cmd = fake_launch
    mgr._monitor_order_commands = fake_monitor

    asyncio.run(mgr.execute_target_position(is_manual=False))
    assert launched == []
    assert inst.status == "COMPLETED"
    assert inst.volume == 0


def test_execute_recalculates_failed_on_manual() -> None:
    """手动触发(is_manual=True)时，FAILED 指令也按当前持仓重算并执行。

    对应 a2611 id=11 场景：导入时 volume=6，执行失败后持仓变为 3，
    点开始(手动)应重算为平 2 手、filled 归零重新执行。
    """
    mgr = build_manager()
    inst = SimpleNamespace(
        id=1,
        status="FAILED",
        current_order_id=None,
        filled_volume=6,  # 旧累计成交(脏数据)
        volume=6,  # 导入时旧差值
        remaining_volume=0,
        direction="SELL",
        offset="CLOSE",
        side="LONG",
        target_volume=1,
        enabled=True,
        symbol="a2611",
        price=0,
        strategy_id="S1",
        error_message="TIMEOUT",
        order_placed_time=None,
    )
    mgr._load_today_instructions = lambda: [inst]
    mgr._is_cmd_active = lambda cid: False
    mgr._update_instructions = lambda x: None
    mgr._side_position_volume = lambda symbol, side: 3  # 当前持仓 3

    launched = []

    async def fake_launch(i):
        launched.append(i)

    async def fake_monitor(i_list):
        return None

    mgr._launch_order_cmd = fake_launch
    mgr._monitor_order_commands = fake_monitor

    asyncio.run(mgr.execute_target_position(is_manual=True))
    # 重算：目标 1 - 持仓 3 = -2 → 平 2 手，filled 归零
    assert len(launched) == 1
    assert inst.volume == 2
    assert inst.filled_volume == 0
    assert inst.remaining_volume == 2
    assert inst.offset == "CLOSE"
    assert inst.direction == "SELL"


def test_execute_recalculates_completed_when_deviation_nonzero() -> None:
    """COMPLETED 指令若持仓又偏离目标，点开始(手动或定时)应重算重新执行。

    对应"完成后持仓变了产生新偏差"的场景：定时触发(is_manual=False)也重新评估。
    """
    mgr = build_manager()
    inst = SimpleNamespace(
        id=1,
        status="COMPLETED",
        current_order_id=None,
        filled_volume=2,
        volume=2,
        remaining_volume=0,
        direction="SELL",
        offset="CLOSE",
        side="LONG",
        target_volume=1,
        enabled=True,
        symbol="a2611",
        price=0,
        strategy_id="S1",
        error_message=None,
        order_placed_time=None,
    )
    mgr._load_today_instructions = lambda: [inst]
    mgr._is_cmd_active = lambda cid: False
    mgr._update_instructions = lambda x: None
    mgr._side_position_volume = lambda symbol, side: 3  # 持仓又偏离到 3，偏差 -2

    launched = []

    async def fake_launch(i):
        launched.append(i)

    async def fake_monitor(i_list):
        return None

    mgr._launch_order_cmd = fake_launch
    mgr._monitor_order_commands = fake_monitor

    asyncio.run(mgr.execute_target_position(is_manual=False))
    assert len(launched) == 1
    assert inst.volume == 2
    assert inst.filled_volume == 0
    assert inst.remaining_volume == 2
    assert inst.offset == "CLOSE"
    assert inst.direction == "SELL"


# ==================== N/D 盘次文件与交易日口径 ====================


def test_extract_trading_date_with_session_flag():
    """文件名带 -N/-D 盘次标志时仍正确提取交易日"""
    mgr = build_manager()
    assert mgr._extract_trading_date("TargetPos-DQ-20260818-N.csv") == "20260818"
    assert mgr._extract_trading_date("TargetPos-DQ-20260818-D.csv") == "20260818"
    assert mgr._extract_trading_date("SwitchPos-DQ-20260309-N-2.csv") == "20260309"


def test_manual_import_records_file_path():
    """页面导入也记录 file_path（目标仓位目录）与强制重算标志，与扫描导入一致"""
    mgr = build_manager()
    mgr.target_pos_dir = "/opt/data/qtrader/target_pos"
    captured = {}

    def fake_import(csv_text, filename, file_path, force=False):
        captured["file_path"] = file_path
        captured["force"] = force
        return {"imported": 0}

    mgr._import_target_csv = fake_import
    mgr.import_target_file(
        "account,stragegy,symbol,direction,volume", "TargetPos-DQ-20260818-N.csv"
    )
    assert captured["file_path"] == "/opt/data/qtrader/target_pos"
    assert captured["force"] is True


def test_trading_date_uses_gateway_trading_day():
    """交易日取网关口径（夜盘时段为次一交易日）"""
    mgr = build_manager()
    mgr.trading_engine.trading_day = datetime(2026, 8, 18)
    assert mgr._trading_date() == "20260818"


def test_scan_matches_trading_day_not_calendar(tmp_path):
    """夜盘场景：网关交易日为次日 20260818 时，应匹配 -N 文件并跳过旧文件"""
    mgr = build_manager()
    mgr.target_pos_dir = str(tmp_path)
    (tmp_path / "TargetPos-DQ-20260818-N.csv").write_text(
        "account,stragegy,symbol,direction,volume\nDQ,S1,a2611,Buy,1\n", encoding="utf-8"
    )
    (tmp_path / "TargetPos-DQ-20260816-N.csv").write_text(
        "account,stragegy,symbol,direction,volume\nDQ,S1,a2611,Buy,1\n", encoding="utf-8"
    )
    mgr._trading_date = lambda: "20260818"

    imported = []

    def fake_import(csv_text, filename, file_path):
        imported.append((filename, file_path))
        return {"imported": 1}

    mgr._import_target_csv = fake_import
    mgr.scan_and_process_target_files()
    assert imported == [("TargetPos-DQ-20260818-N.csv", str(tmp_path))]


def test_load_today_instructions_filters_by_trading_date(monkeypatch):
    """指令加载按交易日（网关口径）过滤，夜盘时段可取到次日指令"""
    mgr = build_manager()
    mgr._trading_date = lambda: "20260818"

    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value.order_by.return_value.all.return_value = []

    class FakeSessionScope:
        def __enter__(self):
            return session

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tpm, "session_scope", lambda: FakeSessionScope())
    mgr._load_today_instructions()

    # 取各过滤条件（Column == value）的比较右值
    values = [getattr(getattr(c, "right", None), "value", None) for c in query.filter.call_args[0]]
    assert "20260818" in values


# ==================== 手动导入强制重算 ====================


def _stub_import_db(monkeypatch, existing):
    """替换 session_scope，返回 (session, existing 记录注入)"""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing

    class FakeSessionScope:
        def __enter__(self):
            return session

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tpm, "session_scope", lambda: FakeSessionScope())
    return session


def test_manual_import_forces_reimport_when_unchanged(monkeypatch):
    """手动导入：文件内容未变化也强制重新计算差值（不返回 skipped）"""
    mgr = build_manager()
    csv_text = "account,stragegy,symbol,direction,volume\nDQ,S1,a2611,Buy,1\n"
    # 已存在同名且 hash 一致的导入记录
    existing = SimpleNamespace(
        file_hash=hashlib.md5(csv_text.encode("utf-8")).hexdigest(), file_path="/old"
    )
    _stub_import_db(monkeypatch, existing)

    mgr._compute_instructions = lambda *args: []
    mgr._retire_old_instructions = lambda *args: None

    result = mgr._import_target_csv(csv_text, "TargetPos-DQ-20260818-N.csv", "/dir", force=True)
    assert result["skipped"] is False


def test_scan_import_skips_unchanged_file(monkeypatch):
    """扫描导入：文件内容未变化时保持幂等跳过"""
    mgr = build_manager()
    csv_text = "account,stragegy,symbol,direction,volume\nDQ,S1,a2611,Buy,1\n"
    existing = SimpleNamespace(
        file_hash=hashlib.md5(csv_text.encode("utf-8")).hexdigest(), file_path="/old"
    )
    _stub_import_db(monkeypatch, existing)
    mgr._compute_instructions = lambda *args: []

    result = mgr._import_target_csv(csv_text, "TargetPos-DQ-20260818-N.csv", "/dir")
    assert result["skipped"] is True
    assert result["reason"] == "文件未变化"


# ==================== 换仓开关拦截 ====================


def test_target_pos_disabled_blocks_manual_import():
    """账户配置 enable_target_pos_rotation=false 时拦截手动导入"""
    mgr = build_manager()
    mgr.config.enable_target_pos_rotation = False
    with pytest.raises(ValueError, match="目标仓位换仓未开启"):
        mgr.import_target_file(
            "account,stragegy,symbol,direction,volume", "TargetPos-DQ-20260818-N.csv"
        )


def test_target_pos_disabled_blocks_scan(tmp_path):
    """账户配置 enable_target_pos_rotation=false 时跳过扫描导入"""
    mgr = build_manager()
    mgr.config.enable_target_pos_rotation = False
    mgr.target_pos_dir = str(tmp_path)
    (tmp_path / "TargetPos-DQ-20260818-N.csv").write_text(
        "account,stragegy,symbol,direction,volume\nDQ,S1,a2611,Buy,1\n", encoding="utf-8"
    )
    mgr._trading_date = lambda: "20260818"

    imported = []
    mgr._import_target_csv = lambda *args: imported.append(args) or {"imported": 1}

    mgr.scan_and_process_target_files()
    assert imported == []


# ==================== 更新指令（目标手数） ====================


def _stub_update_db(monkeypatch, inst):
    """替换 session_scope，使 update_instruction 查询返回 inst"""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = inst

    class FakeSessionScope:
        def __enter__(self):
            return session

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tpm, "session_scope", lambda: FakeSessionScope())
    return session


def build_instruction(**overrides) -> SimpleNamespace:
    """构造一条可被 _recalculate_deviation 修改的指令对象"""
    inst = SimpleNamespace(
        id=11,
        target_volume=5,
        enabled=True,
        status="PENDING",
        symbol="SHFE.rb2610",
        side="LONG",
        current_order_id=None,
        direction="SELL",
        offset="CLOSE",
        volume=4,
        filled_volume=2,
        remaining_volume=2,
        error_message=None,
    )
    for k, v in overrides.items():
        setattr(inst, k, v)
    return inst


def test_update_instruction_target_volume(monkeypatch):
    """更新目标手数：写入新值并按当前持仓重置进度基准"""
    mgr = build_manager()
    inst = build_instruction()
    _stub_update_db(monkeypatch, inst)
    mgr._side_position_volume = lambda symbol, side: 3  # 当前持仓3手
    mgr._instruction_to_dict = lambda i: {
        "id": i.id,
        "target_volume": i.target_volume,
        "volume": i.volume,
        "filled_volume": i.filled_volume,
    }

    result = mgr.update_instruction({"instruction_id": 11, "target_volume": 8})

    assert inst.target_volume == 8
    # 目标8 持仓3 → 需开5手：分子清零、分母=当前偏差
    assert inst.volume == 5
    assert inst.filled_volume == 0
    assert inst.remaining_volume == 5
    assert inst.direction == "BUY"
    assert inst.offset == "OPEN"
    assert inst.status == "PENDING"
    assert result["volume"] == 5
    assert result["filled_volume"] == 0


def test_update_instruction_target_volume_zero_allowed(monkeypatch):
    """目标手数允许为 0（表示该侧清仓）：持仓3手 → 需平3手"""
    mgr = build_manager()
    inst = build_instruction()
    _stub_update_db(monkeypatch, inst)
    mgr._side_position_volume = lambda symbol, side: 3
    mgr._instruction_to_dict = lambda i: {"target_volume": i.target_volume, "volume": i.volume}

    result = mgr.update_instruction({"instruction_id": 11, "target_volume": 0})

    assert inst.target_volume == 0
    assert inst.volume == 3
    assert inst.direction == "SELL"
    assert inst.offset == "CLOSE"
    assert result["volume"] == 3


def test_update_instruction_target_reached_marks_completed(monkeypatch):
    """新目标与当前持仓一致：进度分母为0并标记完成"""
    mgr = build_manager()
    inst = build_instruction()
    _stub_update_db(monkeypatch, inst)
    mgr._side_position_volume = lambda symbol, side: 4
    mgr._instruction_to_dict = lambda i: {"status": i.status, "volume": i.volume}

    result = mgr.update_instruction({"instruction_id": 11, "target_volume": 4})

    assert inst.volume == 0
    assert inst.filled_volume == 0
    assert inst.status == "COMPLETED"
    assert result["status"] == "COMPLETED"


def test_update_instruction_rejected_while_running(monkeypatch):
    """执行中的指令拒绝修改目标手数"""
    mgr = build_manager()
    inst = build_instruction(status="RUNNING", current_order_id="cmd-1")
    _stub_update_db(monkeypatch, inst)
    mgr._is_cmd_active = lambda cmd_id: True

    with pytest.raises(ValueError, match="指令执行中"):
        mgr.update_instruction({"instruction_id": 11, "target_volume": 8})

    assert inst.target_volume == 5
    assert inst.volume == 4


def test_update_instruction_target_volume_negative_rejected(monkeypatch):
    """目标手数为负数时拒绝且不修改原值"""
    mgr = build_manager()
    inst = build_instruction()
    _stub_update_db(monkeypatch, inst)

    with pytest.raises(ValueError, match="目标手数不能为负数"):
        mgr.update_instruction({"instruction_id": 11, "target_volume": -1})

    assert inst.target_volume == 5


def test_update_instruction_missing_instruction_id():
    """缺少 instruction_id 时抛出 ValueError"""
    mgr = build_manager()
    with pytest.raises(ValueError, match="缺少 instruction_id"):
        mgr.update_instruction({"target_volume": 8})
