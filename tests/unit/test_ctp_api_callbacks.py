"""
CtpTdApi 回调单元测试（加载真实 ctp_api 模块）

通过 importlib 从文件路径加载真实 ctp_api（绕开 test_ctp_gateway.py 对该模块的
sys.modules 整体 mock），以 mock gateway 驱动订单/成交回调，
覆盖报单、报错误单、废单、撤单、成交单的状态映射与 REJECTED 判定。
不连接真实 CTP 前置。
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import qtrader
from qtrader.app_context import AppContext, get_app_context
from qtrader.models.object import (
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderStatus,
)

# 不经 ctp_gateway 定位路径：模块级 import 会触发 ctp_api 导入链，
# 而此时应用配置尚未注入
MODULE_PATH = Path(qtrader.__file__).parent / "trader" / "gateway" / "ctp_api.py"


def _make_config() -> MagicMock:
    """构造可导入 ctp_api 的最小配置（broker.type 为空走默认 ctpx.ctp 分支）"""
    config = MagicMock()
    broker = MagicMock()
    broker.type = ""
    config.gateway.broker = broker
    config.gateway.account_id = "CTP01"
    return config


@pytest.fixture(scope="module")
def ctp_api_mod():
    """从文件路径加载真实 ctp_api 模块（避免与其他测试的模块级 mock 相互干扰）"""
    ctx = get_app_context()
    ctx.set(AppContext.KEY_CONFIG, _make_config())
    try:
        spec = importlib.util.spec_from_file_location("ctp_api_under_test", MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["ctp_api_under_test"] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop("ctp_api_under_test", None)
            raise
        yield mod
    finally:
        ctx.remove(AppContext.KEY_CONFIG)
        sys.modules.pop("ctp_api_under_test", None)


@pytest.fixture
def td_api(ctp_api_mod):
    return ctp_api_mod.CtpTdApi(MagicMock())


def seed_order(td) -> OrderData:
    """预置 order_map 中的本地订单（模拟 send_order 后的回报匹配对象）"""
    order = OrderData(
        order_id="1001",
        symbol="rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=2,
        account_id="CTP01",
        status=OrderStatus.PENDING,
    )
    td.order_map["1001"] = order
    return order


def make_ctp_order(tdapi, status, msg="", traded=0):
    return SimpleNamespace(
        OrderRef="1001",
        OrderStatus=status,
        StatusMsg=msg,
        OrderSysID="SYS001",
        VolumeTraded=traded,
    )


@pytest.mark.unit
class TestOnRtnOrder:
    """OnRtnOrder 委托回报：状态映射与 REJECTED 判定"""

    def test_queuing_maps_pending(self, td_api, ctp_api_mod):
        """报单挂出（未成交排队）→ PENDING"""
        order = seed_order(td_api)
        td_api.OnRtnOrder(
            make_ctp_order(ctp_api_mod.tdapi, ctp_api_mod.tdapi.THOST_FTDC_OST_NoTradeQueueing)
        )
        assert order.status == OrderStatus.PENDING
        td_api.gateway.on_order.assert_called_once()

    def test_part_traded_maps_pending(self, td_api, ctp_api_mod):
        """部分成交仍在队列 → PENDING"""
        order = seed_order(td_api)
        td_api.OnRtnOrder(
            make_ctp_order(
                ctp_api_mod.tdapi,
                ctp_api_mod.tdapi.THOST_FTDC_OST_PartTradedQueueing,
                traded=1,
            )
        )
        assert order.status == OrderStatus.PENDING
        assert order.traded == 1

    def test_all_traded_maps_finished(self, td_api, ctp_api_mod):
        """全部成交 → FINISHED，成交数更新，本地订单移除"""
        order = seed_order(td_api)
        td_api.OnRtnOrder(
            make_ctp_order(
                ctp_api_mod.tdapi, ctp_api_mod.tdapi.THOST_FTDC_OST_AllTraded, traded=2
            )
        )
        assert order.status == OrderStatus.FINISHED
        assert order.traded == 2
        assert "1001" not in td_api.order_map

    def test_canceled_maps_finished(self, td_api, ctp_api_mod):
        """正常撤单（无错误文案）→ FINISHED"""
        order = seed_order(td_api)
        td_api.OnRtnOrder(
            make_ctp_order(ctp_api_mod.tdapi, ctp_api_mod.tdapi.THOST_FTDC_OST_Canceled)
        )
        assert order.status == OrderStatus.FINISHED

    def test_reject_msg_maps_rejected(self, td_api, ctp_api_mod):
        """废单：Canceled + 错误文案（资金不足）→ REJECTED"""
        order = seed_order(td_api)
        td_api.OnRtnOrder(
            make_ctp_order(
                ctp_api_mod.tdapi,
                ctp_api_mod.tdapi.THOST_FTDC_OST_Canceled,
                msg="资金不足",
            )
        )
        assert order.status == OrderStatus.REJECTED
        assert order.status_msg == "资金不足"
        assert "1001" not in td_api.order_map

    def test_cancel_msg_with_error_word_maps_rejected(self, td_api, ctp_api_mod):
        """回归：撤单类文案含错误关键词时同样判 REJECTED

        命中 error_msg 即为错误单，不再按撤单关键词排除
        （撤单被拒走 OnRspOrderAction/OnErrRtnOrderAction 专用回调，不进本回报）。
        """
        order = seed_order(td_api)
        td_api.OnRtnOrder(
            make_ctp_order(
                ctp_api_mod.tdapi,
                ctp_api_mod.tdapi.THOST_FTDC_OST_Canceled,
                msg="已撤单报单被拒绝CFFEX:当前状态禁止此项操作",
            )
        )
        assert order.status == OrderStatus.REJECTED


@pytest.mark.unit
class TestOnErrRtnOrderInsert:
    """OnErrRtnOrderInsert 交易所报单失败回报"""

    def test_exchange_reject_maps_rejected(self, td_api):
        """交易所拒单（私有流）→ REJECTED 并推送"""
        order = seed_order(td_api)
        td_api.OnErrRtnOrderInsert(
            SimpleNamespace(OrderRef="1001"),
            SimpleNamespace(ErrorID=30, ErrorMsg="资金不足"),
        )
        assert order.status == OrderStatus.REJECTED
        assert order.status_msg == "资金不足"
        td_api.gateway.on_order.assert_called_once()

    def test_zero_error_id_noop(self, td_api):
        """无错误（ErrorID=0）不推送"""
        seed_order(td_api)
        td_api.OnErrRtnOrderInsert(
            SimpleNamespace(OrderRef="1001"),
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
        )
        td_api.gateway.on_order.assert_not_called()


@pytest.mark.unit
class TestOnRtnTrade:
    """OnRtnTrade 成交回报推送"""

    def test_trade_pushed(self, td_api):
        """成交回报 → 构造 TradeData 推送 gateway.on_trade"""
        trade = SimpleNamespace(
            TradeID="T1",
            OrderRef="1001",
            InstrumentID="rb2505",
            ExchangeID="SHFE",
            Direction="0",  # THOST_FTDC_D_Buy
            OffsetFlag="0",  # THOST_FTDC_OF_Open
            Price=3500.0,
            Volume=1,
            TradeDate="20260909",
            TradeTime="10:00:00",
        )
        td_api.OnRtnTrade(trade)
        td_api.gateway.on_trade.assert_called_once()
        pushed = td_api.gateway.on_trade.call_args[0][0]
        assert pushed.trade_id == "T1"
        assert pushed.order_id == "1001"
        assert pushed.symbol == "rb2505"
        assert pushed.price == 3500.0
        assert pushed.volume == 1
