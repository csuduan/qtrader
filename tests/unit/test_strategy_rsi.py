"""
RSI 策略单元测试

覆盖纯函数（roll_mean_right/calc_rsi_sma）、K线重采样锚点逻辑、
信号生成阈值判断、止盈止损与外部信号过滤。不依赖交易引擎。
"""

import asyncio
import math
from collections import deque
from datetime import datetime, time, timedelta
from unittest.mock import MagicMock

import pytest

from qtrader.models.object import BarData
from qtrader.trader.strategy.base_strategy import Signal
from qtrader.trader.strategy.strategy_rsi import (
    RsiParam,
    RsiStrategy,
    calc_rsi_sma,
    hv_side,
    roll_mean_right,
)
from qtrader.utils.config_loader import StrategyConfig


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


# ==================== Test Symbol Change (换月) ====================


@pytest.fixture
def strategy_config() -> StrategyConfig:
    """创建RSI策略配置（换月场景需完整init）"""
    return StrategyConfig(
        enabled=True,
        type="rsi_strategy",
        symbol="IM2609",
        exchange="CFFEX",
        volume=1,
        bar="M1",
        params={"symbol": "IM2609", "volume": 1},
    )


def _bar_at(minute: int, symbol: str = "IM2610") -> BarData:
    """创建9:30锚点后的M1测试bar"""
    return make_bar(datetime(2026, 9, 17, 9, minute), symbol=symbol)


class TestRsiStrategySymbolChange:
    """换月清理K线缓存测试"""

    def test_symbol_change_clears_bar_caches(self, strategy_config: StrategyConfig):
        """测试换月后清空老合约的指标缓存"""
        strategy = RsiStrategy("rsi_test", strategy_config)
        asyncio.run(strategy.init(datetime.now()))
        bar = _bar_at(31, "IM2609")
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
        strategy.short_k_bars.append(_bar_at(31, "IM2609"))

        strategy.update_params({"volume": 2})

        assert strategy.symbol == "IM2609"
        assert len(strategy.short_k_bars) == 1

    def test_symbol_change_clears_signal(self, strategy_config: StrategyConfig):
        """测试换月时清理基于老合约价格产生的活跃信号"""
        strategy = RsiStrategy("rsi_test", strategy_config)
        asyncio.run(strategy.init(datetime.now()))
        strategy.update_signal({"side": 1, "entry_price": 4000.0})
        assert strategy.signal is not None

        strategy.update_params({"symbol": "IM2610"})

        assert strategy.symbol == "IM2610"
        assert strategy.signal is None

    def test_symbol_change_syncs_config_for_replay(self, strategy_config: StrategyConfig):
        """测试盘中切换合约后配置同步，手动回播重新 init 时不回读老合约"""
        strategy = RsiStrategy("rsi_test", strategy_config)
        asyncio.run(strategy.init(datetime.now()))
        assert strategy.config.params["symbol"] == "IM2609"

        strategy.update_params({"symbol": "IM2610"})

        assert strategy.config.params["symbol"] == "IM2610"
        # 重新 init（回播第一步）应使用新合约
        asyncio.run(strategy.init(datetime.now()))
        assert strategy.symbol == "IM2610"


# ==================== Test High-Vol Mode (高波模式) ====================

HV_TRADING_DAY = datetime(2026, 11, 23)  # 周一


@pytest.fixture
def hv_strategy() -> RsiStrategy:
    """高波模式（mode=1）AM行策略，IM品种，止损1.5%"""
    config = MagicMock()
    config.symbol = "IM2612"
    config.volume = 1
    config.bar = "M1"
    config.params = {
        "symbol": "IM2612",
        "mode": 1,
        "rsi_n": 3,
        "short_k": 5,
        "long_k": 15,
        "trade_start_time": time(10, 0),
        "trade_end_time": time(13, 25),
        "force_exit_time": time(14, 55),
        "take_profit_pct": 0.015,
        "stop_loss_pct": 0.015,
    }
    s = RsiStrategy("StrRsiInDay-AM-IM01", config)
    s.signal = None
    s.param = RsiParam(**config.params)
    s.symbol = s.param.symbol
    s.volume = s.param.volume
    s.short_k_bars = deque()
    s.long_k_bars = deque()
    s._short_bar_buf = []
    s._long_bar_buf = []
    s.trading_day = HV_TRADING_DAY
    s._prev_close = None
    s._day_open = None
    s._day_bar_count = 0
    s._hv_decided = False
    return s


