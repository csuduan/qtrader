"""
合约信息相关API路由
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Query, Request
from sqlalchemy.orm import Session

from src.app_context import get_app_context
from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.manager import TradingManager
from src.models.po import ContractPo
from src.utils.config_loader import get_config_loader
from src.utils.database import Database, get_database
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/contract", tags=["合约"])


def get_db(request: Request):
    """从 app.state 获取数据库实例"""
    db = request.app.state.db
    if db is None:
        raise RuntimeError("数据库未初始化，请检查应用启动配置")
    return db


def _get_trader_database_path(account_id: str) -> Optional[str]:
    """
    获取指定账户的数据库文件路径

    Args:
        account_id: 账户ID

    Returns:
        数据库文件路径，如果不存在则返回None
    """
    try:
        config = get_config_loader().load_config()
        # 使用账户配置中的数据库路径
        for acc_config in config.accounts:
            if acc_config.account_id == account_id:
                db_path = Path(acc_config.paths.database).expanduser().resolve()
                if db_path.exists():
                    return str(db_path)
                break
        return None
    except Exception as e:
        logger.error(f"获取账户 [{account_id}] 数据库路径失败: {e}")
        return None


def _query_contracts_from_database(db_path: str, update_date: str) -> List[dict]:
    """
    从指定数据库文件查询合约信息

    Args:
        db_path: 数据库文件路径
        update_date: 更新日期

    Returns:
        合约信息字典列表
    """
    try:
        # 创建临时数据库连接
        db = Database(db_path)
        with db.get_session() as session:
            contract_pos = (
                session.query(ContractPo)
                .filter(ContractPo.update_date == update_date)
                .all()
            )
            # 在Session关闭前转换为字典
            result = []
            for c in contract_pos:
                result.append({
                    "symbol": c.symbol,
                    "exchange_id": c.exchange_id,
                    "name": c.instrument_name,
                    "product_type": c.product_type,
                    "volume_multiple": c.volume_multiple,
                    "price_tick": float(c.price_tick),
                    "min_volume": c.min_volume,
                    "option_strike": float(c.option_strike) if c.option_strike else None,
                    "option_underlying": c.option_underlying,
                    "option_type": c.option_type,
                    "update_date": c.update_date,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                })
            return result
    except Exception as e:
        logger.error(f"从数据库 [{db_path}] 查询合约信息失败: {e}")
        return []


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
    默认返回今天更新的合约信息
    从所有Trader的数据库中查询并合并结果
    """
    try:
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()

        if not trading_manager:
            return error_response(code=500, message="交易管理器未初始化")

        today = datetime.now().strftime("%Y-%m-%d")
        all_contracts = {}
        seen_symbols = set()

        # 确定要查询的账户列表
        account_ids = [account_id] if account_id else list(trading_manager.traders.keys())

        for acc_id in account_ids:
            # 获取该账户的数据库路径
            db_path = _get_trader_database_path(acc_id)
            if not db_path:
                logger.warning(f"账户 [{acc_id}] 的数据库文件不存在")
                continue

            # 从数据库查询合约信息
            contract_list = _query_contracts_from_database(db_path, today)
            if not contract_list:
                continue

            for c in contract_list:
                # 去重：按合约代码去重
                if c["symbol"] in seen_symbols:
                    continue

                # 应用筛选条件
                if exchange_id and c["exchange_id"] != exchange_id.upper():
                    continue
                if product_type and c["product_type"] != product_type.upper():
                    continue
                if symbol_keyword and symbol_keyword.upper() not in c["symbol"].upper():
                    continue

                seen_symbols.add(c["symbol"])
                all_contracts[c["symbol"]] = c

        # 按合约代码排序
        data = sorted(all_contracts.values(), key=lambda x: x["symbol"])

        return success_response(data=data, message="获取成功")
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
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()

        if not trading_manager:
            return error_response(code=500, message="交易管理器未初始化")

        today = datetime.now().strftime("%Y-%m-%d")
        exchange_counts = {}

        # 遍历所有Trader的数据库
        for acc_id in trading_manager.traders.keys():
            db_path = _get_trader_database_path(acc_id)
            if not db_path:
                continue

            contract_list = _query_contracts_from_database(db_path, today)
            if not contract_list:
                continue

            for c in contract_list:
                ex_id = c["exchange_id"]
                if ex_id not in exchange_counts:
                    exchange_counts[ex_id] = 0
                exchange_counts[ex_id] += 1

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
