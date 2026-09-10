"""
持仓导出、合约刷新、公共数据初始化请求处理
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from qtrader.trader.req.base import BaseReqHandler
from qtrader.utils.ipc import request
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.models.po import RotationInstructionPo

logger = get_logger(__name__)


class MiscReqHandler(BaseReqHandler):
    @request("export_positions")
    async def _req_export_positions(self, data: dict) -> dict:
        """
        处理导出持仓请求

        调用 JobManager 的 post_market_export 导出本账户持仓到 CSV。
        """
        if self.trader.job_manager is None:
            logger.error(f"Trader [{self.account_id}] 作业管理器未初始化")
            return {"success": False, "message": "作业管理器未初始化"}

        try:
            await self.trader.job_manager.post_market_export()
            return {"success": True, "message": "持仓导出成功"}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 导出持仓失败: {e}")
            return {"success": False, "message": f"导出失败: {str(e)}"}

    @request("refresh_contracts")
    async def _req_refresh_contracts(self, data: dict) -> dict:
        """
        处理强制刷新合约信息请求

        Returns:
            {"success": bool, "message": str}
        """
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return {"success": False, "message": "交易引擎未初始化"}

        try:
            success = self.trader.trading_engine.refresh_contracts()
            if success:
                logger.info(f"Trader [{self.account_id}] 合约信息刷新成功")
                return {"success": True, "message": "合约信息刷新成功"}
            else:
                logger.warning(f"Trader [{self.account_id}] 合约信息刷新失败")
                return {"success": False, "message": "合约信息刷新失败，请检查网关连接状态"}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 刷新合约信息失败: {e}")
            return {"success": False, "message": f"刷新失败: {str(e)}"}

    @request("init_public_data")
    async def _req_init_public_data(self, data: dict) -> dict:
        """
        接收 Manager 推送的公共数据（合约信息）

        Manager 在检测到本 Trader 进程启动后，会从共享数据库中读取合约信息
        并通过此请求推送过来，Trader 将数据加载到 Gateway 的合约缓存中。

        Args:
            data: {"contracts": [{合约信息字典}, ...]}

        Returns:
            {"success": bool, "message": str, "count": int}
        """
        contracts = data.get("contracts", [])
        if not contracts:
            logger.info(f"Trader [{self.account_id}] 收到空的公共数据推送")
            self.trader._public_data_initialized = True
            if self.trader._init_data_future and not self.trader._init_data_future.done():
                self.trader._init_data_future.set_result(True)
            return {"success": True, "message": "无合约数据", "count": 0}

        try:
            # 将合约数据加载到 Gateway
            if self.trader.trading_engine and self.trader.trading_engine.gateway:
                count = self.trader.trading_engine.gateway.load_contracts_from_init_data(contracts)
                self.trader._public_data_initialized = True
                # 唤醒等待中的 _wait_for_init_data
                if self.trader._init_data_future and not self.trader._init_data_future.done():
                    self.trader._init_data_future.set_result(True)
                logger.info(f"Trader [{self.account_id}] 已从 Manager 加载 {count} 个合约信息")
                return {"success": True, "message": "合约数据已加载", "count": count}
            else:
                logger.warning(
                    f"Trader [{self.account_id}] 交易引擎或 Gateway 未初始化，无法加载合约数据"
                )
                return {"success": False, "message": "交易引擎未初始化", "count": 0}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 加载公共数据失败: {e}")
            return {"success": False, "message": f"加载失败: {str(e)}", "count": 0}
