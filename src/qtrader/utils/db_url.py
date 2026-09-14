"""
数据库 URL 构建模块
根据配置构建 SQLAlchemy 数据库连接 URL（PostgreSQL）
"""

from urllib.parse import quote

from qtrader.utils.config_loader import DataBaseConfig


def build_db_url(config: DataBaseConfig) -> str:
    """
    构建同步数据库连接 URL

    Args:
        config: 数据库配置

    Returns:
        SQLAlchemy 数据库 URL
    """
    pg = config.pg
    # 对密码进行URL编码，处理特殊字符如@、#、:等
    encoded_password = quote(pg.password, safe="")
    encoded_user = quote(pg.user, safe="")
    return (
        f"postgresql+psycopg://{encoded_user}:{encoded_password}@{pg.host}:{pg.port}/{pg.database}"
    )


def build_async_db_url(config: DataBaseConfig) -> str:
    """
    构建异步数据库连接 URL

    Args:
        config: 数据库配置

    Returns:
        SQLAlchemy 异步数据库 URL
    """
    pg = config.pg
    # 对密码进行URL编码，处理特殊字符如@、#、:等
    encoded_password = quote(pg.password, safe="")
    encoded_user = quote(pg.user, safe="")
    return (
        f"postgresql+asyncpg://{encoded_user}:{encoded_password}@{pg.host}:{pg.port}/{pg.database}"
    )
