"""
抽象数据模型层
统一tqsdk和CTP的数据格式，作为所有外部接口的契约
"""
from datetime import datetime as DateTime
from enum import Enum
from typing import Optional, Dict, List, Any

from pydantic import BaseModel, Field


# ==================== 枚举定义 ====================

class Direction(str, Enum):
    """买卖方向"""
    BUY = "BUY"
    SELL = "SELL"


class PosDirection(str, Enum):
    """持仓方向"""
    LONG = "LONG"
    SHORT = "SHORT"
    NET = "NET"


class Offset(str, Enum):
    """开平类型"""
    NONE = ""
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSETODAY = "CLOSETODAY"
    CLOSEYESTERDAY = "CLOSEYESTERDAY"


class Status(str, Enum):
    """订单状态"""
    SUBMITTING = "SUBMITTING"
    NOTTRADED = "NOTTRADED"
    PARTTRADED = "PARTTRADED"
    ALLTRADED = "ALLTRADED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ProductType(str, Enum):
    """产品类型"""
    FUTURES = "FUTURES"
    OPTION = "OPTION"
    SPOT = "SPOT"
    INDEX = "INDEX"
    ETF = "ETF"


class OrderType(str, Enum):
    """订单类型"""
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    FOK = "FOK"
    FAK = "FAK"


class Exchange(str, Enum):
    """交易所"""
    # 中国期货交易所
    CFFEX = "CFFEX"
    SHFE = "SHFE"
    CZCE = "CZCE"
    DCE = "DCE"
    INE = "INE"
    GFEX = "GFEX"
    # 股票交易所
    SSE = "SSE"
    SZSE = "SZSE"
    # 特殊
    LOCAL = "LOCAL"
    NONE = ""


class Interval(str, Enum):
    """K线周期"""
    TICK = "tick"
    MINUTE = "1m"
    HOUR = "1h"
    DAILY = "d"
    WEEKLY = "w"


class StrategyType(str, Enum):
    """策略类型"""
    TICK_DRIVEN = "tick"
    BAR_DRIVEN = "bar"
    BOTH = "both"


# ==================== 核心数据模型 ====================

