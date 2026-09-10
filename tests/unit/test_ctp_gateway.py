"""
CtpGateway 单元测试

通过伪造 ctp_api 模块（其模块级依赖应用配置与 ctpx 动态导入），
覆盖网关自身的状态管理、下单价格合成、回调缓存与推送逻辑。
不连接真实 CTP 前置。
"""

import sys
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ctp_api 模块级读取应用配置，测试环境未初始化 → 用假模块替换
fake_ctp_api = MagicMock()
sys.modules["qtrader.trader.gateway.ctp_api"] = fake_ctp_api

from qtrader.models.object import (  # noqa: E402
    AccountData,
    CancelRequest,
    ContractData,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderRequest,
    OrderStatus,
    PositionData,
    ProductType,
    TickData,
    TradeData,
)
from qtrader.trader.gateway.ctp_gateway import CtpGateway  # noqa: E402
from qtrader.utils.event import EventTypes  # noqa: E402


def make_config() -> MagicMock:
    config = MagicMock()
    config.account_id = "CTP01"
    config.gateway.account_id = "CTP01"
    config.gateway.type = "CTP"
    config.gateway.broker = None  # 缺省走 "--" 兜底
    config.subs.subscribe_symbols = []
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
def gateway() -> CtpGateway:
    fake_ctp_api.reset_mock()  # 模块级共享 mock，清掉上一个用例的调用记录
    with patch.object(CtpGateway, "load_contracts", return_value=None):
        gw = CtpGateway(make_config())
    gw._event_engine = MagicMock()
    return gw


def attach_apis(gateway: CtpGateway, connected: bool = True):
    """挂接 mock 行情/交易接口并置连接状态"""
    fake_ctp_api.reset_mock()
    gateway.md_api = fake_ctp_api.CtpMdApi.return_value
    gateway.td_api = fake_ctp_api.CtpTdApi.return_value
    gateway.md_api.side_effect = None
    gateway.td_api.side_effect = None
    gateway.md_api.connected = connected
    gateway.td_api.connected = connected
    gateway.md_connected = connected
    gateway.td_connected = connected
    return gateway.md_api, gateway.td_api


def make_tick(symbol: str = "rb2505", last: float = 3500.0, bid=3499.0, ask=3501.0) -> TickData:
    return TickData(
        symbol=symbol,
        exchange=Exchange.SHFE,
        last_price=last,
        bid_price1=bid,
        ask_price1=ask,
        datetime=datetime(2026, 9, 3, 10, 0),
    )


def make_order_request(price: float = 0, direction: str = "BUY") -> OrderRequest:
    return OrderRequest(
        symbol="rb2505",
        direction=direction,
        offset="OPEN",
        volume=1,
        price=price,
    )


@pytest.mark.unit
class TestInit:
    """初始化状态"""

    def test_init_state(self, gateway):
        assert gateway.account_id == "CTP01"
        assert gateway.md_api is None
        assert gateway.td_api is None
        assert gateway._quotes == {}
        assert gateway._positions == {}
        assert gateway._orders == {}
        assert gateway._trades == {}


@pytest.mark.unit
class TestConnect:
    """连接管理"""

    @pytest.mark.asyncio
    async def test_connect_creates_apis(self, gateway):
        assert await gateway.connect() is True
        fake_ctp_api.CtpMdApi.assert_called_once_with(gateway)
        fake_ctp_api.CtpTdApi.assert_called_once_with(gateway)
        gateway.md_api.connect.assert_called_once()
        gateway.td_api.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_closes_apis(self, gateway):
        await gateway.connect()
        md, td = gateway.md_api, gateway.td_api
        assert await gateway.disconnect() is True
        md.close.assert_called_once()
        td.close.assert_called_once()
        assert gateway.md_api is None
        assert gateway.td_api is None
        assert gateway.connected is False


