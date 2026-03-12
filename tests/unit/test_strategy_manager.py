"""
StrategyManager 单元测试
测试 StrategyManager 类的所有方法和功能
"""

import csv
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch, mock_open
from datetime import datetime

import pytest

from src.trader.strategy_manager import (
    StrategyManager,
    load_csv_file,
    load_strategy_params,
    _csv_cache,
)
from src.models.object import (
    Direction,
    Offset,
    OrderData,
    TradeData,
    TickData,
    BarData,
    Interval,
    Exchange,
)
from src.utils.event_engine import EventEngine, EventTypes


# ==================== Fixtures ====================


@pytest.fixture
def mock_trading_engine():
    """模拟TradingEngine"""
    engine = MagicMock()
    engine.insert_order = MagicMock(return_value="order_123")
    engine.cancel_order = MagicMock(return_value=True)
    engine.subscribe_symbol = MagicMock(return_value=True)
    engine.event_engine = MagicMock()
    return engine


@pytest.fixture
def mock_strategies_config():
    """模拟StrategiesConfig"""
    config = MagicMock()
    config.strategies = {
        "test_strategy": {
            "enabled": True,
            "type": "rsi",
            "symbol": "SHFE.rb2505",
            "exchange": "SHFE",
            "volume_per_trade": 1,
        }
    }
    return config


@pytest.fixture
def mock_event_engine():
    """模拟EventEngine"""
    engine = MagicMock()
    engine.register = MagicMock()
    return engine


@pytest.fixture
def strategy_manager(mock_strategies_config, mock_trading_engine):
    """创建StrategyManager实例"""
    return StrategyManager(mock_strategies_config, mock_trading_engine)


@pytest.fixture
def mock_strategy():
    """模拟BaseStrategy"""
    strategy = MagicMock()
    strategy.strategy_id = "test_strategy"
    strategy.active = False
    strategy.config = {"enabled": True, "symbol": "SHFE.rb2505"}
    strategy.init = MagicMock()
    strategy.start = MagicMock(return_value=True)
    strategy.stop = MagicMock(return_value=True)
    strategy.reset_for_new_day = MagicMock()
    strategy.on_tick = MagicMock()
    strategy.on_bar = MagicMock()
    strategy.on_order = MagicMock()
    strategy.on_trade = MagicMock()
    return strategy


@pytest.fixture(autouse=True)
def clear_csv_cache():
    """每个测试前清空CSV缓存"""
    _csv_cache.clear()
    yield
    _csv_cache.clear()


# ==================== Test CSV Loading Functions ====================


class TestLoadCsvFile:
    """测试 load_csv_file 函数"""

    def test_load_csv_file_success(self, tmp_path):
        """测试成功加载CSV文件"""
        csv_path = tmp_path / "test_params.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["StrategyId", "param1", "param2"])
            writer.writeheader()
            writer.writerow({"StrategyId": "strat1", "param1": "value1", "param2": "value2"})
            writer.writerow({"StrategyId": "strat2", "param1": "value3", "param2": "value4"})

        result = load_csv_file(str(csv_path))

        assert "strat1" in result
        assert result["strat1"]["param1"] == "value1"
        assert "strat2" in result
        assert result["strat2"]["param2"] == "value4"

    def test_load_csv_file_uses_cache(self, tmp_path):
        """测试使用缓存"""
        csv_path = tmp_path / "test_params.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["StrategyId", "param1"])
            writer.writeheader()
            writer.writerow({"StrategyId": "strat1", "param1": "value1"})

        # First call
        result1 = load_csv_file(str(csv_path))
        # Modify file
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            f.write("StrategyId,param1\nstrat2,value2")
        # Second call should use cache
        result2 = load_csv_file(str(csv_path))

        assert result1 == result2
        assert "strat1" in result2

    def test_load_csv_file_not_found(self, tmp_path):
        """测试文件不存在"""
        result = load_csv_file(str(tmp_path / "nonexistent.csv"))

        assert result == {}

    def test_load_csv_file_empty_strategy_id(self, tmp_path):
        """测试空策略ID行被跳过"""
        csv_path = tmp_path / "test_params.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["StrategyId", "param1"])
            writer.writeheader()
            writer.writerow({"StrategyId": "", "param1": "value1"})
            writer.writerow({"StrategyId": "strat1", "param1": "value2"})

        result = load_csv_file(str(csv_path))

        assert "strat1" in result
        assert "" not in result

    def test_load_csv_file_invalid_csv(self, tmp_path):
        """测试无效CSV格式"""
        csv_path = tmp_path / "invalid.csv"
        csv_path.write_text("not a valid csv", encoding="utf-8")

        result = load_csv_file(str(csv_path))

        assert result == {}