class TickData(BaseModel):
    """
    Tick行情数据

    必需字段：symbol, exchange, datetime, last_price
    可选字段：提供完整五档行情
    扩展字段：使用extras存放特定Gateway的数据
    """
    # 必需字段（所有Gateway必须提供）
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(..., description="交易所")
    datetime: DateTime = Field(..., description="行情时间")
    last_price: float = Field(..., description="最新价")

    # 可选字段（建议提供，但不强制）
    volume: Optional[float] = Field(None, description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")
    open_interest: Optional[float] = Field(None, description="持仓量")

    # 盘口数据（建议提供）
    bid_price_1: Optional[float] = Field(None, description="买一价")
    bid_volume_1: Optional[float] = Field(None, description="买一量")
    ask_price_1: Optional[float] = Field(None, description="卖一价")
    ask_volume_1: Optional[float] = Field(None, description="卖一量")

    # 日内数据
    open_price: Optional[float] = Field(None, description="开盘价")
    high_price: Optional[float] = Field(None, description="最高价")
    low_price: Optional[float] = Field(None, description="最低价")
    pre_close: Optional[float] = Field(None, description="昨收价")

    # 涨跌停
    limit_up: Optional[float] = Field(None, description="涨停价")
    limit_down: Optional[float] = Field(None, description="跌停价")

    # 扩展字段（存放Gateway特定数据）
    extras: Dict[str, Any] = Field(default_factory=dict, description="扩展数据")

    @property
    def std_symbol(self) -> str:
        """标准合约代码 (exchange.symbol)"""
        return f"{self.symbol}.{self.exchange.value}"


class BarData(BaseModel):
    """
    K线数据

    必需字段：symbol, exchange, interval, datetime, open_price, high_price, low_price, close_price
    """
    # 必需字段
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(..., description="交易所")
    interval: Interval = Field(..., description="K线周期")
    datetime: DateTime = Field(..., description="K线时间")

    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    close_price: float = Field(..., description="收盘价")

    # 可选字段
    volume: Optional[float] = Field(None, description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")
    open_interest: Optional[float] = Field(None, description="持仓量")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    @property
    def std_symbol(self) -> str:
        return f"{self.symbol}.{self.exchange.value}"


class OrderData(BaseModel):
    """
    订单数据

    必需字段：order_id, symbol, direction, offset, volume, status
    """
    # 必需字段
    order_id: str = Field(..., description="订单ID（系统内部唯一标识）")
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(default=Exchange.NONE, description="交易所")

    direction: Direction = Field(..., description="买卖方向")
    offset: Offset = Field(default=Offset.OPEN, description="开平类型")

    volume: int = Field(..., description="委托数量")
    traded: int = Field(default=0, description="已成交数量")

    price: Optional[float] = Field(None, description="委托价格（None=市价单）")
    price_type: OrderType = Field(default=OrderType.LIMIT, description="订单类型")

    status: Status = Field(default=Status.SUBMITTING, description="订单状态")
    status_msg: str = Field(default="", description="状态消息")

    # 可选字段
    gateway_order_id: Optional[str] = Field(None, description="网关订单ID（如CTP的OrderSysID）")
    trading_day: Optional[str] = Field(None, description="交易日")

    insert_time: Optional[DateTime] = Field(None, description="下单时间")
    update_time: Optional[DateTime] = Field(None, description="最后更新时间")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    @property
    def volume_left(self) -> int:
        """剩余数量"""
        return self.volume - self.traded

    def is_active(self) -> bool:
        """是否为活动订单"""
        return self.status in [Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED]


class TradeData(BaseModel):
    """
    成交数据

    必需字段：trade_id, order_id, symbol, direction, offset, price, volume
    """
    # 必需字段
    trade_id: str = Field(..., description="成交ID")
    order_id: str = Field(..., description="关联订单ID")
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(default=Exchange.NONE, description="交易所")

    direction: Direction = Field(..., description="买卖方向")
    offset: Offset = Field(default=Offset.OPEN, description="开平类型")

    price: float = Field(..., description="成交价格")
    volume: int = Field(..., description="成交数量")

    # 可选字段
    trading_day: Optional[str] = Field(None, description="交易日")
    trade_time: Optional[DateTime] = Field(None, description="成交时间")
    commission: Optional[float] = Field(None, description="手续费")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)


class PositionData(BaseModel):
    """
    持仓数据

    必需字段：symbol, exchange, direction, volume
    """
    # 必需字段
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(..., description="交易所")
    direction: PosDirection = Field(..., description="持仓方向")

    volume: int = Field(..., description="持仓数量")

    # 可选字段
    yd_volume: Optional[int] = Field(None, description="昨仓")
    td_volume: Optional[int] = Field(None, description="今仓")
    frozen: Optional[int] = Field(None, description="冻结数量")
    available: Optional[int] = Field(None, description="可平数量")

    avg_price: Optional[float] = Field(None, description="持仓均价")
    hold_cost: Optional[float] = Field(None, description="持仓成本")
    hold_profit: Optional[float] = Field(None, description="持仓盈亏")
    close_profit: Optional[float] = Field(None, description="平仓盈亏")

    margin: Optional[float] = Field(None, description="保证金占用")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    @property
    def position_id(self) -> str:
        """持仓唯一标识"""
        return f"{self.symbol}.{self.exchange.value}.{self.direction.value}"


class AccountData(BaseModel):
    """
    账户数据

    必需字段：account_id, balance, available
    """
    # 必需字段
    account_id: str = Field(..., description="账户ID")
    balance: float = Field(..., description="账户余额")
    available: float = Field(..., description="可用资金")

    # 可选字段
    frozen: Optional[float] = Field(None, description="冻结资金")
    margin: Optional[float] = Field(None, description="保证金占用")

    pre_balance: Optional[float] = Field(None, description="昨结余额")
    hold_profit: Optional[float] = Field(None, description="持仓盈亏")
    close_profit: Optional[float] = Field(None, description="平仓盈亏")
    float_profit: Optional[float] = Field(None, description="浮动盈亏")


    risk_ratio: Optional[float] = Field(None, description="风险度")

    update_time: Optional[DateTime] = Field(None, description="更新时间")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    broker_name: Optional[str] = Field(None, description="经纪商名称")
    currency: Optional[str] = Field(None, description="交易货币")


class ContractData(BaseModel):
    """
    合约数据

    必需字段：symbol, exchange, name, product_type
    """
    # 必需字段
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(..., description="交易所")
    name: str = Field(..., description="合约名称")
    product_type: ProductType = Field(ProductType.FUTURES, description="产品类型")

    # 可选字段
    multiple: Optional[int] = Field(None, description="合约乘数")
    pricetick: Optional[float] = Field(None, description="最小价格变动")

    min_volume: Optional[int] = Field(None, description="最小下单量")

    # 期权相关
    option_strike: Optional[float] = Field(None, description="期权行权价")
    option_underlying: Optional[str] = Field(None, description="标的合约")
    option_type: Optional[str] = Field(None, description="期权类型 CALL/PUT")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    @property
    def std_symbol(self) -> str:
        return f"{self.symbol}.{self.exchange.value}"


# ==================== 请求模型 ====================

class SubscribeRequest(BaseModel):
    """订阅请求"""
    symbols: List[str] = Field(..., description="合约代码列表")


class OrderRequest(BaseModel):
    """下单请求"""
    symbol: str = Field(..., description="合约代码")
    exchange: Exchange = Field(default=Exchange.NONE, description="交易所")

    direction: Direction = Field(..., description="买卖方向")
    offset: Offset = Field(default=Offset.OPEN, description="开平类型")

    volume: int = Field(..., ge=1, description="数量")
    price: Optional[float] = Field(None, description="价格（None=市价）")
    price_type: OrderType = Field(default=OrderType.LIMIT, description="订单类型")


class CancelRequest(BaseModel):
    """撤单请求"""
    order_id: str = Field(..., description="订单ID")

# ==================== 常量定义 ====================

ACTIVE_STATUSES = {Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED}
