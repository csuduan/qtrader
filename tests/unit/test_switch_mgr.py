"""
SwitchPosManager 单元测试

覆盖：
- CSV 导入基本解析
"""

import asyncio
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
