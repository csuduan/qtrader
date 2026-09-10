"""
BarGenerator 单元测试
覆盖：bar周期切分、增量成交量语义（含累计值回绕）、bar完成与回调、查询接口
"""

from datetime import datetime

import pytest

from qtrader.models.object import TickData
from qtrader.utils.bar_generator import BarGenerator


def make_tick(
    dt: datetime,
    last_price: float = 3500.0,
    volume: float = 100.0,
    turnover: float = 350000.0,
    open_interest: float = 50000.0,
    trading_day: str | None = None,
) -> TickData:
    """构造测试用tick（volume/turnover为当日累计值）"""
    return TickData.model_construct(
        symbol="rb2505",
        datetime=dt,
        last_price=last_price,
        volume=volume,
        turnover=turnover,
        open_interest=open_interest,
        trading_day=trading_day,
    )


@pytest.mark.unit
class TestBarGeneratorInit:
    """初始化与订阅"""

    def test_bar_generator_initialization(self):
        gen = BarGenerator("rb2505")
        assert gen.symbol == "rb2505"
        assert len(gen._current_bars) == 0
        assert len(gen._completed_bars) == 0

    def test_subscribe_valid_interval(self):
        gen = BarGenerator("rb2505")
        assert gen.subscribe("M1") is True
        assert gen.subscribe("M5") is True
        assert gen.subscribe("D1") is True

    def test_subscribe_invalid_interval(self):
        gen = BarGenerator("rb2505")
        assert gen.subscribe("XX") is False


@pytest.mark.unit
class TestBarStart:
    """bar周期起点计算"""

    def test_minute_bar_start(self):
        gen = BarGenerator("rb2505")
        tick = make_tick(datetime(2024, 1, 1, 9, 30, 45))
        assert gen._get_bar_start_time(tick, 1) == datetime(2024, 1, 1, 9, 30, 0)

    def test_minute_bar_start_5min(self):
        gen = BarGenerator("rb2505")
        tick = make_tick(datetime(2024, 1, 1, 9, 37, 20))
        assert gen._get_bar_start_time(tick, 5) == datetime(2024, 1, 1, 9, 35, 0)

    def test_hour_bar_start(self):
        gen = BarGenerator("rb2505")
        tick = make_tick(datetime(2024, 1, 1, 9, 30, 45))
        assert gen._get_bar_start_time(tick, 60) == datetime(2024, 1, 1, 9, 0, 0)

    def test_daily_bar_start_uses_trading_day(self):
        """夜盘tick按交易日归属，避免同一交易日被切成两根日线"""
        gen = BarGenerator("rb2505")
        # 周五夜盘21:00，交易日为下周一
        tick = make_tick(datetime(2024, 1, 5, 21, 0, 0), trading_day="20240108")
        assert gen._get_bar_start_time(tick, 1440) == datetime(2024, 1, 8)

    def test_daily_bar_start_dashed_trading_day(self):
        """trading_day 支持 YYYY-MM-DD 与 YYYYMMDD 两种格式"""
        gen = BarGenerator("rb2505")
        tick = make_tick(datetime(2024, 1, 8, 9, 0, 0), trading_day="2024-01-08")
        assert gen._get_bar_start_time(tick, 1440) == datetime(2024, 1, 8)

    def test_daily_bar_start_fallback_natural_day(self):
        """无交易日信息时退化为自然日"""
        gen = BarGenerator("rb2505")
        tick = make_tick(datetime(2024, 1, 8, 21, 30, 0), trading_day=None)
        assert gen._get_bar_start_time(tick, 1440) == datetime(2024, 1, 8, 0, 0, 0)


