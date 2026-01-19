"""
账户管理器
管理多个交易引擎实例，支持多账户并发运行
"""
from typing import Dict, List, Optional
from threading import Lock
import time

from src.config_loader import AppConfig, AccountConfig
from src.adapters.base import TradingAdapter
from src.adapters.tqsdk_adapter import TqSdkAdapter
from src.utils.logger import get_logger
from src.utils.event import event_engine, EventTypes

logger = get_logger(__name__)


class AccountManager:
    """账户管理器"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.engines: Dict[str, "TradingEngine"] = {}
        self._lock = Lock()
        self.event_engine = event_engine

    def initialize_all(self) -> bool:
        """初始化所有启用的账户"""
        success_count = 0

        for account_cfg in self.config.accounts:
            if not account_cfg.enabled:
                logger.info(f"账户 {account_cfg.account_id} 已禁用，跳过初始化")
                continue

            if self.create_engine(account_cfg):
                success_count += 1

        logger.info(f"成功初始化 {success_count}/{len(self.config.accounts)} 个账户")
        return success_count > 0

    def create_engine(self, account_cfg: AccountConfig) -> bool:
        """为单个账户创建交易引擎"""
        account_id = account_cfg.account_id

        with self._lock:
            if account_id in self.engines:
                logger.warning(f"账户 {account_id} 已存在，跳过创建")
                return False

            try:
                from src.trading_engine import TradingEngine

                temp_config = self._create_temp_config(account_cfg)
                engine = TradingEngine(temp_config)

                if engine.connect():
                    self._setup_event_forwarding(engine, account_id)
                    self.engines[account_id] = engine
                    logger.info(f"成功创建交易引擎: {account_id}")
                    return True
                else:
                    return False

            except Exception as e:
                logger.error(f"创建交易引擎失败 {account_id}: {e}", exc_info=True)
                return False

    def _create_temp_config(self, account_cfg: AccountConfig) -> AppConfig:
        """为单个账户创建临时配置"""
        from src.config_loader import AppConfig as AppCfg

        return AppCfg(
            tianqin=self.config.tianqin,
            account_type=account_cfg.account_type,
            account_id=account_cfg.account_id,
            trading_account=account_cfg.trading_account,
            paths=self.config.paths,
            risk_control=self.config.risk_control,
            market=self.config.market,
            api=self.config.api,
            trading=self.config.trading,
            scheduler=self.config.scheduler,
        )

    def _setup_event_forwarding(self, engine, account_id: str):
        """设置事件转发到全局事件引擎"""

        def forward_event(event_type: str):
            def handler(event):
                event.data["account_id"] = account_id
                self.event_engine.emit(event_type, event.data)
            return handler

        from src.utils.event import EventTypes

        engine.event_engine.register(EventTypes.ACCOUNT_UPDATE, forward_event(EventTypes.ACCOUNT_UPDATE))
        engine.event_engine.register(EventTypes.POSITION_UPDATE, forward_event(EventTypes.POSITION_UPDATE))
        engine.event_engine.register(EventTypes.TRADE_UPDATE, forward_event(EventTypes.TRADE_UPDATE))
        engine.event_engine.register(EventTypes.ORDER_UPDATE, forward_event(EventTypes.ORDER_UPDATE))

    def get_engine(self, account_id: str) -> Optional["TradingEngine"]:
        """获取指定账户的交易引擎"""
        return self.engines.get(account_id)

    def get_all_engines(self) -> Dict[str, "TradingEngine"]:
        """获取所有交易引擎"""
        return self.engines

    def get_enabled_account_ids(self) -> List[str]:
        """获取所有已启用账户ID"""
        return [
            acc.account_id
            for acc in self.config.accounts
            if acc.enabled and acc.account_id in self.engines
        ]

    def connect_account(self, account_id: str) -> bool:
        """连接指定账户"""
        engine = self.get_engine(account_id)
        if not engine:
            return False
        return engine.connect()

    def disconnect_account(self, account_id: str) -> bool:
        """断开指定账户"""
        engine = self.get_engine(account_id)
        if not engine:
            return False
        engine.disconnect()
        return False

    def get_account_status(self, account_id: str) -> Optional[dict]:
        """获取账户状态"""
        engine = self.get_engine(account_id)
        if not engine:
            return None

        return {
            "account_id": account_id,
            "connected": engine.connected,
            "paused": engine.paused,
            "account_type": engine.config.account_type,
            "cpu_usage": 0,
            "memory_usage": 0,
        }

    def get_all_account_status(self) -> List[dict]:
        """获取所有账户状态"""
        return [
            self.get_account_status(account_id)
            for account_id in self.get_enabled_account_ids()
        ]

    def shutdown_all(self):
        """关闭所有账户连接"""
        for account_id, engine in list(self.engines.items()):
            try:
                engine.disconnect()
                logger.info(f"已断开账户: {account_id}")
            except Exception as e:
                logger.error(f"断开账户失败 {account_id}: {e}")

        self.engines.clear()


account_manager: Optional[AccountManager] = None


def get_account_manager() -> Optional[AccountManager]:
    """获取全局账户管理器"""
    return account_manager
