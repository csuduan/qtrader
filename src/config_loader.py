"""
配置文件加载器
支持从YAML文件加载配置，并提供默认值
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

from src.utils.logger import get_logger

logger = get_logger(__name__)



class TianqinConfig(BaseModel):
    """天勤账户配置"""
    username: str
    password: str


class TradingAccountConfig(BaseModel):
    """实盘交易账户配置"""
    broker_name: str = ""
    user_id: str = ""
    password: str = ""


class PathsConfig(BaseModel):
    """目录配置"""
    switchPos_files: str = "./data/orders"
    logs: str = "./data/logs"
    database: str = "./storage/trading.db"
    export: str = "./data/export"
    strategies: str = "./config/strategies.yaml"
    params: str = "./config/params"


class RiskControlConfig(BaseModel):
    """风控参数配置"""
    max_daily_orders: int = 1000
    max_daily_cancels: int = 500
    max_order_volume: int = 50
    max_split_volume: int = 5
    order_timeout: int = 5

    @field_validator("max_daily_orders", "max_daily_cancels", "max_order_volume", "max_split_volume", "order_timeout")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("风控参数必须大于0")
        return v


class MarketConfig(BaseModel):
    """行情订阅配置"""
    subscribe_symbols: List[str] = Field(default_factory=list)
    kline_duration: int = 60

    @field_validator("kline_duration")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("K线周期必须大于0")
        return v


class SwitchManagerConfig(BaseModel):
    """交易切换管理器配置"""
    scan_interval: int = 10
    processed_files_dir: str = "./data/orders/processed"


class JobConfig(BaseModel):
    """定时任务配置"""
    job_id: str
    job_name: str
    job_group: str = "default"
    job_description: Optional[str] = None
    cron_expression: str
    job_method: str
    enabled: bool = True


class ApiConfig(BaseModel):
    """API服务配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"]
    )


class SchedulerConfig(BaseModel):
    """定时任务调度器配置"""
    jobs: List[JobConfig] = Field(default_factory=list)


class TradingConfig(BaseModel):
    """交易控制配置"""
    auto_trade: bool = True
    paused: bool = False


