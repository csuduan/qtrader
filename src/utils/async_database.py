"""
异步数据库操作模块
提供数据库连接、会话管理和初始化功能（异步版本）
每个Trader进程管理一个独立的数据库
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.po import Base
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 全局异步数据库实例
_async_db: Optional["AsyncDatabase"] = None


class AsyncDatabase:
    """异步数据库管理类"""

    def __init__(self, db_path: str, echo: bool = False):
        """
        初始化异步数据库连接

        Args:
            db_path: 数据库文件路径
            echo: 是否输出SQL语句
        """
        self.db_path = db_path
        self.db_url = f"sqlite+aiosqlite:///{db_path}"
        self.engine = create_async_engine(self.db_url, echo=echo)
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info(f"异步数据库连接已创建: {db_path}")

    async def create_tables(self) -> None:
        """创建所有数据表"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表创建完成")

    async def drop_tables(self) -> None:
        """删除所有数据表（慎用）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("数据库表已删除")

    async def drop_and_recreate(self) -> None:
        """删除并重新创建所有数据表（慎用）"""
        await self.drop_tables()
        await self.create_tables()
        logger.warning("数据库表已重建")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        获取异步数据库会话的上下文管理器

        Yields:
            AsyncSession: SQLAlchemy异步会话对象
        """
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.info("数据库连接已关闭")


async def init_async_database(
    db_path: str, account_id: str = "default", echo: bool = False
) -> AsyncDatabase:
    """
    初始化异步数据库

    Args:
        db_path: 数据库文件路径
        account_id: 账户ID（用于日志记录）
        echo: 是否输出SQL语句

    Returns:
        AsyncDatabase: 异步数据库实例
    """
    global _async_db

    # 确保数据库目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # 创建异步数据库实例
    _async_db = AsyncDatabase(db_path, echo=echo)

    # 创建表（如果不存在）
    await _async_db.create_tables()

    logger.info(f"账户 [{account_id}] 异步数据库初始化完成: {db_path}")
    return _async_db


def get_async_database() -> Optional[AsyncDatabase]:
    """
    获取全局异步数据库实例

    Returns:
        AsyncDatabase: 异步数据库实例，如果未初始化则返回None
    """
    return _async_db


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话的上下文管理器

    Yields:
        AsyncSession: 异步数据库会话，如果数据库未初始化则抛出异常
    """
    db = get_async_database()
    if db is None:
        raise RuntimeError("数据库未初始化，请先调用 init_async_database()")
    async with db.get_session() as session:
        yield session


async def close_async_database() -> None:
    """关闭异步数据库连接"""
    global _async_db
    if _async_db:
        await _async_db.close()
        _async_db = None
        logger.info("异步数据库连接已关闭")
