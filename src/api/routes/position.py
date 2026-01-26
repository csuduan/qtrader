"""
持仓相关API路由
"""
from datetime import datetime
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_trading_engine, require_connected
from src.api.responses import success_response, error_response
from src.api.schemas import PositionRes
from src.trading_engine import TradingEngine
from src.models.object import PositionData

router = APIRouter(prefix="/api/position", tags=["持仓"])


@router.get("")
async def get_positions(
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    获取持仓信息

    返回当前所有持仓或指定合约的持仓
    """
    if not engine or not engine.positions:
        return success_response(
            data=[],
            message="获取成功"
        )

    positions_dict:dict[str,PositionData] = engine.positions


    return success_response(
        data=[
            PositionRes(
                id=0,
                account_id=engine.config.account_id,
                exchange_id=symbol.split(".")[0] if "." in symbol else None,
                instrument_id=symbol.split(".")[1] if "." in symbol else None,
                symbol=symbol,
                pos_long=pos.pos_long,
                pos_short=pos.pos_short,
                open_price_long=None if math.isnan(pos.open_price_long) else pos.open_price_long,
                open_price_short=None if math.isnan(pos.open_price_short) else pos.open_price_short,
                float_profit=float(pos.float_profit_long)+float(pos.float_profit_short),
                margin=float(pos.margin_long)+float(pos.margin_short),
                updated_at=datetime.now(),
            )
            for symbol, pos in positions_dict.items()
        ],
        message="获取成功"
    )


@router.get("/{symbol}")
async def get_position_by_symbol(
    symbol: str,
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    获取指定合约的持仓信息

    - **symbol**: 合约代码
    """
    if not engine or not engine.positions:
        return success_response(
            data=[],
            message="获取成功"
        )

    position = engine.positions.get(symbol)

    if not position:
        return success_response(
            data=[],
            message="获取成功"
        )

    return success_response(
        data=[
            PositionRes(
                id=0,
                account_id=engine.account.account_id if engine.account else "",
                exchange_id=symbol.split(".")[0] if "." in symbol else None,
                instrument_id=symbol.split(".")[1] if "." in symbol else None,
                symbol=symbol,
                pos_long=position.pos_long,
                pos_short=position.pos_short,
                open_price_long=position.open_price_long,
                open_price_short=position.open_price_short,
                float_profit=float(position.float_profit_long) + float(position.float_profit_short),
                margin=float(position.margin_long) + float(position.margin_short),
                updated_at=datetime.now(),
            )
        ],
        message="获取成功"
    )


@router.post("/close")
async def close_position(
    request: dict,
    engine: TradingEngine = Depends(require_connected),
):
    """
    平仓

    - **symbol**: 合约代码
    - **direction**: 买卖方向 (BUY/SELL)
    - **offset**: 开平标志 (OPEN/CLOSE/CLOSETODAY)
    - **volume**: 手数
    - **price**: 价格（0表示市价）
    """
    symbol = request.get("symbol")
    direction = request.get("direction")
    offset = request.get("offset")
    volume = request.get("volume")
    price = request.get("price", 0)

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

    order_id = engine.insert_order(
        symbol=symbol,
        direction=direction,
        offset=offset,
        volume=int(volume),
        price=float(price),
    )

    if not order_id:
        return error_response(code=500, message="平仓失败")

    return success_response(
        data={"order_id": order_id},
        message="平仓请求已发送"
    )


@router.post("/close-batch")
async def close_batch_positions(
    request: dict,
    engine: TradingEngine = Depends(require_connected),
):
    """
    批量平仓

    - **positions**: 持仓列表，每个持仓包含：
         - symbol: 合约代码
         - direction: 买卖方向 (BUY/SELL)
         - offset: 开平标志 (OPEN/CLOSE/CLOSETODAY)
         - volume: 手数
         - price: 价格（可选，默认0）
    """
    positions = request.get("positions", [])

    if not positions:
        return error_response(code=400, message="请提供要平仓的持仓列表")

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

            order_id = engine.insert_order(
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
        message=f"成功平仓 {success_count}/{len(positions)} 个持仓"
    )
