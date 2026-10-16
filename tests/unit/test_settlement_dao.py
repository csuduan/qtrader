"""
SettlementDao 单元测试

测试每日结算快照 DAO 的核心功能，包括：
- 结算权益快照保存与同日覆盖
- 结算持仓快照删除重写与空仓过滤
- 按日期范围查询
"""

from datetime import date

import pytest
from sqlalchemy import select

from qtrader.models.object import AccountData, Exchange, PositionData
from qtrader.trader.dao.settlement_dao import SettlementDao
from qtrader.utils.async_database import close_async_database, init_async_database


@pytest.fixture
async def dao(tmp_path):
    """初始化测试数据库并返回 DAO 实例"""
    await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield SettlementDao()
    await close_async_database()


@pytest.fixture
def sample_account() -> AccountData:
    """示例账户数据"""
    return AccountData(
        account_id="TEST",
        balance=1005000.0,
        available=900000.0,
        pre_balance=1000000.0,
        static_balance=1005000.0,
        deposit=5000.0,
        withdraw=0.0,
        close_profit=1000.0,
        hold_profit=4000.0,
        margin=100000.0,
        risk_ratio=0.1,
    )


@pytest.fixture
def sample_positions() -> dict[str, PositionData]:
    """示例持仓数据（含一个空仓）"""
    return {
        "rb2505": PositionData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            multiple=10,
            pos_long_td=2,
            pos_long_yd=1,
            pos_short_td=0,
            pos_short_yd=0,
            hold_price_long=3500.0,
            hold_profit_long=1500.0,
            margin_long=31500.0,
            last_price=3550.0,
        ),
        "IM2606": PositionData(
            symbol="IM2606",
            exchange=Exchange.CFFEX,
            multiple=200,
            pos_long_td=0,
            pos_long_yd=0,
            pos_short_td=0,
            pos_short_yd=1,
            hold_price_short=6000.0,
            hold_profit_short=-2000.0,
            margin_short=144000.0,
            last_price=6010.0,
        ),
        "empty": PositionData(
            symbol="cu2506",
            exchange=Exchange.SHFE,
            multiple=5,
        ),
    }


class TestSaveSettlement:
    """结算权益快照保存测试"""

    async def test_save_settlement(self, dao, sample_account):
        """测试保存结算权益快照"""
        settle_date = date(2026, 7, 24)
        await dao.save_settlement_snapshot("TEST", settle_date, sample_account, {})

        records = await dao.query_settlements(None, settle_date, settle_date)
        assert len(records) == 1
        record = records[0]
        assert record.account_id == "TEST"
        assert record.settle_date == settle_date
        assert float(record.balance) == 1005000.0
        assert float(record.deposit) == 5000.0
        assert float(record.withdraw) == 0.0
        assert float(record.close_profit) == 1000.0

    async def test_save_settlement_upsert_same_day(self, dao, sample_account):
        """测试同日重复保存覆盖旧记录"""
        settle_date = date(2026, 7, 24)
        await dao.save_settlement_snapshot("TEST", settle_date, sample_account, {})

        sample_account.balance = 1010000.0
        await dao.save_settlement_snapshot("TEST", settle_date, sample_account, {})

        records = await dao.query_settlements(None, settle_date, settle_date)
        assert len(records) == 1
        assert float(records[0].balance) == 1010000.0

    async def test_save_settlement_none_fields(self, dao):
        """测试 TQ 网关账户（无出入金字段）保存"""
        account = AccountData(account_id="TQ", balance=500000.0, available=400000.0)
        settle_date = date(2026, 7, 24)
        await dao.save_settlement_snapshot("TQ", settle_date, account, {})

        records = await dao.query_settlements(None, settle_date, settle_date)
        assert len(records) == 1
        assert records[0].deposit is None
        assert records[0].withdraw is None