@pytest.mark.unit
class TestIncrement:
    """增量成交量语义：tick.volume为当日累计值"""

    def test_first_tick_delta_is_zero(self):
        gen = BarGenerator("rb2505")
        delta_v, delta_t = gen._calc_increment(
            make_tick(datetime(2024, 1, 1, 9, 0, 0), volume=100)
        )
        assert delta_v == 0
        assert delta_t == 0

    def test_delta_is_difference(self):
        gen = BarGenerator("rb2505")
        gen._calc_increment(make_tick(datetime(2024, 1, 1, 9, 0, 0), volume=100))
        delta_v, _ = gen._calc_increment(make_tick(datetime(2024, 1, 1, 9, 0, 1), volume=130))
        assert delta_v == 30

    def test_wraparound_counts_full_volume(self):
        """累计值回绕（跨交易日重置）时按全量计"""
        gen = BarGenerator("rb2505")
        gen._calc_increment(make_tick(datetime(2024, 1, 1, 9, 0, 0), volume=5000, turnover=1e7))
        delta_v, delta_t = gen._calc_increment(
            make_tick(datetime(2024, 1, 1, 21, 0, 0), volume=10, turnover=30000)
        )
        assert delta_v == 10
        assert delta_t == 30000


@pytest.mark.unit
class TestBarGeneration:
    """bar生成流程"""

    def test_m1_bar_completion(self):
        gen = BarGenerator("rb2505")
        gen.subscribe("M1")

        # 同一分钟内两个tick：不产出bar
        bars = gen.update_tick(
            make_tick(datetime(2024, 1, 1, 9, 30, 10), last_price=3500, volume=100)
        )
        bars += gen.update_tick(
            make_tick(datetime(2024, 1, 1, 9, 30, 40), last_price=3510, volume=150)
        )
        assert bars == []

        # 下一分钟的tick：完成上一根bar
        bars = gen.update_tick(
            make_tick(datetime(2024, 1, 1, 9, 31, 5), last_price=3520, volume=200)
        )
        assert len(bars) == 1
        bar = bars[0]
        assert bar.open_price == 3500
        assert bar.high_price == 3510
        assert bar.low_price == 3500
        assert bar.close_price == 3510
        # 增量：0 + 50
        assert bar.volume == 50
        assert bar.datetime == datetime(2024, 1, 1, 9, 30, 0)

    def test_completion_callback(self):
        completed = []

        gen = BarGenerator("rb2505")
        gen.subscribe("M1", callback=completed.append)

        gen.update_tick(make_tick(datetime(2024, 1, 1, 9, 30, 10), volume=100))
        gen.update_tick(make_tick(datetime(2024, 1, 1, 9, 31, 10), volume=120))

        assert len(completed) == 1

    def test_multi_interval_completion(self):
        """同tick驱动多周期，各自产出bar"""
        gen = BarGenerator("rb2505")
        gen.subscribe("M1")
        gen.subscribe("M5")

        bars = gen.update_tick(make_tick(datetime(2024, 1, 1, 9, 30, 10), volume=100))
        assert bars == []

        # 9:31 越过 M1 边界；9:35:30 同时越 M5 边界
        bars = gen.update_tick(make_tick(datetime(2024, 1, 1, 9, 35, 30), volume=300))
        assert {b.interval for b in bars} == {"M1", "M5"}


@pytest.mark.unit
class TestBarQuery:
    """bar查询接口"""

    def test_get_bar_returns_none_when_no_bars(self):
        gen = BarGenerator("rb2505")
        gen.subscribe("M1")
        assert gen.get_bar("M1") is None

    def test_get_bars_returns_empty_when_no_bars(self):
        gen = BarGenerator("rb2505")
        gen.subscribe("M1")
        assert gen.get_bars("M1") == []

    def test_get_completed_bars(self):
        gen = BarGenerator("rb2505")
        gen.subscribe("M1")
        for minute in (0, 1, 2):
            gen.update_tick(
                make_tick(datetime(2024, 1, 1, 9, 30 + minute, 10), volume=100 + minute * 10)
            )
            gen.update_tick(
                make_tick(datetime(2024, 1, 1, 9, 30 + minute, 40), volume=110 + minute * 10)
            )
        # 3个tick分钟 → 前两分钟各完成一根（第三分钟未结束）
        bars = gen.get_bars("M1")
        assert len(bars) == 2
        assert bars[-1].datetime == datetime(2024, 1, 1, 9, 31, 0)
        latest = gen.get_bar("M1")
        assert latest.datetime == datetime(2024, 1, 1, 9, 31, 0)
