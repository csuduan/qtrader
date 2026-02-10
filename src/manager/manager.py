"""
交易管理器
负责管理多个Trader（独立进程模式），提供API服务
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.manager.trader_proxy import TraderProxy
from src.models.object import AccountData, Direction, Offset, OrderData, OrderRequest
from src.utils.config_loader import AccountConfig, DatabaseConfig, SocketConfig
from src.utils.logger import get_logger
from src.utils.scheduler import TaskScheduler

logger = get_logger(__name__)


class _GlobalConfigAdapter:
    """
    将全局配置适配为AppConfig接口的适配器类
    用于TraderProxy等期望AppConfig的组件
    """

    def __init__(self, socket_config: SocketConfig):
        self._socket_config = socket_config

    @property
    def socket(self):
        return self._socket_config

    @property
    def api(self):
        from src.utils.config_loader import ApiConfig

        return ApiConfig()

    @property
    def paths(self):
        from src.utils.config_loader import PathsConfig

        return PathsConfig()

    @property
    def trading(self):
        from src.utils.config_loader import TradingConfig

        return TradingConfig()

    @property
    def risk_control(self):
        from src.utils.config_loader import RiskControlConfig

        return RiskControlConfig()

    @property
    def scheduler(self):
        from src.utils.config_loader import SchedulerConfig

        return SchedulerConfig()


class TradingManager:
    """
    交易管理器

    职责：
    1. 启动/停止/重启 Trader（独立进程模式）
    2. 进程健康检查和自动重启
    3. 事件处理和分发（通过ManagerEventEngine）
    4. API 服务集成（查询Trader获取数据）

    运行模式：
    - standalone: 独立模式，Trader作为独立进程运行，Trader作为Socket服务器
    """

    def __init__(self, account_configs: List[AccountConfig]):
        """
        初始化交易管理器

        Args:
            account_configs: 账户配置列表
        """
        self.account_configs = account_configs
        self.account_configs_map: Dict[str, AccountConfig] = {
            acc.account_id: acc for acc in account_configs if acc.account_id is not None
        }

        # 使用默认的 Socket 和 Database 配置（从全局配置获取）
        self.socket_config = SocketConfig()
        self.database_config = DatabaseConfig()

        # 创建全局配置适配器（用于传递给TraderProxy）
        self._global_config_adapter = _GlobalConfigAdapter(self.socket_config)

        # Socket目录（独立模式的Trader进程会创建socket文件）
        socket_dir = self.socket_config.socket_dir
        Path(socket_dir).mkdir(parents=True, exist_ok=True)

        # Trader Proxy 实例（独立模式）
        self.traders: Dict[str, TraderProxy] = {}

        # 运行状态
        self._running = False
        self._health_check_running = False
        self._health_check_task: Optional[asyncio.Task] = None

        logger.info("交易管理器初始化完成")

    # ==================== Trader Proxy管理 ====================
    async def create_trader(self, account_id) -> bool:
        """
        创建指定账户的Trader Proxy
        Args:
            account_id: 账户ID

        Returns:
            是否创建成功
        """

        account_config = self.account_configs_map.get(account_id)
        if not account_config:
            logger.error(f"未找到账号 [{account_id}] 的配置")
            return False

        # 立即创建Trader Proxy并添加到traders字典（禁用的账户也会创建）
        socket_dir_abs = Path(self.socket_config.socket_dir).expanduser().resolve()
        socket_path = str(socket_dir_abs / f"qtrader_{account_id}.sock")

        trader = TraderProxy(
            account_config=account_config,
            global_config=self._global_config_adapter,
            socket_path=socket_path,
            heartbeat_timeout=self.socket_config.heartbeat_timeout,
        )
        self.traders[account_id] = trader
        logger.info(
            f"Trader Proxy [{account_id}] 初始化完成（enabled: {account_config.enabled}, auto_start: {account_config.auto_start}）"
        )
        return True

    async def start_trader(self, account_id: str) -> bool:
        """
        启动指定Trader（独立进程模式）

        Args:
            account_id: 账户ID

        Returns:
            是否启动成功
        """

        # 启动Trader Proxy（会自动检测进程是否已存在）
        try:
            trader = self.traders.get(account_id)
            if not trader:
                logger.error(f"Trader Proxy [{account_id}] 未初始化")
                return False

            success = await trader.start()
            if success:
                logger.info(f"Trader Proxy [{account_id}] 启动成功")

            return success

        except Exception as e:
            logger.error(f"启动Trader Proxy [{account_id}] 失败: {e}")
            return False

    async def stop_trader(self, account_id: str) -> bool:
        """
        停止指定Trader

        Args:
            account_id: 账户ID

        Returns:
            是否停止成功
        """
        trader = self.traders.get(account_id)
        if not trader:
            logger.warning(f"Trader [{account_id}] 未运行")
            return False

        try:
            # 停止Trader（只停止自己创建的子进程）
            success = await trader.stop()
            logger.info(f"Trader [{account_id}] 已停止")
            return success

        except Exception as e:
            logger.error(f"停止Trader [{account_id}] 失败: {e}")
            return False

    async def restart_trader(self, account_id: str) -> bool:
        """
        重启指定Trader

        Args:
            account_id: 账户ID

        Returns:
            是否重启成功
        """
        trader = self.traders.get(account_id)
        if not trader:
            logger.warning(f"Trader [{account_id}] 未运行，无法重启")
            return False

        # 获取配置信息
        account_config = self.account_configs_map.get(account_id)
        if account_config is None:
            logger.warning(f"未找到账号 [{account_id}] 的配置")
            return False

        # 停止
        await self.stop_trader(account_id)

        # 等待一秒
        await asyncio.sleep(1)

        # 启动
        return await self.start_trader(account_id)

    def is_running(self, account_id: str) -> bool:
        """
        检查Trader是否运行

        Args:
            account_id: 账户ID

        Returns:
            是否运行
        """
        trader = self.traders.get(account_id)
        if trader:
            return trader.is_running()
        return False

    def get_trader_status(self, account_id: str) -> Optional[Dict]:
        """
        获取Trader状态

        Args:
            account_id: 账户ID

        Returns:
            状态字典
        """
        trader = self.traders.get(account_id)
        if trader:
            return trader.get_status()
        return None

    def get_all_trader_status(self) -> List[Dict]:
        """
        获取所有Trader状态

        Returns:
            状态列表
        """
        statuses = []
        for trader in self.traders.values():
            statuses.append(trader.get_status())
        return statuses

    # ==================== 交易接口 ====================

    async def send_order_request(
        self,
        account_id: str,
        symbol: str,
        direction: Direction,
        offset: Offset,
        volume: int,
        price: float = 0,
    ) -> Optional[str]:
        """
        发送下单请求到指定Trader

        Args:
            account_id: 账户ID
            symbol: 合约代码
            direction: 方向
            offset: 开平
            volume: 数量
            price: 价格（0=市价）

        Returns:
            订单ID，失败返回None
        """
        trader = self.traders.get(account_id)
        if not trader:
            logger.error(f"Trader [{account_id}] 不存在")
            return None

        return await trader.send_order_request(symbol, direction.value, offset.value, volume, price)

    async def send_cancel_request(self, account_id: str, order_id: str) -> bool:
        """
        发送撤单请求到指定Trader

        Args:
            account_id: 账户ID
            order_id: 订单ID

        Returns:
            是否成功
        """
        trader = self.traders.get(account_id)
        if not trader:
            logger.error(f"Trader [{account_id}] 不存在")
            return False

        return await trader.send_cancel_request(order_id)

    # ==================== TaskScheduler ====================

    def get_task_scheduler(self, account_id: str) -> Optional[TaskScheduler]:
        """
        获取指定Trader的任务调度器

        Args:
            account_id: 账户ID

        Returns:
            独立模式不支持任务调度器，返回None
        """
        return None

    def get_trader_mode(self, account_id: str) -> Optional[str]:
        """
        获取Trader运行模式

        Args:
            account_id: 账户ID

        Returns:
            运行模式 (standalone)，不存在返回None
        """
        if account_id in self.traders:
            return "standalone"
        return None

    # ==================== 数据查询接口（查询Trader） ====================

    async def get_account(self, account_id: str) -> Optional[AccountData]:
        """获取账户数据"""
        trader = self.traders.get(account_id)
        if trader:
            return await trader.get_account()
        return None

    async def get_all_accounts(self) -> List[AccountData]:
        """获取所有账户数据（包括禁用账户）"""
        accounts = []
        # 获取已启动trader的账户数据
        for trader in self.traders.values():
            account = await trader.get_account()
            if account:
                accounts.append(account)
        return accounts

    def get_trader(self, account_id: str) -> Optional[TraderProxy]:
        """获取Trader实例"""
        return self.traders.get(account_id)

    async def get_order(self, account_id: str, order_id: str) -> Optional[Any]:
        """获取订单数据"""
        trader = self.traders.get(account_id)
        if trader:
            return await trader.get_order(order_id)
        return None

    async def get_orders(self, account_id: Optional[str] = None) -> List[OrderData]:
        """获取订单列表"""
        if account_id:
            trader = self.traders.get(account_id)
            if trader:
                return await trader.get_orders()
            return []
        # 获取所有账户的订单
        all_orders = []
        for trader in self.traders.values():
            all_orders.extend(await trader.get_orders())
        return all_orders

    async def get_active_orders(self, account_id: Optional[str] = None) -> List[Any]:
        """获取活动订单"""
        if account_id:
            trader = self.traders.get(account_id)
            if trader:
                return await trader.get_active_orders()
            return []
        # 获取所有账户的活动订单
        all_orders = []
        for trader in self.traders.values():
            all_orders.extend(await trader.get_active_orders())
        return all_orders

    async def get_trades(self, account_id: Optional[str] = None) -> List[Any]:
        """获取成交列表"""
        if account_id:
            trader = self.traders.get(account_id)
            if trader:
                return await trader.get_trades()
            return []
        # 获取所有账户的成交
        all_trades = []
        for trader in self.traders.values():
            all_trades.extend(await trader.get_trades())
        return []

    async def get_positions(self, account_id: Optional[str] = None) -> Dict[str, List[Any]]:
        """获取持仓列表"""
        if account_id:
            trader = self.traders.get(account_id)
            if trader:
                return {account_id: await trader.get_positions()}
            return {account_id: []}
        # 获取所有账户的持仓
        result = {}
        for acc_id, trader in self.traders.items():
            result[acc_id] = await trader.get_positions()
        return result

    # ==================== 策略管理接口 ====================

    async def list_strategies(self, account_id: str) -> List:
        """获取策略列表"""
        trader = self.traders.get(account_id)
        if trader:
            strategies: Any = await trader.send_request("list_strategies", {})
            return strategies if isinstance(strategies, list) else []
        return []

    async def get_strategy(self, account_id: str, strategy_id: str) -> Optional[dict]:
        """获取指定策略状态"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("get_strategy", {"strategy_id": strategy_id})
            return result if isinstance(result, dict) else None
        return None

    async def start_strategy(self, account_id: str, strategy_id: str) -> bool:
        """启动策略"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("start_strategy", {"strategy_id": strategy_id})
            return bool(result) if result is not None else False
        return False

    async def stop_strategy(self, account_id: str, strategy_id: str) -> bool:
        """停止策略"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("stop_strategy", {"strategy_id": strategy_id})
            return bool(result) if result is not None else False
        return False

    async def start_all_strategies(self, account_id: str) -> bool:
        """启动所有策略"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("start_all_strategies", {})
            return bool(result) if result is not None else False
        return False

    async def stop_all_strategies(self, account_id: str) -> bool:
        """停止所有策略"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("stop_all_strategies", {})
            return bool(result) if result is not None else False
        return False

    # ==================== 换仓管理接口 ====================

    async def get_rotation_instructions(
        self,
        account_id: str,
        limit: int = 100,
        offset: int = 0,
        status: str = None,
        enabled: bool = None,
    ) -> Optional[dict]:
        """获取换仓指令列表"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request(
                "get_rotation_instructions",
                {"limit": limit, "offset": offset, "status": status, "enabled": enabled},
            )
            return result if isinstance(result, dict) else None
        return None

    async def get_rotation_instruction(
        self, account_id: str, instruction_id: int
    ) -> Optional[dict]:
        """获取指定换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request(
                "get_rotation_instruction", {"instruction_id": instruction_id}
            )
            return result if isinstance(result, dict) else None
        return None

    async def create_rotation_instruction(
        self, account_id: str, instruction_data: dict
    ) -> Optional[dict]:
        """创建换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("create_rotation_instruction", instruction_data)
            return result if isinstance(result, dict) else None
        return None

    async def update_rotation_instruction(
        self, account_id: str, instruction_id: int, update_data: dict
    ) -> Optional[dict]:
        """更新换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request(
                "update_rotation_instruction", {"instruction_id": instruction_id, **update_data}
            )
            return result if isinstance(result, dict) else None
        return None

    async def delete_rotation_instruction(self, account_id: str, instruction_id: int) -> bool:
        """删除换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request(
                "delete_rotation_instruction", {"instruction_id": instruction_id}
            )
            return bool(result) if result is not None else False
        return False

    async def clear_rotation_instructions(self, account_id: str) -> bool:
        """清除已完成换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("clear_rotation_instructions", {})
            return bool(result) if result is not None else False
        return False

    async def import_rotation_instructions(
        self, account_id: str, csv_text: str, filename: str, mode: str = "append"
    ) -> Optional[dict]:
        """批量导入换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request(
                "import_rotation_instructions",
                {"csv_text": csv_text, "filename": filename, "mode": mode},
            )
            return result if isinstance(result, dict) else None
        return None

    async def execute_rotation(self, account_id: str) -> bool:
        """执行换仓"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("execute_rotation", {})
            return bool(result) if result is not None else False
        return False

    async def close_all_positions(self, account_id: str) -> bool:
        """一键平仓"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("close_all_positions", {})
            return bool(result) if result is not None else False
        return False

    # ==================== 报单指令管理接口 ====================

    async def get_order_cmds_status(self, account_id: str, status: str = None) -> Optional[list]:
        """获取报单指令状态"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("get_order_cmds_status", {"status": status})
            return result if isinstance(result, list) else None
        return None

    async def batch_execute_instructions(self, account_id: str, ids: List[int]) -> Optional[dict]:
        """批量执行换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("batch_execute_instructions", {"ids": ids})
            return result if isinstance(result, dict) else None
        return None

    async def batch_delete_instructions(self, account_id: str, ids: List[int]) -> Optional[dict]:
        """批量删除换仓指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("batch_delete_instructions", {"ids": ids})
            return result if isinstance(result, dict) else None
        return None

    # ==================== 系统参数接口 ====================

    async def list_system_params(self, account_id: str, group: Optional[str] = None) -> List:
        """获取系统参数列表"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("list_system_params", {"group": group})
            return result if isinstance(result, list) else []
        return []

    async def get_system_param(self, account_id: str, param_key: str) -> Optional[dict]:
        """获取单个系统参数"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("get_system_param", {"param_key": param_key})
            return result if isinstance(result, dict) else None
        return None

    async def update_system_param(
        self, account_id: str, param_key: str, param_value: str
    ) -> Optional[dict]:
        """更新系统参数"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request(
                "update_system_param", {"param_key": param_key, "param_value": param_value}
            )
            return result if isinstance(result, dict) else None
        return None

    async def get_system_params_by_group(self, account_id: str, group: str) -> Optional[dict]:
        """根据分组获取系统参数"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("get_system_params_by_group", {"group": group})
            return result if isinstance(result, dict) else None
        return None

    # ==================== 启动/停止 ====================

    async def start(self) -> None:
        """启动管理器"""
        if self._running:
            logger.warning("交易管理器已在运行")
            return

        self._running = True
        logger.info("交易管理器启动中...")

        # 获取所有账号
        accounts = [acc for acc in self.account_configs]
        logger.info(f"识别到账号: {[acc.account_id for acc in accounts]}")

        # 启动所有Trader
        for account in accounts:
            if account.account_id is None:
                logger.warning(f"跳过没有 account_id 的账户配置")
                continue
            await self.create_trader(account.account_id)
            if account.enabled:
                success = await self.start_trader(account.account_id)
                if success:
                    logger.info(f"Trader Proxy [{account.account_id}] 启动成功")
                else:
                    logger.error(f"Trader Proxy [{account.account_id}] 启动失败")

        logger.info("交易管理器启动完成")

    async def stop(self) -> None:
        """停止管理器"""
        if not self._running:
            return

        self._running = False
        logger.info("交易管理器停止中...")

        # 停止所有Trader
        for account_id in list(self.traders.keys()):
            await self.stop_trader(account_id)

        logger.info("交易管理器已停止")
