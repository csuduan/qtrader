"""
系统控制API路由
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import SystemStatusRes
from src.manager.api.websocket_manager import websocket_manager
from src.manager.manager import TradingManager
from src.models.object import AccountData
from src.models.po import JobPo
from src.utils.config_loader import get_config_loader
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["系统"])


@router.get("/status")
async def get_system_status(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取系统状态

    返回交易引擎的当前状态
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        # trader未初始化（可能是禁用账户），返回默认状态
        return success_response(
            data={"account_id": account_id, "paused": False, "running": False}, message="获取成功"
        )

    engine_status = trader.get_status()
    return success_response(data=engine_status, message="获取成功")


@router.get("/risk-control")
async def get_risk_control_status(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取风控状态

    返回风控模块的当前状态和配置
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    account: AccountData = await trading_manager.get_account(account_id)
    return success_response(data=account.risk_status, message="获取成功")


@router.put("/risk-control")
async def update_risk_control(
    max_daily_orders: Optional[int] = Body(default=None),
    max_daily_cancels: Optional[int] = Body(default=None),
    max_order_volume: Optional[int] = Body(default=None),
    max_split_volume: Optional[int] = Body(default=None),
    order_timeout: Optional[int] = Body(default=None),
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    更新风控参数

    - **account_id**: 可选，指定账户ID（多账号模式）
    - **max_daily_orders**: 单日最大报单次数
    - **max_daily_cancels**: 单日最大撤单次数
    - **max_order_volume**: 单笔最大报单手数
    - **max_split_volume**: 单笔最大拆单手数
    - **order_timeout**: 报单超时时间（秒）
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    # 更新风控参数
    await trader.update_risk_control(
        max_daily_orders=max_daily_orders,
        max_daily_cancels=max_daily_cancels,
        max_order_volume=max_order_volume,
        max_split_volume=max_split_volume,
        order_timeout=order_timeout,
    )

    # 获取更新后的账户信息
    account = await trading_manager.get_account(account_id)
    return success_response(data=account.risk_status, message="风控参数已更新")


@router.put("/alert-wechat")
async def update_alert_wechat(
    alert_wechat: bool = Body(..., description="是否启用微信告警"),
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    更新微信告警配置（通过IPC发送给Trader进程）

    - **account_id**: 可选，指定账户ID（多账号模式）
    - **alert_wechat**: 是否启用微信告警
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    # 通过IPC发送到Trader进程
    success = await trader.update_alert_wechat(alert_wechat)
    if success:
        return success_response(data={"alert_wechat": alert_wechat}, message="微信告警配置已更新")
    else:
        return error_response(code=500, message="更新微信告警配置失败")


@router.get("/alert-wechat")
async def get_alert_wechat(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    获取微信告警配置（已废弃，请使用 /alert-config）

    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    # 通过IPC从Trader进程获取新的告警配置
    alert_config = await trader.get_alert_config()
    if alert_config is not None:
        # 兼容旧接口：返回 immediate 和 threshold 的或运算结果
        legacy_value = alert_config.get("immediate", False) or alert_config.get("threshold", False)
        return success_response(data={"alert_wechat": legacy_value}, message="获取成功（已废弃，请使用 /alert-config）")
    else:
        return error_response(code=500, message="获取告警配置失败")


@router.get("/alert-config")
async def get_alert_config(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    获取告警配置

    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    alert_config = await trader.get_alert_config()
    if alert_config is not None:
        return success_response(data=alert_config, message="获取成功")
    else:
        return error_response(code=500, message="获取告警配置失败")


@router.put("/alert-config")
async def update_alert_config(
    immediate: bool = Body(..., description="是否启用即时告警"),
    threshold: bool = Body(..., description="是否启用阈值告警"),
    threshold_count: Optional[int] = Body(None, description="阈值告警数量"),
    threshold_window: Optional[int] = Body(None, description="阈值告警时间窗口（秒）"),
    dnd_start: Optional[int] = Body(None, description="免打扰开始时间（小时，默认23点）"),
    dnd_end: Optional[int] = Body(None, description="免打扰结束时间（小时，默认次日8点）"),
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    更新告警配置

    - **account_id**: 可选，指定账户ID（多账号模式）
    - **immediate**: 是否启用即时告警（如Trader异常、连接断开等立即发送）
    - **threshold**: 是否启用阈值告警（异常日志达到阈值时发送）
    - **threshold_count**: 阈值告警数量，默认5
    - **threshold_window**: 阈值告警时间窗口（秒），默认300（5分钟）
    - **dnd_start**: 免打扰开始时间（小时，默认23点），此时间段内不发送即时告警
    - **dnd_end**: 免打扰结束时间（小时，默认次日8点）
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    config = {
        "immediate": immediate,
        "threshold": threshold,
    }
    if threshold_count is not None:
        config["threshold_count"] = threshold_count
    if threshold_window is not None:
        config["threshold_window"] = threshold_window
    if dnd_start is not None:
        config["dnd_start"] = dnd_start
    if dnd_end is not None:
        config["dnd_end"] = dnd_end

    success = await trader.update_alert_config(config)
    if success:
        return success_response(data=config, message="告警配置已更新")
    else:
        return error_response(code=500, message="更新告警配置失败")


@router.post("/connect")
async def connect_system(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    连接到交易系统

    建立与交易接口的连接
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    success = await trader.connect_gateway()

    if success:
        return success_response(data={"connected": True}, message="连接成功")
    else:
        return error_response(code=500, message="连接失败")


@router.post("/disconnect")
async def disconnect_system(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    断开交易系统连接

    关闭与交易接口的连接
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    await trader.disconnect_gateway()
    return success_response(data={"connected": False}, message="已断开连接")


@router.post("/disconnect/gateway")
async def disconnect_gateway(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    断开网关连接

    只断开网关连接，不停止trader进程
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    await trader.disconnect_gateway()
    return success_response(
        data={"md_connected": False, "td_connected": False}, message="已断开网关连接"
    )


@router.post("/trader/start")
async def start_trader(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    启动账户Trader

    启动指定账户的Trader进程
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    success = await trading_manager.start_trader(account_id)

    if success:
        return success_response(data={"running": True}, message="Trader已启动")
    else:
        return error_response(code=500, message="Trader启动失败")


@router.post("/trader/stop")
async def stop_trader(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    停止账户Trader

    停止指定账户的Trader进程
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    success = await trading_manager.stop_trader(account_id)

    if success:
        return success_response(data={"running": False}, message="Trader已停止")
    else:
        return error_response(code=500, message="Trader停止失败")


@router.get("/trader/status")
async def get_trader_status(
    account_id: Optional[str] = Query(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    获取Trader状态

    返回指定账户Trader的运行状态
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        # trader不存在（可能是禁用账户），返回默认状态
        return success_response(
            data={
                "account_id": account_id,
                "running": False,
                "alive": False,
                "created_process": False,
                "pid": None,
                "start_time": None,
                "last_heartbeat": None,
                "restart_count": 0,
                "socket_path": None,
            },
            message="获取成功",
        )

    status = trader.get_status()
    return success_response(data=status, message="获取成功")


@router.post("/pause")
async def pause_trading(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    暂停交易

    暂停自动交易功能，手动下单仍然可用
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    await trader.pause_trading()
    return success_response(data={"paused": True}, message="交易已暂停")


@router.post("/resume")
async def resume_trading(
    account_id: Optional[str] = Body(None, description="账户ID（多账号模式）"),
    trading_manager=Depends(get_trading_manager),
):
    """
    恢复交易

    恢复自动交易功能
    - **account_id**: 可选，指定账户ID（多账号模式）
    """
    trader = trading_manager.get_trader(account_id)

    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    await trader.resume_trading()
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


@router.get("/scheduler/jobs")
async def get_manager_scheduler_jobs(
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取Manager级别的定时任务列表

    返回Manager Scheduler中所有任务的状态和配置
    """
    jobs = trading_manager.get_manager_scheduler_jobs()
    return success_response(data={"tasks": jobs, "count": len(jobs)}, message="获取成功")


