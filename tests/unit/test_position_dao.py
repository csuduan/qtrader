"""
StrategyPositionService（position_dao）单元测试

测试策略持仓持久化服务的核心功能，包括：
- 持仓保存（新建/更新）与 PositionData <-> PositionPo 字段往返
- 按账户+策略加载（空仓过滤）
- 单合约加载
- 按合约/策略/账户清仓
- 异常路径返回 False / 空列表
"""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from qtrader.models.object import Exchange, PositionData
from qtrader.models.po import PositionPo
from qtrader.trader.dao.position_dao import StrategyPositionService
from qtrader.utils.async_database import (
    close_async_database,
    get_async_session,
    init_async_database,
)


@pytest.fixture
async def service(tmp_path):
    """初始化测试数据库并返回服务实例"""
    await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield StrategyPositionService()
    await close_async_database()


def _make_position(symbol: str = "IM2609", strategy_id: str = "s1", **overrides) -> PositionData:
    """构造策略持仓"""
    fields = dict(
        symbol=symbol,
        exchange=Exchange.CFFEX,
        multiple=200,
        strategy_id=strategy_id,
        pos_long_td=2,
        pos_long_yd=1,
        pos_short_td=0,
        pos_short_yd=0,
        hold_price_long=6000.0,
        hold_price_short=0,
        close_profit_long=1500.0,
        close_profit_short=0,
        extras={"account_id": "TEST"},
    )
    fields.update(overrides)
    return PositionData(**fields)


async def _insert_po(**kwargs) -> None:
    """直接向数据库插入一条持仓记录"""
    fields = dict(
        account_id="TEST",
        strategy_id="s1",
        symbol="IM2609",
        exchange="CFFEX",
        multiple=200,
        pos_long_td=2,
        pos_long_yd=1,
        pos_short_td=0,
        pos_short_yd=0,
        hold_price_long=6000.0,
        hold_price_short=0,
        close_profit_long=1500.0,
        close_profit_short=0,
    )
    fields.update(kwargs)
    async with get_async_session() as session:
        session.add(PositionPo(**fields))


async def _query_pos(**filters) -> list[PositionPo]:
    """查询持仓记录并预加载属性"""
    async with get_async_session() as session:
        records = list(
            (await session.execute(select(PositionPo).filter_by(**filters))).scalars().all()
        )
        for r in records:
            _ = (r.symbol, r.pos_long_td, r.hold_price_long)
        return records


@pytest.mark.unit
class TestSavePosition:
    """持仓保存测试"""

    async def test_save_position_creates_record(self, service):
        """测试新建持仓记录的字段往返"""
        assert await service.save_position(_make_position()) is True

        records = await _query_pos(account_id="TEST")
        assert len(records) == 1
        po = records[0]
        assert po.strategy_id == "s1"
        assert po.symbol == "IM2609"
        assert po.exchange == "CFFEX"
        assert po.multiple == 200
        assert po.pos_long_td == 2
        assert po.pos_long_yd == 1
        assert po.pos_short_td == 0
        assert po.pos_short_yd == 0
        assert float(po.hold_price_long) == pytest.approx(6000.0)
        assert float(po.close_profit_long) == pytest.approx(1500.0)

    async def test_save_position_updates_existing(self, service):
        """测试重复保存为更新而非新增"""
        assert await service.save_position(_make_position()) is True
        assert await service.save_position(_make_position(pos_long_td=5, pos_long_yd=0)) is True

        records = await _query_pos(account_id="TEST")
        assert len(records) == 1
        assert records[0].pos_long_td == 5
        assert records[0].pos_long_yd == 0

    async def test_save_position_none_values_as_zero(self, service):
        """测试 None 持仓字段写 0"""
        position = _make_position(
            pos_long_td=None,
            hold_price_long=None,
            close_profit_short=None,
        )
        assert await service.save_position(position) is True

        po = (await _query_pos(account_id="TEST"))[0]
        assert po.pos_long_td == 0
        assert float(po.hold_price_long) == 0.0
        assert float(po.close_profit_short) == 0.0

    async def test_save_position_exception_returns_false(self, service):
        """测试数据库异常时返回 False"""
        with patch(
            "qtrader.trader.dao.position_dao.get_async_session",
            side_effect=RuntimeError("db down"),
        ):
            assert await service.save_position(_make_position()) is False