def feed_hv_bar(strategy: RsiStrategy, dt: datetime, open_: float, close: float) -> None:
    """喂一根M1给策略（高波测试专用）"""
    bar = make_bar(dt, open_=open_, close=close, symbol="IM2612")
    asyncio.run(strategy.on_bar(bar))


def feed_prev_day_close(strategy: RsiStrategy, close: float) -> None:
    """喂前一交易日最后一根M1，建立昨收"""
    feed_hv_bar(strategy, datetime(2026, 11, 20, 14, 59), close, close)


def feed_first_15_min(
    strategy: RsiStrategy, day_open: float, closes: list[float], skip_minutes: tuple[int, ...] = ()
) -> None:
    """
    喂当日09:30-09:44的M1（closes长度15，索引即分钟偏移）
    skip_minutes 指定跳过的分钟偏移，用于模拟行情缺数
    """
    for m in range(15):
        if m in skip_minutes:
            continue
        close = closes[m]
        feed_hv_bar(
            strategy,
            HV_TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=m),
            day_open,
            close,
        )


@pytest.mark.unit
class TestHvSide:
    """高波09:45方向判定纯函数（对接说明定稿口径）"""

    def test_gap_and_move_same_direction_long(self) -> None:
        assert hv_side(4710.0, 4700.0, 4720.0) == 1

    def test_gap_and_move_same_direction_short(self) -> None:
        assert hv_side(4690.0, 4700.0, 4680.0) == -1

    def test_rebound_passes_floor_and_recovers_prev_close(self) -> None:
        # 高开+1回落：回到昨收下方且回撤0.53%>=0.35%，沿回补方向开空
        assert hv_side(4720.0, 4700.0, 4695.0) == -1

    def test_rebound_not_reaching_prev_close_blocks(self) -> None:
        # 回落但未回到昨收
        assert hv_side(4720.0, 4700.0, 4710.0) == 0

    def test_rebound_below_floor_blocks(self) -> None:
        # 恰好回到昨收但幅度仅0.13%<0.35%
        assert hv_side(4706.0, 4700.0, 4700.0) == 0

    def test_rebound_exactly_at_floor_opens(self) -> None:
        # 低开回升：恰好回到昨收且幅度恰好0.35%，边界可开仓
        assert hv_side(10000.0, 10035.0, 10035.0) == 1

    def test_flat_open_blocks(self) -> None:
        # 平开（今开==昨收）gap=0
        assert hv_side(4700.0, 4700.0, 4710.0) == 0

    def test_flat_move_blocks(self) -> None:
        # 09:45收盘==今开 move=0
        assert hv_side(4710.0, 4700.0, 4710.0) == 0


