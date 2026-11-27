"""
指标采集器（IndicatorManager）及RSI策略指标采集单元测试

覆盖采集器的重置/记录/去重/导出，以及RSI策略两种模式下
on_bar 过程中的指标数据与信号事件采集。
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from qtrader.models.object import BarData
from qtrader.trader.strategy.indicator_mgr import IndicatorManager
from qtrader.trader.strategy.strategy_rsi import RsiParam, RsiStrategy


def make_bar(
    dt: datetime,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
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
        volume=10.0,
    )


@pytest.mark.unit
class TestIndicatorManager:
    """采集器基础行为"""

    def test_inactive_by_default(self):
        mgr = IndicatorManager()
        assert mgr.to_dict() is None
        # 未激活时所有写入为no-op
        mgr.record_bar(make_bar(datetime(2026, 9, 3, 9, 30)))
        mgr.update_hv(prev_close=100.0)
        mgr.record_event("09:30", "ENTRY", 1, 100.0)
        assert mgr.bars == []
        assert mgr.hv == {}
        assert mgr.events == []

    def test_reset_activates_and_snapshots_params(self):
        mgr = IndicatorManager()
        mgr.reset(datetime(2026, 9, 3), "IM2603", 0, {"rsi_n": 5})
        d = mgr.to_dict()
        assert d is not None
        assert d["trading_day"] == "2026-09-03"
        assert d["symbol"] == "IM2603"
        assert d["mode"] == 0
        assert d["params"] == {"rsi_n": 5}
        assert d["bars"] == []
        assert d["hv"] is None  # 空快照导出为None
        assert d["events"] == []

    def test_record_bar_rounds_rsi(self):
        mgr = IndicatorManager()
        mgr.reset(datetime(2026, 9, 3), "IM2603", 0, {})
        mgr.record_bar(make_bar(datetime(2026, 9, 3, 9, 34), close=101.0), 55.678, None)
        point = mgr.bars[0]
        assert point["time"] == "09:34"
        assert point["close"] == 101.0
        assert point["rsi_short"] == 55.68
        assert point["rsi_long"] is None

    def test_record_bar_dedupes_same_minute(self):
        """回播与实时重叠时同一分钟覆盖而非重复追加"""
        mgr = IndicatorManager()
        mgr.reset(datetime(2026, 9, 3), "IM2603", 0, {})
        mgr.record_bar(make_bar(datetime(2026, 9, 3, 9, 30), close=100.0))
        mgr.record_bar(make_bar(datetime(2026, 9, 3, 9, 30), close=101.0))
        assert len(mgr.bars) == 1
        assert mgr.bars[0]["close"] == 101.0

    def test_update_hv_merges_fields(self):
        mgr = IndicatorManager()
        mgr.reset(datetime(2026, 9, 3), "IM2603", 1, {})
        mgr.update_hv(prev_close=4700.0)
        mgr.update_hv(day_open=4710.0, side=1)
        assert mgr.hv == {"prev_close": 4700.0, "day_open": 4710.0, "side": 1}

    def test_clear_deactivates(self):
        mgr = IndicatorManager()
        mgr.reset(datetime(2026, 9, 3), "IM2603", 0, {})
        mgr.record_bar(make_bar(datetime(2026, 9, 3, 9, 30)))
        mgr.clear()
        assert mgr.to_dict() is None
        assert mgr.bars == []


# ==================== RSI策略指标采集 ====================


def make_rsi_strategy(params: dict, trading_day: datetime) -> RsiStrategy:
    """构建手动补齐状态的RSI策略（不经init，采集器手动激活）"""
    config = MagicMock()
    config.symbol = params["symbol"]
    config.volume = 1
    config.bar = "M1"
    config.params = params
    s = RsiStrategy("rsi_ind", config)
    s.signal = None
    s.param = RsiParam(**params)
    s.symbol = s.param.symbol
    s.volume = s.param.volume
    s.short_k_bars = deque()
    s.long_k_bars = deque()
    s._short_bar_buf = []
    s._long_bar_buf = []
    s.trading_day = trading_day
    s._prev_close = None
    s._day_open = None
    s._day_bar_count = 0
    s._hv_decided = False
    s.indicator_mgr.reset(trading_day, s.symbol, s.param.mode, {"stub": True})
    return s


TRADING_DAY = datetime(2026, 9, 3)


@pytest.mark.unit
class TestRsiModeIndicatorCollect:
    """普通RSI模式（mode=0）指标采集"""

    @pytest.fixture
    def strategy(self) -> RsiStrategy:
        return make_rsi_strategy(
            {
                "symbol": "IM2603",
                "rsi_n": 3,
                "short_k": 5,
                "long_k": 15,
                "used_signal": 1,
                "take_profit_pct": 0.05,
                "stop_loss_pct": 0.05,
            },
            TRADING_DAY,
        )

    def feed(self, strategy: RsiStrategy, minute_offset: int, close: float) -> None:
        dt = TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=minute_offset)
        asyncio.run(strategy.on_bar(make_bar(dt, open_=close, close=close)))

    def test_bars_recorded_with_rsi_at_short_bar_points(self, strategy: RsiStrategy):
        """每根M1入图，RSI值仅在对应周期K线形成且数据充足时非空"""
        for i in range(60):  # 09:30-10:29
            self.feed(strategy, i, 100.0 + i)

        assert len(strategy.indicator_mgr.bars) == 60
        by_time = {p["time"]: p for p in strategy.indicator_mgr.bars}
        # 短周期K线形成前RSI为空
        assert by_time["09:30"]["rsi_short"] is None
        assert by_time["09:44"]["rsi_short"] is None
        # 第4根short bar（09:49，rsi_n+1=4）起短RSI非空，单边上涨RSI=100
        assert by_time["09:49"]["rsi_short"] == 100.0
        # 长周期需4根M15，09:49时仅1根，长RSI仍为空
        assert by_time["09:49"]["rsi_long"] is None
        # 第4根long bar（10:29）起长RSI非空
        assert by_time["10:29"]["rsi_short"] == 100.0
        assert by_time["10:29"]["rsi_long"] == 100.0
        # 非短周期时点为空
        assert by_time["09:50"]["rsi_short"] is None

    def test_prev_day_and_pre_market_bars_not_recorded(self, strategy: RsiStrategy):
        """前一日及09:30前的bar不入图"""
        asyncio.run(
            strategy.on_bar(make_bar(datetime(2026, 9, 2, 14, 59), symbol="IM2603"))
        )
        asyncio.run(strategy.on_bar(make_bar(datetime(2026, 9, 3, 9, 25), symbol="IM2603")))
        assert strategy.indicator_mgr.bars == []

    def test_entry_and_exit_events_recorded(self, strategy: RsiStrategy):
        """交易窗口内RSI多头信号记录ENTRY，止盈记录EXIT(TP)"""
        # 09:30-10:29 单边上涨，10:29形成第4根long bar，长短RSI齐备触发多头信号
        for i in range(60):
            self.feed(strategy, i, 100.0 + i)

        events = strategy.indicator_mgr.events
        assert len(events) == 1
        assert events[0]["type"] == "ENTRY"
        assert events[0]["side"] == 1
        assert events[0]["time"] == "10:29"
        assert events[0]["price"] == 159.0
        # 信号依据：满足的条件公式（单边上涨RSI=100，默认阈值长50/短55）
        assert events[0]["reason"] == "长RSI100.00>50 且 短RSI100.00>55"

        # 价格跳涨超5%触发止盈（entry=159，止盈线166.95）
        self.feed(strategy, 60, 170.0)
        events = strategy.indicator_mgr.events
        assert len(events) == 2
        assert events[1]["type"] == "EXIT"
        assert events[1]["reason"] == "TP"
        assert events[1]["price"] == 170.0


@pytest.mark.unit
class TestHvModeIndicatorCollect:
    """高波模式（mode=1）指标采集"""

    @pytest.fixture
    def strategy(self) -> RsiStrategy:
        s = make_rsi_strategy(
            {
                "symbol": "IM2612",
                "mode": 1,
                "short_k": 5,
                "long_k": 15,
                "take_profit_pct": 0.015,
                "stop_loss_pct": 0.015,
            },
            TRADING_DAY,
        )
        return s

    def feed_day_bars(self, strategy: RsiStrategy, day_open: float, closes: list[float]) -> None:
        for m, close in enumerate(closes):
            dt = TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=m)
            asyncio.run(strategy.on_bar(make_bar(dt, open_=day_open, close=close, symbol="IM2612")))

    def test_hv_decision_and_entry_recorded(self, strategy: RsiStrategy):
        """顺跳空做多：昨收/今开/09:45判定快照与ENTRY事件入图"""
        # 前一交易日最后一根M1建立昨收
        asyncio.run(
            strategy.on_bar(make_bar(datetime(2026, 9, 2, 14, 59), close=4700.0, symbol="IM2612"))
        )
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        self.feed_day_bars(strategy, 4710.0, closes)

        d = strategy.indicator_mgr.to_dict()
        assert d is not None
        assert len(d["bars"]) == 15  # 仅当日bar
        hv = d["hv"]
        assert hv["prev_close"] == 4700.0
        assert hv["day_open"] == 4710.0
        assert hv["decided"] is True
        assert hv["close_0945"] == 4720.0
        assert hv["gap"] == 1
        assert hv["move"] == 1
        assert hv["side"] == 1
        assert "顺势" in hv["reason"]

        assert d["events"] == [
            {"time": "09:44", "type": "ENTRY", "side": 1, "price": 4720.0, "reason": ""}
        ]

    def test_hv_block_reason_recorded(self, strategy: RsiStrategy):
        """反向回补不达标：记录空仓原因"""
        asyncio.run(
            strategy.on_bar(make_bar(datetime(2026, 9, 2, 14, 59), close=4700.0, symbol="IM2612"))
        )
        # 高开回落但未回到昨收
        closes = [4710.0 - 0.5 * i for i in range(11)] + [4705.0] * 4
        self.feed_day_bars(strategy, 4710.0, closes)

        hv = strategy.indicator_mgr.hv
        assert hv["decided"] is True
        assert hv["side"] == 0
        assert "空仓" in hv["reason"]
        assert strategy.indicator_mgr.events == []

    def test_hv_stop_loss_event_recorded(self, strategy: RsiStrategy):
        """5分钟收盘确认止损记录EXIT(SL)事件"""
        asyncio.run(
            strategy.on_bar(make_bar(datetime(2026, 9, 2, 14, 59), close=4700.0, symbol="IM2612"))
        )
        closes = [4705.0 + i for i in range(14)] + [4720.0]
        self.feed_day_bars(strategy, 4710.0, closes)
        # 09:45-09:49 深跌，09:49形成5分钟K线收盘确认止损
        for m in range(15, 20):
            dt = TRADING_DAY.replace(hour=9, minute=30) + timedelta(minutes=m)
            asyncio.run(strategy.on_bar(make_bar(dt, open_=4650.0, close=4640.0, symbol="IM2612")))

        events = strategy.indicator_mgr.events
        assert len(events) == 2
        assert events[1]["type"] == "EXIT"
        assert events[1]["reason"] == "SL"
        assert events[1]["time"] == "09:49"
