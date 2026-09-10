"""
异步数据库操作模块（PostgreSQL）
提供数据库连接、会话管理和初始化功能（异步版本，asyncpg）

Manager 与 Trader 共用同一套 AsyncDatabase 实例访问同一个 PostgreSQL 库。
支持命名实例：不同事件循环（如 ManagerDataFeed 独立线程）必须使用独立实例，
因为 asyncpg 连接池绑定为创建它的事件循环，跨循环共享会报错。
"""

from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from qtrader.models.po import Base
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 全局异步数据库实例（按名称区分，默认实例名 "default"）
_async_dbs: dict[str, "AsyncDatabase"] = {}

DEFAULT_DB_NAME = "default"


class AsyncDatabase:
    """PostgreSQL 异步数据库管理类"""

    def __init__(
        self,
        db_url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        statement_timeout: int = 30,
    ):
        """
        初始化异步数据库连接

        Args:
            db_url: SQLAlchemy 异步数据库 URL（postgresql+asyncpg://...）
            echo: 是否输出SQL语句
            pool_size: 连接池大小
            max_overflow: 连接池最大溢出
            statement_timeout: SQL 语句超时（秒），防慢查询拖垮协程
        """
        self.db_url = db_url
        # statement_timeout 为 PG 专用参数，非 PG 后端（如测试用 SQLite）不传
        connect_args = (
            {"server_settings": {"statement_timeout": str(statement_timeout * 1000)}}
            if db_url.startswith("postgresql")
            else {}
        )
        self.engine = create_async_engine(
            db_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            connect_args=connect_args,
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        db_display = db_url.split("@")[-1] if "@" in db_url else db_url
        logger.info(f"异步数据库连接已创建: {db_display}")

    async def create_tables(self) -> None:
        """创建所有数据表"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
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
    async def get_session(self):
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
        logger.info("异步数据库连接已关闭")


async def init_async_database(
    db_url: str,
    account_id: str = "default",
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    statement_timeout: int = 30,
    name: str = DEFAULT_DB_NAME,
) -> AsyncDatabase:
    """
    初始化异步数据库（注册到全局命名实例表）

    Args:
        db_url: SQLAlchemy 异步数据库 URL（postgresql+asyncpg://...）
        account_id: 账户ID（用于日志记录）
        echo: 是否输出SQL语句
        pool_size: 连接池大小
        max_overflow: 连接池最大溢出
        statement_timeout: SQL 语句超时（秒）
        name: 实例名称（不同事件循环使用不同实例）

    Returns:
        AsyncDatabase: 异步数据库实例
    """
    if name in _async_dbs:
        await _async_dbs[name].close()

    _async_dbs[name] = AsyncDatabase(
        db_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        statement_timeout=statement_timeout,
    )
    await _async_dbs[name].create_tables()

    logger.info(f"账户 [{account_id}] 异步数据库初始化完成 (name={name})")
    return _async_dbs[name]


def get_async_database(name: str = DEFAULT_DB_NAME) -> AsyncDatabase | None:
    """
    获取全局异步数据库实例

    Args:
        name: 实例名称

    Returns:
        AsyncDatabase: 异步数据库实例，如果未初始化则返回None
    """
    return _async_dbs.get(name)


@asynccontextmanager
async def get_async_session(name: str = DEFAULT_DB_NAME):
    """
    获取异步数据库会话的上下文管理器

    Args:
        name: 实例名称

    Yields:
        AsyncSession: SQLAlchemy异步会话对象
    """
    db = get_async_database(name)
    if db is None:
        raise RuntimeError(f"数据库未初始化，请先调用 init_async_database(name={name})")
    async with db.get_session() as session:
        yield session


async def close_async_database(name: str = DEFAULT_DB_NAME) -> None:
    """关闭异步数据库连接"""
    if name in _async_dbs:
        await _async_dbs[name].close()
        del _async_dbs[name]
        logger.info(f"异步数据库连接已关闭 (name={name})")


async def close_all_async_databases() -> None:
    """关闭所有异步数据库连接（进程退出时使用）"""
    for name in list(_async_dbs.keys()):
        await close_async_database(name)


async def fetch_one(session: AsyncSession, stmt):
    """执行查询并返回单条结果（无则None）"""
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def fetch_all(session: AsyncSession, stmt) -> list:
    """执行查询并返回全部结果列表"""
    result = await session.execute(stmt)
    return list(result.scalars().all())
