"""
load_hist_bars 三层数据源合并逻辑测试

数据来源优先级：bars_history 历史表 → 网关内存K线（覆盖）→ bars_today 当日表（补缺）
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from qtrader.trader.strategy_manager import StrategyManager


@pytest.fixture
def mock_trading_engine():
    """模拟TradingEngine"""
    engine = MagicMock()
    engine.get_kline = MagicMock(return_value=None)
    return engine


@pytest.fixture
def strategy_manager(mock_trading_engine):
    """构建 StrategyManager 实例（空策略配置）"""
    return StrategyManager({}, mock_trading_engine)


def _history_po(bar_time: datetime, close: float):
    po = MagicMock()
    po.bar_time = bar_time
    po.open_price = close - 1
    po.high_price = close + 1
    po.low_price = close - 2
    po.close_price = close
    po.volume = 10
    return po


def _today_po(bar_time: datetime, close: float, account_id: str = "OTHER"):
    po = MagicMock()
    po.bar_time = bar_time
    po.open_price = close - 1
    po.high_price = close + 1
    po.low_price = close - 2
    po.close_price = close
    po.volume = 10
    po.account_id = account_id
    return po


def _kline_df(rows: list[tuple[datetime, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "datetime": t,
                "open": c - 1,
                "high": c + 1,
                "low": c - 2,
                "close": c,
                "volume": 10,
            }
            for t, c in rows
        ]
    )


class TestLoadHistBars:
    """load_hist_bars 合并逻辑测试"""

    @pytest.mark.asyncio
    async def test_history_table_only(self, strategy_manager, mock_trading_engine):
        """CTP冷启动：内存无K线，仅历史表有数据"""
        base = datetime(2026, 8, 26, 9, 30)
        dao = MagicMock()
        dao.query_history_bars.return_value = [
            _history_po(base + timedelta(minutes=i), 100.0 + i) for i in range(3)
        ]
        dao.query_today_bars.return_value = []
        mock_trading_engine.get_kline.return_value = None

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            bars = await strategy_manager.load_hist_bars(
                "IM2609", "M1", base, base + timedelta(minutes=2)
            )

        assert len(bars) == 3
        assert [b.close_price for b in bars] == [100.0, 101.0, 102.0]
        assert bars[0].type == "history"

    @pytest.mark.asyncio
    async def test_gateway_memory_overrides_history(self, strategy_manager, mock_trading_engine):
        """网关内存覆盖历史表同时间点的数据"""
        base = datetime(2026, 8, 26, 9, 30)
        dao = MagicMock()
        dao.query_history_bars.return_value = [_history_po(base, 100.0)]
        dao.query_today_bars.return_value = []
        mock_trading_engine.get_kline.return_value = _kline_df([(base, 999.0)])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            bars = await strategy_manager.load_hist_bars(
                "IM2609", "M1", base, base + timedelta(minutes=1)
            )

        assert len(bars) == 1
        assert bars[0].close_price == 999.0  # 内存覆盖

    @pytest.mark.asyncio
    async def test_today_table_fills_gaps(self, strategy_manager, mock_trading_engine):
        """当日表只补内存和历史表都没有的时间点"""
        base = datetime(2026, 8, 27, 9, 30)
        t1, t2, t3 = base, base + timedelta(minutes=1), base + timedelta(minutes=2)
        dao = MagicMock()
        dao.query_history_bars.return_value = []  # 历史表无当日数据
        dao.query_today_bars.return_value = [
            _today_po(t1, 100.0),
            _today_po(t2, 101.0),
            _today_po(t3, 102.0),
        ]
        # 内存仅有 t2（重启后的部分数据）
        mock_trading_engine.get_kline.return_value = _kline_df([(t2, 888.0)])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            bars = await strategy_manager.load_hist_bars("IM2609", "M1", t1, t3)

        assert len(bars) == 3
        closes = {b.datetime: b.close_price for b in bars}
        assert closes[t1] == 100.0  # 当日表补缺
        assert closes[t2] == 888.0  # 内存优先
        assert closes[t3] == 102.0  # 当日表补缺
        # 按时间升序
        times = [b.datetime for b in bars]
        assert times == sorted(times)

    @pytest.mark.asyncio
    async def test_db_error_falls_back_to_gateway(self, strategy_manager, mock_trading_engine):
        """数据库异常时仍走网关内存"""
        base = datetime(2026, 8, 26, 9, 30)
        dao = MagicMock()
        dao.query_history_bars.side_effect = Exception("db down")
        dao.query_today_bars.side_effect = Exception("db down")
        mock_trading_engine.get_kline.return_value = _kline_df([(base, 100.0)])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            bars = await strategy_manager.load_hist_bars("IM2609", "M1", base, base)

        assert len(bars) == 1

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self, strategy_manager, mock_trading_engine):
        base = datetime(2026, 8, 26, 9, 30)
        dao = MagicMock()
        dao.query_history_bars.return_value = []
        dao.query_today_bars.return_value = []
        mock_trading_engine.get_kline.return_value = None

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            bars = await strategy_manager.load_hist_bars(
                "IM2609", "M1", base, base + timedelta(minutes=1)
            )

        assert bars == []


class TestGetHistStart:
    """get_hist_start 交易日回数与回退逻辑测试"""

    @pytest.mark.asyncio
    async def test_returns_trading_day_start(self, strategy_manager):
        """历史表有数据时返回trading_day列回数的起点"""
        dao = MagicMock()
        dao.query_hist_trading_day_start.return_value = datetime(2026, 9, 30, 9, 30)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            start = await strategy_manager.get_hist_start("IM2609", "M1", datetime(2026, 10, 9))

        assert start == datetime(2026, 9, 30, 9, 30)
        dao.query_hist_trading_day_start.assert_called_once_with(
            "IM2609", "M1", date(2026, 10, 9), 5
        )

    @pytest.mark.asyncio
    async def test_falls_back_when_no_data(self, strategy_manager):
        """历史表无数据时回退为自然日估算"""
        dao = MagicMock()
        dao.query_hist_trading_day_start.return_value = None

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            start = await strategy_manager.get_hist_start("IM2609", "M1", datetime(2026, 10, 9))

        assert start == datetime(2026, 10, 4)

    @pytest.mark.asyncio
    async def test_falls_back_on_db_error(self, strategy_manager):
        """查询异常时回退为自然日估算"""
        dao = MagicMock()
        dao.query_hist_trading_day_start.side_effect = Exception("db down")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("qtrader.trader.dao.bar_dao.BarDao", lambda: dao)
            start = await strategy_manager.get_hist_start("IM2609", "M1", datetime(2026, 10, 9))

        assert start == datetime(2026, 10, 4)
