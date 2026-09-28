"""
一次性修复 bars_history.trading_day 批量错标

背景：ManagerDataFeed._sync_all 曾把整批历史K线统一盖上"同步当天"的trading_day戳，
导致同一trading_day组内混入多日bar_time，按交易日回数的查询起点漂移。

修复逻辑：按bar_time逐根重算——白盘bar（3~20点）归当天；夜盘bar归下一交易日
（交易日集合从表内白盘bar的日期自推导，无需连接行情源）。

用法：
    uv run python scripts/repair_bars_trading_day.py [--dry-run]
"""

import argparse
from datetime import date

from sqlalchemy import func, select, text

from qtrader.manager.data_feed import calc_bar_trading_day
from qtrader.models.po import BarHistoryPo
from qtrader.utils.async_database import (
    close_async_database,
    get_async_session,
    init_async_database,
)
from qtrader.utils.config_loader import get_config_loader
from qtrader.utils.db_url import build_async_db_url
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


async def load_trading_dates_from_db() -> list[date]:
    """从表内白盘bar的日期自推导交易日集合（出现白盘bar的日期必为交易日）"""
    async with get_async_session() as session:
        result = await session.execute(
            select(func.distinct(func.date(BarHistoryPo.bar_time))).where(
                func.extract("hour", BarHistoryPo.bar_time).between(3, 19)
            )
        )
        return sorted(date.fromisoformat(str(r[0])) for r in result.all())


async def repair(dry_run: bool) -> None:
    """
    按bar_time重算bars_history.trading_day

    Args:
        dry_run: 只打印将要修正的内容，不落库
    """
    async with get_async_session() as session:
        rows = (
            await session.execute(
                select(BarHistoryPo.bar_time, BarHistoryPo.trading_day).distinct()
            )
        ).all()
    logger.info(f"共 {len(rows)} 个 (bar_time, trading_day) 组合")

    trading_dates = await load_trading_dates_from_db()
    if trading_dates:
        logger.info(
            f"自推导交易日 {len(trading_dates)} 个: {trading_dates[0]} ~ {trading_dates[-1]}"
        )
    else:
        logger.warning("表内无白盘bar，无法推导交易日，夜盘bar将按锚点日近似")

    to_fix = [
        {"bt": bt, "td": calc_bar_trading_day(bt, trading_dates)}
        for bt, td_old in rows
        if td_old != calc_bar_trading_day(bt, trading_dates)
    ]
    logger.info(f"需修正 {len(to_fix)} 个 bar_time")
    if not to_fix:
        logger.info("数据无需修复")
        return

    if dry_run:
        for p in to_fix[:20]:
            logger.info(f"bar_time={p['bt']} -> trading_day={p['td']}")
        logger.info("dry-run 模式，未落库")
        return

    async with get_async_session() as session:
        result = await session.execute(
            text("UPDATE bars_history SET trading_day = :td WHERE bar_time = :bt"),
            to_fix,
        )
        logger.info(f"已更新 {int(getattr(result, 'rowcount', 0) or 0)} 行")


async def main() -> None:
    """脚本入口：按config.yaml连接数据库并执行修复"""
    parser = argparse.ArgumentParser(description="修复bars_history.trading_day批量错标")
    parser.add_argument("--dry-run", action="store_true", help="只打印修正内容，不落库")
    args = parser.parse_args()

    db_config = get_config_loader()._load_app_config().data_base
    if db_config is None:
        raise RuntimeError("config.yaml 未配置数据库(data_base)")
    await init_async_database(build_async_db_url(db_config), account_id="repair")
    try:
        await repair(dry_run=args.dry_run)
    finally:
        await close_async_database()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