@pytest.mark.unit
class TestLoadPositions:
    """持仓加载测试"""

    async def test_load_positions_filters_empty(self, service):
        """测试加载时过滤总持仓为0的记录"""
        await _insert_po(symbol="IM2609")
        await _insert_po(
            symbol="IC2609", pos_long_td=0, pos_long_yd=0, pos_short_td=0, pos_short_yd=0
        )
        await _insert_po(symbol="rb2510", pos_short_yd=3, hold_price_short=3500.0)

        positions = await service.load_positions("TEST", "s1")

        assert {p.symbol for p in positions} == {"IM2609", "rb2510"}
        im = next(p for p in positions if p.symbol == "IM2609")
        assert im.exchange == Exchange.CFFEX
        assert im.strategy_id == "s1"
        assert im.pos_long == 3
        assert im.pos_long_td == 2
        assert im.pos_long_yd == 1
        assert im.hold_price_long == pytest.approx(6000.0)
        assert im.close_profit_long == pytest.approx(1500.0)
        assert im.extras["account_id"] == "TEST"
        rb = next(p for p in positions if p.symbol == "rb2510")
        assert rb.pos_short == 3

    async def test_load_positions_empty(self, service):
        """测试无记录时返回空列表"""
        assert await service.load_positions("TEST", "s1") == []

    async def test_load_positions_filters_other_strategy(self, service):
        """测试只加载指定策略的持仓"""
        await _insert_po(symbol="IM2609", strategy_id="s1")
        await _insert_po(symbol="rb2510", strategy_id="s2")

        assert [p.symbol for p in await service.load_positions("TEST", "s1")] == ["IM2609"]

    async def test_load_positions_exception_returns_empty(self, service):
        """测试数据库异常时返回空列表"""
        with patch(
            "qtrader.trader.dao.position_dao.get_async_session",
            side_effect=RuntimeError("db down"),
        ):
            assert await service.load_positions("TEST", "s1") == []


@pytest.mark.unit
class TestLoadPosition:
    """单合约持仓加载测试"""

    async def test_load_position_found(self, service):
        """测试加载指定合约持仓"""
        await _insert_po(symbol="IM2609")

        position = await service.load_position("TEST", "s1", "IM2609")

        assert position is not None
        assert position.symbol == "IM2609"
        assert position.strategy_id == "s1"
        assert position.pos_long == 3
        assert position.extras["account_id"] == "TEST"

    async def test_load_position_not_found(self, service):
        """测试合约不存在时返回 None"""
        assert await service.load_position("TEST", "s1", "IM2609") is None

    async def test_load_position_zero_volume_returns_none(self, service):
        """测试总持仓为0时返回 None"""
        await _insert_po(pos_long_td=0, pos_long_yd=0, pos_short_td=0, pos_short_yd=0)

        assert await service.load_position("TEST", "s1", "IM2609") is None

    async def test_load_position_exception_returns_none(self, service):
        """测试数据库异常时返回 None"""
        with patch(
            "qtrader.trader.dao.position_dao.get_async_session",
            side_effect=RuntimeError("db down"),
        ):
            assert await service.load_position("TEST", "s1", "IM2609") is None


@pytest.mark.unit
class TestClearPositions:
    """持仓清理测试"""

    async def test_clear_position_by_symbol(self, service):
        """测试仅清空指定合约持仓"""
        await _insert_po(symbol="IM2609")
        await _insert_po(symbol="rb2510")

        assert await service.clear_position("TEST", "s1", "IM2609") is True

        assert [r.symbol for r in await _query_pos()] == ["rb2510"]

    async def test_clear_position_all_symbols(self, service):
        """测试清空策略全部持仓（symbol=None）"""
        await _insert_po(symbol="IM2609", strategy_id="s1")
        await _insert_po(symbol="rb2510", strategy_id="s1")
        await _insert_po(symbol="ag2512", strategy_id="s2")

        assert await service.clear_position("TEST", "s1") is True

        assert [r.symbol for r in await _query_pos()] == ["ag2512"]

    async def test_clear_all_positions_keeps_account_level(self, service):
        """测试清空账户策略持仓时保留账户级（无策略ID）持仓"""
        await _insert_po(symbol="IM2609", strategy_id="s1")
        await _insert_po(symbol="rb2510", strategy_id="s2")
        await _insert_po(symbol="ag2512", strategy_id=None)

        assert await service.clear_all_positions("TEST") is True

        assert [r.symbol for r in await _query_pos()] == ["ag2512"]

    async def test_clear_position_exception_returns_false(self, service):
        """测试数据库异常时返回 False"""
        with patch(
            "qtrader.trader.dao.position_dao.get_async_session",
            side_effect=RuntimeError("db down"),
        ):
            assert await service.clear_position("TEST", "s1") is False
            assert await service.clear_all_positions("TEST") is False
