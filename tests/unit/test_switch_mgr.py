"""
SwitchPosManager 单元测试

覆盖：
- CSV 导入基本解析
"""

import asyncio
import os
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.trader.switch_mgr import SwitchPosManager


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


def async_scope_with(session: MagicMock) -> MagicMock:
    """返回一个模拟的 get_async_session，进入时返回给定 session"""
    cm = MagicMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return MagicMock(return_value=cm)


async def test_import_csv_basic():
    """CSV 正常导入生成 RotationInstructionPo"""
    mgr = build_manager()
    mgr.trading_engine.std_symbol = lambda s: s
    mgr.load_rotation_instructions = AsyncMock()
    csv_text = "account,strategy,symbol,offset,direction,volume\nDQ,S1,a2611,Open,Buy,1\n"
    session = MagicMock()
    session.execute = AsyncMock()
    with patch("qtrader.trader.switch_mgr.get_async_session", async_scope_with(session)):
        result = await mgr.import_csv(csv_text, "20260818_rotation.csv")
    assert result["imported"] == 1


@pytest.mark.asyncio
async def test_execute_rotation_close_before_open():
    """执行换仓时应先插入平仓指令，平仓完成后再插入开仓指令"""
    mgr = build_manager()
    mgr.config.trading.risk_control.max_split_volume = 10

    close_inst = MagicMock()
    close_inst.offset = "CLOSE"
    close_inst.direction = "SELL"
    close_inst.symbol = "rb2609"
    close_inst.volume = 2
    close_inst.remaining_volume = 2
    close_inst.price = 0
    close_inst.status = "PENDING"
    close_inst.enabled = True
    close_inst.account_id = "DQ"
    close_inst.is_deleted = False
    close_inst.filled_volume = 0
    close_inst.order_time = None
    close_inst.trading_date = datetime.now().strftime("%Y%m%d")

    open_inst = MagicMock()
    open_inst.offset = "OPEN"
    open_inst.direction = "BUY"
    open_inst.symbol = "rb2609"
    open_inst.volume = 3
    open_inst.remaining_volume = 3
    open_inst.price = 0
    open_inst.status = "PENDING"
    open_inst.enabled = True
    open_inst.account_id = "DQ"
    open_inst.is_deleted = False
    open_inst.filled_volume = 0
    open_inst.order_time = None
    open_inst.trading_date = datetime.now().strftime("%Y%m%d")

    inserted_offsets: list[str] = []

    def fake_insert(cmd):
        cmd.cmd_id = f"cmd-{cmd.offset}"
        inserted_offsets.append(cmd.offset)

    mgr.trading_engine.insert_order_cmd = fake_insert
    mgr.get_today_instructions = MagicMock(return_value=[open_inst, close_inst])
    mgr._check_instruction = MagicMock(return_value=True)
    mgr._monitor_order_commands = MagicMock(return_value=asyncio.Future())
    mgr._monitor_order_commands.return_value.set_result(None)
    mgr._update_instructions = AsyncMock()

    await mgr.execute_position_rotation(is_manual=True)

    assert inserted_offsets == ["CLOSE", "OPEN"]
    assert close_inst.status == "RUNNING"
    assert open_inst.status == "RUNNING"


def _mock_async_session_scope():
    """模拟 get_async_session，查询结果为空（文件未导入过）"""
    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return MagicMock(return_value=cm)


