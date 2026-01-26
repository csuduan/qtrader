"""
账户相关API路由
"""
from typing import List

from fastapi import APIRouter, Depends

from src.api.dependencies import get_trading_engine
from src.api.responses import success_response, error_response
from src.api.schemas import AccountRes
from src.utils.logger import get_logger
from src.models.object import AccountData

logger = get_logger(__name__)

router = APIRouter(prefix="/api/account", tags=["账户"])


@router.get("")
async def get_account_info(engine = Depends(get_trading_engine)):
    """
    获取当前账户信息

    返回实时账户资金情况
    """
    from datetime import datetime

    try:
        if not engine or not engine.account:
            return success_response(
                data=AccountRes(
                    account_id="-",
                    broker_name="",
                    currency="CNY",
                    balance=0,
                    available=0,
                    margin=0,
                    float_profit=0,
                    position_profit=0,
                    close_profit=0,
                    risk_ratio=0,
                    updated_at=datetime.now(),
                    user_id=None,
                ),
                message="获取成功"
            )

        account:AccountData = engine.account
        # 安全获取 user_id，trading_account 可能为 None
        user_id = 'SIM'
        if engine.config.account_type == "real" and engine.config.trading_account:
            user_id = engine.config.trading_account.user_id or 'SIM'


        return success_response(
            data=AccountRes(
                account_id=engine.account_id,
                broker_name=account.broker_name or "",
                currency=account.currency or "CNY",    
                balance=float(account.balance or 0),
                available=float(account.available or 0),
                margin=float(account.margin or 0),
                float_profit=float(account.float_profit or 0),
                position_profit=float(account.hold_profit or 0),
                close_profit=float(account.close_profit or 0),
                risk_ratio=float(account.risk_ratio or 0),
                updated_at=datetime.now(),
                user_id=user_id,
            ),
            message="获取成功"
        )
    except Exception as e:
        logger.error(f"获取账户信息失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取账户信息失败: {str(e)}")
