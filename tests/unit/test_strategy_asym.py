"""
ASYM 股指择时策略单元测试

覆盖信号计算（ASYM公式、品种阈值、等于阈值不触发、数据不足不出信号）
与交付验收六场景：同向叠仓、同合约反向抵消、无新信号旧批到期、
周末/节假日顺延、跨合约换月、缺失旧合约退出价。
"""

import asyncio
import math
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from qtrader.models.object import BarData, Direction, Exchange, Offset
from qtrader.trader.order_cmd import OrderCmd, OrderCmdStatus
from qtrader.trader.strategy.strategy_asym import (
    MORNING_BARS,
    AsymStrategy,
    asym_side,
)

DAY1 = datetime(2026, 11, 23)  # 周一
DAY2 = datetime(2026, 11, 24)  # 周二
FRIDAY = datetime(2026, 11, 20)  # 周五
MONDAY = datetime(2026, 11, 23)  # 周一


def make_bar(
    dt: datetime,
    open_: float,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    symbol: str = "IC2612",
) -> BarData:
    return BarData(
        symbol=symbol,
        interval="M1",
        datetime=dt,
        open_price=open_,
        high_price=high if high is not None else open_,
        low_price=low if low is not None else open_,
        close_price=close if close is not None else open_,
        volume=1.0,
    )


@pytest.fixture
def strategy(monkeypatch: pytest.MonkeyPatch) -> AsymStrategy:
    """IC策略实例：批次持久化替换为内存透传，下单走mock"""

    async def _noop(self: AsymStrategy) -> None:
        pass

    monkeypatch.setattr(AsymStrategy, "_load_batches", _noop)
    monkeypatch.setattr(AsymStrategy, "_save_batches", _noop)

    config = MagicMock()
    config.symbol = "IC2612"
    config.volume = 1
    config.bar = "M1"
    config.params = {"symbol": "IC2612", "volume": 1}
    s = AsymStrategy("asym_ic", config)

    engine = MagicMock()
    engine.account_id = "TEST"
    engine.quotes = {}
    contract = MagicMock()
    contract.exchange = Exchange.CFFEX
    contract.multiple = 200
    engine.get_contract = MagicMock(return_value=contract)

    sm = MagicMock()
    sm.send_order_cmd = AsyncMock()
    sm.cancel_order_cmd = AsyncMock()
    sm.trading_engine = engine
    s.strategy_manager = sm
    s.trading_engine = engine
    return s


def feed(
    strategy: AsymStrategy,
    dt: datetime,
    open_: float,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    symbol: str = "IC2612",
) -> None:
    asyncio.run(strategy.on_bar(make_bar(dt, open_, high, low, close, symbol)))


def start_day(strategy: AsymStrategy, day: datetime) -> None:
    asyncio.run(strategy.init(day))


def feed_morning(
    strategy: AsymStrategy, day: datetime, o: float, h: float, low: float, symbol: str = "IC2612"
) -> None:
    """喂早盘120根M1：首根开盘o，中间一根冲高h、一根探底low"""
    start = day.replace(hour=9, minute=30)
    for i in range(MORNING_BARS):
        dt = start + timedelta(minutes=i)
        high = h if i == 60 else o
        bar_low = low if i == 61 else o
        feed(strategy, dt, o, high=high, low=bar_low, symbol=symbol)


def feed_long_morning(strategy: AsymStrategy, day: datetime, symbol: str = "IC2612") -> None:
    """IC做多信号早盘：ASYM≈+0.005 > +0.004"""
    o = 6000.0
    feed_morning(strategy, day, o, o * math.exp(0.005), o, symbol)


def feed_short_morning(strategy: AsymStrategy, day: datetime, symbol: str = "IC2612") -> None:
    """IC做空信号早盘：ASYM≈-0.007 < -0.006"""
    o = 6000.0
    feed_morning(strategy, day, o, o, o * math.exp(-0.007), symbol)


def feed_flat_morning(strategy: AsymStrategy, day: datetime, symbol: str = "IC2612") -> None:
    """无信号早盘：ASYM=0"""
    feed_morning(strategy, day, 6000.0, 6000.0, 6000.0, symbol)


def feed_entry_bar(strategy: AsymStrategy, day: datetime, symbol: str = "IC2612") -> None:
    """13:34 bar（收盘即13:35时点）触发建仓"""
    feed(strategy, day.replace(hour=13, minute=34), 6000.0, symbol=symbol)


