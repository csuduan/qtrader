"""
换仓指令管理请求处理
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


class RotationReqHandler(BaseReqHandler):
    @request("get_rotation_instructions")
    async def _req_get_rotation_instructions(self, data: dict) -> dict:
        """处理获取换仓指令列表请求"""
        rotation_status = {"working": False, "is_manual": False}
        instructions: list = []
        if self.trader.switchPos_manager:
            rotation_status = {
                "working": self.trader.switchPos_manager.working,
                "is_manual": self.trader.switchPos_manager.is_manual,
            }
            instructions = self.trader.switchPos_manager.get_today_instructions()

        result = []
        for ins in instructions:
            # 计算进行中手数（当前挂单中尚未成交的手数）
            pending_volume = 0
            if ins.current_order_id and ins.status == "RUNNING" and self.trader.trading_engine:
                cmd_dict = self.trader.trading_engine.get_order_cmd(str(ins.current_order_id))
                if cmd_dict:
                    pending_volume = cmd_dict.get("pending_volume", 0)

            result.append(
                {
                    "id": ins.id,
                    "account_id": ins.account_id,
                    "strategy_id": ins.strategy_id,
                    "symbol": ins.symbol,
                    "offset": ins.offset,
                    "direction": ins.direction,
                    "volume": ins.volume,
                    "filled_volume": ins.filled_volume,
                    "pending_volume": pending_volume,
                    "price": ins.price,
                    "order_time": ins.order_time,
                    "trading_date": ins.trading_date,
                    "enabled": ins.enabled,
                    "status": ins.status,
                    "attempt_count": ins.attempt_count,
                    "remaining_attempts": ins.remaining_attempts,
                    "remaining_volume": ins.remaining_volume,
                    "current_order_id": ins.current_order_id,
                    "order_placed_time": (
                        ins.order_placed_time.isoformat() if ins.order_placed_time else None
                    ),
                    "last_attempt_time": (
                        ins.last_attempt_time.isoformat() if ins.last_attempt_time else None
                    ),
                    "error_message": ins.error_message,
                    "source": ins.source,
                    "created_at": ins.created_at.isoformat() if ins.created_at else None,
                    "updated_at": ins.updated_at.isoformat() if ins.updated_at else None,
                }
            )

        return {
            "instructions": result,
            "rotation_status": rotation_status,
        }

    @request("get_rotation_instruction")
    async def _req_get_rotation_instruction(self, data: dict) -> dict | None:
        """处理获取指定换仓指令请求"""

        if self.trader.switchPos_manager is None:
            return None
        instruction_id = data.get("instruction_id")
        instructions = self.trader.switchPos_manager.get_today_instructions()
        instruction = next((x for x in instructions if x.id == instruction_id), None)
        if not instruction:
            return None

        return {
            "id": instruction.id,
            "account_id": instruction.account_id,
            "strategy_id": instruction.strategy_id,
            "symbol": instruction.symbol,
            "offset": instruction.offset,
            "direction": instruction.direction,
            "volume": instruction.volume,
            "filled_volume": instruction.filled_volume,
            "price": instruction.price,
            "order_time": instruction.order_time,
            "trading_date": instruction.trading_date,
            "enabled": instruction.enabled,
            "status": instruction.status,
            "attempt_count": instruction.attempt_count,
            "remaining_attempts": instruction.remaining_attempts,
            "remaining_volume": instruction.remaining_volume,
            "current_order_id": instruction.current_order_id,
            "order_placed_time": (
                instruction.order_placed_time.isoformat() if instruction.order_placed_time else None
            ),
            "last_attempt_time": (
                instruction.last_attempt_time.isoformat() if instruction.last_attempt_time else None
            ),
            "error_message": instruction.error_message,
            "source": instruction.source,
            "created_at": (instruction.created_at.isoformat() if instruction.created_at else None),
            "updated_at": (instruction.updated_at.isoformat() if instruction.updated_at else None),
        }

    # 低频接口：手动UI操作触发，内部同步写库可接受，未做异步化
    @request("update_rotation_instruction")
    async def _req_update_rotation_instruction(self, data: dict) -> "RotationInstructionPo | None":
        """处理更新换仓指令请求"""
        instruction_id = data.get("instruction_id")
        if not instruction_id or self.trader.switchPos_manager is None:
            return None

        return await self.trader.switchPos_manager.update_instruction(data)

    @request("import_rotation_instructions")
    async def _req_import_rotation_instructions(self, data: dict) -> dict:
        """处理批量导入换仓指令请求"""
        csv_text = data.get("csv_text")
        filename = data.get("filename")
        mode = data.get("mode", "append")

        if self.trader.switchPos_manager and csv_text and filename:
            return await self.trader.switchPos_manager.import_csv(
                str(csv_text), str(filename), str(mode)
            )
        return {"imported": 0, "skipped": 0, "errors": []}

    @request("execute_rotation")
    async def _req_execute_rotation(self, data: dict) -> bool:
        """处理执行换仓请求"""
        if self.trader.switchPos_manager is None:
            return False

        async def execute():
            try:
                logger.info(f"Trader [{self.account_id}] 换仓任务执行开始")
                await self.trader.switchPos_manager.execute_position_rotation(is_manual=True)
                logger.info(f"Trader [{self.account_id}] 换仓任务执行完成")
            except Exception as e:
                logger.error(f"Trader [{self.account_id}] 后台换仓任务执行失败: {e}")

        asyncio.create_task(execute())
        return True

    @request("stop_rotation")
    async def _req_stop_rotation(self, data: dict) -> bool:
        """处理停止换仓请求"""
        if self.trader.switchPos_manager is None:
            return False
        self.trader.switchPos_manager.stop_rotation()
        return True

    @request("batch_delete_instructions")
    async def _req_batch_delete_instructions(self, data: dict) -> dict:
        """处理批量删除换仓指令请求"""
        ids = data.get("ids", [])
        if self.trader.switchPos_manager is None:
            return {"deleted": 0}
        await self.trader.switchPos_manager.delete_instruction(ids)
        return {"deleted": len(ids)}

    # ========== 目标仓位比对请求处理 ==========
