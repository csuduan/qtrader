"""
委托单相关API路由
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_trading_engine, require_connected, require_not_paused
from src.api.responses import success_response, error_response
from src.api.schemas import ManualOrderReq, OrderRes
from src.trading_engine import TradingEngine

router = APIRouter(prefix="/api/order", tags=["委托单"])


@router.get("")
async def get_orders(
    status: Optional[str] = Query(None, description="委托单状态: ALIVE/FINISHED/REJECTED"),
    limit: int = Query(100, ge=1, le=1000, description="返回记录数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    获取委托单列表

    返回委托单记录，支持按状态筛选和分页
    - ALIVE: 挂单中
    - FINISHED: 已成交（有实际成交）
    - REJECTED: 废单（包括REJECTED状态和FINISHED但未成交任何数量的订单）
    """
    from datetime import datetime

    if not engine or not engine.orders:
        return success_response(
            data=[],
            message="获取成功"
        )

    orders_dict = engine.orders

    if status:
        if status == "REJECTED":
            # 废单：状态为REJECTED，或者状态为FINISHED但未成交任何数量
            orders_dict = {
                k: v for k, v in orders_dict.items()
                if v.status == "REJECTED" or
                (v.status == "FINISHED" and v.volume_left == v.volume)
            }
        elif status == "FINISHED":
            # 已成交：状态为FINISHED且有实际成交
            orders_dict = {
                k: v for k, v in orders_dict.items()
                if v.status == "FINISHED" and v.volume_left < v.volume
            }
        else:
            # 其他状态直接匹配
            orders_dict = {k: v for k, v in orders_dict.items() if v.status == status}

    orders_list = list(orders_dict.values())
    total_count = len(orders_list)
    end_index = offset + limit
    paginated_orders = orders_list[offset:end_index]

    return success_response(
        data=[
            OrderRes(
                id=0,
                account_id=engine.account.account_id,
                order_id=order.order_id,
                exchange_order_id=order.exchange.value,
                symbol=order.symbol,
                direction=order.direction,
                offset=order.offset,
                volume_orign=order.volume,
                volume_left=order.volume_left,
                limit_price=float(order.price) if order.price else None,
                price_type=order.price_type,
                status=order.status,
                insert_date_time=order.insert_time,
                last_msg=order.status_msg,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            for order in paginated_orders
        ],
        message="获取成功"
    )


@router.get("/{order_id}")
async def get_order_by_id(
    order_id: str,
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    获取指定委托单详情

    - **order_id**: 委托单ID
    """
    from datetime import datetime

    if not engine or not engine.orders:
        return error_response(code=404, message="委托单不存在")

    order = engine.orders.get(order_id)

    if not order:
        return error_response(code=404, message="委托单不存在")

    return success_response(
        data=OrderRes(
            id=0,
            account_id=engine.account.account_id if engine.account else "",
            order_id=order.order_id,
            exchange_order_id=order.gateway_order_id,
            symbol=order.symbol,
            direction=order.direction.value,
            offset=order.offset.value,
            volume_orign=order.volume,
            volume_left=order.volume_left,
            limit_price=float(order.price) if order.price else None,
            price_type=order.price_type.value,
            status=order.status,
            insert_date_time=order.insert_time or datetime.now(),
            last_msg=order.status_msg,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        message="获取成功"
    )


@router.post("")
async def create_manual_order(
    request: ManualOrderReq,
    engine: TradingEngine = Depends(require_connected),
    check_paused = Depends(require_not_paused),
):
    """
    手动报单

    根据请求参数创建委托单
    """
    # 验证参数
    if request.direction not in ("BUY", "SELL"):
        return error_response(code=400, message="无效的买卖方向，必须是 BUY 或 SELL")

    if request.offset not in ("OPEN", "CLOSE", "CLOSETODAY"):
        return error_response(code=400, message="无效的开平标志，必须是 OPEN、CLOSE 或 CLOSETODAY")

    # 下单
    order_id = engine.insert_order(
        symbol=request.symbol,
        direction=request.direction,
        offset=request.offset,
        volume=request.volume,
        price=request.price or 0,
    )

    if not order_id:
        return error_response(code=500, message="下单失败")

    return success_response(
        data={"order_id": order_id},
        message="下单成功"
    )


@router.delete("/{order_id}")
async def cancel_order(
    order_id: str,
    engine = Depends(require_connected),
):
    """
    撤销委托单

    - **order_id**: 委托单ID
    """
    success = engine.cancel_order(order_id)

    if not success:
        return error_response(code=500, message="撤单失败")

    return success_response(
        data={"order_id": order_id},
        message="撤单请求已发送"
    )


@router.post("/cancel-batch")
async def cancel_batch_orders(
    request: dict,
    engine = Depends(require_connected),
):
    """
    批量撤销委托单

    - **order_ids**: 委托单ID列表
    """
    order_ids = request.get("order_ids", [])

    if not order_ids:
        return error_response(code=400, message="请提供要撤销的委托单ID列表")

    success_count = 0
    failed_orders = []

    for order_id in order_ids:
        success = engine.cancel_order(order_id)
        if success:
            success_count += 1
        else:
            failed_orders.append(order_id)

    return success_response(
        data={
            "success_count": success_count,
            "total": len(order_ids),
            "failed_orders": failed_orders,
            "message": f"成功撤销 {success_count}/{len(order_ids)} 个委托单"
        },
        message=f"成功撤销 {success_count}/{len(order_ids)} 个委托单"
    )