def feed_exit_bar(strategy: AsymStrategy, day: datetime, symbol: str = "IC2612") -> None:
    """14:54 bar（收盘即14:55时点）触发到期退出"""
    feed(strategy, day.replace(hour=14, minute=54), 6000.0, symbol=symbol)


def sent_cmds(strategy: AsymStrategy) -> list[OrderCmd]:
    """已发出的报单指令"""
    return [c.args[1] for c in strategy.strategy_manager.send_order_cmd.call_args_list]


def clear_cmds(strategy: AsymStrategy) -> None:
    strategy.strategy_manager.send_order_cmd.reset_mock()


def fill(strategy: AsymStrategy, cmd: OrderCmd, price: float) -> None:
    """模拟指令全部成交并触发完成回调"""
    cmd.filled_volume = cmd.volume
    cmd.filled_price = price
    cmd.status = OrderCmdStatus.FINISHED
    strategy._on_cmd_change(cmd)


def pos_net(strategy: AsymStrategy, symbol: str) -> int:
    p = strategy.get_position(symbol)
    return (p.pos_long - p.pos_short) if p else 0


@pytest.mark.unit
class TestAsymSignal:
    """信号计算"""

    def test_strict_threshold_boundary(self):
        """等于阈值不新增批次（严格大于/小于）"""
        assert asym_side(0.004, 0.004, 0.006) == 0
        assert asym_side(0.0041, 0.004, 0.006) == 1
        assert asym_side(-0.006, 0.004, 0.006) == 0
        assert asym_side(-0.0061, 0.004, 0.006) == -1

    def test_variety_default_thresholds(self, strategy: AsymStrategy):
        start_day(strategy, DAY1)
        assert (strategy._long_thr, strategy._short_thr) == (0.004, 0.006)

        strategy.update_params({"symbol": "IM2612"})
        start_day(strategy, DAY1)
        assert (strategy._long_thr, strategy._short_thr) == (0.006, 0.008)

    def test_param_overrides_thresholds(self, monkeypatch: pytest.MonkeyPatch):
        async def _noop(self: AsymStrategy) -> None:
            pass

        monkeypatch.setattr(AsymStrategy, "_load_batches", _noop)
        monkeypatch.setattr(AsymStrategy, "_save_batches", _noop)
        config = MagicMock()
        config.symbol = "IC2612"
        config.volume = 1
        config.bar = "M1"
        config.params = {"symbol": "IC2612", "asym_long_thr": 0.001, "asym_short_thr": 0.002}
        s = AsymStrategy("asym_ic2", config)
        start_day(s, DAY1)
        assert (s._long_thr, s._short_thr) == (0.001, 0.002)

    def test_asym_formula(self, strategy: AsymStrategy):
        """ASYM = ln(H/O) + ln(L/O)，O为首根开盘"""
        start_day(strategy, DAY1)
        o = 6000.0
        h, low = 6030.0, 5970.0
        feed_morning(strategy, DAY1, o, h, low)
        expected = math.log(h / o) + math.log(low / o)
        assert strategy._today_asym == pytest.approx(expected)
        # IC阈值+0.004/-0.006，该值在区间内无信号
        assert strategy._today_signal == 0

    def test_long_and_short_signal(self, strategy: AsymStrategy):
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1)
        assert strategy._today_signal == 1

        start_day(strategy, DAY1)
        feed_short_morning(strategy, DAY1)
        assert strategy._today_signal == -1

    def test_insufficient_morning_blocks(self, strategy: AsymStrategy):
        """早盘数据不足120根不出信号"""
        start_day(strategy, DAY1)
        start = DAY1.replace(hour=9, minute=30)
        for i in range(100):
            feed(strategy, start + timedelta(minutes=i), 6000.0, high=6030.0)
        feed_entry_bar(strategy, DAY1)
        assert strategy._today_signal == 0
        assert sent_cmds(strategy) == []


