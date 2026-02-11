"""
数据库持久化对象模型定义
使用SQLAlchemy ORM定义所有数据表结构
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
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
    """持仓信息表"""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), ForeignKey("accounts.account_id"), nullable=False, index=True)
    symbol = Column(String(80), nullable=False, index=True)
    pos_long = Column(Integer, nullable=False, default=0)
    pos_short = Column(Integer, nullable=False, default=0)
    open_price_long = Column(Numeric(20, 4), default=0)
    open_price_short = Column(Numeric(20, 4), default=0)
    float_profit = Column(Numeric(20, 2), default=0)
    margin = Column(Numeric(20, 2), default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_account_symbol"),)

    account = relationship("AccountPo", back_populates="positions")

    def __repr__(self):
        return f"<PositionPo(symbol={self.symbol}, pos_long={self.pos_long}, pos_short={self.pos_short})>"


class TradePo(Base):
    """成交记录表"""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), ForeignKey("accounts.account_id"), nullable=False, index=True)
    trade_id = Column(String(50), unique=True, nullable=False, index=True)
    order_id = Column(String(50), nullable=True, index=True)
    symbol = Column(String(80), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    offset = Column(String(20), nullable=False)
    price = Column(Numeric(20, 4), nullable=False)
    volume = Column(Integer, nullable=False)
    trade_date_time = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    account = relationship("AccountPo", back_populates="trades")

    def __repr__(self):
        return f"<TradePo(trade_id={self.trade_id}, symbol={self.symbol}, direction={self.direction}, volume={self.volume})>"


class OrderPo(Base):
    """委托单记录表"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(50), ForeignKey("accounts.account_id"), nullable=False, index=True)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    exchange_order_id = Column(String(50), nullable=True)
    symbol = Column(String(80), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    offset = Column(String(20), nullable=False)
    volume_orign = Column(Integer, nullable=False)
    volume_left = Column(Integer, nullable=False)
    limit_price = Column(Numeric(20, 4), nullable=True)
    price_type = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, index=True)
    insert_date_time = Column(Integer, nullable=False)
    last_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    account = relationship("AccountPo", back_populates="orders")

    def __repr__(self):
        return f"<OrderPo(order_id={self.order_id}, symbol={self.symbol}, status={self.status}, volume_left={self.volume_left})>"


class SwitchPosImportPo(Base):
    """订单文件记录表"""

    __tablename__ = "switchPos_import"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False, unique=True)
    file_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<OrderFilePo(file_name={self.file_name})>"


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
    alarm_date = Column(String(10), nullable=False, index=True)
    alarm_time = Column(String(8), nullable=False)
    source = Column(String(20), nullable=False)
    title = Column(String(200), nullable=False)
    detail = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="UNCONFIRMED", index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

    def __repr__(self):
        return f"<AlarmPo(account_id={self.account_id}, title={self.title}, status={self.status})>"


class SystemParamPo(Base):
    """系统参数表"""

    __tablename__ = "system_params"

    id = Column(Integer, primary_key=True, autoincrement=True)
    param_key = Column(String(100), unique=True, nullable=False, index=True)
    param_value = Column(Text, nullable=True)
    param_type = Column(String(20), nullable=False, default="string")
    description = Column(Text, nullable=True)
    group = Column(String(50), nullable=False, default="general")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

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
    option_strike = Column(Numeric(20, 4), nullable=True)
    option_underlying = Column(String(80), nullable=True)
    option_type = Column(String(20), nullable=True)
    update_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<ContractPo(symbol={self.symbol}, exchange_id={self.exchange_id}, update_date={self.update_date})>"
