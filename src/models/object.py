"""
抽象数据模型层
统一tqsdk和CTP的数据格式，作为所有外部接口的契约
"""

from datetime import datetime as DateTime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.util import b

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


class TraderState(str, Enum):
    """Trader Proxy 状态"""

    STOPPED = "stopped"  # 已停止
    CONNECTING = "connecting"  # 连接中
    CONNECTED = "connected"  # 已连接


class OrderStatus(str, Enum):
    """订单状态"""

    PENDING = "PENDING"
    FINISHED = "FINISHED"
    REJECTED = "REJECTED"


class ProductType(str, Enum):
    """产品类型"""

    FUTURES = "FUTURES"
    OPTION = "OPTION"
    SPOT = "SPOT"
    INDEX = "INDEX"
    ETF = "ETF"
    SPREAD = "SPREAD"


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
    # 其他交易所
    NONE = ""

    @classmethod
    def from_str(cls, value: str) -> "Exchange":
        """从字符串创建枚举实例"""
        try:
            return cls(value)
        except ValueError:
            return cls.NONE


class Interval(str, Enum):
    """K线周期"""

    TICK = "tick"
    MINUTE = "M1"
    MINUTE_5 = "M5"
    MINUTE_15 = "M15"
    MINUTE_30 = "M30"
    HOUR = "H1"
    DAILY = "D1"


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
    last_price: Optional[float] = Field(..., description="最新价")

    # 可选字段（建议提供，但不强制）
    volume: Optional[float] = Field(None, description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")
    open_interest: Optional[float] = Field(None, description="持仓量")

    # 盘口数据（建议提供）
    bid_price1: Optional[float] = Field(None, description="买一价")
    bid_volume1: Optional[float] = Field(None, description="买一量")
    ask_price1: Optional[float] = Field(None, description="卖一价")
    ask_volume1: Optional[float] = Field(None, description="卖一量")

    # 五档行情扩展
    bid_price2: Optional[float] = Field(None, description="买二价")
    bid_volume2: Optional[float] = Field(None, description="买二量")
    ask_price2: Optional[float] = Field(None, description="卖二价")
    ask_volume2: Optional[float] = Field(None, description="卖二量")

    bid_price3: Optional[float] = Field(None, description="买三价")
    bid_volume3: Optional[float] = Field(None, description="买三量")
    ask_price3: Optional[float] = Field(None, description="卖三价")
    ask_volume3: Optional[float] = Field(None, description="卖三量")

    bid_price4: Optional[float] = Field(None, description="买四价")
    bid_volume4: Optional[float] = Field(None, description="买四量")
    ask_price4: Optional[float] = Field(None, description="卖四价")
    ask_volume4: Optional[float] = Field(None, description="卖四量")

    bid_price5: Optional[float] = Field(None, description="买五价")
    bid_volume5: Optional[float] = Field(None, description="买五量")
    ask_price5: Optional[float] = Field(None, description="卖五价")
    ask_volume5: Optional[float] = Field(None, description="卖五量")

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
    interval: str = Field(..., description="K线周期")
    datetime: DateTime = Field(..., description="K线时间")

    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    close_price: float = Field(..., description="收盘价")

    # 可选字段
    volume: Optional[float] = Field(None, description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")
    open_interest: Optional[float] = Field(None, description="持仓量")
    type: str = Field(default="real", description="K线类型")
    update_time: Optional[DateTime] = Field(None, description="最后更新时间")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    @property
    def std_symbol(self) -> str:
        return f"{self.symbol}"

    @property
    def id(self) -> str:
        return f"{self.symbol}-{self.interval}"

    def __str__(self) -> str:
        return f"{self.symbol}-{self.interval} {self.datetime} open:{self.open_price} high:{self.high_price} low:{self.low_price} close:{self.close_price} volume:{self.volume} update:{self.update_time}"


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
    traded_price: Optional[float] = Field(None, description="已成交价格")

    price: Optional[float] = Field(None, description="委托价格（None=市价单）")
    price_type: OrderType = Field(default=OrderType.LIMIT, description="订单类型")

    status: OrderStatus = Field(default=OrderStatus.PENDING, description="订单状态")
    status_msg: str = Field(default="", description="状态消息")

    # 账号标识（多账号支持）
    account_id: str = Field(..., description="账户ID")

    # 可选字段
    gateway_order_id: Optional[str] = Field(None, description="网关订单ID（如CTP的OrderSysID）")
    trading_day: Optional[str] = Field(None, description="交易日")

    insert_time: Optional[DateTime] = Field(None, description="下单时间")
    update_time: Optional[DateTime] = Field(None, description="最后更新时间")
    canceled: bool = Field(default=False, description="是否已取消")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)

    @property
    def volume_left(self) -> int:
        """剩余数量"""
        return self.volume - self.traded

    def is_active(self) -> bool:
        """是否为活动订单"""
        return self.status == OrderStatus.PENDING

    def can_cancel(self) -> bool:
        return self.status == OrderStatus.PENDING and not self.canceled


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

    # 账号标识（多账号支持）
    account_id: str = Field(..., description="账户ID")

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
    multiple: int = Field(1, description="合约乘数")

    pos: int = Field(..., description="净持仓数量")
    pos_long: int = Field(..., description="多头持仓数量")
    pos_short: int = Field(..., description="空头持仓数量")

    pos_long_yd: Optional[int] = Field(None, description="昨仓多头持仓数量")
    pos_short_yd: Optional[int] = Field(None, description="昨仓空头持仓数量")
    pos_long_td: Optional[int] = Field(None, description="今仓多头持仓数量")
    pos_short_td: Optional[int] = Field(None, description="今仓空头持仓数量")

    # 成本
    hold_price_long: Optional[float] = Field(0, description="多头持仓均价")
    hold_price_short: Optional[float] = Field(0, description="空头持仓均价")
    hold_cost_long: Optional[float] = Field(0, description="多头持仓成本")
    hold_cost_short: Optional[float] = Field(0, description="空头持仓成本")
    # 盈亏
    hold_profit_long: Optional[float] = Field(0, description="多头持仓盈亏(盯日)")
    hold_profit_short: Optional[float] = Field(0, description="空头持仓盈亏(盯日)")
    close_profit_long: Optional[float] = Field(0, description="多头平仓盈亏(盯日)")
    close_profit_short: Optional[float] = Field(0, description="空头平仓盈亏(盯日)")

    margin_long: Optional[float] = Field(0, description="多头持仓保证金占用")
    margin_short: Optional[float] = Field(0, description="空头持仓保证金占用")

    # 账号标识（多账号支持）
    account_id: Optional[str] = Field(None, description="账户ID")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)


