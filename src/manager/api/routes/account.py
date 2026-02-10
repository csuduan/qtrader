"""
账户相关API路由
"""

from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query

from src.app_context import get_app_context
from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import AccountRes, TraderStatusRes
from src.manager.manager import TradingManager
from src.models.object import AccountData,TraderState
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/account", tags=["账户"])


@router.get("")
async def get_account_info(
    account_id: Optional[str] = Query(None, description="账户ID，不传则返回第一个账户"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取指定账户信息

    返回实时账户资金情况
    """
    from datetime import datetime

    try:
        # 从 TradingManager 获取账户数据
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()
        account_data = await trading_manager.get_account(account_id)
        if not account_data:
            return error_response(code=404, message=f"账户 [{account_id}] 不存在")

        return success_response(
            data=AccountRes(
                account_id=account_id,
                broker_type=account_data.broker_type or "--",
                broker_name=account_data.broker_name if account_data.broker_type=="real" else "--",
                currency=account_data.currency or "CNY",
                balance=float(account_data.balance or 0),
                available=float(account_data.available or 0),
                margin=float(account_data.margin or 0),
                float_profit=float(account_data.float_profit or 0),
                position_profit=float(account_data.hold_profit or 0),
                close_profit=float(account_data.close_profit or 0),
                risk_ratio=float(account_data.risk_ratio or 0),
                updated_at=datetime.now(),
                user_id=account_data.user_id or "--",
                risk_status=account_data.risk_status or {},
                trade_paused=account_data.trade_paused,
                gateway_connected=account_data.gateway_connected,
                status=account_data.status.value if account_data.status else None,
            ),
            message="获取成功",
        )
    except Exception as e:
        logger.error(f"获取账户信息失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取账户信息失败: {str(e)}")


@router.get("/all")
async def get_all_accounts(
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取所有账户信息（多账号模式）
    返回所有账户的资金情况
    """
    from datetime import datetime

    try:
        # 从 TradingManager 获取所有账户数据
        ctx = get_app_context()
        trading_manager: TradingManager = ctx.get_trading_manager()
        accounts = await trading_manager.get_all_accounts()
        accounts_list = []
        for account_info in accounts:
            # 添加 None 检查，避免访问 None 对象的属性
            if account_info is None:
                continue

            accounts_list.append(
                AccountRes(
                    account_id=account_info.account_id,
                    broker_type=account_info.broker_type or "--",
                    broker_name=account_info.broker_name if account_info.broker_type=="real" else "--",
                    currency=account_info.currency or "CNY",
                    balance=float(account_info.balance or 0),
                    available=float(account_info.available or 0),
                    margin=float(account_info.margin or 0),
                    float_profit=float(account_info.float_profit or 0),
                    position_profit=float(account_info.hold_profit or 0),
                    close_profit=float(account_info.close_profit or 0),
                    risk_ratio=float(account_info.risk_ratio or 0),
                    updated_at=datetime.now(),
                    user_id=account_info.user_id or "--",
                    gateway_connected=account_info.gateway_connected,
                    trade_paused=account_info.trade_paused,
                    risk_status=account_info.risk_status or {},
                    status=account_info.status.value if account_info.status else TraderState.STOPPED.value,
                )
            )
        sorted_list = sorted(accounts_list, key=lambda x: x.account_id)
        return success_response(data=sorted_list, message="获取成功")
    except Exception as e:
        logger.exception(f"获取所有账户信息失败: {e}")
        return error_response(code=500, message=f"获取所有账户信息失败: {str(e)}")


@router.get("/traders/status")
async def get_traders_status(
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    批量获取所有Trader状态

    返回所有账户的Trader连接状态，用于前端账户状态展示（总览账户面板和header中账户状态）
    交易状态和网关状态还是继续从account接口获取

    Returns:
        Trader状态列表
    """
    try:
        traders_status = trading_manager.get_all_trader_status()
        result = []
        for status in traders_status:
            result.append(
                TraderStatusRes(
                    account_id=status["account_id"],
                    state=status["state"],
                    running=status["running"],
                    alive=status["alive"],
                    connected=status["connected"],
                    connecting=status["connecting"],
                    created_process=status["created_process"],
                    pid=status["pid"],
                    start_time=status.get("start_time"),
                    last_heartbeat=status.get("last_heartbeat"),
                    restart_count=status["restart_count"],
                    socket_path=status.get("socket_path"),
                )
            )
        return success_response(data=result, message="获取成功")
    except Exception as e:
        logger.exception(f"获取Trader状态失败: {e}")
        return error_response(code=500, message=f"获取Trader状态失败: {str(e)}")


@router.post("/{account_id}/start")
async def start_account_trader(
    account_id: str,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    启动账户Trader

    启动指定账户的Trader进程
    - **account_id**: 账户ID
    """
    success = await trading_manager.start_trader(account_id)

    if success:
        return success_response(data={"running": True}, message="Trader已启动")
    else:
        return error_response(code=500, message="Trader启动失败")


@router.post("/{account_id}/stop")
async def stop_account_trader(
    account_id: str,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止账户Trader

    停止指定账户的Trader进程
    - **account_id**: 账户ID
    """
    success = await trading_manager.stop_trader(account_id)

    if success:
        return success_response(data={"running": False}, message="Trader已停止")
    else:
        return error_response(code=500, message="Trader停止失败")


@router.post("/{account_id}/connect")
async def connect_account_gateway(
    account_id: str,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    连接账户网关

    建立与交易接口的连接
    - **account_id**: 账户ID
    """
    trader = trading_manager.traders.get(account_id)

    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    success = await trader.connect()
    if success:
        return success_response(data={"connected": True}, message="连接成功")
    else:
        return error_response(code=500, message="连接失败")


@router.post("/{account_id}/disconnect")
async def disconnect_account_gateway(
    account_id: str,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    断开账户网关连接

    关闭与交易接口的连接
    - **account_id**: 账户ID
    """
    trader = trading_manager.traders.get(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    success = await trader.disconnect()
    if success:
        return success_response(data={"connected": False}, message="已断开连接")
    else:
        return error_response(code=500, message="断开连接失败")


@router.post("/{account_id}/pause")
async def pause_account_trading(
    account_id: str,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    暂停账户交易

    暂停自动交易功能，手动下单仍然可用
    - **account_id**: 账户ID
    """
    trader = trading_manager.traders.get(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    success = await trader.pause()
    if success:
        return success_response(data={"paused": True}, message="交易已暂停")
    else:
        return error_response(code=500, message="暂停交易失败")


@router.post("/{account_id}/resume")
async def resume_account_trading(
    account_id: str,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    恢复账户交易

    恢复自动交易功能
    - **account_id**: 账户ID
    """
    trader = trading_manager.traders.get(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    success = await trader.resume()
    if success:
        return success_response(data={"paused": False}, message="交易已恢复")
    else:
        return error_response(code=500, message="恢复交易失败")
