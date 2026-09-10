"""
Socket消息协议模块

提供标准化的消息封装、解包、编码、解码功能
"""

import asyncio
import struct
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

import orjson

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 单条消息最大长度（16MB），防止对端声明超大长度导致内存耗尽
MAX_MESSAGE_SIZE = 16 * 1024 * 1024


def _json_default(obj: Any) -> str:
    """orjson 兜底序列化：Decimal 保持数字语义（与 simplejson use_decimal 一致），其余转字符串"""
    if isinstance(obj, Decimal):
        return float(obj)  # type: ignore[return-value]
    return str(obj)


class RemoteHandlerError(Exception):
    """对端处理器执行失败的 IPC 错误响应

    message 即对端回传的真实失败原因（含异常类型），由调用方决定
    是否透传给前端；与传输失败/超时（返回 None）区分。
    """


class MessageType(str, Enum):
    """消息类型枚举"""

    HEARTBEAT = "heartbeat"
    REQUEST = "request"
    RESPONSE = "response"
    PUSH = "push"
    ERROR = "error"


@dataclass
class MessageBody:
    """消息体结构"""

    msg_type: MessageType  # 消息类型
    request_id: str  # 请求ID
    data: Any  # 请求数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())  # 时间戳
    error: str | None = None  # 错误信息

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "msg_type": self.msg_type.value,
            "request_id": self.request_id,
            "data": self.data,
            "timestamp": self.timestamp,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageBody":
        """从字典创建"""
        return cls(
            msg_type=MessageType(data["msg_type"]),
            request_id=data["request_id"],
            data=data["data"],
            timestamp=data["timestamp"],
            error=data.get("error"),
        )


class MessageProtocol:
    """消息协议处理器"""

    def encode(self, message: MessageBody) -> bytes:
        """
        编码消息

        格式: 4字节长度 + JSON报文体

        Args:
            message: 消息体

        Returns:
            编码后的字节数据
        """
        # orjson.dumps 直接返回 bytes；NaN/Infinity 序列化为 null，datetime 原生支持
        message_bytes = orjson.dumps(message.to_dict(), default=_json_default)

        # 4字节长度 + 报文体
        length = len(message_bytes)
        return struct.pack("!I", length) + message_bytes

    def decode(self, data: bytes) -> MessageBody | None:
        """
        解码消息

        Args:
            data: 字节数据

        Returns:
            消息体对象，解码失败返回None
        """
        try:
            if len(data) < 4:
                return None

            # 解析长度
            length = struct.unpack("!I", data[:4])[0]

            if len(data) < 4 + length:
                return None

            # 解析JSON（orjson.loads 直接接受 bytes）
            message_dict = orjson.loads(data[4 : 4 + length])

            return MessageBody.from_dict(message_dict)
        except (struct.error, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to decode message: {e}")
            return None

    async def read_message(self, reader: asyncio.StreamReader) -> MessageBody | None:
        """
        从StreamReader读取完整消息

        Args:
            reader: asyncio StreamReader对象

        Returns:
            消息体对象，读取失败返回None
        """
        try:
            # 读取4字节的长度头
            length_data = await reader.readexactly(4)
            if not length_data:
                return None

            # 解析消息长度
            total_length = struct.unpack("!I", length_data)[0]

            if total_length > MAX_MESSAGE_SIZE:
                logger.error(
                    f"消息长度超限: {total_length} > {MAX_MESSAGE_SIZE}，判定为非法对端，断开连接"
                )
                raise ConnectionError(f"Message too large: {total_length}")

            # 读取消息体
            message_data = await reader.readexactly(total_length)

            # 解码消息
            full_data = length_data + message_data
            return self.decode(full_data)

        except (asyncio.IncompleteReadError, ConnectionError):
            # 连接已关闭
            return None
        except Exception as e:
            logger.error(f"Error reading message: {e}")
            return None


# 便捷函数
def create_request(data: Any, request_id: str) -> MessageBody:
    """创建请求消息"""
    return MessageBody(msg_type=MessageType.REQUEST, request_id=request_id, data=data)


def create_response(data: Any, request_id: str, error: str | None = None) -> MessageBody:
    """创建响应消息"""
    return MessageBody(msg_type=MessageType.RESPONSE, request_id=request_id, data=data, error=error)


def create_heartbeat() -> MessageBody:
    """创建心跳消息"""
    return MessageBody(msg_type=MessageType.HEARTBEAT, request_id="", data=None)


def create_push(push_type: str, data: Any, request_id: str = "") -> MessageBody:
    """创建推送消息"""
    return MessageBody(
        msg_type=MessageType.PUSH,
        request_id=request_id or str(uuid.uuid4()),
        data={"type": push_type, "data": data},
    )


def create_error(error: str, request_id: str = "") -> MessageBody:
    """创建错误消息"""
    return MessageBody(msg_type=MessageType.ERROR, request_id=request_id, data=None, error=error)


def create_data_notification(
    data_type: str,
    account_id: str,
    record_id: str,
    timestamp: str | None = None,
    extra_data: (dict[str, Any]) | None = None,
) -> MessageBody:
    """
    创建数据变更轻量级通知

    Trader 写入 PG 后发送此通知给 Manager，Manager 收到后从 PG 查询完整数据。

    Args:
        data_type: 数据类型 (account, order, trade, position, rotation_instruction, account_status)
        account_id: 账户ID
        record_id: 记录ID (如 order_id, trade_id, symbol 等)
        timestamp: 时间戳，默认当前时间
        extra_data: 额外数据字典（如网关连接状态 md_connected/td_connected）

    Returns:
        轻量级通知消息体
    """
    data = {
        "data_type": data_type,
        "account_id": account_id,
        "record_id": record_id,
        "timestamp": timestamp or datetime.now().isoformat(),
    }
    if extra_data:
        data.update(extra_data)

    return MessageBody(
        msg_type=MessageType.PUSH,
        request_id=str(uuid.uuid4()),
        data={
            "type": "data_notification",
            "data": data,
        },
    )
