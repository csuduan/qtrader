"""
TraderProxy 单元测试

覆盖当前 API 的核心行为：初始化状态、状态机、心跳存活判定、
账户推送缓存、持仓盈亏计算、请求通道（未连接拒绝/连接后转发）、暂停恢复。
不启动真实子进程与 socket。
"""

import asyncio
import os
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio

from qtrader.manager.trader_proxy import TraderProxy
from qtrader.models.object import AccountData, PositionData, TickData, TraderState


def make_account_config() -> MagicMock:
    config = MagicMock()
    config.account_id = "test_account_001"
    return config


@pytest_asyncio.fixture
async def proxy(tmp_path):
    """构建 TraderProxy 并终止其后台连接任务（测试不驱动连接循环）"""
    with (
        patch("qtrader.manager.trader_proxy.get_config_loader") as mock_loader,
        patch("qtrader.manager.trader_proxy.ctx") as mock_ctx,
    ):
        mock_loader.return_value._load_app_config.return_value = Mock(
            paths=Mock(socket_dir=str(tmp_path))
        )
        mock_ctx.get_event_engine.return_value = MagicMock()
        p = TraderProxy(make_account_config(), heartbeat_timeout=30)
        for task in (p._connect_task, p._socket_monitor_task):
            if task:
                task.cancel()
        yield p
        for task in (p._connect_task, p._socket_monitor_task):
            if task and not task.done():
                task.cancel()


async def _wait_background_tasks() -> None:
    """等待事件循环中已创建的后台任务结束（覆盖 create_task 包装的异步落库路径）"""
    current = asyncio.current_task()
    pending = {task for task in asyncio.all_tasks() if task is not current}
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.unit
class TestTraderProxyInit:
    """初始化状态"""

    @pytest.mark.asyncio
    async def test_init_basic_attributes(self, proxy):
        assert proxy.account_id == "test_account_001"
        assert proxy.heartbeat_timeout == 30

    @pytest.mark.asyncio
    async def test_socket_path_derived_from_socket_dir(self, proxy, tmp_path):
        assert proxy.socket_path == f"{tmp_path}/qtrader_test_account_001.sock"
        assert proxy.pid_file == f"{tmp_path}/qtrader_test_account_001.pid"

    @pytest.mark.asyncio
    async def test_initial_state(self, proxy):
        assert proxy.get_state() == TraderState.STOPPED
        assert proxy.is_running() is False
        assert proxy.manual_stop is False
        assert proxy._created_process is False
        assert proxy.start_time is None
        assert proxy.restart_count == 0


@pytest.mark.unit
class TestTraderProxyState:
    """状态机与状态查询"""

    @pytest.mark.asyncio
    async def test_set_state_transitions(self, proxy):
        await proxy._set_state(TraderState.CONNECTING)
        assert proxy.get_state() == TraderState.CONNECTING
        assert proxy.is_running() is True

        await proxy._set_state(TraderState.CONNECTED)
        assert proxy.get_state() == TraderState.CONNECTED

    @pytest.mark.asyncio
    async def test_get_status_structure(self, proxy):
        status = proxy.get_status()
        assert status["account_id"] == "test_account_001"
        assert status["state"] == "stopped"
        assert status["running"] is False
        assert status["connected"] is False
        assert status["connecting"] is False
        assert status["created_process"] is False
        assert status["socket_path"] == proxy.socket_path
        assert status["start_time"] is None
        assert status["last_heartbeat"] is not None


@pytest.mark.unit
class TestTraderProxyAlive:
    """心跳存活判定（非自建进程走心跳路径）"""

    @pytest.mark.asyncio
    async def test_stopped_is_not_alive(self, proxy):
        assert proxy.is_alive() is False

    @pytest.mark.asyncio
    async def test_fresh_heartbeat_is_alive(self, proxy):
        await proxy._set_state(TraderState.CONNECTED)
        proxy._update_heartbeat()
        assert proxy.is_alive() is True

    @pytest.mark.asyncio
    async def test_stale_heartbeat_not_alive(self, proxy):
        await proxy._set_state(TraderState.CONNECTED)
        proxy.last_heartbeat = datetime.now() - timedelta(seconds=proxy.heartbeat_timeout + 1)
        assert proxy.is_alive() is False


@pytest.mark.unit
class TestTraderProxyAccountUpdate:
    """账户推送缓存"""

    @pytest.mark.asyncio
    async def test_account_update_refreshes_cache_and_emits(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=100.0)

        proxy._handle_account_update(
            {
                "account_id": "test_account_001",
                "balance": 200000.0,
                "available": 150000.0,
                "md_connected": True,
                "td_connected": True,
            }
        )

        assert proxy._account_cache.balance == 200000.0
        assert proxy._account_cache.md_connected is True

    @pytest.mark.asyncio
    async def test_get_account_cached(self, proxy):
        # 无缓存时返回仅含 account_id/status 的默认对象
        fallback = proxy.get_account_cached()
        assert fallback.account_id == "test_account_001"
        assert fallback.status == TraderState.STOPPED

        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        cached = proxy.get_account_cached()
        assert cached.balance == 1.0
        assert cached is not proxy._account_cache  # 返回副本

        # 已连接状态下副本的 status 被改写为 CONNECTED
        await proxy._set_state(TraderState.CONNECTED)
        assert proxy.get_account_cached().status == TraderState.CONNECTED


@pytest.mark.unit
class TestTraderProxyHoldProfit:
    """持仓盈亏计算"""

    @pytest.mark.asyncio
    async def test_update_hold_profit_long(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        pos = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            multiple=10,
            pos_long_td=2,
            hold_price_long=3500.0,
        )
        proxy._position_cache["SHFE.rb2505"] = pos

        tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3550.0)
        proxy.update_hold_profit(tick)

        # (3550 - 3500) * 2 * 10 = 1000
        assert pos.hold_profit_long == 1000.0

    @pytest.mark.asyncio
    async def test_update_hold_profit_ignores_unknown_symbol(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        tick = TickData.model_construct(symbol="SHFE.hc2505", last_price=3550.0)
        proxy.update_hold_profit(tick)  # 无持仓，不应抛错
        assert proxy._position_cache == {}

    @pytest.mark.asyncio
    async def test_recalc_position_profit_short(self, proxy):
        pos = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            pos_short_yd=3,
            hold_price_short=3500.0,
        )
        # 乘数取自 tick 缓存
        proxy._tick_cache["SHFE.rb2505"] = {"volume_multiple": 10}
        result = proxy._recalc_position_profit(pos, 3450.0)
        # (3500-3450)*3*10 = 1500
        assert result.hold_profit_short == 1500.0

    @pytest.mark.asyncio
    async def test_recalc_position_profit_default_multiple(self, proxy):
        pos = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            pos_short_yd=3,
            hold_price_short=3500.0,
        )
        result = proxy._recalc_position_profit(pos, 3450.0)
        # 无 tick 缓存时默认乘数1: (3500-3450)*3 = 150
        assert result.hold_profit_short == 150.0

    @pytest.mark.asyncio
    async def test_position_push_throttled(self, proxy):
        """2秒推送窗口内同一合约只推送一次"""
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        pos = PositionData(
            symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=1, hold_price_long=3500.0
        )
        proxy._position_cache["SHFE.rb2505"] = pos

        with patch.object(proxy, "_emit_data") as mock_emit:
            tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3550.0)
            proxy.update_hold_profit(tick)
            proxy.update_hold_profit(tick)

        mock_emit.assert_called_once()


