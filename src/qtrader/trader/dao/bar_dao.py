"""
K线数据DAO
历史K线表（bars_history）与当日K线表（bars_today）均由 Manager 数据服务
（ManagerDataFeed，data-only TqApi）统一写入；Trader 只读，用于策略加载历史bar。
"""

from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from qtrader.models.object import BarData
from qtrader.models.po import BarHistoryPo, BarTodayPo
from qtrader.utils.async_database import DEFAULT_DB_NAME, fetch_all, get_async_session
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


def _to_naive(dt: datetime) -> datetime:
    """
    时区感知时间转为本地无时区时间（与落库口径一致：naive本地时间）

    Args:
        dt: 任意datetime

    Returns:
        无时区datetime（aware输入转本地时间后剥离tzinfo，naive原样返回）
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


class BarDao:
    """K线数据访问对象"""

    def __init__(self, db_name: str = DEFAULT_DB_NAME):
        """
        初始化

        Args:
            db_name: 异步数据库实例名（ManagerDataFeed 独立事件循环须传专用实例名）
        """
        self._db_name = db_name

    async def upsert_history_bars(self, bars: list[dict], source: str) -> int:
        """
        批量写入历史K线（官方数据覆盖旧值）

        Args:
            bars: bar字典列表，字段: symbol/interval/bar_time/trading_day/open/high/low/close/
                volume/turnover/open_interest
            source: 数据来源标识（如rq）

        Returns:
            写入条数
        """
        if not bars:
            return 0
        async with get_async_session(self._db_name) as session:
            rows = [
                {
                    "symbol": b["symbol"],
                    "interval": b["interval"],
                    "bar_time": b["bar_time"],
                    "trading_day": b["trading_day"],
                    "open_price": b["open"],
                    "high_price": b["high"],
                    "low_price": b["low"],
                    "close_price": b["close"],
                    "volume": b.get("volume") or 0,
                    "turnover": b.get("turnover") or 0,
                    "open_interest": b.get("open_interest") or 0,
                    "source": source,
                }
                for b in bars
            ]
            stmt = pg_insert(BarHistoryPo).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_bars_history_symbol_interval_time",
                set_={
                    "open_price": stmt.excluded.open_price,
                    "high_price": stmt.excluded.high_price,
                    "low_price": stmt.excluded.low_price,
                    "close_price": stmt.excluded.close_price,
                    "volume": stmt.excluded.volume,
                    "turnover": stmt.excluded.turnover,
                    "open_interest": stmt.excluded.open_interest,
                    "trading_day": stmt.excluded.trading_day,
                    "source": stmt.excluded.source,
                },
            )
            await session.execute(stmt)
        return len(rows)

    async def query_history_bars(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[BarHistoryPo]:
        """
        查询历史K线

        Args:
            symbol: 合约代码
            interval: K线周期
            start: 起始时间（含）
            end: 结束时间（含）

        Returns:
            按时间升序的BarHistoryPo列表
        """
        start, end = _to_naive(start), _to_naive(end)
        async with get_async_session(self._db_name) as session:
            pos = await fetch_all(
                session,
                select(BarHistoryPo)
                .filter(
                    BarHistoryPo.symbol == symbol,
                    BarHistoryPo.interval == interval,
                    BarHistoryPo.bar_time >= start,
                    BarHistoryPo.bar_time <= end,
                )
                .order_by(BarHistoryPo.bar_time),
            )
            session.expunge_all()
            return pos

    async def upsert_today_bars(
        self, account_id: str, bars: list[BarData], trading_day: date
    ) -> int:
        """
        批量写入当日K线（同一账户重复写入不覆盖，先写先得）

        Args:
            account_id: 写入账户ID
            bars: BarData列表
            trading_day: 交易日

        Returns:
            写入条数
        """
        if not bars:
            return 0
        async with get_async_session(self._db_name) as session:
            rows = [
                {
                    "symbol": b.symbol,
                    "interval": b.interval,
                    "bar_time": b.datetime,
                    "trading_day": trading_day,
                    "account_id": account_id,
                    "open_price": b.open_price,
                    "high_price": b.high_price,
                    "low_price": b.low_price,
                    "close_price": b.close_price,
                    "volume": b.volume or 0,
                    "turnover": b.turnover or 0,
                    "open_interest": b.open_interest or 0,
                }
                for b in bars
            ]
            stmt = pg_insert(BarTodayPo).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_bars_today_symbol_interval_time_account"
            )
            result = await session.execute(stmt)
            return int(getattr(result, "rowcount", 0) or 0)

    async def query_today_bars(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[BarTodayPo]:
        """
        查询当日K线（多账户重复时每根bar只取一条，按账户ID排序取第一个）

        Args:
            symbol: 合约代码
            interval: K线周期
            start: 起始时间（含）
            end: 结束时间（含）

        Returns:
            按时间升序、时间去重的BarTodayPo列表
        """
        start, end = _to_naive(start), _to_naive(end)
        async with get_async_session(self._db_name) as session:
            pos = await fetch_all(
                session,
                select(BarTodayPo)
                .filter(
                    BarTodayPo.symbol == symbol,
                    BarTodayPo.interval == interval,
                    BarTodayPo.bar_time >= start,
                    BarTodayPo.bar_time <= end,
                )
                .order_by(BarTodayPo.bar_time, BarTodayPo.account_id),
            )
            session.expunge_all()

        # 同一根bar多账户写入时只取一条（相邻bar_time相同跳过）
        result: list[BarTodayPo] = []
        for po in pos:
            if not result or result[-1].bar_time != po.bar_time:
                result.append(po)
        return result

    async def query_bars(
        self, symbol: str, interval: str, start: datetime, end: datetime, limit: int = 500
    ) -> list[dict]:
        """
        合并查询K线（bars_history + bars_today，按时间去重，当日表优先）

        Args:
            symbol: 合约代码
            interval: K线周期
            start: 起始时间（含）
            end: 结束时间（含）
            limit: 最大返回条数（超出时保留最新）

        Returns:
            按时间升序的bar字典列表
        """
        bars: dict[datetime, dict] = {}
        for hpo in await self.query_history_bars(symbol, interval, start, end):
            bar_time = hpo.bar_time
            if not isinstance(bar_time, datetime):
                continue
            bars[bar_time] = {
                "datetime": bar_time.isoformat(),
                "open": float(hpo.open_price),
                "high": float(hpo.high_price),
                "low": float(hpo.low_price),
                "close": float(hpo.close_price),
                "volume": float(hpo.volume or 0),
                "source": hpo.source or "history",
            }
        # 当日表覆盖同时间点的历史数据（实时数据最新）
        for tpo in await self.query_today_bars(symbol, interval, start, end):
            bar_time = tpo.bar_time
            if not isinstance(bar_time, datetime):
                continue
            bars[bar_time] = {
                "datetime": bar_time.isoformat(),
                "open": float(tpo.open_price),
                "high": float(tpo.high_price),
                "low": float(tpo.low_price),
                "close": float(tpo.close_price),
                "volume": float(tpo.volume or 0),
                "source": tpo.account_id,
            }

        result = [bars[t] for t in sorted(bars.keys())]
        return result[-limit:] if len(result) > limit else result

    async def cleanup_today_bars(self, keep_date: date) -> int:
        """
        清理指定日期之前的当日K线数据

        Args:
            keep_date: 保留该日期及之后的数据

        Returns:
            删除条数
        """
        async with get_async_session(self._db_name) as session:
            result = await session.execute(
                delete(BarTodayPo).where(BarTodayPo.trading_day < keep_date)
            )
            deleted = int(result.rowcount or 0)
        if deleted > 0:
            logger.info(f"已清理 {deleted} 条过期当日K线数据")
        return deleted
