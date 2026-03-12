"""
Socket消息协议模块

提供标准化的消息封装、解包、编码、解码功能
"""

import asyncio
import struct
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

import simplejson as json

from src.utils.logger import get_logger

logger = get_logger(__name__)


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
    error: Optional[str] = None  # 错误信息

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "msg_type": self.msg_type.value,
            "request_id": self.request_id,
            "data": self.data,
            "timestamp": self.timestamp,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MessageBody":
        """从字典创建"""
        return cls(
            msg_type=MessageType(data["msg_type"]),
            request_id=data["request_id"],
            data=data["data"],
            timestamp=data["timestamp"],
            error=data.get("error"),
        )


class MessageEncoder(json.JSONEncoder):
    """自定义JSON编码器"""

    def default(self, obj):
        if isinstance(obj, bytes):
            return {"__bytes__": obj.hex()}
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def message_decode_hook(dct):
    """JSON解码钩子"""
    if "__bytes__" in dct:
        return bytes.fromhex(dct["__bytes__"])
    return dct


class MessageProtocol:
    """消息协议处理器"""

    def __init__(self):
        self.encoder = MessageEncoder()

    def encode(self, message: MessageBody) -> bytes:
        """
        编码消息

        格式: 4字节长度 + JSON报文体

        Args:
            message: 消息体

        Returns:
            编码后的字节数据
        """
        # 将消息体转换为JSON
        # json_data = self.encoder.encode(message.to_dict())
        json_data = json.dumps(message.to_dict(), ignore_nan=True, default=str)
        message_bytes = json_data.encode("utf-8")

        # 4字节长度 + 报文体
        length = len(message_bytes)
        return struct.pack("!I", length) + message_bytes

    def decode(self, data: bytes) -> Optional[MessageBody]:
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

            # 解析JSON
            json_data = data[4 : 4 + length].decode("utf-8")
            message_dict = json.loads(json_data, object_hook=message_decode_hook)

            return MessageBody.from_dict(message_dict)
        except (struct.error, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to decode message: {e}")
            return None

    async def read_message(self, reader: asyncio.StreamReader) -> Optional[MessageBody]:
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


def create_response(data: Any, request_id: str, error: Optional[str] = None) -> MessageBody:
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
