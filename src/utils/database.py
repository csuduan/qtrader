"""
数据库操作模块（同步版本，向后兼容）
提供数据库连接、会话管理和初始化功能
每个Trader进程管理一个独立的数据库

注意：新项目应使用 src.utils.async_database 中的异步版本
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models.po import Base
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 全局数据库实例
_db: Optional["Database"] = None


class Database:
    """数据库管理类"""

    def __init__(self, db_path: str, echo: bool = False):
        """
        初始化数据库连接

        Args:
            db_path: 数据库文件路径
            echo: 是否输出SQL语句
        """
        self.db_path = db_path
        self.db_url = f"sqlite:///{db_path}"
        self.engine = create_engine(self.db_url, echo=echo)
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )
        logger.info(f"数据库连接已创建: {db_path}")

    def create_tables(self) -> None:
        """创建所有数据表"""
        Base.metadata.create_all(bind=self.engine)
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


def init_database(db_path: str, account_id: str = "default", echo: bool = False) -> Database:
    """
    初始化数据库

    Args:
        db_path: 数据库文件路径
        account_id: 账户ID（用于日志记录）
        echo: 是否输出SQL语句

    Returns:
        Database: 数据库实例
    """
    global _db

    # 确保数据库目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # 创建数据库实例
    _db = Database(db_path, echo=echo)

    # 创建表（如果不存在）
    _db.create_tables()

    logger.info(f"账户 [{account_id}] 数据库初始化完成: {db_path}")
    return _db


def get_database() -> Optional[Database]:
    """
    获取全局数据库实例

    Returns:
        Database: 数据库实例，如果未初始化则返回None
    """
    return _db


def get_session() -> Optional[Session]:
    """
    获取数据库会话

    Returns:
        Session: 数据库会话，如果数据库未初始化则返回None
    """
    db = get_database()
    if db:
        return db.get_session_sync()
    return None


def close_database() -> None:
    """关闭数据库连接"""
    global _db
    if _db:
        _db.close()
        _db = None


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """提供事务范围的上下文管理器"""
    session = get_session()
    if session is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