class AppConfig(BaseModel):
    """应用总配置"""
    tianqin: TianqinConfig
    account_type: str = "kq"
    account_id: str = ""
    trading_account: Optional[TradingAccountConfig] = None
    paths: PathsConfig = Field(default_factory=PathsConfig)
    risk_control: RiskControlConfig = Field(default_factory=RiskControlConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        if v not in ("kq", "real"):
            raise ValueError("账户类型必须是 kq, real")
        return v


app_config:AppConfig = None
def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认为 ./config/config.yaml

    Returns:
        AppConfig: 配置对象

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置文件格式错误
    """
    if config_path is None:
        possible_paths = [
            "./config/config.yaml",
            "./config.yaml",
            "../config/config.yaml",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                config_path = path
                break

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"配置文件不存在。请创建配置文件或将 config.example.yaml 复制为 {config_path}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    app_config = AppConfig(**config_data)
    ensure_directories(app_config)
    return app_config

def get_config() -> AppConfig:
    """获取已加载的配置"""
    global app_config
    if app_config is None:
        app_config = load_config()
    return app_config


def ensure_directories(config: AppConfig) -> None:
    """确保所需的目录存在"""
    directories = [
        config.paths.switchPos_files,
        config.paths.logs,
        os.path.dirname(config.paths.database) if os.path.dirname(config.paths.database) else "./storage",
        config.paths.switchPos_files,
        config.paths.export,
        config.paths.params
    ]

    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


def create_settings_file() -> None:
    """创建默认配置文件"""
    config_path = Path("config/config.yaml")

    if config_path.exists():
        print("配置文件已存在")
        return

    default_config = {
        "tianqin": {
            "username": "your_username",
            "password": "your_password"
        },
        "account_type": "kq",
        "account_id": None,
        "paths": {
            "switchPos_files": "./data/orders",
            "logs": "./data/logs",
            "database": "./storage/trading.db",
            "export": "./data/export"
        },
        "risk_control": {
            "max_daily_orders": 1000,
            "max_daily_cancels": 500,
            "max_order_volume": 50,
            "max_split_volume": 5,
            "order_timeout": 5
        },
        "market": {
            "subscribe_symbols": [],
            "kline_duration": 60
        },
        "switch_mgr": {
            "scan_interval": 10,
            "processed_files_dir": "./data/orders/processed"
        },
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "cors_origins": [
                "http://localhost:5173",
                "http://localhost:8080"
            ]
        },
        "trading": {
            "auto_trade": True,
            "paused": False
        },
        "scheduler": {
            "jobs": [
                {
                    "job_id": "pre_market_connect_morning",
                    "job_name": "早盘盘前自动连接",
                    "job_group": "connect",
                    "job_description": "早盘开盘前自动连接到TqSdk",
                    "cron_expression": "55 8 * * *",
                    "enabled": True
                },
                {
                    "job_id": "pre_market_connect_night",
                    "job_name": "夜盘盘前自动连接",
                    "job_group": "connect",
                    "job_description": "夜盘开盘前自动连接到TqSdk",
                    "cron_expression": "55 20 * * *",
                    "enabled": True
                },
                {
                    "job_id": "rotation_0905",
                    "job_name": "日盘开盘换仓09:05",
                    "job_group": "rotation",
                    "job_description": "日盘开盘前09:05执行换仓",
                    "cron_expression": "5 9 * * *",
                    "enabled": True
                },
                {
                    "job_id": "rotation_0935",
                    "job_name": "日盘中段换仓09:35",
                    "job_group": "rotation",
                    "job_description": "日盘中段09:35执行换仓",
                    "cron_expression": "35 9 * * *",
                    "enabled": True
                },
                {
                    "job_id": "rotation_2105",
                    "job_name": "夜盘开盘换仓21:05",
                    "job_group": "rotation",
                    "job_description": "夜盘开盘前21:05执行换仓",
                    "cron_expression": "5 21 * * *",
                    "enabled": True
                },
                {
                    "job_id": "post_market_export_morning",
                    "job_name": "早盘盘后处理",
                    "job_group": "process",
                    "job_description": "早盘收盘后导出持仓到CSV文件",
                    "cron_expression": "35 15 * * *",
                    "enabled": True
                },
                {
                    "job_id": "post_market_export_night",
                    "job_name": "夜盘盘后处理",
                    "job_group": "process",
                    "job_description": "夜盘收盘后导出持仓到CSV文件",
                    "cron_expression": "30 2 * * *",
                    "enabled": True
                },
                {
                    "job_id": "post_market_disconnect_morning",
                    "job_name": "早盘盘后断开连接",
                    "job_group": "disconnect",
                    "job_description": "早盘收盘后断开TqSdk连接",
                    "cron_expression": "35 15 * * *",
                    "enabled": True
                },
                {
                    "job_id": "post_market_disconnect_night",
                    "job_name": "夜盘盘后断开连接",
                    "job_group": "disconnect",
                    "job_description": "夜盘收盘后断开TqSdk连接",
                    "cron_expression": "30 2 * * *",
                    "enabled": True
                }
            ]
        }
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)

    print(f"默认配置文件已创建: {config_path}")

# 策略配置类
class StrategyConfig(BaseModel):
    """单个策略配置"""
    enabled: bool = False
    strategy_type: str = "bar"  # tick 或 bar
    symbol: str = ""
    exchange: str = ""
    volume_per_trade: int = 1
    max_position: int = 5

    # 交易参数
    take_profit_pct: float = 0.02
    stop_loss_pct: float = 0.01
    fee_rate: float = 0.0001

    # 交易窗口
    trade_start_time: str = "09:30:00"
    trade_end_time: str = "14:50:00"
    force_exit_time: str = "14:55:00"

    # 交易限制
    one_trade_per_day: bool = True

    # 参数文件路径
    params_file: Optional[str] = None

    # 策略特定参数（子类扩展）
    params: Dict[str, Any] = Field(default_factory=dict)


class StrategiesConfig(BaseModel):
    """策略配置集合"""
    strategies: Dict[str, StrategyConfig] = Field(default_factory=dict)

    class Config:
        extra = "allow"  # 允许额外字段


def load_strategies_config(config_path: str = "config/strategies.yaml") -> StrategiesConfig:
    """
    加载策略配置

    Args:
        config_path: 策略配置文件路径

    Returns:
        StrategiesConfig: 策略配置对象
    """
    from pathlib import Path

    config_file = Path(config_path)
    if not config_file.exists():
        logger.warning(f"策略配置文件不存在: {config_path}")
        return StrategiesConfig()

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return StrategiesConfig(**data)
    except Exception as e:
        logger.error(f"加载策略配置失败: {e}")
        return StrategiesConfig()

# Gateway类型配置
class GatewayConfig(BaseModel):
    """Gateway配置"""
    gateway_type: str = "TQSDK"  # TQSDK 或 CTP