@pytest.mark.unit
class TestSendOrder:
    """下单与价格合成"""

    def test_not_connected_returns_none(self, gateway):
        assert gateway.send_order(make_order_request(price=3500.0)) is None

    def test_unknown_contract_raises(self, gateway):
        attach_apis(gateway)
        with pytest.raises(ValueError, match="未找到合约信息"):
            gateway.send_order(make_order_request(price=3500.0))

    def test_td_api_missing_raises(self, gateway):
        gateway.td_connected = True
        gateway.contracts["rb2505"] = make_contract()
        with pytest.raises(ValueError, match="交易接口未初始化"):
            gateway.send_order(make_order_request(price=3500.0))

    def test_buy_market_price_uses_bid(self, gateway):
        _, td = attach_apis(gateway)
        gateway.contracts["rb2505"] = make_contract()
        gateway._quotes["rb2505"] = make_tick(bid=3499.0, ask=3501.0)
        td.insert_order.side_effect = lambda req: OrderData(
            order_id="1",
            symbol=req.symbol,
            account_id="CTP01",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=req.price,
        )

        gateway.send_order(make_order_request(price=0, direction="BUY"))

        sent = td.insert_order.call_args[0][0]
        assert sent.price == 3499.0  # 买方向取买一价

    def test_sell_market_price_uses_ask(self, gateway):
        _, td = attach_apis(gateway)
        gateway.contracts["rb2505"] = make_contract()
        gateway._quotes["rb2505"] = make_tick(bid=3499.0, ask=3501.0)
        td.insert_order.side_effect = lambda req: OrderData(
            order_id="1",
            symbol=req.symbol,
            account_id="CTP01",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=req.price,
        )

        gateway.send_order(make_order_request(price=0, direction="SELL"))

        sent = td.insert_order.call_args[0][0]
        assert sent.price == 3501.0  # 卖方向取卖一价

    def test_market_price_without_tick_raises(self, gateway):
        attach_apis(gateway)
        gateway.contracts["rb2505"] = make_contract()
        with pytest.raises(ValueError, match="未获取到有效价格"):
            gateway.send_order(make_order_request(price=0))

    def test_limit_price_passthrough(self, gateway):
        _, td = attach_apis(gateway)
        gateway.contracts["rb2505"] = make_contract()
        td.insert_order.side_effect = lambda req: OrderData(
            order_id="1",
            symbol=req.symbol,
            account_id="CTP01",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=req.price,
        )

        gateway.send_order(make_order_request(price=3600.0))

        sent = td.insert_order.call_args[0][0]
        assert sent.price == 3600.0

    def test_cancel_order(self, gateway):
        _, td = attach_apis(gateway)
        td.cancel_order.return_value = True
        assert gateway.cancel_order(CancelRequest(order_id="1")) is True
        td.cancel_order.assert_called_once()

    def test_cancel_not_connected(self, gateway):
        assert gateway.cancel_order(CancelRequest(order_id="1")) is False


@pytest.mark.unit
class TestGetAccount:
    """账户数据聚合"""

    def test_default_account_without_cache(self, gateway):
        account = gateway.get_account()
        assert account.account_id == "CTP01"
        assert account.user_id == "--"  # broker 缺失时的兜底
        assert account.balance == 0

    def test_cached_account_aggregates_positions(self, gateway):
        gateway._account = AccountData(account_id="CTP01", balance=0, static_balance=100000.0)
        gateway._positions["rb2505"] = PositionData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            hold_profit_long=100.0,
            hold_profit_short=50.0,
            close_profit_long=20.0,
            close_profit_short=10.0,
        )

        account = gateway.get_account()

        assert account.hold_profit == 150.0
        assert account.close_profit == 30.0
        assert account.balance == 100180.0  # 静态权益 + 持仓盈亏 + 平仓盈亏


