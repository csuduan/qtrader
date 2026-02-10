"""
TraderProxy 单元测试
测试 TraderProxy 类的所有方法和功能
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from decimal import Decimal

import pytest

from src.manager.trader_proxy import TraderProxy
from src.models.object import (
    AccountData,
    OrderData,
    TradeData,
    PositionData,
    TickData,
    TraderState,
    Direction,
    Offset,
    Exchange,
)


# ==================== Fixtures ====================


@pytest.fixture
def mock_account_config():
    """创建模拟的账户配置"""
    config = MagicMock()
    config.account_id = "test_account_001"
    config.account_type = "kq"
    config.enabled = True
    config.auto_start = False
    config.debug = False
    return config


@pytest.fixture
def mock_global_config():
    """创建模拟的全局配置"""
    config = MagicMock()
    config.paths = MagicMock()
    config.paths.logs = "./data/logs"
    config.paths.database = "./storage/test.db"
    return config


@pytest.fixture
def socket_path(tmp_path):
    """临时socket文件路径"""
    return str(tmp_path / "test.sock")


@pytest.fixture
def trader_proxy(mock_account_config, mock_global_config, socket_path):
    """创建 TraderProxy 实例"""
    with patch("src.manager.trader_proxy.ctx"), patch("src.manager.trader_proxy.get_app_context"):
        proxy = TraderProxy(
            mock_account_config,
            mock_global_config,
            socket_path,
            heartbeat_timeout=30,
        )
        return proxy


@pytest.fixture
def mock_socket_client():
    """创建模拟的SocketClient"""
    client = AsyncMock()
    client.is_connected = MagicMock(return_value=True)
    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    client.request = AsyncMock()
    return client


@pytest.fixture
def mock_event_engine():
    """创建模拟的事件引擎"""
    engine = AsyncMock()
    engine.put = MagicMock()
    return engine


# ==================== Test Initialization ====================


class TestTraderProxyInit:
    """测试 __init__ 方法"""

    def test_init_with_all_params(self, trader_proxy, mock_account_config, mock_global_config, socket_path):
        """测试完整参数初始化"""
        assert trader_proxy.account_id == "test_account_001"
        assert trader_proxy.account_config == mock_account_config
        assert trader_proxy.global_config == mock_global_config
        assert trader_proxy.socket_path == socket_path
        assert trader_proxy.heartbeat_timeout == 30

    def test_init_initial_state(self, trader_proxy):
        """测试初始化状态"""
        assert trader_proxy.get_state() == TraderState.STOPPED
        assert trader_proxy.start_time is None
        assert trader_proxy.restart_count == 0
        assert trader_proxy._created_process is False
        assert trader_proxy.process is None
        assert trader_proxy.socket_client is None
        assert trader_proxy._connect_task is None

    def test_init_pid_file_path(self, trader_proxy, socket_path):
        """测试PID文件路径设置"""
        expected_pid = str(Path(socket_path).parent / "qtrader_test_account_001.pid")
        assert trader_proxy.pid_file == expected_pid


# ==================== Test State Management ====================


class TestTraderProxyState:
    """测试状态管理"""

    def test_get_state(self, trader_proxy):
        """测试获取状态"""
        assert trader_proxy.get_state() == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_set_state_stopped_to_connecting(self, trader_proxy, mock_event_engine):
        """测试状态变更 STOPPED -> CONNECTING"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            await trader_proxy._set_state(TraderState.CONNECTING)
            assert trader_proxy.get_state() == TraderState.CONNECTING
            mock_event_engine.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_state_to_connected_emits_event(self, trader_proxy, mock_event_engine):
        """测试状态变更为CONNECTED时触发事件"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            await trader_proxy._set_state(TraderState.CONNECTED)

            call_args = mock_event_engine.put.call_args
            assert call_args[0][0] == "e:account.status"
            assert call_args[0][1]["account_id"] == "test_account_001"
            assert call_args[0][1]["status"] == "connected"

    @pytest.mark.asyncio
    async def test_set_state_event_engine_error(self, trader_proxy):
        """测试事件引擎异常不影响状态设置"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(side_effect=Exception("Event engine error")))):
            # 不应该抛出异常
            await trader_proxy._set_state(TraderState.CONNECTING)
            assert trader_proxy.get_state() == TraderState.CONNECTING

    def test_is_state(self, trader_proxy):
        """测试状态检查"""
        assert trader_proxy._is_state(TraderState.STOPPED) is True
        assert trader_proxy._is_state(TraderState.CONNECTING) is False
        assert trader_proxy._is_state(TraderState.CONNECTED) is False


# ==================== Test Start Method ====================


