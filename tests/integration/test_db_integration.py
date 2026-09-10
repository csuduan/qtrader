"""
数据库集成测试（真实 PostgreSQL）

验证 DAO 层在真实 PG 方言下的行为——SQLite 单测无法覆盖的路径：
- BarDAO 的 PG 专有 upsert（on_conflict_do_update / on_conflict_do_nothing）
- Numeric 精度、外键约束、部分索引等真实约束

门控：环境变量 QTRADER_TEST_DB_URL，未设置则整模块 skip。

环境隔离（二选一，均不触碰生产数据）：
- 独立数据库（需 pg_hba.conf 放行该库）：postgresql://user:pass@host:5432/qtrader_test
- 同库独立 schema（URL 传 search_path）：postgresql://user:pass@host:5432/qtrader?options=-csearch_path=test

注：qtrader_test 库采用角色级 search_path 隔离（tester→tester schema、dev→dev schema），
连接 URL 无需再传 options，角色设置自动生效。
异步驱动：async_database 基于 asyncpg，环境变量中的 psycopg 驱动自动替换为 asyncpg。

回退：每个用例结束后 TRUNCATE 涉及表（DAO 内部 get_async_session 自行 commit，
外部事务回滚管不到，直接清表最可靠）。
"""

import os
from datetime import date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from qtrader.models.object import (
    AccountData,
    BarData,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderStatus,
    PositionData,
    ProductType,
    TradeData,
)
from qtrader.utils.async_database import (
    close_async_database,
    get_async_session,
    init_async_database,
)

TEST_DB_URL = (
    os.environ.get("QTRADER_TEST_DB_URL", "")
    .replace("postgresql+psycopg://", "postgresql+asyncpg://")
    .replace("postgresql://", "postgresql+asyncpg://")
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        not TEST_DB_URL,
        reason="未设置 QTRADER_TEST_DB_URL，跳过真实 PostgreSQL 集成测试",
    ),
]

# 用例涉及的全部业务表（TRUNCATE 回退用）
_TABLES = (
    "bars_history",
    "bars_today",
    "positions",
    "trades",
    "orders",
    "account_history",
    "positions_history",
    "accounts",
)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg_db():
    """模块级：初始化真实 PG 连接并建表，模块结束释放"""
    await init_async_database(TEST_DB_URL)
    yield
    await close_async_database()


