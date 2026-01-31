"""
换仓指令相关API路由
所有操作通过TradingManager路由到Trader
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.core.trading_manager import TradingManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/rotation", tags=["换仓指令"])


class RotationInstructionResponse(BaseModel):
    """换仓指令响应"""

    id: int
    account_id: Optional[str] = None
    strategy_id: Optional[str] = None
    symbol: Optional[str] = None
    exchange_id: Optional[str] = None
    offset: Optional[str] = None
    direction: Optional[str] = None
    volume: Optional[int] = 0
    filled_volume: Optional[int] = 0
    price: Optional[float] = 0
    order_time: Optional[str] = None
    trading_date: Optional[str] = None
    enabled: bool
    status: Optional[str] = None
    attempt_count: int = 0
    remaining_attempts: int = 0
    remaining_volume: int = 0
    current_order_id: Optional[str] = None
    order_placed_time: Optional[datetime] = None
    last_attempt_time: Optional[datetime] = None
    error_message: Optional[str] = None
    source: Optional[str] = None
    is_deleted: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RotationInstructionCreate(BaseModel):
    """创建换仓指令请求"""

    account_id: str
    strategy_id: str
    symbol: str
    exchange_id: str
    offset: str
    direction: str
    volume: int
    price: float = 0
    order_time: Optional[str] = None
    trading_date: Optional[str] = None
    enabled: bool = True


class RotationInstructionUpdate(BaseModel):
    """更新换仓指令请求"""

    enabled: Optional[bool] = None
    status: Optional[str] = None
    filled_volume: Optional[int] = None


@router.get("")
async def get_rotation_instructions(
    account_id: str = Query(..., description="账户ID"),
    limit: int = Query(100, description="返回记录数量"),
    offset: int = Query(0, description="偏移量"),
    status: Optional[str] = Query(None, description="状态筛选"),
    enabled: Optional[bool] = Query(None, description="是否启用筛选"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取换仓指令列表

    - **account_id**: 账户ID
    - **limit**: 返回记录数量
    - **offset**: 偏移量
    - **status**: 状态筛选
    - **enabled**: 是否启用筛选
    """
    try:
        result = await trading_manager.get_rotation_instructions(
            account_id, limit=limit, offset=offset, status=status, enabled=enabled
        )
        if result is None:
            return success_response(data={"instructions": [], "rotation_status": {"working": False, "is_manual": False}, "total": 0, "limit": limit, "offset": offset}, message="获取成功")
        return success_response(data=result, message="获取成功")
    except Exception as e:
        logger.error(f"获取换仓指令列表失败: {e}")
        return error_response(message=f"获取换仓指令列表失败: {str(e)}")


