"""
TradingManager 账户添加/删除/扫描单元测试

覆盖：
- get_available_accounts：扫描 config 目录中未添加的账户
- add_account：加载配置、创建 Proxy、持久化 account_ids
- remove_account：仅限已停止账户，停止 Proxy、移除内存配置、持久化 account_ids
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import qtrader.manager.manager as mgr_mod
from qtrader.manager.manager import TradingManager
from qtrader.utils.config_loader import AccountConfig, AppConfig


def build_manager() -> TradingManager:
    """构造不依赖启动流程的 TradingManager"""
    existing = AccountConfig(account_id="DQ", enabled=True)
    manager = TradingManager.__new__(TradingManager)
    manager.account_configs = [existing]
    manager.account_configs_map = {"DQ": existing}
    manager.app_config = MagicMock()
    manager.traders = {}
    return manager


def make_loader_mock(config_dir: Path, app_account_ids: list[str]) -> MagicMock:
    """构造模拟 ConfigLoader：config_dir 可 glob，_load_app_config 返回 account_ids"""
    loader = MagicMock()
    loader.config_dir = config_dir
    app_config = AppConfig(account_ids=app_account_ids)
    loader._load_app_config.return_value = app_config
    loader.update_account_ids = MagicMock()
    return loader


@pytest.fixture
def config_dir(tmp_path):
    """模拟 config 目录：DQ 已添加，WY/YJ 未添加，sample 为模板"""
    for name in ("DQ", "WY", "YJ", "sample"):
        (tmp_path / f"account-{name}.yaml").write_text(
            f"account_id: {name}\naccount_type: kq\n", encoding="utf-8"
        )
    return tmp_path


# ==================== get_available_accounts ====================


def test_get_available_accounts(config_dir):
    """扫描未添加的账户，排除已添加账户与 sample 模板"""
    manager = build_manager()
    loader = make_loader_mock(config_dir, ["DQ"])
    with patch.object(mgr_mod, "get_config_loader", return_value=loader):
        available = manager.get_available_accounts()
    assert available == ["WY", "YJ"]


# ==================== add_account ====================


@pytest.mark.asyncio
async def test_add_account_success(config_dir):
    """添加账户：加载配置、创建 Proxy、追加 account_ids"""
    manager = build_manager()
    loader = make_loader_mock(config_dir, ["DQ"])
    loader._load_account_config.return_value = AccountConfig(account_id="WY", enabled=True)

    async def fake_create_proxy(account_id):
        manager.traders[account_id] = MagicMock()
        return True

    with (
        patch.object(mgr_mod, "get_config_loader", return_value=loader),
        patch.object(TradingManager, "create_trader_proxy", side_effect=fake_create_proxy),
    ):
        result = await manager.add_account("WY")

    assert result is True
    assert "WY" in manager.traders
    assert "WY" in manager.account_configs_map
    loader.update_account_ids.assert_called_once_with(["DQ", "WY"])


@pytest.mark.asyncio
async def test_add_account_already_exists(config_dir):
    """已添加的账户重复添加返回 False"""
    manager = build_manager()
    manager.traders["DQ"] = MagicMock()
    loader = make_loader_mock(config_dir, ["DQ"])

    with patch.object(mgr_mod, "get_config_loader", return_value=loader):
        result = await manager.add_account("DQ")

    assert result is False
    loader.update_account_ids.assert_not_called()


@pytest.mark.asyncio
async def test_add_account_file_missing(config_dir):
    """配置文件不存在时返回 False"""
    manager = build_manager()
    loader = make_loader_mock(config_dir, ["DQ"])
    loader._load_account_config.side_effect = FileNotFoundError("not found")

    with patch.object(mgr_mod, "get_config_loader", return_value=loader):
        result = await manager.add_account("NOPE")

    assert result is False


@pytest.mark.asyncio
async def test_add_account_id_mismatch(config_dir):
    """文件内 account_id 与文件名不一致时拒绝添加"""
    manager = build_manager()
    loader = make_loader_mock(config_dir, ["DQ"])
    loader._load_account_config.return_value = AccountConfig(account_id="OTHER")

    with patch.object(mgr_mod, "get_config_loader", return_value=loader):
        result = await manager.add_account("WY")

    assert result is False
    assert "WY" not in manager.traders


# ==================== remove_account ====================


@pytest.mark.asyncio
async def test_remove_account_success(config_dir):
    """删除已停止账户：停止监控、移除内存配置、更新 account_ids（不再停止进程）"""
    manager = build_manager()
    trader = AsyncMock()
    trader.is_running = MagicMock(return_value=False)
    trader.stop_process = AsyncMock(return_value=True)
    trader.stop_monitoring = AsyncMock()
    manager.traders["DQ"] = trader
    loader = make_loader_mock(config_dir, ["DQ", "RF"])

    with patch.object(mgr_mod, "get_config_loader", return_value=loader):
        result = await manager.remove_account("DQ")

    assert result is True
    trader.stop_process.assert_not_awaited()
    trader.stop_monitoring.assert_awaited_once()
    assert "DQ" not in manager.traders
    assert "DQ" not in manager.account_configs_map
    assert manager.account_configs == []
    loader.update_account_ids.assert_called_once_with(["RF"])


@pytest.mark.asyncio
async def test_remove_account_not_added(config_dir):
    """未添加的账户删除返回 False"""
    manager = build_manager()
    loader = make_loader_mock(config_dir, ["DQ"])

    with patch.object(mgr_mod, "get_config_loader", return_value=loader):
        result = await manager.remove_account("DQ")

    assert result is False


@pytest.mark.asyncio
async def test_remove_account_running_rejected(config_dir):
    """运行中的账户拒绝删除，需先停止"""
    manager = build_manager()
    trader = AsyncMock()
    trader.is_running = MagicMock(return_value=True)
    trader.stop_monitoring = AsyncMock()
    manager.traders["DQ"] = trader
    loader = make_loader_mock(config_dir, ["DQ"])

    with (
        patch.object(mgr_mod, "get_config_loader", return_value=loader),
        pytest.raises(ValueError, match="请先停止"),
    ):
        await manager.remove_account("DQ")

    assert "DQ" in manager.traders
    trader.stop_monitoring.assert_not_awaited()
    loader.update_account_ids.assert_not_called()
