"""
OrderDao / TradeDao 单元测试

测试订单与成交数据持久化 DAO 的核心功能，包括：
- 订单字段往返（含交易所单号回退、委托量为空/None 处理）
- 同订单 upsert（状态更新）
- 成交去重（trade_id 已存在则跳过）
- 缺失主键时跳过写入
- 异常吞并（save 不向上抛出）
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qtrader.models.object import (
    Direction,
    Offset,
    OrderData,
    OrderStatus,
    OrderType,
    TradeData,
)
from qtrader.models.po import AccountPo, OrderPo, TradePo
from qtrader.trader.dao.order_dao import OrderDao
from qtrader.trader.dao.trade_dao import TradeDao
from qtrader.utils.database import close_database, init_database, session_scope

INSERT_TIME = datetime(2026, 8, 28, 9, 30, 5)
UPDATE_TIME = datetime(2026, 8, 28, 9, 30, 15)


@pytest.fixture
def db(tmp_path):
    """初始化测试数据库"""
    init_database(f"sqlite:///{tmp_path}/test.db")
    # 订单/成交表存在指向账户表的外键，预先写入账户记录
    with session_scope() as session:
        session.add(AccountPo(account_id="TEST"))
    yield
    close_database()


def _make_order(**overrides) -> OrderData:
    """构造测试订单"""
    fields = dict(
        order_id="O1",
        symbol="IM2609",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=5,
        traded=2,
        price=3500.5,
        price_type=OrderType.LIMIT,
        status=OrderStatus.FINISHED,
        account_id="TEST",
        gateway_order_id="SYS123",
        insert_time=INSERT_TIME,
        update_time=UPDATE_TIME,
    )
    fields.update(overrides)
    return OrderData(**fields)


def _make_trade(**overrides) -> TradeData:
    """构造测试成交"""
    fields = dict(
        trade_id="T1",
        order_id="O1",
        symbol="IM2609",
        direction=Direction.SELL,
        offset=Offset.CLOSETODAY,
        price=3510.0,
        volume=3,
        account_id="TEST",
        trade_time=UPDATE_TIME,
        order_price=3505.0,
    )
    fields.update(overrides)
    return TradeData(**fields)


def _query_order(order_id: str) -> OrderPo | None:
    """查询订单持久化记录"""
    with session_scope() as session:
        po = session.query(OrderPo).filter_by(order_id=order_id).first()
        _ = (po.symbol, po.direction, po.volume_left) if po else None
        return po


def _count_orders() -> int:
    with session_scope() as session:
        return session.query(OrderPo).count()


def _query_trade(trade_id: str) -> TradePo | None:
    """查询成交持久化记录"""
    with session_scope() as session:
        po = session.query(TradePo).filter_by(trade_id=trade_id).first()
        _ = (po.symbol, po.direction, po.price) if po else None
        return po


def _count_trades() -> int:
    with session_scope() as session:
        return session.query(TradePo).count()


@pytest.mark.unit
class TestOrderDaoSave:
    """订单写入测试"""

    def test_save_order_full_fields_roundtrip(self, db):
        """测试全字段写入与读回"""
        OrderDao().save("TEST", _make_order())

        po = _query_order("O1")
        assert po is not None
        assert po.account_id == "TEST"
        assert po.symbol == "IM2609"
        assert po.direction == "BUY"
        assert po.offset == "OPEN"
        assert float(po.limit_price) == pytest.approx(3500.5)
        assert po.volume_orign == 5
        assert po.volume_left == 3  # volume - traded
        assert po.status == "FINISHED"
        assert po.price_type == "LIMIT"
        assert po.exchange_order_id == "SYS123"
        assert po.insert_date_time == INSERT_TIME
        assert po.update_date_time == UPDATE_TIME

    def test_save_order_market_price(self, db):
        """测试市价单（price=None）limit_price 写空"""
        OrderDao().save("TEST", _make_order(price=None, price_type=OrderType.MARKET))

        po = _query_order("O1")
        assert po.limit_price is None
        assert po.price_type == "MARKET"

    def test_save_order_exchange_id_fallback(self, db):
        """测试无网关单号时回退使用 order_sys_id"""
        order = _make_order(gateway_order_id=None)
        order.order_sys_id = "SYS456"

        OrderDao().save("TEST", order)

        assert _query_order("O1").exchange_order_id == "SYS456"

    def test_save_order_upsert_updates_status(self, db):
        """测试同订单重复保存为更新而非新增"""
        dao = OrderDao()
        dao.save("TEST", _make_order(status=OrderStatus.PENDING))
        dao.save("TEST", _make_order(status=OrderStatus.FINISHED, traded=5))

        assert _count_orders() == 1
        po = _query_order("O1")
        assert po.status == "FINISHED"
        assert po.volume_left == 0

    def test_save_order_insert_time_fallback(self, db):
        """测试无下单时间时回退使用最后更新时间"""
        OrderDao().save("TEST", _make_order(insert_time=None))

        assert _query_order("O1").insert_date_time == UPDATE_TIME

    def test_save_order_insert_and_update_time_missing(self, db):
        """测试下单与更新时间均缺失时写当前时间"""
        OrderDao().save("TEST", _make_order(insert_time=None, update_time=None))

        assert _query_order("O1").insert_date_time is not None

    def test_save_order_without_order_id_skipped(self, db):
        """测试缺失订单号时不写入"""
        with session_scope() as session:
            OrderDao()._save_with_session(session, "TEST", SimpleNamespace(symbol="IM2609"))

        assert _count_orders() == 0

    def test_save_order_swallows_exception(self):
        """测试数据库异常被捕获记录，不向上抛出"""
        with patch(
            "qtrader.trader.dao.order_dao.session_scope",
            side_effect=RuntimeError("db down"),
        ):
            OrderDao().save("TEST", _make_order())  # 不应抛出


@pytest.mark.unit
class TestTradeDaoSave:
    """成交写入测试"""

    def test_save_trade_full_fields_roundtrip(self, db):
        """测试全字段写入与读回"""
        TradeDao().save("TEST", _make_trade())

        po = _query_trade("T1")
        assert po is not None
        assert po.account_id == "TEST"
        assert po.order_id == "O1"
        assert po.symbol == "IM2609"
        assert po.direction == "SELL"
        assert po.offset == "CLOSETODAY"
        assert float(po.price) == pytest.approx(3510.0)
        assert float(po.order_price) == pytest.approx(3505.0)
        assert po.volume == 3
        assert po.trade_date_time == UPDATE_TIME

    def test_save_trade_dedupes_by_trade_id(self, db):
        """测试同 trade_id 重复保存被跳过"""
        dao = TradeDao()
        dao.save("TEST", _make_trade())
        dao.save("TEST", _make_trade(price=9999.0))

        assert _count_trades() == 1
        assert float(_query_trade("T1").price) == pytest.approx(3510.0)

    def test_save_trade_without_trade_id_skipped(self, db):
        """测试缺失成交ID时不写入"""
        with session_scope() as session:
            TradeDao()._save_with_session(session, "TEST", SimpleNamespace(symbol="IM2609"))

        assert _count_trades() == 0

    def test_save_trade_time_defaults_to_now(self, db):
        """测试无成交时间时写当前时间"""
        TradeDao().save("TEST", _make_trade(trade_time=None))

        assert _query_trade("T1").trade_date_time is not None

    def test_save_trade_order_price_none(self, db):
        """测试无报单价格时 order_price 写空"""
        TradeDao().save("TEST", _make_trade(order_price=None))

        assert _query_trade("T1").order_price is None

    def test_save_trade_swallows_exception(self):
        """测试数据库异常被捕获记录，不向上抛出"""
        with patch(
            "qtrader.trader.dao.trade_dao.session_scope",
            side_effect=RuntimeError("db down"),
        ):
            TradeDao().save("TEST", _make_trade())  # 不应抛出