@pytest.fixture()
async def clean_tables(pg_db, ensure_account):
    """用例级：测完 TRUNCATE 回退数据（含外键引用的 accounts 表）"""
    yield
    async with get_async_session() as session:
        await session.execute(text(f"TRUNCATE TABLE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture()
async def ensure_account(pg_db):
    """positions/orders/trades 均有 accounts 外键，先插入账户记录"""
    from qtrader.models.po import AccountPo

    async with get_async_session() as session:
        session.add(AccountPo(account_id="ITEST"))
    return "ITEST"


def make_bar_dict(bar_time: datetime, close: float) -> dict:
    return {
        "symbol": "SHFE.rb2701",
        "interval": "1m",
        "bar_time": bar_time,
        "trading_day": bar_time.date(),
        "open": close - 5,
        "high": close + 5,
        "low": close - 10,
        "close": close,
        "volume": 100,
        "turnover": close * 100,
        "open_interest": 1000,
    }


@pytest.mark.usefixtures("clean_tables")
class TestBarDaoUpsert:
    """BarDAO PG 专有 upsert（SQLite 无法编译执行，真实库是唯一可测路径）"""

    async def test_upsert_history_insert_then_update(self):
        """首次写入插入，重复写入（同 symbol/interval/bar_time）覆盖旧值"""
        from qtrader.trader.dao.bar_dao import BarDao

        dao = BarDao()
        t = datetime(2026, 9, 9, 21, 0)
        assert await dao.upsert_history_bars([make_bar_dict(t, 3500.0)], source="itests") == 1

        # 冲突更新：同K线改收盘价再写
        assert await dao.upsert_history_bars([make_bar_dict(t, 3600.0)], source="itests") == 1

        bars = await dao.query_history_bars(
            "SHFE.rb2701", "1m", datetime(2026, 9, 9, 20, 0), datetime(2026, 9, 9, 22, 0)
        )
        assert len(bars) == 1
        assert float(bars[0].close_price) == 3600.0

    async def test_upsert_history_batch_distinct_times(self):
        """不同 bar_time 互不冲突，批量写入全量保留"""
        from qtrader.trader.dao.bar_dao import BarDao

        dao = BarDao()
        bars = [make_bar_dict(datetime(2026, 9, 9, 21, i), 3500.0 + i) for i in range(5)]
        assert await dao.upsert_history_bars(bars, source="itests") == 5

        got = await dao.query_history_bars(
            "SHFE.rb2701", "1m", datetime(2026, 9, 9, 21, 0), datetime(2026, 9, 9, 21, 4)
        )
        assert len(got) == 5
        assert [float(b.close_price) for b in got] == [3500.0, 3501.0, 3502.0, 3503.0, 3504.0]

    async def test_upsert_today_conflict_nothing(self):
        """当日K线 upsert（on_conflict_do_nothing）：重复写入不报错不重复"""
        from qtrader.trader.dao.bar_dao import BarDao

        dao = BarDao()
        bar = BarData(
            symbol="SHFE.rb2701",
            exchange=Exchange.SHFE,
            datetime=datetime(2026, 9, 9, 21, 0),
            interval="1m",
            open_price=3500.0,
            high_price=3505.0,
            low_price=3495.0,
            close_price=3502.0,
            volume=100,
        )
        assert await dao.upsert_today_bars("ITEST", [bar], date(2026, 9, 9)) in (1, -1)
        await dao.upsert_today_bars("ITEST", [bar], date(2026, 9, 9))

        got = await dao.query_today_bars(
            "SHFE.rb2701", "1m", datetime(2026, 9, 9, 20, 0), datetime(2026, 9, 9, 22, 0)
        )
        assert len(got) == 1


@pytest.mark.usefixtures("clean_tables")
class TestPositionDao:
    """StrategyPositionService：策略持仓在真实 PG 下的增改查删"""

    async def test_save_load_update_clear(self):
        from qtrader.trader.dao.position_dao import StrategyPositionService

        svc = StrategyPositionService()
        pos = PositionData(
            symbol="SHFE.rb2701",
            exchange=Exchange.SHFE,
            strategy_id="ITEST_STRAT",
            multiple=10,
            pos_long_td=2,
            hold_price_long=3500.0,
        )
        pos.extras["account_id"] = "ITEST"

        assert await svc.save_position(pos) is True

        loaded = await svc.load_positions("ITEST", "ITEST_STRAT")
        assert len(loaded) == 1
        assert loaded[0].pos_long_td == 2

        # 更新：同键再存覆盖
        pos.pos_long_td = 5
        assert await svc.save_position(pos) is True
        assert (await svc.load_positions("ITEST", "ITEST_STRAT"))[0].pos_long_td == 5

        # 删除
        assert await svc.clear_position("ITEST", "ITEST_STRAT", "SHFE.rb2701") is True
        assert await svc.load_positions("ITEST", "ITEST_STRAT") == []


@pytest.mark.usefixtures("clean_tables")
class TestOrderTradeDao:
    """OrderDao/TradeDao：委托与成交在真实 PG 下的持久化与幂等"""

    async def test_order_save_and_update(self, ensure_account):
        """订单保存后更新状态（同 account+order_id 覆盖）"""
        from qtrader.trader.dao.order_dao import OrderDao

        dao = OrderDao()
        order = OrderData(
            order_id="ITEST-O1",
            symbol="SHFE.rb2701",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=2,
            price=3500.0,
            account_id="ITEST",
            status=OrderStatus.PENDING,
        )
        await dao.save("ITEST", order)

        order.status = OrderStatus.FINISHED
        order.traded = 2
        await dao.save("ITEST", order)

        async with get_async_session() as session:
            from qtrader.models.po import OrderPo

            rows = (
                (await session.execute(select(OrderPo).filter_by(account_id="ITEST")))
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].status == "FINISHED"
            assert rows[0].volume_left == 0

    async def test_trade_save_idempotent(self, ensure_account):
        """成交按 trade_id 幂等：重复保存不产生重复记录"""
        from qtrader.trader.dao.trade_dao import TradeDao

        dao = TradeDao()
        trade = TradeData(
            trade_id="ITEST-T1",
            order_id="ITEST-O1",
            symbol="SHFE.rb2701",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            price=3500.0,
            volume=1,
            account_id="ITEST",
            trade_time=datetime(2026, 9, 9, 21, 0, 0),
        )
        await dao.save("ITEST", trade)
        await dao.save("ITEST", trade)

        async with get_async_session() as session:
            from qtrader.models.po import TradePo

            rows = (
                (await session.execute(select(TradePo).filter_by(account_id="ITEST")))
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert float(rows[0].price) == 3500.0


@pytest.mark.usefixtures("clean_tables")
class TestSettlementDao:
    """SettlementDao：结算快照同日覆盖与范围查询"""

    async def test_save_same_day_overwrite_and_query(self, ensure_account):
        from qtrader.trader.dao.settlement_dao import SettlementDao

        dao = SettlementDao()
        account = AccountData(
            account_id="ITEST",
            balance=100000.0,
            available=90000.0,
        )
        d = date(2026, 9, 9)
        await dao.save_settlement_snapshot("ITEST", d, account, {})
        account.balance = 105000.0
        await dao.save_settlement_snapshot("ITEST", d, account, {})

        records = await dao.query_settlements(["ITEST"], date(2026, 9, 1), date(2026, 9, 30))
        assert len(records) == 1
        assert float(records[0].balance) == 105000.0
