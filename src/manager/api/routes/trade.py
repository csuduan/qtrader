"""
成交相关API路由
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import TradeRes
from src.manager.manager import TradingManager
from src.models.object import TradeData
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/trade", tags=["成交"])


@router.get("")
async def get_trades(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    date: Optional[str] = Query(None, description="查询日期（YYYY-MM-DD格式），默认为今日"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取成交记录

    返回最近的成交记录，支持分页
    - 今日成交记录自动从内存查询
    - 历史成交记录自动从数据库查询
    - 设置from_db=true可强制从数据库查询
    - account_id: 可选，指定账户ID筛选（多账号模式）
    """

    try:
        # 从内存查询（使用 TradingManager）
        trades_list: List[TradeData] = await trading_manager.get_trades(account_id=account_id)
        return success_response(
            data=[
                TradeRes(
                    id=0,
                    account_id=trade.account_id,
                    trade_id=trade.trade_id,
                    order_id=trade.order_id,
                    symbol=trade.symbol,
                    direction=(
                        trade.direction.value
                        if hasattr(trade.direction, "value")
                        else str(trade.direction)
                    ),
                    offset=(
                        trade.offset.value if hasattr(trade.offset, "value") else str(trade.offset)
                    ),
                    price=float(trade.price),
                    volume=trade.volume,
                    trade_date_time=trade.trade_time or datetime.now(),
                    created_at=datetime.now(),
                )
                for trade in trades_list
            ],
            message="获取成功",
        )
    except Exception as e:
        logger.exception(f"获取成交记录失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取成交记录失败: {str(e)}")


@router.get("/order/{order_id}")
async def get_trades_by_order(
    order_id: str,
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取指定委托单的成交记录

    - **order_id**: 委托单ID
    - **account_id**: 可选，指定账户ID筛选（多账号模式）
    """
    try:
        # 从 TradingManager 获取所有成交记录
        all_trades = await trading_manager.get_trades(account_id)

        # 筛选出指定委托单的成交记录
        order_trades = [
            TradeRes(
                id=0,
                account_id=trade.account_id,
                trade_id=trade.trade_id,
                order_id=trade.order_id,
                symbol=trade.symbol,
                direction=(
                    trade.direction.value
                    if hasattr(trade.direction, "value")
                    else str(trade.direction)
                ),
                offset=(
                    trade.offset.value if hasattr(trade.offset, "value") else str(trade.offset)
                ),
                price=float(trade.price),
                volume=trade.volume,
                trade_date_time=trade.trade_time or datetime.now(),
                created_at=datetime.now(),
            )
            for trade in all_trades
            if trade.order_id == order_id
        ]

        return success_response(data=order_trades, message="获取成功")
    except Exception as e:
        logger.error(f"获取委托单成交记录失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取委托单成交记录失败: {str(e)}")
