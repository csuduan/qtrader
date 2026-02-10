"""
SocketServer 单元测试
测试 SocketServer 类的所有方法和功能
"""

import asyncio
import json
import struct
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import pytest

from src.trader.socket_server import SocketServer, request


# ==================== Fixtures ====================


@pytest.fixture
def socket_path(tmp_path):
    """临时socket文件路径"""
    return str(tmp_path / "test.sock")


@pytest.fixture
def account_id():
    """测试账户ID"""
    return "test_account_001"


@pytest.fixture
def socket_server(socket_path, account_id):
    """创建 SocketServer 实例"""
    return SocketServer(socket_path, account_id)


@pytest.fixture
def mock_reader():
    """模拟StreamReader"""
    return MagicMock()


@pytest.fixture
def mock_writer():
    """模拟StreamWriter"""
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


# ==================== Test Request Decorator ====================


class TestRequestDecorator:
    """测试 @request 装饰器"""

    def test_request_decorator_sync_function(self):
        """测试装饰同步函数"""
        @request("test_type")
        def handle_test(data: dict) -> str:
            return "test_result"

        assert hasattr(handle_test, "_message_type")
        assert handle_test._message_type == "test_type"
        assert hasattr(handle_test, "_handler_func")

    def test_request_decorator_async_function(self):
        """测试装饰异步函数"""
        @request("async_type")
        async def handle_async(data: dict) -> str:
            return "async_result"

        assert hasattr(handle_async, "_message_type")
        assert handle_async._message_type == "async_type"

    @pytest.mark.asyncio
    async def test_request_decorator_call_sync(self):
        """测试调用同步包装函数"""
        @request("test_type")
        def handle_test(data: dict) -> str:
            return "test_result"

        result = await handle_test({"key": "value"})
        assert result == "test_result"

    @pytest.mark.asyncio
    async def test_request_decorator_call_async(self):
        """测试调用异步包装函数"""
        @request("test_type")
        async def handle_async(data: dict) -> str:
            return "async_result"

        result = await handle_async({"key": "value"})
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_request_decorator_exception_handling(self):
        """测试装饰器异常处理"""
        @request("error_type")
        def handle_error(data: dict) -> str:
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await handle_error({})


# ==================== Test Initialization ====================


class TestSocketServerInit:
    """测试 __init__ 方法"""

    def test_init(self, socket_server, socket_path, account_id):
        """测试初始化"""
        assert socket_server.socket_path == socket_path
        assert socket_server.account_id == account_id
        assert socket_server.server is None
        assert socket_server.client_writer is None
        assert socket_server.client_connected is False
        assert socket_server._req_handlers == {}


# ==================== Test Handler Registration ====================


class TestSocketServerHandlerRegistration:
    """测试处理器注册"""

    def test_register_handler(self, socket_server):
        """测试手动注册处理器"""
        async def test_handler(data: dict) -> str:
            return "test"

        socket_server.register_handler("test_type", test_handler)

        assert "test_type" in socket_server._req_handlers
        assert socket_server._req_handlers["test_type"] == test_handler

    def test_register_handlers_from_instance(self, socket_server):
        """测试从实例自动注册处理器"""
        class TestHandlers:
            @request("req1")
            async def _req_handler1(self, data: dict) -> str:
                return "handler1"

            @request("req2")
            async def _req_handler2(self, data: dict) -> str:
                return "handler2"

            def not_a_handler(self):
                """不是处理器"""
                pass

        instance = TestHandlers()
        socket_server.register_handlers_from_instance(instance)

        assert "req1" in socket_server._req_handlers
        assert "req2" in socket_server._req_handlers

    def test_register_handlers_skips_private_methods(self, socket_server):
        """测试跳过非_req_开头的私有方法"""
        class TestHandlers:
            def _private_method(self):
                pass

            @request("public_req")
            async def _req_handler(self, data: dict) -> str:
                return "handler"

        instance = TestHandlers()
        socket_server.register_handlers_from_instance(instance)

        assert "public_req" in socket_server._req_handlers
        assert "_private_method" not in socket_server._req_handlers


# ==================== Test Start/Stop ====================


