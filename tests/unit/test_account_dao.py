"""
AccountDao 单元测试

测试账户数据持久化 DAO 的核心功能，包括：
- Pydantic 账户对象写入的字段往返（含 hold_profit -> position_profit 映射）
- dict 批量写入（save_dict）
- 同账户 upsert（更新而非新增）
- None 字段回退为 0
- 异常吞并（save 不向上抛出）
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from qtrader.models.object import AccountData
from qtrader.models.po import AccountPo
from qtrader.trader.dao.account_dao import AccountDao
from qtrader.utils.async_database import (
    close_async_database,
    get_async_session,
    init_async_database,
)


@pytest.fixture
async def dao(tmp_path):
    """初始化测试数据库并返回 DAO 实例"""
    await init_async_database(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield AccountDao()
    await close_async_database()


async def _query_account(account_id: str) -> AccountPo | None:
    """查询指定账户的持久化记录"""
    async with get_async_session() as session:
        po = (
            await session.execute(select(AccountPo).filter_by(account_id=account_id))
        ).scalar_one_or_none()
        # 触发属性加载，避免脱离会话后失效
        _ = (po.balance, po.available, po.margin) if po else None
        return po


async def _count_accounts() -> int:
    """统计账户表记录数"""
    async with get_async_session() as session:
        pos = (await session.execute(select(AccountPo))).scalars().all()
        return len(pos)


@pytest.mark.unit
class TestAccountDaoSave:
    """账户对象写入测试"""

    async def test_save_full_fields_roundtrip(self, dao):
        """测试全字段写入与读回（含 hold_profit -> position_profit 映射）"""
        account = AccountData(
            account_id="TEST",
            balance=1005000.0,
            available=900000.0,
            margin=100000.0,
            float_profit=3000.0,
            hold_profit=4000.0,
            close_profit=1000.0,
            risk_ratio=0.1234,
        )
        await dao.save("TEST", account)

        po = await _query_account("TEST")
        assert po is not None
        assert float(po.balance) == pytest.approx(1005000.0)
        assert float(po.available) == pytest.approx(900000.0)
        assert float(po.margin) == pytest.approx(100000.0)
        assert float(po.float_profit) == pytest.approx(3000.0)
        # position_profit 来源于 AccountData.hold_profit
        assert float(po.position_profit) == pytest.approx(4000.0)
        assert float(po.close_profit) == pytest.approx(1000.0)
        assert float(po.risk_ratio) == pytest.approx(0.1234)
        assert po.updated_at is not None

    async def test_save_upsert_same_account(self, dao):
        """测试同账户重复保存为更新而非新增"""
        await dao.save("TEST", AccountData(account_id="TEST", balance=100.0, available=50.0))
        await dao.save("TEST", AccountData(account_id="TEST", balance=200.0, available=150.0))

        assert await _count_accounts() == 1
        po = await _query_account("TEST")
        assert float(po.balance) == pytest.approx(200.0)
        assert float(po.available) == pytest.approx(150.0)

    async def test_save_none_fields_as_zero(self, dao):
        """测试 None 可选字段写入为 0"""
        account = AccountData(account_id="TEST", balance=100.0, available=50.0)
        assert account.margin is None  # 确认输入确为 None

        await dao.save("TEST", account)

        po = await _query_account("TEST")
        assert float(po.margin) == 0.0
        assert float(po.float_profit) == 0.0
        assert float(po.position_profit) == 0.0
        assert float(po.close_profit) == 0.0
        assert float(po.risk_ratio) == 0.0

    async def test_save_object_without_attributes_defaults_zero(self, dao):
        """测试缺少属性的数据对象其余字段写 0"""
        data = SimpleNamespace(balance=88.5)

        await dao.save("TEST", data)

        po = await _query_account("TEST")
        assert float(po.balance) == pytest.approx(88.5)
        assert float(po.available) == 0.0
        assert float(po.margin) == 0.0
        assert float(po.risk_ratio) == 0.0

    async def test_save_swallows_exception(self):
        """测试数据库异常被捕获记录，不向上抛出"""
        dao = AccountDao()
        with patch(
            "qtrader.trader.dao.account_dao.get_async_session",
            side_effect=RuntimeError("db down"),
        ):
            await dao.save("TEST", SimpleNamespace(balance=1.0))  # 不应抛出


async def _save_dict(dao: AccountDao, account_id: str, data: dict) -> None:
    """在外部会话中调用 save_dict（模拟批量写入场景）"""
    async with get_async_session() as session:
        await dao.save_dict(session, account_id, data)


@pytest.mark.unit
class TestAccountDaoSaveDict:
    """字典批量写入测试"""

    async def test_save_dict_full_fields(self, dao):
        """测试 dict 写入与读回"""
        await _save_dict(
            dao,
            "TEST",
            {
                "balance": 500000.0,
                "available": 400000.0,
                "margin": 50000.0,
                "float_profit": 100.0,
                "hold_profit": 200.0,
                "close_profit": 300.0,
                "risk_ratio": 0.1,
            },
        )

        po = await _query_account("TEST")
        assert po is not None
        assert float(po.balance) == pytest.approx(500000.0)
        assert float(po.available) == pytest.approx(400000.0)
        assert float(po.margin) == pytest.approx(50000.0)
        assert float(po.float_profit) == pytest.approx(100.0)
        assert float(po.position_profit) == pytest.approx(200.0)
        assert float(po.close_profit) == pytest.approx(300.0)
        assert float(po.risk_ratio) == pytest.approx(0.1)

    async def test_save_dict_empty_values_as_zero(self, dao):
        """测试空 dict 全部字段写 0"""
        await _save_dict(dao, "TEST", {})

        po = await _query_account("TEST")
        assert float(po.balance) == 0.0
        assert float(po.available) == 0.0
        assert float(po.risk_ratio) == 0.0

    async def test_save_dict_updates_existing(self, dao):
        """测试 dict 写入已有账户为更新"""
        await _save_dict(dao, "TEST", {"balance": 1.0})
        await _save_dict(dao, "TEST", {"balance": 2.0})

        assert await _count_accounts() == 1
        assert float((await _query_account("TEST")).balance) == pytest.approx(2.0)
