"""
Socket服务器 (Trader端)
用于在独立模式下与Manager通信
"""

import asyncio
import struct
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from functools import wraps


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
        wrapper._message_type = message_type
        wrapper._handler_func = func
        return wrapper

    return decorator

class SocketServer:
    """
    Unix Domain Socket 服务器 (Trader端)

    在独立模式下，Trader子进程作为Socket服务器，
    等待Manager（StandaloneTraderProxy）连接。

    职责：
    1. 创建Unix Domain Socket
    2. 接受Manager连接
    3. 接收订单/撤单请求
    4. 推送账户/订单/成交/持仓/tick数据
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
        self.client_writer: Optional[asyncio.StreamWriter] = None
        self.client_connected = False
        self._req_handlers: Dict[str, Callable] = {}
        logger.info(f"[Trader-{account_id}] Socket服务器初始化: {socket_path}")


    def register_handler(self, message_type: str, handler: Callable) -> None:
        """
        手动注册消息处理器

        Args:
            message_type: 消息类型 (order_req, cancel_req)
            handler: 处理函数 (data: dict) -> None
        """
        self._req_handlers[message_type] = handler
        logger.info(f"[Trader-{self.account_id}] 注册消息处理器: {message_type}")

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
                logger.debug(f"[Trader-{self.account_id}] 注册请求处理器: {message_type} -> {attr_name}")
        logger.info(f"[Trader-{self.account_id}] 自动注册了 {count} 个请求处理器")

    

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

        logger.info(f"[Trader-{self.account_id}] Socket服务器启动成功: {self.socket_path}")

    async def stop(self) -> None:
        """停止Socket服务器"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info(f"[Trader-{self.account_id}] Socket服务器已停止")

        # 关闭客户端连接
        if self.client_writer:
            self.client_writer.close()
            try:
                await self.client_writer.wait_closed()
            except Exception:
                pass
            self.client_writer = None
            self.client_connected = False

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
        处理Manager连接

        Args:
            reader: 读取流
            writer: 写入流
        """
        try:
            logger.info(f"[Trader-{self.account_id}] 收到新连接")
            self.client_writer = writer
            self.client_connected = True

            # 发送注册确认消息
            await self.send_message("register", {"account_id": self.account_id})

            # 接收并处理消息
            while True:
                try:
                    message = await self._receive_message(reader)
                    if not message:
                        logger.info(f"[Trader-{self.account_id}] 未收到有效消息")
                        break

                    await self._handle_message(message)

                except asyncio.IncompleteReadError:
                    logger.info(f"[Trader-{self.account_id}] 连接已断开")
                    break
                except Exception as e:
                    logger.exception(f"[Trader-{self.account_id}] 处理消息时出错: {e}")
                    break

        finally:
            # 清理连接
            self.client_writer = None
            self.client_connected = False
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"[Trader-{self.account_id}] 连接已关闭")

    async def _receive_message(self, reader: asyncio.StreamReader) -> Optional[Dict[str, Any]]:
        """
        接收消息

        消息格式：
        - 4字节长度前缀（Big Endian）
        - JSON内容

        Args:
            reader: 读取流

        Returns:
            消息字典，失败返回None
        """
        try:
            # 读取4字节长度前缀
            length_bytes = await reader.readexactly(4)
            length = struct.unpack(">I", length_bytes)[0]

            # 读取JSON内容
            json_bytes = await reader.readexactly(length)
            message: Dict[str, Any] = json.loads(json_bytes.decode("utf-8"))  # type: ignore[no-any-return]

            return message

        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.error(f"[Trader-{self.account_id}] 接收消息失败: {e}")
            return None

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """
        处理接收到的消息

        Args:
            message: 消息内容
        """
        # 检查是否是请求消息（有request_id）
        request_type = message.get("type")
        request_id = message.get("request_id")
        data = message.get("data", {})   
        try:
            result = await self._handle_request(request_type,request_id,data)
        except ValueError as e:
            logger.error(f"[Trader-{self.account_id}] 处理请求[{request_type}]出错: {e}")
            result = {"status": "error", "message": str(e)}

        response = {
                "type": "response",
                "request_id": request_id,
                "status": result.get("status", "success"),
                "data": result.get("data", None),
                "message": result.get("message", ""),
        }
        await self._send_response(response)             
        

    async def _handle_request(self, request_type:str,request_id:str,data:Dict[str, Any]) -> Dict[str, Any]:
        """
        处理请求消息（request-response模式）
        Args:
            message: 请求消息字典
        """
        # 调用注册的请求处理器
        if request_type is None:
            raise ValueError("消息中缺少 'type' 字段")
        if request_id is None:
            raise ValueError("消息中缺少 'request_id' 字段")

        if request_type == "ping":
            return  {"status": "success","data":{"status":"ok"}}
            
        handler = self._req_handlers.get(request_type)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(data)
            else:
                result = handler(data)
            return {"status": "success", "data": result}
        else:
            raise ValueError(f"未注册的请求类型: {request_type}")
        


    async def _send_response(self, data: Dict[str, Any]
    ) -> None:
        """
        发送响应

        Args:
            msg: 响应消息字典
        """
        if not self.client_connected or not self.client_writer:
            logger.warning(f"[Trader-{self.account_id}] Manager未连接，无法发送响应")
            return

        try:
            json_bytes = json.dumps(data, ignore_nan=True, default=str).encode("utf-8")
        except Exception as e:
            logger.error(f"[Trader-{self.account_id}] 序列化响应 [{data!r}] 时出错: {e}")
            fail_response = {
                "type": "response",
                "request_id": data.get("request_id", ""),
                "status": "error",
                "message": f"处理响应异常{e}"
            }
            json_bytes = json.dumps(fail_response, ignore_nan=True, default=str).encode("utf-8")

        try:
            length = len(json_bytes)
            # 发送：4字节长度 + JSON内容
            self.client_writer.write(struct.pack(">I", length))
            self.client_writer.write(json_bytes)
            await self.client_writer.drain()
        except Exception as e:
            logger.exception(f"[Trader-{self.account_id}] 发送响应失败: {e}")
            self.client_writer = None

    
    async def send_message(self, message_type: str, data: Dict[str, Any]) -> bool:
        """
        发送消息到Manager

        Args:
            message_type: 消息类型 (account, order, trade, position, tick, heartbeat)
            data: 消息数据

        Returns:
            是否发送成功
        """
        if not self.client_connected or not self.client_writer:
            return False

        try:
            message = {"type": message_type, "account_id": self.account_id, "data": data}
            # 序列化为JSON
            json_bytes = json.dumps(message, ignore_nan=True, default=str).encode("utf-8")
            length = len(json_bytes)

            # 发送：4字节长度 + JSON内容
            self.client_writer.write(struct.pack(">I", length))
            self.client_writer.write(json_bytes)
            await self.client_writer.drain()
            return True

        except Exception as e:
            logger.exception(f"[Trader-{self.account_id}] 发送消息失败:{message_type} {e}")
            self.client_writer = None
            return False

    def is_connected(self) -> bool:
        """
        检查Manager是否连接

        Returns:
            是否连接
        """
        return self.client_connected

    async def send_heartbeat(self) -> bool:
        """
        发送心跳

        Returns:
            是否发送成功
        """
        return await self.send_message("heartbeat", {})