@pytest.mark.unit
class TestAcceptanceScenarios:
    """交付验收六场景"""

    def test_scenario1_same_direction_stacking(self, strategy: AsymStrategy):
        """场景1 同向叠仓：次日同向再开一批，净仓叠加到+1.0（2手），旧批按时退出"""
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        cmds = sent_cmds(strategy)
        assert len(cmds) == 1
        assert (cmds[0].symbol, cmds[0].direction, cmds[0].offset, cmds[0].volume) == (
            "IC2612",
            Direction.BUY,
            Offset.OPEN,
            1,
        )
        fill(strategy, cmds[0], 6000.0)
        assert pos_net(strategy, "IC2612") == 1

        # 次日同向信号：13:35后再开一批，净仓+2手（权重+1.0）
        start_day(strategy, DAY2)
        clear_cmds(strategy)
        feed_long_morning(strategy, DAY2)
        feed_entry_bar(strategy, DAY2)
        cmds = sent_cmds(strategy)
        assert len(cmds) == 1 and cmds[0].offset == Offset.OPEN
        fill(strategy, cmds[0], 6010.0)
        assert pos_net(strategy, "IC2612") == 2

        # 14:55旧批到期退出，剩次日批次
        feed_exit_bar(strategy, DAY2)
        cmds = sent_cmds(strategy)
        assert len(cmds) == 2
        assert (cmds[1].direction, cmds[1].offset, cmds[1].volume) == (
            Direction.SELL,
            Offset.CLOSE,
            1,
        )
        fill(strategy, cmds[1], 6020.0)
        assert pos_net(strategy, "IC2612") == 1

        batches = strategy.get_batches()
        assert len(batches) == 2
        assert batches[0]["status"] == "CLOSED"
        assert batches[0]["exit_date"] == "2026-11-24"
        assert batches[1]["status"] == "OPEN"

    def test_scenario2_reverse_offset_same_contract(self, strategy: AsymStrategy):
        """场景2 同合约反向抵消：13:35后净仓为0，14:55平旧批后净-0.5（1手空）"""
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        fill(strategy, sent_cmds(strategy)[0], 6000.0)

        start_day(strategy, DAY2)
        clear_cmds(strategy)
        feed_short_morning(strategy, DAY2)
        feed_entry_bar(strategy, DAY2)
        cmds = sent_cmds(strategy)
        assert (cmds[0].direction, cmds[0].offset) == (Direction.SELL, Offset.OPEN)
        fill(strategy, cmds[0], 6000.0)
        # 多头1手+空头1手，净仓0
        assert pos_net(strategy, "IC2612") == 0

        feed_exit_bar(strategy, DAY2)
        cmds = sent_cmds(strategy)
        assert (cmds[1].direction, cmds[1].offset, cmds[1].symbol) == (
            Direction.SELL,
            Offset.CLOSE,
            "IC2612",
        )
        fill(strategy, cmds[1], 5990.0)
        # 旧多批退出后只剩新空批
        assert pos_net(strategy, "IC2612") == -1

    def test_scenario3_no_signal_old_batch_expires(self, strategy: AsymStrategy):
        """场景3 无新信号：当日不建仓，旧批次仍按时退出"""
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        fill(strategy, sent_cmds(strategy)[0], 6000.0)

        start_day(strategy, DAY2)
        clear_cmds(strategy)
        feed_flat_morning(strategy, DAY2)
        feed_entry_bar(strategy, DAY2)
        assert sent_cmds(strategy) == []  # 无信号不建仓

        feed_exit_bar(strategy, DAY2)
        cmds = sent_cmds(strategy)
        assert len(cmds) == 1
        assert (cmds[0].direction, cmds[0].offset) == (Direction.SELL, Offset.CLOSE)
        assert strategy.get_batches()[0]["status"] == "CLOSED"

    def test_scenario4_weekend_postpone(self, strategy: AsymStrategy):
        """场景4 周末顺延：周五建仓，周一（下一交易日）14:55到期"""
        start_day(strategy, FRIDAY)
        feed_long_morning(strategy, FRIDAY)
        feed_entry_bar(strategy, FRIDAY)
        fill(strategy, sent_cmds(strategy)[0], 6000.0)

        # 周五当天14:54不退出（entry_date == 当日）
        feed_exit_bar(strategy, FRIDAY)
        assert len(sent_cmds(strategy)) == 1  # 仍只有建仓指令

        # 下一交易日（周一）到期退出
        start_day(strategy, MONDAY)
        clear_cmds(strategy)
        feed_flat_morning(strategy, MONDAY)
        feed_exit_bar(strategy, MONDAY)
        cmds = sent_cmds(strategy)
        assert len(cmds) == 1 and cmds[0].offset == Offset.CLOSE
        batch = strategy.get_batches()[0]
        assert batch["exit_date"] == "2026-11-23"

    def test_scenario5_rollover_cross_contract(self, strategy: AsymStrategy):
        """场景5 跨合约换月：新批用当天主力建仓，旧批在原合约退出，分合约仓位正确"""
        strategy.config.params["symbol"] = "IC2611"
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1, symbol="IC2611")
        feed_entry_bar(strategy, DAY1, symbol="IC2611")
        fill(strategy, sent_cmds(strategy)[0], 6000.0)
        assert pos_net(strategy, "IC2611") == 1

        # 次日换月：主力切换IC2612，旧合约行情已订阅
        strategy.update_params({"symbol": "IC2612"})
        strategy.trading_engine.quotes["IC2611"] = MagicMock(last_price=5900.0)
        start_day(strategy, DAY2)
        clear_cmds(strategy)

        feed_short_morning(strategy, DAY2, symbol="IC2612")
        feed_entry_bar(strategy, DAY2, symbol="IC2612")
        cmds = sent_cmds(strategy)
        assert (cmds[0].symbol, cmds[0].direction, cmds[0].offset) == (
            "IC2612",
            Direction.SELL,
            Offset.OPEN,
        )
        fill(strategy, cmds[0], 5950.0)
        # 换月示例：13:35后品种净权重为0，但两个合约各有一笔持仓
        assert pos_net(strategy, "IC2611") == 1
        assert pos_net(strategy, "IC2612") == -1

        feed_exit_bar(strategy, DAY2, symbol="IC2612")
        cmds = sent_cmds(strategy)
        assert (cmds[1].symbol, cmds[1].direction, cmds[1].offset) == (
            "IC2611",
            Direction.SELL,
            Offset.CLOSE,
        )
        fill(strategy, cmds[1], 5910.0)
        # 14:55平掉IC2611后只剩IC2612空头
        assert pos_net(strategy, "IC2611") == 0
        assert pos_net(strategy, "IC2612") == -1

        batches = strategy.get_batches()
        assert batches[0]["symbol"] == "IC2611" and batches[0]["status"] == "CLOSED"
        assert batches[0]["exit_price"] == 5900.0  # 旧合约退出价取最新行情
        assert batches[1]["symbol"] == "IC2612" and batches[1]["status"] == "OPEN"

    def test_scenario6_missing_old_contract_quote(self, strategy: AsymStrategy):
        """场景6 缺失旧合约退出行情：报错并记录日期与合约，平仓指令仍发出"""
        from loguru import logger

        strategy.config.params["symbol"] = "IC2611"
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1, symbol="IC2611")
        feed_entry_bar(strategy, DAY1, symbol="IC2611")
        fill(strategy, sent_cmds(strategy)[0], 6000.0)

        strategy.update_params({"symbol": "IC2612"})
        start_day(strategy, DAY2)
        clear_cmds(strategy)

        # loguru自带sink不被capsys捕获，挂载内存sink收集ERROR日志
        errors: list[str] = []
        sink_id = logger.add(lambda m: errors.append(str(m)), level="ERROR")
        try:
            feed_flat_morning(strategy, DAY2, symbol="IC2612")
            feed_exit_bar(strategy, DAY2, symbol="IC2612")
        finally:
            logger.remove(sink_id)

        # 报错含日期与合约
        assert any(
            "旧合约退出行情缺失" in e and "2026-11-24" in e and "IC2611" in e for e in errors
        )
        # 平仓指令仍发出，退出价缺失记0待人工核对
        cmds = sent_cmds(strategy)
        assert len(cmds) == 1 and cmds[0].symbol == "IC2611"
        assert strategy.get_batches()[0]["exit_price"] == 0.0