class AccountData(BaseModel):
    """
    账户数据

    必需字段：account_id, balance, available
    """

    # 必需字段
    account_id: str = Field(..., description="账户ID")
    balance: float = Field(0, description="账户余额")
    available: float = Field(0, description="可用资金")

    # 可选字段
    frozen: Optional[float] = Field(None, description="冻结资金")
    margin: Optional[float] = Field(None, description="保证金占用")

    pre_balance: Optional[float] = Field(None, description="昨结余额")
    hold_profit: Optional[float] = Field(None, description="持仓盈亏(盯日)")
    close_profit: Optional[float] = Field(None, description="平仓盈亏(盯日)")
    float_profit: Optional[float] = Field(None, description="浮动盈亏")

    risk_ratio: Optional[float] = Field(None, description="风险度")

    update_time: Optional[DateTime] = Field(None, description="更新时间")

    # 扩展字段
    extras: Dict[str, Any] = Field(default_factory=dict)
    broker_type: Optional[str] = Field(None, description="经纪商类型")
    broker_name: Optional[str] = Field(None, description="经纪商名称")
    currency: Optional[str] = Field(None, description="交易货币")
    user_id: Optional[str] = Field(None, description="用户ID")
    trade_paused: bool = False  # 是否暂停交易
    gateway_connected: bool = False  # 网关是否已连接
    risk_status: dict = Field(default_factory=dict, description="风控状态")

    # 账户状态
    status: Optional[TraderState] = Field(TraderState.STOPPED, description="交易状态")


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
    expire_date: Optional[str] = Field(None, description="到期日期")

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
    slip: Optional[int] = Field(0, description="滑点")


class CancelRequest(BaseModel):
    """撤单请求"""

    order_id: str = Field(..., description="订单ID")


# ==================== 常量定义 ====================

ACTIVE_STATUSES = {OrderStatus.PENDING}


class OrderCmdFinishReason(str, Enum):
    """报单指令结束原因"""

    ALL_COMPLETED = "ALL_COMPLETED"  # 全部完成
    CANCELLED = "CANCELLED"  # 已取消
    TIMEOUT = "TIMEOUT"  # 超时
    ORDER_ERROR = "ORDER_ERROR"  # 报单异常