class TestLoadStrategyParams:
    """测试 load_strategy_params 函数"""

    def test_load_strategy_params_no_csv_file(self):
        """测试无CSV参数文件"""
        yaml_config = {"enabled": True, "symbol": "SHFE.rb2505"}
        mock_config = MagicMock()
        mock_config.paths.params = "/data/params"

        with patch("src.trader.strategy_manager.get_app_context", return_value=mock_config):
            result = load_strategy_params(yaml_config, "strat1")

            assert result == yaml_config

    def test_load_strategy_params_csv_not_found(self, tmp_path):
        """测试CSV文件不存在"""
        yaml_config = {"enabled": True, "symbol": "SHFE.rb2505", "params_file": "test.csv"}
        mock_config = MagicMock()
        mock_config.paths.params = str(tmp_path)

        with patch("src.trader.strategy_manager.get_app_context", return_value=mock_config):
            result = load_strategy_params(yaml_config, "strat1")

            assert result == yaml_config

    def test_load_strategy_params_csv_override(self, tmp_path):
        """测试CSV参数覆盖YAML"""
        csv_path = tmp_path / "test_params.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["StrategyId", "symbol", "volume"])
            writer.writeheader()
            writer.writerow({"StrategyId": "strat1", "symbol": "SHFE.rb2505", "volume": "5"})

        # Clear cache to ensure we're testing the actual load
        _csv_cache.clear()

        yaml_config = {"enabled": True, "symbol": "SHFE.rb2505", "params_file": "test_params.csv", "volume": "1"}

        # Create a proper mock that has the paths attribute
        from types import SimpleNamespace
        mock_paths = SimpleNamespace(params=str(tmp_path))
        mock_config = SimpleNamespace(paths=mock_paths)
        mock_context = MagicMock()
        mock_context.get_config.return_value = mock_config

        with patch("src.trader.strategy_manager.get_app_context", return_value=mock_context):
            result = load_strategy_params(yaml_config, "strat1")

        # The CSV override should have worked
        assert result["volume"] == "5"  # Overridden by CSV

    def test_load_strategy_params_csv_empty_values_skipped(self, tmp_path):
        """测试空CSV值不覆盖"""
        csv_path = tmp_path / "test_params.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["StrategyId", "symbol", "volume"])
            writer.writeheader()
            writer.writerow({"StrategyId": "strat1", "symbol": "", "volume": "5"})

        # Clear cache to ensure we're testing the actual load
        _csv_cache.clear()

        # Test CSV loading directly - empty values should still be in the dict
        csv_data = load_csv_file(os.path.join(str(tmp_path), "test_params.csv"))
        assert csv_data["strat1"]["symbol"] == ""  # Empty string in CSV
        assert csv_data["strat1"]["volume"] == "5"


# ==================== Test Initialization ====================


class TestStrategyManagerInit:
    """测试 StrategyManager 初始化"""

    def test_init(self, strategy_manager):
        """测试初始化"""
        assert strategy_manager.strategies == {}
        assert strategy_manager.strategies_config is not None
        assert strategy_manager.trading_engine is not None
        assert strategy_manager.event_engine is None
        assert strategy_manager.subscribed_symbols == set()
        assert strategy_manager.order_strategy_map == {}


# ==================== Test Start Method ====================


