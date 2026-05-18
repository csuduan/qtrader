"""
数据库操作模块
提供数据库连接、会话管理和初始化功能（PostgreSQL）
"""

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from qtrader.models.po import Base
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 全局数据库实例
_db: Optional["Database"] = None


class Database:
    """PostgreSQL 数据库管理类"""

    def __init__(self, db_url: str, echo: bool = False, pool_size: int = 5, max_overflow: int = 10):
        """
        初始化数据库连接

        Args:
            db_url: SQLAlchemy 数据库 URL（postgresql://...）
            echo: 是否输出SQL语句
            pool_size: 连接池大小
            max_overflow: 连接池最大溢出
        """
        self.db_url = db_url
        self.engine = create_engine(
            db_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )

        db_display = db_url.split("@")[-1] if "@" in db_url else db_url
        logger.info(f"数据库连接已创建: {db_display}")

    def create_tables(self) -> None:
        """创建所有数据表"""
        Base.metadata.create_all(bind=self.engine, checkfirst=True)
        logger.info("数据库表创建完成")

    def drop_tables(self) -> None:
        """删除所有数据表（慎用）"""
        Base.metadata.drop_all(bind=self.engine)
        logger.warning("数据库表已删除")

    def drop_and_recreate(self) -> None:
        """删除并重新创建所有数据表（慎用）"""
        self.drop_tables()
        self.create_tables()
        logger.warning("数据库表已重建")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        获取数据库会话的上下文管理器

        Yields:
            Session: SQLAlchemy会话对象
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session_sync(self) -> Session:
        """
        获取数据库会话（同步模式）

        Returns:
            Session: SQLAlchemy会话对象
        """
        return self.SessionLocal()

    def close(self) -> None:
        """关闭数据库连接"""
        self.engine.dispose()
        logger.info("数据库连接已关闭")


def init_database(
    db_url: str,
    account_id: str = "default",
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> Database:
    """
    初始化数据库

    Args:
        db_url: SQLAlchemy 数据库 URL（postgresql://...）
        account_id: 账户ID（用于日志记录）
        echo: 是否输出SQL语句
        pool_size: 连接池大小
        max_overflow: 连接池最大溢出

    Returns:
        Database: 数据库实例
    """
    global _db

    _db = Database(db_url, echo=echo, pool_size=pool_size, max_overflow=max_overflow)
    _db.create_tables()

    logger.info(f"账户 [{account_id}] 数据库初始化完成")
    return _db


def get_database() -> Database | None:
    """
    获取全局数据库实例

    Returns:
        Database: 数据库实例，如果未初始化则返回None
    """
    return _db


def _get_session_sync() -> Session | None:
    """
    【内部使用，不推荐】获取原始数据库会话

    请优先使用 session_scope() context manager 以自动管理事务和连接。

    Returns:
        Session: 数据库会话，如果数据库未初始化则返回None
    """
    db = get_database()
    if db:
        return db.get_session_sync()
    return None


def get_session() -> Session | None:
    """
    【已废弃】获取数据库会话

    请使用 session_scope() context manager 替代，以自动管理 commit/rollback/close。
    保留此函数仅用于兼容旧代码。

    Returns:
        Session: 数据库会话，如果数据库未初始化则返回None
    """
    logger.warning("get_session() 已废弃，请使用 session_scope() context manager")
    return _get_session_sync()


def close_database() -> None:
    """关闭数据库连接"""
    global _db
    if _db:
        _db.close()
        _db = None


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    提供事务范围的上下文管理器

    自动处理 commit / rollback / close，推荐使用。

    Usage:
        with session_scope() as session:
            result = session.query(Model).all()
            # 自动 commit，异常自动 rollback
    """
    db = get_database()
    if db is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    with db.get_session() as session:
        yield session
