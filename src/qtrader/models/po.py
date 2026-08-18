"""
数据库持久化对象模型定义
使用SQLAlchemy ORM定义所有数据表结构
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """ORM基类"""

    pass


class AccountPo(Base):
    """账户信息表"""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), unique=True, nullable=False, index=True)
    broker_name = Column(String(100), nullable=True)
    currency = Column(String(10), nullable=False, default="CNY")
    balance = Column(Numeric(20, 2), nullable=False, default=0)
    available = Column(Numeric(20, 2), nullable=False, default=0)
    margin = Column(Numeric(20, 2), nullable=False, default=0)
    float_profit = Column(Numeric(20, 2), nullable=False, default=0)
    position_profit = Column(Numeric(20, 2), nullable=False, default=0)
    close_profit = Column(Numeric(20, 2), nullable=False, default=0)
    risk_ratio = Column(Numeric(10, 4), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    positions = relationship("PositionPo", back_populates="account", cascade="all, delete-orphan")
    trades = relationship("TradePo", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("OrderPo", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AccountPo(account_id={self.account_id}, balance={self.balance})>"


class PositionPo(Base):
    """持仓信息表 - 支持账户持仓和策略持仓"""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), ForeignKey("accounts.account_id"), nullable=False, index=True)
    symbol = Column(String(80), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    multiple = Column(Integer, nullable=False, default=0)
    # 策略ID（为空表示账户持仓，不为空表示策略持仓）
    strategy_id = Column(String(100), nullable=True, index=True)

    # 多头持仓
    pos_long_td = Column(Integer, nullable=False, default=0)  # 多头今仓
    pos_long_yd = Column(Integer, nullable=False, default=0)  # 多头昨仓

    # 空头持仓
    pos_short_td = Column(Integer, nullable=False, default=0)  # 空头今仓
    pos_short_yd = Column(Integer, nullable=False, default=0)  # 空头昨仓

    # 持仓均价
    hold_price_long = Column(Numeric(20, 4), default=0)  # 多头持仓均价
    hold_price_short = Column(Numeric(20, 4), default=0)  # 空头持仓均价

    # 盈亏
    hold_profit_long = Column(Numeric(20, 2), default=0)  # 多头持仓盈亏
    hold_profit_short = Column(Numeric(20, 2), default=0)  # 空头持仓盈亏
    close_profit_long = Column(Numeric(20, 2), default=0)  # 多头平仓盈亏
    close_profit_short = Column(Numeric(20, 2), default=0)  # 空头平仓盈亏

    # 保证金
    margin_long = Column(Numeric(20, 2), default=0)  # 多头保证金
    margin_short = Column(Numeric(20, 2), default=0)  # 空头保证金

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("account_id", "strategy_id", "symbol", name="uq_account_strategy_symbol"),
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

    def __repr__(self):
        if self.strategy_id:
            return f"<PositionPo(strategy={self.strategy_id}, symbol={self.symbol}, long={self.pos_long}, short={self.pos_short})>"
        return f"<PositionPo(account={self.account_id}, symbol={self.symbol}, long={self.pos_long}, short={self.pos_short})>"


class TradePo(Base):
    """成交记录表"""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), ForeignKey("accounts.account_id"), nullable=False, index=True)
    trade_id = Column(String(100), unique=True, nullable=False, index=True)
    order_id = Column(String(100), nullable=True, index=True)
    symbol = Column(String(80), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    offset = Column(String(20), nullable=False)
    price = Column(Numeric(20, 4), nullable=False)
    volume = Column(Integer, nullable=False)
    trade_date_time = Column(DateTime, nullable=False)
    # 报单价格（用于计算滑点）
    order_price = Column(Numeric(20, 4), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    account = relationship("AccountPo", back_populates="trades")

    def __repr__(self):
        return f"<TradePo(trade_id={self.trade_id}, symbol={self.symbol}, direction={self.direction}, volume={self.volume})>"


class OrderPo(Base):
    """委托单记录表"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), ForeignKey("accounts.account_id"), nullable=False, index=True)
    order_id = Column(String(100), unique=True, nullable=False, index=True)
    exchange_order_id = Column(String(50), nullable=True)
    symbol = Column(String(80), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    offset = Column(String(20), nullable=False)
    volume_orign = Column(Integer, nullable=False)
    volume_left = Column(Integer, nullable=False)
    limit_price = Column(Numeric(20, 4), nullable=True)
    price_type = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, index=True)
    status_msg = Column(Text, nullable=True)
    insert_date_time = Column(DateTime, nullable=True)
    update_date_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    account = relationship("AccountPo", back_populates="orders")

    def __repr__(self):
        return f"<OrderPo(order_id={self.order_id}, symbol={self.symbol}, status={self.status}, volume_left={self.volume_left})>"


