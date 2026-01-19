"""
WebSocket管理模块
"""
import asyncio
import json
import simplejson as json
from datetime import datetime
from typing import Optional

from fastapi import WebSocket

from src.utils.logger import get_logger


logger = get_logger(__name__)


class WebSocketManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self._cached_account_data: Optional[dict] = None
        self._account_update_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket):
        """接受WebSocket连接"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket连接已建立，当前连接数: {len(self.active_connections)}")
        await self._start_account_update_task()

    async def disconnect(self, websocket: WebSocket):
        """断开WebSocket连接"""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket连接已断开，当前连接数: {len(self.active_connections)}")
        if len(self.active_connections) == 0:
            await self._stop_account_update_task()

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
        """更新账户信息缓存（每3秒推送一次）"""
        self._cached_account_data = account_data

    async def _start_account_update_task(self) -> None:
        """启动账户信息定时推送任务"""
        if self._account_update_task is None or self._account_update_task.done():
            self._account_update_task = asyncio.create_task(self._account_update_loop())

    async def _stop_account_update_task(self) -> None:
        """停止账户信息定时推送任务"""
        if self._account_update_task is not None and not self._account_update_task.done():
            self._account_update_task.cancel()
            try:
                await self._account_update_task
            except asyncio.CancelledError:
                pass

    async def _account_update_loop(self) -> None:
        """账户信息定时推送循环"""
        while True:
            await asyncio.sleep(3)
            if self._cached_account_data is not None:
                await self.broadcast({
                    "type": "account_update",
                    "data": self._cached_account_data,
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
