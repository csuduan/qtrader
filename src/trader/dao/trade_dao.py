"""
成交数据持久化DAO
"""

from decimal import Decimal

from src.models.object import TradeData
from src.models.po import TradePo
from src.utils.database import session_scope
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeDao:
    """成交数据访问对象"""

    def save(self, account_id: str, data: TradeData) -> None:
        """持久化成交数据"""
        try:
            with session_scope() as session:
                self._save_with_session(session, account_id, data)
        except Exception as e:
            logger.exception(f"持久化成交数据失败: {e}")

    def _save_with_session(self, session, account_id: str, data: TradeData) -> None:
        """在指定会话中持久化成交数据"""
        trade_id = data.trade_id if hasattr(data, "trade_id") else None
        if not trade_id:
            return

        existing = session.query(TradePo).filter_by(trade_id=trade_id).first()
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
            trade_date_time=data.trade_time if hasattr(data, "trade_time") else 0,
            order_price=(
                Decimal(str(data.order_price))
                if hasattr(data, "order_price") and data.order_price is not None
                else None
            ),
        )
        session.add(trade_po)
        logger.debug(f"成交数据已持久化: {trade_id}")