class AlarmData(BaseModel):
    """告警数据传输对象"""

    account_id: str = Field(..., description="账户ID")
    alarm_date: str = Field(..., description="告警日期 YYYY-MM-DD")
    alarm_time: str = Field(..., description="告警时间 HH:MM:SS")
    source: str = Field(..., description="告警来源 TRADER/MANAGER")
    title: str = Field(..., description="告警标题")
    detail: Optional[str] = Field(None, description="告警详情")
    status: str = Field(default="UNCONFIRMED", description="告警状态")
    created_at: DateTime = Field(default_factory=DateTime.now, description="创建时间")


class StrategyPosition(BaseModel):
    """
    策略仓位数据类
    支持多合约、区分今昨仓、锁仓模式
    """

    strategy_id: str = Field(..., description="策略ID")
    symbol: str = Field(..., description="合约代码")
    account_id: Optional[str] = Field(None, description="账户ID")

    # 多头持仓
    pos_long_td: int = Field(default=0, description="多头今仓")
    pos_long_yd: int = Field(default=0, description="多头昨仓")

    # 空头持仓
    pos_short_td: int = Field(default=0, description="空头今仓")
    pos_short_yd: int = Field(default=0, description="空头昨仓")

    # 持仓均价
    avg_price_long: float = Field(default=0.0, description="多头持仓均价")
    avg_price_short: float = Field(default=0.0, description="空头持仓均价")

    # 盈亏
    position_profit: float = Field(default=0.0, description="持仓盈亏")
    close_profit: float = Field(default=0.0, description="平仓盈亏")

    # 时间戳
    created_at: Optional[DateTime] = Field(default=None, description="创建时间")
    updated_at: Optional[DateTime] = Field(default=None, description="更新时间")

    @property
    def pos_long(self) -> int:
        """多头总持仓"""
        return self.pos_long_td + self.pos_long_yd

    @property
    def pos_short(self) -> int:
        """空头总持仓"""
        return self.pos_short_td + self.pos_short_yd

    @property
    def pos_net(self) -> int:
        """净持仓"""
        return self.pos_long - self.pos_short

    @property
    def total_pos(self) -> int:
        """总持仓（双向合计）"""
        return self.pos_long + self.pos_short

    def update_from_trade(
        self, direction: Direction, offset: Offset, volume: int, price: float
    ) -> None:
        """
        根据成交更新持仓

        Args:
            direction: 买卖方向
            offset: 开平类型
            volume: 成交数量
            price: 成交价格
        """
        if offset == Offset.OPEN:
            # 开仓：增加对应方向的今仓
            if direction == Direction.BUY:
                # 开多：增加多头今仓
                cost = self.pos_long * self.avg_price_long + volume * price
                self.pos_long_td += volume
                self.avg_price_long = cost / self.pos_long if self.pos_long > 0 else 0
            else:
                # 开空：增加空头今仓
                cost = self.pos_short * self.avg_price_short + volume * price
                self.pos_short_td += volume
                self.avg_price_short = cost / self.pos_short if self.pos_short > 0 else 0
        else:
            # 平仓：减少对应方向的持仓
            if direction == Direction.SELL:
                # 平多：优先平昨仓，再平今仓
                close_yd = min(self.pos_long_yd, volume)
                close_td = min(self.pos_long_td, volume - close_yd)
                self.pos_long_yd -= close_yd
                self.pos_long_td -= close_td

                # 计算平仓盈亏
                if self.pos_long > 0:
                    profit = (price - self.avg_price_long) * volume
                    self.close_profit += profit
            else:
                # 平空：优先平昨仓，再平今仓
                close_yd = min(self.pos_short_yd, volume)
                close_td = min(self.pos_short_td, volume - close_yd)
                self.pos_short_yd -= close_yd
                self.pos_short_td -= close_td

                # 计算平仓盈亏
                if self.pos_short > 0:
                    profit = (self.avg_price_short - price) * volume
                    self.close_profit += profit

        self.updated_at = DateTime.now()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "account_id": self.account_id,
            "pos_long": self.pos_long,
            "pos_long_td": self.pos_long_td,
            "pos_long_yd": self.pos_long_yd,
            "pos_short": self.pos_short,
            "pos_short_td": self.pos_short_td,
            "pos_short_yd": self.pos_short_yd,
            "pos_net": self.pos_net,
            "avg_price_long": self.avg_price_long,
            "avg_price_short": self.avg_price_short,
            "position_profit": self.position_profit,
            "close_profit": self.close_profit,
        }

    def __repr__(self) -> str:
        return (
            f"<StrategyPosition({self.strategy_id}, {self.symbol}, "
            f"long={self.pos_long}({self.pos_long_td}/{self.pos_long_yd}), "
            f"short={self.pos_short}({self.pos_short_td}/{self.pos_short_yd}), "
            f"net={self.pos_net})>"
        )
