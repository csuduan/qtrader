"""
成交数据持久化DAO
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qtrader.models.object import TradeData
from qtrader.models.po import TradePo
from qtrader.utils.async_database import fetch_one, get_async_session
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class TradeDao:
    """成交数据访问对象"""

    @logger.catch(message="持久化成交数据失败")
    async def save(self, account_id: str, data: TradeData) -> None:
        """持久化成交数据"""
        async with get_async_session() as session:
            await self._save_with_session(session, account_id, data)

    async def _save_with_session(
        self, session: AsyncSession, account_id: str, data: TradeData
    ) -> None:
        """在指定会话中持久化成交数据"""
        trade_id = data.trade_id if hasattr(data, "trade_id") else None
        if not trade_id:
            return

        existing = await fetch_one(session, select(TradePo).filter_by(trade_id=trade_id))
        if existing:
            return

        trade_po = TradePo(
            account_id=account_id,
            trade_id=trade_id,
            order_id=data.order_id if hasattr(data, "order_id") else "",
            symbol=data.symbol if hasattr(data, "symbol") else "",
            direction=data.direction.value if hasattr(data, "direction") else "",
            offset=data.offset.value if hasattr(data, "offset") else "",
            price=Decimal(str(data.price)) if hasattr(data, "price") else Decimal("0"),
            volume=data.volume if hasattr(data, "volume") else 0,
            trade_date_time=(
                data.trade_time
                if hasattr(data, "trade_time") and data.trade_time
                else datetime.now()
            ),
            order_price=(
                Decimal(str(data.order_price))
                if hasattr(data, "order_price") and data.order_price is not None
                else None
            ),
        )
        session.add(trade_po)
        logger.debug(f"成交数据已持久化: {trade_id}")
