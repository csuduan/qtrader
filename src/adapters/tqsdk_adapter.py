"""
TqSdk交易接口适配器
将TqSdk的接口适配到统一的TradingAdapter接口
"""
from typing import Any, Dict, List, Optional
import math

from tqsdk import TqApi, TqAuth, TqKq, TqSim, TqAccount
from tqsdk.objs import Account, Position, Trade, Order, Quote

from src.adapters.base import (
    TradingAdapter,
    AccountInfo,
    PositionInfo,
    TradeInfo,
    OrderInfo,
    QuoteInfo,
)


class TqSdkAdapter(TradingAdapter):
    """TqSdk接口适配器"""

    def __init__(
        self,
        account_type: str,
        account_id: str,
        tianqin_username: str,
        tianqin_password: str,
        trading_account_config: Optional[dict] = None,
    ):
        self.account_type = account_type
        self.account_id = account_id
        self.api: Optional[TqApi] = None
        self.auth: Optional[TqAuth] = None
        self.account: Optional[Account] = None
        self.positions: Dict[str, PositionInfo] = {}
        self.trades: Dict[str, TradeInfo] = {}
        self.orders: Dict[str, OrderInfo] = {}
        self.quotes: Dict[str, QuoteInfo] = {}
        self.tianqin_username = tianqin_username
        self.tianqin_password = tianqin_password
        self.trading_account_config = trading_account_config

    def connect(self) -> bool:
        """连接到TqSdk"""
        try:
            self.auth = TqAuth(self.tianqin_username, self.tianqin_password)

            if self.account_type == "kq":
                account = TqKq()
            elif self.account_type == "real":
                if not self.trading_account_config:
                    raise ValueError("实盘账户需要配置 trading_account")
                account = TqAccount(
                    self.trading_account_config.get("broker_name"),
                    self.trading_account_config.get("user_id"),
                    self.trading_account_config.get("password"),
                )
            elif self.account_type == "sim":
                account = TqSim()
            else:
                raise ValueError(f"未知账户类型: {self.account_type}")

            self.api = TqApi(account, auth=self.auth, web_gui=False)
            self.account = self.api.get_account()
            return True
        except Exception as e:
            print(f"TqSdk连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """断开连接"""
        if self.api:
            self.api.close()
            self.api = None
            self.account = None

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.api is not None and self.account is not None

    def get_account(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        if not self.account:
            return None

        user_id = None
        if self.account_type == "real" and self.trading_account_config:
            user_id = self.trading_account_config.get("user_id")

        return AccountInfo(
            account_id=self.account_id,
            broker_name=self.account.get("broker_name", ""),
            currency=self.account.get("currency", "CNY"),
            balance=float(self.account.get("balance", 0)),
            available=float(self.account.get("available", 0)),
            margin=float(self.account.get("margin", 0)),
            float_profit=float(self.account.get("float_profit", 0)),
            position_profit=float(self.account.get("position_profit", 0)),
            close_profit=float(self.account.get("close_profit", 0)),
            risk_ratio=float(self.account.get("risk_ratio", 0)),
            user_id=user_id,
        )

    def get_position(self) -> Dict[str, PositionInfo]:
        """获取持仓信息"""
        if not self.api:
            return {}

        positions = self.api.get_position()
        result = {}

        for symbol, pos in positions.items():
            if pos.pos_long == 0 and pos.pos_short == 0:
                continue

            result[symbol] = PositionInfo(
                symbol=symbol,
                exchange_id=symbol.split(".")[0] if "." in symbol else "",
                instrument_id=symbol.split(".")[1] if "." in symbol else "",
                pos_long=int(pos.pos_long),
                pos_short=int(pos.pos_short),
                open_price_long=float(pos.open_price_long) if not math.isnan(pos.open_price_long) else None,
                open_price_short=float(pos.open_price_short) if not math.isnan(pos.open_price_short) else None,
                float_profit=float(pos.float_profit),
                margin=float(pos.margin),
            )

        return result

    def get_trade(self) -> Dict[str, TradeInfo]:
        """获取成交记录"""
        if not self.api:
            return {}

        trades = self.api.get_trade()
        result = {}

        for trade_id, trade in trades.items():
            result[trade_id] = TradeInfo(
                trade_id=trade_id,
                order_id=trade.order_id,
                symbol=trade.exchange_id + "." + trade.instrument_id,
                exchange_id=trade.exchange_id,
                instrument_id=trade.instrument_id,
                direction=trade.direction,
                offset=trade.offset,
                price=float(trade.price),
                volume=int(trade.volume),
                trade_date_time=int(trade.trade_date_time),
            )

        return result

    def get_order(self) -> Dict[str, OrderInfo]:
        """获取委托单信息"""
        if not self.api:
            return {}

        orders = self.api.get_order()
        result = {}

        for order_id, order in orders.items():
            result[order_id] = OrderInfo(
                order_id=order_id,
                exchange_order_id=order.exchange_order_id,
                symbol=order.exchange_id + "." + order.instrument_id,
                exchange_id=order.exchange_id,
                instrument_id=order.instrument_id,
                direction=order.direction,
                offset=order.offset,
                volume_orign=int(order.volume_orign),
                volume_left=int(order.volume_left),
                limit_price=float(order.limit_price) if not math.isnan(order.limit_price) else None,
                price_type=order.price_type,
                status=order.status,
                insert_date_time=int(order.insert_date_time),
                last_msg=order.last_msg,
            )

        return result

    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
        price_type: str = "LIMIT",
    ) -> Optional[str]:
        """下单"""
        if not self.api:
            return None

        try:
            order = self.api.insert_order(
                symbol=symbol,
                direction=direction,
                offset=offset,
                volume=volume,
                limit_price=price,
            )

            return order.order_id if order else None
        except Exception as e:
            print(f"下单失败: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self.api:
            return False

        try:
            self.api.cancel_order(order_id)
            return True
        except Exception as e:
            print(f"撤单失败: {e}")
            return False

    def query_quotes(self, ins_class: List[str] = None, expired: bool = False) -> List[str]:
        """查询合约列表"""
        if not self.api:
            return []

        return self.api.query_quotes(ins_class=ins_class or ["FUTURE"], expired=expired)

    def subscribe_quote(self, symbols: List[str]) -> bool:
        """订阅行情"""
        if not self.api:
            return False

        try:
            for symbol in symbols:
                self.api.get_quote(symbol)
            return True
        except Exception as e:
            print(f"订阅行情失败: {e}")
            return False

    def wait_update(self) -> Any:
        """等待数据更新"""
        if not self.api:
            return None
        return self.api.wait_update()

    def is_changing(self, data: Any) -> bool:
        """检查数据是否变化"""
        if not self.api:
            return False
        return self.api.is_changing(data)

    def close(self) -> None:
        """关闭连接"""
        self.disconnect()
