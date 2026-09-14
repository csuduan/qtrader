"""
目标仓位比对请求处理
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtrader.trader.req.base import BaseReqHandler
from qtrader.utils.ipc import request
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class TargetReqHandler(BaseReqHandler):
    @request("get_target_comparison")
    async def _req_get_target_comparison(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理获取目标仓位比对请求"""
        if self.trader.targetPos_manager is None:
            return {"trading_date": "", "comparisons": []}
        result: dict[str, Any] = self.trader.targetPos_manager.get_position_comparison()
        return result

    @request("import_target_instructions")
    async def _req_import_target_instructions(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理导入目标仓位文件请求（保存到目标仓位目录）"""
        if self.trader.targetPos_manager is None:
            return {"error": "Trader 未加载目标仓位模块"}
        csv_text = data.get("csv_text", "")
        filename = data.get("filename", "")
        if not csv_text or not filename:
            return {"error": "缺少 csv_text 或 filename"}
        try:
            result: dict[str, Any] = self.trader.targetPos_manager.import_target_file(
                csv_text, filename
            )
            return result
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception("Trader [{}] 导入目标仓位文件失败", self.account_id)
            return {"error": str(e)}

    @request("export_target_instructions")
    async def _req_export_target_instructions(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理导出换仓指令文件请求（按目标仓位偏差生成）"""
        if self.trader.targetPos_manager is None:
            return {"error": "Trader 未加载目标仓位模块"}
        try:
            result: dict[str, Any] = self.trader.targetPos_manager.export_instructions()
            return result
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception("Trader [{}] 导出换仓指令文件失败", self.account_id)
            return {"error": str(e)}

    @request("export_target_positions")
    async def _req_export_target_positions(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理导出目标仓位文件请求（按当前持仓生成）"""
        if self.trader.targetPos_manager is None:
            return {"error": "Trader 未加载目标仓位模块"}
        try:
            result: dict[str, Any] = self.trader.targetPos_manager.export_target_positions(
                strategy_id=data.get("strategy_id", "manual")
            )
            return result
        except Exception as e:
            logger.exception("Trader [{}] 导出目标仓位文件失败", self.account_id)
            return {"error": str(e)}

    @request("update_target_volume")
    async def _req_update_target_volume(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理手动更新目标手数请求"""
        if self.trader.targetPos_manager is None:
            return {"error": "Trader 未加载目标仓位模块"}
        symbol = data.get("symbol", "")
        side = data.get("side", "")
        target_volume = data.get("target_volume")
        if not symbol or not side:
            return {"error": "缺少 symbol 或 side"}
        try:
            result: dict[str, Any] = self.trader.targetPos_manager.update_target_volume(
                symbol, side, target_volume
            )
            return result
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.exception("Trader [{}] 更新目标手数失败", self.account_id)
            return {"error": str(e)}

    # ========== 系统参数请求处理 ==========