@pytest.mark.unit
class TestTraderProxyRequests:
    """请求通道"""

    @pytest.mark.asyncio
    async def test_send_request_not_connected_returns_none(self, proxy):
        assert await proxy.send_request("get_orders", {}) is None

    @pytest.mark.asyncio
    async def test_pause_not_connected_fails(self, proxy):
        assert await proxy.pause() is False

    @pytest.mark.asyncio
    async def test_pause_sends_request_when_connected(self, proxy):
        proxy.socket_client = MagicMock()
        proxy.socket_client.is_connected.return_value = True
        proxy.socket_client.request = AsyncMock(return_value={"success": True})

        assert await proxy.pause() is True
        proxy.socket_client.request.assert_awaited_once_with("pause_trading", {}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_resume_sends_request_when_connected(self, proxy):
        proxy.socket_client = MagicMock()
        proxy.socket_client.is_connected.return_value = True
        proxy.socket_client.request = AsyncMock(return_value={"success": True})

        assert await proxy.resume() is True
        proxy.socket_client.request.assert_awaited_once_with("resume_trading", {}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_request_exception_returns_falsy(self, proxy):
        proxy.socket_client = MagicMock()
        proxy.socket_client.is_connected.return_value = True
        proxy.socket_client.request = AsyncMock(side_effect=RuntimeError("boom"))

        assert await proxy.pause() is False


def connect_proxy(proxy) -> MagicMock:
    """为 proxy 挂载一个已连接的 mock socket client，返回该 client"""
    client = MagicMock()
    client.is_connected.return_value = True
    client.request = AsyncMock()
    proxy.socket_client = client
    return client


def order_dict(order_id: str = "O1") -> dict:
    """构造可通过 OrderData 校验的订单字典"""
    return {
        "order_id": order_id,
        "symbol": "SHFE.rb2505",
        "direction": "BUY",
        "offset": "OPEN",
        "volume": 1,
        "account_id": "test_account_001",
    }


def trade_dict(trade_id: str = "T1") -> dict:
    """构造可通过 TradeData 校验的成交字典"""
    return {
        "trade_id": trade_id,
        "order_id": "O1",
        "symbol": "SHFE.rb2505",
        "direction": "BUY",
        "offset": "OPEN",
        "price": 3500.0,
        "volume": 1,
        "account_id": "test_account_001",
    }


def position_dict(symbol: str = "SHFE.rb2505") -> dict:
    """构造可通过 PositionData 校验的持仓字典"""
    return {"symbol": symbol, "exchange": "SHFE"}


def tick_dict(symbol: str = "SHFE.rb2505") -> dict:
    """构造可通过 TickData 校验的行情字典"""
    return {
        "symbol": symbol,
        "exchange": "SHFE",
        "datetime": "2026-09-04 10:00:00",
        "last_price": 3550.0,
    }


@pytest.mark.unit
class TestTraderProxyStartProcess:
    """start_process 子进程启动"""

    @pytest.mark.asyncio
    async def test_refuses_when_process_exists(self, proxy):
        """进程已存在时不允许重复启动"""
        proxy._manual_stop = True
        with patch.object(proxy, "_get_process", AsyncMock(return_value=123)):
            result = await proxy.start_process()
        assert result is False
        assert proxy._created_process is False

    @pytest.mark.asyncio
    async def test_launches_shell_command(self, proxy):
        """启动时应以 nohup shell 方式拉起 run_trader.py"""
        proxy.account_config.debug = False
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=None)),
            patch(
                "qtrader.manager.trader_proxy.asyncio.create_subprocess_shell",
                AsyncMock(return_value=Mock(pid=999)),
            ) as mock_spawn,
        ):
            result = await proxy.start_process()
        assert result is True
        assert proxy._created_process is True
        assert proxy._manual_stop is False
        shell_cmd = mock_spawn.await_args[0][0]
        assert shell_cmd.startswith("nohup ")
        assert "run_trader.py --account-id test_account_001" in shell_cmd
        assert shell_cmd.endswith("&")
        assert "--debug" not in shell_cmd

    @pytest.mark.asyncio
    async def test_debug_flag_appended(self, proxy):
        """账户配置 debug 开启时应追加 --debug 参数"""
        proxy.account_config.debug = True
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=None)),
            patch(
                "qtrader.manager.trader_proxy.asyncio.create_subprocess_shell",
                AsyncMock(return_value=Mock(pid=999)),
            ) as mock_spawn,
        ):
            assert await proxy.start_process() is True
        assert "--debug" in mock_spawn.await_args[0][0]


@pytest.mark.unit
class TestTraderProxyStopProcess:
    """stop_process 优雅停止"""

    @pytest.mark.asyncio
    async def test_stop_without_process_marks_stopped(self, proxy):
        """无进程时直接置为 STOPPED 并返回成功"""
        with patch.object(proxy, "_get_process", AsyncMock(return_value=None)):
            result = await proxy.stop_process()
        assert result is True
        assert proxy.get_state() == TraderState.STOPPED
        assert proxy.manual_stop is True

    @pytest.mark.asyncio
    async def test_stop_sends_sigterm(self, proxy):
        """进程存在时应发送 SIGTERM，退出后置为 STOPPED"""
        with (
            patch.object(proxy, "_get_process", AsyncMock(side_effect=[111, None, None, None])),
            patch("qtrader.manager.trader_proxy.os.kill") as mock_kill,
            patch("qtrader.manager.trader_proxy.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await proxy.stop_process()
        assert result is True
        mock_kill.assert_any_call(111, 0)
        mock_kill.assert_any_call(111, signal.SIGTERM)
        assert proxy.get_state() == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_escalates_to_sigkill(self, proxy):
        """SIGTERM 后进程仍在时应升级为 SIGKILL，退出后返回成功"""
        with (
            patch.object(
                proxy, "_get_process", AsyncMock(side_effect=[111] * 7 + [None, None])
            ),
            patch("qtrader.manager.trader_proxy.os.kill") as mock_kill,
            patch("qtrader.manager.trader_proxy.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await proxy.stop_process()
        assert result is True
        mock_kill.assert_any_call(111, signal.SIGTERM)
        mock_kill.assert_any_call(111, signal.SIGKILL)
        assert proxy.get_state() == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_reports_failure_when_process_survives(self, proxy):
        """SIGTERM+SIGKILL 均无法停止时返回 False，状态保持不变"""
        await proxy._set_state(TraderState.CONNECTED)
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=111)),
            patch("qtrader.manager.trader_proxy.os.kill") as mock_kill,
            patch("qtrader.manager.trader_proxy.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await proxy.stop_process()
        assert result is False
        mock_kill.assert_any_call(111, signal.SIGTERM)
        mock_kill.assert_any_call(111, signal.SIGKILL)
        assert proxy.get_state() == TraderState.CONNECTED

    @pytest.mark.asyncio
    async def test_stop_sigterm_failure_still_proceeds(self, proxy):
        """发送 SIGTERM 失败时记录告警并继续检测"""
        with (
            patch.object(proxy, "_get_process", AsyncMock(side_effect=[111, None, None, None])),
            patch("qtrader.manager.trader_proxy.os.kill", side_effect=OSError("no such process")),
            patch("qtrader.manager.trader_proxy.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await proxy.stop_process()
        assert result is True
        assert proxy.get_state() == TraderState.STOPPED


@pytest.mark.unit
class TestTraderProxyConnectLoop:
    """_connect_async 连接循环"""

    @pytest.mark.asyncio
    async def test_no_process_sets_stopped(self, proxy):
        """进程不存在时状态置为 STOPPED 并创建 socket client"""
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=None)),
            patch("qtrader.manager.trader_proxy.SocketClient") as mock_client_cls,
        ):
            task = asyncio.create_task(proxy._connect_async())
            await asyncio.to_thread(time.sleep, 0.1)
            assert proxy.get_state() == TraderState.STOPPED
            assert proxy.socket_client is mock_client_cls.return_value
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_connect_success_syncs_data(self, proxy):
        """连接成功后状态置为 CONNECTED 并触发全量同步"""
        client = MagicMock()
        client.is_connected = MagicMock(side_effect=[False, True, True, True])
        client.connect = AsyncMock(return_value=True)
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=123)),
            patch("qtrader.manager.trader_proxy.SocketClient", return_value=client),
            patch.object(proxy, "_sync_account_detail", AsyncMock()) as mock_sync,
        ):
            task = asyncio.create_task(proxy._connect_async())
            await asyncio.to_thread(time.sleep, 0.2)
            assert proxy.get_state() == TraderState.CONNECTED
            client.connect.assert_awaited_once()
            mock_sync.assert_awaited_once()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_connect_failure_stays_connecting(self, proxy):
        """连接失败时保持 CONNECTING 并等待重试"""
        client = MagicMock()
        client.is_connected.return_value = False
        client.connect = AsyncMock(return_value=False)
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=123)),
            patch("qtrader.manager.trader_proxy.SocketClient", return_value=client),
        ):
            task = asyncio.create_task(proxy._connect_async())
            await asyncio.to_thread(time.sleep, 0.2)
            assert proxy.get_state() == TraderState.CONNECTING
            client.connect.assert_awaited_once()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.unit
