"""
数据库持久化对象模型定义
使用SQLAlchemy ORM（Mapped/mapped_column 声明风格）定义所有数据表结构
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """ORM基类"""

    pass


class AccountPo(Base):
    """账户信息表"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    broker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CNY")
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    available: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    margin: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    float_profit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    position_profit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    close_profit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    risk_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    positions = relationship("PositionPo", back_populates="account", cascade="all, delete-orphan")
    trades = relationship("TradePo", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("OrderPo", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<AccountPo(account_id={self.account_id}, balance={self.balance})>"


class PositionPo(Base):
    """持仓信息表 - 支持账户持仓和策略持仓"""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("accounts.account_id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    multiple: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 策略ID（为空表示账户持仓，不为空表示策略持仓）
    strategy_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # 多头持仓
    pos_long_td: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 多头今仓
    pos_long_yd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 多头昨仓

    # 空头持仓
    pos_short_td: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 空头今仓
    pos_short_yd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 空头昨仓

    # 持仓均价
    hold_price_long: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), default=0
    )  # 多头持仓均价
    hold_price_short: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), default=0
    )  # 空头持仓均价

    # 盈亏
    hold_profit_long: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), default=0
    )  # 多头持仓盈亏
    hold_profit_short: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), default=0
    )  # 空头持仓盈亏
    close_profit_long: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), default=0
    )  # 多头平仓盈亏
    close_profit_short: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), default=0
    )  # 空头平仓盈亏

    # 保证金
    margin_long: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)  # 多头保证金
    margin_short: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)  # 空头保证金

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        UniqueConstraint("account_id", "strategy_id", "symbol", name="uq_account_strategy_symbol"),
        # strategy_id 为 NULL 时上述唯一约束不生效（PG 中 NULL≠NULL），补充账户级部分唯一索引
        Index(
            "uq_position_account_symbol",
            "account_id",
            "symbol",
            unique=True,
            postgresql_where=text("strategy_id IS NULL"),
            sqlite_where=text("strategy_id IS NULL"),
        ),
    )

    account = relationship("AccountPo", back_populates="positions")

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

    def __repr__(self) -> str:
        if self.strategy_id:
            return f"<PositionPo(strategy={self.strategy_id}, symbol={self.symbol}, long={self.pos_long}, short={self.pos_short})>"
        return f"<PositionPo(account={self.account_id}, symbol={self.symbol}, long={self.pos_long}, short={self.pos_short})>"


class TradePo(Base):
    """成交记录表"""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("accounts.account_id"), nullable=False, index=True
    )
    trade_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    offset: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    trade_date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # 报单价格（用于计算滑点）
    order_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)

    account = relationship("AccountPo", back_populates="trades")

    def __repr__(self) -> str:
        return f"<TradePo(trade_id={self.trade_id}, symbol={self.symbol}, direction={self.direction}, volume={self.volume})>"


class OrderPo(Base):
    """委托单记录表"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("accounts.account_id"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    offset: Mapped[str] = mapped_column(String(20), nullable=False)
    volume_orign: Mapped[int] = mapped_column(Integer, nullable=False)
    volume_left: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    price_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    insert_date_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    update_date_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    account = relationship("AccountPo", back_populates="orders")

    def __repr__(self) -> str:
        return f"<OrderPo(order_id={self.order_id}, symbol={self.symbol}, status={self.status}, volume_left={self.volume_left})>"


class SwitchPosImportPo(Base):
    """换仓文件导入记录表（指令换仓与目标仓位换仓共用，仅记录导入审计信息）"""

    __tablename__ = "switchPos_import"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("account_id", "file_name", name="uq_switchpos_account_file"),
    )

    def __repr__(self) -> str:
        return f"<SwitchPosImportPo(account_id={self.account_id}, file_name={self.file_name})>"


class RotationInstructionPo(Base):
    """换仓指令表"""

    __tablename__ = "rotation_instructions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    offset: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)  # 目标手数
    filled_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 已成交手数
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=0)
    order_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trading_date: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING, RUNNING, COMPLETED, FAILED
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_volume: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 剩余手数=目标-已成交
    current_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    order_placed_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_attempt_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # 来源：文件名 或 '手动添加'
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<RotationInstructionPo(account_id={self.account_id}, strategy_id={self.strategy_id}, symbol={self.symbol}, direction={self.direction}, volume={self.volume}, filled={self.filled_volume}, enabled={self.enabled})>"


class JobPo(Base):
    """定时任务配置表"""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(50), primary_key=True, nullable=False)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_group: Mapped[str] = mapped_column(String(50), nullable=False, default="default")
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    job_method: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    last_trigger_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_trigger_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<JobPo(job_id={self.job_id}, job_name={self.job_name}, enabled={self.enabled})>"


class QuotePo(Base):
    """行情数据表"""

    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), default=0)
    bid_price1: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), default=0)
    ask_price1: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), default=0)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    open_interest: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<QuotePo(instrument_id={self.instrument_id}, last_price={self.last_price})>"


class AlarmPo(Base):
    """告警信息表"""

    __tablename__ = "alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    alarm_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="exception", index=True
    )  # notification/exception
    indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 1min/5min/1hour
    alarm_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    alarm_time: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNCONFIRMED", index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True)

    def __repr__(self) -> str:
        return (
            f"<AlarmPo(account_id={self.account_id}, type={self.alarm_type}, title={self.title})>"
        )


class SystemParamPo(Base):
    """系统参数表"""

    __tablename__ = "system_params"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )  # NULL=全局参数
    param_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    param_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    param_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (UniqueConstraint("account_id", "param_key", name="uq_sysparam_account_key"),)

    def __repr__(self) -> str:
        return f"<SystemParamPo(key={self.param_key}, type={self.param_type}, value={self.param_value})>"


class ContractPo(Base):
    """合约信息表"""

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    exchange_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_type: Mapped[str] = mapped_column(String(20), nullable=False, default="FUTURES")
    volume_multiple: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_tick: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0.01)
    min_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    min_open_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    option_strike: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    option_underlying: Mapped[str | None] = mapped_column(String(80), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    update_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    # 数据来源：tq（天勤）、ctp（中泰CTP）等
    data_source: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # 是否活跃合约（当日可交易）
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # 是否主力合约（随每日合约刷新打标）
    is_main: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<ContractPo(symbol={self.symbol}, exchange_id={self.exchange_id}, update_date={self.update_date}, data_source={self.data_source})>"


class UserPo(Base):
    """用户信息表"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)  # 密码哈希
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="guest"
    )  # admin, trader, guest
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<UserPo(user_id={self.user_id}, role={self.role}, is_active={self.is_active})>"


