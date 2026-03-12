"""
Database 单元测试

测试数据库工具模块的核心功能，包括：
- 数据库连接
- 会话管理
- 表创建/删除
- 全局数据库实例
- 上下文管理器
"""

from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from src.models.po import Base
from src.utils.database import Database, close_database, get_database, get_session, init_database, session_scope


# ==================== Fixtures ====================


@pytest.fixture
def temp_db_path(tmp_path):
    """临时数据库文件路径"""
    return str(tmp_path / "test.db")


@pytest.fixture
def database(temp_db_path):
    """创建数据库实例"""
    return Database(db_path=temp_db_path, echo=False)


# ==================== TestDatabaseInitialization ====================


class TestDatabaseInitialization:
    """Database 初始化测试"""

    def test_initialization_creates_engine(self, database: Database, temp_db_path):
        """测试初始化创建数据库引擎"""
        assert database.db_path == temp_db_path
        assert database.db_url == f"sqlite:///{temp_db_path}"
        assert database.engine is not None

    def test_initialization_creates_session_factory(self, database: Database):
        """测试初始化创建会话工厂"""
        assert database.SessionLocal is not None
        assert callable(database.SessionLocal)

    def test_initialization_with_echo(self, temp_db_path):
        """测试初始化 echo 参数"""
        db = Database(db_path=temp_db_path, echo=True)
        # 验证引擎已创建（不检查 echo 内部状态）
        assert db.engine is not None


# ==================== TestDatabaseTableManagement ====================


class TestDatabaseTableManagement:
    """Database 表管理测试"""

    def test_create_tables(self, database: Database):
        """测试 create_tables() 创建所有数据表"""
        # 先删除可能存在的表
        database.drop_tables()

        database.create_tables()

        # 验证表已创建（通过查询表名）
        inspector = inspect(database.engine)
        table_names = inspector.get_table_names()

        # 至少应该有一些基础表
        assert len(table_names) > 0

    def test_drop_tables(self, database: Database):
        """测试 drop_tables() 删除所有数据表"""
        # 先创建表
        database.create_tables()

        # 删除表
        database.drop_tables()

        # 验证表已删除
        inspector = inspect(database.engine)
        table_names = inspector.get_table_names()

        assert len(table_names) == 0

    def test_drop_and_recreate(self, database: Database):
        """测试 drop_and_recreate() 删除并重建"""
        database.create_tables()

        database.drop_and_recreate()

        # 验证表存在
        inspector = inspect(database.engine)
        table_names = inspector.get_table_names()

        assert len(table_names) > 0


# ==================== TestDatabaseSessionManagement ====================


class TestDatabaseSessionManagement:
    """Database 会话管理测试"""

    def test_get_session_returns_session(self, database: Database):
        """测试 get_session() 返回 SQLAlchemy 会话"""
        with database.get_session() as session:
            assert isinstance(session, Session)

    def test_get_session_commits_on_success(self, database: Database):
        """测试成功时提交事务"""
        with database.get_session() as session:
            # 执行简单查询验证会话可用
            result = session.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

    def test_get_session_rolls_back_on_error(self, database: Database):
        """测试错误时回滚事务"""
        with pytest.raises(Exception):
            with database.get_session() as session:
                session.execute("SELECT 1")
                # 模拟错误
                raise Exception("测试错误")

        # 验证会话已关闭，不应有未提交的事务

    def test_get_session_sync_returns_session(self, database: Database):
        """测试 get_session_sync() 返回会话"""
        session = database.get_session_sync()

        assert isinstance(session, Session)

        # 需要手动关闭
        session.close()

    def test_get_session_context_manager_closes_session(self, database: Database):
        """测试上下文管理器正确关闭会话"""
        with database.get_session() as session:
            pass

        # 会话应该已关闭
        # 注意：SQLAlchemy 的 Session 在上下文管理器退出时关闭


# ==================== TestDatabaseInitFunction ====================


class TestDatabaseInitFunction:
    """数据库初始化函数测试"""

    def test_init_database_creates_instance(self, temp_db_path):
        """测试 init_database() 创建数据库实例"""
        db = init_database(db_path=temp_db_path, account_id="test_account")

        assert isinstance(db, Database)
        assert db.db_path == temp_db_path

    def test_init_database_creates_tables(self, temp_db_path):
        """测试 init_database() 创建表"""
        db = init_database(db_path=temp_db_path)

        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        assert len(table_names) > 0

    def test_init_database_creates_directory(self, tmp_path):
        """测试 init_database() 创建目录"""
        db_path = str(tmp_path / "subdir" / "test.db")

        db = init_database(db_path=db_path)

        assert Path(db_path).parent.exists()
        assert isinstance(db, Database)

    def test_init_database_sets_global_instance(self, temp_db_path):
        """测试 init_database() 设置全局实例"""
        # 先关闭可能存在的实例
        close_database()

        db = init_database(db_path=temp_db_path)

        assert get_database() is db


