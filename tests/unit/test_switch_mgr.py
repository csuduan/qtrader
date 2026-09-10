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
    """扫描时只导入时间戳与系统时间偏差绝对值大于10秒的文件"""
    mgr = build_manager()
    today_str = datetime.now().strftime("%Y%m%d")
    today_dir = tmp_path / today_str
    today_dir.mkdir()
    mgr.switchPos_files_dir = str(tmp_path)

    now = time.time()
    files = {
        "fresh": now,  # 刚写入 → 跳过
        "future_fresh": now + 5,  # 未来值但偏差不足10秒 → 跳过
        "stable": now - 60,  # 偏差超过10秒 → 导入
        "future": now + 3600,  # 未来值且偏差超过10秒（时区偏差）→ 导入
    }
    for name, mtime in files.items():
        f = today_dir / f"{today_str}_DQ_{name}.csv"
        f.write_text("header\n", encoding="gbk")
        os.utime(f, (mtime, mtime))

    imported = []

    async def fake_import(content, filename, mode="replace"):
        imported.append(filename)

    mgr.import_csv = fake_import

    with (
        patch("qtrader.trader.switch_mgr.get_async_session", _mock_async_session_scope()),
        patch("qtrader.trader.switch_mgr.fetch_one", AsyncMock(return_value=None)),
    ):
        await mgr.scan_and_process_orders()

    assert sorted(imported) == [
        f"{today_str}_DQ_future.csv",
        f"{today_str}_DQ_stable.csv",
    ]