class TestSocketServerStartStop:
    """测试启动和停止"""

    @pytest.mark.asyncio
    async def test_start_creates_socket_file(self, socket_server, tmp_path):
        """测试启动创建socket文件"""
        socket_path = tmp_path / "test.sock"
        socket_server.socket_path = str(socket_path)

        with patch("asyncio.start_unix_server") as mock_start:
            mock_server = AsyncMock()
            mock_server.close = MagicMock()
            mock_start.return_value = mock_server

            await socket_server.start()

            assert socket_server.server == mock_server

    @pytest.mark.asyncio
    async def test_start_deletes_existing_socket(self, socket_server, tmp_path):
        """测试启动时删除已存在的socket文件"""
        socket_path = tmp_path / "test.sock"
        socket_path.touch()  # 创建已存在的文件
        socket_server.socket_path = str(socket_path)

        with patch("asyncio.start_unix_server") as mock_start:
            mock_server = AsyncMock()
            mock_start.return_value = mock_server

            await socket_server.start()

            # 文件应该被删除
            assert not socket_path.exists()

    @pytest.mark.asyncio
    async def test_start_socket_dir_not_exists(self, socket_server, tmp_path):
        """测试socket目录不存在时创建"""
        socket_path = tmp_path / "subdir" / "test.sock"
        socket_server.socket_path = str(socket_path)

        with patch("asyncio.start_unix_server") as mock_start:
            mock_server = AsyncMock()
            mock_start.return_value = mock_server

            await socket_server.start()

            # 目录应该被创建
            assert socket_path.parent.exists()

    @pytest.mark.asyncio
    async def test_stop(self, socket_server):
        """测试停止服务器"""
        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()
        socket_server.server = mock_server

        await socket_server.stop()

        mock_server.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_with_client_connection(self, socket_server, mock_writer):
        """测试停止时关闭客户端连接"""
        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()
        socket_server.server = mock_server
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True

        await socket_server.stop()

        mock_writer.close.assert_called_once()
        assert socket_server.client_writer is None
        assert socket_server.client_connected is False

    @pytest.mark.asyncio
    async def test_stop_deletes_socket_file(self, socket_server, tmp_path):
        """测试停止时删除socket文件"""
        socket_path = tmp_path / "test.sock"
        socket_path.touch()
        socket_server.socket_path = str(socket_path)

        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()
        socket_server.server = mock_server

        await socket_server.stop()

        assert not socket_path.exists()


# ==================== Test Client Handling ====================


class TestSocketServerClientHandling:
    """测试客户端处理"""

    @pytest.mark.asyncio
    async def test_handle_client_sends_register_message(self, socket_server, mock_writer):
        """测试处理客户端连接时发送注册消息"""
        mock_reader = MagicMock()

        # Mock _receive_message to return None and exit the loop
        async def mock_receive(reader):
            return None

        with patch.object(socket_server, "_receive_message", side_effect=mock_receive), \
             patch.object(socket_server, "send_message", new=AsyncMock()) as mock_send:
            await socket_server._handle_client(mock_reader, mock_writer)

            # Should send register message
            mock_send.assert_called_once_with("register", {"account_id": socket_server.account_id})

    @pytest.mark.asyncio
    async def test_handle_client_processes_messages(self, socket_server):
        """测试处理客户端消息"""
        # Create fresh mocks
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # Mock messages
        messages = [
            {"type": "test", "request_id": "1", "data": {}},
            {"type": "test2", "request_id": "2", "data": {}},
            None  # Exit the loop
        ]

        async def mock_receive(reader):
            if messages:
                return messages.pop(0)
            return None

        with patch.object(socket_server, "_receive_message", side_effect=mock_receive), \
             patch.object(socket_server, "_handle_message", new=AsyncMock()), \
             patch("asyncio.IncompleteReadError", Exception):
            await socket_server._handle_client(mock_reader, mock_writer)

    @pytest.mark.asyncio
    async def test_handle_client_incomplete_read_error(self, socket_server):
        """测试处理IncompleteReadError"""
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def mock_receive(reader):
            raise asyncio.IncompleteReadError(partial=b"", expected=4)

        with patch.object(socket_server, "_receive_message", side_effect=mock_receive):
            await socket_server._handle_client(mock_reader, mock_writer)

        # Should exit without exception
        assert True

    @pytest.mark.asyncio
    async def test_handle_client_exception(self, socket_server):
        """测试处理异常"""
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def mock_receive(reader):
            raise Exception("Test error")

        with patch.object(socket_server, "_receive_message", side_effect=mock_receive):
            await socket_server._handle_client(mock_reader, mock_writer)

        # Should exit without exception
        assert True

    @pytest.mark.asyncio
    async def test_handle_client_cleanup_on_exit(self, socket_server, mock_writer):
        """测试客户端退出时清理资源"""
        mock_reader = MagicMock()

        async def mock_receive(reader):
            return None

        with patch.object(socket_server, "_receive_message", side_effect=mock_receive):
            await socket_server._handle_client(mock_reader, mock_writer)

        assert socket_server.client_writer is None
        assert socket_server.client_connected is False
        mock_writer.close.assert_called_once()