@pytest.mark.unit
class TestHvOnBarFlow:
    """高波模式on_bar流程：09:45开仓、退出规则"""

    def test_am_row_opens_at_0945(self, hv_strategy: RsiStrategy) -> None:
        """顺跳空：昨收4700/今开4710/09:45收4720 → 09:44 bar收盘即开多"""
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        feed_first_15_min(hv_strategy, 4710.0, closes)

        assert hv_strategy.signal is not None
        assert hv_strategy.signal.side == 1
        assert hv_strategy.signal.entry_price == 4720.0
        assert hv_strategy.signal.entry_time == time(9, 44)

    def test_pm_row_never_opens(self, hv_strategy: RsiStrategy) -> None:
        """下午行（trade_start_time=13:30）高波日不开仓"""
        hv_strategy.param.trade_start_time = time(13, 30)
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        feed_first_15_min(hv_strategy, 4710.0, closes)

        assert hv_strategy.signal is None
        assert hv_strategy._hv_decided is True

    def test_incomplete_15min_blocks(self, hv_strategy: RsiStrategy) -> None:
        """前15分钟缺一根M1（数据不完整）按空仓处理"""
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(15)]
        feed_first_15_min(hv_strategy, 4710.0, closes, skip_minutes=(5,))

        assert hv_strategy.signal is None

    def test_missing_prev_close_blocks(self, hv_strategy: RsiStrategy) -> None:
        """无昨收（历史数据缺失）按空仓处理"""
        closes = [4705.0 + i for i in range(15)]
        feed_first_15_min(hv_strategy, 4710.0, closes)

        assert hv_strategy.signal is None

    def test_decide_only_once(self, hv_strategy: RsiStrategy) -> None:
        """09:45判定一次后不再重判：判定空仓后即使行情补齐也不开仓"""
        feed_prev_day_close(hv_strategy, 4700.0)
        # 高开回落但未回补昨收：09:45判定为空仓
        closes = [4710.0 - 0.5 * i for i in range(11)] + [4705.0] * 4
        feed_first_15_min(hv_strategy, 4710.0, closes)
        assert hv_strategy.signal is None
        assert hv_strategy._hv_decided is True

        # 09:45 后价格大幅上冲（若重判将满足顺势条件）
        feed_hv_bar(hv_strategy, HV_TRADING_DAY.replace(hour=9, minute=45), 4720.0, 4740.0)
        assert hv_strategy.signal is None

    def test_stop_loss_confirmed_on_5min_close(self, hv_strategy: RsiStrategy) -> None:
        """止损以完整5分钟K线收盘确认：M1跌破不触发，5分钟bar收盘触发"""
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        feed_first_15_min(hv_strategy, 4710.0, closes)
        assert hv_strategy.signal is not None and hv_strategy.signal.side == 1

        # 09:45-09:48 M1收盘已深跌破止损线（4720*0.985=4649.2），未形成5分钟bar不触发
        for m in range(15, 19):
            feed_hv_bar(
                hv_strategy,
                HV_TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=m),
                4650.0,
                4640.0,
            )
        assert hv_strategy.signal.exit_time is None

        # 09:49 形成09:45-09:49完整5分钟K线，收盘确认止损
        feed_hv_bar(
            hv_strategy,
            HV_TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=19),
            4645.0,
            4640.0,
        )
        assert hv_strategy.signal.exit_reason == "SL"
        assert hv_strategy.signal.exit_price == 4640.0

    def test_no_take_profit_in_hv_mode(self, hv_strategy: RsiStrategy) -> None:
        """高波模式无固定止盈：涨幅超take_profit_pct也不平仓"""
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        feed_first_15_min(hv_strategy, 4710.0, closes)

        # 09:49 5分钟收盘4800，涨幅1.7%>1.5%止盈线，高波模式只查止损
        for m in range(15, 20):
            feed_hv_bar(
                hv_strategy,
                HV_TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=m),
                4790.0,
                4800.0,
            )
        assert hv_strategy.signal.exit_time is None

    def test_force_exit_kept_in_hv_mode(self, hv_strategy: RsiStrategy) -> None:
        """高波模式保留14:55强平"""
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        feed_first_15_min(hv_strategy, 4710.0, closes)
        assert hv_strategy.signal is not None

        feed_hv_bar(hv_strategy, HV_TRADING_DAY.replace(hour=14, minute=55), 4720.0, 4720.0)
        assert hv_strategy.signal.exit_reason == "FORCE"

    def test_rsi_open_disabled_in_hv_mode(self, hv_strategy: RsiStrategy) -> None:
        """高波日停用RSI开仓：即使RSI条件满足也不产生RSI信号"""
        feed_prev_day_close(hv_strategy, 4700.0)
        # 构造单边上涨满足RSI多头条件
        closes = [4700.0 + i * 2 for i in range(15)]
        feed_first_15_min(hv_strategy, 4701.0, closes)

        # 信号若产生只可能来自09:45判定（顺跳空做多）
        assert hv_strategy.signal is not None
        assert hv_strategy.signal.side == 1
        assert hv_strategy.signal.entry_time == time(9, 44)  # 09:44判定，非RSI路径

    def test_mode0_keeps_rsi_path(self, hv_strategy: RsiStrategy) -> None:
        """mode=0沿用RSI：09:44不触发高波判定"""
        hv_strategy.param.mode = 0
        feed_prev_day_close(hv_strategy, 4700.0)
        closes = [4705.0 + i for i in range(15)]
        feed_first_15_min(hv_strategy, 4710.0, closes)

        assert hv_strategy.signal is None
        assert hv_strategy._hv_decided is False


@pytest.mark.unit
class TestHvParams:
    """高波模式参数加载"""

    def test_mode_string_coerced_by_pydantic(self) -> None:
        param = RsiParam(mode="1")
        assert param.mode == 1

    def test_mode_default_zero(self) -> None:
        assert RsiParam().mode == 0

    def test_update_params_mode_string_converted(self, hv_strategy: RsiStrategy) -> None:
        hv_strategy.update_params({"mode": "0"})
        assert hv_strategy.param.mode == 0
        assert hv_strategy.config.params["mode"] == 0