async def test_scan_skips_fresh_files(tmp_path):
    """扫描时只导入时间戳与系统时间偏差绝对值不小于5秒且大小稳定的文件"""
    mgr = build_manager()
    today_str = datetime.now().strftime("%Y%m%d")
    today_dir = tmp_path / today_str
    today_dir.mkdir()
    mgr.switchPos_files_dir = str(tmp_path)

    now = time.time()
    files = {
        "fresh": now,  # 刚写入 → 跳过
        "future_fresh": now + 2,  # 未来值但偏差不足5秒 → 跳过
        "stable": now - 60,  # 偏差不小于5秒 → 导入
        "future": now + 3600,  # 未来值且偏差超过5秒（时区偏差）→ 导入
    }
    for name, mtime in files.items():
        f = today_dir / f"SwitchPos-DQ-{today_str}-{name}.csv"
        f.write_text("header\n", encoding="gbk")
        os.utime(f, (mtime, mtime))

    imported = []

    async def fake_import(content, filename, mode="replace"):
        imported.append(filename)

    mgr.import_csv = fake_import

    with (
        patch("qtrader.trader.switch_mgr.get_async_session", _mock_async_session_scope()),
        patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        patch("qtrader.trader.switch_mgr.asyncio.sleep", AsyncMock()),
    ):
        await mgr.scan_and_process_orders()

    assert sorted(imported) == [
        f"SwitchPos-DQ-{today_str}-future.csv",
        f"SwitchPos-DQ-{today_str}-stable.csv",
    ]


def _make_scan_env(mgr: SwitchPosManager, tmp_path, name: str, content: str = ""):
    """创建扫描目录和已稳定的文件（写入内容并将时间戳设为60秒前）"""
    today_str = datetime.now().strftime("%Y%m%d")
    today_dir = tmp_path / today_str
    today_dir.mkdir(exist_ok=True)
    mgr.switchPos_files_dir = str(tmp_path)

    csv_file = today_dir / f"SwitchPos-{mgr.config.account_id}-{today_str}-{name}.csv"
    csv_file.write_text(content, encoding="gbk")
    old_ts = time.time() - 60
    os.utime(csv_file, (old_ts, old_ts))
    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    return csv_file, session, MagicMock(return_value=cm)


async def test_scan_skips_empty_file(tmp_path):
    """空文件不导入也不写导入记录，等待写入方写完后再扫描导入"""
    mgr = build_manager()
    _, session, session_factory = _make_scan_env(mgr, tmp_path, "empty")

    imported = []

    async def fake_import(content, filename, mode="replace"):
        imported.append(filename)

    mgr.import_csv = fake_import

    with (
        patch("qtrader.trader.switch_mgr.get_async_session", session_factory),
        patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        patch("qtrader.trader.switch_mgr.asyncio.sleep", AsyncMock()),
    ):
        await mgr.scan_and_process_orders()

    assert imported == []
    session.add.assert_not_called()


async def test_scan_no_record_when_import_fails(tmp_path):
    """导入失败时不写导入记录，等待下轮扫描重试"""
    mgr = build_manager()
    _, session, session_factory = _make_scan_env(
        mgr,
        tmp_path,
        "bad",
        "account,strategy,symbol,offset,direction,volume\nDQ,S1,a2611,Open,Buy,1\n",
    )

    mgr.import_csv = AsyncMock(side_effect=ValueError("CSV文件为空或格式错误"))

    with (
        patch("qtrader.trader.switch_mgr.get_async_session", session_factory),
        patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        patch("qtrader.trader.switch_mgr.asyncio.sleep", AsyncMock()),
    ):
        await mgr.scan_and_process_orders()

    mgr.import_csv.assert_awaited_once()
    session.add.assert_not_called()


async def test_scan_skips_file_growing_during_check(tmp_path):
    """观察窗口内文件仍在增长（写入方未写完），跳过本轮"""
    mgr = build_manager()
    csv_file, session, session_factory = _make_scan_env(
        mgr,
        tmp_path,
        "growing",
        "account,strategy,symbol,offset,direction,volume\nDQ,S1,a2611,Open,Buy,1\n",
    )

    # 模拟写入方：在观察窗口（sleep期间）追加数据
    async def fake_sleep(_):
        with open(csv_file, "a", encoding="gbk") as fh:
            fh.write("DQ,S2,a2611,Open,Buy,2\n")

    imported = []

    async def fake_import(content, filename, mode="replace"):
        imported.append(filename)

    mgr.import_csv = fake_import

    with (
        patch("qtrader.trader.switch_mgr.get_async_session", session_factory),
        patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        patch("qtrader.trader.switch_mgr.asyncio.sleep", fake_sleep),
    ):
        await mgr.scan_and_process_orders()

    assert imported == []
    session.add.assert_not_called()