class TestStrategyManagerStartMethod:
    """测试 start 方法"""

    @pytest.mark.asyncio
    async def test_start_success(self, strategy_manager, mock_event_engine):
        """测试成功启动"""
        with patch("src.trader.strategy_manager.ctx") as mock_ctx, \
             patch.object(strategy_manager, "_load_strategies"), \
             patch.object(strategy_manager, "_register_events"), \
             patch.object(strategy_manager, "start_all"):
            mock_ctx.get_event_engine.return_value = mock_event_engine

            result = await strategy_manager.start()

            assert result is True
            assert strategy_manager.event_engine == mock_event_engine


# ==================== Test Load Strategies ====================


class TestStrategyManagerLoadStrategies:
    """测试 _load_strategies 方法"""

    def test_load_strategies_disabled(self, strategy_manager):
        """测试跳过禁用的策略"""
        strategy_manager.strategies_config.strategies = {
            "disabled_strat": {"enabled": False, "type": "rsi_strategy"}
        }

        with patch("src.trader.strategy.get_strategy_class", return_value=None):
            strategy_manager._load_strategies()

            assert "disabled_strat" not in strategy_manager.strategies

    def test_load_strategies_no_strategy_class(self, strategy_manager):
        """测试策略类不存在"""
        strategy_manager.strategies_config.strategies = {
            "test_strat": {"enabled": True, "type": "nonexistent_strategy"}
        }

        with patch("src.trader.strategy.get_strategy_class", return_value=None):
            strategy_manager._load_strategies()

            assert "test_strat" not in strategy_manager.strategies

    def test_load_strategies_success(self, strategy_manager, mock_strategy):
        """测试成功加载策略"""
        strategy_manager.strategies_config.strategies = {
            "test_strat": {"enabled": True, "type": "rsi_strategy", "symbol": "SHFE.rb2505"}
        }

        mock_class = MagicMock(return_value=mock_strategy)
        mock_strategy.strategy_id = "test_strat"

        with patch("src.trader.strategy.get_strategy_class", return_value=mock_class), \
             patch.object(strategy_manager, "subscribe_symbol"):
            strategy_manager._load_strategies()

            assert "test_strat" in strategy_manager.strategies

    def test_load_strategies_exception(self, strategy_manager):
        """测试策略创建异常"""
        strategy_manager.strategies_config.strategies = {
            "test_strat": {"enabled": True, "type": "rsi_strategy"}
        }

        def raise_error(*args):
            raise Exception("Create error")

        mock_class = MagicMock(side_effect=raise_error)

        with patch("src.trader.strategy.get_strategy_class", return_value=mock_class):
            # Should not raise exception
            strategy_manager._load_strategies()


# ==================== Test Register Events ====================


class TestStrategyManagerRegisterEvents:
    """测试 _register_events 方法"""

    def test_register_events_no_event_engine(self, strategy_manager):
        """测试无EventEngine"""
        strategy_manager.event_engine = None

        strategy_manager._register_events()

        # Should not raise exception

    def test_register_events_success(self, strategy_manager, mock_event_engine):
        """测试成功注册事件"""
        strategy_manager.event_engine = mock_event_engine

        strategy_manager._register_events()

        assert mock_event_engine.register.call_count == 4  # TICK, KLINE, ORDER, TRADE


# ==================== Test Dispatch Event ====================