class SwitchPosImportPo(Base):
    """换仓文件导入记录表（指令换仓与目标仓位换仓共用，仅记录导入审计信息）"""

    __tablename__ = "switchPos_import"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("account_id", "file_name", name="uq_switchpos_account_file"),
    )

    def __repr__(self):
        return f"<SwitchPosImportPo(account_id={self.account_id}, file_name={self.file_name})>"


class RotationInstructionPo(Base):
    """换仓指令表"""

    __tablename__ = "rotation_instructions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=False, index=True)
    strategy_id = Column(String(100), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    offset = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    volume = Column(Integer, nullable=False)  # 目标手数
    filled_volume = Column(Integer, nullable=False, default=0)  # 已成交手数
    price = Column(Numeric(20, 4), nullable=False, default=0)
    order_time = Column(String(20), nullable=True)
    trading_date = Column(String(8), nullable=True, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    status = Column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING, RUNNING, COMPLETED, FAILED
    attempt_count = Column(Integer, nullable=False, default=0)
    remaining_attempts = Column(Integer, nullable=False, default=0)
    remaining_volume = Column(Integer, nullable=False, default=0)  # 剩余手数=目标-已成交
    current_order_id = Column(String(50), nullable=True)
    order_placed_time = Column(DateTime, nullable=True)
    last_attempt_time = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    source = Column(String(255), nullable=True)  # 来源：文件名 或 '手动添加'
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<RotationInstructionPo(account_id={self.account_id}, strategy_id={self.strategy_id}, symbol={self.symbol}, direction={self.direction}, volume={self.volume}, filled={self.filled_volume}, enabled={self.enabled})>"


class TargetPosInstructionPo(Base):
    """目标仓位差值指令表（按侧独立计算的待执行指令）"""

    __tablename__ = "target_pos_instructions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=False, index=True)
    strategy_id = Column(String(100), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # LONG / SHORT
    target_volume = Column(Integer, nullable=False, default=0)  # 该侧目标手数
    direction = Column(String(10), nullable=False)  # BUY / SELL
    offset = Column(String(20), nullable=False)  # OPEN / CLOSE
    volume = Column(Integer, nullable=False)  # 待成交手数（差值绝对值）
    filled_volume = Column(Integer, nullable=False, default=0)
    remaining_volume = Column(Integer, nullable=False, default=0)
    price = Column(Numeric(20, 4), nullable=False, default=0)
    trading_date = Column(String(8), nullable=True, index=True)
    plan_id = Column(String(64), nullable=False, index=True)
    instruction_key = Column(String(200), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    status = Column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING/RUNNING/COMPLETED/FAILED
    current_order_id = Column(String(50), nullable=True)
    order_placed_time = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    source = Column(String(255), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (UniqueConstraint("instruction_key", name="uq_target_pos_instruction_key"),)

    def __repr__(self):
        return (
            f"<TargetPosInstructionPo(account_id={self.account_id}, "
            f"strategy_id={self.strategy_id}, symbol={self.symbol}, side={self.side}, "
            f"target={self.target_volume}, volume={self.volume}, filled={self.filled_volume}, "
            f"status={self.status})>"
        )


class JobPo(Base):
    """定时任务配置表"""

    __tablename__ = "jobs"

    job_id = Column(String(50), primary_key=True, nullable=False)
    job_name = Column(String(100), nullable=False)
    job_group = Column(String(50), nullable=False, default="default")
    job_description = Column(Text, nullable=True)
    cron_expression = Column(String(100), nullable=False)
    job_method = Column(String(100), nullable=False, default="")
    last_trigger_time = Column(DateTime, nullable=True)
    next_trigger_time = Column(DateTime, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<JobPo(job_id={self.job_id}, job_name={self.job_name}, enabled={self.enabled})>"


class QuotePo(Base):
    """行情数据表"""

    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange_id = Column(String(20), nullable=False, index=True)
    instrument_id = Column(String(50), nullable=False, index=True)
    last_price = Column(Numeric(20, 4), default=0)
    bid_price1 = Column(Numeric(20, 4), default=0)
    ask_price1 = Column(Numeric(20, 4), default=0)
    volume = Column(Integer, nullable=False)
    open_interest = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<QuotePo(instrument_id={self.instrument_id}, last_price={self.last_price}>"


class AlarmPo(Base):
    """告警信息表"""

    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=False, index=True)
    alarm_type = Column(
        String(20), nullable=False, default="exception", index=True
    )  # notification/exception
    indicator = Column(String(20), nullable=True)  # 1min/5min/1hour
    alarm_date = Column(String(10), nullable=False, index=True)
    alarm_time = Column(String(8), nullable=False)
    source = Column(String(20), nullable=False)
    title = Column(String(200), nullable=False)
    detail = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="UNCONFIRMED", index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

    def __repr__(self):
        return (
            f"<AlarmPo(account_id={self.account_id}, type={self.alarm_type}, title={self.title})>"
        )


class SystemParamPo(Base):
    """系统参数表"""

    __tablename__ = "system_params"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=True, index=True)  # NULL=全局参数
    param_key = Column(String(100), nullable=False, index=True)
    param_value = Column(Text, nullable=True)
    param_type = Column(String(20), nullable=False, default="string")
    description = Column(Text, nullable=True)
    group = Column(String(50), nullable=False, default="general")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (UniqueConstraint("account_id", "param_key", name="uq_sysparam_account_key"),)

    def __repr__(self):
        return f"<SystemParamPo(key={self.param_key}, type={self.param_type}, value={self.param_value})>"


class ContractPo(Base):
    """合约信息表"""

    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(80), unique=True, nullable=False, index=True)
    exchange_id = Column(String(20), nullable=False, index=True)
    instrument_name = Column(String(100), nullable=True)
    product_type = Column(String(20), nullable=False, default="FUTURES")
    volume_multiple = Column(Integer, nullable=False, default=1)
    price_tick = Column(Numeric(20, 6), nullable=False, default=0.01)
    min_volume = Column(Integer, nullable=False, default=1)
    min_open_volume = Column(Integer, nullable=False, default=1)
    option_strike = Column(Numeric(20, 4), nullable=True)
    option_underlying = Column(String(80), nullable=True)
    option_type = Column(String(20), nullable=True)
    update_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    # 数据来源：tq（天勤）、ctp（中泰CTP）等
    data_source = Column(String(20), nullable=True, index=True)
    # 是否活跃合约（当日可交易）
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<ContractPo(symbol={self.symbol}, exchange_id={self.exchange_id}, update_date={self.update_date}, data_source={self.data_source})>"


class UserPo(Base):
    """用户信息表"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # 密码哈希
    role = Column(String(20), nullable=False, default="guest")  # admin, trader, guest
    is_active = Column(Boolean, nullable=False, default=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<UserPo(user_id={self.user_id}, role={self.role}, is_active={self.is_active})>"


class AccountHistoryPo(Base):
    """账户每日结算权益历史表"""

    __tablename__ = "account_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=False, index=True)
    settle_date = Column(Date, nullable=False, index=True)  # 结算日期

    balance = Column(Numeric(20, 2), nullable=False, default=0)  # 结算权益
    available = Column(Numeric(20, 2), nullable=False, default=0)  # 可用资金
    pre_balance = Column(Numeric(20, 2), nullable=True)  # 昨日权益
    static_balance = Column(Numeric(20, 2), nullable=True)  # 静态权益
    deposit = Column(Numeric(20, 2), nullable=True)  # 入金
    withdraw = Column(Numeric(20, 2), nullable=True)  # 出金
    close_profit = Column(Numeric(20, 2), nullable=True)  # 平仓盈亏
    hold_profit = Column(Numeric(20, 2), nullable=True)  # 持仓盈亏
    margin = Column(Numeric(20, 2), nullable=True)  # 保证金占用
    risk_ratio = Column(Numeric(10, 4), nullable=True)  # 风险度

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("account_id", "settle_date", name="uq_account_history_account_date"),
    )

    def __repr__(self):
        return f"<AccountHistoryPo(account_id={self.account_id}, settle_date={self.settle_date}, balance={self.balance})>"


class PositionHistoryPo(Base):
    """账户每日结算持仓历史表"""

    __tablename__ = "positions_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), nullable=False, index=True)
    settle_date = Column(Date, nullable=False, index=True)  # 结算日期
    symbol = Column(String(80), nullable=False)
    exchange = Column(String(20), nullable=False)

    pos_long = Column(Integer, nullable=False, default=0)  # 多头持仓(今+昨)
    pos_short = Column(Integer, nullable=False, default=0)  # 空头持仓(今+昨)

    hold_price_long = Column(Numeric(20, 4), default=0)  # 多头持仓均价
    hold_price_short = Column(Numeric(20, 4), default=0)  # 空头持仓均价

    hold_profit_long = Column(Numeric(20, 2), default=0)  # 多头持仓盈亏
    hold_profit_short = Column(Numeric(20, 2), default=0)  # 空头持仓盈亏

    margin_long = Column(Numeric(20, 2), default=0)  # 多头保证金
    margin_short = Column(Numeric(20, 2), default=0)  # 空头保证金

    last_price = Column(Numeric(20, 4), nullable=True)  # 结算价

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "settle_date", "symbol", name="uq_positions_history_account_date_symbol"
        ),
    )

    def __repr__(self):
        return f"<PositionHistoryPo(account_id={self.account_id}, settle_date={self.settle_date}, symbol={self.symbol}, long={self.pos_long}, short={self.pos_short})>"