# ==================== Test Message Receiving ====================


class TestSocketServerReceiveMessage:
    """测试接收消息"""

    @pytest.mark.asyncio
    async def test_receive_message_success(self, socket_server, mock_reader):
        """测试成功接收消息"""
        message_data = {"type": "test", "data": {"key": "value"}}
        json_bytes = json.dumps(message_data).encode("utf-8")
        length_bytes = struct.pack(">I", len(json_bytes))

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, json_bytes])

        result = await socket_server._receive_message(mock_reader)

        assert result == message_data

    @pytest.mark.asyncio
    async def test_receive_message_incomplete_read(self, socket_server, mock_reader):
        """测试接收不完整"""
        mock_reader.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(partial=b"", expected=4))

        result = await socket_server._receive_message(mock_reader)

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_json_error(self, socket_server, mock_reader):
        """测试JSON解析错误"""
        length_bytes = struct.pack(">I", 10)
        invalid_json = b"not valid json"

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, invalid_json])

        result = await socket_server._receive_message(mock_reader)

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_unicode(self, socket_server, mock_reader):
        """测试接收Unicode消息"""
        message_data = {"type": "test", "data": {"message": "你好世界"}}
        json_bytes = json.dumps(message_data, ensure_ascii=False).encode("utf-8")
        length_bytes = struct.pack(">I", len(json_bytes))

        mock_reader.readexactly = AsyncMock(side_effect=[length_bytes, json_bytes])

        result = await socket_server._receive_message(mock_reader)

        assert result == message_data


# ==================== Test Message Handling ====================


class TestSocketServerHandleMessage:
    """测试消息处理"""

    @pytest.mark.asyncio
    async def test_handle_message_ping(self, socket_server):
        """测试处理ping消息"""
        message = {
            "type": "ping",
            "request_id": "test_id",
            "data": {}
        }

        with patch.object(socket_server, "_send_response", new=AsyncMock()) as mock_send:
            await socket_server._handle_message(message)

            response = mock_send.call_args[0][0]
            assert response["type"] == "response"
            assert response["request_id"] == "test_id"

    @pytest.mark.asyncio
    async def test_handle_message_with_handler(self, socket_server):
        """测试处理带处理器的消息"""
        async def test_handler(data: dict) -> str:
            return "test_result"

        socket_server.register_handler("test_type", test_handler)

        message = {
            "type": "test_type",
            "request_id": "test_id",
            "data": {"key": "value"}
        }

        with patch.object(socket_server, "_send_response", new=AsyncMock()) as mock_send:
            await socket_server._handle_message(message)

            response = mock_send.call_args[0][0]
            assert response["status"] == "success"
            assert response["data"] == "test_result"

    @pytest.mark.asyncio
    async def test_handle_message_sync_handler(self, socket_server):
        """测试同步处理器"""
        def test_handler(data: dict) -> str:
            return "sync_result"

        socket_server.register_handler("test_type", test_handler)

        message = {
            "type": "test_type",
            "request_id": "test_id",
            "data": {}
        }

        with patch.object(socket_server, "_send_response", new=AsyncMock()):
            await socket_server._handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_no_type(self, socket_server):
        """测试无type字段"""
        message = {
            "request_id": "test_id",
            "data": {}
        }

        with patch.object(socket_server, "_send_response", new=AsyncMock()) as mock_send:
            await socket_server._handle_message(message)

            response = mock_send.call_args[0][0]
            assert response["status"] == "error"

    @pytest.mark.asyncio
    async def test_handle_message_no_request_id(self, socket_server):
        """测试无request_id字段"""
        message = {
            "type": "test_type",
            "data": {}
        }

        with patch.object(socket_server, "_send_response", new=AsyncMock()) as mock_send:
            await socket_server._handle_message(message)

            response = mock_send.call_args[0][0]
            assert response["status"] == "error"

    @pytest.mark.asyncio
    async def test_handle_message_unknown_type(self, socket_server):
        """测试未知消息类型"""
        message = {
            "type": "unknown_type",
            "request_id": "test_id",
            "data": {}
        }

        with patch.object(socket_server, "_send_response", new=AsyncMock()) as mock_send:
            await socket_server._handle_message(message)

            response = mock_send.call_args[0][0]
            assert response["status"] == "error"


# ==================== Test Send Response ====================