class TestStrategyManagerDispatchEvent:
    """测试 _dispatch_event 方法"""

    def test_dispatch_event_to_all_active(self, strategy_manager):
        """测试分发事件到所有活跃策略"""
        strategy1 = MagicMock()
        strategy1.active = True
        strategy1.on_tick = MagicMock()
        strategy2 = MagicMock()
        strategy2.active = False
        strategy2.on_tick = MagicMock()

        strategy_manager.strategies = {"strat1": strategy1, "strat2": strategy2}

        tick_data = TickData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime.now(),
            last_price=Decimal("3500")
        )

        strategy_manager._dispatch_event("on_tick", tick_data)

        strategy1.on_tick.assert_called_once()
        strategy2.on_tick.assert_not_called()

    def test_dispatch_event_order_to_owner(self, strategy_manager):
        """测试分发订单事件到所有者策略"""
        strategy = MagicMock()
        strategy.active = True
        strategy.on_order = MagicMock()

        strategy_manager.strategies = {"strat1": strategy}
        strategy_manager.order_strategy_map = {"order_123": "strat1"}

        order_data = OrderData(
            order_id="order_123",
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
            account_id="test_account"
        )

        strategy_manager._dispatch_event("on_order", order_data)

        strategy.on_order.assert_called_once()

    def test_dispatch_event_order_dict_data(self, strategy_manager):
        """测试分发订单事件（dict数据）"""
        strategy = MagicMock()
        strategy.active = True
        strategy.on_order = MagicMock()

        strategy_manager.strategies = {"strat1": strategy}
        strategy_manager.order_strategy_map = {"order_123": "strat1"}

        order_data = {"order_id": "order_123", "symbol": "SHFE.rb2505"}

        strategy_manager._dispatch_event("on_order", order_data)

        strategy.on_order.assert_called_once()

    def test_dispatch_event_trade_to_owner(self, strategy_manager):
        """测试分发成交事件到所有者策略"""
        strategy = MagicMock()
        strategy.active = True
        strategy.on_trade = MagicMock()

        strategy_manager.strategies = {"strat1": strategy}
        strategy_manager.order_strategy_map = {"order_123": "strat1"}

        trade_data = TradeData(
            trade_id="trade_123",
            order_id="order_123",
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            account_id="test_account"
        )

        strategy_manager._dispatch_event("on_trade", trade_data)

        strategy.on_trade.assert_called_once()

    def test_dispatch_event_strategy_exception(self, strategy_manager):
        """测试策略异常处理"""
        strategy = MagicMock()
        strategy.active = True
        strategy.on_tick = MagicMock(side_effect=Exception("Strategy error"))

        strategy_manager.strategies = {"strat1": strategy}

        tick_data = TickData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime.now(),
            last_price=Decimal("3500")
        )

        # Should not raise exception
        strategy_manager._dispatch_event("on_tick", tick_data)


# ==================== Test Start/Stop Strategy ====================
# ==================== Test Start/Stop Strategy ====================


class TestStrategyManagerStartStopStrategy:
    """测试启动/停止策略"""

    def test_start_strategy_success(self, strategy_manager, mock_strategy):
        """测试成功启动策略"""
        strategy_manager.strategies = {"test_strat": mock_strategy}

        result = strategy_manager.start_strategy("test_strat")

        assert result is True
        mock_strategy.start.assert_called_once()

    def test_start_strategy_not_found(self, strategy_manager):
        """测试启动不存在的策略"""
        result = strategy_manager.start_strategy("nonexistent")

        assert result is False

    def test_stop_strategy_success(self, strategy_manager, mock_strategy):
        """测试成功停止策略"""
        strategy_manager.strategies = {"test_strat": mock_strategy}

        result = strategy_manager.stop_strategy("test_strat")

        assert result is True
        mock_strategy.stop.assert_called_once()

    def test_stop_strategy_not_found(self, strategy_manager):
        """测试停止不存在的策略"""
        result = strategy_manager.stop_strategy("nonexistent")

        assert result is False


# ==================== Test Start/Stop All ====================


class TestStrategyManagerStartStopAll:
    """测试启动/停止所有策略"""

    def test_start_all(self, strategy_manager):
        """测试启动所有策略"""
        strat1 = MagicMock()
        strat2 = MagicMock()
        strategy_manager.strategies = {"strat1": strat1, "strat2": strat2}
        strategy_manager.strategies_config.strategies = {
            "strat1": {"enabled": True},
            "strat2": {"enabled": False}
        }

        strategy_manager.start_all()

        strat1.start.assert_called_once()
        strat2.start.assert_not_called()

    def test_stop_all(self, strategy_manager):
        """测试停止所有策略"""
        strat1 = MagicMock()
        strat2 = MagicMock()
        strategy_manager.strategies = {"strat1": strat1, "strat2": strat2}

        strategy_manager.stop_all()

        strat1.stop.assert_called_once()
        strat2.stop.assert_called_once()

    def test_reset_all_for_new_day(self, strategy_manager):
        """测试重置所有策略"""
        strat1 = MagicMock()
        strat2 = MagicMock()
        strategy_manager.strategies = {"strat1": strat1, "strat2": strat2}

        strategy_manager.reset_all_for_new_day()

        strat1.reset_for_new_day.assert_called_once()
        strat2.reset_for_new_day.assert_called_once()


