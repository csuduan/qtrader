"""
交易管理器
负责管理多个Trader（独立进程模式），提供API服务
"""

import asyncio
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.app_context import AppContext, get_app_context
from src.manager.public_data_service import PublicDataService
from src.manager.service.alarm_service import AlarmService
from src.manager.trader_proxy import TraderProxy
from src.models.object import AccountData, Direction, Offset, OrderData, OrderRequest
from src.utils.config_loader import AccountConfig, AppConfig, DatabaseConfig, SocketConfig, get_config_loader
from src.utils.logger import get_logger
from src.utils.scheduler import TaskScheduler
from src.utils.db_url import build_db_url
from src.utils.shared_database import SharedDatabase, init_shared_database

ctx: AppContext = get_app_context()

logger = get_logger(__name__)


class TradingManager:
    """
    交易管理器

    职责：
    1. 启动/停止/重启 Trader
    2. 进程健康检查和自动重启
    3. 事件处理和分发（通过 AsyncEventEngine）
    4. API 服务集成（查询Trader获取数据）

    """

    def __init__(self, account_configs: List[AccountConfig], app_config: Optional[AppConfig] = None):
        """
        初始化交易管理器

        Args:
            account_configs: 账户配置列表
            app_config: 全局配置（包含告警配置等）
        """
        self.account_configs = account_configs
        self.account_configs_map: Dict[str, AccountConfig] = {
            acc.account_id: acc for acc in account_configs if acc.account_id is not None
        }
        self.app_config = app_config

        # 使用默认的 Socket 和 Database 配置（从全局配置获取）
        self.socket_config = SocketConfig()
        self.database_config = DatabaseConfig()


        # Socket目录（独立模式的Trader进程会创建socket文件）
        socket_dir = self.socket_config.socket_dir
        Path(socket_dir).mkdir(parents=True, exist_ok=True)

        # Trader Proxy 实例
        self.traders: Dict[str, TraderProxy] = {}

        # 运行状态
        self._running = False
        self._health_check_running = False
        self._health_check_task: Optional[asyncio.Task] = None

        # Scheduler（将在 start() 中初始化）
        self._scheduler: Optional[TaskScheduler] = None

        # 共享数据库（公共数据）
        self._shared_db: Optional[SharedDatabase] = None

        # 公共数据服务
        self.public_data_service: Optional[PublicDataService] = None

        # 告警服务
        self.alarm_service: Optional[AlarmService] = None

        # 服务器资源监控历史缓存（5秒采样一次，默认保存2880条约4小时）
        self._resource_history: deque = deque(maxlen=2880)
        self._resource_sample_task: Optional[asyncio.Task] = None

        logger.info("交易管理器初始化完成")

    # ==================== Trader Proxy管理 ====================
    async def create_trader_proxy(self, account_id) -> bool:
        """
        创建指定账户的Trader Proxy
        Args:
            account_id: 账户ID

        Returns:
            是否创建成功
        """
        # 如果已存在，先停止旧实例
        if account_id in self.traders:
            old_trader = self.traders[account_id]
            logger.warning(f"Trader [{account_id}] 已存在，_connect_task={old_trader._connect_task}，先停止旧实例")
            await old_trader.stop_monitoring()
            del self.traders[account_id]

        account_config = self.account_configs_map.get(account_id)
        if not account_config:
            logger.error(f"未找到账号 [{account_id}] 的配置")
            return False

        trader_proxy = TraderProxy(account_config=account_config)
        # TraderProxy 会自动检测 socket 文件并决定是否连接，不需要手动调用 start()
        self.traders[account_id] = trader_proxy
        logger.info(f"Trader Proxy [{account_id}] 初始化完成（enabled: {account_config.enabled}）")
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

            success = await trader.start_process()
            if success:
                logger.info(f"Trader Proxy [{account_id}] 启动成功")
            else:
                logger.warning(f"Trader Proxy [{account_id}] 启动返回 False")
            return success

        except Exception as e:
            logger.exception(f"启动Trader Proxy [{account_id}] 失败: {e}")
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
            # 停止Trader
            success = await trader.stop_process()
            logger.info(f"Trader [{account_id}] 已停止")
            return success

        except Exception as e:
            logger.exception(f"停止Trader [{account_id}] 失败: {e}")
            return False

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

    def get_manager_scheduler_jobs(self) -> List[dict]:
        """
        获取Manager级别的定时任务列表

        Returns:
            任务信息列表
        """
        if not self._scheduler:
            return []

        jobs = self._scheduler.get_jobs()
        result = []
        for job in jobs.values():
            job_dict = job.model_dump()
            # 补充APScheduler中的下次触发时间
            aps_job = self._scheduler.scheduler.get_job(job.job_id)
            if aps_job and aps_job.next_run_time:
                job_dict["next_trigger_time"] = aps_job.next_run_time.isoformat()
            result.append(job_dict)
        return result

    def operate_manager_scheduler_job(self, job_id: str, action: str) -> bool:
        """
        操作Manager级别的定时任务

        Args:
            job_id: 任务ID
            action: 操作类型 (pause/resume/trigger)

        Returns:
            是否操作成功
        """
        if not self._scheduler:
            return False
        return self._scheduler.operate_job(job_id, action)

    def toggle_manager_scheduler_job(self, job_id: str, enabled: bool) -> bool:
        """
        切换Manager级别定时任务的启用状态

        Args:
            job_id: 任务ID
            enabled: 是否启用

        Returns:
            是否更新成功
        """
        if not self._scheduler:
            return False
        return self._scheduler.update_job_status(job_id, enabled)

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

    async def sync_account(self, account_id: str) -> Optional[dict]:
        """手动触发全量同步：账户+持仓+报单+成交"""
        trader = self.traders.get(account_id)
        if trader:
            return await trader.sync_all()
        return None

    async def get_account(self, account_id: str) -> Optional[AccountData]:
        """获取账户数据"""
        trader = self.traders.get(account_id)
        if trader:
            return await trader.get_account()
        return None

    def get_all_accounts_cached(self) -> List[AccountData]:
        """获取所有缓存的账户数据（不走RPC，用于列表展示）"""
        accounts = []
        for trader in self.traders.values():
            account = trader.get_account_cached()
            if account:
                accounts.append(account)
        return accounts

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

    async def sync_account_data(self, account_id: str) -> dict:
        """
        触发指定账户的全量数据同步

        供前端手动刷新使用
        """
        trader = self.traders.get(account_id)
        if not trader:
            return {"success": False, "message": f"账户 [{account_id}] 不存在"}

        try:
            result = await trader.sync_all()
            return result
        except Exception as e:
            logger.exception(f"同步账户 [{account_id}] 数据失败: {e}")
            return {"success": False, "message": f"同步失败: {str(e)}"}

    async def refresh_contracts(self, account_id: Optional[str] = None) -> dict:
        """
        强制刷新合约信息

        Args:
            account_id: 账户ID，不传则刷新所有账户

        Returns:
            {"success": bool, "results": {account_id: {"success": bool, "message": str}}}
        """
        results = {}
        account_ids = [account_id] if account_id else list(self.traders.keys())

        for acc_id in account_ids:
            trader = self.traders.get(acc_id)
            if not trader:
                results[acc_id] = {"success": False, "message": "Trader不存在"}
                continue

            try:
                result = await trader.refresh_contracts()
                results[acc_id] = result
            except Exception as e:
                logger.exception(f"刷新账户 [{acc_id}] 合约信息失败: {e}")
                results[acc_id] = {"success": False, "message": f"请求异常: {str(e)}"}

        # 统计总体结果
        all_success = all(r.get("success", False) for r in results.values())
        return {"success": all_success, "results": results}

    async def get_contracts(
        self,
        account_id: Optional[str] = None,
        exchange_id: Optional[str] = None,
        product_type: Optional[str] = None,
        symbol_keyword: Optional[str] = None,
    ) -> list:
        """
        获取合约列表

        从 Trader 进程的内存中获取合约信息

        Args:
            account_id: 账户ID，不传则查询所有账户
            exchange_id: 交易所筛选
            product_type: 产品类型筛选
            symbol_keyword: 合约代码关键词

        Returns:
            合约信息字典列表
        """
        all_contracts: dict[str, dict] = {}
        seen_symbols: set[str] = set()

        # 确定要查询的账户列表
        account_ids = [account_id] if account_id else list(self.traders.keys())

        for acc_id in account_ids:
            trader = self.traders.get(acc_id)
            if not trader:
                logger.warning(f"账户 [{acc_id}] 的 Trader 不存在")
                continue

            try:
                contracts = await trader.get_contracts()
                if not contracts:
                    continue

                for contract in contracts:
                    # 去重：按合约代码去重
                    symbol = contract.get("symbol")
                    if not symbol or symbol in seen_symbols:
                        continue

                    # 应用筛选条件
                    if exchange_id and contract.get("exchange") != exchange_id.upper():
                        continue
                    if product_type and contract.get("product_type") != product_type.upper():
                        continue
                    if symbol_keyword and symbol_keyword.upper() not in symbol.upper():
                        continue

                    seen_symbols.add(symbol)
                    all_contracts[symbol] = contract
            except Exception as e:
                logger.exception(f"获取账户 [{acc_id}] 合约列表失败: {e}")

        # 按合约代码排序
        return sorted(all_contracts.values(), key=lambda x: x.get("symbol", ""))

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

    async def cancel_order_cmd(self, account_id: str, cmd_id: str) -> Optional[dict]:
        """取消报单指令"""
        trader = self.traders.get(account_id)
        if trader:
            result: Any = await trader.send_request("cancel_order_cmd", {"cmd_id": cmd_id})
            return result if isinstance(result, dict) else None
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

        # 初始化共享数据库和公共数据服务
        await self._init_public_data()

        logger.info("Manager 使用新架构：Trader 直接写入 PG，Manager 只读模式")

        # 获取所有账号
        accounts = [acc for acc in self.account_configs]
        logger.info(f"识别到账号: {[acc.account_id for acc in accounts]}")

        # 创建所有TraderProxy（TraderProxy会自动检测socket文件并决定是否连接）
        for account in accounts:
            if account.account_id is None:
                logger.warning(f"跳过没有 account_id 的账户配置")
                continue
            await self.create_trader_proxy(account.account_id)

        # 启动资源采样任务
        self._start_resource_sampler()

        # 初始化告警服务
        self.alarm_service = AlarmService(self)
        ctx.register(ctx.KEY_ALARM_SERVICE, self.alarm_service)
        logger.info("告警服务已初始化")

        # 初始化并启动 Scheduler（复用 utils/scheduler.py）
        from src.manager.job_mgr import ManagerJobManager
        from src.utils.scheduler import TaskScheduler

        job_manager = ManagerJobManager(self)

        # 从全局配置加载 Manager 的 scheduler 配置
        app_config = ctx.get_config()
        if app_config is None or app_config.scheduler is None:
            logger.warning("未找到 Scheduler 配置，跳过启动")
            return
        scheduler_config = app_config.scheduler

        self._scheduler = TaskScheduler(scheduler_config, job_manager)  # type: ignore[arg-type]
        self._scheduler.start()
        logger.info("Manager Scheduler 已启动")

        logger.info("交易管理器启动完成")

    async def _init_public_data(self) -> None:
        """初始化共享数据库和公共数据服务"""
        try:
            loader = get_config_loader()
            app_config = loader._load_app_config()

            # 使用 PostgreSQL 数据库
            db_config = app_config.data_base
            db_url = build_db_url(db_config)
            self._shared_db = init_shared_database(
                db_url,
                pool_size=db_config.pg.pool_size,
                max_overflow=db_config.pg.max_overflow,
            )

            # 创建公共数据服务并加载历史数据
            self.public_data_service = PublicDataService(self._shared_db)
            count = self.public_data_service.load_from_database()

            # 检查合约新鲜度，过期则从 TqSdk + 米筐刷新
            if not self.public_data_service.has_fresh_contracts():
                logger.info("数据库合约信息已过期，从 TqSdk + 米筐 API 刷新...")
                await self._refresh_contracts_from_tq()
            else:
                logger.info(f"合约信息新鲜，已加载 {count} 个合约")
        except Exception as e:
            logger.exception(f"初始化公共数据服务失败: {e}")

    async def _refresh_contracts_from_tq(self) -> None:
        """通过 TqSdk + 米筐 API 刷新合约信息"""
        try:
            # 1. TqSdk 获取基础合约信息
            tq_config = self._get_data_service_config("tq_data")
            if not tq_config:
                logger.warning("未找到天勤认证配置(data_service.tq_data)，跳过合约刷新")
                return

            from src.manager.tq_contract_fetcher import TqContractFetcher

            fetcher = TqContractFetcher(tq_config["username"], tq_config["password"])
            # TqSdk 连接超时由库内部控制
            contracts = await asyncio.to_thread(fetcher.fetch_contracts)

            if contracts is None:
                logger.error("从 TqSdk 获取合约信息失败（连接超时或认证失败）")
                return
            if len(contracts) == 0:
                logger.warning("从 TqSdk 未获取到合约信息（返回空列表）")
                return

            # 2. 米筐补充最小开仓手数（失败不阻塞）
            min_order_map: Dict[str, int] = {}
            rq_config = self._get_data_service_config("rice_data")
            if rq_config:
                try:
                    from src.manager.rq_contract_fetcher import RqContractFetcher

                    rq_fetcher = RqContractFetcher(rq_config["username"], rq_config["password"])
                    min_order_map = await asyncio.to_thread(rq_fetcher.fetch_min_order_quantities)
                    logger.info(f"从米筐获取了 {len(min_order_map)} 个合约的最小开仓手数")
                except Exception as e:
                    logger.warning(f"从米筐获取最小开仓手数失败（不影响主流程）: {e}")

            # 3. 合并数据：将 min_volume 写入 contracts
            # 米筐合约代码为大写，匹配时统一转大写
            min_order_map_upper = {k.upper(): v for k, v in min_order_map.items()}
            for contract in contracts:
                raw_symbol = contract["symbol"]  # Tq格式: "rb2505" (无交易所前缀)
                contract["min_open_volume"] = min_order_map_upper.get(raw_symbol.upper(), 1)

            # 4. 写入共享库
            count = self.public_data_service.upsert_contracts(contracts, data_source="tq")
            logger.info(f"从 TqSdk + 米筐刷新了 {count} 个合约信息")
        except Exception as e:
            logger.exception(f"刷新合约信息失败: {e}")

    def _get_data_service_config(self, key: str) -> Optional[dict]:
        """
        获取数据服务配置

        从 config.yaml 的 data_service.{key} 读取 user/password。
        data_service 通过 AppConfig 的 extra="allow" 作为 dict 存入。

        Args:
            key: 配置键名，如 "tq_data"、"rice_data"

        Returns:
            配置字典 {"user": ..., "password": ...}，未找到返回 None
        """
        from src.utils.config_loader import get_config_loader

        loader = get_config_loader()
        app_config = loader._load_app_config()
        data_service = getattr(app_config, "data_service", None)
        if not data_service or not isinstance(data_service, dict):
            return None
        config = data_service.get(key)
        if config and config.get("username"):
            return config
        return None

    async def _push_public_data_to_trader(self, account_id: str) -> bool:
        """
        推送公共数据给指定 Trader

        Args:
            account_id: 目标 Trader 的账户ID

        Returns:
            是否推送成功
        """
        if not self.public_data_service or not self.public_data_service.has_contracts():
            logger.info(f"公共数据服务无合约数据，跳过推送给 [{account_id}]")
            return False

        trader = self.traders.get(account_id)
        if not trader:
            logger.error(f"Trader [{account_id}] 不存在，无法推送公共数据")
            return False

        try:
            contracts = self.public_data_service.get_contracts_for_push()
            result = await trader.push_public_data(contracts)
            if result:
                logger.info(
                    f"成功推送 {len(contracts)} 个合约数据给 Trader [{account_id}]"
                )
            else:
                logger.warning(f"推送公共数据给 Trader [{account_id}] 失败")
            return result
        except Exception as e:
            logger.exception(f"推送公共数据给 Trader [{account_id}] 出错: {e}")
            return False

    async def stop(self) -> None:
        """停止管理器"""
        if not self._running:
            return

        self._running = False
        logger.info("交易管理器停止中...")

        # 停止资源采样任务
        self._stop_resource_sampler()

        # 注意：Manager 退出时不停止 Trader 进程，让 Trader 继续独立运行
        # 这样可以实现 Manager 重启而不影响交易进程
        logger.info("Trader 进程保持运行（Manager 退出不影响）")

        # 停止 ManagerScheduler
        if self._scheduler:
            self._scheduler.shutdown()
            logger.info("ManagerScheduler 已停止")

        # 清理告警服务
        if self.alarm_service:
            self.alarm_service.clear_all_suppression()
            ctx.remove(ctx.KEY_ALARM_SERVICE)
            self.alarm_service = None
            logger.info("告警服务已清理")

        # 关闭共享数据库
        from src.utils.shared_database import close_shared_database

        close_shared_database()

        logger.info("交易管理器已停止")

    # ==================== 资源监控采样 ====================

    def _start_resource_sampler(self) -> None:
        """启动服务器资源采样任务"""
        if self._resource_sample_task is not None:
            return
        self._resource_sample_task = asyncio.create_task(self._sample_resource_loop())
        logger.info("服务器资源采样任务已启动")

    def _stop_resource_sampler(self) -> None:
        """停止服务器资源采样任务"""
        if self._resource_sample_task is not None:
            self._resource_sample_task.cancel()
            self._resource_sample_task = None
            logger.info("服务器资源采样任务已停止")

    async def _sample_resource_loop(self) -> None:
        """资源采样循环，每 5 秒采集一次"""
        try:
            while self._running:
                self._sample_resource()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("资源采样任务被取消")
        except Exception as e:
            logger.exception(f"资源采样任务出错: {e}")

    def _sample_resource(self) -> None:
        """采集一次服务器资源数据并写入历史缓存"""
        try:
            import psutil

            now = datetime.now()
            cpu_percent = psutil.cpu_percent(interval=None)

            mem = psutil.virtual_memory()
            memory_used_gb = round(mem.used / (1024 ** 3), 2)
            memory_total_gb = round(mem.total / (1024 ** 3), 2)
            memory_percent = round(mem.percent, 2)

            disk = psutil.disk_usage("/")
            disk_used_gb = round(disk.used / (1024 ** 3), 2)
            disk_total_gb = round(disk.total / (1024 ** 3), 2)
            disk_percent = round(disk.percent, 2)

            point = {
                "timestamp": now.isoformat(),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_used_gb": memory_used_gb,
                "memory_total_gb": memory_total_gb,
                "disk_percent": disk_percent,
                "disk_used_gb": disk_used_gb,
                "disk_total_gb": disk_total_gb,
            }
            self._resource_history.append(point)
        except Exception as e:
            logger.exception(f"资源采样失败: {e}")

    def get_resource_history(self, points: int = 60) -> List[dict]:
        """获取最近 N 个资源采样点"""
        return list(self._resource_history)[-points:]
