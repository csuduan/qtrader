"""
BarDao / collect_bar_subscriptions / ManagerDataFeed 单元测试

测试内容：
- bar表查询与清理（sqlite内存库，upsert为PostgreSQL方言仅验证入参构造）
- 订阅汇总逻辑
- ManagerDataFeed 的周期解析与合约代码转换
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from qtrader.models.object import BarData
from qtrader.models.po import BarTodayPo
from qtrader.trader.dao.bar_dao import BarDao
from qtrader.utils.async_database import (
    close_async_database,
    get_async_session,
    init_async_database,
)


@pytest.fixture
async def dao(tmp_path):
    """初始化测试数据库并返回DAO实例"""
    await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield BarDao()
    await close_async_database()


def _make_bar(symbol: str, dt: datetime, close: float = 100.0) -> BarData:
    """构造测试bar"""
    return BarData(
        symbol=symbol,
        interval="M1",
        datetime=dt,
        open_price=close - 1,
        high_price=close + 1,
        low_price=close - 2,
        close_price=close,
        volume=10,
    )


class TestBarDaoQuery:
    """查询与清理逻辑测试（ORM操作，sqlite可跑）"""

    async def test_query_history_bars_filters_and_sorts(self, dao):
        from qtrader.models.po import BarHistoryPo

        base = datetime(2026, 8, 26, 9, 30)
        async with get_async_session() as session:
            for i in range(5):
                session.add(
                    BarHistoryPo(
                        symbol="IM2609",
                        interval="M1",
                        bar_time=base + timedelta(minutes=i),
                        trading_day=base.date(),
                        open_price=100,
                        high_price=101,
                        low_price=99,
                        close_price=100,
                    )
                )
            # 其他合约不应被查出
            session.add(
                BarHistoryPo(
                    symbol="IC2609",
                    interval="M1",
                    bar_time=base,
                    trading_day=base.date(),
                    open_price=100,
                    high_price=101,
                    low_price=99,
                    close_price=100,
                )
            )

        start = base + timedelta(minutes=1)
        end = base + timedelta(minutes=3)
        result = await dao.query_history_bars("IM2609", "M1", start, end)
        assert len(result) == 3
        assert [p.bar_time for p in result] == sorted(p.bar_time for p in result)
        assert all(start <= p.bar_time <= end for p in result)

    async def test_query_today_bars_dedupes_by_time(self, dao):
        base = datetime(2026, 8, 27, 9, 30)
        async with get_async_session() as session:
            # 两个写入者写同一根bar + 一个独有bar
            for account in ["AAA", "MANAGER"]:
                session.add(
                    BarTodayPo(
                        symbol="IM2609",
                        interval="M1",
                        bar_time=base,
                        trading_day=base.date(),
                        account_id=account,
                        open_price=100,
                        high_price=101,
                        low_price=99,
                        close_price=100,
                    )
                )
            session.add(
                BarTodayPo(
                    symbol="IM2609",
                    interval="M1",
                    bar_time=base + timedelta(minutes=1),
                    trading_day=base.date(),
                    account_id="AAA",
                    open_price=100,
                    high_price=101,
                    low_price=99,
                    close_price=101,
                )
            )

        result = await dao.query_today_bars("IM2609", "M1", base, base + timedelta(minutes=1))
        assert len(result) == 2  # 时间去重后每根bar只留一条

    async def test_cleanup_today_bars_keeps_given_date(self, dao):
        old_day = datetime(2026, 8, 25, 9, 30)
        today = datetime(2026, 8, 27, 9, 30)
        async with get_async_session() as session:
            for dt in [old_day, today]:
                session.add(
                    BarTodayPo(
                        symbol="IM2609",
                        interval="M1",
                        bar_time=dt,
                        trading_day=dt.date(),
                        account_id="MANAGER",
                        open_price=100,
                        high_price=101,
                        low_price=99,
                        close_price=100,
                    )
                )

        deleted = await dao.cleanup_today_bars(keep_date=today.date())
        assert deleted == 1
        assert len(await dao.query_today_bars("IM2609", "M1", today, today)) == 1

    async def test_query_accepts_tz_aware_inputs(self, dao):
        """aware入参自动转naive（asyncpg拒绝aware绑定 timestamp without time zone 列）"""
        from qtrader.models.po import BarHistoryPo

        base = datetime(2026, 9, 9, 14, 10)
        async with get_async_session() as session:
            session.add(
                BarHistoryPo(
                    symbol="IM2609",
                    interval="M1",
                    bar_time=base,
                    trading_day=base.date(),
                    open_price=100,
                    high_price=101,
                    low_price=99,
                    close_price=100,
                )
            )

        # 本地时区aware窗口覆盖naive落库的base
        start = (base - timedelta(minutes=1)).astimezone()
        end = (base + timedelta(minutes=1)).astimezone()
        assert start.tzinfo is not None

        result = await dao.query_history_bars("IM2609", "M1", start, end)
        assert len(result) == 1
        assert result[0].bar_time == base

    async def test_upsert_history_bars_empty(self, dao):
        assert await dao.upsert_history_bars([], "tq") == 0

    async def test_upsert_today_bars_empty(self, dao):
        assert await dao.upsert_today_bars("MANAGER", [], date.today()) == 0

    async def test_dao_routes_to_named_instance(self, tmp_path):
        """BarDao(db_name=...) 读写指定实例，与默认实例隔离（feed线程独立事件循环场景）"""
        from qtrader.manager.data_feed import FEED_DB_NAME

        await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/default.db")
        await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/feed.db", name=FEED_DB_NAME)
        try:
            base = datetime(2026, 9, 10, 21, 0)
            feed_dao = BarDao(db_name=FEED_DB_NAME)
            await feed_dao.upsert_today_bars("MANAGER", [_make_bar("IM2609", base)], base.date())

            # 写入落在 feed 实例
            assert len(await feed_dao.query_today_bars("IM2609", "M1", base, base)) == 1
            # 默认实例无该数据（跨循环共享会报 attached to a different loop，必须隔离）
            assert len(await BarDao().query_today_bars("IM2609", "M1", base, base)) == 0
        finally:
            await close_async_database(name=FEED_DB_NAME)
            await close_async_database()


class TestToNaive:
    """时区归一化辅助函数测试"""

    def test_naive_passthrough(self):
        from qtrader.trader.dao.bar_dao import _to_naive

        naive = datetime(2026, 9, 9, 14, 10)
        assert _to_naive(naive) == naive
        assert _to_naive(naive).tzinfo is None

    def test_aware_converts_to_local_wall_time(self):
        """aware转本地时间：与 datetime.fromtimestamp 口径一致（时区无关断言）"""
        from qtrader.trader.dao.bar_dao import _to_naive

        utc_dt = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
        naive = _to_naive(utc_dt)
        assert naive.tzinfo is None
        assert naive == datetime.fromtimestamp(utc_dt.timestamp())


class TestCollectBarSubscriptions:
    """订阅汇总逻辑测试"""

    def _make_account(self, account_id: str, enabled: bool, strategies: dict):
        account = MagicMock()
        account.account_id = account_id
        account.enabled = enabled
        account.strategies = strategies
        return account

    def _make_strategy(self, enabled: bool, symbol: str, bar: str = "M1"):
        strategy = MagicMock()
        strategy.enabled = enabled
        strategy.symbol = symbol
        strategy.bar = bar
        return strategy

    def test_collect_dedupes_across_accounts(self):
        from qtrader.manager.data_feed import collect_bar_subscriptions

        app_config = MagicMock()
        app_config.subs = None
        accounts = [
            self._make_account("A", True, {"s1": self._make_strategy(True, "IM2609")}),
            self._make_account("B", True, {"s2": self._make_strategy(True, "IM2609")}),
            self._make_account("C", True, {"s3": self._make_strategy(True, "IC2609")}),
        ]
        subs = collect_bar_subscriptions(app_config, accounts)
        assert sorted(subs) == [("IC2609", "M1"), ("IM2609", "M1")]

    def test_collect_skips_disabled(self):
        from qtrader.manager.data_feed import collect_bar_subscriptions

        app_config = MagicMock()
        app_config.subs = None
        accounts = [
            self._make_account("A", False, {"s1": self._make_strategy(True, "IM2609")}),
            self._make_account("B", True, {"s2": self._make_strategy(False, "IC2609")}),
        ]
        assert collect_bar_subscriptions(app_config, accounts) == []

    def test_collect_includes_global_subs(self):
        from qtrader.manager.data_feed import collect_bar_subscriptions

        app_config = MagicMock()
        app_config.subs.subscribe_bars = ["rb2510-M5"]
        subs = collect_bar_subscriptions(app_config, [])
        assert subs == [("rb2510", "M5")]


class TestManagerDataFeed:
    """ManagerDataFeed 辅助逻辑测试（不连真实tqsdk）"""

    def _make_feed(self):
        from qtrader.manager.data_feed import ManagerDataFeed

        return ManagerDataFeed("user", "pass", lambda: [])

    def test_request_resync_not_connected(self):
        feed = self._make_feed()
        assert "未连接" in feed.request_resync()

    def test_request_resync_sets_flag(self):
        feed = self._make_feed()
        feed.api = MagicMock()  # 模拟已连接
        feed._running = True
        message = feed.request_resync()
        assert feed._resync_requested is True
        assert "触发" in message

    def test_sync_history_delegates_to_resync(self):
        feed = self._make_feed()
        feed.api = MagicMock()
        feed._running = True
        feed.sync_history()
        assert feed._resync_requested is True

    async def test_resolve_tq_symbol_queries_contracts(self, tmp_path):
        from qtrader.manager.data_feed import FEED_DB_NAME
        from qtrader.models.po import ContractPo

        await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/test.db", name=FEED_DB_NAME)
        try:
            async with get_async_session(name=FEED_DB_NAME) as session:
                # 真实存储格式：裸合约代码（TqContractFetcher 写入）
                session.add(
                    ContractPo(
                        symbol="IM2609",
                        exchange_id="CFFEX",
                        update_date="2026-08-27",
                    )
                )
                # 兼容带前缀的历史数据
                session.add(
                    ContractPo(
                        symbol="SHFE.rb2510",
                        exchange_id="SHFE",
                        update_date="2026-08-27",
                    )
                )
            feed = self._make_feed()
            assert await feed._resolve_tq_symbol("IM2609") == "CFFEX.IM2609"
            assert await feed._resolve_tq_symbol("rb2510") == "SHFE.rb2510"
            assert await feed._resolve_tq_symbol("XX9999") is None
        finally:
            await close_async_database(name=FEED_DB_NAME)