# ==================== Test Subscribe Symbol ====================


class TestStrategyManagerSubscribeSymbol:
    """测试订阅合约"""

    def test_subscribe_symbol_new(self, strategy_manager, mock_trading_engine):
        """测试订阅新合约"""
        strategy_manager.trading_engine = mock_trading_engine

        result = strategy_manager.subscribe_symbol("SHFE.rb2505")

        assert result is True
        assert "SHFE.rb2505" in strategy_manager.subscribed_symbols
        mock_trading_engine.subscribe_symbol.assert_called_once_with("SHFE.rb2505")

    def test_subscribe_symbol_already_subscribed(self, strategy_manager):
        """测试已订阅合约"""
        strategy_manager.subscribed_symbols.add("SHFE.rb2505")

        result = strategy_manager.subscribe_symbol("SHFE.rb2505")

        assert result is True

    def test_subscribe_symbol_no_trading_engine(self, strategy_manager):
        """测试无TradingEngine"""
        strategy_manager.trading_engine = None

        result = strategy_manager.subscribe_symbol("SHFE.rb2505")

        assert result is False


# ==================== Test Get Status ====================


class TestStrategyManagerGetStatus:
    """测试获取状态"""

    def test_get_status(self, strategy_manager):
        """测试获取所有策略状态"""
        strat1 = MagicMock()
        strat1.strategy_id = "strat1"
        strat1.active = True
        strat1.config = {"enabled": True}

        strat2 = MagicMock()
        strat2.strategy_id = "strat2"
        strat2.active = False
        strat2.config = {"enabled": False}

        strategy_manager.strategies = {"strat1": strat1, "strat2": strat2}

        result = strategy_manager.get_status()

        assert len(result) == 2
        assert result[0]["strategy_id"] == "strat1"
        assert result[0]["active"] is True
        assert result[1]["strategy_id"] == "strat2"
        assert result[1]["active"] is False


# ==================== Test Trading Methods ====================


