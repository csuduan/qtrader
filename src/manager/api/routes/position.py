"""
持仓相关API路由
"""

import math
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import PositionRes
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/position", tags=["持仓"])


@router.get("")
async def get_positions(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    获取持仓信息

    返回当前所有持仓或指定账户的持仓
    - account_id: 可选，指定账户ID筛选（多账号模式）
    """
    try:
        # 从 TradingManager 获取持仓数据
        positions_dict = await trading_manager.get_positions(account_id)

        # 过滤禁用账户的持仓数据
        enabled_accounts = set(acc.account_id for acc in trading_manager.account_configs if acc.enabled)
        filtered_positions = {k: v for k, v in positions_dict.items() if k in enabled_accounts}

        # 转换为列表
        positions_list = []
        for acc_id, positions in positions_dict.items():
            if account_id and acc_id != account_id:
                continue
            positions_list.extend(positions)

        return success_response(
            data=[
                PositionRes(
                    id=0,
                    account_id=pos.account_id,
                    exchange_id=(
                        pos.exchange.value if hasattr(pos.exchange, "value") else str(pos.exchange)
                    ),
                    instrument_id=pos.symbol,
                    symbol=(
                        f"{pos.exchange.value}.{pos.symbol}"
                        if hasattr(pos.exchange, "value")
                        else pos.symbol
                    ),
                    pos_long=pos.pos_long,
                    pos_short=pos.pos_short,
                    open_price_long=pos.open_price_long,
                    open_price_short=pos.open_price_short,
                    float_profit_long=pos.float_profit_long,
                    float_profit_short=pos.float_profit_short,
                    margin_long=pos.margin_long,
                    margin_short=pos.margin_short,
                    updated_at=datetime.now(),
                )
                for pos in positions_list
            ],
            message="获取成功",
        )
    except Exception as e:
        logger.exception(f"获取持仓信息失败: {e}")
        return error_response(code=500, message=f"获取持仓信息失败: {str(e)}")


@router.get("/{symbol}")
async def get_position_by_symbol(
    symbol: str,
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    获取指定合约的持仓信息

    - **symbol**: 合约代码
    - **account_id**: 可选，指定账户ID筛选（多账号模式）
    """
    try:
        # 从 TradingManager 获取持仓数据
        positions_dict = await trading_manager.get_positions(account_id)

        result_positions = []

        # 遍历所有账户查找指定合约的持仓
        for acc_id, positions in positions_dict.items():
            for pos in positions:
                # 检查 symbol 是否匹配（支持模糊匹配）
                if symbol in pos.symbol or pos.symbol in symbol:
                    result_positions.append(pos)

        if not result_positions:
            return success_response(data=[], message="获取成功")

        return success_response(
            data=[
                PositionRes(
                    id=0,
                    account_id=pos.account_id,
                    exchange_id=(
                        pos.exchange.value if hasattr(pos.exchange, "value") else str(pos.exchange)
                    ),
                    instrument_id=pos.symbol,
                    symbol=(
                        f"{pos.exchange.value}.{pos.symbol}"
                        if hasattr(pos.exchange, "value")
                        else pos.symbol
                    ),
                    pos_long=pos.pos_long,
                    pos_short=pos.pos_short,
                    open_price_long=(
                        None if math.isnan(pos.open_price_long) else pos.open_price_long
                    ),
                    open_price_short=(
                        None if math.isnan(pos.open_price_short) else pos.open_price_short
                    ),
                    float_profit=float(pos.float_profit_long) + float(pos.float_profit_short),
                    margin=float(pos.margin_long) + float(pos.margin_short),
                    updated_at=datetime.now(),
                )
                for pos in result_positions
            ],
            message="获取成功",
        )
    except Exception as e:
        logger.error(f"获取指定合约持仓失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取指定合约持仓失败: {str(e)}")


@router.post("/close")
async def close_position(
    request: dict,
    trading_manager=Depends(get_trading_manager),
):
    """
    平仓

    - **account_id**: 账户ID（多账号模式）
    - **symbol**: 合约代码
    - **direction**: 买卖方向 (BUY/SELL)
    - **offset**: 开平标志 (OPEN/CLOSE/CLOSETODAY)
    - **volume**: 手数
    - **price**: 价格（0表示市价）
    """
    account_id = request.get("account_id")
    symbol = request.get("symbol")
    direction = request.get("direction")
    offset = request.get("offset")
    volume = request.get("volume")
    price = request.get("price", 0)

    if not account_id:
        return error_response(code=400, message="请提供账户ID")
    if not all([symbol, direction, offset, volume]):
        return error_response(code=400, message="缺少必要参数")

    if direction not in ("BUY", "SELL"):
        return error_response(code=400, message="无效的买卖方向，必须是 BUY 或 SELL")

    if offset not in ("OPEN", "CLOSE", "CLOSETODAY"):
        return error_response(code=400, message="无效的开平标志，必须是 OPEN、CLOSE 或 CLOSETODAY")

    if not isinstance(symbol, str):
        return error_response(code=400, message="合约代码必须是字符串")

    if not isinstance(volume, (int, float)):
        return error_response(code=400, message="手数必须是数字")

    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    # 通过 trader 下单平仓
    order_id = await trader.send_order_request(
        symbol=symbol,
        direction=direction,
        offset=offset,
        volume=int(volume),
        price=float(price),
    )

    if not order_id:
        return error_response(code=500, message="平仓失败")

    return success_response(data={"order_id": order_id}, message="平仓请求已发送")


@router.post("/close-batch")
async def close_batch_positions(
    request: dict,
    trading_manager=Depends(get_trading_manager),
):
    """
    批量平仓

    - **account_id**: 账户ID（多账号模式）
    - **positions**: 持仓列表，每个持仓包含：
         - symbol: 合约代码
         - direction: 买卖方向 (BUY/SELL)
         - offset: 开平标志 (OPEN/CLOSE/CLOSETODAY)
         - volume: 手数
         - price: 价格（可选，默认0）
    """
    account_id = request.get("account_id")
    positions = request.get("positions", [])

    if not account_id:
        return error_response(code=400, message="请提供账户ID")
    if not positions:
        return error_response(code=400, message="请提供要平仓的持仓列表")

    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    success_count = 0
    failed_orders = []

    for pos in positions:
        try:
            symbol = pos.get("symbol")
            direction = pos.get("direction")
            offset = pos.get("offset")
            volume = pos.get("volume")
            price = pos.get("price", 0)

            if not all([symbol, direction, offset, volume]):
                failed_orders.append({"error": "缺少必要参数", "position": pos})
                continue

            if direction not in ("BUY", "SELL"):
                failed_orders.append({"error": "无效的买卖方向", "position": pos})
                continue

            if offset not in ("OPEN", "CLOSE", "CLOSETODAY"):
                failed_orders.append({"error": "无效的开平标志", "position": pos})
                continue

            if not isinstance(symbol, str) or not isinstance(volume, (int, float)):
                failed_orders.append({"error": "参数类型错误", "position": pos})
                continue

            order_id = await trader.send_order_request(
                symbol=symbol,
                direction=direction,
                offset=offset,
                volume=int(volume),
                price=float(price),
            )

            if order_id:
                success_count += 1
            else:
                failed_orders.append({"error": "下单失败", "position": pos})
        except Exception as e:
            failed_orders.append({"error": str(e), "position": pos})

    return success_response(
        data={
            "success_count": success_count,
            "total": len(positions),
            "failed_orders": failed_orders,
        },
        message=f"成功平仓 {success_count}/{len(positions)} 个持仓",
    )
