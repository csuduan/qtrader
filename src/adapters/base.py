"""
交易接口抽象层
支持TqSdk和CTP等不同交易接口
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Direction(str, Enum):
    """买卖方向"""
    BUY = "BUY"
    SELL = "SELL"


class Offset(str, Enum):
    """开平标志"""
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSETODAY = "CLOSETODAY"


class OrderStatus(str, Enum):
    """委托单状态"""
    ALIVE = "ALIVE"          # 活跃
    FINISHED = "FINISHED"    # 已完成
    REJECTED = "REJECTED"    # 已拒绝


@dataclass
class AccountInfo:
    """账户信息"""
    account_id: str
    broker_name: str
    currency: str
    balance: float
    available: float
    margin: float
    float_profit: float
    position_profit: float
    close_profit: float
    risk_ratio: float
    user_id: Optional[str] = None


@dataclass
class PositionInfo:
    """持仓信息"""
    symbol: str
    exchange_id: str
    instrument_id: str
    pos_long: int
    pos_short: int
    open_price_long: Optional[float]
    open_price_short: Optional[float]
    float_profit: float
    margin: float


@dataclass
class TradeInfo:
    """成交信息"""
    trade_id: str
    order_id: Optional[str]
    symbol: str
    exchange_id: str
    instrument_id: str
    direction: str
    offset: str
    price: float
    volume: int
    trade_date_time: int


@dataclass
class OrderInfo:
    """委托单信息"""
    order_id: str
    exchange_order_id: Optional[str]
    symbol: str
    exchange_id: str
    instrument_id: str
    direction: str
    offset: str
    volume_orign: int
    volume_left: int
    limit_price: Optional[float]
    price_type: str
    status: str
    insert_date_time: int
    last_msg: Optional[str]


@dataclass
class QuoteInfo:
    """行情信息"""
    exchange_id: str
    instrument_id: str
    symbol: str
    last_price: float
    bid_price1: float
    ask_price1: float
    volume: int
    open_interest: int


class TradingAdapter(ABC):
    """交易接口适配器抽象类"""

    @abstractmethod
    def connect(self) -> bool:
        """连接到交易接口"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """检查是否已连接"""
        pass

    @abstractmethod
    def get_account(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        pass

    @abstractmethod
    def get_position(self) -> Dict[str, PositionInfo]:
        """获取持仓信息，返回 {symbol: PositionInfo}"""
        pass

    @abstractmethod
    def get_trade(self) -> Dict[str, TradeInfo]:
        """获取成交记录，返回 {trade_id: TradeInfo}"""
        pass

    @abstractmethod
    def get_order(self) -> Dict[str, OrderInfo]:
        """获取委托单信息，返回 {order_id: OrderInfo}"""
        pass

    @abstractmethod
    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
        price_type: str = "LIMIT"
    ) -> Optional[str]:
        """下单，返回order_id"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass

    @abstractmethod
    def query_quotes(self, ins_class: List[str] = None, expired: bool = False) -> List[str]:
        """查询合约列表，返回 [symbol, ...]"""
        pass

    @abstractmethod
    def subscribe_quote(self, symbols: List[str]) -> bool:
        """订阅行情"""
        pass

    @abstractmethod
    def wait_update(self) -> Any:
        """等待数据更新"""
        pass

    @abstractmethod
    def is_changing(self, data: Any) -> bool:
        """检查数据是否变化"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭连接"""
        pass
