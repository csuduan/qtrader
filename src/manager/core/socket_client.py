"""
Socket客户端 (Manager端)
用于在独立模式下与Trader子进程通信
"""

import asyncio
import inspect
import json
import struct
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)
HandlerType = Callable[[str, Any], None] | Callable[[str, Any], Awaitable[None]]


class SocketClient:
    """
    Unix Domain Socket 客户端 (Manager端)

    在独立模式下，TraderProxy作为Socket客户端，
    连接到Trader子进程的Socket服务器。

    职责：
    1. 连接到Trader Socket服务器
    2. 发送查询请求（request-response模式）
    3. 接收推送消息（账户/订单/成交/持仓/tick更新）
    """

    def __init__(
        self, socket_path: str, account_id: str, on_data_callback: HandlerType | None = None
    ):
        """
        初始化Socket客户端

        Args:
            socket_path: Socket文件路径
            account_id: 账户ID
            on_data_callback: 数据回调函数 (account_id: str, data_type: str, data: dict) -> None
        """
        self.socket_path = socket_path
        self.account_id = account_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.on_data_callback: HandlerType | None = on_data_callback

        # 请求-响应相关
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._receiving_task: Optional[asyncio.Task] = None

        logger.info(f"[Manager-{account_id}] Socket客户端初始化: {socket_path}")

    async def connect(self, retry_interval: int = 3, max_retries: int = 30) -> bool:
        """
        连接到Trader

        Args:
            retry_interval: 重试间隔（秒）
            max_retries: 最大重试次数

        Returns:
            是否连接成功
        """
        for i in range(max_retries):
            try:
                self.reader, self.writer = await asyncio.open_unix_connection(self.socket_path)
                self.connected = True
                logger.info(f"[Trade Proxy-{self.account_id}] 已连接到Trader: {self.socket_path}")

                # 等待注册确认消息
                register_msg = await self._receive_message()
                if register_msg and register_msg.get("type") == "register":
                    registered_account_id = register_msg.get("data", {}).get("account_id")
                    if registered_account_id == self.account_id:
                        logger.info(f"[Trade Proxy-{self.account_id}] 注册确认成功")    
                        # 启动消息接收循环
                        self._receiving_task = asyncio.create_task(self._receiving_loop())
                        return True
                    else:
                        logger.warning(
                            f"[Trade Proxy-{self.account_id}] 注册account_id不匹配: {registered_account_id}"
                        )
                        return False

                return True

            except FileNotFoundError:
                logger.debug(
                    f"[Manager-{self.account_id}] Socket文件不存在，将在{retry_interval}秒后重试 "
                    f"({i+1}/{max_retries})"
                )
                await asyncio.sleep(retry_interval)
            except Exception as e:
                logger.error(f"[Manager-{self.account_id}] 连接Trader失败: {e}")
                await asyncio.sleep(retry_interval)

        logger.error(f"[Manager-{self.account_id}] 连接Trader失败，已达到最大重试次数")
        return False

    async def disconnect(self) -> None:
        """断开连接"""
        self.connected = False

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

        logger.info(f"[Manager-{self.account_id}] 已断开Trader连接")

    async def request(
        self, request_type: str, data: Dict[str, Any], timeout: float = 10.0
    ) -> Optional[Dict[str, Any]]:
        """
        发送请求到Trader并等待响应（request-response模式）

        所有请求都使用此方法，包括：
        - 查询请求: get_account, get_orders, get_trades, get_positions, etc.
        - 交易请求: order_req, cancel_req

        Args:
            request_type: 请求类型
            data: 请求参数
            timeout: 超时时间（秒）

        Returns:
            响应数据，失败返回None
        """
        if not self.connected or not self.writer:
            logger.warning(f"[Manager-{self.account_id}] 未连接到Trader")
            return None

        # 生成请求ID
        request_id = str(uuid.uuid4())

        # 创建Future等待响应
        future: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            # 发送请求
            message = {"type": request_type, "request_id": request_id, "data": data}

            # 序列化为JSON
            json_bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")
            length = len(json_bytes)

            # 发送：4字节长度 + JSON内容
            self.writer.write(struct.pack(">I", length))
            self.writer.write(json_bytes)
            await self.writer.drain()

            # 等待响应
            response = await asyncio.wait_for(future, timeout=timeout)
            if request_type != "ping":
                logger.info(f"[Trade Proxy-{self.account_id}] 请求成功: {request_type}")
            return response

        except asyncio.TimeoutError:
            logger.warning(f"[Manager-{self.account_id}] 请求超时: {request_type}")
            self._pending_requests.pop(request_id, None)
            return None
        except Exception as e:
            logger.exception(f"[Manager-{self.account_id}] 请求失败: {request_type}, {e}")
            self._pending_requests.pop(request_id, None)
            return None

    async def _receiving_loop(self) -> None:
        """消息接收循环"""
        while self.connected:
            try:
                message = await self._receive_message()
                if not message:
                    logger.info(f"[Manager-{self.account_id}] Trader关闭了连接")
                    break

                await self._handle_message(message)

            except asyncio.IncompleteReadError:
                logger.info(f"[Manager-{self.account_id}] Trader关闭了连接")
                break
            except Exception as e:
                logger.error(f"[Manager-{self.account_id}] 接收消息时出错: {e}")
                break

        self.connected = False

    async def _receive_message(self) -> Optional[Dict[str, Any]]:
        """
        接收消息

        消息格式：
        - 4字节长度前缀（Big Endian）
        - JSON内容

        Returns:
            消息字典，失败返回None
        """
        if self.reader is None:
            logger.error(f"[Manager-{self.account_id}] StreamReader 未初始化")
            return None

        try:
            # 读取4字节长度前缀
            length_bytes = await self.reader.readexactly(4)
            length = struct.unpack(">I", length_bytes)[0]

            # 读取JSON内容
            json_bytes = await self.reader.readexactly(length)
            message: Dict[str, Any] = json.loads(json_bytes.decode("utf-8"))  # type: ignore[no-any-return]

            return message

        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.error(f"[Manager-{self.account_id}] 接收消息失败: {e}")
            return None

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """
        处理接收到的消息

        Args:
            message: 消息内容
        """
        message_type = message.get("type")
        if message_type is None:
            logger.warning(f"[Manager-{self.account_id}] 消息中缺少 'type' 字段")
            return

        # 检查是否是响应消息
        if message_type == "response":
            # 响应消息
            request_id = message.get("request_id")
            if not request_id:
                logger.error(f"响应消息缺少request_id，{message}")
                return
            # 这是响应消息
            future = self._pending_requests.pop(request_id, None)
            if future and not future.done():
                data = message.get("data", {})
                if message.get("status") == "error":
                    future.set_exception(Exception(data.get("message", "请求失败")))
                else:
                    future.set_result(data)
            return
        else:
            # 这是推送消息
            data = message.get("data", {})
            # 调用注册的处理器
            handler = self.on_data_callback
            if handler:
                try:
                    if inspect.iscoroutinefunction(handler):
                        await handler(message_type, data)
                    else:
                        handler(message_type, data)
                except Exception as e:
                    logger.error(
                        f"[Manager-{self.account_id}] 处理消息 [{message_type}] 时出错: {e}"
                    )
            else:
                logger.warning(f"[Manager-{self.account_id}] 未注册的消息类型: {message_type}")

    def is_connected(self) -> bool:
        """
        检查是否连接到Trader

        Returns:
            是否连接
        """
        return self.connected
