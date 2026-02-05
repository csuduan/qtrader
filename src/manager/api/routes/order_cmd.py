"""
报单指令相关API路由
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import OrderCmdRes
from src.manager.core.trading_manager import TradingManager
from src.utils.logger import get_logger



logger = get_logger(__name__)

router = APIRouter(prefix="/api/order-cmd", tags=["报单指令"])


@router.get("")
async def get_order_cmds_status(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    status: Optional[str] = Query(None, description="状态过滤 (active/finished)"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取报单指令状态

    返回正在运行的报单指令信息
    """
    try:
        if not account_id:
            return error_response(code=400, message="请提供账户ID")

        result = await trading_manager.get_order_cmds_status(account_id,status)

        if not result:
            return success_response(data=[], message="获取成功")

        return success_response(
            data=[
                OrderCmdRes(
                    cmd_id=cmd.get("cmd_id", ""),
                    status=cmd.get("status", ""),
                    symbol=cmd.get("symbol", ""),
                    filled_volume=cmd.get("filled_volume", 0),
                    volume=cmd.get("volume", 0),
                    direction=cmd.get("direction"),
                    offset=cmd.get("offset"),
                    limit_price=cmd.get("limit_price"),
                    started_at=cmd.get("started_at"),
                    finished_at=cmd.get("finished_at"),
                    total_orders=cmd.get("total_orders", 0),
                    finish_reason=cmd.get("finish_reason", ""),
                )
                for cmd in result
            ],
            message="获取成功",
        )
    except Exception as e:
        logger.exception(f"获取报单指令失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取报单指令失败: {str(e)}")
