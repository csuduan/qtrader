"""
SwitchPosManager 单元测试

覆盖：
- CSV 导入基本解析
"""

import asyncio
import os
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

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


def test_import_csv_basic():
    """CSV 正常导入生成 RotationInstructionPo"""
    mgr = build_manager()
    mgr.trading_engine.std_symbol = lambda s: s
    csv_text = "account,strategy,symbol,offset,direction,volume\nDQ,S1,a2611,Open,Buy,1\n"
    with patch("qtrader.trader.switch_mgr.session_scope"):
        result = mgr.import_csv(csv_text, "20260818_rotation.csv")
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
    mgr._update_instructions = MagicMock()

    await mgr.execute_position_rotation(is_manual=True)

    assert inserted_offsets == ["CLOSE", "OPEN"]
    assert close_inst.status == "RUNNING"
    assert open_inst.status == "RUNNING"


def _mock_session_scope():
    """模拟 session_scope，查询结果为空（文件未导入过）"""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


def _mock_session_scope_pair():
    """模拟 session_scope，返回 (工厂, session) 以便断言导入记录写入"""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm), session


def _make_scan_env(mgr: SwitchPosManager, tmp_path, name: str):
    """创建扫描目录和过mtime守卫的文件（时间戳设为60秒前），返回 (文件路径, session)"""
    today_str = datetime.now().strftime("%Y%m%d")
    today_dir = tmp_path / today_str
    today_dir.mkdir(exist_ok=True)
    mgr.switchPos_files_dir = str(tmp_path)

    csv_file = today_dir / f"{today_str}_DQ_{name}.csv"
    old_ts = time.time() - 60
    return csv_file, old_ts, _mock_session_scope_pair()


def test_scan_skips_fresh_files(tmp_path):
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
        f = today_dir / f"{today_str}_DQ_{name}.csv"
        f.write_text("header\n", encoding="gbk")
        os.utime(f, (mtime, mtime))

    imported = []
    mgr.import_csv = lambda content, filename, mode="replace": imported.append(filename)

    with (
        patch("qtrader.trader.switch_mgr.session_scope", _mock_session_scope()),
        patch("qtrader.trader.switch_mgr.time.sleep"),
    ):
        mgr.scan_and_process_orders()

    assert sorted(imported) == [
        f"{today_str}_DQ_future.csv",
        f"{today_str}_DQ_stable.csv",
    ]


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

    with patch("qtrader.trader.switch_mgr.time.sleep"):
        assert mgr._is_file_stable(f) is True


def test_is_file_stable_fresh_file_no_wait(tmp_path):
    """修改时间不足5秒 → 不稳定，且不进入观察窗口（无sleep）"""
    mgr = build_manager()
    f = tmp_path / "a.csv"
    f.write_text("header\n", encoding="gbk")

    with patch("qtrader.trader.switch_mgr.time.sleep") as mock_sleep:
        assert mgr._is_file_stable(f) is False
        mock_sleep.assert_not_called()


def test_is_file_stable_growing_file(tmp_path):
    """观察窗口内大小变化 → 不稳定"""
    mgr = build_manager()
    f = _stable_file(tmp_path)

    def fake_sleep(_):
        with open(f, "a", encoding="gbk") as fh:
            fh.write("row\n")

    with patch("qtrader.trader.switch_mgr.time.sleep", fake_sleep):
        assert mgr._is_file_stable(f) is False


def test_is_file_stable_touched_during_window(tmp_path):
    """观察窗口内被触碰（大小未变）→ 不稳定"""
    mgr = build_manager()
    f = _stable_file(tmp_path)

    def fake_sleep(_):
        os.utime(f, None)

    with patch("qtrader.trader.switch_mgr.time.sleep", fake_sleep):
        assert mgr._is_file_stable(f) is False


def test_is_file_stable_missing_file(tmp_path):
    """文件不存在（获取状态失败）→ 不稳定"""
    mgr = build_manager()
    assert mgr._is_file_stable(tmp_path / "nope.csv") is False


def test_scan_skips_empty_file(tmp_path):
    """空文件不导入也不写导入记录，等待写入方写完后再扫描导入"""
    mgr = build_manager()
    csv_file, old_ts, (session_factory, session) = _make_scan_env(mgr, tmp_path, "empty")
    csv_file.write_text("", encoding="gbk")
    os.utime(csv_file, (old_ts, old_ts))

    imported = []
    mgr.import_csv = lambda content, filename, mode="replace": imported.append(filename)

    with (
        patch("qtrader.trader.switch_mgr.session_scope", session_factory),
        patch("qtrader.trader.switch_mgr.time.sleep"),
    ):
        mgr.scan_and_process_orders()

    assert imported == []
    session.add.assert_not_called()


def test_scan_no_record_when_import_fails(tmp_path):
    """导入失败时不写导入记录，等待下轮扫描重试"""
    mgr = build_manager()
    csv_file, old_ts, (session_factory, session) = _make_scan_env(mgr, tmp_path, "bad")
    csv_file.write_text(
        "account,strategy,symbol,offset,direction,volume\nDQ,S1,a2611,Open,Buy,1\n",
        encoding="gbk",
    )
    os.utime(csv_file, (old_ts, old_ts))

    mgr.import_csv = MagicMock(side_effect=ValueError("CSV文件为空或格式错误"))

    with (
        patch("qtrader.trader.switch_mgr.session_scope", session_factory),
        patch("qtrader.trader.switch_mgr.time.sleep"),
    ):
        mgr.scan_and_process_orders()

    mgr.import_csv.assert_called_once()
    session.add.assert_not_called()


def test_scan_skips_file_growing_during_check(tmp_path):
    """两次大小检查之间文件仍在增长（写入方未写完），跳过本轮"""
    mgr = build_manager()
    csv_file, old_ts, (session_factory, session) = _make_scan_env(mgr, tmp_path, "growing")
    csv_file.write_text(
        "account,strategy,symbol,offset,direction,volume\nDQ,S1,a2611,Open,Buy,1\n",
        encoding="gbk",
    )
    os.utime(csv_file, (old_ts, old_ts))

    # 模拟写入方：在两次大小检查之间（sleep期间）追加数据
    def fake_sleep(_):
        with open(csv_file, "a", encoding="gbk") as fh:
            fh.write("DQ,S2,a2611,Open,Buy,2\n")

    imported = []
    mgr.import_csv = lambda content, filename, mode="replace": imported.append(filename)

    with (
        patch("qtrader.trader.switch_mgr.session_scope", session_factory),
        patch("qtrader.trader.switch_mgr.time.sleep", fake_sleep),
    ):
        mgr.scan_and_process_orders()

    assert imported == []
    session.add.assert_not_called()
