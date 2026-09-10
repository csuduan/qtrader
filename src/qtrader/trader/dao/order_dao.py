"""
订单数据持久化DAO
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qtrader.models.object import OrderData
from qtrader.models.po import OrderPo
from qtrader.utils.async_database import fetch_one, get_async_session
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class OrderDao:
    """订单数据访问对象"""

    async def save(self, account_id: str, data: OrderData) -> None:
        """持久化订单数据"""
        try:
            async with get_async_session() as session:
                await self._save_with_session(session, account_id, data)
        except Exception as e:
            logger.exception(f"持久化订单数据失败: {e}")

    async def _save_with_session(
        self, session: AsyncSession, account_id: str, data: OrderData
    ) -> None:
        """在指定会话中持久化订单数据"""
        order_id = data.order_id if hasattr(data, "order_id") else None
        if not order_id:
            return

        order_po = await fetch_one(
            session, select(OrderPo).filter_by(account_id=account_id, order_id=order_id)
        )
        if not order_po:
            order_po = OrderPo(account_id=account_id, order_id=order_id)

        order_po.symbol = data.symbol if hasattr(data, "symbol") else ""
        order_po.direction = data.direction.value if hasattr(data, "direction") else ""
        order_po.offset = data.offset.value if hasattr(data, "offset") else ""
        order_po.limit_price = (
            Decimal(str(data.price)) if hasattr(data, "price") and data.price is not None else None
        )
        order_po.volume_orign = data.volume if hasattr(data, "volume") else 0
        order_po.volume_left = (
            data.volume_left
            if hasattr(data, "volume_left")
            else data.volume if hasattr(data, "volume") else 0
        )
        order_po.status = data.status if hasattr(data, "status") else ""
        order_po.price_type = data.price_type if hasattr(data, "price_type") else "LIMIT"
        order_po.exchange_order_id = getattr(data, "gateway_order_id", None) or getattr(
            data, "order_sys_id", None
        )
        order_po.status_msg = data.status_msg if hasattr(data, "status_msg") else None
        order_po.update_date_time = data.update_time if hasattr(data, "update_time") else None
        insert_time = data.insert_time if hasattr(data, "insert_time") else None
        order_po.insert_date_time = insert_time or order_po.update_date_time or datetime.now()

        session.add(order_po)
        logger.debug(f"订单数据已持久化: {order_id}")
