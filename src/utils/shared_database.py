"""
共享数据库模块
提供跨进程共享的数据库访问（PostgreSQL）

主要用途：
- Manager进程写入公共数据（合约信息）
- Trader进程读写业务数据（策略持仓、换仓指令等）
"""

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 全局共享数据库实例
_shared_db: Optional["SharedDatabase"] = None


class SharedDatabase:
    """PostgreSQL 共享数据库管理类"""

    def __init__(self, db_url: str, echo: bool = False,
                 pool_size: int = 5, max_overflow: int = 10):
        """
        初始化共享数据库连接

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
        logger.info(f"共享数据库连接已创建: {db_display}")

    def create_tables(self) -> None:
        """创建所有数据表"""
        from src.models.po import Base  # noqa: F401

        Base.metadata.create_all(bind=self.engine, checkfirst=True)
        logger.info("共享数据库表创建完成")

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

    def close(self) -> None:
        """关闭数据库连接"""
        self.engine.dispose()
        logger.info("共享数据库连接已关闭")


def init_shared_database(db_url: str, echo: bool = False,
                         pool_size: int = 5, max_overflow: int = 10) -> "SharedDatabase":
    """
    初始化共享数据库

    Args:
        db_url: SQLAlchemy 数据库 URL（postgresql://...）
        echo: 是否输出SQL语句
        pool_size: 连接池大小
        max_overflow: 连接池最大溢出

    Returns:
        SharedDatabase: 共享数据库实例
    """
    global _shared_db

    _shared_db = SharedDatabase(db_url, echo=echo, pool_size=pool_size, max_overflow=max_overflow)
    _shared_db.create_tables()

    logger.info("共享数据库初始化完成")
    return _shared_db


def get_shared_database() -> Optional["SharedDatabase"]:
    """
    获取全局共享数据库实例

    Returns:
        SharedDatabase: 共享数据库实例，如果未初始化则返回None
    """
    return _shared_db


def close_shared_database() -> None:
    """关闭共享数据库连接"""
    global _shared_db
    if _shared_db:
        _shared_db.close()
        _shared_db = None
        logger.info("共享数据库连接已关闭")
