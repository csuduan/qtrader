"""
Socket服务器
"""

import asyncio
import struct
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

import simplejson as json

from src.utils.logger import get_logger

logger = get_logger(__name__)


def request(message_type: str) -> Callable:
    """
    请求-响应模式装饰器

    用于标记处理函数，自动注册到SocketServer。

    Args:
        message_type: 消息类型

    Example:
        @request("connect")
        async def handle_connect(data: dict) -> bool:
            return True
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"处理请求 [{message_type}] 时出错: {e}")
                raise

        # 保存元数据，供注册时使用
        wrapper._message_type = message_type  # type: ignore[attr-defined]
        wrapper._handler_func = func  # type: ignore[attr-defined]
        return wrapper

    return decorator


class SocketClientConnection:
    """
    客户端连接包装类

    封装单个客户端连接的读写流和状态。
    """

    def __init__(
        self, conn_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, addr: Any
    ):
        self.conn_id = conn_id
        self.reader = reader
        self.writer = writer
        self.addr = addr
        self.connected = True
        self.lock = asyncio.Lock()  # 用于发送时的线程安全

    async def close(self) -> None:
        """关闭连接"""
        self.connected = False
        try:
            if self.writer:
                self.writer.close()
                try:
                    await self.writer.wait_closed()
                except Exception:
                    pass
        except Exception:
            pass

    def is_connected(self) -> bool:
        """检查连接是否有效"""
        if not self.connected or not self.writer:
            return False
        # 检查writer是否已关闭
        if self.writer.is_closing():
            return False
        return True


class SocketServer:
    """
    Unix Domain Socket 服务器

    职责：
    1. 创建Unix Domain Socket
    2. 接受客户端连接
    3. 接收请求-响应
    4. 推送数据
    """

    def __init__(self, socket_path: str, account_id: str):
        """
        初始化Socket服务器

        Args:
            socket_path: Socket文件路径
            account_id: 账户ID
        """
        self.socket_path = socket_path
        self.account_id = account_id
        self.server: Optional[asyncio.AbstractServer] = None

        # 多连接管理：使用字典存储所有客户端连接
        self._clients: Dict[str, SocketClientConnection] = {}
        self._clients_lock = asyncio.Lock()

        self._req_handlers: Dict[str, Callable] = {}

        # 连接健康检查任务
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval = 30  # 每30秒检查一次

        logger.info(f"SocketServer 服务器初始化: {socket_path}")

    # def request(self, request_type: str):
    #     """请求处理器装饰器"""
    #     def decorator(func: Callable):
    #         @wraps(func)
    #         async def wrapper(*args, **kwargs):
    #             return await func(*args, **kwargs)

    #         # 直接在这里注册，而不是通过 handlers.register
    #         self._req_handlers[request_type] = wrapper
    #         return wrapper
    #     return decorator

    def register_handler(self, message_type: str, handler: Callable) -> None:
        """
        手动注册消息处理器

        Args:
            message_type: 消息类型 (order_req, cancel_req)
            handler: 处理函数 (data: dict) -> None
        """
        self._req_handlers[message_type] = handler
        logger.info(f"SocketServer 注册消息处理器: {message_type}")

    def register_handlers_from_instance(self, instance: object) -> None:
        """
        自动从实例中收集带 @request 装饰器的方法并注册

        通过遍历实例的所有属性，查找带有 _message_type 标记的方法。
        支持识别 _req_* 前缀的方法名。

        Args:
            instance: 包含带 @request 装饰器方法的实例
        """
        count = 0
        for attr_name in dir(instance):
            # 跳过非 _req_ 开头的私有属性
            if attr_name.startswith("_") and not attr_name.startswith("_req_"):
                continue
            attr = getattr(instance, attr_name)
            if hasattr(attr, "_message_type") and hasattr(attr, "_handler_func"):
                message_type = attr._message_type
                self._req_handlers[message_type] = attr
                count += 1
                logger.debug(f"SocketServer 注册请求处理器: {message_type} -> {attr_name}")
        logger.info(f"SocketServer 自动注册了 {count} 个请求处理器")

    async def start(self) -> None:
        """启动Socket服务器"""
        # 删除已存在的socket文件
        try:
            if Path(self.socket_path).exists():
                Path(self.socket_path).unlink()
        except (PermissionError, OSError) as e:
            logger.warning(f"[Trader-{self.account_id}] 无法删除socket文件: {e}")

        # 创建socket目录
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        # 创建Unix Domain Socket服务器
        self.server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)

        # 启动健康检查任务
        # self._health_check_task = asyncio.create_task(self._health_check_loop())

        logger.info(f"SocketServer 启动成功: {self.socket_path}")
        async with self.server:
            await self.server.serve_forever()
        logger.info(f"SocketServer 已停止: {self.socket_path}")

    async def stop(self) -> None:
        """停止Socket服务器"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info(f"[Trader-{self.account_id}] Socket服务器已停止")

        # 停止健康检查任务
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        # 关闭所有客户端连接
        async with self._clients_lock:
            for conn_id, conn in list(self._clients.items()):
                try:
                    await conn.close()
                    logger.info(f"[Trader-{self.account_id}] 已关闭客户端连接: {conn_id}")
                except Exception as e:
                    logger.warning(f"[Trader-{self.account_id}] 关闭客户端连接失败: {conn_id}, {e}")
            self._clients.clear()

        # 删除socket文件
        try:
            if Path(self.socket_path).exists():
                Path(self.socket_path).unlink()
        except (PermissionError, OSError) as e:
            logger.warning(f"[Trader-{self.account_id}] 无法删除socket文件: {e}")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """
        处理客户端连接
        Args:
            reader: 读取流
            writer: 写入流
        """
        # 生成唯一连接ID
        conn_id = str(uuid.uuid4())[:8]
        peer_name = writer.get_extra_info("peername")

        try:
            logger.info(f"[Trader-{self.account_id}] 收到新连接: {conn_id} from {peer_name}")

            # 创建连接对象
            conn = SocketClientConnection(conn_id, reader, writer, peer_name)

            # 添加到连接管理器
            async with self._clients_lock:
                self._clients[conn_id] = conn

            # 发送注册确认消息
            await self._send_message_to_connection(
                conn, "register", {"account_id": self.account_id}
            )

            # 接收并处理消息
            while conn.is_connected():
                try:
                    message = await self._receive_message_from_connection(conn)
                    if message:
                        await self._process_message(message, conn_id)
                except asyncio.IncompleteReadError:
                    logger.info(
                        f"[Trader-{self.account_id}] 连接 {conn_id} 数据读取异常，客户端已断开"
                    )
                    break
                except (ConnectionResetError, BrokenPipeError):
                    logger.info(f"[Trader-{self.account_id}] 连接 {conn_id} 被客户端重置")
                    break
                except Exception as e:
                    logger.exception(
                        f"[Trader-{self.account_id}] 处理连接 {conn_id} 消息时出错: {e}"
                    )
                    break

            logger.info(f"[Trader-{self.account_id}] 连接 {conn_id} 消息处理循环结束")

        except Exception as e:
            logger.exception(f"[Trader-{self.account_id}] 处理连接 {conn_id} 时出错: {e}")
        finally:
            # 清理连接
            await self._remove_client_connection(conn_id)
            logger.info(f"[Trader-{self.account_id}] 连接 {conn_id} 已关闭")

    async def _remove_client_connection(self, conn_id: str) -> None:
        """从连接管理器中移除并关闭连接"""
        async with self._clients_lock:
            conn = self._clients.pop(conn_id, None)
            if conn:
                try:
                    await conn.close()
                    logger.info(f"[Trader-{self.account_id}] 已从连接管理器移除连接: {conn_id}")
                except Exception as e:
                    logger.warning(f"[Trader-{self.account_id}] 关闭连接 {conn_id} 时出错: {e}")

    async def _health_check_loop(self) -> None:
        """
        连接健康检查循环

        定期检查所有连接的状态，清理已断开的连接
        """
        logger.info(f"[Trader-{self.account_id}] 连接健康检查任务已启动")

        while True:
            try:
                await asyncio.sleep(self._health_check_interval)

                # 检查所有连接
                dead_connections = []
                async with self._clients_lock:
                    for conn_id, conn in list(self._clients.items()):
                        if not conn.is_connected():
                            dead_connections.append(conn_id)

                # 清理已断开的连接
                for conn_id in dead_connections:
                    logger.info(
                        f"[Trader-{self.account_id}] 健康检查发现连接 {conn_id} 已断开，清理中..."
                    )
                    await self._remove_client_connection(conn_id)

                if dead_connections:
                    logger.info(
                        f"[Trader-{self.account_id}] 健康检查清理完成，移除 {len(dead_connections)} 个连接"
                    )

            except asyncio.CancelledError:
                logger.info(f"[Trader-{self.account_id}] 连接健康检查任务已取消")
                break
            except Exception as e:
                logger.exception(f"[Trader-{self.account_id}] 连接健康检查任务出错: {e}")

        logger.info(f"[Trader-{self.account_id}] 连接健康检查任务已停止")

    async def _receive_message_from_connection(
        self, conn: SocketClientConnection
    ) -> Optional[Dict[str, Any]]:
        """
        从指定连接接收消息

        Args:
            conn: 客户端连接对象

        Returns:
            消息字典，失败返回None
        Raises:
            asyncio.IncompleteReadError: 当连接断开时，让上层处理
        """
        # 读取4字节长度前缀
        length_bytes = await conn.reader.readexactly(4)
        length = struct.unpack("!I", length_bytes)[0]

        # 读取JSON内容
        json_bytes = await conn.reader.readexactly(length)
        message: Dict[str, Any] = json.loads(json_bytes.decode("utf-8"))
        return message

    async def _process_message(self, message: Dict[str, Any], conn_id: str) -> None:
        """
        处理接收到的消息

        Args:
            message: 消息内容
            conn_id: 连接ID
        """
        # 检查是否是请求消息（有request_id）
        request_type = message.get("type")
        request_id = message.get("request_id")
        data = message.get("data", {})

        # 如果没有 request_id，这可能是推送消息或其他类型消息，不需要响应
        if request_id is None:
            logger.debug(f"[Trader-{self.account_id}] 收到无request_id的消息，忽略: {request_type}")
            return {"status": "success"}  # type: ignore[return-value]

        try:
            result = await self._handle_request(request_type, request_id, data)  # type: ignore[arg-type]
        except ValueError as e:
            logger.warning(f"[Trader-{self.account_id}] 处理请求[{request_type}]出错: {e}")
            result = {"status": "error", "message": str(e)}
        except Exception as e:
            logger.exception(f"[Trader-{self.account_id}] 处理请求[{request_type}]时发生异常: {e}")
            result = {"status": "error", "message": f"内部错误: {str(e)}"}

        try:
            response = {
                "type": "response",
                "request_id": request_id,
                "status": result.get("status", "success"),
                "data": result.get("data", None),
                "message": result.get("message", ""),
            }
            # 发送回对应的连接
            await self._send_response_to_connection(conn_id, response)
        except Exception as e:
            logger.error(f"[Trader-{self.account_id}] 发送响应到连接 {conn_id} 失败: {e}")

    async def _send_response_to_connection(self, conn_id: str, data: Dict[str, Any]) -> None:
        """
        发送响应到指定连接

        Args:
            conn_id: 连接ID
            data: 响应数据
        """
        async with self._clients_lock:
            conn = self._clients.get(conn_id)
            if not conn or not conn.is_connected():
                logger.warning(f"[Trader-{self.account_id}] 连接 {conn_id} 未连接，无法发送响应")
                return

        try:
            json_bytes = json.dumps(data, ignore_nan=True, default=str).encode("utf-8")
        except Exception as e:
            logger.error(f"[Trader-{self.account_id}] 序列化响应时出错: {e}")
            return

        async with conn.lock:
            try:
                length = len(json_bytes)
                # 发送：4字节长度 + JSON内容
                conn.writer.write(struct.pack("!I", length))
                conn.writer.write(json_bytes)
                await conn.writer.drain()
            except Exception as e:
                logger.exception(f"[Trader-{self.account_id}] 发送响应到连接 {conn_id} 失败: {e}")
                # 发送失败，标记连接为断开并清理
                conn.connected = False
                asyncio.create_task(self._remove_client_connection(conn_id))

    async def _send_message_to_connection(
        self, conn: SocketClientConnection, message_type: str, data: Dict[str, Any]
    ) -> bool:
        """
        发送消息到指定连接

        Args:
            conn: 客户端连接对象
            message_type: 消息类型
            data: 消息数据

        Returns:
            是否发送成功
        """
        if not conn.is_connected():
            return False

        try:
            message = {"type": message_type, "account_id": self.account_id, "data": data}
            json_bytes = json.dumps(message, ignore_nan=True, default=str).encode("utf-8")
            length = len(json_bytes)

            async with conn.lock:
                conn.writer.write(struct.pack("!I", length))
                conn.writer.write(json_bytes)
                await conn.writer.drain()
            return True
        except Exception as e:
            logger.exception(f"[Trader-{self.account_id}] 发送消息到连接 {conn.conn_id} 失败: {e}")
            # 发送失败，标记连接为断开并清理
            conn.connected = False
            asyncio.create_task(self._remove_client_connection(conn.conn_id))
            return False

    async def _receive_message(self, reader: asyncio.StreamReader) -> Optional[Dict[str, Any]]:
        """
        接收消息（兼容旧代码）

        Args:
            reader: 读取流

        Returns:
            消息字典，失败返回None
        """
        # 读取4字节长度前缀
        length_bytes = await reader.readexactly(4)
        length = struct.unpack(">I", length_bytes)[0]

        # 读取JSON内容
        json_bytes = await reader.readexactly(length)
        message: Dict[str, Any] = json.loads(json_bytes.decode("utf-8"))
        return message

    async def _handle_request(
        self, request_type: str, request_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        处理请求消息（request-response模式）
        Args:
            request_type: 请求类型
            request_id: 请求ID
            data: 请求数据
        """
        # 调用注册的请求处理器
        if request_type is None:
            raise ValueError("消息中缺少 'type' 字段")
        if request_id is None:
            raise ValueError("消息中缺少 'request_id' 字段")

        if request_type == "ping":
            return {"status": "success", "data": {"status": "ok"}}

        handler = self._req_handlers.get(request_type)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(data)
            else:
                result = handler(data)
            return {"status": "success", "data": result}
        else:
            raise ValueError(f"未注册的请求类型: {request_type}")

    async def _send_response(self, data: Dict[str, Any]) -> None:
        """
        发送响应（兼容旧代码，向所有连接广播）

        Args:
            data: 响应数据
        """
        # 向所有连接发送响应
        async with self._clients_lock:
            clients = list(self._clients.values())

        for conn in clients:
            if conn.is_connected():
                await self._send_response_to_connection(conn.conn_id, data)

    async def send_message(self, message_type: str, data: Dict[str, Any]) -> bool:
        """
        发送消息到所有Manager客户端

        Args:
            message_type: 消息类型 (account, order, trade, position, tick, heartbeat)
            data: 消息数据

        Returns:
            是否至少一个客户端发送成功
        """
        async with self._clients_lock:
            clients = list(self._clients.values())

        if not clients:
            return False

        # 向所有连接发送消息
        success = False
        for conn in clients:
            if conn.is_connected():
                if await self._send_message_to_connection(conn, message_type, data):
                    success = True

        return success

    def is_connected(self) -> bool:
        """
        检查是否有Manager连接

        Returns:
            是否有至少一个连接
        """
        return any(conn.is_connected() for conn in self._clients.values())

    async def send_push(self, push_type: str, data: Dict[str, Any]) -> bool:
        """
        发送推送消息到所有Manager客户端

        Args:
            push_type: 推送类型 (account, order, trade, position, tick, alarm, heartbeat)
            data: 推送数据

        Returns:
            是否至少一个客户端发送成功
        """
        return await self.send_message(push_type, data)

    async def send_heartbeat(self) -> bool:
        """
        发送心跳到所有连接

        Returns:
            是否至少一个客户端发送成功
        """
        return await self.send_push("heartbeat", {})
