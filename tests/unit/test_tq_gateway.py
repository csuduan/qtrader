"""
TqGateway 单元测试

覆盖不依赖真实 TqSdk 连接的行为：初始化、订阅记账、
tq 线程指令队列（_submit_to_tq_thread/_drain_cmds）、
数据转换（账户/持仓/订单/成交/行情/K线）、订单状态映射、
推送与查询接口。全部使用 mock，不启动 tq 线程。
"""

import math
import queue
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from qtrader.models.object import (
    AccountData,
    CancelRequest,
    ContractData,
    Exchange,
    Offset,
    OrderRequest,
    OrderStatus,
    ProductType,
)
from qtrader.trader.gateway.tq_gateway import TqGateway
from qtrader.utils.async_event_engine import EventTypes


class TqEntity(dict):
    """模拟 tqsdk Entity 对象：同时支持属性访问与 .get()"""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def make_config(symbol: str = "SHFE.rb2505") -> MagicMock:
    config = MagicMock()
    config.gateway.account_id = "DQ"
    config.gateway.tianqin = None
    config.gateway.broker = None
    config.subs.subscribe_symbols = ["SHFE.rb2505"]
    config.subs.subscribe_bars = []
    return config


def make_contract(symbol: str = "rb2505") -> ContractData:
    return ContractData(
        symbol=symbol,
        exchange=Exchange.SHFE,
        name="螺纹钢",
        product_type=ProductType.FUTURES,
        multiple=10,
        pricetick=1.0,
    )


@pytest.fixture
def gateway() -> TqGateway:
    with patch.object(TqGateway, "load_contracts", return_value=None):
        gw = TqGateway(make_config())
    gw._event_engine = MagicMock()
    return gw


def make_order(status: str = "ALIVE", last_msg: str = "", **fields) -> TqEntity:
    data = {
        "order_id": "order_001",
        "instrument_id": "SHFE.rb2505",
        "exchange_id": "SHFE",
        "direction": "BUY",
        "offset": "OPEN",
        "volume_orign": 5,
        "volume_left": 2,
        "trade_price": 3500.5,
        "limit_price": 3500.0,
        "status": status,
        "last_msg": last_msg,
        "exchange_order_id": "EX001",
        "insert_date_time": 1756800000000000000,
    }
    data.update(fields)
    return TqEntity(data)


@pytest.mark.unit
class TestInit:
    """初始化"""

    def test_init_state(self, gateway):
        assert gateway.account_id == "DQ"
        assert gateway.api is None
        assert gateway._running is False
        assert gateway.connected is False

    def test_hist_subs_loaded_from_config(self, gateway):
        assert "SHFE.rb2505" in gateway.hist_subs


@pytest.mark.unit
class TestSubscribe:
    """订阅记账（未连接）"""

    def test_subscribe_not_connected_recorded(self, gateway):
        assert gateway.subscribe(["SHFE.hc2505"]) is True
        assert "SHFE.hc2505" in gateway.hist_subs

    def test_subscribe_bars_unknown_symbol_fails(self, gateway):
        assert gateway.subscribe_bars("GHOST.xx", "M1") is False

    def test_subscribe_bars_not_connected_records_sub(self, gateway):
        gateway.contracts["rb2505"] = make_contract()
        result = gateway.subscribe_bars("SHFE.rb2505", "M1")
        assert result is False  # 未连接
        assert ("rb2505", "M1") in gateway.kline_subs

    def test_subscribe_bars_deduplicated(self, gateway):
        gateway.contracts["rb2505"] = make_contract()
        gateway.subscribe_bars("SHFE.rb2505", "M1")
        gateway.subscribe_bars("SHFE.rb2505", "M1")
        assert gateway.kline_subs.count(("rb2505", "M1")) == 1


@pytest.mark.unit
class TestTqThreadQueue:
    """tq 线程指令队列"""

    def test_in_tq_thread_executes_directly(self, gateway):
        gateway._tq_thead = threading.current_thread()
        assert gateway._submit_to_tq_thread(lambda: 42) == 42

    def test_not_running_raises(self, gateway):
        with pytest.raises(Exception, match="未连接"):
            gateway._submit_to_tq_thread(lambda: 42)

    def test_drain_cmds_sets_result(self, gateway):
        from concurrent.futures import Future

        fut: Future = Future()
        gateway._cmd_queue.put((fut, lambda: "ok"))

        gateway._drain_cmds()

        assert fut.result() == "ok"

    def test_drain_cmds_captures_exception(self, gateway):
        from concurrent.futures import Future

        fut: Future = Future()

        def boom():
            raise RuntimeError("boom")

        gateway._cmd_queue.put((fut, boom))
        gateway._drain_cmds()

        with pytest.raises(RuntimeError, match="boom"):
            fut.result()


