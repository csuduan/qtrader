"""
Socket客户端 - V2版本，使用标准协议

基于参考实现优化，包含：
- 完善的自动重连机制（带退避策略）
- 心跳检测和健康检查
- 优化的请求-响应模式
- 完善的连接状态管理
"""

import asyncio
import inspect
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from src.utils.logger import get_logger
from src.utils.ipc.protocol import (
    MessageType, MessageBody, MessageProtocol,
    create_request, create_response, create_heartbeat
)
from src.utils.ipc.utils import (
    BackoffStrategy, HealthChecker, generate_request_id
)

logger = get_logger(__name__)

HandlerType = Callable[[str, Any], None] | Callable[[str, Any], Awaitable[None]]
PushHandlerType = Callable[[str, Dict], Any] | Callable[[str, Dict], Awaitable[Any]]


class SocketClient:
    """
    Socket客户端 V2

    基于标准协议的高性能Socket客户端，特性：
    - 自动重连机制（带退避策略）
    - 心跳检测
    - 请求-响应模式
    - 推送消息处理
    - 完善的错误处理

    Attributes:
        socket_path: Socket文件路径
        account_id: 账户ID
    """

    def __init__(
        self,
        socket_path: str,
        account_id: str,
        on_data_callback: Optional[HandlerType] = None,
        auto_reconnect: bool = True,
        reconnect_interval: float = 3.0,
        max_reconnect_attempts: int = 1000,  # 0表示无限重试
        heartbeat_interval: float = 15.0,  # 默认15秒心跳间隔
        request_timeout: float = 10.0
    ):
        """
        初始化Socket客户端

        Args:
            socket_path: Socket文件路径
            account_id: 账户ID
            on_data_callback: 数据回调函数
            auto_reconnect: 是否自动重连
            reconnect_interval: 重连基础间隔（秒）
            max_reconnect_attempts: 最大重连次数，0表示无限
            heartbeat_interval: 心跳间隔（秒）
            request_timeout: 请求超时时间（秒）
        """
        self.socket_path = socket_path
        self.account_id = account_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.on_data_callback: Optional[HandlerType] = on_data_callback
        self.protocol = MessageProtocol()

        # 请求-响应相关
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._receiving_task: Optional[asyncio.Task] = None
        self._request_timeout = request_timeout

        # 重连相关
        self._auto_reconnect = auto_reconnect
        self._reconnect_interval = reconnect_interval
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_task: Optional[asyncio.Task] = None
        self._backoff = BackoffStrategy(
            initial_delay=reconnect_interval,
            max_delay=60.0,
            multiplier=1.5
        )

        # 心跳相关
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._health_checker = HealthChecker(
            interval=heartbeat_interval,
            timeout=5.0
        )

        # 推送处理器
        self._push_handlers: Dict[str, PushHandlerType] = {}

        # 连接断开回调
        self._on_disconnect_callback: Optional[Callable[[], Any]] = None
        self._on_connect_callback: Optional[Callable[[], Any]] = None

        logger.info(f"SocketClient V2 初始化: {socket_path}")

    def on_push(self, push_type: str) -> Callable:
        """
        推送处理器装饰器

        Example:
            @client.on_push("notification")
            async def handle_notification(data: dict):
                print(f"Received: {data}")
        """
        def decorator(func: PushHandlerType) -> PushHandlerType:
            self._push_handlers[push_type] = func
            return func
        return decorator

    async def connect(self, retry_interval: float = 3.0, max_retries: int = 30) -> bool:
        """
        连接到服务器

        Args:
            retry_interval: 重试间隔（秒）
            max_retries: 最大重试次数

        Returns:
            是否连接成功
        """
        for i in range(max_retries):
            try:
                self.reader, self.writer = await asyncio.open_unix_connection(
                    self.socket_path
                )
                self.connected = True
                self._backoff.reset()

                # 启动接收循环
                self._receiving_task = asyncio.create_task(self._receiving_loop())

                # 启动心跳任务
                if self._heartbeat_interval > 0:
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # 启动自动重连任务
                if self._auto_reconnect and (self._reconnect_task is None or self._reconnect_task.done()):
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop())

                logger.info(f"SocketClient V2 已连接: {self.socket_path}")

                # 调用连接回调
                if self._on_connect_callback:
                    try:
                        if asyncio.iscoroutinefunction(self._on_connect_callback):
                            await self._on_connect_callback()
                        else:
                            self._on_connect_callback()
                    except Exception as e:
                        logger.error(f"执行连接回调时出错: {e}")

                return True

            except FileNotFoundError:
                logger.debug(
                    f"Socket文件不存在，将在{retry_interval}秒后重试 "
                    f"({i+1}/{max_retries})"
                )
                await asyncio.sleep(retry_interval)
            except Exception as e:
                logger.error(f"连接服务器失败: {e}")
                await asyncio.sleep(retry_interval)

        logger.error(f"连接服务器失败，已达到最大重试次数")
        return False

    async def disconnect(self) -> None:
        """断开连接"""
        self.connected = False

        # 停止心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # 停止接收任务
        if self._receiving_task:
            self._receiving_task.cancel()
            try:
                await self._receiving_task
            except asyncio.CancelledError:
                pass
            self._receiving_task = None

        # 取消所有等待的请求
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(ConnectionError("连接已断开"))
        self._pending_requests.clear()

        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

        logger.info(f"SocketClient V2 已断开")

    async def request(
        self,
        request_type: str,
        data: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        发送请求并等待响应

        Args:
            request_type: 请求类型
            data: 请求数据
            timeout: 超时时间（秒），None则使用默认值

        Returns:
            响应数据，失败返回None
        """
        if not self.connected or not self.writer:
            logger.warning(f"未连接到服务器")
            return None

        request_id = str(uuid.uuid4())
        future: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            logger.info(f"开始请求: {request_type} {request_id}")
            message = create_request(
                data={"type": request_type, "data": data},
                request_id=request_id
            )

            data_bytes = self.protocol.encode(message)
            self.writer.write(data_bytes)
            await self.writer.drain()

            use_timeout = timeout if timeout is not None else self._request_timeout
            response_data = await asyncio.wait_for(future, timeout=use_timeout)
            logger.info(f"收到响应: {request_type} {request_id}")
            return response_data

        except asyncio.TimeoutError:
            logger.warning(f"请求超时: {request_type}")
            self._pending_requests.pop(request_id, None)
            return None
        except Exception as e:
            logger.exception(f"请求失败: {request_type}, {e}")
            self._pending_requests.pop(request_id, None)
            return None

    async def _receiving_loop(self) -> None:
        """接收消息循环"""
        while self.connected:
            try:
                message = await self.protocol.read_message(self.reader)
                if not message:
                    logger.info("服务器关闭了连接")
                    break

                await self._handle_message(message)

            except asyncio.IncompleteReadError:
                logger.info("服务器关闭了连接")
                break
            except ConnectionResetError:
                logger.warning("连接被重置")
                break
            except ConnectionAbortedError:
                logger.warning("连接被中止")
                break
            except Exception as e:
                logger.error(f"接收消息时出错: {e}")
                break

        # 连接断开
        was_connected = self.connected
        self.connected = False

        if was_connected:
            asyncio.create_task(self._notify_disconnection())

    async def _handle_message(self, message: MessageBody) -> None:
        """处理消息"""
        if message.msg_type == MessageType.RESPONSE:
            request_id = message.request_id
            if not request_id:
                # 没有request_id的响应可能是服务器主动推送的（如注册确认）
                logger.debug(f"收到无request_id的响应消息（可能是服务器主动推送）: {message.data}")
                return

            future = self._pending_requests.pop(request_id, None)
            if future and not future.done():
                if message.error:
                    future.set_exception(Exception(message.error))
                else:
                    future.set_result(message.data)
            return

        elif message.msg_type == MessageType.PUSH:
            # 处理推送消息
            push_data = message.data if isinstance(message.data, dict) else {}
            push_type = push_data.get("type", "unknown")
            data = push_data.get("data", {})

            # 调用专用推送处理器
            handler = self._push_handlers.get(push_type)
            if handler:
                try:
                    if inspect.iscoroutinefunction(handler):
                        await handler(push_type, data)
                    else:
                        handler(push_type, data)
                except Exception as e:
                    logger.error(f"处理推送消息时出错: {e}")
            # 调用通用回调
            elif self.on_data_callback:
                try:
                    if inspect.iscoroutinefunction(self.on_data_callback):
                        await self.on_data_callback(push_type, data)
                    else:
                        self.on_data_callback(push_type, data)
                except Exception as e:
                    logger.error(f"处理消息时出错: {e}")
            else:
                logger.debug(f"收到推送消息但未处理: {push_type}")

        elif message.msg_type == MessageType.HEARTBEAT:
            # 收到心跳响应，无需处理
            pass

    async def _reconnect_loop(self) -> None:
        """自动重连循环"""
        attempt = 0

        while self._auto_reconnect:
            if self.connected:
                # 连接正常，等待一段时间后再次检查
                await asyncio.sleep(1)
                continue

            # 检查是否达到最大重连次数
            if self._max_reconnect_attempts > 0 and attempt >= self._max_reconnect_attempts:
                logger.error(
                    f"重连失败，已达到最大重连次数 ({self._max_reconnect_attempts})"
                )
                break

            attempt += 1
            delay = self._backoff.get_delay()
            logger.info(f"尝试重新连接... ({attempt}/{self._max_reconnect_attempts if self._max_reconnect_attempts > 0 else '∞'}), 等待 {delay:.1f}s")
            await asyncio.sleep(delay)

            try:
                success = await self.connect(
                    retry_interval=self._reconnect_interval,
                    max_retries=1
                )

                if success:
                    logger.info("重连成功")
                    attempt = 0
                    self._backoff.reset()
                else:
                    logger.warning("重连失败，将在下次重试")
            except Exception as e:
                logger.error(f"重连时出错: {e}")

    async def _heartbeat_loop(self) -> None:
        """心跳发送循环"""
        while self.connected:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if not self.connected:
                    break

                # 发送心跳
                success = await self._send_heartbeat()
                if not success:
                    logger.warning("心跳发送失败")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"心跳循环出错: {e}")

    async def _send_heartbeat(self) -> bool:
        """发送心跳包"""
        if not self.connected or not self.writer:
            return False

        try:
            message = create_heartbeat()
            data = self.protocol.encode(message)
            self.writer.write(data)
            await self.writer.drain()
            return True
        except Exception as e:
            logger.debug(f"发送心跳失败: {e}")
            return False

    async def _notify_disconnection(self) -> None:
        """通知连接断开"""
        if self._on_disconnect_callback:
            try:
                if asyncio.iscoroutinefunction(self._on_disconnect_callback):
                    await self._on_disconnect_callback()
                else:
                    self._on_disconnect_callback()
            except Exception as e:
                logger.error(f"执行断开回调时出错: {e}")

    def set_disconnect_callback(self, callback: Callable[[], Any]) -> None:
        """设置连接断开回调"""
        self._on_disconnect_callback = callback

    def set_connect_callback(self, callback: Callable[[], Any]) -> None:
        """设置连接成功回调"""
        self._on_connect_callback = callback

    def start_auto_reconnect(self) -> None:
        """启动自动重连"""
        if self._reconnect_task is None or self._reconnect_task.done():
            self._auto_reconnect = True
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())
            logger.info("已启动自动重连")

    def stop_auto_reconnect(self) -> None:
        """停止自动重连"""
        self._auto_reconnect = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            logger.info("已停止自动重连")

    async def health_check(self) -> bool:
        """执行健康检查"""
        return await self._health_checker.check(self._send_heartbeat)

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.connected and self.writer is not None and not self.writer.is_closing()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "connected": self.connected,
            "pending_requests": len(self._pending_requests),
            "auto_reconnect": self._auto_reconnect,
            "heartbeat_interval": self._heartbeat_interval,
            "reconnect_attempts": self._max_reconnect_attempts
        }