class AccountHistoryPo(Base):
    """账户每日结算权益历史表"""

    __tablename__ = "account_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    settle_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # 结算日期

    balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)  # 结算权益
    available: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )  # 可用资金
    pre_balance: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 昨日权益
    static_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), nullable=True
    )  # 静态权益
    deposit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 入金
    withdraw: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 出金
    close_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 平仓盈亏
    hold_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 持仓盈亏
    margin: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 保证金占用
    risk_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)  # 风险度

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("account_id", "settle_date", name="uq_account_history_account_date"),
    )

    def __repr__(self) -> str:
        return f"<AccountHistoryPo(account_id={self.account_id}, settle_date={self.settle_date}, balance={self.balance})>"


class PositionHistoryPo(Base):
    """账户每日结算持仓历史表"""

    __tablename__ = "positions_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    settle_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # 结算日期
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)

    pos_long: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 多头持仓(今+昨)
    pos_short: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 空头持仓(今+昨)

    hold_price_long: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), default=0
    )  # 多头持仓均价
    hold_price_short: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), default=0
    )  # 空头持仓均价

    hold_profit_long: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), default=0
    )  # 多头持仓盈亏
    hold_profit_short: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), default=0
    )  # 空头持仓盈亏

    margin_long: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)  # 多头保证金
    margin_short: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)  # 空头保证金

    last_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)  # 结算价

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "settle_date", "symbol", name="uq_positions_history_account_date_symbol"
        ),
    )

    def __repr__(self) -> str:
        return f"<PositionHistoryPo(account_id={self.account_id}, settle_date={self.settle_date}, symbol={self.symbol}, long={self.pos_long}, short={self.pos_short})>"


class BarHistoryPo(Base):
    """历史K线数据表（Manager盘后统一更新）"""

    __tablename__ = "bars_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)  # 合约代码（如IM2609）
    interval: Mapped[str] = mapped_column(String(10), nullable=False)  # K线周期（如M1）
    bar_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # bar开始时间
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # 交易日

    open_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), default=0)
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)

    source: Mapped[str | None] = mapped_column(String(20), default="")  # 数据来源（rq/tq）
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        UniqueConstraint(
            "symbol", "interval", "bar_time", name="uq_bars_history_symbol_interval_time"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BarHistoryPo(symbol={self.symbol}, interval={self.interval}, "
            f"bar_time={self.bar_time}, close={self.close_price})>"
        )


class BarTodayPo(Base):
    """当日K线数据表（各Trader盘中实时写入，多账户并存）"""

    __tablename__ = "bars_today"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # bar开始时间
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # 交易日
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # 写入账户

    open_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), default=0)
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=0)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "interval",
            "bar_time",
            "account_id",
            name="uq_bars_today_symbol_interval_time_account",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BarTodayPo(symbol={self.symbol}, interval={self.interval}, "
            f"bar_time={self.bar_time}, account={self.account_id}, close={self.close_price})>"
        )