class TestTraderProxyGetProcess:
    """_get_process 进程探测"""

    @pytest.mark.asyncio
    async def test_no_socket_file_returns_none(self, proxy):
        assert await proxy._get_process() is None

    @pytest.mark.asyncio
    async def test_no_pid_file_returns_none(self, proxy):
        Path(proxy.socket_path).touch()
        assert await proxy._get_process() is None

    @pytest.mark.asyncio
    async def test_live_pid_returned(self, proxy):
        Path(proxy.socket_path).touch()
        Path(proxy.pid_file).write_text(str(os.getpid()))
        assert await proxy._get_process() == os.getpid()

    @pytest.mark.asyncio
    async def test_dead_pid_cleans_pid_file(self, proxy):
        Path(proxy.socket_path).touch()
        Path(proxy.pid_file).write_text("99999999")
        with patch("qtrader.manager.trader_proxy.os.kill", side_effect=OSError):
            assert await proxy._get_process() is None
        assert not Path(proxy.pid_file).exists()

    @pytest.mark.asyncio
    async def test_invalid_pid_file_returns_none(self, proxy):
        Path(proxy.socket_path).touch()
        Path(proxy.pid_file).write_text("not-a-pid")
        assert await proxy._get_process() is None


@pytest.mark.unit
class TestTraderProxyLoadAccountFromDb:
    """_load_account_from_db_async 初始缓存加载"""

    @pytest.mark.asyncio
    async def test_no_database_returns_silently(self, proxy):
        with patch("qtrader.utils.async_database.get_async_database", return_value=None):
            await proxy._load_account_from_db_async()
        assert proxy._account_cache is None

    @pytest.mark.asyncio
    async def test_loads_po_fields_into_cache(self, proxy):
        po = SimpleNamespace(
            account_id="test_account_001",
            balance=1000.5,
            available=800.25,
            margin=200.25,
            position_profit=10.5,
            close_profit=5.5,
            risk_ratio=0.2,
        )
        session = MagicMock()
        session.scalar = AsyncMock(return_value=po)
        db = MagicMock()
        db.get_session.return_value.__aenter__.return_value = session
        db.get_session.return_value.__aexit__.return_value = False
        with patch("qtrader.utils.async_database.get_async_database", return_value=db):
            await proxy._load_account_from_db_async()
        assert proxy._account_cache.balance == 1000.5
        assert proxy._account_cache.available == 800.25
        assert proxy._account_cache.margin == 200.25
        assert proxy._account_cache.hold_profit == 10.5
        assert proxy._account_cache.close_profit == 5.5
        assert proxy._account_cache.risk_ratio == 0.2
        assert proxy._account_cache.md_connected is False
        assert proxy._account_cache.td_connected is False

    @pytest.mark.asyncio
    async def test_no_account_row_keeps_cache_empty(self, proxy):
        session = MagicMock()
        session.scalar = AsyncMock(return_value=None)
        db = MagicMock()
        db.get_session.return_value.__aenter__.return_value = session
        db.get_session.return_value.__aexit__.return_value = False
        with patch("qtrader.utils.async_database.get_async_database", return_value=db):
            await proxy._load_account_from_db_async()
        assert proxy._account_cache is None

    @pytest.mark.asyncio
    async def test_db_error_swallowed(self, proxy):
        with patch(
            "qtrader.utils.async_database.get_async_database",
            side_effect=RuntimeError("db down"),
        ):
            await proxy._load_account_from_db_async()
        assert proxy._account_cache is None