@pytest.mark.unit
class TestIntervalConversion:
    """周期转换"""

    def test_minute(self, gateway):
        assert gateway._interval_to_seconds("M1") == 60
        assert gateway._interval_to_seconds("M5") == 300

    def test_hour(self, gateway):
        assert gateway._interval_to_seconds("H1") == 3600

    def test_invalid(self, gateway):
        with pytest.raises(ValueError):
            gateway._interval_to_seconds("D1")


@pytest.mark.unit
class TestTradingWhenDisconnected:
    """未连接时的交易接口"""

    def test_send_order_raises(self, gateway):
        req = OrderRequest(
            symbol="rb2505",
            direction="BUY",
            offset="OPEN",
            volume=1,
            price=3500.0,
        )
        with pytest.raises(Exception):
            gateway.send_order(req)

    def test_cancel_order_fails(self, gateway):
        req = CancelRequest(order_id="order_001")
        assert gateway.cancel_order(req) is False

    def test_get_kline_none(self, gateway):
        assert gateway.get_kline("rb2505", "M1") is None


@pytest.mark.unit
class TestConvertAccount:
    """账户转换"""

    def test_convert_account(self, gateway):
        account = TqEntity(
            balance=100000.0,
            available=90000.0,
            margin=8000.0,
            static_balance=99000.0,
            position_profit=500.0,
            close_profit=200.0,
            risk_ratio=0.08,
        )
        data = gateway._convert_account(account)

        assert isinstance(data, AccountData)
        assert data.account_id == "DQ"
        assert data.balance == 100000.0
        assert data.hold_profit == 500.0
        assert data.pre_balance == 99000.0

    def test_get_account_fallback(self, gateway):
        data = gateway.get_account()
        assert data.account_id == "DQ"
        assert data.balance == 0


@pytest.mark.unit
class TestConvertPosition:
    """持仓转换"""

    def test_convert_position(self, gateway):
        gateway.contracts["rb2505"] = make_contract()
        pos = TqEntity(
            instrument_id="rb2505",
            exchange_id="SHFE",
            pos_long_his=1,
            pos_long_today=2,
            pos_short_his=0,
            pos_short_today=0,
            position_price_long=3500.0,
            position_price_short=float("nan"),
            position_profit_long=100.0,
            position_profit_short=float("nan"),
            margin_long=7000.0,
            margin_short=float("nan"),
        )

        data = gateway._convert_position(pos)

        assert data.symbol == "rb2505"
        assert data.exchange == Exchange.SHFE
        assert data.pos_long_yd == 1
        assert data.pos_long_td == 2
        assert data.pos_long == 3
        assert data.multiple == 10
        # NaN 为真值，`or 0` 不会归零，原样保留
        assert math.isnan(data.hold_price_short)

    def test_get_positions_filters_long_symbols(self, gateway):
        gateway.contracts["rb2505"] = make_contract()
        valid = TqEntity(
            instrument_id="rb2505",
            exchange_id="SHFE",
            pos_long_his=0,
            pos_long_today=1,
            pos_short_his=0,
            pos_short_today=0,
            position_price_long=3500.0,
            position_price_short=0,
            position_profit_long=0,
            position_profit_short=0,
            margin_long=0,
            margin_short=0,
        )
        invalid = TqEntity(
            instrument_id="TOO_LONG_SYMBOL",
            exchange_id="SHFE",
            pos_long_his=0,
            pos_long_today=1,
            pos_short_his=0,
            pos_short_today=0,
            position_price_long=3500.0,
            position_price_short=0,
            position_profit_long=0,
            position_profit_short=0,
            margin_long=0,
            margin_short=0,
        )
        gateway._positions = {"rb2505": valid, "TOO_LONG_SYMBOL": invalid}

        positions = gateway.get_positions()
        assert set(positions.keys()) == {"rb2505"}


