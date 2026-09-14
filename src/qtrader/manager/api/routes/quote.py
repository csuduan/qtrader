"""
行情相关API路由
"""

from typing import Any

from fastapi import APIRouter, Depends, Response

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.manager import TradingManager
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/quote", tags=["行情"])


@router.get("")
async def get_subscribed_quotes(
    account_id: str | None = None,
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    获取所有已订阅的行情列表

    返回当前订阅的所有合约代码（从Manager内存缓存获取，由Trader实时推送维护）
    """
    try:
        # 从Manager内存缓存获取行情（由Trader tick推送维护）
        all_quotes = []
        if account_id:
            # 获取指定账户的行情
            trader = trading_manager.get_trader(account_id)
            if trader:
                quotes = await trader.get_quotes()
                all_quotes = [
                    {
                        "account_id": account_id,
                        "symbol": q.symbol,
                        "last_price": q.last_price if q else None,
                        "bid_price1": q.bid_price1 if q else None,
                        "ask_price1": q.ask_price1 if q else None,
                        "volume": q.volume if q else 0,
                        "datetime": q.datetime if q else None,
                    }
                    for q in quotes
                ]
        return success_response(data=all_quotes, message="获取成功")
    except Exception as e:
        logger.exception("获取行情列表失败")
        return error_response(code=500, message=f"获取行情列表失败: {e}")


@router.post("/subscribe")
async def subscribe_symbol(
    request: dict[str, Any],
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    订阅合约行情

    - **account_id**: 账户ID
    - **symbol**: 合约代码
    """
    account_id = request.get("account_id")
    symbol = request.get("symbol")

    if not account_id:
        return error_response(code=400, message="请提供账户ID")
    if not symbol:
        return error_response(code=400, message="请提供合约代码")

    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    # 检查 trader 是否支持订阅（异常含 Trader 回传的真实失败原因，透传给前端）
    try:
        success = await trader.subscribe(request)
    except Exception as e:
        logger.exception("订阅 {} 失败 [{}]", symbol, account_id)
        return error_response(code=500, message=f"订阅 {symbol} 失败: {e}")

    if not success:
        return error_response(code=500, message=f"订阅 {symbol} 失败")

    return success_response(
        data={"account_id": account_id, "symbol": symbol}, message=f"已订阅 {symbol}"
    )
