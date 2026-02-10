import sys
from pathlib import Path
from datetime import datetime
from typing import Generator, Optional
from unittest.mock import MagicMock

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.po import Base
from src.models.object import Direction, Exchange, Offset
from src.trader.order_cmd import OrderCmd
from src.utils.config_loader import StrategyConfig


@pytest.fixture(scope="session")
def test_db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def test_db_session(test_db_engine):
    Session = sessionmaker(bind=test_db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_symbol():
    return "SHFE.rb2505"


@pytest.fixture
def sample_account_id():
    return "test_account_001"


# ==================== 策略相关 Fixtures ====================


@pytest.fixture
def mock_strategy_config() -> StrategyConfig:
    """模拟策略配置"""
    return StrategyConfig(
        enabled=True,
        type="test_strategy",
        symbol="SHFE.rb2505",
        exchange="SHFE",
        volume=5,
        bar="M1",
        params={
            "symbol": "SHFE.rb2505",
            "bar_type": "M1",
            "volume": 5,
            "slip": 0.0,
            "max_position": 50,
            "volume_per_order": 5,
            "order_timeout": 10,
            "cmd_timeout": 300,
            "take_profit_pct": 0.02,
            "stop_loss_pct": 0.01,
            "overnight": False,
            "force_exit_time": "14:45:00",
        },
    )


@pytest.fixture
def mock_strategy_manager():
    """模拟策略管理器"""
    from unittest.mock import AsyncMock, MagicMock

    manager = MagicMock()
    manager.send_order_cmd = AsyncMock()
    manager.cancel_order_cmd = AsyncMock()
    manager.get_position = MagicMock(return_value=None)
    manager.load_hist_bars = MagicMock(return_value=[])
    manager.trading_engine = MagicMock()
    return manager


# ==================== TqGateway 相关 Fixtures ====================


@pytest.fixture
def mock_tq_api():
    """模拟 TqApi"""
    from unittest.mock import MagicMock
    import pandas as pd
    from datetime import datetime

    api = MagicMock()

    # 模拟账户数据
    mock_account = MagicMock()
    mock_account.balance = 1000000.0
    mock_account.available = 900000.0
    mock_account.margin = 100000.0
    mock_account.pre_balance = 1000000.0
    mock_account.position_profit = 0.0
    mock_account.close_profit = 0.0
    mock_account.risk_ratio = 0.1
    api.get_account.return_value = mock_account

    # 模拟持仓数据
    mock_positions = {}
    api.get_position.return_value = mock_positions

    # 模拟订单数据
    mock_orders = {}
    api.get_order.return_value = mock_orders

    # 模拟成交数据
    mock_trades = {}
    api.get_trade.return_value = mock_trades

    # 模拟行情订阅
    mock_quote = MagicMock()
    mock_quote.instrument_id = "SHFE.rb2505"
    mock_quote.exchange_id = "SHFE"
    mock_quote.last_price = 3500.0
    mock_quote.ask_price1 = 3501.0
    mock_quote.bid_price1 = 3499.0
    mock_quote.ask_volume1 = 100
    mock_quote.bid_volume1 = 100
    mock_quote.volume = 10000
    mock_quote.turnover = 35000000
    mock_quote.open_interest = 50000
    mock_quote.open = 3480.0
    mock_quote.highest = 3520.0
    mock_quote.lowest = 3470.0
    mock_quote.datetime = int(datetime.now().timestamp() * 1e9)
    api.get_quote.return_value = mock_quote

    # 模拟 K 线数据
    mock_kline = pd.DataFrame({
        "datetime": [int(datetime.now().timestamp() * 1e9)],
        "open": [3500.0],
        "high": [3510.0],
        "low": [3490.0],
        "close": [3505.0],
        "volume": [1000],
        "turnover": [3505000],
        "open_interest": [50000],
    })
    api.get_kline_serial.return_value = mock_kline

    # 模拟合约查询
    api.query_quotes.return_value = ["SHFE.rb2505"]
    api.query_symbol_info.return_value = pd.DataFrame({
        "instrument_id": ["SHFE.rb2505"],
        "exchange_id": ["SHFE"],
        "instrument_name": ["螺纹钢2505"],
        "volume_multiple": [10],
        "price_tick": [1.0],
    })

    # 模拟 is_changing
    api.is_changing.return_value = False
    api.wait_update.return_value = True

    # 模拟下单
    mock_order = {
        "order_id": "test_order_id",
        "instrument_id": "SHFE.rb2505",
        "exchange_id": "SHFE",
        "direction": "BUY",
        "offset": "OPEN",
        "volume_orign": 5,
        "volume_left": 5,
        "limit_price": 3500.0,
        "status": "ALIVE",
        "last_msg": "",
        "insert_date_time": int(datetime.now().timestamp() * 1e9),
    }
    api.insert_order.return_value = mock_order

    # 模拟撤单
    api.cancel_order.return_value = None

    # 模拟交易日历
    trading_calendar = pd.DataFrame({
        "date": ["2026-01-15"],
        "trading": [True],
    })
    api.get_trading_calendar.return_value = trading_calendar

    return api


@pytest.fixture
def mock_tq_gateway_config():
    """模拟 TqGateway 配置"""
    from src.utils.config_loader import GatewayConfig, TianqinConfig, BrokerConfig

    return GatewayConfig(
        account_id="test_account_001",
        type="TQSDK",
        tianqin=TianqinConfig(
            username="test_user",
            password="test_pass",
        ),
        broker=BrokerConfig(
            type="sim",
        ),
        subscribe_symbols=["SHFE.rb2505"],
    )


# ==================== 配置加载器相关 Fixtures ====================


@pytest.fixture
def temp_config_dir(tmp_path):
    """临时配置目录"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def sample_config_yaml():
    """示例 config.yaml 内容"""
    return {
        "account_ids": ["test_account_001"],
        "accounts": [],
        "paths": {
            "switchPos_files": "./data/orders",
            "logs": "./data/logs",
            "database": "./data/trading.db",
            "export": "./data/export",
            "params": "./data/params",
        },
        "socket": {
            "socket_dir": "./data/socks",
            "health_check_interval": 10,
            "heartbeat_timeout": 30,
        },
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "cors_origins": ["http://localhost:5173"],
        },
    }


@pytest.fixture
def sample_account_yaml():
    """示例 account-{ID}.yaml 内容"""
    return {
        "account_id": "test_account_001",
        "account_type": "kq",
        "enabled": True,
        "auto_start": False,
        "alert_wechat": False,
        "gateway": {
            "account_id": "test_account_001",
            "type": "TQSDK",
            "tianqin": {
                "username": "test_user",
                "password": "test_pass",
            },
            "broker": {
                "type": "kq",
                "broker_name": "",
                "user_id": "",
                "password": "",
                "app_id": "",
                "auth_code": "",
                "url": "",
            },
            "subscribe_symbols": ["SHFE.rb2505"],
        },
        "trading": {
            "auto_trade": True,
            "paused": False,
            "risk_control": {
                "max_daily_orders": 1000,
                "max_daily_cancels": 500,
                "max_order_volume": 50,
                "max_split_volume": 5,
                "order_timeout": 5,
            },
        },
        "paths": {
            "switchPos_files": "./data/orders/test_account_001",
            "logs": "./data/logs/test_account_001",
            "database": "./data/trading_test_account_001.db",
            "export": "./data/export/test_account_001",
            "params": "./data/params/test_account_001",
        },
        "strategies": {
            "test_strategy": {
                "enabled": True,
                "type": "rsi_strategy",
                "symbol": "SHFE.rb2505",
                "bar": "M1",
                "volume": 1,
            }
        },
    }
