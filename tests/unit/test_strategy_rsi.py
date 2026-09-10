"""
RSI 策略单元测试

覆盖纯函数（roll_mean_right/calc_rsi_sma）、K线重采样锚点逻辑、
信号生成阈值判断、止盈止损与外部信号过滤。不依赖交易引擎。
"""

import math
from collections import deque
from datetime import datetime, time
from unittest.mock import MagicMock

import pytest

from qtrader.models.object import BarData
from qtrader.trader.strategy.base_strategy import Signal
from qtrader.trader.strategy.strategy_rsi import (
    RsiParam,
    RsiStrategy,
    calc_rsi_sma,
    roll_mean_right,
)


def make_bar(
    dt: datetime,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
    volume: float = 10.0,
    symbol: str = "IM2603",
) -> BarData:
    return BarData(
        symbol=symbol,
        interval="M1",
        datetime=dt,
        open_price=open_,
        high_price=high,
        low_price=low,
        close_price=close,
        volume=volume,
    )


@pytest.fixture
def strategy() -> RsiStrategy:
    config = MagicMock()
    config.symbol = "IM2603"
    config.volume = 1
    config.bar = "M1"
    config.params = {
        "symbol": "IM2603",
        "rsi_n": 3,
        "short_k": 5,
        "long_k": 15,
        "take_profit_pct": 0.05,
        "stop_loss_pct": 0.05,
    }
    s = RsiStrategy("rsi_001", config)
    # 手动补齐 init() 中与引擎无关的状态
    s.signal = None
    s.param = RsiParam(**config.params)
    s.symbol = s.param.symbol
    s.volume = s.param.volume
    s.short_k_bars = deque()
    s.long_k_bars = deque()
    s._short_bar_buf = []
    s._long_bar_buf = []
    return s


@pytest.mark.unit
class TestRollMeanRight:
    """右对齐滚动均值"""

    def test_basic_mean(self):
        assert roll_mean_right([1, 2, 3, 4], 2) == 3.5

    def test_n_equals_1_returns_last(self):
        assert roll_mean_right([1, 2, 3], 1) == 3.0

    def test_too_short_returns_nan(self):
        assert math.isnan(roll_mean_right([1], 2))

    def test_non_positive_n_returns_nan(self):
        assert math.isnan(roll_mean_right([1, 2], 0))

    def test_ignores_non_finite(self):
        values = [1.0, float("nan"), 3.0]
        # 最后2个值中仅3.0有限，均值为3.0
        assert roll_mean_right(values, 2) == 3.0


@pytest.mark.unit
class TestCalcRsiSma:
    """SMA 口径 RSI"""

    def test_monotonic_rise_is_100(self):
        values = [float(i) for i in range(10)]
        assert calc_rsi_sma(values, 5) == pytest.approx(100.0)

    def test_monotonic_fall_is_zero(self):
        values = [float(10 - i) for i in range(10)]
        assert calc_rsi_sma(values, 5) == 0.0

    def test_flat_is_zero(self):
        values = [5.0] * 10
        assert calc_rsi_sma(values, 5) == 0.0

    def test_short_series_returns_nan(self):
        assert math.isnan(calc_rsi_sma([1.0], 5))

    def test_hand_computed(self):
        # 涨跌各半：AU=AD → RS=1 → RSI=50
        values = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
        assert calc_rsi_sma(values, 2) == pytest.approx(50.0)


@pytest.mark.unit
class TestResampleKline:
    """K线重采样（09:30 锚点）"""

    def test_before_anchor_skipped(self, strategy):
        bar = make_bar(datetime(2026, 9, 3, 9, 20))
        assert strategy._resample_kline(bar) == (None, None)
        assert strategy._short_bar_buf == []  # 不进缓存

    def test_short_bar_built_every_short_k(self, strategy):
        bars = []
        for i in range(5):
            dt = datetime(2026, 9, 3, 9, 30 + i)
            bar = make_bar(dt, open_=100 + i, high=102 + i, low=99 + i, close=101 + i)
            bars.append(bar)
            short, long_ = strategy._resample_kline(bar)

        # 第5根（9:34，min_idx=4，(4+1)%5==0）触发 short bar
        assert short is not None
        assert long_ is None  # long_k=15 未到
        assert short.open_price == 100
        assert short.close_price == 105
        assert short.high_price == 106
        assert short.low_price == 99
        assert len(strategy.short_k_bars) == 1
        assert strategy._short_bar_buf == []

    def test_long_bar_built_every_long_k(self, strategy):
        short_count = 0
        long_count = 0
        for i in range(15):
            dt = datetime(2026, 9, 3, 9, 30 + i)
            short, long_ = strategy._resample_kline(make_bar(dt))
            if short:
                short_count += 1
            if long_:
                long_count += 1

        assert short_count == 3  # 9:34 / 9:39 / 9:44
        assert long_count == 1  # 9:44


