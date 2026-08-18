"""
报单指令相关API路由
"""

from fastapi import APIRouter, Body, Depends, Query

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.api.schemas import OrderCmdRes
from qtrader.manager.manager import TradingManager
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/order-cmd", tags=["报单指令"])


@router.get("")
async def get_order_cmds_status(
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
    status: str | None = Query(None, description="状态过滤 (active/finished)"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取报单指令状态

    返回正在运行的报单指令信息
    """
    try:
        if not account_id:
            return error_response(code=400, message="请提供账户ID")

        result = await trading_manager.get_order_cmds_status(account_id, status)

        if not result:
            return success_response(data=[], message="获取成功")

        # 按开始时间倒序排序（最新的在前）
        result.sort(key=lambda x: x.get("started_at") or "", reverse=True)

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


@router.post("")
async def send_order_cmd(
    request: dict = Body(..., description="订单指令数据"),
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    发送账户级报单指令（手动平仓等）

    Args:
        request: {
            "symbol": "合约代码",
            "direction": "BUY/SELL",
            "offset": "OPEN/CLOSE/CLOSETODAY",
            "volume": 手数,
            "price": 目标价格 (0表示市价)
        }
        account_id: 账户ID
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            return error_response(code=404, message=f"账户 [{account_id}] 不存在")

        symbol = request.get("symbol")
        direction = request.get("direction")
        offset = request.get("offset")
        volume = request.get("volume")
        price = request.get("price", 0)

        if not all([symbol, direction, offset, volume is not None]):
            return error_response(message="缺少必要参数: symbol, direction, offset, volume")

        if direction not in ["BUY", "SELL"]:
            return error_response(message="direction 必须是 BUY 或 SELL")

        if offset not in ["OPEN", "CLOSE", "CLOSETODAY"]:
            return error_response(message="offset 必须是 OPEN, CLOSE 或 CLOSETODAY")

        try:
            volume = int(volume)
            if volume <= 0:
                return error_response(message="volume 必须大于0")
        except (ValueError, TypeError):
            return error_response(message="volume 必须是整数")

        try:
            price = float(price) if price is not None else 0
        except (ValueError, TypeError):
            return error_response(message="price 必须是数字")

        result = await trader.send_request(
            "send_order_cmd",
            {
                "order_cmd": {
                    "symbol": symbol,
                    "direction": direction,
                    "offset": offset,
                    "volume": volume,
                    "price": price,
                }
            },
            timeout=10.0,
        )

        if result and result.get("success"):
            return success_response(message="报单指令已发送", data={"cmd_id": result.get("cmd_id")})
        else:
            return error_response(
                message=result.get("message", "发送报单指令失败") if result else "发送报单指令失败"
            )
    except Exception as e:
        logger.exception(f"发送报单指令失败: {e}")
        return error_response(message=f"发送报单指令失败: {str(e)}")


@router.post("/{cmd_id}/cancel")
async def cancel_order_cmd(
    cmd_id: str,
    account_id: str | None = Query(None, description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    强制取消报单指令

    Args:
        cmd_id: 指令ID
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        if not account_id:
            return error_response(code=400, message="请提供账户ID")

        result = await trading_manager.cancel_order_cmd(account_id, cmd_id)

        if not result:
            return error_response(code=500, message="取消指令失败")

        if result.get("success"):
            return success_response(message="取消指令成功")
        else:
            return error_response(code=400, message=result.get("message", "取消指令失败"))
    except Exception as e:
        logger.exception(f"取消报单指令失败: {e}", exc_info=True)
        return error_response(code=500, message=f"取消报单指令失败: {str(e)}")
