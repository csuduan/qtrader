"""
异步数据库模块（async_database）单元测试

以 mock 引擎验证 AsyncDatabase 的会话生命周期语义（commit/rollback）、
建表/删表语句分发、连接释放，以及全局实例管理与会话上下文，
不依赖真实 PostgreSQL/asyncpg。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.utils import async_database as db_mod
from qtrader.utils.async_database import (
    AsyncDatabase,
    close_async_database,
    get_async_database,
    get_async_session,
    init_async_database,
)

PG_URL = "postgresql+asyncpg://qtrader:pass@localhost:5432/qtrader"


def _make_mock_engine():
    """构造支持 begin() 异步上下文与 dispose() 的 mock 引擎"""
    conn = MagicMock()
    conn.run_sync = AsyncMock()

    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=conn)
    begin_cm.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.begin = MagicMock(return_value=begin_cm)
    engine.dispose = AsyncMock()
    return engine, conn


@pytest.fixture
def mock_async_engine():
    """mock create_async_engine/async_sessionmaker/Base，返回 (引擎, 连接, 会话, Base, maker)"""
    with (
        patch("qtrader.utils.async_database.create_async_engine") as mock_create,
        patch("qtrader.utils.async_database.async_sessionmaker") as mock_maker,
        patch("qtrader.utils.async_database.Base") as mock_base,
    ):
        engine, conn = _make_mock_engine()
        mock_create.return_value = engine

        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        mock_maker.return_value = MagicMock(return_value=session)

        yield SimpleNamespace(
            create=mock_create,
            maker=mock_maker,
            base=mock_base,
            engine=engine,
            conn=conn,
            session=session,
        )


@pytest.fixture(autouse=True)
def reset_global_async_db():
    """每个用例后清理全局异步数据库实例"""
    yield
    db_mod._async_dbs.clear()


@pytest.mark.unit
class TestAsyncDatabaseInit:
    """初始化与引擎参数"""

    def test_init_creates_engine(self, mock_async_engine):
        db = AsyncDatabase(PG_URL)
        mock_async_engine.create.assert_called_once_with(
            PG_URL,
            echo=False,
            pool_size=5,
            max_overflow=10,
            connect_args={"server_settings": {"statement_timeout": "30000"}},
        )
        assert db.db_url == PG_URL
        assert db.engine is mock_async_engine.engine

    def test_init_passes_echo_and_pool_args(self, mock_async_engine):
        AsyncDatabase(PG_URL, echo=True, pool_size=10, max_overflow=20)
        assert mock_async_engine.create.call_args.kwargs["echo"] is True
        assert mock_async_engine.create.call_args.kwargs["pool_size"] == 10
        assert mock_async_engine.create.call_args.kwargs["max_overflow"] == 20

    def test_init_creates_session_factory(self, mock_async_engine):
        db = AsyncDatabase(PG_URL)

        mock_async_engine.maker.assert_called_once()
        assert mock_async_engine.maker.call_args.args[0] is db.engine
        assert mock_async_engine.maker.call_args.kwargs["expire_on_commit"] is False


@pytest.mark.unit
class TestAsyncDatabaseSession:
    """会话生命周期语义"""

    @pytest.mark.asyncio
    async def test_get_session_commits_on_success(self, mock_async_engine):
        session = mock_async_engine.session
        db = AsyncDatabase(PG_URL)
        async with db.get_session() as s:
            assert s is session
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_rolls_back_on_error(self, mock_async_engine):
        session = mock_async_engine.session
        db = AsyncDatabase(PG_URL)
        with pytest.raises(ValueError):
            async with db.get_session():
                raise ValueError("boom")
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()


@pytest.mark.unit
class TestAsyncDatabaseTables:
    """建表/删表语句分发"""

    @pytest.mark.asyncio
    async def test_create_tables(self, mock_async_engine):
        conn, base = mock_async_engine.conn, mock_async_engine.base
        db = AsyncDatabase(PG_URL)
        await db.create_tables()
        conn.run_sync.assert_awaited_once_with(base.metadata.create_all, checkfirst=True)

    @pytest.mark.asyncio
    async def test_drop_tables(self, mock_async_engine):
        conn, base = mock_async_engine.conn, mock_async_engine.base
        db = AsyncDatabase(PG_URL)
        await db.drop_tables()
        conn.run_sync.assert_awaited_once_with(base.metadata.drop_all)

    @pytest.mark.asyncio
    async def test_drop_and_recreate(self, mock_async_engine):
        conn, base = mock_async_engine.conn, mock_async_engine.base
        db = AsyncDatabase(PG_URL)
        await db.drop_and_recreate()
        assert conn.run_sync.await_count == 2
        assert conn.run_sync.await_args_list[0].args[0] is base.metadata.drop_all
        assert conn.run_sync.await_args_list[1].args[0] is base.metadata.create_all

    @pytest.mark.asyncio
    async def test_close_disposes_engine(self, mock_async_engine):
        engine = mock_async_engine.engine
        db = AsyncDatabase(PG_URL)
        await db.close()
        engine.dispose.assert_awaited_once()


@pytest.mark.unit
class TestGlobalAsyncDatabase:
    """全局实例管理与会话上下文"""

    def test_get_async_database_default_none(self):
        assert get_async_database() is None

    @pytest.mark.asyncio
    async def test_init_async_database_creates_global_instance(self, mock_async_engine):
        conn, base = mock_async_engine.conn, mock_async_engine.base
        db = await init_async_database(PG_URL, account_id="TEST")

        assert db is db_mod._async_dbs[db_mod.DEFAULT_DB_NAME]
        assert db is not None
        # 建表被调用
        conn.run_sync.assert_awaited_once_with(base.metadata.create_all, checkfirst=True)

    @pytest.mark.asyncio
    async def test_close_async_database_disposes_and_clears(self, mock_async_engine):
        engine = mock_async_engine.engine
        await init_async_database(PG_URL)
        await close_async_database()

        assert get_async_database() is None
        engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_async_database_without_init_is_noop(self):
        await close_async_database()  # 不应抛出
        assert get_async_database() is None

    @pytest.mark.asyncio
    async def test_get_async_session_requires_init(self):
        with pytest.raises(RuntimeError, match="数据库未初始化"):
            async with get_async_session():
                pass

    @pytest.mark.asyncio
    async def test_get_async_session_yields_session(self, mock_async_engine):
        session = mock_async_engine.session
        await init_async_database(PG_URL)
        async with get_async_session() as s:
            assert s is session
        session.commit.assert_awaited_once()
        await close_async_database()
