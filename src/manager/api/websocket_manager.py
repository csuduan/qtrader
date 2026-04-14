"""
WebSocket管理模块
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

import simplejson as json
from fastapi import WebSocket

from src.app_context import AppContext, get_app_context
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.event_engine import EventTypes
from src.utils.logger import get_logger

logger = get_logger(__name__)
ctx: AppContext = get_app_context()


class WebSocketManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        # 行情订阅状态: connection -> bool
        self.quote_subscriptions: dict[WebSocket, bool] = {}

    def start(self):
        event_engine: AsyncEventEngine = ctx.get(AppContext.KEY_EVENT_ENGINE)
        event_engine.register(EventTypes.POSITION_UPDATE, self.broadcast_position)
        event_engine.register(EventTypes.ORDER_UPDATE, self.broadcast_order)
        event_engine.register(EventTypes.TRADE_UPDATE, self.broadcast_trade)
        event_engine.register(EventTypes.TICK_UPDATE, self.broadcast_quote)
        event_engine.register(EventTypes.ACCOUNT_UPDATE, self.broadcast_account)
        event_engine.register(EventTypes.ACCOUNT_STATUS, self.broadcast_account_status)
        logger.info("WEBSOCKET已注册事件引擎订阅")

    async def connect(self, websocket: WebSocket):
        """接受WebSocket连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
        self.quote_subscriptions[websocket] = False
        logger.info(f"WebSocket连接已建立，当前连接数: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """断开WebSocket连接"""
        self.active_connections.discard(websocket)
        self.quote_subscriptions.pop(websocket, None)
        logger.info(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")

    def set_quote_subscription(self, websocket: WebSocket, subscribed: bool) -> None:
        """设置指定连接的行情订阅状态"""
        if websocket in self.quote_subscriptions:
            self.quote_subscriptions[websocket] = subscribed
            logger.info(f"WebSocket行情订阅状态更新: {subscribed}")

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        if not self.active_connections:
            return
        message_str = json.dumps(message, ignore_nan=True)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                disconnected.add(connection)

        # 清理断开的连接
        for connection in disconnected:
            await self.disconnect(connection)

    async def broadcast_to_subscribers(self, message: dict, subscription_key: str):
        """按订阅状态广播消息"""
        if not self.active_connections:
            return
        message_str = json.dumps(message, ignore_nan=True)
        disconnected = set()

        for connection in self.active_connections:
            if not self.quote_subscriptions.get(connection, False):
                continue
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                disconnected.add(connection)

        # 清理断开的连接
        for connection in disconnected:
            await self.disconnect(connection)

    async def broadcast_account(self, account_data: dict) -> None:
        """广播账户信息更新"""
        await self.broadcast(
            {
                "type": "account_update",
                "data": account_data,
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def broadcast_position(self, position_data: dict) -> None:
        """广播持仓信息更新"""
        await self.broadcast(
            {
                "type": "position_update",
                "data": position_data,
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def broadcast_trade(self, trade_data: dict) -> None:
        """广播新成交记录"""
        await self.broadcast(
            {
                "type": "trade_update",
                "data": trade_data,
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def broadcast_order(self, order_data: dict) -> None:
        """广播委托单状态更新"""
        await self.broadcast(
            {
                "type": "order_update",
                "data": order_data,
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def broadcast_quote(self, quote_data: dict) -> None:
        """广播行情更新（仅推送给订阅了行情的连接）"""
        await self.broadcast_to_subscribers(
            {
                "type": "quote_update",
                "data": quote_data,
                "timestamp": datetime.now().isoformat(),
            },
            "quote",
        )

    async def broadcast_account_status(self, status_data: dict) -> None:
        """广播账户状态更新（暂停/恢复、连接/断开等）"""
        await self.broadcast(
            {
                "type": "account_update",
                "data": status_data,
                "timestamp": datetime.now().isoformat(),
            }
        )



# 创建全局实例
websocket_manager = WebSocketManager()
