"""
合约信息相关API路由
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query, Request

from src.app_context import get_app_context
from src.manager.api.responses import error_response, success_response
from src.manager.manager import TradingManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/contract", tags=["合约"])


@router.get("/list")
async def get_contracts(
    request: Request,
    exchange_id: Optional[str] = Query(None, description="交易所筛选"),
    product_type: Optional[str] = Query(None, description="产品类型筛选"),
    symbol_keyword: Optional[str] = Query(None, description="合约代码关键词"),
    account_id: Optional[str] = Query(None, description="账户ID，不传则查询所有账户"),
):
    """
    获取合约列表

    支持按交易所、产品类型、合约代码关键词筛选
    从所有Trader进程的内存中获取合约信息
    """
    try:
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()

        if not trading_manager:
            return error_response(code=500, message="交易管理器未初始化")

        # 从 Trader 进程获取合约列表
        contracts = await trading_manager.get_contracts(
            account_id=account_id,
            exchange_id=exchange_id,
            product_type=product_type,
            symbol_keyword=symbol_keyword,
        )

        # 转换字段名称以兼容前端
        result = []
        for c in contracts:
            result.append({
                "symbol": c.get("symbol", ""),
                "exchange_id": c.get("exchange", ""),
                "name": c.get("name", ""),
                "product_type": c.get("product_type", "FUTURES"),
                "volume_multiple": c.get("multiple", 1),
                "price_tick": c.get("pricetick", 0.01),
                "min_volume": c.get("min_volume", 1),
                "min_open_volume": c.get("min_open_volume", 1),
                "option_strike": c.get("option_strike"),
                "option_underlying": c.get("option_underlying"),
                "option_type": c.get("option_type"),
                "update_date": c.get("update_date", datetime.now().strftime("%Y-%m-%d")),
                "updated_at": None,
            })

        return success_response(data=result, message="获取成功")
    except Exception as e:
        logger.error(f"获取合约列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取合约列表失败: {str(e)}")


@router.get("/exchanges")
async def get_exchanges(request: Request):
    """
    获取可用的交易所列表

    返回内存中存在的交易所及其合约数量
    """
    try:
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()

        if not trading_manager:
            return error_response(code=500, message="交易管理器未初始化")

        # 从 Trader 进程获取所有合约
        contracts = await trading_manager.get_contracts()

        # 统计每个交易所的合约数量
        exchange_counts = {}
        for c in contracts:
            ex_id = c.get("exchange", "")
            if ex_id:
                exchange_counts[ex_id] = exchange_counts.get(ex_id, 0) + 1

        # 转换为列表格式
        data = [
            {"exchange_id": ex_id, "contract_count": count}
            for ex_id, count in exchange_counts.items()
        ]
        data.sort(key=lambda x: x["exchange_id"])

        return success_response(data=data, message="获取成功")
    except Exception as e:
        logger.error(f"获取交易所列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取交易所列表失败: {str(e)}")


@router.post("/refresh")
async def refresh_contracts(
    request: Request,
    account_id: Optional[str] = Query(None, description="账户ID，不传则刷新所有账户"),
):
    """
    强制刷新合约信息

    通知Trader进程从网关接口重新查询合约信息并更新数据库
    """
    try:
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()

        if not trading_manager:
            return error_response(code=500, message="交易管理器未初始化")

        result = await trading_manager.refresh_contracts(account_id)

        # 检查是否有任何成功的刷新
        any_success = any(r.get("success", False) for r in result.get("results", {}).values())

        if any_success:
            return success_response(data=result, message="合约信息刷新成功")
        else:
            return error_response(code=500, message="合约信息刷新失败", data=result)
    except Exception as e:
        logger.error(f"刷新合约信息失败: {e}", exc_info=True)
        return error_response(code=500, message=f"刷新合约信息失败: {str(e)}")
