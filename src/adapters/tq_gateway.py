"""
TqSdk Gateway适配器
包装现有的TradingEngine，适配统一接口
"""
from datetime import datetime
from typing import Optional, Dict, Any

from src.adapters.base_gateway import BaseGateway
from src.models.object import (
    TickData, BarData, OrderData, TradeData,
    PositionData, AccountData, ContractData,
    SubscribeRequest, OrderRequest, CancelRequest,
    Direction, Offset, Status, OrderType, Exchange
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TqGateway(BaseGateway):
    """TqSdk Gateway适配器"""

    gateway_name = "TqSdk"

    def __init__(self, trading_engine):
        """
        初始化

        Args:
            trading_engine: TradingEngine实例
        """
        super().__init__()
        self.engine = trading_engine
        self.exchange_map = self._init_exchange_map()

        # 缓存
        self._contracts_cache: Dict[str, ContractData] = {}

    def _init_exchange_map(self) -> Dict[str, Exchange]:
        """初始化交易所映射"""
        return {
            "SHFE": Exchange.SHFE,
            "DCE": Exchange.DCE,
            "CZCE": Exchange.CZCE,
            "CFFEX": Exchange.CFFEX,
            "INE": Exchange.INE,
            "GFEX": Exchange.GFEX,
        }

    # ==================== 连接管理 ====================

    def connect(self) -> bool:
        """TqEngine已在外部连接，此处仅标记状态"""
        try:
            if self.engine and self.engine.connected:
                self.trading_day = datetime.now().strftime("%Y%m%d")
                self.connected = True
                logger.info(f"{self.gateway_name} 连接成功，交易日: {self.trading_day}")
                return True
            return False
        except Exception as e:
            logger.error(f"{self.gateway_name} 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开连接"""
        try:
            if self.engine:
                self.engine.disconnect()
            self.connected = False
            logger.info(f"{self.gateway_name} 已断开连接")
            return True
        except Exception as e:
            logger.error(f"{self.gateway_name} 断开连接失败: {e}")
            return False

    # ==================== 行情订阅 ====================

    def subscribe(self, req: SubscribeRequest) -> bool:
        """订阅行情"""
        try:
            for symbol in req.symbols:
                self.engine.subscribe_symbol(symbol)
                logger.debug(f"订阅行情: {symbol}")
            return True
        except Exception as e:
            logger.error(f"订阅行情失败: {e}")
            return False

    def unsubscribe(self, req: SubscribeRequest) -> bool:
        """取消订阅"""
        try:
            for symbol in req.symbols:
                self.engine.unsubscribe_symbol(symbol)
            return True
        except Exception as e:
            logger.error(f"取消订阅失败: {e}")
            return False

    # ==================== 交易接口 ====================

    def send_order(self, req: OrderRequest) -> Optional[str]:
        """下单"""
        try:
            order_id = self.engine.insert_order(
                symbol=req.symbol,
                direction=req.direction.value,
                offset=req.offset.value,
                volume=req.volume,
                price=req.price or 0
            )
            logger.info(f"下单成功: {req.symbol} {req.direction.value} {req.offset.value} {req.volume}手 @{req.price}")
            return order_id
        except Exception as e:
            logger.error(f"下单失败: {e}")
            return None

    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单"""
        try:
            success = self.engine.cancel_order(req.order_id)
            if success:
                logger.info(f"撤单成功: {req.order_id}")
            return success
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    # ==================== 查询接口 ====================

    def query_account(self) -> Optional[AccountData]:
        """查询账户"""
        try:
            if not self.engine or not self.engine.account:
                return None

            acc = self.engine.account
            return AccountData(
                account_id=self.engine.config.account_id,
                balance=float(acc.get("balance", 0)),
                available=float(acc.get("available", 0)),
                frozen=float(acc.get("frozen", 0)),
                margin=float(acc.get("margin", 0)),
                pre_balance=float(acc.get("pre_balance", 0)),
                hold_profit=float(acc.get("float_profit", 0)),
                close_profit=float(acc.get("close_profit", 0)),
                risk_ratio=float(acc.get("risk_ratio", 0)),
                update_time=datetime.now()
            )
        except Exception as e:
            logger.error(f"查询账户失败: {e}")
            return None

    def query_position(self) -> list[PositionData]:
        """查询持仓"""
        try:
            if not self.engine or not self.engine.positions:
                return []

            result = []
            for symbol, pos in self.engine.positions.items():
                # 分离长短仓
                if pos.get("pos_long", 0) > 0:
                    result.append(PositionData(
                        symbol=symbol.split(".")[1],
                        exchange=self._parse_exchange(symbol.split(".")[0]),
                        direction="LONG",
                        volume=int(pos.get("pos_long", 0)),
                        yd_volume=int(pos.get("pos_long_his", 0)),
                        td_volume=int(pos.get("pos_long_today", 0)),
                        avg_price=pos.get("open_price_long", 0),
                        hold_profit=pos.get("float_profit_long", 0),
                        margin=pos.get("margin_long", 0)
                    ))

                if pos.get("pos_short", 0) > 0:
                    result.append(PositionData(
                        symbol=symbol.split(".")[1],
                        exchange=self._parse_exchange(symbol.split(".")[0]),
                        direction="SHORT",
                        volume=int(pos.get("pos_short", 0)),
                        yd_volume=int(pos.get("pos_short_his", 0)),
                        td_volume=int(pos.get("pos_short_today", 0)),
                        avg_price=pos.get("open_price_short", 0),
                        hold_profit=pos.get("float_profit_short", 0),
                        margin=pos.get("margin_short", 0)
                    ))

            return result
        except Exception as e:
            logger.error(f"查询持仓失败: {e}")
            return []

    def query_orders(self) -> list[OrderData]:
        """查询活动订单"""
        try:
            if not self.engine or not self.engine.orders:
                return []

            result = []
            for order_id, order in self.engine.orders.items():
                result.append(self._convert_order(order))

            return result
        except Exception as e:
            logger.error(f"查询订单失败: {e}")
            return []

    def query_trades(self) -> list[TradeData]:
        """查询今日成交"""
        try:
            if not self.engine or not self.engine.trades:
                return []

            result = []
            for trade_id, trade in self.engine.trades.items():
                result.append(self._convert_trade(trade))

            return result
        except Exception as e:
            logger.error(f"查询成交失败: {e}")
            return []

    def query_contracts(self) -> Dict[str, ContractData]:
        """查询合约"""
        try:
            if self._contracts_cache:
                return self._contracts_cache

            # 查询合约列表
            if not self.engine or not self.engine.api:
                return {}

            # 简化实现 - 实际需要调用 query_quotes
            return self._contracts_cache
        except Exception as e:
            logger.error(f"查询合约失败: {e}")
            return {}

    # ==================== 数据转换 ====================

    def _convert_order(self, order: dict) -> OrderData:
        """转换TqSdk订单为统一格式"""
        exchange_id = order.get("exchange_id", "")
        instrument_id = order.get("instrument_id", "")

        return OrderData(
            order_id=order.get("order_id", ""),
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            direction=Direction(order.get("direction", "BUY")),
            offset=Offset(order.get("offset", "OPEN")),
            volume=int(order.get("volume_orign", 0)),
            traded=int(order.get("volume_orign", 0)) - int(order.get("volume_left", 0)),
            price=order.get("limit_price"),
            price_type=OrderType.LIMIT if order.get("limit_price") else OrderType.MARKET,
            status=self._convert_status(order.get("status", "UNKNOWN")),
            status_msg=order.get("last_msg", ""),
            gateway_order_id=order.get("exchange_order_id", ""),
            insert_time=datetime.fromtimestamp(order.get("insert_date_time", 0) / 1e9) if order.get("insert_date_time") else None,
            update_time=datetime.now()
        )

    def _convert_trade(self, trade: dict) -> TradeData:
        """转换TqSdk成交为统一格式"""
        exchange_id = trade.get("exchange_id", "")
        instrument_id = trade.get("instrument_id", "")

        return TradeData(
            trade_id=trade.get("trade_id", ""),
            order_id=trade.get("order_id", ""),
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            direction=Direction(trade.get("direction", "BUY")),
            offset=Offset(trade.get("offset", "OPEN")),
            price=float(trade.get("price", 0)),
            volume=int(trade.get("volume", 0)),
            trade_time=datetime.fromtimestamp(trade.get("trade_date_time", 0) / 1e9) if trade.get("trade_date_time") else None
        )

    # ==================== 辅助方法 ====================

    def _parse_exchange(self, exchange_code: str) -> Exchange:
        """解析交易所代码"""
        return self.exchange_map.get(exchange_code.upper(), Exchange.NONE)

    def _convert_status(self, status: str) -> Status:
        """转换订单状态"""
        status_map = {
            "ALIVE": Status.NOTTRADED,
            "FINISHED": Status.ALLTRADED,
            "CANCELED": Status.CANCELLED
        }
        return status_map.get(status, Status.SUBMITTING)