@pytest.mark.unit
class TestGenerateSignal:
    """RSI 交叉信号"""

    def test_insufficient_bars(self, strategy):
        strategy.short_k_bars.append(make_bar(datetime(2026, 9, 3, 9, 34)))
        assert strategy._generate_signal() == 0

    def test_rising_gives_long_signal(self, strategy):
        for i in range(6):
            bar = make_bar(datetime(2026, 9, 3, 9, 34), close=100.0 + i)
            strategy.short_k_bars.append(bar)
            strategy.long_k_bars.append(bar)
        assert strategy._generate_signal() == 1

    def test_falling_gives_short_signal(self, strategy):
        for i in range(6):
            bar = make_bar(datetime(2026, 9, 3, 9, 34), close=100.0 - i)
            strategy.short_k_bars.append(bar)
            strategy.long_k_bars.append(bar)
        assert strategy._generate_signal() == -1

    def test_flat_gives_short_signal(self, strategy):
        # 横盘时 RSI=0，低于空头阈值（100-阈值），按实际行为判定为空头信号
        for _ in range(6):
            bar = make_bar(datetime(2026, 9, 3, 9, 34), close=100.0)
            strategy.short_k_bars.append(bar)
            strategy.long_k_bars.append(bar)
        assert strategy._generate_signal() == -1


@pytest.mark.unit
class TestExitConditions:
    """止盈止损"""

    def test_long_take_profit(self, strategy):
        signal = Signal(side=1, entry_price=100.0)
        assert strategy._check_exit_conditions(106.0, signal) == "TP"

    def test_long_stop_loss(self, strategy):
        signal = Signal(side=1, entry_price=100.0)
        assert strategy._check_exit_conditions(94.0, signal) == "SL"

    def test_long_hold(self, strategy):
        signal = Signal(side=1, entry_price=100.0)
        assert strategy._check_exit_conditions(101.0, signal) is None

    def test_short_take_profit(self, strategy):
        signal = Signal(side=-1, entry_price=100.0)
        assert strategy._check_exit_conditions(94.0, signal) == "TP"

    def test_short_stop_loss(self, strategy):
        signal = Signal(side=-1, entry_price=100.0)
        assert strategy._check_exit_conditions(106.0, signal) == "SL"


@pytest.mark.unit
class TestExternalSignalFilter:
    """外部信号过滤"""

    def test_zero_external_blocks(self, strategy):
        strategy.param.used_signal = 0
        assert strategy._check_external_signal_filter(1) is False

    def test_matching_direction_passes(self, strategy):
        strategy.param.used_signal = 1
        assert strategy._check_external_signal_filter(1) is True

    def test_mismatched_direction_blocks(self, strategy):
        strategy.param.used_signal = -1
        assert strategy._check_external_signal_filter(1) is False


@pytest.mark.unit
class TestUpdateParams:
    """参数热更新"""

    def test_time_string_parsed(self, strategy):
        strategy.update_params({"trade_start_time": "10:30:00", "volume": 3})
        assert strategy.param.trade_start_time == time(10, 30)
        assert strategy.param.volume == 3

    def test_unknown_key_ignored(self, strategy):
        strategy.update_params({"no_such_param": 1})  # 仅告警，不抛错

    def test_invalid_time_falls_back(self, strategy):
        strategy.update_params({"trade_start_time": "bad"})
        assert strategy.param.trade_start_time == time(0, 0, 0)
