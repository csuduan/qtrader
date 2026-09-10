"""
SocketServer 单元测试

覆盖当前 V2 服务器：初始化统计、处理器注册（手动与 @request 装饰器）、
消息处理（心跳/请求/错误响应）、无客户端时的推送缓冲队列、
连接管理，以及基于真实 Unix Socket 回环的端到端验证。
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from qtrader.utils.ipc.protocol import (
    MessageBody,
    MessageType,
    create_heartbeat,
    create_request,
)
from qtrader.utils.ipc.socket_client import SocketClient
from qtrader.utils.ipc.socket_server import SocketClientConnection, SocketServer, request


@pytest.fixture
def server() -> SocketServer:
    return SocketServer("/tmp/qt_test_dummy.sock", "TEST", enable_health_check=False)


def make_conn(conn_id: str = "c1") -> MagicMock:
    """构造 mock 客户端连接"""
    conn = MagicMock()
    conn.conn_id = conn_id
    conn.is_connected.return_value = True
    conn.update_heartbeat = MagicMock()
    conn.send_message = AsyncMock(return_value=True)
    conn.close = AsyncMock()
    return conn


@pytest.mark.unit
class TestSocketServerInit:
    """初始化"""

    def test_init_state(self, server):
        assert server.account_id == "TEST"
        assert server._clients == {}
        assert server._req_handlers == {}
        assert server._running is False
        assert server.is_connected() is False
        assert server.get_connection_count() == 0

    def test_get_stats_initial(self, server):
        stats = server.get_stats()
        assert stats["total_connections"] == 0
        assert stats["messages_received"] == 0
        assert stats["messages_sent"] == 0
        assert stats["errors"] == 0
        assert stats["active_connections"] == 0
        assert stats["push_queue_size"] == 0


@pytest.mark.unit
class TestHandlerRegistration:
    """处理器注册"""

    def test_register_handler(self, server):
        server.register_handler("order_req", lambda data: True)
        assert "order_req" in server._req_handlers

    def test_register_handlers_from_instance(self, server):
        class Handlers:
            @request("connect")
            async def _req_connect(self, data):
                return True

            @request("order_req")
            async def _req_order(self, data):
                return "id"

            async def not_a_handler(self, data):
                return None

        server.register_handlers_from_instance(Handlers())

        assert set(server._req_handlers.keys()) == {"connect", "order_req"}


@pytest.mark.unit
class TestProcessMessage:
    """消息处理（mock 连接）"""

    @pytest.mark.asyncio
    async def test_heartbeat_updates_and_replies(self, server):
        conn = make_conn()
        await server._process_message(conn, create_heartbeat())

        conn.update_heartbeat.assert_called_once()
        conn.send_message.assert_awaited_once()
        reply = conn.send_message.call_args[0][0]
        assert reply.msg_type == MessageType.HEARTBEAT

    @pytest.mark.asyncio
    async def test_request_sync_handler(self, server):
        handler = MagicMock(return_value={"ok": 1})
        server.register_handler("query", handler)
        conn = make_conn()

        message = create_request({"type": "query", "data": {"k": 1}}, "req_1")
        await server._process_message(conn, message)

        handler.assert_called_once_with({"k": 1})
        response = conn.send_message.call_args[0][0]
        assert response.msg_type == MessageType.RESPONSE
        assert response.request_id == "req_1"
        assert response.data == {"ok": 1}
        assert response.error is None

    @pytest.mark.asyncio
    async def test_request_async_handler(self, server):
        async def async_handler(data):
            return {"async": True}

        server.register_handler("aquery", async_handler)
        conn = make_conn()

        await server._process_message(conn, create_request({"type": "aquery", "data": {}}, "r2"))

        response = conn.send_message.call_args[0][0]
        assert response.data == {"async": True}

    @pytest.mark.asyncio
    async def test_unknown_request_returns_error(self, server):
        conn = make_conn()

        await server._process_message(conn, create_request({"type": "nope", "data": {}}, "r3"))

        response = conn.send_message.call_args[0][0]
        assert response.error == "Unknown request type"

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error(self, server):
        def bad_handler(data):
            raise RuntimeError("boom")

        server.register_handler("bad", bad_handler)
        conn = make_conn()

        await server._process_message(conn, create_request({"type": "bad", "data": {}}, "r4"))

        response = conn.send_message.call_args[0][0]
        # IPC 为内部信任通道：异常类型与消息回传 Manager，前端才能看到真实失败原因
        assert response.error == "RuntimeError: boom"

    @pytest.mark.asyncio
    async def test_sync_handler_runs_in_thread(self, server):
        """同步 handler 应通过 to_thread 在工作线程执行，不占用事件循环线程"""
        import threading

        loop_thread = threading.get_ident()
        seen = {}

        def slow_handler(data):
            seen["thread"] = threading.get_ident()
            return {"ok": True}

        server.register_handler("slow", slow_handler)
        conn = make_conn()

        await server._process_message(conn, create_request({"type": "slow", "data": {}}, "r5"))

        response = conn.send_message.call_args[0][0]
        assert response.data == {"ok": True}
        assert seen["thread"] != loop_thread  # 在工作线程而非事件循环线程执行

    @pytest.mark.asyncio
    async def test_push_message_not_processed(self, server):
        conn = make_conn()
        message = MessageBody(
            msg_type=MessageType.PUSH, request_id="", data={"type": "x", "data": {}}
        )

        await server._process_message(conn, message)  # 仅记录，不响应

        conn.send_message.assert_not_awaited()


@pytest.mark.unit
class TestSendWithoutClients:
    """无客户端时的发送与缓冲"""

    @pytest.mark.asyncio
    async def test_send_message_no_clients(self, server):
        assert await server.send_message(create_heartbeat()) is False

    @pytest.mark.asyncio
    async def test_send_push_no_clients_buffered(self, server):
        assert await server.send_push("account", {"balance": 1}) is False
        assert server.get_stats()["push_queue_size"] == 1

    @pytest.mark.asyncio
    async def test_send_push_no_clients_not_buffered(self, server):
        assert await server.send_push("tick_batch", {"ticks": []}) is False
        assert server.get_stats()["push_queue_size"] == 0

    @pytest.mark.asyncio
    async def test_push_queue_bounded(self, server):
        # 超过上限后旧消息被挤出，队列长度不超过上限
        for i in range(SocketServer.PUSH_QUEUE_MAX_SIZE + 50):
            await server.send_push("account", {"i": i})
        assert len(server._push_queue) == SocketServer.PUSH_QUEUE_MAX_SIZE

    @pytest.mark.asyncio
    async def test_send_heartbeat_no_clients(self, server):
        assert await server.send_heartbeat() is False


@pytest.mark.unit
class TestConnectionLifecycle:
    """连接移除"""

    @pytest.mark.asyncio
    async def test_remove_client_connection(self, server):
        conn = make_conn()
        server._clients["c1"] = conn

        await server._remove_client_connection("c1")

        assert "c1" not in server._clients
        conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_unknown_connection_no_error(self, server):
        await server._remove_client_connection("ghost")


@pytest.mark.unit
class TestClientConnectionUnit:
    """SocketClientConnection 单元行为（真实连接）"""

    @pytest_asyncio.fixture
    async def conn_pair(self):
        with tempfile.TemporaryDirectory(prefix="qt_conn_") as short_dir:
            socket_path = str(Path(short_dir) / "c.sock")
            server = SocketServer(socket_path, "TEST", enable_health_check=False)
            server_task = asyncio.create_task(server.start())
            for _ in range(100):
                await asyncio.sleep(0.02)
                if Path(socket_path).exists():
                    break

            client = SocketClient(socket_path, "MGR")
            assert await client.connect(max_retries=5, retry_interval=0.05) is True
            for _ in range(50):
                await asyncio.sleep(0.02)
                if server._clients:
                    break

            conn = next(iter(server._clients.values()))
            yield server, conn, client

            await client.disconnect()
            await server.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_connection_registered(self, conn_pair):
        server, conn, client = conn_pair
        assert isinstance(conn, SocketClientConnection)
        assert conn.is_connected() is True
        assert server.get_connection_count() == 1
        assert server.is_connected() is True

    @pytest.mark.asyncio
    async def test_uptime_and_heartbeat(self, conn_pair):
        server, conn, client = conn_pair
        assert 0 <= conn.get_uptime() < 5
        assert 0 <= conn.get_time_since_last_heartbeat() < 5

        conn._last_heartbeat_time -= 10
        assert conn.get_time_since_last_heartbeat() >= 10
        conn.update_heartbeat()
        assert conn.get_time_since_last_heartbeat() < 1

    @pytest.mark.asyncio
    async def test_close_marks_disconnected(self, conn_pair):
        server, conn, client = conn_pair
        await conn.close()
        assert conn.is_connected() is False

    @pytest.mark.asyncio
    async def test_stats_count_connection(self, conn_pair):
        server, conn, client = conn_pair
        assert server.get_stats()["total_connections"] == 1


@pytest.mark.unit
class TestLoopback:
    """回环端到端（真实 Unix Socket）"""

    @pytest_asyncio.fixture
    async def pair(self):
        with tempfile.TemporaryDirectory(prefix="qt_srv_") as short_dir:
            socket_path = str(Path(short_dir) / "s.sock")
            server = SocketServer(socket_path, "TEST", enable_health_check=False)
            server.register_handler("echo", lambda data: {"echo": data})
            server_task = asyncio.create_task(server.start())
            for _ in range(100):
                await asyncio.sleep(0.02)
                if Path(socket_path).exists():
                    break
            server._test_task = server_task
            yield server, socket_path
            await server.stop()  # 先关闭客户端连接，否则 wait_closed 挂起
            server._test_task.cancel()
            try:
                await server._test_task
            except asyncio.CancelledError:
                pass

    async def _wait_for(self, cond, attempts: int = 50, interval: float = 0.02):
        """轮询等待条件成立"""
        for _ in range(attempts):
            await asyncio.sleep(interval)
            if cond():
                return True
        return False

    @pytest.mark.asyncio
    async def test_handler_exception_error_propagates_to_client(self, pair):
        """回环验证：handler 异常的真实原因经 IPC 完整传到客户端（Manager）"""
        server, socket_path = pair
        server.register_handler(
            "boom", lambda data: (_ for _ in ()).throw(RuntimeError("账户资金不足"))
        )
        client = SocketClient(socket_path, "MGR")
        assert await client.connect(max_retries=5, retry_interval=0.05) is True
        assert await self._wait_for(lambda: server.get_connection_count() == 1)

        with pytest.raises(Exception, match="账户资金不足"):
            await client.request("boom", {}, timeout=5.0)
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_push_with_connected_client(self, pair):
        server, socket_path = pair
        client = SocketClient(socket_path, "MGR")
        received = []
        client.on_data_callback = lambda t, d: received.append((t, d))
        assert await client.connect(max_retries=5, retry_interval=0.05) is True
        # 等待服务端完成连接注册，避免与 _handle_client 协程调度竞争
        assert await self._wait_for(lambda: server.get_connection_count() == 1)

        assert await server.send_push("account", {"balance": 9}) is True
        assert await self._wait_for(lambda: bool(received))
        assert received == [("account", {"balance": 9})]
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_buffered_push_flushed_on_reconnect(self, pair):
        server, socket_path = pair

        # 客户端未连接：account 推送进入缓冲队列
        await server.send_push("account", {"balance": 42})
        assert server.get_stats()["push_queue_size"] == 1

        client = SocketClient(socket_path, "MGR")
        received = []
        client.on_data_callback = lambda t, d: received.append((t, d))
        assert await client.connect(max_retries=5, retry_interval=0.05) is True

        # 连接建立后缓冲消息被自动下发
        for _ in range(50):
            await asyncio.sleep(0.02)
            if received:
                break
        assert received == [("account", {"balance": 42})]
        assert server.get_stats()["push_queue_size"] == 0
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_stats_messages_received(self, pair):
        server, socket_path = pair
        client = SocketClient(socket_path, "MGR")
        assert await client.connect(max_retries=5, retry_interval=0.05) is True

        await client.request("echo", {"a": 1})
        for _ in range(20):
            await asyncio.sleep(0.02)
            if server.get_stats()["messages_received"] >= 1:
                break

        stats = server.get_stats()
        assert stats["messages_received"] >= 1
        assert stats["messages_sent"] >= 1
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_disconnect_updates_connection_count(self, pair):
        server, socket_path = pair
        client = SocketClient(socket_path, "MGR")
        assert await client.connect(max_retries=5, retry_interval=0.05) is True
        for _ in range(50):
            await asyncio.sleep(0.02)
            if server.get_connection_count() == 1:
                break
        assert server.get_connection_count() == 1

        await client.disconnect()
        for _ in range(50):
            await asyncio.sleep(0.02)
            if server.get_connection_count() == 0:
                break
        assert server.get_connection_count() == 0