@pytest.mark.unit
class TestReplayAndIdempotency:
    """回播守卫与幂等"""

    def test_replay_does_not_send_orders(self, strategy: AsymStrategy):
        """回播（enabled=False）只重建信号状态，不发单不建批次"""
        start_day(strategy, DAY1)
        strategy.enable(False)
        feed_long_morning(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        assert sent_cmds(strategy) == []
        assert strategy.get_batches() == []
        assert strategy._today_signal == 1  # 信号状态已重建

    def test_late_entry_after_replay(self, strategy: AsymStrategy):
        """回播结束后首根>=13:34的实时bar迟到补仓"""
        start_day(strategy, DAY1)
        strategy.enable(False)
        feed_long_morning(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        strategy.enable()
        # 回放结束后第一根实时bar（13:50）触发迟到建仓
        feed(strategy, DAY1.replace(hour=13, minute=50), 6010.0)
        cmds = sent_cmds(strategy)
        assert len(cmds) == 1 and cmds[0].offset == Offset.OPEN

    def test_duplicate_entry_bar_no_double_batch(self, strategy: AsymStrategy):
        """13:34 bar重复到达（回播与实时重叠）不重复建仓"""
        start_day(strategy, DAY1)
        feed_long_morning(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        feed_entry_bar(strategy, DAY1)
        assert len(sent_cmds(strategy)) == 1
        assert len(strategy.get_batches()) == 1
