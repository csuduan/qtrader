"""
Manager 数据服务
通过 data-only TqApi 订阅K线：当日bar实时落库、历史K线全量落库、故障后手动同步

设计约束：bar 只落库，不进入实时交易路径（Trader 的策略行情始终来自自己的网关）
运行说明：feed 线程持有独立的事件循环与独立异步数据库实例（"feed"），
asyncpg 连接池绑定事件循环，不能与主循环共享实例。
"""

import asyncio
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import or_, select
from tqsdk import TqApi, TqAuth

from qtrader.models.object import BarData
from qtrader.models.po import ContractPo
from qtrader.trader.dao.bar_dao import BarDao
from qtrader.utils.async_database import (
    close_async_database,
    get_async_session,
    init_async_database,
)
from qtrader.utils.config_loader import AccountConfig, AppConfig, get_config_loader
from qtrader.utils.db_url import build_async_db_url
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 当日bar写入账户标记（bars_today.account_id）
FEED_ACCOUNT_ID = "MANAGER"

# feed 线程专用异步数据库实例名
FEED_DB_NAME = "feed"

# 自动全量同步间隔（秒），同时用于发现新增订阅（如换月后的新合约）
AUTO_SYNC_INTERVAL = 300.0


def collect_bar_subscriptions(
    app_config: AppConfig | None, account_configs: list[AccountConfig] | None
) -> list[tuple[str, str]]:
    """
    汇总所有启用账户的启用策略K线订阅（去重），加上全局subs配置

    Args:
        app_config: 全局配置
        account_configs: 账户配置列表

    Returns:
        [(symbol, interval)] 列表
    """
    subs: dict[tuple[str, str], None] = {}
    for account_config in account_configs or []:
        if not account_config or not account_config.enabled:
            continue
        for strategy in (account_config.strategies or {}).values():
            if strategy.enabled and strategy.symbol:
                subs[(strategy.symbol, strategy.bar)] = None

    if app_config and app_config.subs and app_config.subs.subscribe_bars:
        for item in app_config.subs.subscribe_bars:
            if "-" in item:
                symbol, interval = item.split("-", 1)
                if symbol:
                    subs[(symbol, interval)] = None
    return list(subs.keys())


