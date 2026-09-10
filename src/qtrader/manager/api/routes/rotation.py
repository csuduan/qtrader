"""
换仓指令相关API路由
所有操作通过TradingManager路由到Trader
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.manager import TradingManager
from qtrader.models.po import RotationInstructionPo
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/rotation", tags=["换仓指令"])


class RotationInstructionResponse(BaseModel):
    """换仓指令响应"""

    id: int
    account_id: str | None = None
    strategy_id: str | None = None
    symbol: str | None = None
    exchange_id: str | None = None
    offset: str | None = None
    direction: str | None = None
    volume: int | None = 0
    filled_volume: int | None = 0
    pending_volume: int = 0
    price: float | None = 0
    order_time: str | None = None
    trading_date: str | None = None
    enabled: bool
    status: str | None = None
    attempt_count: int = 0
    remaining_attempts: int = 0
    remaining_volume: int = 0
    current_order_id: str | None = None
    order_placed_time: datetime | None = None
    last_attempt_time: datetime | None = None
    error_message: str | None = None
    source: str | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

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
    order_time: str | None = None
    trading_date: str | None = None
    enabled: bool = True


class RotationInstructionUpdate(BaseModel):
    """更新换仓指令请求"""

    enabled: bool | None = None
    status: str | None = None
    filled_volume: int | None = None
    direction: str | None = None
    offset: str | None = None
    volume: int | None = None


async def _query_rotation_from_db(
    account_id: str,
    limit: int,
    offset: int,
    status: str | None,
    enabled: bool | None,
    trading_date: str | None,
):
    """从数据库查询换仓指令列表"""
    from sqlalchemy import func, select

    from qtrader.utils.async_database import get_async_database

    db = get_async_database()
    if not db:
        return error_response(code=500, message="数据库未初始化")

    async with db.get_session() as session:
        stmt = select(RotationInstructionPo).filter(
            RotationInstructionPo.account_id == account_id,
            RotationInstructionPo.is_deleted.is_(False),
        )

        if status:
            stmt = stmt.filter(RotationInstructionPo.status == status)

        if enabled is not None:
            stmt = stmt.filter(RotationInstructionPo.enabled.is_(enabled))

        if trading_date is None:
            trading_date = datetime.now().strftime("%Y%m%d")
        stmt = stmt.filter(RotationInstructionPo.trading_date == trading_date)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar_one()

        instructions = (
            (
                await session.execute(
                    stmt.order_by(RotationInstructionPo.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

        data = [
            RotationInstructionResponse(
                id=inst.id,
                account_id=inst.account_id,
                strategy_id=inst.strategy_id,
                symbol=inst.symbol,
                exchange_id=(
                    inst.symbol.split(".")[-1] if inst.symbol and "." in inst.symbol else None
                ),
                offset=inst.offset,
                direction=inst.direction,
                volume=inst.volume,
                filled_volume=inst.filled_volume,
                pending_volume=0,
                price=float(inst.price) if inst.price else 0,
                order_time=inst.order_time,
                trading_date=inst.trading_date,
                enabled=inst.enabled,
                status=inst.status,
                attempt_count=inst.attempt_count,
                remaining_attempts=inst.remaining_attempts,
                remaining_volume=inst.remaining_volume,
                current_order_id=inst.current_order_id,
                order_placed_time=inst.order_placed_time,
                last_attempt_time=inst.last_attempt_time,
                error_message=inst.error_message,
                source=inst.source,
                is_deleted=inst.is_deleted,
                created_at=inst.created_at,
                updated_at=inst.updated_at,
            )
            for inst in instructions
        ]

        return {
            "instructions": [item.model_dump() for item in data],
            "rotation_status": {"working": False, "is_manual": False},
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.get("")
async def get_rotation_instructions(
    account_id: str = Query(..., description="账户ID"),
    limit: int = Query(100, description="返回记录数量"),
    offset: int = Query(0, description="偏移量"),
    status: str | None = Query(None, description="状态筛选"),
    enabled: bool | None = Query(None, description="是否启用筛选"),
    trading_date: str | None = Query(None, description="交易日筛选"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取换仓指令列表

    优先从Trader进程查询，未连接时回退到数据库查询。

    - **account_id**: 账户ID
    - **limit**: 返回记录数量
    - **offset**: 偏移量
    - **status**: 状态筛选
    - **enabled**: 是否启用筛选
    - **trading_date**: 交易日筛选(格式yyyyMMdd)
    """
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        target_date = trading_date or today_str

        # 优先从Trader查询（Trader只返回今日数据）
        trader_result = None
        if target_date == today_str:
            try:
                trader_result = await trading_manager.get_rotation_instructions(
                    account_id, limit, offset, status, enabled
                )
            except Exception as e:
                logger.warning(f"从Trader查询换仓指令失败，将回退到数据库: {e}")

        if trader_result is not None:
            instructions = trader_result.get("instructions", [])

            # 应用前端筛选条件（Trader内部可能未完全处理）
            if status:
                instructions = [i for i in instructions if i.get("status") == status]
            if enabled is not None:
                instructions = [i for i in instructions if i.get("enabled") == enabled]

            total = len(instructions)
            paginated = instructions[offset : offset + limit]

            # 补充缺失字段以兼容前端
            for item in paginated:
                symbol = item.get("symbol", "")
                item["exchange_id"] = symbol.split(".")[-1] if "." in symbol else None
                item["is_deleted"] = False

            result = {
                "instructions": paginated,
                "rotation_status": trader_result.get(
                    "rotation_status", {"working": False, "is_manual": False}
                ),
                "total": total,
                "limit": limit,
                "offset": offset,
            }
            return success_response(data=result, message="获取成功")

        # Trader未连接或查询非今日数据，回退到数据库
        result = await _query_rotation_from_db(
            account_id, limit, offset, status, enabled, trading_date
        )
        if isinstance(result, dict):
            return success_response(data=result, message="获取成功")
        return result
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
        from sqlalchemy import select

        from qtrader.utils.async_database import get_async_database

        db = get_async_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        async with db.get_session() as session:
            inst = await session.scalar(
                select(RotationInstructionPo).filter(
                    RotationInstructionPo.id == instruction_id,
                    RotationInstructionPo.account_id == account_id,
                    RotationInstructionPo.is_deleted.is_(False),
                )
            )

            if not inst:
                return error_response(code=404, message="换仓指令不存在")

            result = RotationInstructionResponse(
                id=inst.id,
                account_id=inst.account_id,
                strategy_id=inst.strategy_id,
                symbol=inst.symbol,
                exchange_id=(
                    inst.symbol.split(".")[-1] if inst.symbol and "." in inst.symbol else None
                ),
                offset=inst.offset,
                direction=inst.direction,
                volume=inst.volume,
                filled_volume=inst.filled_volume,
                price=float(inst.price) if inst.price else 0,
                order_time=inst.order_time,
                trading_date=inst.trading_date,
                enabled=inst.enabled,
                status=inst.status,
                attempt_count=inst.attempt_count,
                remaining_attempts=inst.remaining_attempts,
                remaining_volume=inst.remaining_volume,
                current_order_id=inst.current_order_id,
                order_placed_time=inst.order_placed_time,
                last_attempt_time=inst.last_attempt_time,
                error_message=inst.error_message,
                source=inst.source,
                is_deleted=inst.is_deleted,
                created_at=inst.created_at,
                updated_at=inst.updated_at,
            )

            return success_response(data=result.model_dump(), message="获取成功")
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
        result = await trading_manager.update_rotation_instruction(
            account_id, instruction_id, update_data
        )
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
        return success_response(message="删除成功")
    except Exception as e:
        logger.error(f"删除换仓指令失败: {e}")
        return error_response(message=f"删除换仓指令失败: {str(e)}")


@router.post("/clear")
async def clear_rotation_instructions(
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
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
        return success_response(message="清除成功")
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
        result = await trading_manager.import_rotation_instructions(
            account_id, csv_text, file.filename, mode
        )
        if result is None:
            return error_response(message="导入失败")
        return success_response(data=result, message="导入完成")
    except Exception as e:
        logger.error(f"导入换仓指令失败: {e}")
        return error_response(message=f"导入换仓指令失败: {str(e)}")


class BatchRequest(BaseModel):
    """批量操作请求"""

    ids: list[int]


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


@router.post("/stop")
async def stop_rotation(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止换仓流程

    - **account_id**: 账户ID
    """
    try:
        success = await trading_manager.stop_rotation(account_id)
        if not success:
            return error_response(code=500, message="停止换仓流程失败")
        return success_response(data={}, message="换仓流程已停止")
    except Exception as e:
        logger.error(f"停止换仓流程失败: {e}")
        return error_response(code=500, message=f"停止换仓流程失败: {str(e)}")


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
