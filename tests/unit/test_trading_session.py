"""
交易时段判断测试

覆盖：日盘边界（小节休息/午休）、夜盘跨零点、周末规则、
合约代码交易所解析、未知交易所保守放行。
"""

from datetime import datetime, timedelta

import pytest

from qtrader.models.object import Exchange
from qtrader.utils.trading_session import (
    SESSIONS,
    is_symbol_trading_time,
    is_trading_time,
    parse_exchange_from_symbol,
)


def _dt(weekday: int, hh: int, mm: int = 0) -> datetime:
    """构造指定星期与时刻的 datetime（2026-09-06 是周日）"""
    base = datetime(2026, 9, 6)  # 周日
    return base + timedelta(days=(weekday + 1), hours=hh, minutes=mm)


@pytest.mark.unit
class TestParseExchange:
    """合约代码交易所解析"""

    def test_prefixed(self):
        assert parse_exchange_from_symbol("SHFE.rb2505") == Exchange.SHFE
        assert parse_exchange_from_symbol("CFFEX.IF2509") == Exchange.CFFEX

    def test_suffixed(self):
        assert parse_exchange_from_symbol("rb2505.SHFE") == Exchange.SHFE

    def test_case_insensitive(self):
        assert parse_exchange_from_symbol("shfe.rb2505") == Exchange.SHFE

    def test_bare_symbol_unresolvable(self):
        assert parse_exchange_from_symbol("rb2505") is None

    def test_unknown_exchange(self):
        assert parse_exchange_from_symbol("NASDAQ.AAPL") is None


@pytest.mark.unit
class TestDaySession:
    """日盘时段判断（商品期货：10:15-10:30 小节休息、11:30-13:30 午休）"""

    @pytest.mark.parametrize(
        "hh,mm,expected",
        [
            (8, 59, False),  # 开盘前
            (9, 0, True),  # 开盘
            (10, 14, True),  # 小节休息前
            (10, 15, True),  # 边界含开始（收尾单可入）
            (10, 16, False),  # 小节休息中
            (10, 29, False),
            (10, 30, True),  # 休息结束
            (11, 29, True),
            (11, 31, False),  # 午休
            (13, 29, False),
            (13, 30, True),  # 下午开盘
            (15, 0, True),  # 收盘
            (15, 1, False),  # 收盘后
        ],
    )
    def test_shfe_day_boundaries(self, hh, mm, expected):
        assert is_trading_time(Exchange.SHFE, _dt(1, hh, mm)) is expected

    def test_cffex_no_break(self):
        """中金所无小节休息：10:20 可交易；但有午休且下午 13:00 开盘"""
        assert is_trading_time(Exchange.CFFEX, _dt(1, 10, 20)) is True
        assert is_trading_time(Exchange.CFFEX, _dt(1, 9, 20)) is False  # 9:30 开盘
        assert is_trading_time(Exchange.CFFEX, _dt(1, 12, 30)) is False  # 午休
        assert is_trading_time(Exchange.CFFEX, _dt(1, 13, 30)) is True


@pytest.mark.unit
class TestNightSession:
    """夜盘时段判断（跨零点）"""

    def test_shfe_night_cross_midnight(self):
        """上期所夜盘 21:00-次日02:30"""
        assert is_trading_time(Exchange.SHFE, _dt(1, 21, 0)) is True  # 周一晚开始
        assert is_trading_time(Exchange.SHFE, _dt(1, 23, 59)) is True
        assert is_trading_time(Exchange.SHFE, _dt(2, 1, 0)) is True  # 周二凌晨
        assert is_trading_time(Exchange.SHFE, _dt(2, 2, 30)) is True
        assert is_trading_time(Exchange.SHFE, _dt(2, 2, 31)) is False  # 夜盘收盘后
        assert is_trading_time(Exchange.SHFE, _dt(2, 3, 0)) is False

    def test_dce_night_same_day(self):
        """大商所夜盘 21:00-23:30（当日收尾）"""
        assert is_trading_time(Exchange.DCE, _dt(3, 22, 0)) is True
        assert is_trading_time(Exchange.DCE, _dt(3, 23, 30)) is True
        assert is_trading_time(Exchange.DCE, _dt(4, 0, 0)) is False  # 次日零点后

    def test_saturday_night_ended(self):
        """周六：凌晨夜盘延续交易，白天与晚上不交易"""
        assert is_trading_time(Exchange.SHFE, _dt(5, 1, 0)) is True  # 周六凌晨
        assert is_trading_time(Exchange.SHFE, _dt(5, 3, 0)) is False  # 夜盘收盘后
        assert is_trading_time(Exchange.SHFE, _dt(5, 10, 0)) is False  # 周六白天
        assert is_trading_time(Exchange.SHFE, _dt(5, 21, 30)) is False  # 周六晚无夜盘

    def test_sunday_no_trading(self):
        assert is_trading_time(Exchange.SHFE, _dt(6, 10, 0)) is False
        assert is_trading_time(Exchange.SHFE, _dt(6, 1, 0)) is False

    def test_cffex_no_night(self):
        assert is_trading_time(Exchange.CFFEX, _dt(1, 21, 30)) is False


@pytest.mark.unit
class TestSymbolLevel:
    """合约级判断与保守放行"""

    def test_symbol_with_exchange(self):
        assert is_symbol_trading_time("SHFE.rb2505", _dt(1, 10, 10)) is True
        assert is_symbol_trading_time("SHFE.rb2505", _dt(1, 10, 16)) is False

    def test_bare_symbol_passes(self):
        """裸合约代码无法解析交易所：保守放行（交易所拒单兜底）"""
        assert is_symbol_trading_time("rb2505", _dt(6, 10, 0)) is True

    def test_unknown_exchange_passes(self):
        assert is_trading_time(Exchange.SSE, _dt(6, 10, 0)) is True

    def test_session_table_covers_all_futures_exchanges(self):
        for exchange in (
            Exchange.CFFEX,
            Exchange.SHFE,
            Exchange.CZCE,
            Exchange.DCE,
            Exchange.INE,
            Exchange.GFEX,
        ):
            assert exchange in SESSIONS