@router.post("/scheduler/jobs/{job_id}/operate")
async def operate_manager_scheduler_job(
    job_id: str,
    request: Request,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    操作Manager级别的定时任务

    - **job_id**: 任务ID
    - **action**: 操作类型（pause/resume/trigger）从请求体中获取
    """
    try:
        body = await request.json()
        action = body.get("action", "")
    except Exception:
        return error_response(code=400, message="请求体解析失败")

    success = trading_manager.operate_manager_scheduler_job(job_id, action)
    if success:
        action_text = "暂停" if action == "pause" else "恢复" if action == "resume" else "触发"
        return success_response(data={"job_id": job_id}, message=f"任务已{action_text}")
    return error_response(code=500, message="操作任务失败")


@router.put("/scheduler/jobs/{job_id}/toggle")
async def toggle_manager_scheduler_job(
    job_id: str,
    enabled: bool = Body(..., description="是否启用"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    切换Manager级别定时任务的启用状态

    - **job_id**: 任务ID
    - **enabled**: 是否启用
    """
    success = trading_manager.toggle_manager_scheduler_job(job_id, enabled)
    if success:
        return success_response(
            data={"job_id": job_id, "enabled": enabled}, message="任务状态已更新"
        )
    return error_response(code=500, message="更新任务状态失败")


@router.get("/manager/alert-config")
async def get_manager_alert_config():
    """
    获取Manager全局告警配置

    返回config.yaml中配置的alert配置
    """
    try:
        config_loader = get_config_loader()
        app_config = config_loader.load_config()
        alert_config = app_config.alert

        return success_response(
            data={
                "immediate": alert_config.immediate,
                "threshold": alert_config.threshold,
                "threshold_count": alert_config.threshold_count,
                "threshold_window": alert_config.threshold_window,
                "dnd_start": alert_config.dnd_start,
                "dnd_end": alert_config.dnd_end,
            },
            message="获取成功",
        )
    except Exception as e:
        logger.exception(f"获取Manager告警配置失败: {e}")
        return error_response(code=500, message=f"获取告警配置失败: {str(e)}")


@router.put("/manager/alert-config")
async def update_manager_alert_config(
    immediate: bool = Body(..., description="是否启用即时告警"),
    threshold: bool = Body(..., description="是否启用阈值告警"),
    threshold_count: Optional[int] = Body(None, description="阈值告警数量"),
    threshold_window: Optional[int] = Body(None, description="阈值告警时间窗口（秒）"),
    dnd_start: Optional[int] = Body(None, description="免打扰开始时间（小时，默认23点）"),
    dnd_end: Optional[int] = Body(None, description="免打扰结束时间（小时，默认次日8点）"),
):
    """
    更新Manager全局告警配置

    更新config.yaml中的alert配置
    - **immediate**: 是否启用即时告警（如Trader异常、连接断开等立即发送）
    - **threshold**: 是否启用阈值告警（异常日志达到阈值时发送）
    - **threshold_count**: 阈值告警数量，默认5
    - **threshold_window**: 阈值告警时间窗口（秒），默认300（5分钟）
    - **dnd_start**: 免打扰开始时间（小时，默认23点），此时间段内不发送即时告警
    - **dnd_end**: 免打扰结束时间（小时，默认次日8点）
    """
    try:
        import yaml
        from pathlib import Path

        config_loader = get_config_loader()
        app_config = config_loader.load_config()

        # 更新内存中的配置
        app_config.alert.immediate = immediate
        app_config.alert.threshold = threshold
        if threshold_count is not None:
            app_config.alert.threshold_count = threshold_count
        if threshold_window is not None:
            app_config.alert.threshold_window = threshold_window
        if dnd_start is not None:
            app_config.alert.dnd_start = dnd_start
        if dnd_end is not None:
            app_config.alert.dnd_end = dnd_end

        # 读取现有配置文件
        config_path = Path(config_loader.config_dir) / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # 更新alert配置
        config_data["alert"] = {
            "immediate": app_config.alert.immediate,
            "threshold": app_config.alert.threshold,
            "threshold_count": app_config.alert.threshold_count,
            "threshold_window": app_config.alert.threshold_window,
            "dnd_start": app_config.alert.dnd_start,
            "dnd_end": app_config.alert.dnd_end,
        }

        # 写回文件
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Manager告警配置已更新: immediate={immediate}, threshold={threshold}")

        return success_response(
            data={
                "immediate": app_config.alert.immediate,
                "threshold": app_config.alert.threshold,
                "threshold_count": app_config.alert.threshold_count,
                "threshold_window": app_config.alert.threshold_window,
                "dnd_start": app_config.alert.dnd_start,
                "dnd_end": app_config.alert.dnd_end,
            },
            message="告警配置已更新",
        )
    except Exception as e:
        logger.exception(f"更新Manager告警配置失败: {e}")
        return error_response(code=500, message=f"更新告警配置失败: {str(e)}")