class TestTraderProxyStart:
    """测试 start 方法"""

    @pytest.mark.asyncio
    async def test_start_success(self, trader_proxy, mock_socket_client):
        """测试成功启动"""
        with patch.object(trader_proxy, "_check_process_exists", return_value=False), \
             patch.object(trader_proxy, "_create_subprocess", new=AsyncMock()), \
             patch("src.manager.trader_proxy.SocketClient", return_value=mock_socket_client):
            result = await trader_proxy.start()

            assert result is True
            assert trader_proxy.get_state() == TraderState.CONNECTING
            assert trader_proxy.start_time is not None
            assert trader_proxy.socket_client is not None
            assert trader_proxy._connect_task is not None

    @pytest.mark.asyncio
    async def test_start_existing_process(self, trader_proxy, mock_socket_client):
        """测试检测到已存在进程"""
        with patch.object(trader_proxy, "_check_process_exists", return_value=True), \
             patch.object(trader_proxy, "_create_subprocess", new=AsyncMock()) as mock_create, \
             patch("src.manager.trader_proxy.SocketClient", return_value=mock_socket_client):
            result = await trader_proxy.start()

            assert result is True
            assert trader_proxy._created_process is False
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_not_stopped_state(self, trader_proxy):
        """测试非STOPPED状态下启动被拒绝"""
        await trader_proxy._set_state(TraderState.CONNECTING)

        result = await trader_proxy.start()

        assert result is False

    @pytest.mark.asyncio
    async def test_start_exception_cleanup(self, trader_proxy):
        """测试启动异常时清理资源"""
        with patch.object(trader_proxy, "_check_process_exists", side_effect=Exception("Start error")):
            result = await trader_proxy.start()

            assert result is False
            assert trader_proxy.get_state() == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_start_with_debug_flag(self, trader_proxy, mock_socket_client):
        """测试启用debug模式启动"""
        trader_proxy.account_config.debug = True
        trader_proxy._created_process = False

        with patch.object(trader_proxy, "_check_process_exists", return_value=False), \
             patch.object(trader_proxy, "_create_subprocess", new=AsyncMock()) as mock_create, \
             patch("src.manager.trader_proxy.SocketClient", return_value=mock_socket_client):
            await trader_proxy.start()

            mock_create.assert_called_once()


# ==================== Test Stop Method ====================


class TestTraderProxyStop:
    """测试 stop 方法"""

    @pytest.mark.asyncio
    async def test_stop_success(self, trader_proxy, mock_socket_client):
        """测试成功停止"""
        # 设置为运行状态
        trader_proxy.socket_client = mock_socket_client
        await trader_proxy._set_state(TraderState.CONNECTED)
        trader_proxy._connect_task = asyncio.create_task(asyncio.sleep(10))

        result = await trader_proxy.stop()

        assert result is True
        assert trader_proxy.get_state() == TraderState.STOPPED
        assert trader_proxy.socket_client is None
        assert trader_proxy._connect_task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_connect_task(self, trader_proxy):
        """测试停止时取消连接任务"""
        async def dummy_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise

        trader_proxy._connect_task = asyncio.create_task(dummy_task())

        with patch.object(trader_proxy, "_force_kill_trader", new=AsyncMock()):
            await trader_proxy.stop()

        assert trader_proxy._connect_task is None

    @pytest.mark.asyncio
    async def test_stop_disconnects_socket_client(self, trader_proxy, mock_socket_client):
        """测试停止时断开Socket连接"""
        trader_proxy.socket_client = mock_socket_client

        with patch.object(trader_proxy, "_force_kill_trader", new=AsyncMock()):
            await trader_proxy.stop()

            mock_socket_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_kills_process(self, trader_proxy):
        """测试停止时终止进程"""
        with patch.object(trader_proxy, "_force_kill_trader", new=AsyncMock()) as mock_kill:
            await trader_proxy.stop()
            mock_kill.assert_called_once()


# ==================== Test Async Connection ====================


