"""
目标仓位比对 API 路由
所有操作通过 TradingManager 路由到 Trader
"""

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from pydantic import BaseModel

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.manager import TradingManager
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/target-position", tags=["目标仓位比对"])


class UpdateTargetVolumeRequest(BaseModel):
    """更新目标手数请求"""

    symbol: str
    side: str
    target_volume: int | None = None


@router.get("")
async def get_target_comparison(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    获取目标仓位与当前账户持仓的比对结果

    扫描目标仓位文件（target_pos 目录）并在查询时与实时持仓比对，
    需 Trader 在线（持仓来自网关内存）。

    - **account_id**: 账户ID
    """
    try:
        result = await trading_manager.get_target_comparison(account_id)
        if result is None:
            return error_response(message="未连接到Trader，无法比对当前持仓")
        return success_response(data=result, message="获取成功")
    except Exception as e:
        logger.exception("获取目标仓位比对失败")
        return error_response(message=f"获取目标仓位比对失败: {e}")


@router.post("/import")
async def import_target_file(
    file: UploadFile = File(...),
    account_id: str = Form(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    导入目标仓位文件（保存到目标仓位目录，供比对扫描读取）

    CSV格式：account,stragegy,symbol,direction,volume
    例如：DQ,StrategyFix_A,A2611,Sell,2
    文件名需包含8位交易日与账户ID，例如 TargetPos-DQ-20260811.csv

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
            account_id, csv_text, file.filename or "upload.csv"
        )
        if result is None:
            return error_response(message="未连接到Trader，无法导入目标仓位文件")
        if result.get("error"):
            return error_response(message=str(result["error"]))
        return success_response(data=result, message="导入完成")
    except Exception as e:
        logger.exception("导入目标仓位文件失败")
        return error_response(message=f"导入目标仓位文件失败: {e}")


@router.post("/export")
async def export_target_instructions(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    按目标仓位与当前持仓的偏差导出换仓指令文件

    生成指令CSV并写入指令换仓扫描目录（switch_pos），
    由指令换仓流程自动扫描导入并执行。

    - **account_id**: 账户ID
    """
    try:
        result = await trading_manager.export_target_instructions(account_id)
        if result is None:
            return error_response(message="未连接到Trader，无法导出换仓指令文件")
        if result.get("error"):
            return error_response(message=str(result["error"]))
        if not result.get("exported"):
            return success_response(data=result, message="目标仓位与持仓无偏差，未生成指令文件")
        return success_response(
            data=result, message=f"已导出 {result['exported']} 条换仓指令：{result['file_name']}"
        )
    except Exception as e:
        logger.exception("导出换仓指令文件失败")
        return error_response(message=f"导出换仓指令文件失败: {e}")


@router.post("/export-positions")
async def export_target_positions(
    account_id: str = Query(..., description="账户ID"),
    strategy_id: str | None = Query(default="manual", description="策略ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    导出当前账户持仓为目标仓位文件

    默认导出所有持仓（多空两侧分别一行），
    写入 target_pos 目录，供后续比对或生成换仓指令。

    - **account_id**: 账户ID
    - **strategy_id**: 策略ID（默认 manual）
    """
    try:
        result = await trading_manager.export_target_positions(account_id, strategy_id or "manual")
        if result is None:
            return error_response(message="未连接到Trader，无法导出目标仓位文件")
        if result.get("error"):
            return error_response(message=str(result["error"]))
        if not result.get("exported"):
            return success_response(data=result, message="当前账户无持仓，未导出目标仓位文件")
        return success_response(
            data=result, message=f"已导出 {result['exported']} 条目标仓位：{result['file_name']}"
        )
    except Exception as e:
        logger.exception("导出目标仓位文件失败")
        return error_response(message=f"导出目标仓位文件失败: {e}")


@router.post("/update")
async def update_target_volume(
    request: UpdateTargetVolumeRequest,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    手动修改某合约某侧的目标手数

    修改结果写入 TargetPos-<账户>-<交易日>-edit.csv，
    并以最新修改时间参与目标仓位合并。target_volume 为空时表示删除该目标。

    - **account_id**: 账户ID
    - **symbol**: 合约代码
    - **side**: 侧（LONG/SHORT）
    - **target_volume**: 目标手数
    """
    try:
        result = await trading_manager.update_target_volume(
            account_id, request.symbol, request.side, request.target_volume
        )
        if result is None:
            return error_response(message="未连接到Trader，无法更新目标手数")
        if result.get("error"):
            return error_response(message=str(result["error"]))
        return success_response(data=result, message="目标手数已更新")
    except Exception as e:
        logger.exception("更新目标手数失败")
        return error_response(message=f"更新目标手数失败: {e}")
