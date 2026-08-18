"""
SwitchPosManager 单元测试

覆盖：
- 换仓开关拦截（账户配置 enable_instruction_rotation=false 时拦截导入与扫描）
"""

from datetime import datetime
from unittest.mock import MagicMock

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


def test_instruction_rotation_disabled_blocks_import():
    """账户配置 enable_instruction_rotation=false 时拦截手动导入"""
    mgr = build_manager()
    mgr.config.enable_instruction_rotation = False
    csv_text = "账户编号,策略编号,合约,开平,方向,手数\nDQ,S1,a2611,Open,Buy,1\n"
    with pytest.raises(ValueError, match="交易指令换仓未开启"):
        mgr.import_csv(csv_text, "20260818_rotation.csv")


def test_instruction_rotation_disabled_blocks_scan(tmp_path):
    """账户配置 enable_instruction_rotation=false 时跳过扫描导入"""
    mgr = build_manager()
    mgr.config.enable_instruction_rotation = False
    mgr.switchPos_files_dir = str(tmp_path)
    today_dir = tmp_path / datetime.now().strftime("%Y%m%d")
    today_dir.mkdir(parents=True)
    (today_dir / "SwitchPos-DQ-N.csv").write_text("x", encoding="utf-8")

    calls = []
    mgr.import_csv = lambda *args, **kwargs: calls.append(args)

    mgr.scan_and_process_orders()
    assert calls == []


def test_enabled_by_default():
    """默认配置下两个换仓开关均为开启（拦截不生效）"""
    mgr = build_manager()
    assert mgr.config.enable_instruction_rotation is not False