@pytest.mark.unit
class TestCallbacks:
    """ctp_api 回调处理"""

    def test_on_tick_caches_and_emits(self, gateway):
        tick = make_tick(last=3510.0)
        gateway.on_tick(tick)
        assert gateway._quotes["rb2505"].last_price == 3510.0
        event, payload = gateway._event_engine.put.call_args[0]
        assert event == EventTypes.TICK_UPDATE
        assert payload is tick

    def test_on_tick_updates_position(self, gateway):
        gateway._positions["rb2505"] = PositionData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            multiple=10,
            pos_long_td=1,
            hold_price_long=3400.0,
        )
        gateway.on_tick(make_tick(last=3500.0))
        assert gateway._positions["rb2505"].last_price == 3500.0
        assert gateway._positions["rb2505"].hold_profit == pytest.approx(1000.0)

    def test_on_order(self, gateway):
        order = OrderData(
            order_id="o1",
            symbol="rb2505",
            account_id="CTP01",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            status=OrderStatus.PENDING,
        )
        gateway.on_order(order)
        assert "o1" in gateway._orders
        assert gateway._event_engine.put.call_args[0][0] == EventTypes.ORDER_UPDATE

    def test_on_trade_creates_position_and_marks_source(self, gateway):
        gateway.contracts["rb2505"] = make_contract()
        gateway._orders["o1"] = OrderData(
            order_id="o1",
            symbol="rb2505",
            account_id="CTP01",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=2,
            price=Decimal("3450"),
        )
        trade = TradeData(
            trade_id="t1",
            order_id="o1",
            symbol="rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            price=Decimal("3500"),
            volume=2,
            account_id="CTP01",
        )

        gateway.on_trade(trade)

        assert gateway._trades["t1"].order_price == 3450  # 从报单回填
        assert gateway._positions["rb2505"].pos_long == 2
        events = [c.args[0] for c in gateway._event_engine.put.call_args_list]
        assert EventTypes.TRADE_UPDATE in events
        position_calls = [
            c
            for c in gateway._event_engine.put.call_args_list
            if c.args[0] == EventTypes.POSITION_UPDATE
        ]
        assert position_calls[0].args[1]["_source"] == "trade"

    def test_on_account_aggregates(self, gateway):
        gateway._positions["rb2505"] = PositionData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            hold_profit_long=100.0,
            hold_profit_short=0,
        )
        account = AccountData(account_id="CTP01", balance=1)
        gateway.on_account(account)
        assert account.hold_profit == 100.0
        assert gateway._event_engine.put.call_args[0][0] == EventTypes.ACCOUNT_UPDATE


@pytest.mark.unit
class TestOnStatus:
    """连接状态回调"""

    def test_no_apis_noop(self, gateway):
        gateway.on_status(ready=True)
        gateway._event_engine.put.assert_not_called()

    def test_ready_emits_account_ready(self, gateway):
        attach_apis(gateway)
        gateway.on_status(ready=True)
        events = [c.args[0] for c in gateway._event_engine.put.call_args_list]
        assert EventTypes.ACCOUNT_READY in events
        assert EventTypes.ACCOUNT_UPDATE in events

    def test_connected_resubscribes_symbols(self, gateway):
        md, _ = attach_apis(gateway)
        gateway._sub_symbols = {"rb2505", "hc2505"}

        gateway.on_status()

        # 已订阅合约按序重订 + 配置中的订阅列表，共两批
        assert md.subscribe.call_args_list[0].args[0] == ["hc2505", "rb2505"]
        assert md.subscribe.call_count == 2

    def test_not_connected_skips_subscribe(self, gateway):
        md, _ = attach_apis(gateway, connected=False)
        gateway.md_connected = False
        gateway.td_connected = False
        gateway.on_status()
        md.subscribe.assert_not_called()


@pytest.mark.unit
class TestSubscribe:
    """订阅接口"""

    def test_disconnected_defers(self, gateway):
        assert gateway.subscribe("rb2505") is False
        assert "rb2505" in gateway._sub_symbols

    def test_connected_subscribes(self, gateway):
        md, _ = attach_apis(gateway)
        assert gateway.subscribe(["rb2505"]) is True
        md.subscribe.assert_called_once_with(["rb2505"])

    def test_subscribe_bars_dedup(self, gateway):
        assert gateway.subscribe_bars("rb2505", "M1") is True
        assert gateway.subscribe_bars("rb2505", "M1") is True
        assert len(gateway._bar_subs) == 1

    def test_subscribe_bars_invalid_interval(self, gateway):
        assert gateway.subscribe_bars("rb2505", "BAD") is False

    def test_get_kline_without_generator(self, gateway):
        assert gateway.get_kline("rb2505", "M1") is None