class TestTraderProxyConnectAsync:
    """测试 _connect_async 方法"""

    @pytest.mark.asyncio
    async def test_connect_async_success(self, trader_proxy, mock_socket_client):
        """测试异步连接成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.connect = AsyncMock(return_value=True)
        # Set state to CONNECTING before calling _connect_async
        await trader_proxy._set_state(TraderState.CONNECTING)

        await trader_proxy._connect_async()

        assert trader_proxy.get_state() == TraderState.CONNECTED
        mock_socket_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_async_retry_with_backoff(self, trader_proxy, mock_socket_client):
        """测试连接重试和退避算法"""
        trader_proxy.socket_client = mock_socket_client
        # 第一次失败，第二次成功
        mock_socket_client.connect = AsyncMock(side_effect=[False, True])
        await trader_proxy._set_state(TraderState.CONNECTING)

        # 缩短重试间隔
        with patch.object(trader_proxy, "INITIAL_INTERVAL", 0.01), \
             patch.object(trader_proxy, "MAX_INTERVAL", 0.1):
            await trader_proxy._connect_async()

        assert mock_socket_client.connect.call_count == 2
        assert trader_proxy.get_state() == TraderState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_async_max_retries_exceeded(self, trader_proxy, mock_socket_client):
        """测试超过最大重试次数"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.connect = AsyncMock(return_value=False)
        await trader_proxy._set_state(TraderState.CONNECTING)

        with patch.object(trader_proxy, "MAX_RETRIES", 3), \
             patch.object(trader_proxy, "INITIAL_INTERVAL", 0.01):
            await trader_proxy._connect_async()

        assert trader_proxy.get_state() == TraderState.STOPPED
        assert mock_socket_client.connect.call_count == 3

    @pytest.mark.asyncio
    async def test_connect_async_state_changed_during_retry(self, trader_proxy, mock_socket_client):
        """测试重试期间状态变更"""
        trader_proxy.socket_client = mock_socket_client
        call_count = [0]

        async def mock_connect():
            call_count[0] += 1
            if call_count[0] == 1:
                return False
            # 在第二次调用前改变状态
            await trader_proxy._set_state(TraderState.STOPPED)
            return False

        mock_socket_client.connect = AsyncMock(side_effect=mock_connect)

        with patch.object(trader_proxy, "INITIAL_INTERVAL", 0.01):
            await trader_proxy._connect_async()

        # 应该在状态改变时停止重试
        assert trader_proxy.get_state() == TraderState.STOPPED

    @pytest.mark.asyncio
    async def test_connect_async_exception_handling(self, trader_proxy, mock_socket_client):
        """测试连接异常处理"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.connect = AsyncMock(side_effect=Exception("Connection error"))

        with patch.object(trader_proxy, "MAX_RETRIES", 2), \
             patch.object(trader_proxy, "INITIAL_INTERVAL", 0.01):
            await trader_proxy._connect_async()

        assert trader_proxy.get_state() == TraderState.STOPPED


# ==================== Test Connection Check ====================


class TestTraderProxyCheckConnection:
    """测试 _check_connection_and_reconnect 方法"""

    @pytest.mark.asyncio
    async def test_check_connection_no_reconnect_when_stopped(self, trader_proxy, mock_socket_client):
        """测试STOPPED状态时不重连"""
        trader_proxy.socket_client = mock_socket_client
        trader_proxy.socket_client.is_connected = MagicMock(return_value=False)

        await trader_proxy._check_connection_and_reconnect()

        # 应该不创建新的连接任务
        assert trader_proxy._connect_task is None

    @pytest.mark.asyncio
    async def test_check_connection_reconnects_when_disconnected(self, trader_proxy, mock_socket_client):
        """测试检测到断开时重连"""
        trader_proxy.socket_client = mock_socket_client
        trader_proxy.socket_client.is_connected = MagicMock(return_value=False)
        await trader_proxy._set_state(TraderState.CONNECTED)

        await trader_proxy._check_connection_and_reconnect()

        assert trader_proxy.get_state() == TraderState.CONNECTING
        assert trader_proxy._connect_task is not None

    @pytest.mark.asyncio
    async def test_check_connection_no_action_when_connected(self, trader_proxy, mock_socket_client):
        """测试已连接时不采取行动"""
        trader_proxy.socket_client = mock_socket_client
        trader_proxy.socket_client.is_connected = MagicMock(return_value=True)
        await trader_proxy._set_state(TraderState.CONNECTED)

        await trader_proxy._check_connection_and_reconnect()

        assert trader_proxy.get_state() == TraderState.CONNECTED
        assert trader_proxy._connect_task is None


# ==================== Test Process Management ====================


class TestTraderProxyProcessManagement:
    """测试进程管理"""

    @pytest.mark.asyncio
    async def test_check_process_exists_true(self, trader_proxy, tmp_path):
        """测试进程存在"""
        socket_path = tmp_path / "test.sock"
        socket_path.touch()
        pid_path = tmp_path / "qtrader_test_account_001.pid"
        pid_path.write_text("12345")

        trader_proxy.socket_path = str(socket_path)
        trader_proxy.pid_file = str(pid_path)

        with patch("os.kill", return_value=None):
            result = await trader_proxy._check_process_exists()
            # 由于mock kill总是成功，会返回True
            assert result is True

    @pytest.mark.asyncio
    async def test_check_process_exists_no_socket_file(self, trader_proxy):
        """测试socket文件不存在"""
        trader_proxy.socket_path = "/nonexistent/test.sock"

        result = await trader_proxy._check_process_exists()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_process_exists_no_pid_file(self, trader_proxy, tmp_path):
        """测试PID文件不存在"""
        socket_path = tmp_path / "test.sock"
        socket_path.touch()
        trader_proxy.socket_path = str(socket_path)
        trader_proxy.pid_file = str(tmp_path / "nonexistent.pid")

        result = await trader_proxy._check_process_exists()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_process_exists_dead_process(self, trader_proxy, tmp_path):
        """测试进程已死亡"""
        socket_path = tmp_path / "test.sock"
        socket_path.touch()
        pid_path = tmp_path / "qtrader_test_account_001.pid"
        pid_path.write_text("12345")

        trader_proxy.socket_path = str(socket_path)
        trader_proxy.pid_file = str(pid_path)

        with patch("os.kill", side_effect=OSError("No such process")):
            result = await trader_proxy._check_process_exists()

            assert result is False
            assert not pid_path.exists()

    @pytest.mark.asyncio
    async def test_create_subprocess(self, trader_proxy):
        """测试创建子进程"""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_exec.return_value = mock_process

            await trader_proxy._create_subprocess()

            assert trader_proxy._created_process is True
            assert trader_proxy.process == mock_process

    @pytest.mark.asyncio
    async def test_create_subprocess_with_debug(self, trader_proxy):
        """测试创建子进程（启用debug）"""
        trader_proxy.account_config.debug = True

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_exec.return_value = mock_process

            await trader_proxy._create_subprocess()

            # 检查命令中包含--debug参数
            # call_args[0] contains all the positional arguments as a tuple
            # We need to find the command list which is the first arg
            all_args = mock_exec.call_args[0]
            assert len(all_args) > 0
            # The first argument is the command list
            cmd_list = list(all_args[0]) if isinstance(all_args[0], (list, tuple)) else list(all_args)
            assert "--debug" in cmd_list

    @pytest.mark.asyncio
    async def test_cleanup_subprocess(self, trader_proxy, tmp_path):
        """测试清理子进程"""
        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock(return_value=None)
        mock_process.returncode = 0
        trader_proxy.process = mock_process

        pid_path = tmp_path / "qtrader_test_account_001.pid"
        pid_path.touch()
        trader_proxy.pid_file = str(pid_path)

        await trader_proxy._cleanup_subprocess()

        mock_process.terminate.assert_called_once()
        assert trader_proxy.process is None

    @pytest.mark.asyncio
    async def test_cleanup_subprocess_timeout(self, trader_proxy):
        """测试清理子进程超时"""
        mock_process = MagicMock()
        mock_process.terminate = MagicMock()

        # First wait times out, then after kill it succeeds
        wait_calls = [0]

        async def mock_wait():
            wait_calls[0] += 1
            if wait_calls[0] == 1:
                raise asyncio.TimeoutError()
            return None

        mock_process.wait = AsyncMock(side_effect=mock_wait)
        mock_process.kill = MagicMock()
        trader_proxy.process = mock_process

        await trader_proxy._cleanup_subprocess()

        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_subprocess_no_process(self, trader_proxy):
        """测试清理无进程"""
        trader_proxy.process = None

        # 不应该抛出异常
        await trader_proxy._cleanup_subprocess()

    @pytest.mark.asyncio
    async def test_force_kill_trader(self, trader_proxy, tmp_path):
        """测试强制停止trader进程"""
        pid_path = tmp_path / "qtrader_test_account_001.pid"
        pid_path.write_text("12345")
        trader_proxy.pid_file = str(pid_path)

        with patch("os.kill", side_effect=[None, OSError("Process dead")]):
            await trader_proxy._force_kill_trader()

        assert not pid_path.exists()

    @pytest.mark.asyncio
    async def test_force_kill_trader_sigkill(self, trader_proxy, tmp_path):
        """测试强制使用SIGKILL"""
        pid_path = tmp_path / "qtrader_test_account_001.pid"
        pid_path.write_text("12345")
        trader_proxy.pid_file = str(pid_path)

        # 进程在SIGTERM后仍然存活
        call_count = [0]

        def mock_kill(pid, sig):
            call_count[0] += 1
            if sig == 15:  # SIGTERM
                return None
            elif sig == 0:  # 检查进程
                if call_count[0] < 12:
                    return None
                raise OSError("Process dead")
            elif sig == 9:  # SIGKILL
                raise OSError("Process dead")

        with patch("os.kill", side_effect=mock_kill):
            await trader_proxy._force_kill_trader()

        assert not pid_path.exists()

    @pytest.mark.asyncio
    async def test_force_kill_trader_no_pid_file(self, trader_proxy):
        """测试无PID文件时强制停止"""
        trader_proxy.pid_file = "/nonexistent/pid"

        # 不应该抛出异常
        await trader_proxy._force_kill_trader()


# ==================== Test Message Handling ====================


class TestTraderProxyMessageHandling:
    """测试消息处理"""

    def test_update_heartbeat(self, trader_proxy):
        """测试更新心跳"""
        old_time = trader_proxy.last_heartbeat
        import time
        time.sleep(0.01)

        trader_proxy._update_heartbeat()

        assert trader_proxy.last_heartbeat > old_time

    def test_on_msg_callback_heartbeat(self, trader_proxy):
        """测试心跳消息回调"""
        trader_proxy._on_msg_callback("heartbeat", {})

        # 心跳消息只更新时间，不emit
        assert trader_proxy.last_heartbeat is not None

    def test_on_msg_callback_emit_data(self, trader_proxy, mock_event_engine):
        """测试数据消息回调"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._on_msg_callback("account", {"account_id": "test"})

            mock_event_engine.put.assert_called_once()

    def test_on_msg_callback_exception(self, trader_proxy):
        """测试消息回调异常处理"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(side_effect=Exception("Event error")))):
            # 不应该抛出异常
            trader_proxy._on_msg_callback("account", {"account_id": "test"})

    def test_emit_data_account(self, trader_proxy, mock_event_engine):
        """测试emit账户数据"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._emit_data("account", {"account_id": "test"})

            mock_event_engine.put.assert_called_once_with("e:account.update", {"account_id": "test"})

    def test_emit_data_order(self, trader_proxy, mock_event_engine):
        """测试emit订单数据"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._emit_data("order", {"order_id": "test"})

            mock_event_engine.put.assert_called_once_with("e:order.update", {"order_id": "test"})

    def test_emit_data_trade(self, trader_proxy, mock_event_engine):
        """测试emit成交数据"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._emit_data("trade", {"trade_id": "test"})

            mock_event_engine.put.assert_called_once_with("e:trade.created", {"trade_id": "test"})

    def test_emit_data_position(self, trader_proxy, mock_event_engine):
        """测试emit持仓数据"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._emit_data("position", {"symbol": "test"})

            mock_event_engine.put.assert_called_once_with("e:position.update", {"symbol": "test"})

    def test_emit_data_tick(self, trader_proxy, mock_event_engine):
        """测试emit行情数据"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._emit_data("tick", {"symbol": "test"})

            mock_event_engine.put.assert_called_once_with("e:tick.update", {"symbol": "test"})

    def test_emit_data_unknown_type(self, trader_proxy, mock_event_engine):
        """测试emit未知类型"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine))):
            trader_proxy._emit_data("unknown", {"data": "test"})

            # 未知类型不应该触发事件
            mock_event_engine.put.assert_not_called()


# ==================== Test Data Query Methods ====================


class TestTraderProxyDataQuery:
    """测试数据查询方法"""

    @pytest.mark.asyncio
    async def test_get_account_no_socket(self, trader_proxy):
        """测试无socket时获取账户"""
        trader_proxy.socket_client = None

        result = await trader_proxy.get_account()

        assert result.account_id == "test_account_001"

    @pytest.mark.asyncio
    async def test_get_account_success(self, trader_proxy, mock_socket_client):
        """测试成功获取账户"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value={
            "account_id": "test_account_001",
            "balance": 100000.0,
            "available": 95000.0,
        })
        trader_proxy._state = TraderState.CONNECTED

        result = await trader_proxy.get_account()

        assert result.account_id == "test_account_001"
        assert result.balance == 100000.0

    @pytest.mark.asyncio
    async def test_get_account_no_data(self, trader_proxy, mock_socket_client):
        """测试获取账户无数据"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=None)

        result = await trader_proxy.get_account()

        assert result.account_id == "test_account_001"

    @pytest.mark.asyncio
    async def test_get_order_success(self, trader_proxy, mock_socket_client):
        """测试成功获取订单"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value={
            "order_id": "order_123",
            "symbol": "SHFE.rb2505",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 3500.0,
            "traded": 0,
            "status": "ACTIVE",
            "account_id": "test_account_001",
        })

        result = await trader_proxy.get_order("order_123")

        assert result.order_id == "order_123"

    @pytest.mark.asyncio
    async def test_get_order_no_socket(self, trader_proxy):
        """测试无socket时获取订单"""
        trader_proxy.socket_client = None

        result = await trader_proxy.get_order("order_123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_orders_success(self, trader_proxy, mock_socket_client):
        """测试成功获取所有订单"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[
            {
                "order_id": "order_1",
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": 3500.0,
                "traded": 0,
                "status": "ACTIVE",
                "account_id": "test_account_001",
            },
            {
                "order_id": "order_2",
                "symbol": "SHFE.rb2505",
                "direction": "SELL",
                "offset": "CLOSE",
                "volume": 1,
                "price": 3500.0,
                "traded": 1,
                "status": "FILLED",
                "account_id": "test_account_001",
            },
        ])

        result = await trader_proxy.get_orders()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_orders_empty(self, trader_proxy, mock_socket_client):
        """测试获取订单列表为空"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[])

        result = await trader_proxy.get_orders()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_orders(self, trader_proxy, mock_socket_client):
        """测试获取活动订单"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[
            {
                "order_id": "order_1",
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": 3500.0,
                "traded": 0,
                "status": "ACTIVE",
                "account_id": "test_account_001",
            },
        ])

        result = await trader_proxy.get_active_orders()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_trade_success(self, trader_proxy, mock_socket_client):
        """测试成功获取成交"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value={
            "trade_id": "trade_123",
            "order_id": "order_123",
            "symbol": "SHFE.rb2505",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 3500.0,
            "account_id": "test_account_001",
        })

        result = await trader_proxy.get_trade("trade_123")

        assert result.trade_id == "trade_123"

    @pytest.mark.asyncio
    async def test_get_trades_success(self, trader_proxy, mock_socket_client):
        """测试成功获取所有成交"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[
            {
                "trade_id": "trade_1",
                "order_id": "order_1",
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": 3500.0,
                "account_id": "test_account_001",
            },
            {
                "trade_id": "trade_2",
                "order_id": "order_2",
                "symbol": "SHFE.rb2505",
                "direction": "SELL",
                "offset": "CLOSE",
                "volume": 1,
                "price": 3500.0,
                "account_id": "test_account_001",
            },
        ])

        result = await trader_proxy.get_trades()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_positions_success(self, trader_proxy, mock_socket_client):
        """测试成功获取持仓"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[
            {
                "symbol": "SHFE.rb2505",
                "exchange": "SHFE",
                "pos": 1,
                "pos_long": 1,
                "pos_short": 0,
            },
        ])

        result = await trader_proxy.get_positions()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_quotes_success(self, trader_proxy, mock_socket_client):
        """测试成功获取行情"""
        from datetime import datetime

        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[
            {
                "symbol": "SHFE.rb2505",
                "exchange": "SHFE",
                "datetime": datetime.now().isoformat(),
                "last_price": 3500.0,
            },
        ])

        result = await trader_proxy.get_quotes()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_jobs_success(self, trader_proxy, mock_socket_client):
        """测试成功获取任务"""
        from src.utils.scheduler import Job

        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.request = AsyncMock(return_value=[
            {"job_id": "job_1", "name": "test_job"},
        ])

        result = await trader_proxy.get_jobs()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_send_request_success(self, trader_proxy, mock_socket_client):
        """测试通用请求成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={"result": "ok"})

        result = await trader_proxy.send_request("custom_request", {"param": "value"})

        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self, trader_proxy, mock_socket_client):
        """测试未连接时发送请求"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=False)

        result = await trader_proxy.send_request("custom_request", {})

        assert result is None

    @pytest.mark.asyncio
    async def test_send_request_exception(self, trader_proxy, mock_socket_client):
        """测试发送请求异常"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(side_effect=Exception("Request error"))

        result = await trader_proxy.send_request("custom_request", {})

        assert result is None


# ==================== Test Trading Methods ====================


class TestTraderProxyTrading:
    """测试交易方法"""

    @pytest.mark.asyncio
    async def test_send_order_request_success(self, trader_proxy, mock_socket_client):
        """测试发送下单请求成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value="order_123")

        result = await trader_proxy.send_order_request(
            symbol="SHFE.rb2505",
            direction="BUY",
            offset="OPEN",
            volume=1,
            price=3500.0
        )

        assert result == "order_123"

    @pytest.mark.asyncio
    async def test_send_order_request_not_connected(self, trader_proxy):
        """测试未连接时下单"""
        trader_proxy.socket_client = None

        result = await trader_proxy.send_order_request("SHFE.rb2505", "BUY", "OPEN", 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_send_order_request_exception(self, trader_proxy, mock_socket_client):
        """测试下单请求异常"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(side_effect=Exception("Order error"))

        result = await trader_proxy.send_order_request("SHFE.rb2505", "BUY", "OPEN", 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_send_cancel_request_success(self, trader_proxy, mock_socket_client):
        """测试发送撤单请求成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value=True)

        result = await trader_proxy.send_cancel_request("order_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_send_cancel_request_not_connected(self, trader_proxy):
        """测试未连接时撤单"""
        trader_proxy.socket_client = None

        result = await trader_proxy.send_cancel_request("order_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_success(self, trader_proxy, mock_socket_client):
        """测试订阅成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value=True)

        result = await trader_proxy.subscribe({"symbol": "SHFE.rb2505"})

        assert result is True

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self, trader_proxy):
        """测试未连接时订阅"""
        trader_proxy.socket_client = None

        result = await trader_proxy.subscribe({"symbol": "SHFE.rb2505"})

        assert result is False


# ==================== Test Gateway Control ====================


class TestTraderProxyGatewayControl:
    """测试网关控制方法"""

    @pytest.mark.asyncio
    async def test_connect_gateway_success(self, trader_proxy, mock_socket_client):
        """测试连接网关成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={"success": True})

        result = await trader_proxy.connect()

        assert result is True

    @pytest.mark.asyncio
    async def test_connect_gateway_not_connected(self, trader_proxy):
        """测试未连接时连接网关"""
        trader_proxy.socket_client = None

        result = await trader_proxy.connect()

        assert result is False

    @pytest.mark.asyncio
    async def test_connect_gateway_no_success_key(self, trader_proxy, mock_socket_client):
        """测试连接网关响应无success字段"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={})

        result = await trader_proxy.connect()

        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_gateway_success(self, trader_proxy, mock_socket_client):
        """测试断开网关成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={"success": True})

        result = await trader_proxy.disconnect()

        assert result is True

    @pytest.mark.asyncio
    async def test_pause_trading_success(self, trader_proxy, mock_socket_client):
        """测试暂停交易成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={"success": True})

        result = await trader_proxy.pause()

        assert result is True

    @pytest.mark.asyncio
    async def test_resume_trading_success(self, trader_proxy, mock_socket_client):
        """测试恢复交易成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={"success": True})

        result = await trader_proxy.resume()

        assert result is True

    def test_gateway_property_connected(self, trader_proxy):
        """测试gateway属性connected为True"""
        trader_proxy._state = TraderState.CONNECTED

        result = trader_proxy.gateway.connected

        assert result is True

    def test_gateway_property_not_connected(self, trader_proxy):
        """测试gateway属性connected为False"""
        trader_proxy._state = TraderState.CONNECTING

        result = trader_proxy.gateway.connected

        assert result is False


