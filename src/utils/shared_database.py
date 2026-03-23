"""
共享数据库模块
提供跨进程共享的SQLite数据库访问，使用WAL模式支持并发读写

主要用途：
- Manager进程写入公共数据（合约信息）
- Trader进程读取公共数据（合约信息）

WAL模式特点：
- 支持多读者并发，不阻塞
- 写操作原子性
- 崩溃安全
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 全局共享数据库实例
_shared_db: Optional["SharedDatabase"] = None


class SharedDatabase:
    """
    共享数据库管理类

    使用SQLite WAL模式，支持多进程并发读写。
    Manager进程负责写入，Trader进程负责读取。
    """

    def __init__(self, db_path: str, echo: bool = False):
        """
        初始化共享数据库连接

        Args:
            db_path: 数据库文件路径
            echo: 是否输出SQL语句
        """
        self.db_path = db_path
        self.db_url = f"sqlite:///{db_path}"

        # connect_args 针对SQLite并发场景
        self.engine = create_engine(
            self.db_url,
            echo=echo,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,  # 等待锁超时时间（秒）
            },
        )

        # 启用WAL模式，提升并发性能
        @event.listens_for(self.engine, "connect")
        def set_wal_mode(dbapi_connection, connection_record):  # type: ignore[misc]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")  # 性能与安全的平衡
            cursor.execute("PRAGMA wal_autocheckpoint=1000")
            cursor.close()

        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )
        logger.info(f"共享数据库连接已创建 (WAL模式): {db_path}")

    def create_tables(self) -> None:
        """创建共享数据表（仅创建公共数据相关的表）"""
        from src.models.po import Base, ContractPo  # noqa: F401

        # 只创建合约表
        ContractPo.__table__.create(bind=self.engine, checkfirst=True)
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

    def checkpoint(self) -> None:
        """手动触发WAL checkpoint，将WAL文件内容合并到主数据库"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            logger.debug("WAL checkpoint 完成")
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败: {e}")


def init_shared_database(db_path: str, echo: bool = False) -> "SharedDatabase":
    """
    初始化共享数据库

    Args:
        db_path: 数据库文件路径
        echo: 是否输出SQL语句

    Returns:
        SharedDatabase: 共享数据库实例
    """
    global _shared_db

    # 确保数据库目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _shared_db = SharedDatabase(db_path, echo=echo)
    _shared_db.create_tables()

    logger.info(f"共享数据库初始化完成: {db_path}")
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