class TestSavePositions:
    """结算持仓快照保存测试"""

    async def test_save_positions(self, dao, sample_positions):
        """测试保存持仓快照，空仓被过滤"""
        from qtrader.models.po import PositionHistoryPo
        from qtrader.utils.async_database import get_async_session

        settle_date = date(2026, 7, 24)
        await dao.save_settlement_snapshot(
            "TEST", settle_date, AccountData(account_id="TEST", balance=0.0), sample_positions
        )

        async with get_async_session() as session:
            positions = list(
                (
                    await session.execute(
                        select(PositionHistoryPo).filter_by(
                            account_id="TEST", settle_date=settle_date
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"rb2505", "IM2606"}

        rb = next(p for p in positions if p.symbol == "rb2505")
        assert rb.pos_long == 3
        assert rb.pos_short == 0
        assert float(rb.hold_price_long) == 3500.0

    async def test_save_positions_overwrite_same_day(self, dao, sample_positions):
        """测试同日重复保存先删旧记录"""
        from qtrader.models.po import PositionHistoryPo
        from qtrader.utils.async_database import get_async_session

        settle_date = date(2026, 7, 24)
        await dao.save_settlement_snapshot(
            "TEST", settle_date, AccountData(account_id="TEST", balance=0.0), sample_positions
        )

        # 第二次只保存一个持仓
        new_positions = {"rb2505": sample_positions["rb2505"]}
        await dao.save_settlement_snapshot(
            "TEST", settle_date, AccountData(account_id="TEST", balance=0.0), new_positions
        )

        async with get_async_session() as session:
            positions = list(
                (
                    await session.execute(
                        select(PositionHistoryPo).filter_by(
                            account_id="TEST", settle_date=settle_date
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(positions) == 1
        assert positions[0].symbol == "rb2505"

    async def test_snapshot_is_atomic(self, dao, sample_account, sample_positions):
        """权益与持仓在同一事务写入，持仓写入异常时权益也不落库"""
        settle_date = date(2026, 7, 24)
        bad_positions = dict(sample_positions)
        bad_positions["bad"] = None  # 触发属性访问异常

        with pytest.raises(AttributeError):
            await dao.save_settlement_snapshot("TEST", settle_date, sample_account, bad_positions)

        # 权益快照也应回滚
        records = await dao.query_settlements(None, settle_date, settle_date)
        assert records == []


class TestQuerySettlements:
    """结算权益查询测试"""

    async def test_query_by_date_range_and_accounts(self, dao, sample_account):
        """测试按日期范围和账户过滤查询"""
        monday = date(2026, 7, 20)
        for i in range(5):
            day = date(2026, 7, 20 + i)
            sample_account.balance = 1000000.0 + i * 1000
            await dao.save_settlement_snapshot("TEST", day, sample_account, {})
            await dao.save_settlement_snapshot("OTHER", day, sample_account, {})

        # 查询全部账户整周
        records = await dao.query_settlements(None, monday, date(2026, 7, 24))
        assert len(records) == 10

        # 按账户过滤
        records = await dao.query_settlements(["TEST"], monday, date(2026, 7, 24))
        assert len(records) == 5
        assert all(r.account_id == "TEST" for r in records)
        # 按日期排序
        assert [r.settle_date for r in records] == sorted(r.settle_date for r in records)

        # 部分日期范围
        records = await dao.query_settlements(["TEST"], date(2026, 7, 22), date(2026, 7, 23))
        assert len(records) == 2


class TestBuildReportHtml:
    """周报 HTML 拼接测试"""

    async def test_build_report_html(self, dao, sample_account):
        """测试合并单表生成 HTML，每账户取最新一日数据并显示账户名称"""
        from qtrader.manager.job_mgr import _build_settlement_report_html
        from qtrader.utils.config_loader import AccountConfig, AppConfig

        monday = date(2026, 7, 20)
        friday = date(2026, 7, 24)
        await dao.save_settlement_snapshot("AAA", monday, sample_account, {})
        await dao.save_settlement_snapshot("AAA", friday, sample_account, {})
        await dao.save_settlement_snapshot("BBB", friday, sample_account, {})

        app_config = AppConfig(
            accounts=[
                AccountConfig(account_id="AAA", name="账户A"),
                AccountConfig(account_id="BBB", name="账户B"),
            ]
        )

        records = await dao.query_settlements(None, monday, friday)
        html = _build_settlement_report_html(records, friday, app_config)

        # 全部账户合并一张表，每账户取最新一日数据
        assert html.count("<table") == 1
        assert ">AAA</td>" in html and ">账户A</td>" in html
        assert ">BBB</td>" in html and ">账户B</td>" in html
        assert html.count("1,005,000.00") == 2  # 每账户仅保留最新一日
        assert "5,000.00" in html  # deposit 格式化
        assert "结算权益" in html and "账户名称" in html

    async def test_build_report_html_none_fields(self, dao):
        """测试无配置名称及无出入金的字段显示为 -"""
        from qtrader.manager.job_mgr import _build_settlement_report_html
        from qtrader.utils.config_loader import AppConfig

        monday = date(2026, 7, 20)
        account = AccountData(account_id="TQ", balance=500000.0, available=400000.0)
        await dao.save_settlement_snapshot("TQ", monday, account, {})

        records = await dao.query_settlements(None, monday, monday)
        html = _build_settlement_report_html(records, monday, AppConfig())

        assert ">TQ</td>" in html
        assert ">-</td>" in html  # 无名称及 None 字段显示为 -
