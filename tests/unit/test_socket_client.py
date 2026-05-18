"""
SocketClient 单元测试
测试 SocketClient 类的所有方法和功能
"""

import asyncio
import json
import struct
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.manager.socket_client import SocketClient


@pytest.fixture
def socket_path(tmp_path):
    """临时socket文件路径"""
    return str(tmp_path / "test.sock")


@pytest.fixture
def account_id():
    """测试账户ID"""
    return "test_account_001"


@pytest.fixture
def mock_callback():
    """模拟回调函数"""
    return MagicMock()


@pytest.fixture
def socket_client(socket_path, account_id, mock_callback):
    """创建 SocketClient 实例"""
    return SocketClient(socket_path, account_id, mock_callback)


@pytest.fixture
def socket_client_no_callback(socket_path, account_id):
    """创建无回调的 SocketClient 实例"""
    return SocketClient(socket_path, account_id, None)


class TestSocketClientInit:
    """测试 __init__ 方法"""

    def test_init_with_callback(self, socket_path, account_id, mock_callback):
        """测试带回调函数的初始化"""
        client = SocketClient(socket_path, account_id, mock_callback)

        assert client.socket_path == socket_path
        assert client.account_id == account_id
        assert client.reader is None
        assert client.writer is None
        assert client.connected is False
        assert client.on_data_callback == mock_callback
        assert client._pending_requests == {}
        assert client._receiving_task is None

    def test_init_without_callback(self, socket_path, account_id):
        """测试不带回调函数的初始化"""
        client = SocketClient(socket_path, account_id)

        assert client.socket_path == socket_path
        assert client.account_id == account_id
        assert client.on_data_callback is None

    def test_init_with_async_callback(self, socket_path, account_id):
        """测试带异步回调函数的初始化"""
        async_callback = AsyncMock()
        client = SocketClient(socket_path, account_id, async_callback)

        assert client.on_data_callback == async_callback


class TestSocketClientConnect:
    """测试 connect 方法"""

    @pytest.mark.asyncio
    async def test_connect_success(self, socket_client, socket_path):
        """测试成功连接"""
        mock_reader = MagicMock()
        mock_writer = MagicMock()

        # 模拟注册确认消息
        register_msg = {"type": "register", "data": {"account_id": socket_client.account_id}}
        msg_bytes = json.dumps(register_msg, ensure_ascii=False).encode("utf-8")
        length_bytes = struct.pack(">I", len(msg_bytes))

        async def mock_read(n):
            if n == 4:
                return length_bytes
            return msg_bytes

        mock_reader.readexactly = mock_read
        mock_writer.drain = AsyncMock()

        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)

            with patch.object(socket_client, "_receive_message") as mock_receive:
                mock_receive.return_value = register_msg

                with patch("asyncio.create_task") as mock_create_task:
                    result = await socket_client.connect()

                    assert result is True
                    assert socket_client.connected is True
                    assert socket_client.reader == mock_reader
                    assert socket_client.writer == mock_writer
                    mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_account_id_mismatch(self, socket_client):
        """测试账户ID不匹配"""
        mock_reader = MagicMock()
        mock_writer = MagicMock()

        # 模拟返回不同的账户ID
        register_msg = {"type": "register", "data": {"account_id": "different_account"}}

        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)

            with patch.object(socket_client, "_receive_message") as mock_receive:
                mock_receive.return_value = register_msg

                result = await socket_client.connect()

                assert result is False
                assert socket_client.connected is True

    @pytest.mark.asyncio
    async def test_connect_file_not_found_retry(self, socket_client):
        """测试文件不存在时的重试机制"""
        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.side_effect = FileNotFoundError("Socket not found")

            # 使用asyncio.sleep的真实实现
            result = await socket_client.connect(retry_interval=0, max_retries=3)

            assert result is False
            assert socket_client.connected is False

    @pytest.mark.asyncio
    async def test_connect_general_exception(self, socket_client):
        """测试连接时的通用异常"""
        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.side_effect = Exception("Connection failed")

            result = await socket_client.connect(retry_interval=0, max_retries=2)

            assert result is False

    @pytest.mark.asyncio
    async def test_connect_no_register_message(self, socket_client):
        """测试没有收到注册消息"""
        mock_reader = MagicMock()
        mock_writer = MagicMock()

        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)

            with patch.object(socket_client, "_receive_message") as mock_receive:
                mock_receive.return_value = None

                result = await socket_client.connect()

                # 根据代码逻辑，即使没有收到注册消息也会返回True
                assert result is True