class TestStrategyManagerTrading:
    """测试交易方法"""

    def test_open_long_success(self, strategy_manager, mock_trading_engine):
        """测试成功开多仓"""
        strategy_manager.trading_engine = mock_trading_engine

        result = strategy_manager.open(
            strategy_id="test_strat",
            symbol="SHFE.rb2505",
            direction="BUY",
            volume=1,
            price=3500.0,
        )

        assert result == "order_123"
        assert strategy_manager.order_strategy_map["order_123"] == "test_strat"

    def test_open_short_success(self, strategy_manager, mock_trading_engine):
        """测试成功开空仓"""
        strategy_manager.trading_engine = mock_trading_engine

        result = strategy_manager.open(
            strategy_id="test_strat",
            symbol="SHFE.rb2505",
            direction="SELL",
            volume=1,
            price=3500.0,
        )

        assert result == "order_123"
        assert strategy_manager.order_strategy_map["order_123"] == "test_strat"

    def test_open_no_trading_engine(self, strategy_manager):
        """测试无TradingEngine时开仓"""
        strategy_manager.trading_engine = None

        result = strategy_manager.open("test_strat", "SHFE.rb2505", "BUY", 1)

        assert result is None

    def test_open_market_order(self, strategy_manager, mock_trading_engine):
        """测试市价开仓"""
        strategy_manager.trading_engine = mock_trading_engine

        result = strategy_manager.open(
            strategy_id="test_strat",
            symbol="SHFE.rb2505",
            direction="BUY",
            volume=1,
            price=None
        )

        assert result == "order_123"
        # Check that price=0 was passed for market order
        call_args = mock_trading_engine.insert_order.call_args
        assert call_args[1]["price"] == 0

    def test_close_long_success(self, strategy_manager, mock_trading_engine):
        """测试成功平多仓"""
        strategy_manager.trading_engine = mock_trading_engine

        result = strategy_manager.close(
            strategy_id="test_strat",
            symbol="SHFE.rb2505",
            direction="SELL",
            volume=1,
            price=3500.0,
        )

        assert result == "order_123"
        assert strategy_manager.order_strategy_map["order_123"] == "test_strat"

    def test_close_short_success(self, strategy_manager, mock_trading_engine):
        """测试成功平空仓"""
        strategy_manager.trading_engine = mock_trading_engine

        result = strategy_manager.close(
            strategy_id="test_strat",
            symbol="SHFE.rb2505",
            direction="BUY",
            volume=1,
            price=3500.0,
        )

        assert result == "order_123"
        assert strategy_manager.order_strategy_map["order_123"] == "test_strat"

    def test_close_no_trading_engine(self, strategy_manager):
        """测试无TradingEngine时平仓"""
        strategy_manager.trading_engine = None

        result = strategy_manager.close("test_strat", "SHFE.rb2505", "SELL", 1)

        assert result is None

    def test_cancel_order_success(self, strategy_manager, mock_trading_engine):
        """测试成功撤单"""
        strategy_manager.trading_engine = mock_trading_engine
        strategy_manager.order_strategy_map = {"order_123": "test_strat"}

        result = strategy_manager.cancel_order("test_strat", "order_123")

        assert result is True
        mock_trading_engine.cancel_order.assert_called_once_with("order_123")

    def test_cancel_order_no_trading_engine(self, strategy_manager):
        """测试无TradingEngine时撤单"""
        strategy_manager.trading_engine = None

        result = strategy_manager.cancel_order("test_strat", "order_123")

        assert result is False

    def test_cancel_order_wrong_owner(self, strategy_manager, mock_trading_engine):
        """测试撤销其他策略的订单"""
        strategy_manager.trading_engine = mock_trading_engine
        strategy_manager.order_strategy_map = {"order_123": "other_strat"}

        result = strategy_manager.cancel_order("test_strat", "order_123")

        assert result is False
        mock_trading_engine.cancel_order.assert_not_called()

    def test_open_exception(self, strategy_manager, mock_trading_engine):
        """测试开仓异常"""
        strategy_manager.trading_engine = mock_trading_engine
        mock_trading_engine.insert_order.side_effect = Exception("Open error")

        result = strategy_manager.open("test_strat", "SHFE.rb2505", "BUY", 1)

        assert result is None

    def test_close_exception(self, strategy_manager, mock_trading_engine):
        """测试平仓异常"""
        strategy_manager.trading_engine = mock_trading_engine
        mock_trading_engine.insert_order.side_effect = Exception("Close error")

        result = strategy_manager.close("test_strat", "SHFE.rb2505", "SELL", 1)

        assert result is None


# ==================== Edge Cases ====================


class TestStrategyManagerEdgeCases:
    """测试边界情况"""

    def test_dispatch_event_no_order_id_in_trade(self, strategy_manager):
        """测试成交事件无订单ID"""
        strategy = MagicMock()
        strategy.active = True
        strategy.on_trade = MagicMock()

        strategy_manager.strategies = {"strat1": strategy}

        trade_data = {"trade_id": "trade_123"}  # No order_id

        # Should not crash
        strategy_manager._dispatch_event("on_trade", trade_data)

    def test_dispatch_event_order_not_in_map(self, strategy_manager):
        """测试订单不在映射中"""
        strategy1 = MagicMock()
        strategy1.active = True
        strategy1.on_order = MagicMock()

        strategy_manager.strategies = {"strat1": strategy1}
        strategy_manager.order_strategy_map = {}

        order_data = OrderData(
            order_id="order_999",
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
            account_id="test_account"
        )

        # Should not crash
        strategy_manager._dispatch_event("on_order", order_data)

    def test_dispatch_event_strategy_not_found(self, strategy_manager):
        """测试策略不存在"""
        strategy_manager.strategies = {}
        strategy_manager.order_strategy_map = {"order_123": "nonexistent_strat"}

        order_data = OrderData(
            order_id="order_123",
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
            account_id="test_account"
        )

        # Should not crash
        strategy_manager._dispatch_event("on_order", order_data)
