"""
委托单相关API路由
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import ManualOrderReq, OrderRes
from src.manager.manager import TradingManager
from src.models.object import OrderStatus
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/order", tags=["委托单"])


@router.get("")
async def get_orders(
    status: Optional[str] = Query(None, description="委托单状态: ALIVE/FINISHED/REJECTED"),
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    limit: int = Query(100, ge=1, le=1000, description="返回记录数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取委托单列表

    返回委托单记录，支持按状态筛选和分页
    - ALIVE: 挂单中
    - FINISHED: 已成交（有实际成交）
    - REJECTED: 废单（包括REJECTED状态和FINISHED但未成交任何数量的订单）
    - account_id: 可选，指定账户ID筛选（多账号模式）
    """
    from datetime import datetime

    try:
        # 从 TradingManager 获取订单数据
        orders_list = await trading_manager.get_orders(account_id)

        # 按状态筛选
        if status:
            if status == "REJECTED":
                orders_list = [
                    order
                    for order in orders_list
                    if order.status == OrderStatus.REJECTED
                ]
            elif status == "FINISHED":
                orders_list = [
                    order
                    for order in orders_list
                    if order.status == OrderStatus.FINISHED
                ]
            else:
                orders_list = [order for order in orders_list if order.status == OrderStatus.PENDING]

        total_count = len(orders_list)
        end_index = offset + limit
        paginated_orders = orders_list[offset:end_index]

        return success_response(
            data=[
                OrderRes(
                    id=0,
                    account_id=order.account_id,
                    order_id=order.order_id,
                    exchange_order_id=order.exchange.value or "",
                    symbol=order.symbol,
                    direction=(
                        order.direction.value
                        if hasattr(order.direction, "value")
                        else str(order.direction)
                    ),
                    offset=(
                        order.offset.value if hasattr(order.offset, "value") else str(order.offset)
                    ),
                    volume_orign=order.volume,
                    volume_left=order.volume_left,
                    limit_price=float(order.price) if order.price else None,
                    price_type=(
                        order.price_type.value
                        if hasattr(order.price_type, "value")
                        else str(order.price_type)
                    ),
                    status=order.status,
                    insert_date_time=order.insert_time or datetime.now(),
                    last_msg=order.status_msg or "",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                for order in paginated_orders
            ],
            message="获取成功",
        )
    except Exception as e:
        logger.error(f"获取委托单列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取委托单列表失败: {str(e)}")


@router.get("/{order_id}")
async def get_order_by_id(
    order_id: str,
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    获取指定委托单详情

    - **order_id**: 委托单ID
    - **account_id**: 可选，指定账户ID筛选（多账号模式）
    """
    from datetime import datetime

    # 如果没有指定 account_id，从所有账户中查找
    if account_id:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            return error_response(code=404, message=f"账户 [{account_id}] 不存在")
        order = await trader.get_order(order_id)
    else:
        # 从所有账户中查找订单
        order = None
        found_account_id = None
        for acc_id in trading_manager.get_all_account_ids():
            trader = trading_manager.get_trader(acc_id)
            if trader:
                order = await trader.get_order(order_id)
                if order:
                    found_account_id = acc_id
                    break

    if order:
        return success_response(
            data=OrderRes(
                id=0,
                account_id=order.account_id,
                order_id=order.order_id,
                exchange_order_id=order.exchange_order_id or order.gateway_name or "",
                symbol=order.symbol,
                direction=(
                    order.direction.value
                    if hasattr(order.direction, "value")
                    else str(order.direction)
                ),
                offset=(
                    order.offset.value if hasattr(order.offset, "value") else str(order.offset)
                ),
                volume_orign=order.volume,
                volume_left=order.volume_left,
                limit_price=float(order.price) if order.price else None,
                price_type=(
                    order.price_type.value
                    if hasattr(order.price_type, "value")
                    else str(order.price_type)
                ),
                status=order.status,
                insert_date_time=order.insert_time or datetime.now(),
                last_msg=order.status_msg or "",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ),
            message="获取成功",
        )

    return error_response(code=404, message="委托单不存在")


@router.post("")
async def create_manual_order(
    request: ManualOrderReq,
    trading_manager=Depends(get_trading_manager),
):
    """
    手动报单

    - **account_id**: 账户ID（多账号模式）
    - 根据请求参数创建委托单
    """
    # 验证参数
    if request.direction not in ("BUY", "SELL"):
        return error_response(code=400, message="无效的买卖方向，必须是 BUY 或 SELL")

    if request.offset not in ("OPEN", "CLOSE", "CLOSETODAY"):
        return error_response(code=400, message="无效的开平标志，必须是 OPEN、CLOSE 或 CLOSETODAY")

    # 获取账户ID
    account_id = request.account_id
    if not account_id:
        return error_response(code=400, message="请提供账户ID")

    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    # 通过 trader 下单
    order_id = await trader.send_order_request(
        symbol=request.symbol,
        direction=request.direction,
        offset=request.offset,
        volume=request.volume,
        price=request.price or 0,
    )

    if not order_id:
        return error_response(code=500, message="下单失败")

    return success_response(data={"order_id": order_id}, message="下单成功")


@router.delete("/{order_id}")
async def cancel_order(
    order_id: str,
    account_id: str = None,
    trading_manager=Depends(get_trading_manager),
):
    """
    撤销委托单

    - **order_id**: 委托单ID
    - **account_id**: 账户ID（多账号模式，可选）
    """
    # 如果没有提供 account_id，尝试从所有账户中查找订单
    if account_id:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            return error_response(code=404, message=f"账户 [{account_id}] 不存在")

        success = await trader.send_cancel_request(order_id)
    else:
        # 从所有账户中查找并撤销订单
        success = False
        for acc_id in trading_manager.get_all_account_ids():
            trader = trading_manager.get_trader(acc_id)
            if trader:
                result = await trader.send_cancel_request(order_id)
                if result:
                    success = True
                    break

    if not success:
        return error_response(code=500, message="撤单失败")

    return success_response(data={"order_id": order_id}, message="撤单请求已发送")


@router.post("/cancel-batch")
async def cancel_batch_orders(
    request: dict,
    trading_manager=Depends(get_trading_manager),
):
    """
    批量撤销委托单

    - **account_id**: 账户ID（多账号模式，可选）
    - **order_ids**: 委托单ID列表
    """
    account_id = request.get("account_id")
    order_ids = request.get("order_ids", [])

    if not order_ids:
        return error_response(code=400, message="请提供要撤销的委托单ID列表")

    success_count = 0
    failed_orders = []

    for order_id in order_ids:
        success = False
        if account_id:
            trader = trading_manager.get_trader(account_id)
            if trader:
                success = await trader.send_cancel_request(order_id)
        else:
            # 从所有账户中查找并撤销订单
            for acc_id in trading_manager.get_all_account_ids():
                trader = trading_manager.get_trader(acc_id)
                if trader:
                    result = await trader.send_cancel_request(order_id)
                    if result:
                        success = True
                        break

        if success:
            success_count += 1
        else:
            failed_orders.append(order_id)

    return success_response(
        data={
            "success_count": success_count,
            "total": len(order_ids),
            "failed_orders": failed_orders,
            "message": f"成功撤销 {success_count}/{len(order_ids)} 个委托单",
        },
        message=f"成功撤销 {success_count}/{len(order_ids)} 个委托单",
    )
