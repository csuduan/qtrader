"""
行情相关API路由
"""

from typing import List

from fastapi import APIRouter, Depends

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.manager import TradingManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/quote", tags=["行情"])


@router.get("")
async def get_subscribed_quotes(
    account_id: str = None,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取所有已订阅的行情列表

    返回当前订阅的所有合约代码（从 TradingManager 获取实时数据）
    """
    try:
        # 获取行情数据（从所有 trader 聚合）
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
        logger.exception(f"获取行情列表失败: {e}")
        return error_response(code=500, message=f"获取行情列表失败: {str(e)}")


@router.post("/subscribe")
async def subscribe_symbol(
    request: dict,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
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

    # 检查 trader 是否支持订阅
    success = await trader.subscribe(request)

    if not success:
        return error_response(code=500, message=f"订阅 {symbol} 失败")

    return success_response(
        data={"account_id": account_id, "symbol": symbol}, message=f"已订阅 {symbol}"
    )
