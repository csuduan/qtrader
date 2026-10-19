"""ManagerDataFeed 交易日历加载单元测试"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd

from qtrader.manager.data_feed import calc_bar_trading_day, load_trading_dates


def _make_api(calendar: pd.DataFrame) -> MagicMock:
    api = MagicMock()
    api.get_trading_calendar.return_value = calendar
    return api


class TestLoadTradingDates:
    """load_trading_dates"""

    def test_parses_datetime64_date_column(self):
        """date列为datetime64（tqsdk实际返回类型）时应正确解析出日期"""
        api = _make_api(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-10-14", "2026-10-15", "2026-10-16"]),
                    "trading": [True, False, True],
                }
            )
        )
        assert load_trading_dates(api) == [date(2026, 10, 14), date(2026, 10, 16)]

    def test_filters_non_trading_days(self):
        """只保留trading为真的日期"""
        api = _make_api(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-10-17", "2026-10-18"]),
                    "trading": [False, False],
                }
            )
        )
        assert load_trading_dates(api) == []

    def test_result_sorted_ascending(self):
        """结果按日期升序"""
        api = _make_api(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-10-16", "2026-10-13"]),
                    "trading": [True, True],
                }
            )
        )
        assert load_trading_dates(api) == [date(2026, 10, 13), date(2026, 10, 16)]

    def test_none_api_returns_empty(self):
        """api为None返回空列表"""
        assert load_trading_dates(None) == []

    def test_query_failure_returns_empty(self):
        """查询异常时回退空列表（调用方按自然日近似）"""
        api = MagicMock()
        api.get_trading_calendar.side_effect = RuntimeError("network down")
        assert load_trading_dates(api) == []


class TestCalcBarTradingDay:
    """calc_bar_trading_day"""

    def setup_method(self):
        self.trading_dates = [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19)]

    def test_day_session_bars_belong_to_same_day(self):
        """白盘bar（3~20点）归当天"""
        assert calc_bar_trading_day(datetime(2026, 10, 16, 9, 30), self.trading_dates) == date(
            2026, 10, 16
        )

    def test_night_bar_before_midnight_belongs_to_next_trading_day(self):
        """夜盘bar（>=20点）归下一交易日"""
        assert calc_bar_trading_day(datetime(2026, 10, 16, 21, 0), self.trading_dates) == date(
            2026, 10, 19
        )

    def test_night_bar_after_midnight_belongs_to_same_session_day(self):
        """凌晨夜盘bar（<3点）归前一晚锚点的下一交易日"""
        assert calc_bar_trading_day(datetime(2026, 10, 17, 2, 59), self.trading_dates) == date(
            2026, 10, 19
        )

    def test_empty_calendar_falls_back_to_anchor_day(self):
        """日历不可用时夜盘bar按锚点日近似"""
        assert calc_bar_trading_day(datetime(2026, 10, 16, 21, 0), []) == date(2026, 10, 16)


def test_load_trading_dates_called_with_expected_range():
    """查询范围应为 now-days_back 到 now+30天"""
    api = _make_api(
        pd.DataFrame({"date": pd.to_datetime([]), "trading": pd.Series([], dtype=bool)})
    )
    load_trading_dates(api, days_back=10)
    start, end = api.get_trading_calendar.call_args.args
    now = datetime.now()
    assert (now - timedelta(days=10)).date() == start.date()
    assert (now + timedelta(days=30)).date() == end.date()