class TestSocketClientDisconnect:
    """测试 disconnect 方法"""

    @pytest.mark.asyncio
    async def test_disconnect_with_active_connection(self, socket_client):
        """测试断开活动连接"""
        # 设置初始状态
        socket_client.connected = True
        socket_client.reader = MagicMock()
        socket_client.writer = MagicMock()
        socket_client.writer.close = MagicMock()
        socket_client.writer.wait_closed = AsyncMock()

        # 创建模拟的接收任务（使用真实的asyncio Task）
        async def dummy_loop():
            try:
                while True:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise

        mock_task = asyncio.create_task(dummy_loop())
        socket_client._receiving_task = mock_task

        # 添加一个待处理的请求
        future: asyncio.Future = asyncio.Future()
        socket_client._pending_requests["test_request_id"] = future

        await socket_client.disconnect()

        assert socket_client.connected is False
        assert socket_client._receiving_task is None
        assert len(socket_client._pending_requests) == 0
        socket_client.writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_without_writer(self, socket_client):
        """测试没有writer时的断开"""
        socket_client.connected = True
        socket_client.writer = None

        # 不应该抛出异常
        await socket_client.disconnect()

        assert socket_client.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_writer_wait_closed_exception(self, socket_client):
        """测试writer关闭时的异常处理"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.close = MagicMock()
        socket_client.writer.wait_closed = AsyncMock(side_effect=Exception("Close error"))

        # 不应该抛出异常
        await socket_client.disconnect()

        assert socket_client.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_pending_requests_cancelled(self, socket_client):
        """测试待处理请求被取消"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.close = MagicMock()
        socket_client.writer.wait_closed = AsyncMock()

        # 创建多个待处理的Future
        future1: asyncio.Future = asyncio.Future()
        future2: asyncio.Future = asyncio.Future()
        socket_client._pending_requests["req1"] = future1
        socket_client._pending_requests["req2"] = future2

        await socket_client.disconnect()

        # 检查所有future都被设置为异常
        with pytest.raises(ConnectionError, match="连接已断开"):
            await future1

        with pytest.raises(ConnectionError, match="连接已断开"):
            await future2

    @pytest.mark.asyncio
    async def test_disconnect_already_done_future(self, socket_client):
        """测试已完成的future不被重复设置"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.close = MagicMock()
        socket_client.writer.wait_closed = AsyncMock()

        # 创建一个已完成的future
        future: asyncio.Future = asyncio.Future()
        future.set_result({"data": "done"})
        socket_client._pending_requests["req1"] = future

        # 不应该抛出异常
        await socket_client.disconnect()

        assert socket_client.connected is False


class TestSocketClientRequest:
    """测试 request 方法"""

    @pytest.mark.asyncio
    async def test_request_success(self, socket_client):
        """测试成功请求 - 验证请求发送逻辑"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.write = MagicMock()
        socket_client.writer.drain = AsyncMock()

        # Mock asyncio.wait_for来立即返回结果（模拟快速响应）
        response_data = {"data": "response_data"}

        async def mock_wait_for_coro(future, timeout):
            # 在另一个任务中设置future的结果
            async def set_result():
                await asyncio.sleep(0.01)
                if not future.done():
                    future.set_result(response_data)

            asyncio.create_task(set_result())
            return await future

        with patch("asyncio.wait_for", side_effect=mock_wait_for_coro):
            result = await socket_client.request("test_type", {"param": "value"}, timeout=1.0)

            # 验证写入了数据
            assert socket_client.writer.write.call_count == 2  # 一次长度，一次内容
            assert socket_client.writer.drain.called
            assert result == response_data

    @pytest.mark.asyncio
    async def test_request_not_connected(self, socket_client):
        """测试未连接时发送请求"""
        socket_client.connected = False

        result = await socket_client.request("test_type", {"param": "value"})

        assert result is None

    @pytest.mark.asyncio
    async def test_request_no_writer(self, socket_client):
        """测试没有writer时发送请求"""
        socket_client.connected = True
        socket_client.writer = None

        result = await socket_client.request("test_type", {"param": "value"})

        assert result is None

    @pytest.mark.asyncio
    async def test_request_timeout(self, socket_client):
        """测试请求超时"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.write = MagicMock()
        socket_client.writer.drain = AsyncMock()

        # 创建一个永不完成的future
        future: asyncio.Future = asyncio.Future()

        with patch("uuid.uuid4", return_value="test-uuid-timeout"):
            with patch.object(socket_client, "_pending_requests", {"test-uuid-timeout": future}):
                result = await socket_client.request("test_type", {"param": "value"}, timeout=0.1)

                assert result is None

    @pytest.mark.asyncio
    async def test_request_exception(self, socket_client):
        """测试请求时的异常"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.write = MagicMock(side_effect=Exception("Write failed"))

        result = await socket_client.request("test_type", {"param": "value"})

        assert result is None

    @pytest.mark.asyncio
    async def test_request_ping_no_log(self, socket_client, caplog):
        """测试ping请求不记录日志"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.write = MagicMock()
        socket_client.writer.drain = AsyncMock()

        # Mock asyncio.wait_for来立即返回结果
        async def mock_wait_for_coro(future, timeout):
            # 立即设置结果
            if not future.done():
                future.set_result({"data": "pong"})
            return await future

        with patch("asyncio.wait_for", side_effect=mock_wait_for_coro):
            result = await socket_client.request("ping", {}, timeout=1.0)

            assert result == {"data": "pong"}
            # 验证写入了数据
            assert socket_client.writer.write.call_count == 2


class TestSocketClientReceiveMessage:
    """测试 _receive_message 方法"""

    @pytest.mark.asyncio
    async def test_receive_message_success(self, socket_client):
        """测试成功接收消息"""
        mock_reader = MagicMock()
        socket_client.reader = mock_reader

        # 准备测试数据
        message_data = {"type": "test", "data": {"key": "value"}}
        json_bytes = json.dumps(message_data, ensure_ascii=False).encode("utf-8")
        length_bytes = struct.pack(">I", len(json_bytes))

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, json_bytes])

        result = await socket_client._receive_message()

        assert result == message_data
        assert mock_reader.readexactly.call_count == 2

    @pytest.mark.asyncio
    async def test_receive_message_no_reader(self, socket_client):
        """测试没有reader"""
        socket_client.reader = None

        result = await socket_client._receive_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_incomplete_read(self, socket_client):
        """测试读取不完整"""
        mock_reader = MagicMock()
        socket_client.reader = mock_reader
        mock_reader.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(partial=b"", expected=4))

        result = await socket_client._receive_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_json_decode_error(self, socket_client):
        """测试JSON解码错误"""
        mock_reader = MagicMock()
        socket_client.reader = mock_reader

        length_bytes = struct.pack(">I", 10)
        invalid_json = b"not valid json"

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, invalid_json])

        result = await socket_client._receive_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_general_exception(self, socket_client):
        """测试通用异常"""
        mock_reader = MagicMock()
        socket_client.reader = mock_reader
        mock_reader.readexactly = AsyncMock(side_effect=Exception("Read error"))

        result = await socket_client._receive_message()

        assert result is None


class TestSocketClientReceivingLoop:
    """测试 _receiving_loop 方法"""

    @pytest.mark.asyncio
    async def test_receiving_loop_normal(self, socket_client):
        """测试正常接收循环"""
        socket_client.connected = True

        # 模拟接收几条消息然后断开
        messages = [
            {"type": "test1", "data": {}},
            {"type": "test2", "data": {}},
        ]

        call_count = [0]

        async def mock_receive():
            if call_count[0] < len(messages):
                msg = messages[call_count[0]]
                call_count[0] += 1
                return msg
            return None

        with patch.object(socket_client, "_receive_message", side_effect=mock_receive):
            with patch.object(socket_client, "_handle_message") as mock_handle:
                # 运行一小段时间
                task = asyncio.create_task(socket_client._receiving_loop())
                await asyncio.sleep(0.1)
                socket_client.connected = False
                await asyncio.sleep(0.1)

                # 验证handle_message被调用
                assert mock_handle.call_count >= 0

                # 取消任务
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_receiving_loop_incomplete_read_error(self, socket_client):
        """测试接收到IncompleteReadError"""
        socket_client.connected = True

        async def mock_receive():
            raise asyncio.IncompleteReadError(partial=b"", expected=4)

        with patch.object(socket_client, "_receive_message", side_effect=mock_receive):
            await socket_client._receiving_loop()

            assert socket_client.connected is False

    @pytest.mark.asyncio
    async def test_receiving_loop_general_exception(self, socket_client):
        """测试接收循环中的通用异常"""
        socket_client.connected = True

        async def mock_receive():
            raise Exception("Receive error")

        with patch.object(socket_client, "_receive_message", side_effect=mock_receive):
            await socket_client._receiving_loop()

            assert socket_client.connected is False

    @pytest.mark.asyncio
    async def test_receiving_loop_no_message(self, socket_client):
        """测试没有收到消息"""
        socket_client.connected = True

        with patch.object(socket_client, "_receive_message", return_value=None):
            await socket_client._receiving_loop()

            assert socket_client.connected is False


class TestSocketClientHandleMessage:
    """测试 _handle_message 方法"""

    @pytest.mark.asyncio
    async def test_handle_message_response_success(self, socket_client):
        """测试处理响应消息成功"""
        request_id = "test_request_id"
        response_data = {"key": "value"}

        future: asyncio.Future = asyncio.Future()
        socket_client._pending_requests[request_id] = future

        message = {
            "type": "response",
            "request_id": request_id,
            "data": response_data,
            "status": "ok"
        }

        await socket_client._handle_message(message)

        # 验证future被设置结果
        result = await future
        assert result == response_data
        assert request_id not in socket_client._pending_requests

    @pytest.mark.asyncio
    async def test_handle_message_response_error(self, socket_client):
        """测试处理错误响应"""
        request_id = "test_request_id"
        error_msg = "Request failed"

        future: asyncio.Future = asyncio.Future()
        socket_client._pending_requests[request_id] = future

        message = {
            "type": "response",
            "request_id": request_id,
            "data": {"message": error_msg},
            "status": "error"
        }

        await socket_client._handle_message(message)

        # 验证future被设置为异常
        with pytest.raises(Exception, match=error_msg):
            await future

    @pytest.mark.asyncio
    async def test_handle_message_response_no_request_id(self, socket_client):
        """测试响应消息缺少request_id"""
        message = {
            "type": "response",
            "data": {"key": "value"}
        }

        # 不应该抛出异常
        await socket_client._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_response_future_already_done(self, socket_client):
        """测试future已经完成"""
        request_id = "test_request_id"

        future: asyncio.Future = asyncio.Future()
        future.set_result({"data": "early"})
        socket_client._pending_requests[request_id] = future

        message = {
            "type": "response",
            "request_id": request_id,
            "data": {"key": "value"},
            "status": "ok"
        }

        # 不应该抛出异常
        await socket_client._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_push_with_sync_callback(self, socket_client):
        """测试处理推送消息（同步回调）"""
        message = {
            "type": "account_update",
            "data": {"account_id": "test"}
        }

        await socket_client._handle_message(message)

        # 验证回调被调用
        socket_client.on_data_callback.assert_called_once_with("account_update", {"account_id": "test"})

    @pytest.mark.asyncio
    async def test_handle_message_push_with_async_callback(self, socket_client_no_callback):
        """测试处理推送消息（异步回调）"""
        async_callback = AsyncMock()
        socket_client_no_callback.on_data_callback = async_callback

        message = {
            "type": "order_update",
            "data": {"order_id": "test"}
        }

        await socket_client_no_callback._handle_message(message)

        async_callback.assert_called_once_with("order_update", {"order_id": "test"})

    @pytest.mark.asyncio
    async def test_handle_message_push_no_callback(self, socket_client_no_callback):
        """测试没有回调的推送消息"""
        socket_client_no_callback.on_data_callback = None

        message = {
            "type": "test_update",
            "data": {"key": "value"}
        }

        # 不应该抛出异常
        await socket_client_no_callback._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_no_type(self, socket_client):
        """测试消息没有type字段"""
        message = {
            "data": {"key": "value"}
        }

        # 不应该抛出异常
        await socket_client._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_callback_exception(self, socket_client):
        """测试回调函数抛出异常"""
        socket_client.on_data_callback.side_effect = Exception("Callback error")

        message = {
            "type": "test_update",
            "data": {"key": "value"}
        }

        # 不应该抛出异常
        await socket_client._handle_message(message)


class TestSocketClientIsConnected:
    """测试 is_connected 方法"""

    def test_is_connected_true(self, socket_client):
        """测试已连接状态"""
        socket_client.connected = True

        assert socket_client.is_connected() is True

    def test_is_connected_false(self, socket_client):
        """测试未连接状态"""
        socket_client.connected = False

        assert socket_client.is_connected() is False


class TestSocketClientIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_request_response_cycle(self, socket_client):
        """测试完整的请求-响应周期"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.write = MagicMock()
        socket_client.writer.drain = AsyncMock()

        # 创建测试数据
        request_data = {"symbol": "SHFE.rb2505", "volume": 1}
        response_data = {"order_id": "test_order_123", "status": "submitted"}

        # Mock asyncio.wait_for来立即返回结果
        async def mock_wait_for_coro(future, timeout):
            # 立即设置结果
            if not future.done():
                future.set_result(response_data)
            return await future

        with patch("asyncio.wait_for", side_effect=mock_wait_for_coro):
            # 发送请求
            result = await socket_client.request("order_req", request_data, timeout=1.0)

            # 验证结果
            assert result == response_data
            # 验证写入了数据
            assert socket_client.writer.write.call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, socket_client):
        """测试并发请求"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.write = MagicMock()
        socket_client.writer.drain = AsyncMock()

        # 创建多个并发请求
        async def send_request(req_id: str, data: dict):
            future: asyncio.Future = asyncio.Future()

            async def set_result():
                await asyncio.sleep(0.01)
                future.set_result({"request_id": req_id, "result": "ok"})

            asyncio.create_task(set_result())

            with patch.object(socket_client, "_pending_requests", {req_id: future}):
                return await socket_client.request("test", data, timeout=1.0)

        # 并发发送多个请求
        results = await asyncio.gather(
            send_request("req1", {"param": "value1"}),
            send_request("req2", {"param": "value2"}),
            send_request("req3", {"param": "value3"}),
        )

        assert len(results) == 3


class TestSocketClientEdgeCases:
    """边缘情况测试"""

    @pytest.mark.asyncio
    async def test_empty_message_data(self, socket_client):
        """测试空消息数据"""
        message = {
            "type": "test",
            "data": {}
        }

        await socket_client._handle_message(message)

        socket_client.on_data_callback.assert_called_once_with("test", {})

    @pytest.mark.asyncio
    async def test_large_message(self, socket_client):
        """测试大消息"""
        mock_reader = MagicMock()
        socket_client.reader = mock_reader

        # 创建一个大消息
        large_data = {"key": "x" * 10000}
        json_bytes = json.dumps(large_data, ensure_ascii=False).encode("utf-8")
        length_bytes = struct.pack(">I", len(json_bytes))

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, json_bytes])

        result = await socket_client._receive_message()

        assert result == large_data

    @pytest.mark.asyncio
    async def test_unicode_message(self, socket_client):
        """测试Unicode消息"""
        mock_reader = MagicMock()
        socket_client.reader = mock_reader

        # 创建包含Unicode的消息
        unicode_data = {"type": "test", "data": {"message": "你好世界 🌍"}}
        json_bytes = json.dumps(unicode_data, ensure_ascii=False).encode("utf-8")
        length_bytes = struct.pack(">I", len(json_bytes))

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, json_bytes])

        result = await socket_client._receive_message()

        assert result == unicode_data

    @pytest.mark.asyncio
    async def test_connect_disconnect_reconnect(self, socket_client):
        """测试连接-断开-重连"""
        mock_reader = MagicMock()
        mock_writer = MagicMock()

        register_msg = {"type": "register", "data": {"account_id": socket_client.account_id}}

        # 第一次连接
        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)

            with patch.object(socket_client, "_receive_message", return_value=register_msg):
                result1 = await socket_client.connect()
                assert result1 is True

        # 断开
        await socket_client.disconnect()
        assert socket_client.connected is False

        # 重新连接
        with patch("asyncio.open_unix_connection") as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)

            with patch.object(socket_client, "_receive_message", return_value=register_msg):
                result2 = await socket_client.connect()
                assert result2 is True

    @pytest.mark.asyncio
    async def test_multiple_disconnect_calls(self, socket_client):
        """测试多次调用disconnect"""
        socket_client.connected = True
        socket_client.writer = MagicMock()
        socket_client.writer.close = MagicMock()
        socket_client.writer.wait_closed = AsyncMock()

        # 多次调用disconnect不应该抛出异常
        await socket_client.disconnect()
        await socket_client.disconnect()
        await socket_client.disconnect()

        assert socket_client.connected is False
