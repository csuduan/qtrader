"""
目标仓位换仓 API 路由
所有操作通过 TradingManager 路由到 Trader
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel, Field

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.manager import TradingManager
from qtrader.models.po import TargetPosInstructionPo
from qtrader.utils.database import get_database
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/target-position", tags=["目标仓位换仓"])


class BatchRequest(BaseModel):
    """批量操作请求"""

    ids: list[int]


class TargetInstructionUpdate(BaseModel):
    """更新目标仓位指令请求"""

    enabled: bool | None = None
    status: str | None = None
    target_volume: int | None = Field(default=None, ge=0, description="目标手数")


def _query_target_from_db(account_id: str, trading_date: str | None = None) -> dict:
    """从数据库查询今日目标仓位差值指令（Trader 不可用时的回退）"""
    db = get_database()
    if not db:
        return error_response(code=500, message="数据库未初始化")

    if trading_date is None:
        trading_date = datetime.now().strftime("%Y%m%d")

    with db.get_session() as session:
        rows = (
            session.query(TargetPosInstructionPo)
            .filter(
                TargetPosInstructionPo.account_id == account_id,
                TargetPosInstructionPo.is_deleted.is_(False),
                TargetPosInstructionPo.trading_date == trading_date,
            )
            .order_by(TargetPosInstructionPo.id)
            .all()
        )

        # 注意：账户持仓必须从 Trader 网关内存获取（DB 异步落库会滞后）。
        # 此处为 Trader 不可用时的回退，无法拿到实时持仓，故 current_volume/deviation 置空，
        # 由前端显示 "-"。Trader 在线时走 trading_manager.get_target_instructions() 实时返回。
        instructions = []
        for r in rows:
            instructions.append(
                {
                    "id": r.id,
                    "account_id": r.account_id,
                    "strategy_id": r.strategy_id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "target_volume": r.target_volume,
                    "current_volume": None,
                    "initial_deviation": (r.volume if r.offset == "OPEN" else -r.volume),
                    "current_deviation": None,
                    "direction": r.direction,
                    "offset": r.offset,
                    "volume": r.volume,
                    "filled_volume": r.filled_volume,
                    "remaining_volume": r.remaining_volume,
                    "pending_volume": 0,
                    "price": float(r.price) if r.price else 0,
                    "trading_date": r.trading_date,
                    "plan_id": r.plan_id,
                    "enabled": r.enabled,
                    "status": r.status,
                    "current_order_id": r.current_order_id,
                    "order_placed_time": (
                        r.order_placed_time.isoformat() if r.order_placed_time else None
                    ),
                    "error_message": r.error_message,
                    "source": r.source,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
            )
        return {
            "instructions": instructions,
            "rotation_status": {"working": False, "is_manual": False},
        }


@router.get("")
async def get_target_instructions(
    account_id: str = Query(..., description="账户ID"),
    trading_date: str | None = Query(None, description="交易日筛选(yyyyMMdd)"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取目标仓位差值指令列表

    优先从 Trader 进程查询（仅今日），未连接时回退到数据库。

    - **account_id**: 账户ID
    - **trading_date**: 交易日筛选(格式yyyyMMdd)
    """
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        target_date = trading_date or today_str

        # 仅今日才向 Trader 查询
        if target_date == today_str:
            try:
                result = await trading_manager.get_target_instructions(account_id)
                if isinstance(result, dict):
                    return success_response(data=result, message="获取成功")
            except Exception as e:
                logger.warning(f"从Trader查询目标仓位指令失败，将回退到数据库: {e}")

        # 回退数据库
        data = _query_target_from_db(account_id, target_date)
        if isinstance(data, dict):
            return success_response(data=data, message="获取成功")
        return data
    except Exception as e:
        logger.error(f"获取目标仓位指令失败: {e}")
        return error_response(message=f"获取目标仓位指令失败: {str(e)}")


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_target_instructions(
    file: UploadFile = File(...),
    account_id: str = Form(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    导入目标仓位文件并生成差值指令

    CSV格式：account,stragegy,symbol,direction,volume
    例如：DQ,StrategyFix_A,A2611,Sell,2
    文件名需包含8位交易日，例如 TargetPos-DQ-20260811.csv

    - **account_id**: 账户ID
    - **file**: CSV 文件
    """
    try:
        content = await file.read()
        try:
            csv_text = content.decode("utf-8")
        except UnicodeDecodeError:
            csv_text = content.decode("gbk")
        result = await trading_manager.import_target_instructions(
            account_id, csv_text, file.filename
        )
        if result is None:
            return error_response(
                message="未连接到Trader或Trader未加载目标仓位模块（请确认Trader进程已重启并在运行）"
            )
        if result.get("errors"):
            return error_response(message=str(result["errors"][0]))
        return success_response(data=result, message="导入完成")
    except Exception as e:
        logger.error(f"导入目标仓位文件失败: {e}")
        return error_response(message=f"导入目标仓位文件失败: {str(e)}")


@router.post("/execute")
async def execute_target_position(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    执行目标仓位换仓（异步）

    - **account_id**: 账户ID
    """
    try:
        success = await trading_manager.execute_target_position(account_id)
        if not success:
            return error_response(code=500, message="启动目标仓位换仓失败")
        return success_response(data={}, message="目标仓位换仓已在后台启动")
    except Exception as e:
        logger.error(f"启动目标仓位换仓失败: {e}")
        return error_response(code=500, message=f"启动目标仓位换仓失败: {str(e)}")


@router.post("/stop")
async def stop_target_position(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止目标仓位换仓

    - **account_id**: 账户ID
    """
    try:
        success = await trading_manager.stop_target_position(account_id)
        if not success:
            return error_response(code=500, message="停止目标仓位换仓失败")
        return success_response(data={}, message="目标仓位换仓已停止")
    except Exception as e:
        logger.error(f"停止目标仓位换仓失败: {e}")
        return error_response(code=500, message=f"停止目标仓位换仓失败: {str(e)}")


def _db_delete_target_instructions(account_id: str, ids: list[int]) -> int:
    """DB 直连软删除（Trader 不可用时的回退）"""
    db = get_database()
    if not db or not ids:
        return 0
    with db.get_session() as session:
        count = (
            session.query(TargetPosInstructionPo)
            .filter(
                TargetPosInstructionPo.account_id == account_id,
                TargetPosInstructionPo.id.in_(ids),
            )
            .update({"is_deleted": True}, synchronize_session=False)
        )
    return int(count)


def _db_update_target_instruction(account_id: str, instruction_id: int, update_data: dict) -> bool:
    """DB 直连更新（Trader 不可用时的回退）"""
    db = get_database()
    if not db:
        return False
    with db.get_session() as session:
        inst = (
            session.query(TargetPosInstructionPo)
            .filter_by(id=instruction_id, account_id=account_id)
            .first()
        )
        if not inst:
            return False
        if "enabled" in update_data and update_data["enabled"] is not None:
            inst.enabled = bool(update_data["enabled"])
        if "status" in update_data and update_data["status"] is not None:
            inst.status = str(update_data["status"])
        if "target_volume" in update_data and update_data["target_volume"] is not None:
            inst.target_volume = int(update_data["target_volume"])
        inst.updated_at = datetime.now()
    return True


@router.post("/batch/delete")
async def batch_delete_target_instructions(
    request: BatchRequest,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    批量删除目标仓位指令（软删除）

    - **account_id**: 账户ID
    - **request**: {"ids": [指令ID...]}
    """
    try:
        result = await trading_manager.batch_delete_target_instructions(account_id, request.ids)
        if result is None:
            # 回退 DB 直连
            deleted = _db_delete_target_instructions(account_id, request.ids)
            if deleted == 0:
                return error_response(message="删除失败（未连接到Trader且数据库无匹配记录）")
            return success_response(data={"deleted": deleted}, message="删除成功")
        return success_response(data=result, message=f"删除成功 {result.get('deleted', 0)} 条")
    except Exception as e:
        logger.error(f"批量删除目标仓位指令失败: {e}")
        return error_response(message=f"批量删除目标仓位指令失败: {str(e)}")


@router.put("/{instruction_id}")
async def update_target_instruction(
    instruction_id: int,
    request: TargetInstructionUpdate,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    更新目标仓位指令（启用/禁用）

    - **account_id**: 账户ID
    - **instruction_id**: 指令ID
    """
    try:
        update_data = request.model_dump(exclude_unset=True)
        result = await trading_manager.update_target_instruction(
            account_id, instruction_id, update_data
        )
        if result is None:
            # 回退 DB 直连
            ok = _db_update_target_instruction(account_id, instruction_id, update_data)
            if not ok:
                return error_response(message="更新失败（未连接到Trader或指令不存在）")
            return success_response(message="更新成功")
        if result.get("error"):
            return error_response(message=str(result["error"]))
        return success_response(data=result, message="更新成功")
    except Exception as e:
        logger.error(f"更新目标仓位指令失败: {e}")
        return error_response(message=f"更新目标仓位指令失败: {str(e)}")
