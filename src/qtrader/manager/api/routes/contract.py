"""
合约信息相关API路由
"""

from fastapi import APIRouter, Query, Request

from qtrader.manager.api.responses import error_response, success_response
from qtrader.models.po import ContractPo
from qtrader.utils.database import get_database
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/contract", tags=["合约"])


@router.get("/list")
async def get_contracts(
    request: Request,
    exchange_id: str | None = Query(None, description="交易所筛选"),
    product_type: str | None = Query(None, description="产品类型筛选"),
    symbol_keyword: str | None = Query(None, description="合约代码关键词"),
    account_id: str | None = Query(None, description="账户ID，不传则查询所有账户"),
):
    """
    获取合约列表

    支持按交易所、产品类型、合约代码关键词筛选
    从合约数据库(ContractPo)中查询合约信息
    """
    try:
        db = get_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        with db.get_session() as session:
            query = session.query(ContractPo)

            # 应用筛选条件
            if exchange_id:
                query = query.filter(ContractPo.exchange_id == exchange_id)

            if product_type:
                query = query.filter(ContractPo.product_type == product_type)

            if symbol_keyword:
                query = query.filter(ContractPo.symbol.contains(symbol_keyword))

            # 只查询活跃合约
            query = query.filter(ContractPo.is_active.is_(True))

            # 按交易所和合约代码排序
            query = query.order_by(ContractPo.exchange_id, ContractPo.symbol)

            contracts = query.all()

            # 转换字段名称以兼容前端
            result = []
            for c in contracts:
                result.append(
                    {
                        "symbol": c.symbol,
                        "exchange_id": c.exchange_id,
                        "name": c.instrument_name or "",
                        "product_type": c.product_type,
                        "volume_multiple": c.volume_multiple,
                        "price_tick": float(c.price_tick) if c.price_tick else 0.01,
                        "min_volume": c.min_volume,
                        "min_open_volume": c.min_volume,  # 暂时用min_volume
                        "option_strike": float(c.option_strike) if c.option_strike else None,
                        "option_underlying": c.option_underlying,
                        "option_type": c.option_type,
                        "update_date": c.update_date,
                        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                    }
                )

        return success_response(data=result, message="获取成功")
    except Exception as e:
        logger.error(f"获取合约列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取合约列表失败: {str(e)}")


@router.get("/exchanges")
async def get_exchanges(request: Request):
    """
    获取可用的交易所列表

    返回数据库中存在的交易所及其合约数量
    """
    try:
        db = get_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        with db.get_session() as session:
            # 从数据库统计每个交易所的活跃合约数量
            contracts = (
                session.query(ContractPo.exchange_id).filter(ContractPo.is_active.is_(True)).all()
            )

            exchange_counts = {}
            for (ex_id,) in contracts:
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
    account_id: str | None = Query(None, description="账户ID，不传则刷新所有账户"),
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