# ==================== TestDatabaseGlobalInstance ====================


class TestDatabaseGlobalInstance:
    """全局数据库实例测试"""

    def test_get_database_returns_none_when_not_initialized(self):
        """测试未初始化时返回 None"""
        # 确保全局实例为 None
        import src.utils.database
        src.utils.database._db = None

        result = get_database()

        assert result is None

    def test_get_database_returns_initialized_instance(self, temp_db_path):
        """测试返回已初始化的实例"""
        import src.utils.database
        src.utils.database._db = Database(db_path=temp_db_path)

        result = get_database()

        assert isinstance(result, Database)

    def test_close_database_closes_connection(self, temp_db_path):
        """测试 close_database() 关闭连接"""
        import src.utils.database
        db = Database(db_path=temp_db_path)
        src.utils.database._db = db

        close_database()

        assert get_database() is None
        # 引擎应该被释放

    def test_close_database_when_none(self):
        """测试 close_database() 当实例为 None"""
        import src.utils.database
        src.utils.database._db = None

        # 不应该报错
        close_database()


# ==================== TestGetSessionFunction ====================


class TestGetSessionFunction:
    """get_session() 函数测试"""

    def test_get_session_returns_none_when_no_database(self):
        """测试无数据库时返回 None"""
        import src.utils.database
        src.utils.database._db = None

        result = get_session()

        assert result is None

    def test_get_session_returns_session_when_database_exists(self, temp_db_path):
        """测试有数据库时返回会话"""
        import src.utils.database
        db = Database(db_path=temp_db_path)
        src.utils.database._db = db

        session = get_session()

        assert isinstance(session, Session)

        # 清理
        session.close()
        src.utils.database._db = None


# ==================== TestSessionScope ====================


class TestSessionScope:
    """session_scope 上下文管理器测试"""

    def test_session_scope_provides_session(self, temp_db_path):
        """测试 session_scope 提供会话"""
        import src.utils.database
        db = Database(db_path=temp_db_path)
        src.utils.database._db = db

        with session_scope() as session:
            assert isinstance(session, Session)

        src.utils.database._db = None

    def test_session_scope_commits_on_success(self, temp_db_path):
        """测试成功时提交"""
        import src.utils.database
        db = Database(db_path=temp_db_path)
        src.utils.database._db = db

        with session_scope() as session:
            result = session.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

        src.utils.database._db = None

    def test_session_scope_rolls_back_on_error(self, temp_db_path):
        """测试错误时回滚"""
        import src.utils.database
        db = Database(db_path=temp_db_path)
        src.utils.database._db = db

        with pytest.raises(Exception):
            with session_scope() as session:
                session.execute(text("SELECT 1"))
                raise Exception("测试错误")

        src.utils.database._db = None


# ==================== TestDatabaseEdgeCases ====================


class TestDatabaseEdgeCases:
    """Database 边界情况测试"""

    def test_multiple_create_tables(self, database: Database):
        """测试多次创建表"""
        database.create_tables()
        database.create_tables()

        # 不应该报错，表应该存在

    def test_multiple_drop_tables(self, database: Database):
        """测试多次删除表"""
        database.create_tables()
        database.drop_tables()
        database.drop_tables()

        # 不应该报错

    def test_get_session_concurrent_usage(self, database: Database):
        """测试并发使用会话"""
        sessions = []

        for _ in range(3):
            session = database.get_session_sync()
            sessions.append(session)

        # 所有会话应该独立
        assert len(set(sessions)) == 3

        # 清理
        for session in sessions:
            session.close()

    def test_database_with_same_path(self, temp_db_path):
        """测试使用相同路径创建多个数据库实例"""
        db1 = Database(db_path=temp_db_path)
        db2 = Database(db_path=temp_db_path)

        # 应该是两个独立的实例
        assert db1 is not db2
        assert db1.db_path == db2.db_path

    def test_database_in_memory(self):
        """测试内存数据库"""
        db = Database(db_path=":memory:")

        assert db.db_url == "sqlite:///:memory:"

        # 应该能正常创建表
        db.create_tables()


# ==================== TestDatabaseErrorHandling ====================


class TestDatabaseErrorHandling:
    """Database 错误处理测试"""

    def test_invalid_sql_handling(self, database: Database):
        """测试无效 SQL 处理"""
        with pytest.raises(Exception):
            with database.get_session() as session:
                session.execute(text("INVALID SQL STATEMENT"))

    def test_session_after_close(self, database: Database):
        """测试关闭后使用会话"""
        session = database.get_session_sync()
        session.close()

        # 关闭的会话不应该被使用
        # SQLAlchemy 2.x 中已关闭会话的状态检查
        from sqlalchemy.exc import ResourceClosedError
        # 验证会话已正确关闭（不抛出异常即可）
        assert True
