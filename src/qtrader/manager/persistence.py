"""
Manager 端统一持久化层
订阅事件引擎的数据更新事件，写入共享数据库

Manager 是共享数据库（qtrader.db）的唯一写入者。
所有 Trader 的数据通过 IPC 推送到 Manager，再由此模块持久化。
"""

from datetime import datetime
from decimal import Decimal

from qtrader.app_context import get_app_context as ctx
from qtrader.models.po import AccountPo, PositionPo, TradePo
from qtrader.utils.async_event_engine import AsyncEventEngine
from qtrader.utils.database import get_database
from qtrader.utils.event_engine import EventTypes
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class ManagerPersistence:
    """Manager 侧统一持久化服务

    订阅事件引擎的 ACCOUNT/POSITION/TRADE 事件，将 Trader 推送的数据写入共享数据库。
    """

    def __init__(self, event_engine: AsyncEventEngine):
        self._event_engine = event_engine
        self._handlers_registered = False

    def start(self) -> None:
        """启动持久化服务，注册事件处理器"""
        if self._handlers_registered:
            return

        self._event_engine.register(EventTypes.ACCOUNT_UPDATE, self._handle_account)
        self._event_engine.register(EventTypes.POSITION_UPDATE, self._handle_position)
        self._event_engine.register(EventTypes.TRADE_UPDATE, self._handle_trade)

        self._handlers_registered = True
        logger.info("Manager 持久化服务已启动")

    def stop(self) -> None:
        """停止持久化服务"""
        if not self._handlers_registered:
            return

        self._event_engine.unregister(EventTypes.ACCOUNT_UPDATE, self._handle_account)
        self._event_engine.unregister(EventTypes.POSITION_UPDATE, self._handle_position)
        self._event_engine.unregister(EventTypes.TRADE_UPDATE, self._handle_trade)

        self._handlers_registered = False
        logger.info("Manager 持久化服务已停止")

    def _handle_account(self, data: dict) -> None:
        """处理账户更新事件，upsert 到共享库"""
        account_id = data.get("account_id")
        if not account_id:
            return

        db = get_database()
        if db is None:
            return

        try:
            with db.get_session() as session:
                account_po = session.query(AccountPo).filter_by(account_id=account_id).first()
                if not account_po:
                    account_po = AccountPo(account_id=account_id)

                account_po.balance = Decimal(str(data.get("balance", 0)))
                account_po.available = Decimal(str(data.get("available", 0)))
                account_po.margin = Decimal(str(data.get("margin", 0)))
                account_po.position_profit = Decimal(str(data.get("hold_profit", 0)))
                account_po.close_profit = Decimal(str(data.get("close_profit", 0)))
                account_po.risk_ratio = Decimal(str(data.get("risk_ratio", 0)))
                account_po.updated_at = datetime.now()

                session.add(account_po)

            logger.debug(f"账户信息已持久化: {account_id}")
        except Exception as e:
            logger.exception(f"持久化账户信息时出错: {e}")

    def _handle_position(self, data: dict) -> None:
        """处理持仓更新事件，upsert 到共享库"""
        account_id = data.get("account_id") or data.get("extras", {}).get("account_id")
        symbol = data.get("symbol")
        if not account_id or not symbol:
            return

        db = get_database()
        if db is None:
            return

        try:
            with db.get_session() as session:
                strategy_id = data.get("strategy_id")
                query = session.query(PositionPo).filter_by(account_id=account_id, symbol=symbol)
                if strategy_id:
                    query = query.filter_by(strategy_id=strategy_id)
                else:
                    query = query.filter(PositionPo.strategy_id.is_(None))

                position_po = query.first()
                if not position_po:
                    position_po = PositionPo(
                        account_id=account_id,
                        symbol=symbol,
                        exchange=data.get("exchange", ""),
                    )
                    if strategy_id:
                        position_po.strategy_id = strategy_id

                # 多头
                if data.get("pos_long_td") is not None:
                    position_po.pos_long_td = data["pos_long_td"]
                if data.get("pos_long_yd") is not None:
                    position_po.pos_long_yd = data["pos_long_yd"]
                # 空头
                if data.get("pos_short_td") is not None:
                    position_po.pos_short_td = data["pos_short_td"]
                if data.get("pos_short_yd") is not None:
                    position_po.pos_short_yd = data["pos_short_yd"]

                # 均价
                if data.get("hold_price_long") is not None:
                    position_po.hold_price_long = Decimal(str(data["hold_price_long"]))
                if data.get("hold_price_short") is not None:
                    position_po.hold_price_short = Decimal(str(data["hold_price_short"]))

                # 盈亏
                if data.get("hold_profit_long") is not None:
                    position_po.hold_profit_long = Decimal(str(data["hold_profit_long"]))
                if data.get("hold_profit_short") is not None:
                    position_po.hold_profit_short = Decimal(str(data["hold_profit_short"]))

                # 保证金
                margin_long = data.get("margin_long") or 0
                margin_short = data.get("margin_short") or 0
                position_po.margin = Decimal(str(margin_long + margin_short))
                position_po.updated_at = datetime.now()

                session.add(position_po)

            logger.debug(f"持仓信息已持久化: {account_id}/{symbol}")
        except Exception as e:
            logger.exception(f"持久化持仓信息时出错: {e}")

    def _handle_trade(self, data: dict) -> None:
        """处理成交通知事件，insert 到共享库"""
        trade_id = data.get("trade_id")
        if not trade_id:
            return

        db = get_database()
        if db is None:
            return

        try:
            with db.get_session() as session:
                existing = session.query(TradePo).filter_by(trade_id=trade_id).first()
                if existing:
                    return

                account_id = data.get("account_id") or data.get("extras", {}).get("account_id")
                order_price = data.get("order_price")
                trade_po = TradePo(
                    account_id=account_id,
                    trade_id=trade_id,
                    order_id=data.get("order_id"),
                    symbol=data.get("symbol"),
                    direction=data.get("direction"),
                    offset=data.get("offset"),
                    price=Decimal(str(data.get("price", 0))),
                    volume=data.get("volume", 0),
                    trade_date_time=data.get("trade_time") or data.get("trade_date_time", 0),
                    order_price=Decimal(str(order_price)) if order_price is not None else None,
                )

                session.add(trade_po)

            logger.debug(f"成交信息已持久化: {trade_id}")
        except Exception as e:
            logger.exception(f"持久化成交信息时出错: {e}")


# 全局实例
_persistence: ManagerPersistence | None = None


def init_persistence(event_engine: AsyncEventEngine) -> ManagerPersistence:
    """初始化并启动持久化服务"""
    global _persistence
    if _persistence is None:
        _persistence = ManagerPersistence(event_engine)
    _persistence.start()
    return _persistence


def get_persistence() -> ManagerPersistence | None:
    """获取持久化服务实例"""
    return _persistence
