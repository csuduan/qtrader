"""
系统控制API路由
"""

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.api.schemas import SystemStatusRes
from qtrader.manager.manager import TradingManager
from qtrader.models.object import AccountData
from qtrader.models.po import JobPo, SystemParamPo
from qtrader.utils.config_loader import get_config_loader
from qtrader.utils.database import get_database
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/system", tags=["系统"])


def _upsert_risk_params(param_values: dict[str, int | None], account_id: str | None) -> None:
    """
    将风控参数写入 SystemParam 表（None 值跳过）

    Args:
        param_values: {参数键: 值}，键与 Trader 侧 _load_risk_control_config 读取的键一致
        account_id: 账户ID，None 表示全局参数
    """
    db = get_database()
    now = datetime.now()
    with db.get_session() as session:
        for key, value in param_values.items():
            if value is None:
                continue
            param = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.param_key == key,
                    (
                        SystemParamPo.account_id == account_id
                        if account_id
                        else SystemParamPo.account_id.is_(None)
                    ),
                )
                .first()
            )
            if param:
                param.param_value = str(value)
                param.updated_at = now
            else:
                session.add(
                    SystemParamPo(
                        param_key=key,
                        param_value=str(value),
                        param_type="int",
                        description="风控参数",
                        group="risk_control",
                        account_id=account_id,
                    )
                )