class ManagerDataFeed:
    """Manager 数据服务（data-only TqApi，不连接交易账户）"""

    def __init__(
        self,
        username: str,
        password: str,
        subscriptions_getter: Callable[[], list[tuple[str, str]]],
    ):
        """
        初始化

        Args:
            username: 天勤账户用户名（config.yaml data_service.tq_data）
            password: 天勤账户密码
            subscriptions_getter: 返回 [(symbol, interval)] 的回调（动态读取，支持换月）
        """
        self.username = username
        self.password = password
        self._subscriptions_getter = subscriptions_getter
        self.api: TqApi | None = None
        self._klines: dict[tuple[str, str], pd.DataFrame] = {}  # (symbol, interval) -> kline serial
        self._running = False
        self._thread: threading.Thread | None = None
        self._resync_requested = False  # 手动同步标志（API线程设置，feed线程执行）
        self._last_sync_time = 0.0
        self._dao = BarDao(db_name=FEED_DB_NAME)

    @property
    def connected(self) -> bool:
        """数据服务是否已连接"""
        return self.api is not None and self._running

    def start(self) -> None:
        """启动数据服务（后台线程）"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="ManagerDataFeed", daemon=True)
        self._thread.start()
        logger.info("ManagerDataFeed 已启动")

    def stop(self) -> None:
        """停止数据服务"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("ManagerDataFeed 已停止")

    def request_resync(self) -> str:
        """
        请求全量同步（线程安全，手动同步接口使用）

        feed线程在下一轮轮询时执行：补订阅新合约 + 全量K线落库（覆盖修正）

        Returns:
            提示信息
        """
        if not self.connected:
            return "数据服务未连接，无法同步"
        self._resync_requested = True
        return "已触发同步，将在数秒内执行完成"

    # ==================== 内部实现 ====================

    def _run(self) -> None:
        """feed主线程入口：创建独立事件循环与数据库实例后运行异步主逻辑"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        finally:
            loop.run_until_complete(close_async_database(FEED_DB_NAME))
            loop.close()
            asyncio.set_event_loop(None)

    async def _run_async(self) -> None:
        """feed异步主逻辑：初始化feed库、连接tqsdk、订阅K线、循环检测新bar落库"""
        try:
            # 初始化 feed 线程专用数据库实例（连接池绑定本线程事件循环）
            db_config = get_config_loader()._load_app_config().data_base
            if db_config:
                await init_async_database(
                    build_async_db_url(db_config),
                    account_id=FEED_ACCOUNT_ID,
                    pool_size=2,
                    max_overflow=2,
                    name=FEED_DB_NAME,
                )

            self.api = TqApi(auth=TqAuth(self.username, self.password))
            logger.info("ManagerDataFeed TqApi 连接成功")

            # 首次全量同步（启动缺口自愈）
            await self._sync_all()

            while self._running:
                try:
                    has_data = self.api.wait_update(deadline=time.time() + 3)
                    if has_data:
                        await self._push_new_bars()
                    if self._resync_requested or (
                        time.time() - self._last_sync_time > AUTO_SYNC_INTERVAL
                    ):
                        self._resync_requested = False
                        await self._sync_all()
                except Exception:
                    logger.exception("ManagerDataFeed 轮询异常")
                    time.sleep(1)
        except Exception:
            logger.exception("ManagerDataFeed 致命错误")
        finally:
            if self.api:
                self.api.close()
                self.api = None
            logger.info("ManagerDataFeed 线程已退出")

    async def _subscribe(self, symbol: str, interval: str) -> bool:
        """
        订阅K线（补齐新订阅）

        Args:
            symbol: 项目合约代码（如IM2609）
            interval: K线周期（如M1）

        Returns:
            是否订阅成功
        """
        if self.api is None:
            return False
        key = (symbol, interval)
        if key in self._klines:
            return True

        tq_symbol = await self._resolve_tq_symbol(symbol)
        if tq_symbol is None:
            logger.warning(f"无法确定合约交易所，跳过订阅: {symbol}")
            return False

        seconds = int(interval[1:]) * 60 if interval.upper().startswith("M") else 0
        if seconds <= 0:
            logger.warning(f"不支持的K线周期，跳过: {symbol} {interval}")
            return False

        try:
            kline = self.api.get_kline_serial(tq_symbol, duration_seconds=seconds, data_length=720)
            self._klines[key] = kline
            logger.info(f"ManagerDataFeed 订阅K线: {tq_symbol} {interval}")
            return True
        except Exception:
            logger.exception("ManagerDataFeed 订阅K线失败: {} {}", tq_symbol, interval)
            return False

    async def _resolve_tq_symbol(self, symbol: str) -> str | None:
        """
        将项目合约代码转换为tqsdk格式（EXCHANGE.symbol）

        从合约表查询交易所信息（表内symbol为裸合约代码，如IM2609；兼容带前缀格式）。

        Args:
            symbol: 项目合约代码（如IM2609）

        Returns:
            tqsdk合约代码（如CFFEX.IM2609），未找到返回None
        """
        try:
            async with get_async_session(FEED_DB_NAME) as session:
                row = (
                    await session.execute(
                        select(ContractPo.symbol, ContractPo.exchange_id).filter(
                            or_(
                                ContractPo.symbol == symbol,
                                ContractPo.symbol.endswith(f".{symbol}"),
                            )
                        )
                    )
                ).first()
            if not row or not row.exchange_id:
                return None
            bare_symbol = row.symbol.split(".")[1] if "." in row.symbol else row.symbol
            return f"{row.exchange_id}.{bare_symbol}"
        except Exception:
            logger.exception("查询合约交易所失败: {}", symbol)
            return None

    @logger.catch(message="ManagerDataFeed 新bar落库失败")
    async def _push_new_bars(self) -> None:
        """检测新完成的bar并写入当日表（feed线程调用）"""
        if self.api is None:
            return
        trading_day = self._get_trading_day()
        if trading_day is None:
            return
        new_bars: list[BarData] = []
        for (symbol, interval), kline in self._klines.items():
            if self.api.is_changing(kline.iloc[-1], "datetime"):
                # 新bar出现，iloc[-2]为刚完成的bar
                row = kline.iloc[-2]
                bar_time = datetime.fromtimestamp(row["datetime"] / 1e9)
                new_bars.append(
                    BarData(
                        symbol=symbol,
                        interval=interval,
                        datetime=bar_time,
                        open_price=float(row["open"]),
                        high_price=float(row["high"]),
                        low_price=float(row["low"]),
                        close_price=float(row["close"]),
                        volume=float(row["volume"]),
                        turnover=0,
                        open_interest=float(row["close_oi"] or 0),
                        update_time=bar_time + timedelta(minutes=1),
                    )
                )
        if new_bars:
            await self._dao.upsert_today_bars(FEED_ACCOUNT_ID, new_bars, trading_day)
            logger.debug(f"ManagerDataFeed 当日bar落库: {len(new_bars)}根")

    @logger.catch(message="ManagerDataFeed 全量同步失败")
    async def _sync_all(self) -> None:
        """
        全量同步（feed线程调用）：补订阅新合约 + 全量K线落库

        历史段落 bars_history（官方数据覆盖修正），全部段落 bars_today（当日表，
        过期数据由盘后任务清理，trading_day标记为当前交易日）。
        """
        self._last_sync_time = time.time()
        # 1. 补订阅（支持换月后的新合约）
        for symbol, interval in self._subscriptions_getter():
            await self._subscribe(symbol, interval)
        if self.api is None or not self._klines:
            return
        trading_day = self._get_trading_day()
        if trading_day is None:
            logger.warning("ManagerDataFeed 未获取到交易日，跳过全量同步")
            return
        # 2. 全量落库
        history_rows: list[dict[str, Any]] = []
        today_bars = []
        for (symbol, interval), kline in self._klines.items():
            for _, row in kline.iterrows():
                if not row["volume"] or row["volume"] <= 0:
                    continue
                bar_time = datetime.fromtimestamp(row["datetime"] / 1e9)
                history_rows.append(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "bar_time": bar_time,
                        "trading_day": trading_day,  # 标记字段，历史段按bar_time查询
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                        "turnover": 0,
                        "open_interest": float(row["close_oi"] or 0),
                    }
                )
                today_bars.append(
                    BarData(
                        symbol=symbol,
                        interval=interval,
                        datetime=bar_time,
                        open_price=float(row["open"]),
                        high_price=float(row["high"]),
                        low_price=float(row["low"]),
                        close_price=float(row["close"]),
                        volume=float(row["volume"]),
                        turnover=0,
                        open_interest=float(row["close_oi"] or 0),
                        update_time=bar_time + timedelta(minutes=1),
                    )
                )
        if history_rows:
            await self._dao.upsert_history_bars(history_rows, "tq")
        if today_bars:
            await self._dao.upsert_today_bars(FEED_ACCOUNT_ID, today_bars, trading_day)
        logger.info(
            f"ManagerDataFeed 全量同步完成: {len(self._klines)}个订阅, {len(history_rows)}根"
        )

    def _get_trading_day(self) -> date | None:
        """
        获取当前交易日（跟随TqGateway口径：20点后算下一交易日，用交易日历校正）

        Returns:
            交易日date，未连接返回None
        """
        if self.api is None:
            return None
        now = datetime.now()
        trading_day = now.date() + timedelta(days=1) if now.hour >= 20 else now.date()
        try:
            calendar = self.api.get_trading_calendar(now, now + timedelta(days=30))
            while not calendar[calendar.date == trading_day.strftime("%Y-%m-%d")]["trading"].iloc[
                0
            ]:
                trading_day += timedelta(days=1)
        except Exception as e:
            logger.warning("查询交易日历失败，使用自然日作为交易日: {!r}", e)
        return trading_day

    def sync_history(self) -> str:
        """
        盘后历史固化任务入口（由Manager定时任务调用，异步触发）

        Returns:
            提示信息
        """
        return self.request_resync()
