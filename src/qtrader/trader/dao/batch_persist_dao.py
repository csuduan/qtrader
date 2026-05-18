"""
批量持久化DAO
负责账户和持仓数据的缓存及定时批量写入
"""

import asyncio
from typing import Any

from qtrader.trader.dao.account_dao import AccountDao
from qtrader.trader.dao.position_dao import PositionDao
from qtrader.utils.database import session_scope
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class BatchPersistDao:
    """批量持久化数据访问对象"""

    def __init__(self, account_id: str, persist_interval: float = 30.0):
        self.account_id = account_id
        self._persist_interval = persist_interval
        self._pending_accounts: dict[str, Any] = {}
        self._pending_positions: dict[str, Any] = {}
        self._persist_task: asyncio.Task | None = None
        self._running = False
        self._account_dao = AccountDao()
        self._position_dao = PositionDao()

    def start(self) -> asyncio.Task:
        """启动定时批量持久化任务"""
        self._running = True
        self._persist_task = asyncio.create_task(self._periodic_persist())
        return self._persist_task

    async def stop(self) -> None:
        """停止定时任务并强制刷新剩余数据"""
        self._running = False
        if self._persist_task:
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                pass
        await self.flush()

    def cache_account(self, data) -> None:
        """缓存账户数据，等待批量写入"""
        try:
            account_data = data.model_dump() if hasattr(data, "model_dump") else data
            self._pending_accounts[self.account_id] = account_data
            logger.debug(f"账户数据已缓存: {self.account_id}")
        except Exception as e:
            logger.exception(f"缓存账户数据失败: {e}")

    def cache_position(self, data) -> None:
        """缓存持仓数据，等待批量写入"""
        try:
            position_data = data.model_dump() if hasattr(data, "model_dump") else data
            symbol = position_data.get("symbol")
            if symbol:
                self._pending_positions[symbol] = position_data
                logger.debug(f"持仓数据已缓存: {symbol}")
        except Exception as e:
            logger.exception(f"缓存持仓数据失败: {e}")

    async def _periodic_persist(self) -> None:
        """定时批量持久化循环"""
        while self._running:
            try:
                await asyncio.sleep(self._persist_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"定时持久化任务出错: {e}")

    async def flush(self) -> None:
        """将缓存的数据批量写入数据库"""
        if not self._pending_accounts and not self._pending_positions:
            return

        try:
            with session_scope() as session:
                for account_id, data in self._pending_accounts.items():
                    self._account_dao.save_dict(session, account_id, data)
                for symbol, data in self._pending_positions.items():
                    self._position_dao.save_dict(session, self.account_id, symbol, data)

            count_accounts = len(self._pending_accounts)
            count_positions = len(self._pending_positions)
            self._pending_accounts.clear()
            self._pending_positions.clear()

            logger.debug(f"批量持久化完成: {count_accounts} 账户, {count_positions} 持仓")
        except Exception as e:
            logger.exception(f"批量持久化失败: {e}")
