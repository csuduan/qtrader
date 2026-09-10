"""
Trader 侧 IPC 响应模型

与 manager.api.schemas 字段保持一致，但独立定义，
避免 trader 层依赖 manager 层。经 IPC 序列化后两端 dict 兼容。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class StrategyPositionRes(BaseModel):
    """策略持仓响应"""

    symbol: str
    pos_long: int = 0
    pos_long_td: int = 0
    pos_long_yd: int = 0
    pos_short: int = 0
    pos_short_td: int = 0
    pos_short_yd: int = 0
    pos_net: int = 0
    hold_price_long: float = 0.0
    hold_price_short: float = 0.0
    position_profit: float = 0.0
    close_profit: float = 0.0


class StrategyRes(BaseModel):
    """策略信息响应"""

    strategy_id: str
    enabled: bool = False
    opening_paused: bool = False
    closing_paused: bool = False
    inited: bool = False
    symbol: str = ""
    config: dict | None = None
    base_params: list = []
    ext_params: list = []
    signal: dict | None = None
    pos_long: int = 0
    pos_short: int = 0
    positions: list[StrategyPositionRes] = []
    trading_status: str | None = None
    updated_at: datetime = Field(default_factory=datetime.now)


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
    stop_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    fee_rate: float | None = None
    trade_start_time: str | None = None
    trade_end_time: str | None = None
    force_exit_time: str | None = None
    one_trade_per_day: bool | None = None
    rsi_period: int | None = None
    rsi_n: int | None = None
    long_threshold: float | None = None
    short_threshold: float | None = None
    rsi_long_threshold: float | None = None
    rsi_short_threshold: float | None = None
    short_kline_period: int | None = None
    long_kline_period: int | None = None
    dir_threshold: float | None = None
    used_signal: bool | None = None

    model_config = {"populate_by_name": True}
