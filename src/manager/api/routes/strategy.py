"""
策略管理API路由
提供策略CRUD、启停、参数配置接口
所有操作通过TradingManager路由到Trader
"""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import (
    StrategyBatchOpReq,
    StrategyConfig,
    StrategyRes,
    StrategyStatusRes,
    StrategyUpdateReq,
)
from src.manager.manager import TradingManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["策略管理"])


# ============ 辅助函数 ============


def _handle_trader_not_found(account_id: str):
    """处理Trader未找到的情况"""
    logger.warning(f"Trader [{account_id}] 未找到或未连接")
    raise HTTPException(status_code=404, detail=f"Trader [{account_id}] 未找到或未连接")


def _handle_strategy_error(operation: str, strategy_id: str, error: Exception):
    """处理策略操作错误"""
    logger.error(f"{operation}策略 [{strategy_id}] 失败: {error}")
    raise HTTPException(status_code=500, detail=f"{operation}策略失败: {str(error)}")


@router.get("")
async def list_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取策略列表

    Args:
        account_id: 账户ID

    Returns:
        List[StrategyRes]: 策略状态列表
    """
    try:
        strategies = await trading_manager.list_strategies(account_id)
        return success_response(data=strategies)
    except Exception as e:
        logger.error(f"获取策略列表失败: {e}")
        return error_response(message=f"获取策略列表失败: {str(e)}")


@router.get("/{strategy_id}")
async def get_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取指定策略状态

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        StrategyRes: 策略状态
    """
    try:
        result = await trading_manager.get_strategy(account_id, strategy_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略状态失败: {e}")
        return error_response(message=f"获取策略状态失败: {str(e)}")


@router.post("/{strategy_id}/start")
async def start_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    启动指定策略

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.start_strategy(account_id, strategy_id)
        if success:
            return success_response(message=f"策略 {strategy_id} 启动成功")
        else:
            raise HTTPException(status_code=400, detail=f"启动策略失败: {strategy_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动策略失败: {e}")
        return error_response(message=f"启动策略失败: {str(e)}")


@router.post("/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止指定策略

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.stop_strategy(account_id, strategy_id)
        if success:
            return success_response(message=f"策略 {strategy_id} 停止成功")
        else:
            raise HTTPException(status_code=400, detail=f"停止策略失败: {strategy_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"停止策略失败: {e}")
        return error_response(message=f"停止策略失败: {str(e)}")


@router.post("/start-all")
async def start_all_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    启动所有已启用的策略

    Args:
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.start_all_strategies(account_id)
        if success:
            return success_response(message="已启动所有策略")
        else:
            return error_response(message="启动策略失败")
    except Exception as e:
        logger.error(f"启动策略失败: {e}")
        return error_response(message=f"启动策略失败: {str(e)}")


@router.post("/stop-all")
async def stop_all_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止所有策略

    Args:
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.stop_all_strategies(account_id)
        if success:
            return success_response(message="已停止所有策略")
        else:
            return error_response(message="停止策略失败")
    except Exception as e:
        logger.error(f"停止策略失败: {e}")
        return error_response(message=f"停止策略失败: {str(e)}")


@router.post("/batch")
async def batch_operate_strategies(
    request: StrategyBatchOpReq,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    批量操作策略

    Args:
        request: 批量操作请求
        account_id: 账户ID

    Returns:
        操作结果，包含成功和失败的策略列表
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        results = {"success": [], "failed": []}

        for strategy_id in request.strategy_ids:
            try:
                if request.operation == "start":
                    success = await trading_manager.start_strategy(account_id, strategy_id)
                elif request.operation == "stop":
                    success = await trading_manager.stop_strategy(account_id, strategy_id)
                elif request.operation == "restart":
                    await trading_manager.stop_strategy(account_id, strategy_id)
                    await asyncio.sleep(0.5)
                    success = await trading_manager.start_strategy(account_id, strategy_id)
                else:
                    raise HTTPException(
                        status_code=400, detail=f"不支持的操作类型: {request.operation}"
                    )

                if success:
                    results["success"].append(strategy_id)
                else:
                    results["failed"].append({"id": strategy_id, "reason": "操作失败"})
            except Exception as e:
                results["failed"].append({"id": strategy_id, "reason": str(e)})

        return success_response(
            data=results,
            message=f"批量{request.operation}完成: 成功{len(results['success'])}个, 失败{len(results['failed'])}个",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量操作策略失败: {e}")
        return error_response(message=f"批量操作策略失败: {str(e)}")


@router.patch("/{strategy_id}")
async def update_strategy(
    strategy_id: str,
    request: StrategyUpdateReq,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    更新策略参数或信号

    Args:
        strategy_id: 策略ID
        request: 更新请求
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        # 更新策略参数
        params = request.params
        if params:
            result = await trader.update_strategy_params(strategy_id, params)
            if not result.get("success"):
                return error_response(message=result.get("message", "更新参数失败"))

        # 如果需要重启策略
        if request.restart:
            await trading_manager.stop_strategy(account_id, strategy_id)
            await asyncio.sleep(0.5)
            await trading_manager.start_strategy(account_id, strategy_id)

        return success_response(message=f"策略 {strategy_id} 参数更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新策略参数失败: {e}")
        return error_response(message=f"更新策略参数失败: {str(e)}")


@router.post("/{strategy_id}/update-signal")
async def update_strategy_signal(
    strategy_id: str,
    signal: dict = Body(..., description="信号数据"),
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    更新策略信号

    Args:
        strategy_id: 策略ID
        signal: 信号数据
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.update_strategy_signal(strategy_id, signal)
        if not result.get("success"):
            return error_response(message=result.get("message", "更新信号失败"))

        return success_response(message=f"策略 {strategy_id} 信号更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新策略信号失败: {e}")
        return error_response(message=f"更新策略信号失败: {str(e)}")


@router.get("/{strategy_id}/status")
async def get_strategy_status(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> StrategyStatusRes:
    """
    获取策略详细状态

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        StrategyStatusRes: 策略状态
    """
    try:
        result = await trading_manager.get_strategy(account_id, strategy_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
        return StrategyStatusRes(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取策略状态失败: {str(e)}")


@router.get("/{strategy_id}/params")
async def get_strategy_params(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取策略参数（用于前端显示）
    - params_file: 参数文件路径（默认显示）
    - params: 详细参数字典（悬浮显示）
    - summary: 关键参数摘要

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        StrategyParamsRes: 策略参数
    """
    try:
        from src.manager.api.schemas import StrategyParamsRes

        result = await trading_manager.get_strategy(account_id, strategy_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")

        config = result.get("config", {})
        params = result.get("params", {})

        # 构建关键参数摘要
        summary = {}
        if "symbol" in params:
            summary["symbol"] = params["symbol"]
        if "volume_per_trade" in params:
            summary["volume"] = params["volume_per_trade"]
        if "take_profit_pct" in params:
            summary["tp"] = params["take_profit_pct"]
        if "stop_loss_pct" in params:
            summary["sl"] = params["stop_loss_pct"]

        params_res = StrategyParamsRes(
            strategy_id=strategy_id,
            params_file=config.get("params_file"),
            params=params,
            summary=summary,
        )
        return success_response(data=params_res.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略参数失败: {e}")
        return error_response(message=f"获取策略参数失败: {str(e)}")


@router.post("/replay-all")
async def replay_all_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    回播所有有效策略行情

    流程：
    1. 暂停所有策略交易，暂停接收实时tick、bar推送
    2. 执行每个策略初始化方法
    3. 从网关获取kline
    4. 从kline中选出当前交易日的bar(按时间排序)
    5. 循环调用on_bar()
    6. 恢复策略交易，接收实时tick、bar推送

    Args:
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        # 通过trading_manager获取trader
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        # 通过socket发送回播请求到Trader进程
        response = await trader.send_request(
            "replay_all_strategies", {}, timeout=120.0  # 回播可能需要较长时间
        )

        if response is None:
            return error_response(message="回播请求失败：无响应")

        if isinstance(response, dict) and response.get("success"):
            return success_response(
                message=f"回播完成", data={"replayed_count": response.get("replayed_count", 0)}
            )
        else:
            error_msg = (
                response.get("message", "回播失败") if isinstance(response, dict) else "回播失败"
            )
            return error_response(message=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回播策略失败: {e}")
        return error_response(message=f"回播策略失败: {str(e)}")


@router.post("/{strategy_id}/trading-status")
async def set_strategy_trading_status(
    strategy_id: str,
    request: dict = Body(..., description="交易状态设置"),
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    设置策略交易状态（统一接口）

    支持同时设置开仓和平仓状态：
    - opening_paused: 暂停/恢复开仓
    - closing_paused: 暂停/恢复平仓

    Args:
        strategy_id: 策略ID
        request: {"opening_paused": boolean, "closing_paused": boolean}
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.set_strategy_trading_status(strategy_id, request)
        if result.get("success"):
            # 构建详细的成功消息
            changes = []
            if "opening_paused" in request:
                status = "暂停" if request["opening_paused"] else "恢复"
                changes.append(f"开仓已{status}")
            if "closing_paused" in request:
                status = "暂停" if request["closing_paused"] else "恢复"
                changes.append(f"平仓已{status}")
            message = f"策略 {strategy_id} " + ", ".join(changes) + "成功"
            return success_response(message=message, data=result.get("data"))
        else:
            return error_response(message=result.get("message", "设置交易状态失败"))
    except Exception as e:
        logger.error(f"设置策略交易状态失败: {e}")
        return error_response(message=f"设置交易状态失败: {str(e)}")


@router.post("/{strategy_id}/enable")
async def enable_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """启用策略"""
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.enable_strategy(strategy_id)
        if result.get("success"):
            return success_response(message=f"策略 {strategy_id} 启用成功")
        else:
            return error_response(message=result.get("message", "启用策略失败"))
    except Exception as e:
        logger.error(f"启用策略失败: {e}")
        return error_response(message=f"启用策略失败: {str(e)}")


@router.post("/{strategy_id}/disable")
async def disable_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """禁用策略"""
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.disable_strategy(strategy_id)
        if result.get("success"):
            return success_response(message=f"策略 {strategy_id} 禁用成功")
        else:
            return error_response(message=result.get("message", "禁用策略失败"))
    except Exception as e:
        logger.error(f"禁用策略失败: {e}")
        return error_response(message=f"禁用策略失败: {str(e)}")


@router.post("/{strategy_id}/reload-params")
async def reload_strategy_params(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    重载策略参数
    从配置文件重新加载策略参数
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.reload_strategy_params(strategy_id)
        if result.get("success"):
            return success_response(message=f"策略 {strategy_id} 参数重载成功", data=result.get("params"))
        else:
            return error_response(message=result.get("message", "重载参数失败"))
    except Exception as e:
        logger.error(f"重载策略参数失败: {e}")
        return error_response(message=f"重载参数失败: {str(e)}")


@router.post("/{strategy_id}/init")
async def init_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    初始化策略
    调用策略的 init() 方法
    """
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.init_strategy(strategy_id)
        if result.get("success"):
            return success_response(message=f"策略 {strategy_id} 初始化成功")
        else:
            return error_response(message=result.get("message", "初始化策略失败"))
    except Exception as e:
        logger.error(f"初始化策略失败: {e}")
        return error_response(message=f"初始化策略失败: {str(e)}")


@router.get("/{strategy_id}/order-cmds")
async def get_strategy_order_cmds(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    status: Optional[str] = Query(None, description="状态过滤: active/finished"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """获取策略的报单指令历史"""
    try:
        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        result = await trader.get_strategy_order_cmds(strategy_id, status)
        if result is not None:
            return success_response(data=result)
        else:
            return error_response(message="获取报单指令失败")
    except Exception as e:
        logger.error(f"获取策略报单指令失败: {e}")
        return error_response(message=f"获取报单指令失败: {str(e)}")


@router.post("/{strategy_id}/send-order-cmd")
async def send_strategy_order_cmd(
    strategy_id: str,
    request: dict = Body(..., description="订单指令数据"),
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    发送策略报单指令

    通过策略的 send_order_cmd 方法发送订单指令

    Args:
        strategy_id: 策略ID
        request: {
            "symbol": "合约代码",
            "direction": "BUY/SELL",
            "offset": "OPEN/CLOSE/CLOSETODAY",
            "volume": 手数,
            "price": 目标价格 (0表示市价)
        }
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        from src.models.object import Direction, Offset

        trader = trading_manager.get_trader(account_id)
        if not trader:
            _handle_trader_not_found(account_id)

        # 验证请求参数
        symbol = request.get("symbol")
        direction = request.get("direction")
        offset = request.get("offset")
        volume = request.get("volume")
        price = request.get("price", 0)

        if not all([symbol, direction, offset, volume is not None]):
            return error_response(message="缺少必要参数: symbol, direction, offset, volume")

        # 验证方向
        if direction not in ["BUY", "SELL"]:
            return error_response(message="direction 必须是 BUY 或 SELL")

        # 验证开平
        if offset not in ["OPEN", "CLOSE", "CLOSETODAY"]:
            return error_response(message="offset 必须是 OPEN, CLOSE 或 CLOSETODAY")

        # 验证手数
        try:
            volume = int(volume)
            if volume <= 0:
                return error_response(message="volume 必须大于0")
        except (ValueError, TypeError):
            return error_response(message="volume 必须是整数")

        # 验证价格
        try:
            price = float(price) if price is not None else 0
        except (ValueError, TypeError):
            return error_response(message="price 必须是数字")

        # 构造订单指令
        from src.trader.order_cmd import OrderCmd

        order_cmd = OrderCmd(
            symbol=symbol,
            direction=Direction(direction),
            offset=Offset(offset),
            volume=volume,
            price=price,
            source=f"手动-{strategy_id}",
        )

        # 发送到Trader进程
        result = await trader.send_request(
            "send_strategy_order_cmd",
            {"strategy_id": strategy_id, "order_cmd": order_cmd.to_dict()},
            timeout=10.0,
        )

        if result and result.get("success"):
            return success_response(message=f"策略 {strategy_id} 报单指令已发送", data={"cmd_id": order_cmd.cmd_id})
        else:
            return error_response(message=result.get("message", "发送报单指令失败") if result else "发送报单指令失败")

    except Exception as e:
        logger.error(f"发送策略报单指令失败: {e}")
        return error_response(message=f"发送报单指令失败: {str(e)}")