# ==================== _is_file_stable ====================


def _stable_file(tmp_path, name: str = "a.csv"):
    """创建内容固定、时间戳为60秒前的文件"""
    f = tmp_path / name
    f.write_text("header\n", encoding="gbk")
    old_ts = time.time() - 60
    os.utime(f, (old_ts, old_ts))
    return f


def test_is_file_stable_old_file(tmp_path):
    """修改时间超过5秒且观察窗口内大小不变 → 稳定"""
    mgr = build_manager()
    f = _stable_file(tmp_path)
    assert asyncio.run(mgr._is_file_stable(f, size_window=0)) is True


def test_is_file_stable_fresh_file_no_wait(tmp_path):
    """修改时间不足5秒 → 不稳定，且不进入观察窗口（无sleep）"""
    mgr = build_manager()
    f = tmp_path / "a.csv"
    f.write_text("header\n", encoding="gbk")

    with patch("qtrader.trader.switch_mgr.asyncio.sleep", AsyncMock()) as mock_sleep:
        assert asyncio.run(mgr._is_file_stable(f)) is False
        mock_sleep.assert_not_called()


def test_is_file_stable_growing_file(tmp_path):
    """观察窗口内大小变化 → 不稳定"""
    mgr = build_manager()
    f = _stable_file(tmp_path)

    async def fake_sleep(_):
        with open(f, "a", encoding="gbk") as fh:
            fh.write("row\n")

    with patch("qtrader.trader.switch_mgr.asyncio.sleep", fake_sleep):
        assert asyncio.run(mgr._is_file_stable(f)) is False


def test_is_file_stable_touched_during_window(tmp_path):
    """观察窗口内被触碰（大小未变）→ 不稳定"""
    mgr = build_manager()
    f = _stable_file(tmp_path)

    async def fake_sleep(_):
        os.utime(f, None)

    with patch("qtrader.trader.switch_mgr.asyncio.sleep", fake_sleep):
        assert asyncio.run(mgr._is_file_stable(f)) is False


def test_is_file_stable_missing_file(tmp_path):
    """文件不存在（获取状态失败）→ 不稳定"""
    mgr = build_manager()
    assert asyncio.run(mgr._is_file_stable(tmp_path / "nope.csv")) is False


async def test_scan_ignores_prefixed_other_account_file(tmp_path):
    """扫描按前缀匹配账户，WY 不会误扫 WY2 的文件（避免replace模式清空自身指令）"""
    mgr = build_manager("WY")
    csv_file, session, session_factory = _make_scan_env(
        mgr,
        tmp_path,
        "142530",
        "account,strategy,symbol,offset,direction,volume\nWY,S1,a2611,Open,Buy,1\n",
    )

    today_str = datetime.now().strftime("%Y%m%d")
    wy2_file = csv_file.parent / f"SwitchPos-WY2-{today_str}-D-1.csv"
    wy2_file.write_text(
        "account,strategy,symbol,offset,direction,volume\nWY2,S1,a2611,Open,Buy,2\n",
        encoding="gbk",
    )
    old_ts = time.time() - 60
    os.utime(wy2_file, (old_ts, old_ts))

    imported = []

    async def fake_import(content, filename, mode="replace"):
        imported.append(filename)

    mgr.import_csv = fake_import

    with (
        patch("qtrader.trader.switch_mgr.get_async_session", session_factory),
        patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
        patch("qtrader.trader.switch_mgr.asyncio.sleep", AsyncMock()),
    ):
        await mgr.scan_and_process_orders()

    assert imported == [csv_file.name]
