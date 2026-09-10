"""
SocketClient 单元测试

覆盖当前 V2 客户端：初始化配置、消息处理（响应/推送/心跳）、
请求-响应语义（含超时与错误路径），以及基于真实 Unix Socket 回环的
端到端请求/推送验证。
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from qtrader.utils.ipc.protocol import RemoteHandlerError, create_push, create_response
from qtrader.utils.ipc.socket_client import SocketClient
from qtrader.utils.ipc.socket_server import SocketServer


@pytest.fixture
def client(tmp_path) -> SocketClient:
    return SocketClient(str(tmp_path / "qtrader_test.sock"), "MGR")


@pytest.mark.unit
class TestSocketClientInit:
    """初始化配置"""

    def test_init_defaults(self, client):
        assert client.account_id == "MGR"
        assert client.connected is False
        assert client.on_data_callback is None
        assert client._auto_reconnect is True
        assert client._heartbeat_interval == 15.0
        assert client._request_timeout == 10.0

    def test_init_custom_params(self, tmp_path):
        c = SocketClient(
            str(tmp_path / "s.sock"),
            "DQ",
            auto_reconnect=False,
            reconnect_interval=5.0,
            heartbeat_interval=30.0,
            request_timeout=3.0,
        )
        assert c._auto_reconnect is False
        assert c._reconnect_interval == 5.0
        assert c._heartbeat_interval == 30.0
        assert c._request_timeout == 3.0

    def test_is_connected_false_initially(self, client):
        assert client.is_connected() is False

    def test_get_stats(self, client):
        stats = client.get_stats()
        assert stats["connected"] is False
        assert stats["pending_requests"] == 0
        assert stats["auto_reconnect"] is True

    def test_on_push_registers_handler(self, client):
        @client.on_push("account")
        def handle(push_type, data):
            pass

        assert "account" in client._push_handlers

    def test_callback_setters(self, client):
        cb = lambda: None
        client.set_connect_callback(cb)
        client.set_disconnect_callback(cb)
        assert client._on_connect_callback is cb
        assert client._on_disconnect_callback is cb


@pytest.mark.unit
class TestHandleMessage:
    """消息处理（不经过网络）"""

    @pytest.mark.asyncio
    async def test_response_resolves_pending_future(self, client):
        future: asyncio.Future = asyncio.Future()
        client._pending_requests["req_1"] = future

        await client._handle_message(create_response({"ok": 1}, "req_1"))

        assert future.done()
        assert future.result() == {"ok": 1}
        assert "req_1" not in client._pending_requests

    @pytest.mark.asyncio
    async def test_error_response_rejects_future(self, client):
        future: asyncio.Future = asyncio.Future()
        client._pending_requests["req_2"] = future

        await client._handle_message(create_response(None, "req_2", error="boom"))

        assert future.done()
        with pytest.raises(Exception, match="boom"):
            future.result()

    @pytest.mark.asyncio
    async def test_response_without_request_id_ignored(self, client):
        # 服务器注册确认无 request_id，应静默忽略
        await client._handle_message(create_response({"account_id": "X"}, ""))

    @pytest.mark.asyncio
    async def test_unknown_response_ignored(self, client):
        await client._handle_message(create_response({"x": 1}, "unknown"))

    @pytest.mark.asyncio
    async def test_push_invokes_registered_handler(self, client):
        received = []

        @client.on_push("order")
        async def handle(push_type, data):
            received.append((push_type, data))

        await client._handle_message(create_push("order", {"order_id": "o1"}))

        assert received == [("order", {"order_id": "o1"})]

    @pytest.mark.asyncio
    async def test_push_falls_back_to_data_callback(self, client):
        received = []
        client.on_data_callback = lambda push_type, data: received.append((push_type, data))

        await client._handle_message(create_push("position", {"symbol": "rb2505"}))

        assert received == [("position", {"symbol": "rb2505"})]

    @pytest.mark.asyncio
    async def test_push_without_handler_no_error(self, client):
        await client._handle_message(create_push("unknown_type", {}))

    @pytest.mark.asyncio
    async def test_push_handler_exception_swallowed(self, client):
        @client.on_push("trade")
        async def handle(push_type, data):
            raise RuntimeError("boom")

        await client._handle_message(create_push("trade", {}))

    @pytest.mark.asyncio
    async def test_heartbeat_ignored(self, client):
        from qtrader.utils.ipc.protocol import create_heartbeat

        await client._handle_message(create_heartbeat())


@pytest.mark.unit
class TestRequestNotConnected:
    """未连接时的请求语义"""

    @pytest.mark.asyncio
    async def test_request_not_connected_returns_none(self, client):
        assert await client.request("get_orders", {}) is None


async def _start_ipc_pair(socket_path: str):
    """在指定路径启动回环服务器并连接客户端，返回 (server, client)"""
    server = SocketServer(socket_path, "TEST", enable_health_check=False)
    server.register_handler("echo", lambda data: {"echo": data})
    server.register_handler("add", lambda data: {"sum": data.get("a", 0) + data.get("b", 0)})

    async def slow_handler(data):
        await asyncio.sleep(2)
        return {}

    server.register_handler("slow", slow_handler)

    async def fail_handler(data):
        raise RuntimeError("handler boom")

    server.register_handler("fail", fail_handler)

    server_task = asyncio.create_task(server.start())
    for _ in range(100):
        await asyncio.sleep(0.02)
        if Path(socket_path).exists():
            break

    client = SocketClient(socket_path, "MGR")
    connected = await client.connect(max_retries=5, retry_interval=0.05)
    assert connected is True
    server._test_task = server_task  # 挂到实例上，便于清理
    return server, client


@pytest_asyncio.fixture
async def ipc_pair():
    """真实 Unix Socket 回环：服务器 + 已连接客户端

    使用短路径临时目录（macOS 限制 unix socket 路径 ≤104 字符，
    pytest tmp_path 含测试名可能超长）。
    """
    with tempfile.TemporaryDirectory(prefix="qt_sock_") as short_dir:
        socket_path = str(Path(short_dir) / "t.sock")
        server, client = await _start_ipc_pair(socket_path)
        yield server, client
        await client.disconnect()
        await server.stop()  # 先关闭客户端连接，否则 wait_closed 挂起
        server._test_task.cancel()
        try:
            await server._test_task
        except asyncio.CancelledError:
            pass


@pytest.mark.unit
class TestLoopback:
    """回环端到端（真实 Unix Socket）"""

    @pytest.mark.asyncio
    async def test_connect_fires_connect_callback(self, ipc_pair):
        server, client = ipc_pair
        fired = []
        client.set_connect_callback(lambda: fired.append(True))
        # 手动重连触发回调
        await client.disconnect()
        assert await client.connect(max_retries=5, retry_interval=0.05) is True
        assert fired == [True]

    @pytest.mark.asyncio
    async def test_request_response_roundtrip(self, ipc_pair):
        server, client = ipc_pair
        result = await client.request("add", {"a": 2, "b": 3})
        assert result == {"sum": 5}

    @pytest.mark.asyncio
    async def test_request_unknown_type_raises_remote_error(self, ipc_pair):
        """未知请求类型：对端错误以 RemoteHandlerError 上抛（真实原因）"""
        server, client = ipc_pair
        with pytest.raises(RemoteHandlerError, match="Unknown request type"):
            await client.request("no_such_type", {}, timeout=2.0)

    @pytest.mark.asyncio
    async def test_request_handler_error_raises_remote_error(self, ipc_pair):
        """handler 异常：对端回传的真实原因以 RemoteHandlerError 上抛"""
        server, client = ipc_pair
        with pytest.raises(RemoteHandlerError, match="RuntimeError: handler boom"):
            await client.request("fail", {}, timeout=2.0)

    @pytest.mark.asyncio
    async def test_request_timeout_returns_none(self, ipc_pair):
        server, client = ipc_pair
        assert await client.request("slow", {}, timeout=0.3) is None

    @pytest.mark.asyncio
    async def test_push_delivered_to_handler(self, ipc_pair):
        server, client = ipc_pair
        received = []

        @client.on_push("account")
        async def handle(push_type, data):
            received.append(data)

        assert await server.send_push("account", {"balance": 100}) is True
        for _ in range(50):
            await asyncio.sleep(0.02)
            if received:
                break
        assert received == [{"balance": 100}]

    @pytest.mark.asyncio
    async def test_push_delivered_to_data_callback(self, ipc_pair):
        server, client = ipc_pair
        received = []
        client.on_data_callback = lambda push_type, data: received.append((push_type, data))

        await server.send_push("tick_batch", {"ticks": [1]})
        for _ in range(50):
            await asyncio.sleep(0.02)
            if received:
                break
        assert received == [("tick_batch", {"ticks": [1]})]

    @pytest.mark.asyncio
    async def test_send_heartbeat_over_wire(self, ipc_pair):
        server, client = ipc_pair
        assert await client._send_heartbeat() is True

    @pytest.mark.asyncio
    async def test_disconnect_cancels_pending_request(self, ipc_pair):
        server, client = ipc_pair
        task = asyncio.create_task(client.request("slow", {}, timeout=5.0))
        await asyncio.sleep(0.05)
        await client.disconnect()

        assert await task is None

    @pytest.mark.asyncio
    async def test_get_stats_connected(self, ipc_pair):
        server, client = ipc_pair
        stats = client.get_stats()
        assert stats["connected"] is True
        assert stats["pending_requests"] == 0
