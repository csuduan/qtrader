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
from src.utils.event_engine import EventEngine, EventTypes
from src.utils.logger import get_logger

logger = get_logger(__name__)
ctx: AppContext = get_app_context()


class WebSocketManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    def start(self):
        event_engine: EventEngine = ctx.get(AppContext.KEY_EVENT_ENGINE)
        event_engine.register(EventTypes.POSITION_UPDATE, self.broadcast_position)
        event_engine.register(EventTypes.ORDER_UPDATE, self.broadcast_order)
        event_engine.register(EventTypes.TRADE_UPDATE, self.broadcast_trade)
        event_engine.register(EventTypes.TICK_UPDATE, self.broadcast_quote)
        event_engine.register(EventTypes.ACCOUNT_UPDATE, self.broadcast_account)
        event_engine.register(EventTypes.ACCOUNT_STATUS, self.broadcast_account_status)
        event_engine.register(EventTypes.ALARM_UPDATE, self.broadcast_alarm)
        logger.info("WEBSOCKET已注册事件引擎订阅")

    async def connect(self, websocket: WebSocket):
        """接受WebSocket连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket连接已建立，当前连接数: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """断开WebSocket连接"""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")

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
        """广播行情更新"""
        await self.broadcast(
            {
                "type": "quote_update",
                "data": quote_data,
                "timestamp": datetime.now().isoformat(),
            }
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

    async def broadcast_alarm(self, alarm_data: dict) -> None:
        """广播告警更新"""
        await self.broadcast(
            {
                "type": "alarm_update",
                "data": alarm_data,
                "timestamp": datetime.now().isoformat(),
            }
        )

    # ==================== 策略事件推送 ====================

    async def broadcast_strategy_status(self, strategy_status: dict):
        """
        推送策略状态更新

        Args:
            strategy_status: 策略状态数据
        """
        message = {
            "type": "strategy_status",
            "data": strategy_status,
            "timestamp": datetime.now().isoformat(),
        }
        await self.broadcast(message)

    async def broadcast_strategy_signal(self, signal: dict):
        """
        推送策略信号

        Args:
            signal: 策略信号数据
        """
        message = {
            "type": "strategy_signal",
            "data": signal,
            "timestamp": datetime.now().isoformat(),
        }
        await self.broadcast(message)


# 创建全局实例
websocket_manager = WebSocketManager()
