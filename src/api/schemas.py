"""
API数据模型定义
使用Pydantic定义请求和响应模型
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AccountRes(BaseModel):
    """账户信息响应"""
    account_id: str
    broker_name: Optional[str] = None
    currency: str = "CNY"
    balance: float
    available: float
    margin: float
    float_profit: float
    position_profit: float
    close_profit: float
    risk_ratio: float
    updated_at: datetime
    user_id: Optional[str] = None

    class Config:
        from_attributes = True


class PositionRes(BaseModel):
    """持仓信息响应"""
    id: int
    account_id: str
    exchange_id: Optional[str] = None
    instrument_id: Optional[str] = None
    symbol: str
    pos_long: int
    pos_short: int
    open_price_long: Optional[float] = 0
    open_price_short: Optional[float] = 0
    float_profit: float
    margin: float
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeRes(BaseModel):
    """成交记录响应"""
    id: int
    account_id: str
    trade_id: str
    order_id: Optional[str] = None
    symbol: str
    direction: str
    offset: str
    price: float
    volume: int
    trade_date_time: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class OrderRes(BaseModel):
    """委托单响应"""
    id: int
    account_id: str
    order_id: str
    exchange_order_id: Optional[str] = None
    symbol: str
    direction: str
    offset: str
    volume_orign: int
    volume_left: int
    limit_price: Optional[float] = None
    price_type: str
    status: str
    insert_date_time: datetime
    last_msg: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QuoteRes(BaseModel):
    """行情信息响应"""
    symbol: str
    last_price: float
    bid_price1: float
    ask_price1: float
    volume: int
    open_interest: int
    datetime: int


class ManualOrderReq(BaseModel):
    """手动报单请求"""
    symbol: str = Field(..., description="合约代码，如 SHFE.rb2505")
    direction: str = Field(..., description="买卖方向: BUY/SELL")
    offset: str = Field(..., description="开平标志: OPEN/CLOSE/CLOSETODAY")
    volume: int = Field(..., gt=0, description="手数，必须大于0")
    price: Optional[float] = Field(0, description="价格")


class SystemStatusRes(BaseModel):
    """系统状态响应"""
    connected: bool
    paused: bool
    account_id: str
    daily_orders: int
    daily_cancels: int


class ConnectReq(BaseModel):
    """连接请求"""
    username: Optional[str] = None
    password: Optional[str] = None


class Message(BaseModel):
    """WebSocket消息"""
    type: str
    data: dict
    timestamp: str


class AlarmRes(BaseModel):
    """告警信息响应"""
    id: int
    account_id: str
    alarm_date: str
    alarm_time: str
    source: str
    title: str
    detail: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AlarmStatsRes(BaseModel):
    """告警统计响应"""
    today_total: int
    unconfirmed: int
    last_hour: int
    last_five_minutes: int


class SystemParamRes(BaseModel):
    """系统参数响应"""
    id: int
    param_key: str
    param_value: str | None
    param_type: str
    description: str | None
    group: str
    updated_at: datetime

    class Config:
        from_attributes = True


class SystemParamUpdateReq(BaseModel):
    """系统参数更新请求"""
    param_key: str
    param_value: str

class StrategyRes(BaseModel):
    """策略信息响应"""
    strategy_id: str
    active: bool
    config: "StrategyConfig"

    model_config = {"populate_by_name": True}


class StrategyConfig(BaseModel):
    """策略配置"""
    enabled: bool
    strategy_type: str
    symbol: str
    exchange: str
    volume_per_trade: int
    max_position: int
    bar: str | None = None
    params_file: str | None = None
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    fee_rate: float | None = None
    trade_start_time: str | None = None
    trade_end_time: str | None = None
    force_exit_time: str | None = None
    one_trade_per_day: bool | None = None
    # RSI策略参数
    rsi_period: int | None = None
    rsi_long_threshold: float | None = None
    rsi_short_threshold: float | None = None
    short_kline_period: int | None = None
    long_kline_period: int | None = None
    dir_threshold: float | None = None
    used_signal: bool | None = None

    model_config = {"populate_by_name": True}
