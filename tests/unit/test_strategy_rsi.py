"""RSI 策略单元测试"""

import asyncio
from datetime import datetime

import pytest

from qtrader.models.object import BarData
from qtrader.trader.strategy.strategy_rsi import RsiParam, RsiStrategy
from qtrader.utils.config_loader import StrategyConfig


@pytest.fixture
def strategy_config() -> StrategyConfig:
    """创建RSI策略配置"""
    return StrategyConfig(
        enabled=True,
        type="rsi_strategy",
        symbol="IM2609",
        exchange="CFFEX",
        volume=1,
        bar="M1",
        params={"symbol": "IM2609", "volume": 1},
    )


def _make_bar(symbol: str, minute: int) -> BarData:
    """创建测试bar"""
    return BarData(
        symbol=symbol,
        interval="M1",
        datetime=datetime(2026, 9, 17, 9, minute),
        open_price=4000.0,
        high_price=4010.0,
        low_price=3990.0,
        close_price=4005.0,
        volume=10.0,
    )


class TestRsiStrategySymbolChange:
    """换月清理K线缓存测试"""

    def test_symbol_change_clears_bar_caches(self, strategy_config: StrategyConfig):
        """测试换月后清空老合约的指标缓存"""
        strategy = RsiStrategy("rsi_test", strategy_config)
        asyncio.run(strategy.init(datetime.now()))
        bar = _make_bar("IM2609", 31)
        strategy.short_k_bars.append(bar)
        strategy.long_k_bars.append(bar)
        strategy._short_bar_buf.append(bar)
        strategy._long_bar_buf.append(bar)

        strategy.update_params({"symbol": "IM2610"})

        assert strategy.symbol == "IM2610"
        assert len(strategy.short_k_bars) == 0
        assert len(strategy.long_k_bars) == 0
        assert len(strategy._short_bar_buf) == 0
        assert len(strategy._long_bar_buf) == 0

    def test_symbol_unchanged_keeps_bar_caches(self, strategy_config: StrategyConfig):
        """测试合约未变化时不清空指标缓存"""
        strategy = RsiStrategy("rsi_test", strategy_config)
        asyncio.run(strategy.init(datetime.now()))
        strategy.short_k_bars.append(_make_bar("IM2609", 31))

        strategy.update_params({"volume": 2})

        assert strategy.symbol == "IM2609"
        assert len(strategy.short_k_bars) == 1
