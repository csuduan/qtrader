"""
数据持久化模块
从事件引擎获取数据并写入数据库
"""
from datetime import datetime
from typing import Any
from decimal import Decimal

from src.context import get_trading_engine
from src.database import get_session
from src.models.po import AccountPo, OrderPo, PositionPo, TradePo
from src.utils.event import Event, EventTypes, event_engine, HandlerType
from src.utils.logger import get_logger
from src.models.object import OrderData, TradeData, AccountData, PositionData

logger = get_logger(__name__)


class Persistence:
    """数据持久化类"""

    def __init__(self):
        """初始化持久化类"""
        self._handlers_registered = False

    def start(self) -> None:
        """启动持久化服务，注册事件处理器"""
        if self._handlers_registered:
            logger.warning("持久化事件处理器已注册，无需重复注册")
            return

        event_engine.register(EventTypes.ACCOUNT_UPDATE, self._handle_account_update)
        event_engine.register(EventTypes.POSITION_UPDATE, self._handle_position_update)
        event_engine.register(EventTypes.ORDER_UPDATE, self._handle_order_update)
        event_engine.register(EventTypes.TRADE_UPDATE, self._handle_trade_update)

        self._handlers_registered = True
        logger.info("数据持久化服务已启动")

    def stop(self) -> None:
        """停止持久化服务，注销事件处理器"""
        if not self._handlers_registered:
            return

        event_engine.unregister(EventTypes.ACCOUNT_UPDATE, self._handle_account_update)
        event_engine.unregister(EventTypes.POSITION_UPDATE, self._handle_position_update)
        event_engine.unregister(EventTypes.ORDER_UPDATE, self._handle_order_update)
        event_engine.unregister(EventTypes.TRADE_UPDATE, self._handle_trade_update)

        self._handlers_registered = False
        logger.info("数据持久化服务已停止")

    def _handle_account_update(self, event: Event) -> None:
        """
        处理账户更新事件

        Args:
            event: 账户更新事件（data为dict）
        """
        try:
            data:AccountData = event.data
            account_id = data.account_id

            if not account_id:
                logger.warning("账户更新事件缺少account_id")
                return

            session = get_session()
            if not session:
                logger.error("无法获取数据库会话")
                return

            account_po = session.query(AccountPo).filter_by(account_id=account_id).first()
            if not account_po:
                account_po = AccountPo(account_id=account_id)

            account_po.broker_name = None
            account_po.currency = "CNY"
            account_po.balance = Decimal(data.balance)
            account_po.available = Decimal(str(data.available))
            account_po.margin = Decimal(str(data.margin))
            account_po.float_profit = Decimal(str(data.float_profit or 0))
            account_po.position_profit = Decimal(str(data.hold_profit or 0))
            account_po.close_profit = Decimal(str(data.close_profit or 0))
            account_po.risk_ratio = Decimal(str(data.risk_ratio or 0))
            account_po.updated_at = datetime.now()

            session.add(account_po)
            session.commit()
            session.close()

            logger.debug(f"账户信息已持久化: {account_id}")

        except Exception as e:
            logger.exception(f"持久化账户信息时出错: {e}")

    def _handle_position_update(self, event: Event) -> None:
        """
        处理持仓更新事件

        Args:
            event: 持仓更新事件（data为dict）
        """
        try:
            data:PositionData = event.data
            if not data:
                logger.warning("持仓更新事件数据为空")
                return

            trading_engine = get_trading_engine()
            if not trading_engine:
                logger.warning("trading_engine未初始化")
                return

            account_id = trading_engine.config.account_id
            symbol = data.symbol

            if not account_id or not symbol:
                logger.warning("持仓更新事件缺少必要字段")
                return

            session = get_session()
            if not session:
                logger.error("无法获取数据库会话")
                return

            position_po = session.query(PositionPo).filter_by(
                account_id=account_id, symbol=symbol
            ).first()

            if not position_po:
                position_po = PositionPo(
                    account_id=account_id,
                    symbol=symbol,
                )

            position_po.pos_long = data.pos_long
            position_po.pos_short = data.pos_short
            position_po.open_price_long = Decimal(str(data.open_price_long))
            position_po.open_price_short = Decimal(str(data.open_price_short))
            position_po.float_profit = Decimal(str(data.float_profit_long+data.float_profit_short))
            position_po.margin = Decimal(str(data.margin_long+data.margin_short))
            position_po.updated_at = datetime.now()

            session.add(position_po)
            session.commit()
            session.close()

            logger.debug(f"持仓信息已持久化: {symbol}")

        except Exception as e:
            logger.exception(f"持久化持仓信息时出错: {e}")

    def _handle_order_update(self, event: Event) -> None:
        """
        处理委托单更新事件

        Args:
            event: 委托单更新事件（data为dict）
        """
        try:
            data: OrderData = event.data
            # trading_engine = get_trading_engine()
            # if not trading_engine:
            #     logger.warning("trading_engine未初始化")
            #     return

            # account_id = trading_engine.config.account_id
            # order_id = data.get("order_id")

            # if not order_id:
            #     logger.warning("委托单更新事件缺少order_id")
            #     return

            # session = get_session()
            # if not session:
            #     logger.error("无法获取数据库会话")
            #     return

            # order_po = session.query(OrderPo).filter_by(order_id=order_id).first()

            # if not order_po:
            #     order_po = OrderPo(account_id=account_id, order_id=order_id)

            # order_po.exchange_order_id = data.get("exchange_order_id", "")
            # order_po.symbol = data.get("symbol", "")
            # order_po.direction = data.get("direction", "")
            # order_po.offset = data.get("offset", "")
            # order_po.volume_orign = data.get("volume_orign", 0)
            # order_po.volume_left = data.get("volume_left", 0)
            # order_po.limit_price = Decimal(str(data.get("limit_price", 0))) if data.get("limit_price") else None
            # order_po.price_type = data.get("price_type", "")
            # order_po.status = data.get("status", "")
            # order_po.insert_date_time = data.get("insert_date_time", 0)
            # order_po.last_msg = data.get("last_msg", "")
            # order_po.updated_at = datetime.now()

            # session.add(order_po)
            # session.commit()
            # session.close()

            # logger.debug(f"委托单信息已持久化: {order_id}")

        except Exception as e:
            logger.exception(f"持久化委托单信息时出错: {e}")

    def _handle_trade_update(self, event: Event) -> None:
        """
        处理成交更新事件

        Args:
            event: 成交更新事件（data为dict）
        """
        try:
            data: TradeData = event.data

            trading_engine = get_trading_engine()
            if not trading_engine:
                logger.warning("trading_engine未初始化")
                return

            account_id = trading_engine.account_id
            trade_id = data.trade_id

            if not trade_id:
                logger.warning("成交更新事件缺少trade_id")
                return

            session = get_session()
            if not session:
                logger.error("无法获取数据库会话")
                return

            existing = session.query(TradePo).filter_by(trade_id=trade_id).first()
            if existing:
                session.close()
                return

            trade_po = TradePo(
                account_id=account_id,
                trade_id=trade_id,
                order_id=data.order_id,
                symbol=data.symbol,
                direction=data.direction,
                offset=data.offset,
                price=Decimal(str(data.price)),
                volume=data.volume,
                trade_date_time=data.trade_time,
            )

            session.add(trade_po)
            session.commit()
            session.close()

            logger.debug(f"成交信息已持久化: {trade_id}")

        except Exception as e:
            logger.exception(f"持久化成交信息时出错: {e}")


# 全局持久化实例
_persistence: Persistence = None


def get_persistence() -> Persistence:
    """
    获取全局持久化实例

    Returns:
        Persistence: 持久化实例
    """
    global _persistence
    if _persistence is None:
        _persistence = Persistence()
    return _persistence


def init_persistence() -> Persistence:
    """
    初始化并启动持久化服务

    Returns:
        Persistence: 持久化实例
    """
    global _persistence
    if _persistence is None:
        _persistence = Persistence()
    _persistence.start()
    return _persistence