@pytest.mark.unit
class TestTraderProxySyncAccountDetail:
    """get_account_details 一次性全量同步"""

    @pytest.mark.asyncio
    async def test_not_connected_returns(self, proxy):
        await proxy._sync_account_detail()
        assert proxy._position_cache == {}

    @pytest.mark.asyncio
    async def test_invalid_response_returns(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value="bad-response")
        await proxy._sync_account_detail()
        assert proxy._account_cache is None

    @pytest.mark.asyncio
    async def test_full_payload_updates_all_caches(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(
            return_value={
                "account": {"account_id": "test_account_001", "balance": 500.0},
                "positions": [position_dict()],
                "orders": [order_dict()],
                "trades": [trade_dict()],
                "quotes": [{"symbol": "SHFE.rb2505", "volume_multiple": 10}],
            }
        )
        with patch.object(proxy, "_emit_data") as mock_emit:
            await proxy._sync_account_detail()
        client.request.assert_awaited_once_with("get_account_details", {}, timeout=10.0)
        assert proxy._account_cache.balance == 500.0
        assert list(proxy._position_cache) == ["SHFE.rb2505"]
        assert list(proxy._order_cache) == ["O1"]
        assert list(proxy._trade_cache) == ["T1"]
        assert proxy._tick_cache["SHFE.rb2505"]["volume_multiple"] == 10
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "account"

    @pytest.mark.asyncio
    async def test_invalid_items_skipped(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(
            return_value={
                "account": None,
                "positions": [{"no_symbol": True}, position_dict("SHFE.hc2505")],
                "orders": [{"no_order_id": True}],
                "trades": [{"no_trade_id": True}],
                "quotes": ["not-a-dict"],
            }
        )
        await proxy._sync_account_detail()
        assert proxy._account_cache is None
        assert list(proxy._position_cache) == ["SHFE.hc2505"]
        assert proxy._order_cache == {}
        assert proxy._trade_cache == {}


@pytest.mark.unit
class TestTraderProxyMsgCallback:
    """_on_msg_callback 推送消息处理"""

    @pytest.mark.asyncio
    async def test_heartbeat_updates_timestamp(self, proxy):
        proxy.last_heartbeat = datetime(2020, 1, 1)
        proxy._on_msg_callback("heartbeat", {})
        assert proxy.last_heartbeat > datetime(2020, 1, 1)

    @pytest.mark.asyncio
    async def test_tick_updates_cache_and_emits(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        data = tick_dict()
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("tick", data)
        assert proxy._tick_cache["SHFE.rb2505"] is data
        mock_emit.assert_called_once_with("tick", data)

    @pytest.mark.asyncio
    async def test_tick_without_symbol_ignored(self, proxy):
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("tick", {"last_price": 1.0})
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_batch_emits_and_throttles_account(self, proxy):
        proxy._account_cache_time = None
        data = {
            "ticks": [tick_dict()],
            "account": {"account_id": "test_account_001", "balance": 9.0},
        }
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("tick_batch", data)
            call_types = [c.args[0] for c in mock_emit.call_args_list]
            assert call_types == ["tick_batch", "account"]
            # 2秒窗口内第二次推送只发 tick_batch，不再发 account
            proxy._on_msg_callback("tick_batch", data)
            assert mock_emit.call_count == 3
        assert proxy._account_cache.balance == 9.0
        assert proxy._tick_cache["SHFE.rb2505"]["last_price"] == 3550.0

    @pytest.mark.asyncio
    async def test_tick_batch_empty_ticks_no_batch_emit(self, proxy):
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("tick_batch", {"ticks": [], "account": None})
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_account_push_updates_cache(self, proxy):
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback(
                "account",
                {"account_id": "test_account_001", "balance": 321.0, "td_connected": True},
            )
        assert proxy._account_cache.balance == 321.0
        assert mock_emit.call_args[0][0] == "account"

    @pytest.mark.asyncio
    async def test_order_push_updates_cache(self, proxy):
        data = order_dict("O9")
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("order", data)
        assert proxy._order_cache["O9"].symbol == "SHFE.rb2505"
        mock_emit.assert_called_once_with("order", data)

    @pytest.mark.asyncio
    async def test_order_without_id_not_cached(self, proxy):
        data = {"symbol": "SHFE.rb2505"}
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("order", data)
        assert proxy._order_cache == {}
        mock_emit.assert_called_once_with("order", data)

    @pytest.mark.asyncio
    async def test_trade_push_updates_cache(self, proxy):
        data = trade_dict("T9")
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("trade", data)
        assert proxy._trade_cache["T9"].price == 3500.0
        mock_emit.assert_called_once_with("trade", data)

    @pytest.mark.asyncio
    async def test_position_push_updates_cache(self, proxy):
        data = position_dict("SHFE.hc2505")
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("position", data)
        assert proxy._position_cache["SHFE.hc2505"].exchange.value == "SHFE"
        mock_emit.assert_called_once_with("position", data)

    @pytest.mark.asyncio
    async def test_trader_ready_triggers_delayed_sync(self, proxy):
        with (
            patch.object(proxy, "_sync_account_detail", AsyncMock()) as mock_sync,
            patch("qtrader.manager.trader_proxy.asyncio.sleep", new_callable=AsyncMock),
        ):
            proxy._on_msg_callback("trader_ready", {})
            await asyncio.to_thread(time.sleep, 0.05)
        mock_sync.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_type_forwarded(self, proxy):
        with patch.object(proxy, "_emit_data") as mock_emit:
            proxy._on_msg_callback("custom_type", {"foo": 1})
        mock_emit.assert_called_once_with("custom_type", {"foo": 1})


@pytest.mark.unit
class TestTraderProxyNotifyPush:
    """notify 推送的告警转发"""

    @pytest.mark.asyncio
    async def test_notify_without_context_ignored(self, proxy):
        with patch("qtrader.app_context.get_app_context", return_value=None):
            proxy._on_msg_callback("notify", {"title": "t"})
        # 不应抛出

    @pytest.mark.asyncio
    async def test_notify_without_alarm_service_ignored(self, proxy):
        ctx = MagicMock()
        ctx.get_alarm_service.return_value = None
        with patch("qtrader.app_context.get_app_context", return_value=ctx):
            proxy._on_msg_callback("notify", {"title": "t"})
        # 不应抛出

    @pytest.mark.asyncio
    async def test_notify_forwards_to_alarm_service(self, proxy):
        alarm_service = MagicMock()
        ctx = MagicMock()
        ctx.get_alarm_service.return_value = alarm_service
        with patch("qtrader.app_context.get_app_context", return_value=ctx):
            proxy._on_msg_callback(
                "notify",
                {"account_id": "test_account_001", "title": "风险提示", "detail": "详情"},
            )
            for _ in range(40):
                if alarm_service.notify_alarm.called:
                    break
                await asyncio.sleep(0.05)
        alarm_service.notify_alarm.assert_called_once_with(
            "test_account_001", "Trader", "风险提示", "详情"
        )


@pytest.mark.unit
class TestTraderProxySyncAll:
    """sync_all 手动全量同步"""

    @pytest.mark.asyncio
    async def test_not_connected_fails(self, proxy):
        result = await proxy.sync_all()
        assert result == {"success": False, "message": "未连接到Trader"}

    @pytest.mark.asyncio
    async def test_sync_all_returns_cache_counts(self, proxy):
        connect_proxy(proxy)
        proxy._position_cache["SHFE.rb2505"] = PositionData(**position_dict())
        proxy._order_cache["O1"] = order_dict()
        proxy._tick_cache["SHFE.rb2505"] = tick_dict()
        with patch.object(proxy, "_sync_account_detail", AsyncMock()):
            result = await proxy.sync_all()
        assert result["success"] is True
        assert result["account_id"] == "test_account_001"
        assert result["positions"] == 1
        assert result["orders"] == 1
        assert result["trades"] == 0
        assert result["quotes"] == 1

    @pytest.mark.asyncio
    async def test_sync_all_error_returns_failure(self, proxy):
        connect_proxy(proxy)
        with patch.object(
            proxy, "_sync_account_detail", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            result = await proxy.sync_all()
        assert result["success"] is False
        assert "boom" in result["message"]


@pytest.mark.unit
class TestTraderProxyQueryRpc:
    """数据查询接口的参数编组与响应解包"""

    @pytest.mark.asyncio
    async def test_get_account_from_trader_merges_cache(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"balance": 777.0})
        result = await proxy.get_account()
        client.request.assert_awaited_once_with("get_account", {}, timeout=5.0)
        assert result.balance == 777.0
        assert result.account_id == "test_account_001"
        assert result.status == TraderState.CONNECTED
        assert proxy._account_cache.balance == 777.0

    @pytest.mark.asyncio
    async def test_get_account_request_error_falls_back_to_cache(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=5.0)
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        result = await proxy.get_account()
        assert result.balance == 5.0
        assert result.status == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_get_account_without_cache_and_connection(self, proxy):
        result = await proxy.get_account()
        assert result.account_id == "test_account_001"
        assert result.status == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_get_orders_refreshes_cache(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=[order_dict("O1"), {"bad": 1}])
        proxy._order_cache["OLD"] = order_dict("OLD")
        result = await proxy.get_orders()
        client.request.assert_awaited_once_with("get_orders", {}, timeout=5.0)
        assert [o.order_id for o in result] == ["O1"]
        assert list(proxy._order_cache) == ["O1"]

    @pytest.mark.asyncio
    async def test_get_orders_without_connection_returns_cache(self, proxy):
        from qtrader.models.object import OrderData

        proxy._order_cache["O1"] = OrderData(**order_dict())
        result = await proxy.get_orders()
        assert [o.order_id for o in result] == ["O1"]

    @pytest.mark.asyncio
    async def test_get_active_orders_filters(self, proxy):
        from qtrader.models.object import OrderData

        active = OrderData(**order_dict("O1"))  # 默认状态 PENDING
        finished = OrderData(**{**order_dict("O2"), "status": "FINISHED"})
        proxy._order_cache["O1"] = active
        proxy._order_cache["O2"] = finished
        result = await proxy.get_active_orders()
        assert [o.order_id for o in result] == ["O1"]

    @pytest.mark.asyncio
    async def test_get_positions_refreshes_cache(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=[position_dict()])
        result = await proxy.get_positions()
        client.request.assert_awaited_once_with("get_positions", {}, timeout=5.0)
        assert [p.symbol for p in result] == ["SHFE.rb2505"]

    @pytest.mark.asyncio
    async def test_get_trade_and_trades_from_cache(self, proxy):
        from qtrader.models.object import TradeData

        proxy._trade_cache["T1"] = TradeData(**trade_dict())
        assert (await proxy.get_trade("T1")).price == 3500.0
        assert (await proxy.get_trade("NOPE")) is None
        assert len(await proxy.get_trades()) == 1

    @pytest.mark.asyncio
    async def test_get_quotes_builds_tick_objects(self, proxy):
        proxy._tick_cache["SHFE.rb2505"] = tick_dict()
        result = await proxy.get_quotes()
        assert len(result) == 1
        assert result[0].last_price == 3550.0

    @pytest.mark.asyncio
    async def test_get_quotes_from_trader(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=[tick_dict()])
        result = await proxy.get_quotes_from_trader()
        client.request.assert_awaited_once_with("get_quotes", {}, timeout=5.0)
        assert result[0].symbol == "SHFE.rb2505"

    @pytest.mark.asyncio
    async def test_get_quotes_from_trader_no_client(self, proxy):
        assert await proxy.get_quotes_from_trader() == []

    @pytest.mark.asyncio
    async def test_get_jobs(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=[{"job_id": "j1", "enabled": True}])
        result = await proxy.get_jobs()
        client.request.assert_awaited_once_with("get_jobs", {}, timeout=5.0)
        assert result[0].job_id == "j1"

    @pytest.mark.asyncio
    async def test_get_jobs_no_client(self, proxy):
        assert await proxy.get_jobs() == []

    @pytest.mark.asyncio
    async def test_send_request_forwards(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"ok": 1})
        result = await proxy.send_request("custom", {"a": 1}, timeout=3.0)
        client.request.assert_awaited_once_with("custom", {"a": 1}, timeout=3.0)
        assert result == {"ok": 1}

    @pytest.mark.asyncio
    async def test_send_request_error_returns_none(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        assert await proxy.send_request("custom", {}) is None


@pytest.mark.unit
class TestTraderProxyTradingRpc:
    """交易/网关类请求接口"""

    @pytest.mark.asyncio
    async def test_send_order_request_not_connected(self, proxy):
        assert await proxy.send_order_request("SHFE.rb2505", "BUY", "OPEN", 1, 3500.0) is None

    @pytest.mark.asyncio
    async def test_send_order_request_returns_order_id(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value="ORD-1")
        result = await proxy.send_order_request("SHFE.rb2505", "BUY", "OPEN", 2, 3500.0)
        client.request.assert_awaited_once_with(
            "order_req",
            {
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 2,
                "price": 3500.0,
            },
            timeout=10.0,
        )
        assert result == "ORD-1"

    @pytest.mark.asyncio
    async def test_send_order_request_non_str_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"message": "rejected"})
        assert await proxy.send_order_request("SHFE.rb2505", "BUY", "OPEN", 1) is None

    @pytest.mark.asyncio
    async def test_send_order_request_exception(self, proxy):
        """下单异常上抛（SocketClient 已把 IPC error 转为异常，含真实失败原因）"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await proxy.send_order_request("SHFE.rb2505", "BUY", "OPEN", 1)

    @pytest.mark.asyncio
    async def test_send_cancel_request(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.send_cancel_request("ORD-1") is True
        client.request.assert_awaited_once_with("cancel_req", {"order_id": "ORD-1"}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_send_cancel_request_not_connected(self, proxy):
        assert await proxy.send_cancel_request("ORD-1") is False

    @pytest.mark.asyncio
    async def test_subscribe(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.subscribe({"symbols": ["SHFE.rb2505"]}) is True
        client.request.assert_awaited_once_with(
            "subscribe", {"symbols": ["SHFE.rb2505"]}, timeout=10.0
        )

    @pytest.mark.asyncio
    async def test_connect_and_disconnect_gateway(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.connect() is True
        client.request.assert_awaited_once_with("connect_gateway", {}, timeout=10.0)
        client.request.reset_mock()
        assert await proxy.disconnect() is True
        client.request.assert_awaited_once_with("disconnect_gateway", {}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, proxy):
        assert await proxy.disconnect() is False

    @pytest.mark.asyncio
    async def test_reload_risk_config(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.reload_risk_config() is True
        client.request.assert_awaited_once_with("reload_risk_config", {}, timeout=10.0)


@pytest.mark.unit
class TestTraderProxyAlertRpc:
    """告警配置接口"""

    @pytest.mark.asyncio
    async def test_update_alert_config(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={})
        assert await proxy.update_alert_config({"immediate": True}) is True
        client.request.assert_awaited_once_with(
            "update_alert_config", {"immediate": True}, timeout=10.0
        )

    @pytest.mark.asyncio
    async def test_update_alert_config_no_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        assert await proxy.update_alert_config({}) is False

    @pytest.mark.asyncio
    async def test_get_alert_config_dict(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"immediate": False})
        assert await proxy.get_alert_config() == {"immediate": False}
        client.request.assert_awaited_once_with("get_alert_config", {}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_get_alert_config_non_dict(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.get_alert_config() is None

    @pytest.mark.asyncio
    async def test_update_alert_wechat_delegates(self, proxy):
        with patch.object(proxy, "update_alert_config", AsyncMock(return_value=True)) as m:
            assert await proxy.update_alert_wechat(True) is True
        m.assert_awaited_once_with({"immediate": True, "threshold": True})

    @pytest.mark.asyncio
    async def test_get_alert_wechat_reads_flags(self, proxy):
        with patch.object(proxy, "get_alert_config", AsyncMock(return_value={"threshold": True})):
            assert await proxy.get_alert_wechat() is True
        with patch.object(proxy, "get_alert_config", AsyncMock(return_value=None)):
            assert await proxy.get_alert_wechat() is None


@pytest.mark.unit
class TestTraderProxyStrategyRpc:
    """策略类请求接口"""

    @pytest.mark.asyncio
    async def test_update_strategy_params(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        result = await proxy.update_strategy_params("rsi", {"period": 14})
        client.request.assert_awaited_once_with(
            "update_strategy_params",
            {"strategy_id": "rsi", "params": {"period": 14}},
            timeout=10.0,
        )
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_update_strategy_params_no_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        result = await proxy.update_strategy_params("rsi", {})
        assert result == {"success": False, "message": "无响应"}

    @pytest.mark.asyncio
    async def test_update_strategy_params_error(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        result = await proxy.update_strategy_params("rsi", {})
        assert result == {"success": False, "message": "请求失败: boom"}

    @pytest.mark.asyncio
    async def test_update_strategy_signal(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        result = await proxy.update_strategy_signal("rsi", {"sig": 1})
        client.request.assert_awaited_once_with(
            "update_strategy_signal",
            {"strategy_id": "rsi", "signal": {"sig": 1}},
            timeout=10.0,
        )
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_clear_strategy_signal_not_connected(self, proxy):
        result = await proxy.clear_strategy_signal("rsi")
        assert result == {"success": False, "message": "未连接"}

    @pytest.mark.asyncio
    async def test_clear_strategy_signal_no_response(self, proxy):
        """清除信号无响应时返回失败结构"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        result = await proxy.clear_strategy_signal("rsi")
        client.request.assert_awaited_once_with(
            "clear_strategy_signal", {"strategy_id": "rsi"}, timeout=10.0
        )
        assert result == {"success": False, "message": "无响应"}

    @pytest.mark.asyncio
    async def test_update_strategy_position(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        result = await proxy.update_strategy_position("rsi", {"pos_long": 1})
        client.request.assert_awaited_once_with(
            "update_strategy_position",
            {"strategy_id": "rsi", "position": {"pos_long": 1}},
            timeout=10.0,
        )
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_strategy_trading_status(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        result = await proxy.set_strategy_trading_status("rsi", {"opening_paused": True})
        client.request.assert_awaited_once_with(
            "set_strategy_trading_status",
            {"strategy_id": "rsi", "status": {"opening_paused": True}},
            timeout=10.0,
        )
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_enable_disable_strategy(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        assert await proxy.enable_strategy("rsi") == {"success": True}
        client.request.assert_awaited_once_with(
            "enable_strategy", {"strategy_id": "rsi"}, timeout=10.0
        )
        client.request.reset_mock()
        assert await proxy.disable_strategy("rsi") == {"success": True}
        client.request.assert_awaited_once_with(
            "disable_strategy", {"strategy_id": "rsi"}, timeout=10.0
        )

    @pytest.mark.asyncio
    async def test_init_strategy_uses_long_timeout(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        assert await proxy.init_strategy("rsi") == {"success": True}
        client.request.assert_awaited_once_with(
            "init_strategy", {"strategy_id": "rsi"}, timeout=30.0
        )

    @pytest.mark.asyncio
    async def test_get_strategy_order_cmds(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=[{"cmd_id": "c1"}])
        result = await proxy.get_strategy_order_cmds("rsi", "active")
        client.request.assert_awaited_once_with(
            "get_strategy_order_cmds",
            {"strategy_id": "rsi", "status": "active"},
            timeout=10.0,
        )
        assert result == [{"cmd_id": "c1"}]

    @pytest.mark.asyncio
    async def test_get_strategy_order_cmds_non_list(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"cmd_id": "c1"})
        assert await proxy.get_strategy_order_cmds("rsi", None) == []


@pytest.mark.unit
class TestTraderProxyJobRpc:
    """任务管理请求接口"""

    @pytest.mark.asyncio
    async def test_trigger_job(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.trigger_job("job-1") is True
        client.request.assert_awaited_once_with("trigger_job", {"job_id": "job-1"}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_toggle_job(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.toggle_job("job-1", False) is True
        client.request.assert_awaited_once_with(
            "toggle_job", {"job_id": "job-1", "enabled": False}, timeout=10.0
        )

    @pytest.mark.asyncio
    async def test_pause_and_resume_job(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.pause_job("job-1") is True
        client.request.assert_awaited_once_with("pause_job", {"job_id": "job-1"}, timeout=10.0)
        client.request.reset_mock()
        assert await proxy.resume_job("job-1") is True
        client.request.assert_awaited_once_with("resume_job", {"job_id": "job-1"}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_job_rpc_not_connected(self, proxy):
        assert await proxy.trigger_job("job-1") is False
        assert await proxy.toggle_job("job-1", True) is False
        assert await proxy.pause_job("job-1") is False
        assert await proxy.resume_job("job-1") is False


@pytest.mark.unit
class TestTraderProxyMiscRpc:
    """ping/export/refresh/公共数据/合约等杂项接口"""

    @pytest.mark.asyncio
    async def test_ping_updates_heartbeat(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"pong": True})
        proxy.last_heartbeat = datetime(2020, 1, 1)
        assert await proxy.ping() is True
        client.request.assert_awaited_once_with("ping", {}, timeout=5.0)
        assert proxy.last_heartbeat > datetime(2020, 1, 1)

    @pytest.mark.asyncio
    async def test_ping_falsy_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        assert await proxy.ping() is False

    @pytest.mark.asyncio
    async def test_export_positions_dict_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True, "message": "ok"})
        assert await proxy.export_positions() == {"success": True, "message": "ok"}
        client.request.assert_awaited_once_with("export_positions", {}, timeout=10.0)

    @pytest.mark.asyncio
    async def test_export_positions_non_dict_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        assert await proxy.export_positions() == {"success": True, "message": "导出完成"}

    @pytest.mark.asyncio
    async def test_export_positions_not_connected(self, proxy):
        assert await proxy.export_positions() == {"success": False, "message": "未连接到Trader"}

    @pytest.mark.asyncio
    async def test_refresh_contracts(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"success": True})
        assert await proxy.refresh_contracts() == {"success": True}
        client.request.assert_awaited_once_with("refresh_contracts", {}, timeout=30.0)

    @pytest.mark.asyncio
    async def test_refresh_contracts_no_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        assert await proxy.refresh_contracts() == {"success": False, "message": "无响应"}

    @pytest.mark.asyncio
    async def test_push_public_data(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=True)
        contracts = [{"symbol": "SHFE.rb2505"}]
        assert await proxy.push_public_data(contracts) is True
        client.request.assert_awaited_once_with(
            "init_public_data", {"contracts": contracts}, timeout=30.0
        )

    @pytest.mark.asyncio
    async def test_push_public_data_not_connected(self, proxy):
        assert await proxy.push_public_data([]) is False

    @pytest.mark.asyncio
    async def test_get_contracts_list_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=[{"symbol": "SHFE.rb2505"}])
        assert await proxy.get_contracts() == [{"symbol": "SHFE.rb2505"}]

    @pytest.mark.asyncio
    async def test_get_contracts_dict_response_wrapped(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"symbol": "SHFE.rb2505"})
        assert await proxy.get_contracts() == [{"symbol": "SHFE.rb2505"}]

    @pytest.mark.asyncio
    async def test_get_contracts_none_and_invalid_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        assert await proxy.get_contracts() == []
        client.request = AsyncMock(return_value="weird")
        assert await proxy.get_contracts() == []


NOT_CONNECTED_CASES = [
    ("send_order_request", ("SHFE.rb2505", "BUY", "OPEN", 1), None),
    ("send_cancel_request", ("O1",), False),
    ("subscribe", ({},), False),
    ("connect", (), False),
    ("disconnect", (), False),
    ("reload_risk_config", (), False),
    ("update_alert_config", ({},), False),
    ("get_alert_config", (), None),
    ("ping", (), False),
    ("refresh_contracts", (), {"success": False, "message": "未连接到Trader"}),
    ("push_public_data", ([],), False),
    ("get_contracts", (), []),
    ("get_strategy_order_cmds", ("rsi", "all"), []),
    ("init_strategy", ("rsi",), {"success": False, "message": "未连接"}),
    ("update_strategy_params", ("rsi", {}), {"success": False, "message": "未连接"}),
    ("update_strategy_signal", ("rsi", {}), {"success": False, "message": "未连接"}),
    ("clear_strategy_signal", ("rsi",), {"success": False, "message": "未连接"}),
    ("update_strategy_position", ("rsi", {}), {"success": False, "message": "未连接"}),
    ("set_strategy_trading_status", ("rsi", {}), {"success": False, "message": "未连接"}),
    ("enable_strategy", ("rsi",), {"success": False, "message": "未连接"}),
    ("disable_strategy", ("rsi",), {"success": False, "message": "未连接"}),
    ("trigger_job", ("job-1",), False),
    ("toggle_job", ("job-1", True), False),
    ("pause_job", ("job-1",), False),
    ("resume_job", ("job-1",), False),
    ("resume", (), False),
]

# 写路径方法异常直接上抛（真实失败原因由路由层透传给前端）
ERROR_RAISE_CASES = [
    ("send_order_request", ("SHFE.rb2505", "BUY", "OPEN", 1)),
    ("send_cancel_request", ("O1",)),
    ("subscribe", ({},)),
    ("connect", ()),
    ("disconnect", ()),
]

ERROR_DEFAULT_CASES = [
    ("reload_risk_config", (), False),
    ("update_alert_config", ({},), False),
    ("get_alert_config", (), None),
    ("ping", (), False),
    ("trigger_job", ("job-1",), False),
    ("toggle_job", ("job-1", True), False),
    ("pause_job", ("job-1",), False),
    ("resume_job", ("job-1",), False),
    ("resume", (), False),
    ("get_strategy_order_cmds", ("rsi", "all"), []),
    ("push_public_data", ([],), False),
    ("get_contracts", (), []),
    (
        "export_positions",
        (),
        {"success": False, "message": "请求失败: boom"},
    ),
    (
        "refresh_contracts",
        (),
        {"success": False, "message": "请求失败: boom"},
    ),
]


@pytest.mark.unit
class TestTraderProxyRpcGuards:
    """RPC 接口的未连接拒绝与请求异常兜底"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,args,expected", NOT_CONNECTED_CASES)
    async def test_not_connected_returns_default(self, proxy, method, args, expected):
        """未连接时应返回各接口的默认失败值"""
        result = await getattr(proxy, method)(*args)
        assert result == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,args,expected", ERROR_DEFAULT_CASES)
    async def test_request_error_returns_default(self, proxy, method, args, expected):
        """请求抛异常时应返回各接口的默认失败值"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        result = await getattr(proxy, method)(*args)
        assert result == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,args", ERROR_RAISE_CASES)
    async def test_request_error_raises(self, proxy, method, args):
        """写路径接口请求异常时上抛（异常消息即 Trader 回传的真实失败原因）"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await getattr(proxy, method)(*args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,args",
        [
            ("update_strategy_params", ("rsi", {})),
            ("update_strategy_signal", ("rsi", {})),
            ("clear_strategy_signal", ("rsi",)),
            ("update_strategy_position", ("rsi", {})),
            ("set_strategy_trading_status", ("rsi", {})),
            ("enable_strategy", ("rsi",)),
            ("disable_strategy", ("rsi",)),
            ("init_strategy", ("rsi",)),
        ],
    )
    async def test_strategy_rpc_error_shape(self, proxy, method, args):
        """策略类接口请求异常时返回统一的失败结构"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        result = await getattr(proxy, method)(*args)
        assert result["success"] is False
        assert result["message"] == "请求失败: boom"


@pytest.mark.unit
class TestTraderProxySetStateEmit:
    """_set_state 状态变更时的账户事件推送"""

    @pytest.mark.asyncio
    async def test_state_change_updates_cached_account(self, proxy):
        """状态变更且存在账户缓存时应更新缓存字段并推送事件"""
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        proxy._account_cache.md_connected = True
        proxy._account_cache.td_connected = True
        with patch.object(proxy, "_emit_data") as mock_emit:
            await proxy._set_state(TraderState.CONNECTING)
        assert proxy._account_cache.status == TraderState.CONNECTING
        assert proxy._account_cache.md_connected is False
        assert proxy._account_cache.td_connected is False
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "account"

    @pytest.mark.asyncio
    async def test_same_state_no_emit(self, proxy):
        """状态未变化时不推送事件"""
        with patch.object(proxy, "_emit_data") as mock_emit:
            await proxy._set_state(TraderState.STOPPED)
        mock_emit.assert_not_called()


@pytest.mark.unit
class TestTraderProxyConnectLoopEdge:
    """_connect_async 其余分支"""

    @pytest.mark.asyncio
    async def test_already_connected_skips_connect(self, proxy):
        """socket 已连接时不再调用 connect"""
        client = MagicMock()
        client.is_connected.return_value = True
        client.connect = AsyncMock()
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=123)),
            patch("qtrader.manager.trader_proxy.SocketClient", return_value=client),
        ):
            task = asyncio.create_task(proxy._connect_async())
            await asyncio.to_thread(time.sleep, 0.2)
            assert proxy.get_state() == TraderState.CONNECTED
            client.connect.assert_not_awaited()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_process_check_error_logged(self, proxy):
        """_get_process 抛异常时记录异常并继续循环"""
        client = MagicMock()
        client.is_connected.return_value = False
        client.connect = AsyncMock()
        with (
            patch.object(proxy, "_get_process", AsyncMock(side_effect=RuntimeError("stat failed"))),
            patch("qtrader.manager.trader_proxy.SocketClient", return_value=client),
        ):
            task = asyncio.create_task(proxy._connect_async())
            await asyncio.to_thread(time.sleep, 0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_loop_exits_when_stopped(self, proxy):
        """_running 置 False 后连接循环正常退出"""

        async def stop_during_sleep(_seconds):
            proxy._running = False

        client = MagicMock()
        client.is_connected.return_value = False
        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=None)),
            patch("qtrader.manager.trader_proxy.SocketClient", return_value=client),
            patch("qtrader.manager.trader_proxy.asyncio.sleep", side_effect=stop_during_sleep),
        ):
            task = asyncio.create_task(proxy._connect_async())
            await asyncio.wait_for(task, timeout=2.0)  # 不应抛出


