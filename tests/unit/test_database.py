"""
数据库模块单元测试

以 mock 引擎验证 Database 的会话生命周期语义（commit/rollback/close）、
init_database 全局注册与 session_scope 的错误路径，不依赖真实 PostgreSQL。
"""

from unittest.mock import MagicMock, patch

import pytest

from qtrader.utils import database as db_mod
from qtrader.utils.database import Database, close_database, init_database, session_scope

PG_URL = "postgresql://qtrader:pass@localhost:5432/qtrader"


@pytest.fixture
def mock_engine():
    """mock create_engine/sessionmaker，返回 session 工厂"""
    with (
        patch("qtrader.utils.database.create_engine") as mock_create,
        patch("qtrader.utils.database.sessionmaker") as mock_maker,
        patch("qtrader.utils.database.Base") as mock_base,
    ):
        session = MagicMock()
        mock_create.return_value = MagicMock()
        mock_maker.return_value = MagicMock(return_value=session)
        yield mock_create, mock_maker, session, mock_base


@pytest.fixture(autouse=True)
def reset_global_db():
    """每个用例后清理全局数据库实例"""
    yield
    db_mod._db = None


@pytest.mark.unit
class TestDatabaseInit:
    """初始化与引擎参数"""

    def test_init_creates_engine(self, mock_engine):
        mock_create, _, _, _ = mock_engine
        db = Database(PG_URL)
        mock_create.assert_called_once_with(
            PG_URL, echo=False, pool_size=5, max_overflow=10, pool_pre_ping=True
        )
        assert db.db_url == PG_URL

    def test_init_passes_echo_and_pool_args(self, mock_engine):
        mock_create, _, _, _ = mock_engine
        Database(PG_URL, echo=True, pool_size=10, max_overflow=20)
        assert mock_create.call_args.kwargs["echo"] is True
        assert mock_create.call_args.kwargs["pool_size"] == 10
        assert mock_create.call_args.kwargs["max_overflow"] == 20


@pytest.mark.unit
class TestDatabaseSession:
    """会话生命周期语义"""

    def test_get_session_commits_on_success(self, mock_engine):
        _, _, session, _ = mock_engine
        db = Database(PG_URL)
        with db.get_session():
            pass
        session.commit.assert_called_once()
        session.rollback.assert_not_called()
        session.close.assert_called_once()

    def test_get_session_rolls_back_on_error(self, mock_engine):
        _, _, session, _ = mock_engine
        db = Database(PG_URL)
        with pytest.raises(ValueError):
            with db.get_session():
                raise ValueError("boom")
        session.rollback.assert_called_once()
        session.commit.assert_not_called()
        session.close.assert_called_once()

    def test_create_tables(self, mock_engine):
        mock_create, _, _, mock_base = mock_engine
        db = Database(PG_URL)
        db.create_tables()
        engine = mock_create.return_value
        mock_base.metadata.create_all.assert_called_with(bind=engine, checkfirst=True)

    def test_drop_tables(self, mock_engine):
        mock_create, _, _, mock_base = mock_engine
        db = Database(PG_URL)
        db.drop_tables()
        engine = mock_create.return_value
        mock_base.metadata.drop_all.assert_called_with(bind=engine)

    def test_close_disposes_engine(self, mock_engine):
        mock_create, _, _, _ = mock_engine
        db = Database(PG_URL)
        db.close()
        mock_create.return_value.dispose.assert_called_once()


@pytest.mark.unit
class TestInitDatabase:
    """全局实例管理"""

    def test_init_database_creates_global_instance(self, mock_engine):
        db = init_database(PG_URL, account_id="TEST")
        assert db is db_mod._db
        assert db is not None
        # 建表被调用
        engine = mock_engine[0].return_value
        mock_engine[3].metadata.create_all.assert_called_with(bind=engine, checkfirst=True)

    def test_close_database_clears_global(self, mock_engine):
        init_database(PG_URL)
        close_database()
        assert db_mod._db is None

    def test_session_scope_requires_init(self):
        with pytest.raises(RuntimeError, match="数据库未初始化"):
            with session_scope():
                pass

    def test_session_scope_yields_session(self, mock_engine):
        _, _, session, _ = mock_engine
        init_database(PG_URL)
        with session_scope() as s:
            assert s is session
        session.commit.assert_called_once()
        close_database()
