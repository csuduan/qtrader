"""
TradingManager 单元测试

覆盖当前 API 的核心行为：初始化、TraderProxy 创建/添加/删除账户、
启动/停止/重启、状态下查询、交易请求转发、Manager 级定时任务、
数据查询聚合。全部基于 mock，不创建真实进程与 socket。
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.manager.manager import TradingManager
from qtrader.models.object import AccountData, Direction, Offset


def make_account_config(account_id: str, enabled: bool = True) -> MagicMock:
    config = MagicMock()
    config.account_id = account_id
    config.enabled = enabled
    return config


@pytest.fixture
def manager(tmp_path) -> TradingManager:
    socket_config = Mock(socket_dir=str(tmp_path / "socks"))
    with patch("qtrader.manager.manager.SocketConfig", return_value=socket_config):
        return TradingManager([make_account_config("DQ"), make_account_config("GW")])


def make_proxy(running: bool = False) -> MagicMock:
    proxy = MagicMock()
    proxy.is_running.return_value = running
    proxy.stop_monitoring = AsyncMock()
    proxy.start_process = AsyncMock(return_value=True)
    proxy.stop_process = AsyncMock(return_value=True)
    proxy.get_status.return_value = {"account_id": "DQ", "state": "stopped"}
    proxy.get_account_cached.return_value = None
    proxy.get_account = AsyncMock(return_value=None)
    return proxy


@pytest.mark.unit
class TestInit:
    """初始化"""

    def test_init_builds_config_map(self, manager):
        assert set(manager.account_configs_map.keys()) == {"DQ", "GW"}
        assert manager.traders == {}
        assert manager._running is False

    def test_init_skips_none_account_id(self, tmp_path):
        socket_config = Mock(socket_dir=str(tmp_path / "socks"))
        none_config = make_account_config("X")
        none_config.account_id = None
        with patch("qtrader.manager.manager.SocketConfig", return_value=socket_config):
            m = TradingManager([make_account_config("DQ"), none_config])
        assert set(m.account_configs_map.keys()) == {"DQ"}

    def test_init_creates_socket_dir(self, tmp_path):
        socket_dir = tmp_path / "socks"
        socket_config = Mock(socket_dir=str(socket_dir))
        with patch("qtrader.manager.manager.SocketConfig", return_value=socket_config):
            TradingManager([])
        assert socket_dir.exists()


@pytest.mark.unit
class TestCreateTraderProxy:
    """创建 TraderProxy"""

    @pytest.mark.asyncio
    async def test_unknown_account_fails(self, manager):
        assert await manager.create_trader_proxy("NOPE") is False

    @pytest.mark.asyncio
    async def test_creates_proxy(self, manager):
        with patch("qtrader.manager.manager.TraderProxy") as mock_proxy_cls:
            assert await manager.create_trader_proxy("DQ") is True

        mock_proxy_cls.assert_called_once()
        assert "DQ" in manager.traders

    @pytest.mark.asyncio
    async def test_replaces_existing_proxy(self, manager):
        old = make_proxy()
        manager.traders["DQ"] = old

        with patch("qtrader.manager.manager.TraderProxy") as mock_proxy_cls:
            assert await manager.create_trader_proxy("DQ") is True

        old.stop_monitoring.assert_awaited_once()
        assert manager.traders["DQ"] is mock_proxy_cls.return_value


@pytest.mark.unit
class TestAvailableAccounts:
    """可添加账户扫描"""

    def test_lists_unadded_accounts(self, manager, tmp_path):
        loader = MagicMock()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        for name in ["account-DQ.yaml", "account-NEW.yaml", "account-sample.yaml"]:
            (config_dir / name).touch()
        loader.config_dir = config_dir

        with patch("qtrader.manager.manager.get_config_loader", return_value=loader):
            assert manager.get_available_accounts() == ["NEW"]


@pytest.mark.unit
class TestAddRemoveAccount:
    """添加/删除账户"""

    @pytest.mark.asyncio
    async def test_add_existing_fails(self, manager):
        assert await manager.add_account("DQ") is False

    @pytest.mark.asyncio
    async def test_add_missing_file_fails(self, manager):
        loader = MagicMock()
        loader._load_account_config.side_effect = FileNotFoundError("no file")
        with patch("qtrader.manager.manager.get_config_loader", return_value=loader):
            assert await manager.add_account("NEW") is False

    @pytest.mark.asyncio
    async def test_add_account_success(self, manager):
        loader = MagicMock()
        new_config = make_account_config("NEW")
        loader._load_account_config.return_value = new_config
        loader._load_app_config.return_value = Mock(account_ids=["DQ", "GW"])

        with (
            patch("qtrader.manager.manager.get_config_loader", return_value=loader),
            patch("qtrader.manager.manager.TraderProxy"),
        ):
            assert await manager.add_account("NEW") is True

        assert "NEW" in manager.account_configs_map
        loader.update_account_ids.assert_called_once_with(["DQ", "GW", "NEW"])

    @pytest.mark.asyncio
    async def test_add_account_id_mismatch_fails(self, manager):
        loader = MagicMock()
        wrong = make_account_config("OTHER")
        loader._load_account_config.return_value = wrong
        with patch("qtrader.manager.manager.get_config_loader", return_value=loader):
            assert await manager.add_account("NEW") is False

    @pytest.mark.asyncio
    async def test_remove_not_added_fails(self, manager):
        assert await manager.remove_account("GHOST") is False

    @pytest.mark.asyncio
    async def test_remove_running_account_raises(self, manager):
        manager.traders["DQ"] = make_proxy(running=True)
        with pytest.raises(ValueError, match="正在运行"):
            await manager.remove_account("DQ")

    @pytest.mark.asyncio
    async def test_remove_account_success(self, manager):
        proxy = make_proxy()
        manager.traders["DQ"] = proxy
        loader = MagicMock()
        loader._load_app_config.return_value = Mock(account_ids=["DQ", "GW"])

        with patch("qtrader.manager.manager.get_config_loader", return_value=loader):
            assert await manager.remove_account("DQ") is True

        proxy.stop_monitoring.assert_awaited_once()
        assert "DQ" not in manager.traders
        assert "DQ" not in manager.account_configs_map
        loader.update_account_ids.assert_called_once_with(["GW"])


@pytest.mark.unit
class TestTraderLifecycle:
    """启动/停止/重启"""

    @pytest.mark.asyncio
    async def test_start_no_proxy_fails(self, manager):
        assert await manager.start_trader("DQ") is False

    @pytest.mark.asyncio
    async def test_start_delegates(self, manager):
        proxy = make_proxy()
        manager.traders["DQ"] = proxy
        assert await manager.start_trader("DQ") is True
        proxy.start_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_process_false(self, manager):
        proxy = make_proxy()
        proxy.start_process.return_value = False
        manager.traders["DQ"] = proxy
        assert await manager.start_trader("DQ") is False

    @pytest.mark.asyncio
    async def test_start_exception_fails(self, manager):
        proxy = make_proxy()
        proxy.start_process.side_effect = RuntimeError("boom")
        manager.traders["DQ"] = proxy
        assert await manager.start_trader("DQ") is False

    @pytest.mark.asyncio
    async def test_stop_no_proxy_fails(self, manager):
        assert await manager.stop_trader("DQ") is False

    @pytest.mark.asyncio
    async def test_stop_delegates(self, manager):
        proxy = make_proxy()
        manager.traders["DQ"] = proxy
        assert await manager.stop_trader("DQ") is True
        proxy.stop_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restart_stops_then_starts(self, manager):
        proxy = make_proxy()
        manager.traders["DQ"] = proxy
        assert await manager.restart_trader("DQ") is True
        proxy.stop_process.assert_awaited_once()
        proxy.start_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restart_aborts_if_stop_fails(self, manager):
        """停止失败时中止重启，避免半启动状态"""
        proxy = make_proxy()
        proxy.stop_process.return_value = False
        manager.traders["DQ"] = proxy
        assert await manager.restart_trader("DQ") is False
        proxy.start_process.assert_not_awaited()


@pytest.mark.unit
class TestStatusQueries:
    """状态查询"""

    def test_is_running(self, manager):
        assert manager.is_running("DQ") is False
        manager.traders["DQ"] = make_proxy(running=True)
        assert manager.is_running("DQ") is True

    def test_get_trader_status_missing(self, manager):
        assert manager.get_trader_status("DQ") is None

    def test_get_trader_status(self, manager):
        proxy = make_proxy()
        manager.traders["DQ"] = proxy
        assert manager.get_trader_status("DQ") == {"account_id": "DQ", "state": "stopped"}

    def test_get_all_trader_status(self, manager):
        manager.traders["DQ"] = make_proxy()
        manager.traders["GW"] = make_proxy()
        assert len(manager.get_all_trader_status()) == 2

    def test_get_all_account_ids(self, manager):
        manager.traders["DQ"] = make_proxy()
        assert manager.get_all_account_ids() == ["DQ"]

    def test_get_trader(self, manager):
        proxy = make_proxy()
        manager.traders["DQ"] = proxy
        assert manager.get_trader("DQ") is proxy
        assert manager.get_trader("GHOST") is None

    def test_get_trader_mode(self, manager):
        assert manager.get_trader_mode("DQ") is None
        manager.traders["DQ"] = make_proxy()
        assert manager.get_trader_mode("DQ") == "standalone"

    def test_get_all_accounts_cached(self, manager):
        proxy = make_proxy()
        proxy.get_account_cached.return_value = AccountData(account_id="DQ", balance=1.0)
        manager.traders["DQ"] = proxy
        accounts = manager.get_all_accounts_cached()
        assert len(accounts) == 1
        assert accounts[0].account_id == "DQ"


@pytest.mark.unit
class TestTradingRequests:
    """交易请求转发"""

    @pytest.mark.asyncio
    async def test_send_order_no_trader(self, manager):
        result = await manager.send_order_request(
            "DQ", "SHFE.rb2505", Direction.BUY, Offset.OPEN, 1
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_order_forwards(self, manager):
        proxy = make_proxy()
        proxy.send_order_request = AsyncMock(return_value="order_1")
        manager.traders["DQ"] = proxy

        result = await manager.send_order_request(
            "DQ", "SHFE.rb2505", Direction.BUY, Offset.OPEN, 2, price=3500.0
        )

        assert result == "order_1"
        proxy.send_order_request.assert_awaited_once_with("SHFE.rb2505", "BUY", "OPEN", 2, 3500.0)

    @pytest.mark.asyncio
    async def test_send_cancel_no_trader(self, manager):
        assert await manager.send_cancel_request("DQ", "order_1") is False

    @pytest.mark.asyncio
    async def test_send_cancel_forwards(self, manager):
        proxy = make_proxy()
        proxy.send_cancel_request = AsyncMock(return_value=True)
        manager.traders["DQ"] = proxy
        assert await manager.send_cancel_request("DQ", "order_1") is True
        proxy.send_cancel_request.assert_awaited_once_with("order_1")


@pytest.mark.unit
class TestSchedulerFacade:
    """Manager 级定时任务"""

    def test_get_task_scheduler_always_none(self, manager):
        assert manager.get_task_scheduler("DQ") is None

    def test_scheduler_jobs_empty_without_scheduler(self, manager):
        assert manager.get_manager_scheduler_jobs() == []

    def test_operate_job_without_scheduler(self, manager):
        assert manager.operate_manager_scheduler_job("job_1", "pause") is False

    def test_toggle_job_without_scheduler(self, manager):
        assert manager.toggle_manager_scheduler_job("job_1", True) is False

    def test_toggle_job_delegates(self, manager):
        scheduler = MagicMock()
        scheduler.update_job_status.return_value = True
        manager._scheduler = scheduler
        assert manager.toggle_manager_scheduler_job("job_1", True) is True
        scheduler.update_job_status.assert_called_once_with("job_1", True)


@pytest.mark.unit
class TestDataQueries:
    """数据查询"""

    @pytest.mark.asyncio
    async def test_sync_account_missing(self, manager):
        assert await manager.sync_account("GHOST") is None

    @pytest.mark.asyncio
    async def test_sync_account_data_missing(self, manager):
        result = await manager.sync_account_data("GHOST")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_sync_account_data_exception(self, manager):
        proxy = make_proxy()
        proxy.sync_all = AsyncMock(side_effect=RuntimeError("boom"))
        manager.traders["DQ"] = proxy
        result = await manager.sync_account_data("DQ")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_sync_account_data_ok(self, manager):
        proxy = make_proxy()
        proxy.sync_all = AsyncMock(return_value={"success": True, "message": "ok"})
        manager.traders["DQ"] = proxy
        result = await manager.sync_account_data("DQ")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_account_missing(self, manager):
        assert await manager.get_account("GHOST") is None

    @pytest.mark.asyncio
    async def test_get_all_accounts(self, manager):
        proxy = make_proxy()
        proxy.get_account = AsyncMock(return_value=AccountData(account_id="DQ", balance=1.0))
        manager.traders["DQ"] = proxy
        accounts = await manager.get_all_accounts()
        assert len(accounts) == 1