@pytest.mark.unit
class TestTraderProxySyncErrors:
    """同步方法的异常与边界分支"""

    @pytest.mark.asyncio
    async def test_sync_account_detail_error_swallowed(self, proxy):
        """账户数据校验失败时记录异常"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(
            return_value={"account": {"balance": 1.0}}  # 缺 account_id，校验失败
        )
        await proxy._sync_account_detail()
        assert proxy._account_cache is None


@pytest.mark.unit
class TestTraderProxyMsgCallbackErrors:
    """消息回调异常分支"""

    @pytest.mark.asyncio
    async def test_tick_batch_hold_profit_error_swallowed(self, proxy):
        """tick_batch 中单条盈亏计算失败不影响推送"""
        data = {"ticks": [tick_dict()], "account": None}
        with (
            patch.object(proxy, "update_hold_profit", side_effect=RuntimeError("boom")),
            patch.object(proxy, "_emit_data") as mock_emit,
        ):
            proxy._on_msg_callback("tick_batch", data)
        mock_emit.assert_called_once_with(
            "tick_batch", {"ticks": data["ticks"], "account_id": "test_account_001"}
        )

    @pytest.mark.asyncio
    async def test_callback_emit_error_swallowed(self, proxy):
        """回调内异常由外层捕获"""
        with patch.object(proxy, "_emit_data", side_effect=RuntimeError("boom")):
            proxy._on_msg_callback("trade", trade_dict())
        # 不应抛出

    @pytest.mark.asyncio
    async def test_account_update_invalid_data_swallowed(self, proxy):
        """非法账户推送数据不破坏现有缓存"""
        proxy._account_cache = AccountData(account_id="test_account_001", balance=7.0)
        proxy._handle_account_update({"balance": 1.0})  # 缺 account_id
        assert proxy._account_cache.balance == 7.0

    def test_trader_ready_without_running_loop_logged(self, proxy):
        """无事件循环时就绪通知仅记录异常"""

        def fail_create_task(coro):
            coro.close()  # 关闭未调度的协程，避免告警
            raise RuntimeError("no running event loop")

        with patch(
            "qtrader.manager.trader_proxy.asyncio.create_task", side_effect=fail_create_task
        ):
            proxy._handle_trader_ready_push({})
        # 不应抛出

    @pytest.mark.asyncio
    async def test_notify_context_error_swallowed(self, proxy):
        """通知处理中上下文异常不向外抛出"""
        with patch("qtrader.app_context.get_app_context", side_effect=RuntimeError("boom")):
            proxy._on_msg_callback("notify", {"title": "t"})
        # 不应抛出


@pytest.mark.unit
class TestTraderProxyEmitData:
    """_emit_data 事件分发"""

    def _engine(self):
        from qtrader.manager import trader_proxy as tp

        return tp.ctx.get_event_engine.return_value

    @pytest.mark.asyncio
    async def test_emit_order_trade_position_tick(self, proxy):
        engine = self._engine()
        proxy._emit_data("order", {"order_id": "O1"})
        proxy._emit_data("trade", {"trade_id": "T1"})
        proxy._emit_data("position", {"symbol": "SHFE.rb2505"})
        proxy._emit_data("tick", tick_dict())
        proxy._emit_data("tick_batch", {"ticks": []})
        assert engine.put.call_count == 5

    @pytest.mark.asyncio
    async def test_emit_account_adds_status(self, proxy):
        engine = self._engine()
        proxy._emit_data("account", {"account_id": "test_account_001"})
        event_type, data = engine.put.call_args[0]
        assert data["status"] == proxy.get_state()

    @pytest.mark.asyncio
    async def test_emit_account_maps_update_time(self, proxy):
        """account 数据中的 update_time 应映射为 updated_at"""
        engine = self._engine()
        proxy._emit_data("account", {"account_id": "test_account_001", "update_time": "10:00:00"})
        _, data = engine.put.call_args[0]
        assert data["updated_at"] == "10:00:00"

    @pytest.mark.asyncio
    async def test_emit_unknown_type_ignored(self, proxy):
        engine = self._engine()
        proxy._emit_data("whatever", {"x": 1})
        engine.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_emit_without_event_engine(self, proxy):
        from qtrader.manager import trader_proxy as tp

        tp.ctx.get_event_engine.return_value = None
        proxy._emit_data("order", {"order_id": "O1"})  # 不应抛出

    @pytest.mark.asyncio
    async def test_alarm_data_without_db_logged(self, proxy):
        with patch("qtrader.utils.async_database.get_async_database", return_value=None):
            proxy._emit_data("alarm", {"title": "t"})
            await _wait_background_tasks()
        # 不应抛出

    @pytest.mark.asyncio
    async def test_alarm_data_saved_to_db(self, proxy):
        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        db = MagicMock()
        db.get_session.return_value.__aenter__.return_value = session
        db.get_session.return_value.__aexit__.return_value = False
        with patch("qtrader.utils.async_database.get_async_database", return_value=db):
            proxy._emit_data(
                "alarm", {"account_id": "test_account_001", "title": "异常", "detail": "d"}
            )
            await _wait_background_tasks()
        alarm = session.add.call_args[0][0]
        assert alarm.account_id == "test_account_001"
        assert alarm.title == "异常"
        assert alarm.source == "TRADER"
        session.commit.assert_awaited_once()


@pytest.mark.unit
class TestTraderProxyPeriodicSync:
    """_periodic_sync_loop 定时兜底同步"""

    @pytest.mark.asyncio
    async def test_skips_when_not_connected(self, proxy):
        """非 CONNECTED 状态时跳过同步"""
        proxy._running = True

        async def stop_loop(_seconds):
            proxy._running = False

        with patch(
            "qtrader.manager.trader_proxy.asyncio.sleep", side_effect=stop_loop
        ) as mock_sleep:
            await asyncio.wait_for(proxy._periodic_sync_loop(), timeout=2.0)
        mock_sleep.assert_awaited_once_with(60.0)

    @pytest.mark.asyncio
    async def test_skips_when_socket_disconnected(self, proxy):
        await proxy._set_state(TraderState.CONNECTED)
        proxy.socket_client = MagicMock()
        proxy.socket_client.is_connected.return_value = False
        calls = []

        async def stop_loop(_seconds):
            calls.append(1)
            proxy._running = False

        with patch("qtrader.manager.trader_proxy.asyncio.sleep", side_effect=stop_loop):
            await asyncio.wait_for(proxy._periodic_sync_loop(), timeout=2.0)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_syncs_when_connected(self, proxy):
        await proxy._set_state(TraderState.CONNECTED)
        connect_proxy(proxy)
        proxy._running = True

        async def stop_loop(_seconds):
            proxy._running = False

        with (
            patch.object(proxy, "_sync_account_detail", AsyncMock()) as mock_sync,
            patch("qtrader.manager.trader_proxy.asyncio.sleep", side_effect=stop_loop),
        ):
            await asyncio.wait_for(proxy._periodic_sync_loop(), timeout=2.0)
        mock_sync.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_error_logged(self, proxy):
        await proxy._set_state(TraderState.CONNECTED)
        connect_proxy(proxy)
        proxy._running = True

        async def stop_loop(_seconds):
            proxy._running = False

        with (
            patch.object(
                proxy, "_sync_account_detail", AsyncMock(side_effect=RuntimeError("boom"))
            ),
            patch("qtrader.manager.trader_proxy.asyncio.sleep", side_effect=stop_loop),
        ):
            await asyncio.wait_for(proxy._periodic_sync_loop(), timeout=2.0)
        # 不应抛出

    @pytest.mark.asyncio
    async def test_cancelled_breaks_loop(self, proxy):
        proxy._running = True
        task = asyncio.create_task(proxy._periodic_sync_loop())
        await asyncio.to_thread(time.sleep, 0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.unit
class TestTraderProxyHoldProfitEdge:
    """盈亏计算边界"""

    @pytest.mark.asyncio
    async def test_hold_profit_compute_error_swallowed(self, proxy):
        """盈亏计算异常时记录日志并继续推送路径"""

        class BadPosition:
            @property
            def multiple(self):
                raise RuntimeError("boom")

        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        proxy._position_cache["SHFE.rb2505"] = BadPosition()
        proxy.update_hold_profit(TickData.model_construct(symbol="SHFE.rb2505", last_price=3550.0))
        # 不应抛出

    @pytest.mark.asyncio
    async def test_hold_profit_zero_price_ignored(self, proxy):
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        pos = PositionData(**position_dict())
        proxy._position_cache["SHFE.rb2505"] = pos
        proxy.update_hold_profit(TickData.model_construct(symbol="SHFE.rb2505", last_price=0))
        assert pos.hold_profit_long == 0

    @pytest.mark.asyncio
    async def test_recalc_long_with_tick_multiple(self, proxy):
        pos = PositionData(
            symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=2, hold_price_long=3500.0
        )
        proxy._tick_cache["SHFE.rb2505"] = {"volume_multiple": 10}
        result = proxy._recalc_position_profit(pos, 3520.0)
        # (3520-3500)*2*10 = 400
        assert result.hold_profit_long == 400.0

    @pytest.mark.asyncio
    async def test_recalc_zero_price_unchanged(self, proxy):
        pos = PositionData(**position_dict())
        result = proxy._recalc_position_profit(pos, 0)
        assert result.hold_profit_long == 0


@pytest.mark.unit
class TestTraderProxyQueryEdge:
    """查询接口边界"""

    @pytest.mark.asyncio
    async def test_get_order_from_cache(self, proxy):
        from qtrader.models.object import OrderData

        proxy._order_cache["O1"] = OrderData(**order_dict())
        assert (await proxy.get_order("O1")).order_id == "O1"
        assert await proxy.get_order("NOPE") is None

    @pytest.mark.asyncio
    async def test_get_orders_request_error_returns_cache(self, proxy):
        from qtrader.models.object import OrderData

        proxy._order_cache["O1"] = OrderData(**order_dict())
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        result = await proxy.get_orders()
        assert [o.order_id for o in result] == ["O1"]

    @pytest.mark.asyncio
    async def test_get_positions_request_error_returns_cache(self, proxy):
        proxy._position_cache["SHFE.rb2505"] = PositionData(**position_dict())
        client = connect_proxy(proxy)
        client.request = AsyncMock(side_effect=RuntimeError("boom"))
        result = await proxy.get_positions()
        assert [p.symbol for p in result] == ["SHFE.rb2505"]

    @pytest.mark.asyncio
    async def test_get_quotes_from_trader_empty_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        assert await proxy.get_quotes_from_trader() == []

    @pytest.mark.asyncio
    async def test_get_jobs_empty_response(self, proxy):
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        assert await proxy.get_jobs() == []


@pytest.mark.unit
class TestTraderProxyStopMonitoring:
    """stop_monitoring 资源清理"""

    @pytest.mark.asyncio
    async def test_stops_tasks_and_disconnects(self, proxy):
        client = connect_proxy(proxy)
        client.disconnect = AsyncMock()
        await proxy.stop_monitoring()
        client.disconnect.assert_awaited_once()
        assert proxy.socket_client is None
        assert proxy._running is False

    @pytest.mark.asyncio
    async def test_disconnect_error_swallowed(self, proxy):
        client = connect_proxy(proxy)
        client.disconnect = AsyncMock(side_effect=RuntimeError("boom"))
        await proxy.stop_monitoring()
        assert proxy.socket_client is None


@pytest.mark.unit
class TestTraderProxyAliveAndStatus:
    """进程存活与状态信息"""

    @pytest.mark.asyncio
    async def test_alive_with_created_process(self, proxy):
        proxy._created_process = True
        Path(proxy.pid_file).write_text(str(os.getpid()))
        assert proxy.is_alive() is True

    @pytest.mark.asyncio
    async def test_not_alive_created_process_missing_pid(self, proxy):
        proxy._created_process = True
        assert proxy.is_alive() is False

    @pytest.mark.asyncio
    async def test_not_alive_created_process_dead(self, proxy):
        proxy._created_process = True
        Path(proxy.pid_file).write_text("99999999")
        with patch("qtrader.manager.trader_proxy.os.kill", side_effect=OSError):
            assert proxy.is_alive() is False

    @pytest.mark.asyncio
    async def test_get_pid_invalid_file(self, proxy):
        Path(proxy.pid_file).write_text("abc")
        assert proxy._get_pid() is None

    @pytest.mark.asyncio
    async def test_gateway_property_reflects_state(self, proxy):
        assert proxy.gateway.connected is False
        await proxy._set_state(TraderState.CONNECTED)
        assert proxy.gateway.connected is True

    @pytest.mark.asyncio
    async def test_get_status_with_start_time_and_pid(self, proxy):
        proxy.start_time = datetime(2026, 9, 4, 9, 0, 0)
        Path(proxy.pid_file).write_text(str(os.getpid()))
        status = proxy.get_status()
        assert status["start_time"] == "2026-09-04T09:00:00"
        assert status["pid"] == os.getpid()


@pytest.mark.unit
class TestTraderProxyRemainingBranches:
    """剩余零散分支"""

    @pytest.mark.asyncio
    async def test_stop_monitoring_cancels_pending_tasks(self, proxy):
        """存在未完成后台任务时应先取消再断开"""
        proxy._connect_task = asyncio.create_task(AsyncMock()())
        proxy._socket_monitor_task = asyncio.create_task(AsyncMock()())
        client = connect_proxy(proxy)
        client.disconnect = AsyncMock()
        await proxy.stop_monitoring()
        assert proxy._connect_task is None
        assert proxy._socket_monitor_task is None

    @pytest.mark.asyncio
    async def test_update_hold_profit_short_position(self, proxy):
        """空头持仓按 (开仓价-最新价) 计算盈亏"""
        proxy._account_cache = AccountData(account_id="test_account_001", balance=1.0)
        pos = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            multiple=10,
            pos_short_yd=2,
            hold_price_short=3500.0,
        )
        proxy._position_cache["SHFE.rb2505"] = pos
        with patch.object(proxy, "_emit_data"):
            proxy.update_hold_profit(
                TickData.model_construct(symbol="SHFE.rb2505", last_price=3450.0)
            )
        # (3500-3450)*2*10 = 1000
        assert pos.hold_profit_short == 1000.0

    @pytest.mark.asyncio
    async def test_get_account_first_query_without_cache(self, proxy):
        """无缓存时首次查询直接用返回数据构建账户对象"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value={"account_id": "test_account_001", "balance": 8.0})
        result = await proxy.get_account()
        assert result.balance == 8.0
        assert result.status == TraderState.CONNECTED

    @pytest.mark.asyncio
    async def test_alarm_data_session_error_logged(self, proxy):
        """告警入库失败时仅记录错误"""
        db = MagicMock()
        db.get_session.return_value.__aenter__.side_effect = RuntimeError("db down")
        db.get_session.return_value.__aexit__.return_value = False
        with patch("qtrader.utils.async_database.get_async_database", return_value=db):
            proxy._emit_data("alarm", {"title": "异常"})
            await _wait_background_tasks()
        # 不应抛出

    @pytest.mark.asyncio
    async def test_connect_loop_already_connected_continues(self, proxy):
        """已连接分支在休眠后继续下一轮循环"""
        proxy._running = True
        client = MagicMock()
        client.is_connected.return_value = True

        async def stop_loop(_seconds):
            proxy._running = False

        with (
            patch.object(proxy, "_get_process", AsyncMock(return_value=123)),
            patch("qtrader.manager.trader_proxy.SocketClient", return_value=client),
            patch("qtrader.manager.trader_proxy.asyncio.sleep", side_effect=stop_loop),
        ):
            await asyncio.wait_for(proxy._connect_async(), timeout=2.0)
        assert proxy.get_state() == TraderState.CONNECTED

    @pytest.mark.asyncio
    async def test_update_strategy_position_no_response(self, proxy):
        """更新策略持仓无响应时返回失败结构"""
        client = connect_proxy(proxy)
        client.request = AsyncMock(return_value=None)
        result = await proxy.update_strategy_position("rsi", {"pos_long": 1})
        assert result == {"success": False, "message": "无响应"}
