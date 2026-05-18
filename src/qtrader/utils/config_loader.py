"""
配置文件加载器
支持从YAML文件加载配置，并提供默认值

配置文件结构：
- config.yaml: 主配置文件（accounts列表、socket、api配置）
- account-{ACCOUNT_ID}.yaml: 账户配置文件（完整账户配置）
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 基础配置类 ====================


class TianqinConfig(BaseModel):
    """天勤账户配置"""

    username: str
    password: str


class BrokerConfig(BaseModel):
    """CTP经纪商配置"""

    type: str = "kq"  # kq、sim、tq、ctp等
    broker_name: str = ""
    user_id: str = ""
    password: str = ""
    broker_id: str = ""
    app_id: str = ""
    auth_code: str = ""
    url: str = ""
    td_address: str = ""
    md_address: str = ""


class RiskControlConfig(BaseModel):
    """风控参数配置"""

    max_daily_orders: int = 1000
    max_daily_cancels: int = 500
    max_order_volume: int = 50
    max_split_volume: int = 5
    order_timeout: int = 5

    @field_validator(
        "max_daily_orders",
        "max_daily_cancels",
        "max_order_volume",
        "max_split_volume",
        "order_timeout",
    )
    @classmethod
    def validate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("风控参数必须大于0")
        return v


class PathsConfig(BaseModel):
    """目录配置"""

    socket_dir: str = "./data/socks"
    switch_pos: str = "./data/switch_pos"
    logs: str = "./data/logs"
    database: str = "./data/db"
    export: str = "./data/export"
    params: str = "./data/params"


class JobConfig(BaseModel):
    """定时任务配置"""

    job_id: str
    job_name: str
    job_group: str = "default"
    job_description: str | None = None
    cron_expression: str
    job_method: str
    enabled: bool = True


class SchedulerConfig(BaseModel):
    """定时任务调度器配置"""

    jobs: list[JobConfig] = Field(default_factory=list)


class TradingConfig(BaseModel):
    """交易控制配置"""

    auto_trade: bool = True
    paused: bool = False
    risk_control: RiskControlConfig | None = None
    # 开仓限制
    open_limit: (dict[str, int]) | None = None


# ==================== 策略配置类 ====================


class StrategyConfig(BaseModel):
    """单个策略配置"""

    enabled: bool = False
    type: str = "rsi_strategy"  # 策略类型
    symbol: str = ""
    exchange: str = ""
    volume: int = 1
    bar: str = "M1"
    params_file: str | None = None
    # 其他参数（动态扩展）
    params: dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"  # 允许额外字段


# ==================== 账户配置类 ====================


class GatewayConfig(BaseModel):
    """网关配置"""

    account_id: str | None = None
    type: str = "TQSDK"
    tianqin: TianqinConfig | None = None
    broker: BrokerConfig | None = None
    subscribe_symbols: list[str] = []
    subscribe_bars: list[str] = []


class IndicatorConfig(BaseModel):
    """异常指标配置"""

    name: str = Field(..., description="指标名称: 1min/5min/1hour")
    window: int = Field(..., description="时间窗口（秒）")
    threshold: int = Field(..., description="阈值（异常次数）")
    description: str = Field(default="", description="指标描述")


class NotificationAlertConfig(BaseModel):
    """通知告警配置"""

    enabled: bool = Field(default=True, description="是否启用通知告警")
    dnd_start: int = Field(default=23, description="免打扰开始时间（小时）")
    dnd_end: int = Field(default=8, description="免打扰结束时间（小时）")


class ExceptionAlertConfig(BaseModel):
    """异常告警配置"""

    enabled: bool = Field(default=True, description="是否启用异常告警")
    dnd_start: int = Field(default=23, description="免打扰开始时间（小时）")
    dnd_end: int = Field(default=8, description="免打扰结束时间（小时）")
    indicators: list[IndicatorConfig] = Field(
        default_factory=lambda: [
            IndicatorConfig(
                name="1min", window=60, threshold=1, description="最近1分钟异常次数超过1"
            ),
            IndicatorConfig(
                name="5min", window=300, threshold=5, description="最近5分钟异常次数超过5"
            ),
            IndicatorConfig(
                name="1hour", window=3600, threshold=10, description="最近1小时异常次数超过10"
            ),
        ],
        description="异常指标配置列表",
    )


class AlertConfig(BaseModel):
    """告警通知配置（新结构）"""

    notification: NotificationAlertConfig = Field(
        default_factory=NotificationAlertConfig, description="通知告警配置"
    )
    exception: ExceptionAlertConfig = Field(
        default_factory=ExceptionAlertConfig, description="异常告警配置"
    )


class AccountConfig(BaseModel):
    """完整账户配置（来自account-{ID}.yaml）"""

    account_id: str | None = None
    name: str | None = None
    account_type: str | None = "kq"
    enabled: bool | None = True
    # 告警配置
    alert: AlertConfig = Field(default_factory=AlertConfig)

    gateway: GatewayConfig | None = None
    paths: PathsConfig | None = None
    trading: TradingConfig | None = None
    strategies: (dict[str, StrategyConfig]) | None = None

    class Config:
        extra = "allow"  # 允许额外字段


class SocketConfig(BaseModel):
    """Socket配置"""

    socket_dir: str = "./data/socks"
    health_check_interval: int = 10
    heartbeat_timeout: int = 30


class ApiConfig(BaseModel):
    """API服务配置"""

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )


class PublicDataConfig(BaseModel):
    """公共数据库配置"""

    enabled: bool = True  # 是否启用公共数据共享机制


class DatabaseExtConfig(BaseModel):
    """扩展数据库配置"""

    public_data: PublicDataConfig = Field(default_factory=PublicDataConfig)


class PgConfig(BaseModel):
    """PostgreSQL 连接配置"""

    host: str = "localhost"
    port: int = 5432
    user: str = "qtrader"
    password: str = ""
    database: str = "qtrader"
    pool_size: int = 5
    max_overflow: int = 10


class DataBaseConfig(BaseModel):
    """数据库配置"""

    pg: PgConfig = Field(default_factory=PgConfig)


class TraderInitConfig(BaseModel):
    """Trader初始化配置"""

    # 等待 Manager 推送公共数据的超时时间（秒）
    public_data_timeout: int = 30


class SubsConfig(BaseModel):
    """订阅配置（全局）"""

    subscribe_symbols: list[str] = Field(default_factory=list, description="订阅的合约列表")
    subscribe_bars: list[str] = Field(
        default_factory=list, description="订阅的K线列表，格式: symbol-interval"
    )


class AdminConfig(BaseModel):
    """管理员账户配置"""

    user: str = "admin"
    password: str = "admin123"


class AppConfig(BaseModel):
    """全局配置（来自config.yaml）"""

    account_ids: list[str] = Field(default_factory=list, description="账户ID列表")
    accounts: list[AccountConfig] = Field(default_factory=list, description="账户配置列表")
    paths: PathsConfig = Field(default_factory=PathsConfig)
    socket: SocketConfig = Field(default_factory=SocketConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    scheduler: SchedulerConfig | None = None  # Manager 定时任务
    account_scheduler: SchedulerConfig | None = None  # 账户定时任务
    trading: TradingConfig | None = Field(default_factory=TradingConfig)
    # 数据库连接配置
    data_base: DataBaseConfig | None = Field(default_factory=DataBaseConfig)
    # 数据服务配置
    data_service: dict[str, dict[str, str]] = Field(default_factory=dict)
    # 全局订阅配置
    subs: SubsConfig = Field(default_factory=SubsConfig)

    # 全局告警配置（所有账户共享）
    alert: AlertConfig = Field(default_factory=AlertConfig)
    # 管理员账户配置
    admin: AdminConfig = Field(default_factory=AdminConfig)

    class Config:
        extra = "allow"  # 允许额外字段

    def get_active_accounts(self) -> list[AccountConfig]:
        return [acc for acc in self.accounts if acc.enabled]

    def get_account_config(self, account_id: str) -> AccountConfig | None:
        for acc in self.accounts:
            if acc.account_id == account_id:
                return acc
        return None


class TraderConfig(AccountConfig):
    """交易器配置"""

    socket: SocketConfig = Field(default_factory=SocketConfig)
    subs: SubsConfig = Field(default_factory=SubsConfig)


# ==================== 配置加载器 ====================


class ConfigLoader:
    """配置加载器类"""

    def __init__(self, config_dir: str = "./config"):
        """
        初始化配置加载器

        Args:
            config_dir: 配置文件目录
        """
        self.config_dir = Path(config_dir)
        self.app_config: AppConfig | None = None

    def load_config(self) -> AppConfig:
        """加载所有配置（包括动态扫描账户配置）"""
        if self.app_config:
            return self.app_config

        self.app_config = AppConfig()
        self.app_config = self._load_app_config()

        # 动态扫描config目录下所有account-*.yaml文件

        for account_id in self.app_config.account_ids:
            try:
                # 从文件名提取account_id
                account = self._load_account_config(account_id)
                self.app_config.accounts.append(account)
                logger.info(f"已加载账户配置: {account_id} (enabled: {account.enabled})")
            except Exception as e:
                logger.exception(f"加载账户配置文件 account-{account_id}.yaml 失败: {e}")

        # 根据account_ids字段排序（如果有配置顺序）
        if self.app_config.account_ids:
            # 按照account_ids中定义的顺序重新排序
            account_order = {aid: i for i, aid in enumerate(self.app_config.account_ids)}
            self.app_config.accounts.sort(
                key=lambda acc: (
                    account_order.get(acc.account_id, float("inf"))
                    if acc.account_id is not None
                    else float("inf")
                )
            )

        return self.app_config

    def load_trader_config(self, acct_id: str) -> TraderConfig:
        """加载交易器配置（包含socket配置）"""
        acct_config = self._load_account_config(acct_id)
        if not acct_config:
            raise ValueError(f"未找到账户 [{acct_id}] 的配置")
        # 将AccountConfig转换为TraderConfig
        trader_config = TraderConfig.model_validate(acct_config.model_dump())
        app_config = self._load_app_config()
        trader_config.socket = app_config.socket
        # 如果 trading 配置不存在，则使用app的默认值
        if not trader_config.trading:
            trader_config.trading = app_config.trading
        if not trader_config.paths:
            trader_config.paths = app_config.paths
        # 使用全局subs配置（如果账户配置中没有定义）
        trader_config.subs = app_config.subs
        return trader_config

    def _load_app_config(self) -> AppConfig:
        """
        加载全局配置文件 (config.yaml)

        Returns:
            AppConfig: 全局配置对象
        """
        config_path = self.config_dir / "config.yaml"

        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        app_config = AppConfig(**config_data)

        # 如果 socket.socket_dir 未设置，使用 paths.socket_dir 的值
        if not app_config.socket.socket_dir or app_config.socket.socket_dir == "./data/socks":
            app_config.socket.socket_dir = app_config.paths.socket_dir

        return app_config

    def _load_account_config(self, account_id: str) -> AccountConfig:
        """
        加载指定账户的配置文件 (account-{ACCOUNT_ID}.yaml)

        Args:
            account_id: 账户ID

        Returns:
            AccountFullConfig: 账户配置对象
        """
        config_path = self.config_dir / f"account-{account_id}.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"账户配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        account = AccountConfig(**config_data)
        return account


# 全局配置加载器实例
_config_loader: ConfigLoader | None = None


def get_config_loader() -> ConfigLoader:
    """获取全局配置加载器实例"""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader


def get_database_path(base_dir: str, account_id: str) -> str:
    """获取数据库文件路径

    Args:
        base_dir: 数据库目录（来自 config.yaml paths.database）
        account_id: 账户ID（"manager" 或具体账户ID）

    Returns:
        完整数据库文件路径
    """
    if account_id == "manager":
        return f"{base_dir}/q-manager.db"
    else:
        return f"{base_dir}/q-trader-{account_id}.db"


def get_log_dir(base_dir: str, app_name: str) -> str:
    """获取日志目录

    Args:
        base_dir: 日志基础目录（来自 config.yaml paths.logs）
        app_name: 应用名称（"manager" 或账户ID）

    Returns:
        日志目录路径
    """
    return f"{base_dir}/{app_name}"


# 数据库配置
class DatabaseConfig(BaseModel):
    """数据库配置"""

    base_path: str = "./storage"
    db_prefix: str = "trading_"