@router.get("/{instruction_id}")
async def get_rotation_instruction(
    instruction_id: int,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取指定换仓指令

    - **account_id**: 账户ID
    - **instruction_id**: 指令ID
    """
    try:
        result = await trading_manager.get_rotation_instruction(account_id, instruction_id)
        if result is None:
            return error_response(code=404, message="换仓指令不存在")
        return success_response(data=result, message="获取成功")
    except Exception as e:
        logger.error(f"获取换仓指令失败: {e}")
        return error_response(message=f"获取换仓指令失败: {str(e)}")


@router.post("")
async def create_rotation_instruction(
    request: RotationInstructionCreate,
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    创建换仓指令
    """
    try:
        instruction_data = request.model_dump()
        result = await trading_manager.create_rotation_instruction(
            instruction_data["account_id"], instruction_data
        )
        if result is None:
            return error_response(message="创建换仓指令失败")
        return success_response(data=result, message="创建成功")
    except Exception as e:
        logger.error(f"创建换仓指令失败: {e}")
        return error_response(message=f"创建换仓指令失败: {str(e)}")


@router.put("/{instruction_id}")
async def update_rotation_instruction(
    instruction_id: int,
    request: RotationInstructionUpdate,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    更新换仓指令

    - **account_id**: 账户ID
    - **instruction_id**: 指令ID
    """
    try:
        update_data = request.model_dump(exclude_unset=True)
        result = await trading_manager.update_rotation_instruction(account_id, instruction_id, update_data)
        if result is None:
            return error_response(code=404, message="换仓指令不存在")
        return success_response(data=result, message="更新成功")
    except Exception as e:
        logger.error(f"更新换仓指令失败: {e}")
        return error_response(message=f"更新换仓指令失败: {str(e)}")


@router.delete("/{instruction_id}")
async def delete_rotation_instruction(
    instruction_id: int,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    删除换仓指令（软删除）

    - **account_id**: 账户ID
    - **instruction_id**: 指令ID
    """
    try:
        success = await trading_manager.delete_rotation_instruction(account_id, instruction_id)
        if not success:
            return error_response(code=404, message="换仓指令不存在")
        return error_response(code=204, message="删除成功")
    except Exception as e:
        logger.error(f"删除换仓指令失败: {e}")
        return error_response(message=f"删除换仓指令失败: {str(e)}")


@router.post("/clear")
async def clear_rotation_instructions(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    清除已完成换仓指令（软删除）

    - **account_id**: 账户ID
    """
    try:
        success = await trading_manager.clear_rotation_instructions(account_id)
        if not success:
            return error_response(message="清除失败")
        return error_response(code=204, message="清除成功")
    except Exception as e:
        logger.error(f"清除换仓指令失败: {e}")
        return error_response(message=f"清除换仓指令失败: {str(e)}")


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_rotation_instructions(
    file: UploadFile = File(...),
    mode: str = Form("append"),
    account_id: str = Form(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    批量导入换仓指令

    CSV格式：账户编号,策略编号,合约,开平,方向,手数,报单时间(可选)
    例如：DQ,StrategyFix_PK,PK603.CZC,Close,Sell,2,09:05:00

    文件名格式支持：yyyyMMdd_*.csv，用于提取交易日
    例如：20250115_rotation.csv，将提取交易日期为20250115

    - **account_id**: 账户ID
    - **file**: CSV文件
    - **mode**: 导入模式，append(追加) 或 replace(替换)
    """
    try:
        content = await file.read()
        csv_text = content.decode("gbk")
        result = await trading_manager.import_rotation_instructions(account_id, csv_text, file.filename, mode)
        if result is None:
            return error_response(message="导入失败")
        return success_response(data=result, message="导入完成")
    except Exception as e:
        logger.error(f"导入换仓指令失败: {e}")
        return error_response(message=f"导入换仓指令失败: {str(e)}")


class BatchRequest(BaseModel):
    """批量操作请求"""

    ids: List[int]


@router.post("/batch/execute")
async def batch_execute_instructions(
    request: BatchRequest,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    批量执行换仓指令

    - **account_id**: 账户ID
    - **request**: 包含指令ID列表的请求体
    """
    try:
        result = await trading_manager.batch_execute_instructions(account_id, request.ids)
        if result is None:
            return error_response(code=404, message="未找到任何换仓指令")
        return success_response(
            data=result,
            message=f"执行完成：成功 {result['success']} 条，失败 {result['failed']} 条",
        )
    except Exception as e:
        logger.error(f"批量执行换仓指令失败: {e}")
        return error_response(message=f"批量执行换仓指令失败: {str(e)}")


@router.post("/batch/delete")
async def batch_delete_instructions(
    request: BatchRequest,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    批量删除换仓指令（软删除）

    - **account_id**: 账户ID
    - **request**: 包含指令ID列表的请求体
    """
    try:
        result = await trading_manager.batch_delete_instructions(account_id, request.ids)
        if result is None:
            return error_response(message="删除失败")
        return success_response(data=result, message="删除成功")
    except Exception as e:
        logger.error(f"批量删除换仓指令失败: {e}")
        return error_response(message=f"批量删除换仓指令失败: {str(e)}")


@router.post("/start")
async def start_rotation(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    启动换仓流程（异步执行）

    - **account_id**: 账户ID
    """
    try:
        success = await trading_manager.execute_rotation(account_id)
        if not success:
            return error_response(code=500, message="启动换仓流程失败")
        return success_response(data={}, message="换仓流程已在后台启动")
    except Exception as e:
        logger.error(f"启动换仓流程失败: {e}")
        return error_response(code=500, message=f"启动换仓流程失败: {str(e)}")


@router.post("/close-all")
async def close_all_positions(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    一键平仓所有持仓

    - **account_id**: 账户ID
    """
    try:
        success = await trading_manager.close_all_positions(account_id)
        if not success:
            return error_response(code=500, message="一键平仓失败")
        return success_response(data={}, message="一键平仓已在后台启动")
    except Exception as e:
        logger.error(f"一键平仓失败: {e}")
        return error_response(code=500, message=f"一键平仓失败: {str(e)}")
