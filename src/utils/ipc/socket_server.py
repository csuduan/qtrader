"""
Socket服务器 - V2版本，使用标准协议

基于参考实现优化，包含：
- 完善的消息协议处理
- 退避重连策略
- 健康检查机制
- 请求处理器注册表
"""

import asyncio
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from src.utils.ipc.protocol import (
    MessageBody,
    MessageProtocol,
    MessageType,
    create_error,
    create_heartbeat,
    create_push,
    create_request,
    create_response,
)
from src.utils.ipc.utils import (
    BackoffStrategy,
    HealthChecker,
    RequestHandlerRegistry,
    generate_request_id,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def request(message_type: str) -> Callable:
    """
    请求处理器装饰器

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
                logger.exception(f"处理请求 [{message_type}] 时出错: {e}")
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
        self.protocol = MessageProtocol()
        self.lock = asyncio.Lock()  # 用于发送时的线程安全
        self._created_at = asyncio.get_event_loop().time()
        self._last_heartbeat_time = asyncio.get_event_loop().time()  # 上次心跳时间

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
        if self.writer.is_closing():
            return False
        return True

    def get_uptime(self) -> float:
        """获取连接存活时间（秒）"""
        return asyncio.get_event_loop().time() - self._created_at

    def update_heartbeat(self) -> None:
        """更新心跳时间"""
        self._last_heartbeat_time = asyncio.get_event_loop().time()

    def get_time_since_last_heartbeat(self) -> float:
        """获取距离上次心跳的时间（秒）"""
        return asyncio.get_event_loop().time() - self._last_heartbeat_time

    async def send_message(self, message: MessageBody) -> bool:
        """
        发送消息

        Args:
            message: 消息体

        Returns:
            是否发送成功
        """
        if not self.is_connected():
            return False

        try:
            data = self.protocol.encode(message)
            async with self.lock:
                self.writer.write(data)
                await self.writer.drain()
            return True
        except Exception as e:
            logger.exception(f"发送消息失败: {e}")
            self.connected = False
            return False

    async def receive_message(self) -> Optional[MessageBody]:
        """
        接收消息

        Returns:
            消息体，失败返回None
        """
        if not self.is_connected():
            return None

        try:
            return await self.protocol.read_message(self.reader)
        except Exception as e:
            logger.debug(f"接收消息失败: {e}")
            self.connected = False
            return None


class SocketServer:
    """
    Socket服务器 V2

    基于标准协议的高性能Socket服务器，特性：
    - 支持Unix Domain Socket
    - 请求-响应模式
    - 推送模式
    - 心跳检测
    - 自动重连退避策略
    - 完善的错误处理

    Attributes:
        socket_path: Socket文件路径
        account_id: 账户ID
    """

    def __init__(
        self,
        socket_path: str,
        account_id: str,
        enable_health_check: bool = True,
        health_check_interval: float = 30.0,
    ):
        self.socket_path = socket_path
        self.account_id = account_id
        self.server: Optional[asyncio.Server] = None
        self._clients: Dict[str, SocketClientConnection] = {}
        self._clients_lock = asyncio.Lock()
        self._req_handlers: Dict[str, Callable] = {}
        self._running = False

        # 健康检查
        self._enable_health_check = enable_health_check
        self._health_check_interval = health_check_interval
        self._health_check_task: Optional[asyncio.Task] = None

        # 统计信息
        self._stats = {
            "total_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "errors": 0,
        }

        logger.info(f"SocketServer V2 初始化: {socket_path}")

    def register_handler(self, message_type: str, handler: Callable) -> None:
        """
        手动注册消息处理器

        Args:
            message_type: 消息类型 (order_req, cancel_req)
            handler: 处理函数 (data: dict) -> Any
        """
        self._req_handlers[message_type] = handler
        logger.info(f"SocketServer 注册处理器: {message_type}")

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
                logger.debug(f"注册请求处理器: {message_type} -> {attr_name}")
        logger.info(f"SocketServer 自动注册了 {count} 个处理器")

    async def start(self) -> None:
        """启动Socket服务器"""
        self._running = True

        # 清理已存在的socket文件
        try:
            if Path(self.socket_path).exists():
                Path(self.socket_path).unlink()
        except (PermissionError, OSError) as e:
            logger.warning(f"无法删除socket文件: {e}")

        # 创建socket目录
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        # 创建Unix Domain Socket服务器
        self.server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)

        # 启动健康检查任务
        if self._enable_health_check:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

        logger.info(f"SocketServer V2 启动成功: {self.socket_path}")
        async with self.server:
            await self.server.serve_forever()

    async def stop(self) -> None:
        """停止Socket服务器"""
        self._running = False

        # 停止健康检查任务
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        # 关闭服务器
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info(f"SocketServer V2 已停止")

        # 关闭所有客户端连接
        async with self._clients_lock:
            for conn_id, conn in list(self._clients.items()):
                try:
                    await conn.close()
                except Exception as e:
                    logger.warning(f"关闭连接失败: {conn_id}, {e}")
            self._clients.clear()

        # 删除socket文件
        try:
            if Path(self.socket_path).exists():
                Path(self.socket_path).unlink()
        except (PermissionError, OSError) as e:
            logger.warning(f"无法删除socket文件: {e}")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """处理客户端连接"""
        conn_id = str(uuid.uuid4())[:8]
        peer_name = writer.get_extra_info("peername")

        try:
            logger.info(f"收到新连接: {conn_id} from {peer_name}")

            conn = SocketClientConnection(conn_id, reader, writer, peer_name)

            async with self._clients_lock:
                self._clients[conn_id] = conn
                self._stats["total_connections"] += 1

            # 发送注册确认
            await conn.send_message(
                create_response({"account_id": self.account_id, "conn_id": conn_id}, "")
            )

            # 消息处理循环
            while conn.is_connected() and self._running:
                try:
                    message = await conn.receive_message()
                    if message is None:
                        break

                    self._stats["messages_received"] += 1
                    await self._process_message(conn, message)
                except Exception as e:
                    logger.exception(f"连接[{conn_id}] 处理消息时出错: {e}")
                    self._stats["errors"] += 1

            logger.info(f"连接[{conn_id}] 消息处理循环结束，连接状态：{conn.is_connected()}")

        except Exception as e:
            logger.exception(f"连接[{conn_id}] 处理异常: {e}")
            self._stats["errors"] += 1
        finally:
            await self._remove_client_connection(conn_id)
            logger.info(f"连接[{conn_id}] 已关闭")

    async def _process_message(self, conn: SocketClientConnection, message: MessageBody) -> None:
        """处理消息"""
        try:
            conn_id = conn.conn_id
            if message.msg_type == MessageType.HEARTBEAT:
                # 心跳消息，更新心跳时间并回复心跳
                conn.update_heartbeat()
                await conn.send_message(create_heartbeat())
                logger.debug(f"连接[{conn_id}] 收到并回复心跳")
                return

            if message.msg_type == MessageType.REQUEST:
                # 请求消息，调用处理器
                request_data = message.data if isinstance(message.data, dict) else {}
                request_type = request_data.get("type")
                request_id = message.request_id
                logger.info(
                    f"连接[{conn_id}] 收到请求: {request_type} {request_id} from {conn.conn_id}"
                )
                handler = self._req_handlers.get(request_type) if request_type else None
                if handler:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            result = await handler(request_data.get("data", {}))
                        else:
                            result = handler(request_data.get("data", {}))
                        # 发送响应
                        if await conn.send_message(create_response(result, request_id)):
                            self._stats["messages_sent"] += 1
                        logger.info(f"连接[{conn_id}] 响应请求: {request_type} {request_id}")
                    except Exception as e:
                        logger.exception(
                            f"连接[{conn_id}] 处理请求:{request_type} {request_id}时出错: {e}"
                        )
                        if await conn.send_message(create_response(None, request_id, error=str(e))):
                            self._stats["messages_sent"] += 1
                else:
                    logger.warning(f"连接[{conn_id}] 未找到请求处理器: {request_type} {request_id}")
                    if await conn.send_message(
                        create_response(None, message.request_id, error="Unknown request type")
                    ):
                        self._stats["messages_sent"] += 1

            elif message.msg_type == MessageType.PUSH:
                # 推送消息，暂不支持处理
                logger.debug(f"连接[{conn_id}] 收到推送消息，暂不支持处理: {message}")

        except Exception as e:
            logger.exception(f"连接[{conn_id}] 处理消息时出错: {e}")
            self._stats["errors"] += 1

    async def _remove_client_connection(self, conn_id: str) -> None:
        """移除客户端连接"""
        async with self._clients_lock:
            conn = self._clients.pop(conn_id, None)
            if conn:
                try:
                    await conn.close()
                except Exception as e:
                    logger.warning(f"关闭连接 {conn_id} 时出错: {e}")

    async def _health_check_loop(self) -> None:
        """健康检查循环

        客户端每15秒发送一次心跳，服务端检测4个心跳周期（60秒）内是否收到心跳。
        如果超过60秒未收到心跳，则断开该客户端连接。
        """
        HEARTBEAT_INTERVAL = 15.0  # 客户端心跳间隔（秒）
        MAX_MISSED_HEARTBEATS = 4  # 最大允许丢失的心跳次数
        CHECK_INTERVAL = 5.0  # 健康检查间隔（秒）

        logger.info(
            f"健康检查任务已启动（心跳间隔: {HEARTBEAT_INTERVAL}s, 超时: {HEARTBEAT_INTERVAL * MAX_MISSED_HEARTBEATS}s）"
        )

        while self._running:
            try:
                await asyncio.sleep(CHECK_INTERVAL)
                if not self._running:
                    break

                # 检查所有连接的心跳状态
                dead_connections: List[str] = []
                current_time = asyncio.get_event_loop().time()

                async with self._clients_lock:
                    for conn_id, conn in list(self._clients.items()):
                        if not conn.is_connected():
                            dead_connections.append(conn_id)
                            continue

                        # 检查心跳超时
                        time_since_last_heartbeat = conn.get_time_since_last_heartbeat()
                        timeout_threshold = HEARTBEAT_INTERVAL * MAX_MISSED_HEARTBEATS

                        if time_since_last_heartbeat > timeout_threshold:
                            logger.warning(
                                f"连接 {conn_id} 心跳超时 "
                                f"（上次心跳: {time_since_last_heartbeat:.1f}s 前，"
                                f"阈值: {timeout_threshold:.1f}s），将断开连接"
                            )
                            dead_connections.append(conn_id)

                # 断开超时的连接
                for conn_id in dead_connections:
                    await self._remove_client_connection(conn_id)

                if dead_connections:
                    logger.info(f"健康检查清理完成，移除 {len(dead_connections)} 个连接")

            except asyncio.CancelledError:
                logger.info("健康检查任务已取消")
                break
            except Exception as e:
                logger.exception(f"健康检查任务出错: {e}")

        logger.info("健康检查任务已停止")

    async def send_message(self, message: MessageBody) -> bool:
        """
        发送消息到所有客户端

        Args:
            message: 消息体

        Returns:
            是否至少一个客户端发送成功
        """
        async with self._clients_lock:
            clients = list(self._clients.values())

        if not clients:
            return False

        success = False
        for conn in clients:
            if conn.is_connected():
                if await conn.send_message(message):
                    success = True
                    self._stats["messages_sent"] += 1

        return success

    async def send_push(self, push_type: str, data: Any) -> bool:
        """
        发送推送消息到所有客户端

        Args:
            push_type: 推送类型
            data: 推送数据

        Returns:
            是否至少一个客户端发送成功
        """
        return await self.send_message(create_push(push_type, data))

    def is_connected(self) -> bool:
        """
        检查是否有客户端连接

        Returns:
            是否有至少一个连接
        """
        return any(conn.is_connected() for conn in self._clients.values())

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return sum(1 for conn in self._clients.values() if conn.is_connected())

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "active_connections": self.get_connection_count(),
            "total_clients": len(self._clients),
        }

    async def send_heartbeat(self) -> bool:
        """
        发送心跳到所有客户端

        Returns:
            是否至少一个客户端发送成功
        """
        return await self.send_message(create_heartbeat())