@pytest.mark.unit
class TestConvertOrder:
    """订单转换与状态映射"""

    def test_alive_maps_pending(self, gateway):
        data = gateway._convert_order(make_order(status="ALIVE", last_msg=""))
        assert data.status == OrderStatus.PENDING

    def test_filled_maps_finished(self, gateway):
        data = gateway._convert_order(make_order(status="FINISHED", last_msg="全部成交"))
        assert data.status == OrderStatus.FINISHED

    def test_cancelled_maps_finished(self, gateway):
        data = gateway._convert_order(make_order(status="FINISHED", last_msg="已撤单"))
        assert data.status == OrderStatus.FINISHED

    def test_rejected_maps_rejected(self, gateway):
        data = gateway._convert_order(make_order(status="FINISHED", last_msg="资金不足"))
        assert data.status == OrderStatus.REJECTED

    def test_cancel_with_reject_word_maps_finished(self, gateway):
        data = gateway._convert_order(make_order(status="FINISHED", last_msg="撤单：场次不足"))
        assert data.status == OrderStatus.FINISHED

    def test_order_fields(self, gateway):
        data = gateway._convert_order(make_order())

        assert data.order_id == "order_001"
        assert data.symbol == "SHFE.rb2505"
        assert data.volume == 5
        assert data.traded == 3
        assert data.traded_price == 3500.5
        assert data.gateway_order_id == "EX001"
        assert data.insert_time is not None


@pytest.mark.unit
class TestConvertTradeAndTick:
    """成交与行情转换"""

    def test_convert_trade(self, gateway):
        trade = TqEntity(
            trade_id="trade_001",
            order_id="order_001",
            exchange_id="SHFE",
            instrument_id="SHFE.rb2505",
            direction="BUY",
            offset="OPEN",
            price=3500.0,
            volume=2,
            trade_date_time=1756800000000000000,
        )
        data = gateway._convert_trade(trade)

        assert data.trade_id == "trade_001"
        assert data.price == 3500.0
        assert data.volume == 2
        assert data.trade_time is not None

    def test_convert_tick(self, gateway):
        quote = TqEntity(
            exchange_id="SHFE",
            instrument_id="SHFE.rb2505",
            datetime=1756800000000000000,
            last_price=3510.0,
            volume=1000.0,
            turnover=3500000.0,
            open_interest=200000.0,
            bid_price1=3509.0,
            ask_price1=3511.0,
            bid_volume1=10.0,
            ask_volume1=12.0,
            open=3500.0,
            highest=3520.0,
            lowest=3495.0,
            pre_close=3501.0,
            upper_limit=3600.0,
            lower_limit=3400.0,
        )
        data = gateway._convert_tick(quote)

        assert data.symbol == "rb2505"
        assert data.last_price == 3510.0
        assert data.ask_price1 == 3511.0

    def test_convert_tick_nan_last_price(self, gateway):
        quote = TqEntity(
            exchange_id="SHFE",
            instrument_id="SHFE.rb2505",
            datetime=0,
            last_price=float("nan"),
        )
        data = gateway._convert_tick(quote)
        assert math.isnan(data.last_price)  # 保留 NaN，由上游过滤

    def test_convert_bar(self, gateway):
        data = gateway._convert_bar(
            "rb2505",
            "M1",
            {
                "datetime": 1756800000000000000,
                "open": 3500.0,
                "high": 3510.0,
                "low": 3490.0,
                "close": 3505.0,
                "volume": 100.0,
            },
            1756800060000000000,
        )
        assert data.symbol == "rb2505"
        assert data.interval == "M1"
        assert data.close_price == 3505.0