# ==================== Test Utility Methods ====================


class TestTraderProxyUtility:
    """测试工具方法"""

    @pytest.mark.asyncio
    async def test_restart(self, trader_proxy):
        """测试重启"""
        with patch.object(trader_proxy, "stop", new=AsyncMock(return_value=True)), \
             patch.object(trader_proxy, "start", new=AsyncMock(return_value=True)):
            result = await trader_proxy.restart()

            assert result is True
            assert trader_proxy.restart_count == 1

    @pytest.mark.asyncio
    async def test_restart_failure(self, trader_proxy):
        """测试重启失败"""
        with patch.object(trader_proxy, "stop", new=AsyncMock(return_value=True)), \
             patch.object(trader_proxy, "start", new=AsyncMock(return_value=False)):
            result = await trader_proxy.restart()

            assert result is False

    def test_is_running_true(self, trader_proxy):
        """测试运行中状态"""
        trader_proxy._state = TraderState.CONNECTED

        result = trader_proxy.is_running()

        assert result is True

    def test_is_running_false(self, trader_proxy):
        """测试非运行中状态"""
        trader_proxy._state = TraderState.STOPPED

        result = trader_proxy.is_running()

        assert result is False

    def test_is_alive_with_process(self, trader_proxy):
        """测试进程存活检查（有进程）"""
        mock_process = MagicMock()
        mock_process.returncode = None
        trader_proxy.process = mock_process
        trader_proxy._created_process = True

        result = trader_proxy.is_alive()

        assert result is True

    def test_is_alive_process_dead(self, trader_proxy):
        """测试进程存活检查（进程已死）"""
        mock_process = MagicMock()
        mock_process.returncode = 1
        trader_proxy.process = mock_process
        trader_proxy._created_process = True

        result = trader_proxy.is_alive()

        assert result is False

    def test_is_alive_by_heartbeat(self, trader_proxy):
        """测试通过心跳判断存活"""
        trader_proxy._state = TraderState.CONNECTED
        trader_proxy.last_heartbeat = datetime.now()

        result = trader_proxy.is_alive()

        assert result is True

    def test_is_alive_heartbeat_timeout(self, trader_proxy):
        """测试心跳超时"""
        from datetime import timedelta
        trader_proxy._state = TraderState.CONNECTED
        trader_proxy.last_heartbeat = datetime.now() - timedelta(seconds=40)
        trader_proxy.heartbeat_timeout = 30

        result = trader_proxy.is_alive()

        assert result is False

    def test_get_status(self, trader_proxy):
        """测试获取状态"""
        trader_proxy._state = TraderState.CONNECTED
        mock_process = MagicMock()
        mock_process.pid = 12345
        trader_proxy.process = mock_process
        trader_proxy.start_time = datetime.now()
        trader_proxy.restart_count = 2

        result = trader_proxy.get_status()

        assert result["account_id"] == "test_account_001"
        assert result["state"] == "connected"
        assert result["running"] is True
        assert result["connected"] is True
        assert result["pid"] == 12345
        assert result["restart_count"] == 2

    @pytest.mark.asyncio
    async def test_ping_success(self, trader_proxy, mock_socket_client):
        """测试心跳成功"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value={"pong": True})

        result = await trader_proxy.ping()

        assert result is True

    @pytest.mark.asyncio
    async def test_ping_not_connected(self, trader_proxy):
        """测试未连接时心跳"""
        trader_proxy.socket_client = None

        result = await trader_proxy.ping()

        assert result is False

    @pytest.mark.asyncio
    async def test_ping_no_response(self, trader_proxy, mock_socket_client):
        """测试心跳无响应"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(return_value=None)

        result = await trader_proxy.ping()

        assert result is False

    @pytest.mark.asyncio
    async def test_ping_exception(self, trader_proxy, mock_socket_client):
        """测试心跳异常"""
        trader_proxy.socket_client = mock_socket_client
        mock_socket_client.is_connected = MagicMock(return_value=True)
        mock_socket_client.request = AsyncMock(side_effect=Exception("Ping error"))

        result = await trader_proxy.ping()

        assert result is False


