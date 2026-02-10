"""
数据持久化模块
从事件引擎获取数据并写入数据库
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from src.app_context import get_app_context
from src.models.object import AccountData, OrderData, PositionData, TradeData
from src.models.po import AccountPo, OrderPo, PositionPo, TradePo
from src.utils.database import get_session
from src.utils.event_engine import EventEngine, EventTypes, HandlerType
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.trader.trading_engine import TradingEngine

logger = get_logger(__name__)


class Persistence:
    """数据持久化类"""

    def __init__(self, event_engine: EventEngine, trading_engine: "TradingEngine"):
        """
        初始化持久化类

        Args:
            event_engine: 事件引擎实例
            trading_engine: 交易引擎实例
        """
        self._event_engine = event_engine
        self._trading_engine = trading_engine
        self._handlers_registered = False

    def start(self) -> None:
        """启动持久化服务，注册事件处理器"""
        if self._handlers_registered:
            logger.warning("持久化事件处理器已注册，无需重复注册")
            return

        self._event_engine.register(EventTypes.ACCOUNT_UPDATE, self._handle_account_update)
        self._event_engine.register(EventTypes.POSITION_UPDATE, self._handle_position_update)
        self._event_engine.register(EventTypes.ORDER_UPDATE, self._handle_order_update)
        self._event_engine.register(EventTypes.TRADE_UPDATE, self._handle_trade_update)

        self._handlers_registered = True
        logger.info("数据持久化服务已启动")

    def stop(self) -> None:
        """停止持久化服务，注销事件处理器"""
        if not self._handlers_registered:
            return

        self._event_engine.unregister(EventTypes.ACCOUNT_UPDATE, self._handle_account_update)
        self._event_engine.unregister(EventTypes.POSITION_UPDATE, self._handle_position_update)
        self._event_engine.unregister(EventTypes.ORDER_UPDATE, self._handle_order_update)
        self._event_engine.unregister(EventTypes.TRADE_UPDATE, self._handle_trade_update)

        self._handlers_registered = False
        logger.info("数据持久化服务已停止")

    def _handle_account_update(self, data: AccountData) -> None:
        """
        处理账户更新事件

        Args:
            data: 账户数据
        """
        try:
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

            account_po.broker_name = None  # type: ignore[assignment]
            account_po.currency = "CNY"  # type: ignore[assignment]
            account_po.balance = Decimal(data.balance)  # type: ignore[assignment]
            account_po.available = Decimal(str(data.available))  # type: ignore[assignment]
            account_po.margin = Decimal(str(data.margin))  # type: ignore[assignment]
            account_po.float_profit = Decimal(str(data.float_profit or 0))  # type: ignore[assignment]
            account_po.position_profit = Decimal(str(data.hold_profit or 0))  # type: ignore[assignment]
            account_po.close_profit = Decimal(str(data.close_profit or 0))  # type: ignore[assignment]
            account_po.risk_ratio = Decimal(str(data.risk_ratio or 0))  # type: ignore[assignment]
            account_po.updated_at = datetime.now()  # type: ignore[assignment]

            session.add(account_po)
            session.commit()
            session.close()

            logger.debug(f"账户信息已持久化: {account_id}")

        except Exception as e:
            logger.exception(f"持久化账户信息时出错: {e}")

    def _handle_position_update(self, data: PositionData) -> None:
        """
        处理持仓更新事件

        Args:
            data: 持仓数据
        """
        try:
            if not data:
                logger.warning("持仓更新事件数据为空")
                return

            account_id = self._trading_engine.account_id
            symbol = data.symbol

            if not account_id or not symbol:
                logger.warning("持仓更新事件缺少必要字段")
                return

            session = get_session()
            if not session:
                logger.error("无法获取数据库会话")
                return

            position_po = (
                session.query(PositionPo).filter_by(account_id=account_id, symbol=symbol).first()
            )

            if not position_po:
                position_po = PositionPo(
                    account_id=account_id,
                    symbol=symbol,
                )

            position_po.pos_long = data.pos_long  # type: ignore[assignment]
            position_po.pos_short = data.pos_short  # type: ignore[assignment]
            position_po.open_price_long = Decimal(str(data.open_price_long))  # type: ignore[assignment]
            position_po.open_price_short = Decimal(str(data.open_price_short))  # type: ignore[assignment]
            # 处理None值：如果为None则使用0
            float_profit_long = data.float_profit_long or 0
            float_profit_short = data.float_profit_short or 0
            margin_long = data.margin_long or 0
            margin_short = data.margin_short or 0
            position_po.float_profit = Decimal(str(float_profit_long + float_profit_short))  # type: ignore[assignment]
            position_po.margin = Decimal(str(margin_long + margin_short))  # type: ignore[assignment]
            position_po.updated_at = datetime.now()  # type: ignore[assignment]

            session.add(position_po)
            session.commit()
            session.close()

            logger.debug(f"持仓信息已持久化: {symbol}")

        except Exception as e:
            logger.exception(f"持久化持仓信息时出错: {e}")

    def _handle_order_update(self, data: OrderData) -> None:
        """
        处理委托单更新事件

        Args:
            data: 委托单数据
        """
        try:
            # 委托单持久化暂时禁用（可根据需要启用）
            pass

        except Exception as e:
            logger.exception(f"持久化委托单信息时出错: {e}")

    def _handle_trade_update(self, data: TradeData) -> None:
        """
        处理成交更新事件

        Args:
            data: 成交数据
        """
        try:
            account_id = self._trading_engine.account_id
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
_persistence: Optional[Persistence] = None


def get_persistence(
    event_engine: Optional[EventEngine] = None, trading_engine: Optional["TradingEngine"] = None
) -> Persistence:
    """
    获取全局持久化实例

    Args:
        event_engine: 事件引擎实例（首次创建时需要）
        trading_engine: 交易引擎实例（首次创建时需要）

    Returns:
        Persistence: 持久化实例
    """
    global _persistence
    if _persistence is None:
        if event_engine is None or trading_engine is None:
            raise ValueError("首次创建Persistence需要提供event_engine和trading_engine参数")
        _persistence = Persistence(event_engine, trading_engine)
    return _persistence


def init_persistence(event_engine: EventEngine, trading_engine: "TradingEngine") -> Persistence:
    """
    初始化并启动持久化服务

    Args:
        event_engine: 事件引擎实例
        trading_engine: 交易引擎实例

    Returns:
        Persistence: 持久化实例
    """
    global _persistence
    if _persistence is None:
        _persistence = Persistence(event_engine, trading_engine)
    _persistence.start()
    return _persistence