@pytest.mark.unit
class TestCollectAndPush:
    """数据变化收集与推送"""

    def test_pending_order_change_pushed(self, gateway):
        gateway.api = MagicMock()
        gateway.api.is_changing.return_value = False

        order = make_order(status="ALIVE")
        gateway._pending_orders["order_001"] = order

        # 仅该订单变化时推送
        gateway.api.is_changing.side_effect = lambda obj, *a: obj is order

        gateway._collect_and_push_updates()

        event_type, payload = gateway._event_engine.put.call_args[0]
        assert event_type == EventTypes.ORDER_UPDATE
        assert payload.order_id == "order_001"

    def test_finished_order_removed_from_pending(self, gateway):
        gateway.api = MagicMock()
        gateway.api.is_changing.return_value = False
        order = make_order(status="FINISHED", last_msg="全部成交")
        gateway._pending_orders["order_001"] = order
        gateway.api.is_changing.side_effect = lambda obj, *a: obj is order

        gateway._collect_and_push_updates()

        assert "order_001" not in gateway._pending_orders

    def test_quote_change_pushes_tick(self, gateway):
        gateway.api = MagicMock()
        gateway.api.is_changing.return_value = False
        quote = TqEntity(exchange_id="SHFE", instrument_id="SHFE.rb2505", last_price=3510.0)
        gateway._quotes["rb2505"] = quote
        gateway.api.is_changing.side_effect = lambda obj, *a: obj is quote

        gateway._collect_and_push_updates()

        event_type, payload = gateway._event_engine.put.call_args[0]
        assert event_type == EventTypes.TICK_UPDATE
        assert payload.symbol == "rb2505"

    def test_trade_change_pushes_trade_with_order_price(self, gateway):
        gateway.api = MagicMock()
        gateway.api.is_changing.return_value = False
        trade = TqEntity(
            trade_id="t1",
            order_id="order_001",
            exchange_id="SHFE",
            instrument_id="SHFE.rb2505",
            direction="BUY",
            offset="OPEN",
            price=3500.0,
            volume=1,
        )
        gateway._trades["t1"] = trade
        pending = make_order()
        gateway._pending_orders["order_001"] = pending

        gateway.api.is_changing.side_effect = lambda obj, *a: obj is trade or obj is gateway._trades

        gateway._collect_and_push_updates()

        event_type, payload = gateway._event_engine.put.call_args[0]
        assert event_type == EventTypes.TRADE_UPDATE
        assert payload.order_price == 3500.0

    def test_position_change_pushes_with_source(self, gateway):
        gateway.api = MagicMock()
        gateway.api.is_changing.return_value = False
        gateway.contracts["rb2505"] = make_contract()
        pos = TqEntity(
            instrument_id="rb2505",
            exchange_id="SHFE",
            pos_long_his=0,
            pos_long_today=1,
            pos_short_his=0,
            pos_short_today=0,
            position_price_long=3500.0,
            position_price_short=0,
            position_profit_long=0,
            position_profit_short=0,
            margin_long=0,
            margin_short=0,
        )
        gateway._positions["rb2505"] = pos
        gateway.api.is_changing.side_effect = (
            lambda obj, *a: obj is pos or obj is gateway._positions
        )

        gateway._collect_and_push_updates()

        event_type, payload = gateway._event_engine.put.call_args[0]
        assert event_type == EventTypes.POSITION_UPDATE
        assert payload["_source"] == "trade"

    def test_no_api_noop(self, gateway):
        gateway.api = None
        gateway._collect_and_push_updates()  # 不应抛错
        gateway._event_engine.put.assert_not_called()


@pytest.mark.unit
class TestPushAndQuery:
    """推送与查询接口"""

    def test_push_ready(self, gateway):
        gateway._push_ready()
        gateway._event_engine.put.assert_called_once_with(EventTypes.ACCOUNT_READY, None)

    def test_push_account(self, gateway):
        account = AccountData(account_id="DQ", balance=1.0)
        gateway._push_account(account)
        gateway._event_engine.put.assert_called_once_with(EventTypes.ACCOUNT_UPDATE, account)

    def test_parse_exchange(self, gateway):
        assert gateway._parse_exchange("SHFE") == Exchange.SHFE
        assert gateway._parse_exchange("DCE") == Exchange.DCE
        assert gateway._parse_exchange("XXXX") == Exchange.NONE

    def test_get_orders(self, gateway):
        gateway._orders["order_001"] = make_order()
        orders = gateway.get_orders()
        assert "order_001" in orders
        assert orders["order_001"].order_id == "order_001"

    def test_get_trades(self, gateway):
        gateway._trades["t1"] = TqEntity(
            trade_id="t1",
            order_id="o1",
            exchange_id="SHFE",
            instrument_id="SHFE.rb2505",
            direction="BUY",
            offset="OPEN",
            price=1.0,
            volume=1,
        )
        trades = gateway.get_trades()
        assert "t1" in trades

    def test_get_quotes_skips_empty_instrument(self, gateway):
        gateway._quotes["rb2505"] = TqEntity(
            exchange_id="SHFE", instrument_id="SHFE.rb2505", last_price=1.0
        )
        gateway._quotes["bad"] = TqEntity(exchange_id="", instrument_id="")
        quotes = gateway.get_quotes()
        assert set(quotes.keys()) == {"rb2505"}

    def test_get_contracts(self, gateway):
        gateway.contracts["rb2505"] = make_contract()
        assert "rb2505" in gateway.get_contracts()
