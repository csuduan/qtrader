"""
行情相关API路由
"""
from typing import List
import math

from fastapi import APIRouter, Depends

from src.api.dependencies import get_trading_engine, require_connected
from src.api.responses import success_response, error_response
from src.trading_engine import TradingEngine

router = APIRouter(prefix="/api/quote", tags=["行情"])


@router.get("")
async def get_subscribed_quotes(
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    获取所有已订阅的行情列表

    返回当前订阅的所有合约代码（从TradingEngine获取实时数据）
    """
    if not engine or not engine.quotes:
        return success_response(
            data=[],
            message="获取成功"
        )
    quotes_data = [
        {
            "symbol": symbol,
            "last_price": None if math.isnan(quote.last_price) else quote.last_price,
            "bid_price1": None if math.isnan(quote.bid_price1) else quote.bid_price1,
            "ask_price1": None if math.isnan(quote.ask_price1) else quote.ask_price1,
            "volume": quote.volume,
            "datetime": quote.datetime
        }
        for symbol, quote in engine.quotes.items()
    ]

    return success_response(
        data=quotes_data,
        message="获取成功"
    )


@router.post("/subscribe")
async def subscribe_symbol(
    request: dict,
    engine: TradingEngine = Depends(require_connected),
):
    """
    订阅合约行情

    - **symbol**: 合约代码
    """
    symbol = request.get("symbol")

    if not symbol:
        return error_response(code=400, message="请提供合约代码")

    success = engine.subscribe_symbol(symbol)

    if not success:
        return error_response(code=500, message=f"订阅 {symbol} 失败")

    return success_response(
        data={"symbol": symbol},
        message=f"已订阅 {symbol}"
    )


@router.post("/unsubscribe")
async def unsubscribe_symbol(
    request: dict,
    engine: TradingEngine = Depends(require_connected),
):
    """
    取消订阅合约行情

    - **symbol**: 合约代码
    """
    symbol = request.get("symbol")

    if not symbol:
        return error_response(code=400, message="请提供合约代码")

    success = engine.unsubscribe_symbol(symbol)

    if not success:
        return error_response(code=500, message=f"取消订阅 {symbol} 失败")

    return success_response(
        data={"symbol": symbol},
        message=f"已取消订阅 {symbol}"
    )


@router.get("/check/{symbol}")
async def check_subscription(
    symbol: str,
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    检查合约是否已订阅

    - **symbol**: 合约代码
    """
    is_subscribed = engine.is_subscribed(symbol)
    return success_response(
        data={"symbol": symbol, "subscribed": is_subscribed},
        message="获取成功"
    )