class TestSocketServerSendResponse:
    """测试发送响应"""

    @pytest.mark.asyncio
    async def test_send_response_success(self, socket_server, mock_writer):
        """测试成功发送响应"""
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True

        response = {
            "type": "response",
            "request_id": "test_id",
            "status": "success",
            "data": {"result": "ok"}
        }

        await socket_server._send_response(response)

        assert mock_writer.write.call_count == 2  # length + data
        mock_writer.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_response_not_connected(self, socket_server):
        """测试未连接时发送响应"""
        socket_server.client_writer = None
        socket_server.client_connected = False

        response = {"type": "response"}

        # Should not raise exception
        await socket_server._send_response(response)

    @pytest.mark.asyncio
    async def test_send_response_serialization_error(self, socket_server, mock_writer):
        """测试序列化错误处理"""
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True

        # Create an object that can't be serialized normally
        class Unserializable:
            pass

        response = {
            "type": "response",
            "request_id": "test_id",
            "data": Unserializable()
        }

        # Should not raise exception
        await socket_server._send_response(response)


# ==================== Test Send Message ====================


class TestSocketServerSendMessage:
    """测试发送消息"""

    @pytest.mark.asyncio
    async def test_send_message_success(self, socket_server, mock_writer):
        """测试成功发送消息"""
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True

        result = await socket_server.send_message("test_type", {"key": "value"})

        assert result is True
        assert mock_writer.write.call_count == 2  # length + data
        mock_writer.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self, socket_server):
        """测试未连接时发送消息"""
        socket_server.client_writer = None
        socket_server.client_connected = False

        result = await socket_server.send_message("test_type", {"key": "value"})

        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_exception(self, socket_server, mock_writer):
        """测试发送消息异常"""
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True
        mock_writer.write.side_effect = Exception("Write error")

        result = await socket_server.send_message("test_type", {"key": "value"})

        assert result is False


# ==================== Test Is Connected ====================


class TestSocketServerIsConnected:
    """测试连接状态检查"""

    def test_is_connected_true(self, socket_server):
        """测试已连接"""
        socket_server.client_connected = True

        result = socket_server.is_connected()

        assert result is True

    def test_is_connected_false(self, socket_server):
        """测试未连接"""
        socket_server.client_connected = False

        result = socket_server.is_connected()

        assert result is False


# ==================== Test Send Heartbeat ====================


class TestSocketServerSendHeartbeat:
    """测试发送心跳"""

    @pytest.mark.asyncio
    async def test_send_heartbeat_success(self, socket_server, mock_writer):
        """测试成功发送心跳"""
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True

        result = await socket_server.send_heartbeat()

        assert result is True

    @pytest.mark.asyncio
    async def test_send_heartbeat_not_connected(self, socket_server):
        """测试未连接时发送心跳"""
        socket_server.client_writer = None
        socket_server.client_connected = False

        result = await socket_server.send_heartbeat()

        assert result is False


# ==================== Edge Cases ====================


class TestSocketServerEdgeCases:
    """测试边界情况"""

    @pytest.mark.asyncio
    async def test_handle_request_missing_type(self, socket_server):
        """测试处理请求缺少type"""
        with pytest.raises(ValueError, match="消息中缺少 'type' 字段"):
            await socket_server._handle_request(None, "req_id", {})

    @pytest.mark.asyncio
    async def test_handle_request_missing_request_id(self, socket_server):
        """测试处理请求缺少request_id"""
        with pytest.raises(ValueError, match="消息中缺少 'request_id' 字段"):
            await socket_server._handle_request("test_type", None, {})

    @pytest.mark.asyncio
    async def test_send_message_with_nan(self, socket_server, mock_writer):
        """测试发送包含NaN的消息"""
        socket_server.client_writer = mock_writer
        socket_server.client_connected = True

        result = await socket_server.send_message("test", {"value": float('nan')})

        # Should handle NaN without error
        assert result is True

    @pytest.mark.asyncio
    async def test_start_permission_error(self, socket_server, tmp_path):
        """测试启动时权限错误"""
        socket_path = tmp_path / "test.sock"
        socket_path.touch()
        # Make file read-only
        socket_path.chmod(0o444)
        socket_server.socket_path = str(socket_path)

        with patch("asyncio.start_unix_server") as mock_start:
            mock_server = AsyncMock()
            mock_start.return_value = mock_server

            # Should not raise exception
            await socket_server.start()

    @pytest.mark.asyncio
    async def test_writer_close_exception(self, socket_server):
        """测试writer关闭异常"""
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock(side_effect=Exception("Close error"))
        socket_server.client_writer = mock_writer

        # Should not raise exception
        await socket_server.stop()
