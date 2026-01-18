"""
WebSocket管理模块
"""
import asyncio
import json
from datetime import datetime
from typing import Set

from fastapi import WebSocket

from src.utils.logger import get_logger

logger = get_logger(__name__)


class WebSocketManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """接受WebSocket连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket连接已建立，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """断开WebSocket连接"""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        if not self.active_connections:
            return

        message_str = json.dumps(message, ensure_ascii=False)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                disconnected.add(connection)

        # 清理断开的连接
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_account(self, account_data: dict) -> None:
        """广播账户信息更新"""
        await self.broadcast({
            "type": "account_update",
            "data": account_data,
            "timestamp": datetime.now().isoformat(),
        })

    async def broadcast_position(self, position_data: dict) -> None:
        """广播持仓信息更新"""
        await self.broadcast({
            "type": "position_update",
            "data": position_data,
            "timestamp": datetime.now().isoformat(),
        })

    async def broadcast_trade(self, trade_data: dict) -> None:
        """广播新成交记录"""
        await self.broadcast({
            "type": "trade_update",
            "data": trade_data,
            "timestamp": datetime.now().isoformat(),
        })

    async def broadcast_order(self, order_data: dict) -> None:
        """广播委托单状态更新"""
        await self.broadcast({
            "type": "order_update",
            "data": order_data,
            "timestamp": datetime.now().isoformat(),
        })

    async def broadcast_quote(self, quote_data: dict) -> None:
        """广播行情更新"""
        await self.broadcast({
            "type": "quote_update",
            "data": quote_data,
            "timestamp": datetime.now().isoformat(),
        })


# 创建全局实例
websocket_manager = WebSocketManager()
