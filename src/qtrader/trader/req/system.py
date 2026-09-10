"""
系统参数、风控、告警配置请求处理
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from qtrader.trader.req.base import BaseReqHandler
from qtrader.utils.ipc import request
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.models.po import RotationInstructionPo

logger = get_logger(__name__)


class SystemReqHandler(BaseReqHandler):
    @request("list_system_params")
    async def _req_list_system_params(self, data: dict) -> list:
        """处理获取系统参数列表请求"""
        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        group = data.get("group")
        if db is None:
            return []

        with db.get_session() as session:
            query = session.query(SystemParamPo).filter(
                (SystemParamPo.account_id == self.account_id) | (SystemParamPo.account_id.is_(None))
            )

            if group:
                query = query.filter(SystemParamPo.group == group)

            params = query.order_by(SystemParamPo.group, SystemParamPo.param_key).all()

            return [
                {
                    "id": param.id,
                    "param_key": param.param_key,
                    "param_value": param.param_value,
                    "param_type": param.param_type,
                    "description": param.description,
                    "group": param.group,
                    "created_at": param.created_at.isoformat() if param.created_at else None,
                    "updated_at": param.updated_at.isoformat() if param.updated_at else None,
                }
                for param in params
            ]

    @request("get_system_param")
    async def _req_get_system_param(self, data: dict) -> dict | None:
        """处理获取单个系统参数请求"""
        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        param_key = data.get("param_key")
        if db is None:
            return None

        with db.get_session() as session:
            param = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.param_key == param_key,
                    (SystemParamPo.account_id == self.account_id)
                    | (SystemParamPo.account_id.is_(None)),
                )
                .first()
            )

            if param:
                return {
                    "id": param.id,
                    "param_key": param.param_key,
                    "param_value": param.param_value,
                    "param_type": param.param_type,
                    "description": param.description,
                    "group": param.group,
                    "updated_at": param.updated_at.isoformat() if param.updated_at else None,
                }
        return None

    @request("update_system_param")
    async def _req_update_system_param(self, data: dict) -> dict | None:
        """处理更新系统参数请求"""
        from datetime import datetime

        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        param_key = data.get("param_key")
        param_value = data.get("param_value")
        if db is None:
            return {"success": False, "message": "数据库未初始化"}

        with db.get_session() as session:
            param = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.param_key == param_key,
                    (SystemParamPo.account_id == self.account_id)
                    | (SystemParamPo.account_id.is_(None)),
                )
                .first()
            )

            if not param:
                return None

            param.param_value = param_value  # type: ignore[assignment]
            param.updated_at = datetime.now()  # type: ignore[assignment]

            session.commit()
            session.refresh(param)

            logger.info(f"Trader [{self.account_id}] 系统参数已更新: {param_key} = {param_value}")

            return {
                "id": param.id,
                "param_key": param.param_key,
                "param_value": param.param_value,
                "param_type": param.param_type,
                "description": param.description,
                "group": param.group,
                "updated_at": param.updated_at.isoformat() if param.updated_at else None,
            }

    @request("get_system_params_by_group")
    async def _req_get_system_params_by_group(self, data: dict) -> dict | None:
        """处理根据分组获取系统参数请求"""
        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        group = data.get("group")
        if db is None:
            return {}

        with db.get_session() as session:
            params = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.group == group,
                    (SystemParamPo.account_id == self.account_id)
                    | (SystemParamPo.account_id.is_(None)),
                )
                .all()
            )

            result = {param.param_key: param.param_value for param in params}
            return result

    @request("pause_trading")
    async def _req_pause_trading(self, data: dict) -> bool:
        """处理暂停交易请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return False
        self.trader.trading_engine.paused = True
        return True

    @request("resume_trading")
    async def _req_resume_trading(self, data: dict) -> bool:
        """处理恢复交易请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return False
        self.trader.trading_engine.paused = False
        return True

    @request("reload_risk_config")
    async def _req_reload_risk_config(self, data: dict) -> dict:
        """处理重载风控配置请求（从共享数据库重新读取）"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return {"success": False}
        # 热加载含同步DB查询，放入线程避免阻塞事件循环
        await asyncio.to_thread(self.trader.trading_engine.reload_risk_control_config)
        return {"success": True}

    @request("update_alert_wechat")
    async def _req_update_alert_wechat(self, data: dict) -> dict:
        """处理更新微信告警配置请求（已废弃，映射到通知告警开关）"""
        alert_wechat = data.get("alert_wechat", False)
        self.trader.account_config.alert.notification.enabled = alert_wechat
        logger.warning(
            f"Trader [{self.account_id}] update_alert_wechat 已废弃，请使用 update_alert_config"
        )
        logger.info(f"Trader [{self.account_id}] 通知告警已更新: enabled={alert_wechat}")
        return {"alert_wechat": alert_wechat}

    @request("get_alert_wechat")
    async def _req_get_alert_wechat(self, data: dict) -> dict:
        """处理获取微信告警配置请求（已废弃，映射到通知告警开关）"""
        logger.warning(
            f"Trader [{self.account_id}] get_alert_wechat 已废弃，请使用 get_alert_config"
        )
        return {"alert_wechat": self.trader.account_config.alert.notification.enabled}

    @request("update_alert_config")
    async def _req_update_alert_config(self, data: dict) -> dict:
        """
        处理更新告警配置请求

        data 结构（新）: {"notification": {...}, "exception": {...}}，
        两字段均可选，内部字段均可部分更新。
        """
        alert = self.trader.account_config.alert

        notification = data.get("notification") or {}
        if "enabled" in notification:
            alert.notification.enabled = bool(notification["enabled"])
        if notification.get("dnd_start") is not None:
            alert.notification.dnd_start = int(notification["dnd_start"])
        if notification.get("dnd_end") is not None:
            alert.notification.dnd_end = int(notification["dnd_end"])

        exception = data.get("exception") or {}
        if "enabled" in exception:
            alert.exception.enabled = bool(exception["enabled"])
        if exception.get("dnd_start") is not None:
            alert.exception.dnd_start = int(exception["dnd_start"])
        if exception.get("dnd_end") is not None:
            alert.exception.dnd_end = int(exception["dnd_end"])

        logger.info(
            f"Trader [{self.account_id}] 告警配置已更新: "
            f"notification(enabled={alert.notification.enabled}, "
            f"dnd={alert.notification.dnd_start}-{alert.notification.dnd_end}), "
            f"exception(enabled={alert.exception.enabled}, "
            f"dnd={alert.exception.dnd_start}-{alert.exception.dnd_end})"
        )
        return self._dump_alert_config(alert)

    @request("get_alert_config")
    async def _req_get_alert_config(self, data: dict) -> dict:
        """处理获取告警配置请求"""
        return self._dump_alert_config(self.trader.account_config.alert)

    @staticmethod
    def _dump_alert_config(alert) -> dict:
        """将 AlertConfig 序列化为可过 IPC 的字典"""
        return {
            "notification": {
                "enabled": alert.notification.enabled,
                "dnd_start": alert.notification.dnd_start,
                "dnd_end": alert.notification.dnd_end,
            },
            "exception": {
                "enabled": alert.exception.enabled,
                "dnd_start": alert.exception.dnd_start,
                "dnd_end": alert.exception.dnd_end,
            },
        }
