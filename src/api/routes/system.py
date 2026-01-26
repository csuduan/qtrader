"""
系统控制API路由
"""
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Body, Request

from src.api.websocket_manager import websocket_manager
from src.api.dependencies import get_trading_engine, get_db_session
from src.api.responses import success_response, error_response
from src.api.schemas import SystemStatusRes
from src.models.po import JobPo
from src.trading_engine import TradingEngine
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["系统"])


@router.get("/status")
async def get_system_status(
    engine = Depends(get_trading_engine),
):
    """
    获取系统状态

    返回交易引擎的当前状态
    """
    engine_status = engine.get_status()
    return success_response(
        data=engine_status,
        message="获取成功"
    )


@router.get("/risk-control")
async def get_risk_control_status(
    engine:TradingEngine = Depends(get_trading_engine),
):
    """
    获取风控状态

    返回风控模块的当前状态和配置
    """
    risk_status = engine.risk_control.get_status()
    return success_response(data=risk_status, message="获取成功")


@router.put("/risk-control")
async def update_risk_control(
    max_daily_orders: Optional[int] = Body(default=None),
    max_daily_cancels: Optional[int] = Body(default=None),
    max_order_volume: Optional[int] = Body(default=None),
    max_split_volume: Optional[int] = Body(default=None),
    order_timeout: Optional[int] = Body(default=None),
    engine: TradingEngine = Depends(get_trading_engine),
):
    """
    更新风控参数

    - **max_daily_orders**: 单日最大报单次数
    - **max_daily_cancels**: 单日最大撤单次数
    - **max_order_volume**: 单笔最大报单手数
    - **max_split_volume**: 单笔最大拆单手数
    - **order_timeout**: 报单超时时间（秒）
    """
    logger.info(f"收到风控参数更新请求: max_daily_orders={max_daily_orders}, "
                f"max_daily_cancels={max_daily_cancels}, max_order_volume={max_order_volume}, "
                f"max_split_volume={max_split_volume}, order_timeout={order_timeout}")

    if max_daily_orders is not None:
        engine.risk_control.config.max_daily_orders = max_daily_orders

    if max_daily_cancels is not None:
        engine.risk_control.config.max_daily_cancels = max_daily_cancels

    if max_order_volume is not None:
        engine.risk_control.config.max_order_volume = max_order_volume

    if max_split_volume is not None:
        engine.risk_control.config.max_split_volume = max_split_volume

    if order_timeout is not None:
        engine.risk_control.config.order_timeout = order_timeout

    return success_response(
        data=engine.risk_control.get_status(),
        message="风控参数已更新"
    )


@router.post("/connect")
async def connect_system(
    engine = Depends(get_trading_engine),
):
    """
    连接到交易系统

    建立与TqSdk的连接
    """
    if engine.gateway.connected:
        return success_response(data={"connected": True}, message="已连接")

    success = engine.connect()

    if success:
        return success_response(data={"connected": True}, message="连接成功")
    else:
        return error_response(code=500, message="连接失败")


@router.post("/disconnect")
async def disconnect_system(
    engine = Depends(get_trading_engine),
):
    """
    断开交易系统连接

    关闭与TqSdk的连接
    """
    engine.disconnect()
    return success_response(data={"connected": False}, message="已断开连接")


@router.post("/pause")
async def pause_trading(
    engine = Depends(get_trading_engine),
):
    """
    暂停交易

    暂停自动交易功能，手动下单仍然可用
    """
    engine.pause()
    return success_response(data={"paused": True}, message="交易已暂停")


@router.post("/resume")
async def resume_trading(
    engine = Depends(get_trading_engine),
):
    """
    恢复交易

    恢复自动交易功能
    """
    engine.resume()
    return success_response(data={"paused": False}, message="交易已恢复")


@router.post("/log-monitoring/start")
async def start_log_monitoring(request: Request):
    """
    启动日志监控服务

    启动后，服务端会开始监控日志文件并向订阅了日志的WebSocket客户端推送日志
    """
    if websocket_manager.is_log_monitoring_enabled():
        return success_response(data={"enabled": True}, message="日志监控服务已在运行")

    log_watcher = request.app.state.log_watcher
    if log_watcher:
        log_watcher.start()
        websocket_manager.enable_log_monitoring()

    return success_response(data={"enabled": True}, message="日志监控服务已启动")


@router.post("/log-monitoring/stop")
async def stop_log_monitoring(request: Request):
    """
    停止日志监控服务

    停止后，服务端将不再向WebSocket客户端推送日志
    """
    if not websocket_manager.is_log_monitoring_enabled():
        return success_response(data={"enabled": False}, message="日志监控服务未在运行")

    log_watcher = request.app.state.log_watcher
    if log_watcher:
        log_watcher.stop()
        websocket_manager.disable_log_monitoring()

    return success_response(data={"enabled": False}, message="日志监控服务已停止")


@router.get("/log-monitoring/status")
async def get_log_monitoring_status():
    """
    获取日志监控服务状态

    返回日志监控服务是否正在运行
    """
    enabled = websocket_manager.is_log_monitoring_enabled()
    return success_response(data={"enabled": enabled}, message="获取成功")