# ==================== Edge Cases ====================


class TestTraderProxyEdgeCases:
    """测试边界情况"""

    @pytest.mark.asyncio
    async def test_start_stop_multiple_times(self, trader_proxy, mock_socket_client):
        """测试多次启停"""
        with patch.object(trader_proxy, "_check_process_exists", return_value=False), \
             patch.object(trader_proxy, "_create_subprocess", new=AsyncMock()), \
             patch("src.manager.trader_proxy.SocketClient", return_value=mock_socket_client), \
             patch.object(mock_socket_client, "connect", return_value=True):
            # 第一次启动
            result1 = await trader_proxy.start()
            assert result1 is True

            # 停止
            await trader_proxy.stop()

            # 第二次启动
            result2 = await trader_proxy.start()
            assert result2 is True

    @pytest.mark.asyncio
    async def test_concurrent_start_calls(self, trader_proxy, mock_socket_client):
        """测试并发调用start"""
        with patch.object(trader_proxy, "_check_process_exists", return_value=False), \
             patch.object(trader_proxy, "_create_subprocess", new=AsyncMock()), \
             patch("src.manager.trader_proxy.SocketClient", return_value=mock_socket_client):
            # 并发启动
            results = await asyncio.gather(
                trader_proxy.start(),
                trader_proxy.start(),
                return_exceptions=True
            )

            # 只有一个应该成功
            success_count = sum(1 for r in results if r is True)
            assert success_count <= 1

    @pytest.mark.asyncio
    async def test_concurrent_stop_calls(self, trader_proxy, mock_socket_client):
        """测试并发调用stop"""
        trader_proxy.socket_client = mock_socket_client
        trader_proxy._state = TraderState.CONNECTED

        # 并发停止
        results = await asyncio.gather(
            trader_proxy.stop(),
            trader_proxy.stop(),
            trader_proxy.stop(),
        )

        # 所有调用都应该成功
        assert all(results)

    def test_status_with_none_process(self, trader_proxy):
        """测试获取状态（无进程）"""
        trader_proxy.process = None

        result = trader_proxy.get_status()

        assert result["pid"] is None

    def test_status_with_none_start_time(self, trader_proxy):
        """测试获取状态（无启动时间）"""
        trader_proxy.start_time = None

        result = trader_proxy.get_status()

        assert result["start_time"] is None

    @pytest.mark.asyncio
    async def test_emit_data_no_event_engine(self, trader_proxy):
        """测试无事件引擎时emit"""
        with patch("src.manager.trader_proxy.ctx", MagicMock(get_event_engine=MagicMock(return_value=None))):
            # 不应该抛出异常
            trader_proxy._emit_data("account", {"account_id": "test"})