@router.get("/status")
async def get_system_status(
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
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
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
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
    max_daily_orders: int | None = Body(default=None),
    max_daily_cancels: int | None = Body(default=None),
    max_order_volume: int | None = Body(default=None),
    max_split_volume: int | None = Body(default=None),
    order_timeout: int | None = Body(default=None),
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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

    # 写入共享数据库的 SystemParam 表（与 Trader 侧 _load_risk_control_config 的读取键一致）
    param_values = {
        "risk_control.max_daily_orders": max_daily_orders,
        "risk_control.max_daily_cancels": max_daily_cancels,
        "risk_control.max_order_volume": max_order_volume,
        "risk_control.max_split_volume": max_split_volume,
        "risk_control.order_timeout": order_timeout,
    }
    try:
        import asyncio

        await asyncio.to_thread(_upsert_risk_params, param_values, account_id)
    except Exception as e:
        logger.exception(f"写入风控参数失败: {e}")
        return error_response(code=500, message="风控参数写入数据库失败")

    # 通知 Trader 进程重新加载风控配置
    await trader.reload_risk_config()

    # 获取更新后的账户信息
    account = await trading_manager.get_account(account_id)
    return success_response(data=account.risk_status, message="风控参数已更新")


@router.put("/alert-wechat")
async def update_alert_wechat(
    alert_wechat: bool = Body(..., description="是否启用微信告警"),
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
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
        return success_response(
            data={"alert_wechat": legacy_value}, message="获取成功（已废弃，请使用 /alert-config）"
        )
    else:
        return error_response(code=500, message="获取告警配置失败")


@router.post("/connect")
async def connect_system(
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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

    success = await trader.connect()

    if success:
        return success_response(data={"connected": True}, message="连接成功")
    else:
        return error_response(code=500, message="连接失败")


@router.post("/disconnect")
async def disconnect_system(
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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

    await trader.disconnect()
    return success_response(data={"connected": False}, message="已断开连接")


@router.post("/disconnect/gateway")
async def disconnect_gateway(
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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

    await trader.disconnect()
    return success_response(
        data={"md_connected": False, "td_connected": False}, message="已断开网关连接"
    )


@router.post("/trader/start")
async def start_trader(
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
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
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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

    await trader.pause()
    return success_response(data={"paused": True}, message="交易已暂停")


@router.post("/resume")
async def resume_trading(
    account_id: str | None = Body(None, description="账户ID（多账号模式）"),
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

    await trader.resume()
    return success_response(data={"paused": False}, message="交易已恢复")


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
    获取Manager全局告警配置（新结构）

    返回config.yaml中配置的alert配置（notification + exception）
    """
    try:
        config_loader = get_config_loader()
        app_config = config_loader.load_config()
        alert_config = app_config.alert

        # 新结构：notification + exception
        return success_response(
            data={
                "notification": {
                    "enabled": alert_config.notification.enabled,
                    "dnd_start": alert_config.notification.dnd_start,
                    "dnd_end": alert_config.notification.dnd_end,
                },
                "exception": {
                    "enabled": alert_config.exception.enabled,
                    "dnd_start": alert_config.exception.dnd_start,
                    "dnd_end": alert_config.exception.dnd_end,
                    "indicators": [
                        {
                            "name": ind.name,
                            "window": ind.window,
                            "threshold": ind.threshold,
                            "description": ind.description,
                        }
                        for ind in alert_config.exception.indicators
                    ],
                },
            },
            message="获取成功",
        )
    except Exception as e:
        logger.exception(f"获取Manager告警配置失败: {e}")
        return error_response(code=500, message=f"获取告警配置失败: {str(e)}")


class NotificationConfigUpdate(BaseModel):
    """通知告警配置更新（支持部分更新）"""

    enabled: bool
    dnd_start: int | None = None
    dnd_end: int | None = None


class ExceptionConfigUpdate(BaseModel):
    """异常告警配置更新（支持部分更新）"""

    enabled: bool
    dnd_start: int | None = None
    dnd_end: int | None = None


@router.put("/manager/alert-config")
async def update_manager_alert_config(
    notification: NotificationConfigUpdate = Body(..., description="通知告警配置"),
    exception: ExceptionConfigUpdate = Body(..., description="异常告警配置"),
):
    """
    更新Manager全局告警配置（新结构）

    更新config.yaml中的alert配置（notification + exception）
    - **notification.enabled**: 是否启用通知告警
    - **notification.dnd_start**: 免打扰开始时间（小时）
    - **notification.dnd_end**: 免打扰结束时间（小时）
    - **exception.enabled**: 是否启用异常告警
    - **exception.dnd_start**: 免打扰开始时间（小时）
    - **exception.dnd_end**: 免打扰结束时间（小时）
    """
    try:
        from pathlib import Path

        import yaml

        config_loader = get_config_loader()
        app_config = config_loader.load_config()

        # 更新内存中的配置（只更新传入的字段）
        app_config.alert.notification.enabled = notification.enabled
        if notification.dnd_start is not None:
            app_config.alert.notification.dnd_start = notification.dnd_start
        if notification.dnd_end is not None:
            app_config.alert.notification.dnd_end = notification.dnd_end

        app_config.alert.exception.enabled = exception.enabled
        if exception.dnd_start is not None:
            app_config.alert.exception.dnd_start = exception.dnd_start
        if exception.dnd_end is not None:
            app_config.alert.exception.dnd_end = exception.dnd_end

        # 读取现有配置文件
        config_path = Path(config_loader.config_dir) / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # 更新alert配置（新结构）
        config_data["alert"] = {
            "notification": {
                "enabled": app_config.alert.notification.enabled,
                "dnd_start": app_config.alert.notification.dnd_start,
                "dnd_end": app_config.alert.notification.dnd_end,
            },
            "exception": {
                "enabled": app_config.alert.exception.enabled,
                "dnd_start": app_config.alert.exception.dnd_start,
                "dnd_end": app_config.alert.exception.dnd_end,
                "indicators": [
                    {
                        "name": ind.name,
                        "window": ind.window,
                        "threshold": ind.threshold,
                        "description": ind.description,
                    }
                    for ind in app_config.alert.exception.indicators
                ],
            },
        }

        # 写回文件
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)

        logger.info(
            f"Manager告警配置已更新: notification={notification.enabled}, exception={exception.enabled}"
        )

        return success_response(
            data={
                "notification": {
                    "enabled": app_config.alert.notification.enabled,
                    "dnd_start": app_config.alert.notification.dnd_start,
                    "dnd_end": app_config.alert.notification.dnd_end,
                },
                "exception": {
                    "enabled": app_config.alert.exception.enabled,
                    "dnd_start": app_config.alert.exception.dnd_start,
                    "dnd_end": app_config.alert.exception.dnd_end,
                    "indicators": [
                        {
                            "name": ind.name,
                            "window": ind.window,
                            "threshold": ind.threshold,
                            "description": ind.description,
                        }
                        for ind in app_config.alert.exception.indicators
                    ],
                },
            },
            message="告警配置已更新",
        )
    except Exception as e:
        logger.exception(f"更新Manager告警配置失败: {e}")
        return error_response(code=500, message=f"更新告警配置失败: {str(e)}")
