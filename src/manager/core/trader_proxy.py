"""
Trader Proxy 模块
管理独立Trader子进程，作为Socket客户端连接到Trader的Socket服务器

状态机：
- STOPPED: 已停止（初始状态，允许start）
- CONNECTING: 连接中（正在异步连接）
- CONNECTED: 已连接（连接成功）

状态转换：
- STOPPED → CONNECTING: 调用start()
- CONNECTING → CONNECTED: 异步连接成功
- CONNECTING → STOPPED: 异步连接失败（重试次数耗尽）
- CONNECTED → CONNECTING: 检测到socket断开
- 任何状态 → STOPPED: 调用stop()
"""

import asyncio
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

from src.app_context import AppContext, get_app_context
from src.models.object import AccountData, OrderData, PositionData, TickData, TradeData, TraderState
from src.utils.config_loader import AccountConfig, AppConfig
from src.utils.event_engine import EventTypes
from src.utils.ipc import SocketClient
from src.utils.logger import get_logger
from src.utils.scheduler import Job

logger = get_logger(__name__)
ctx: AppContext = get_app_context()


class TraderProxy:
    """
    Trader Proxy - 独立模式

    管理独立Trader子进程，作为Socket客户端连接到Trader的Socket服务器。
    """

    # 连接参数
    MAX_RETRIES = 10  # 最多重试10次
    INITIAL_INTERVAL = 0.5  # 初始间隔0.5秒
    MAX_INTERVAL = 30.0  # 最大间隔30秒

    def __init__(
        self,
        account_config: AccountConfig,
        global_config: Any,  # 可以是 AppConfig 或 _GlobalConfigAdapter
        socket_path: str,
        heartbeat_timeout: int = 30,
    ):
        """
        初始化 Trader Proxy

        Args:
            account_config: 账户配置
            global_config: 全局配置（AppConfig 或 _GlobalConfigAdapter）
            socket_path: Socket路径（Trader作为服务器监听此路径）
            heartbeat_timeout: 心跳超时（秒）
        """
        self.account_id = account_config.account_id
        self.account_config = account_config
        self.global_config = global_config
        self.socket_path = socket_path
        self.heartbeat_timeout = heartbeat_timeout
        self._running = False

        # ==================== 状态管理 ====================
        self._state: TraderState = TraderState.STOPPED
        self._state_lock = asyncio.Lock()
        self.start_time: Optional[datetime] = None
        self.restart_count = 0
        self.last_heartbeat = datetime.now()

        # ==================== 进程管理 ====================
        self._created_process: bool = False
        self.process: Optional[asyncio.subprocess.Process] = None
        self.pid_file = str(Path(socket_path).parent / f"qtrader_{self.account_id}.pid")

        # ==================== 连接管理 ====================
        self.socket_client: Optional[SocketClient] = None
        self._connect_task: Optional[asyncio.Task] = None

        logger.info(f"TraderProxy [{self.account_id}] 初始化完成，状态: STOPPED")

    # ==================== 状态管理 ====================

    def get_state(self) -> TraderState:
        """获取当前状态"""
        return self._state

    async def _set_state(self, new_state: TraderState) -> None:
        """
        设置状态（线程安全）

        Args:
            new_state: 新状态
        """
        async with self._state_lock:
            old_state = self._state
            self._state = new_state
            if old_state != new_state:
                logger.info(f"TraderProxy [{self.account_id}] 状态变更: {old_state} -> {new_state}")

        # 状态变化时触发账户更新事件，通知前端刷新
        try:
            event_engine = ctx.get_event_engine()
            if event_engine:
                # 构造账户状态更新数据
                account_update = {
                    "account_id": self.account_id,
                    "status": new_state.value,
                    "gateway_connected": (new_state == TraderState.CONNECTED),
                    "timestamp": datetime.now().isoformat(),
                }
                event_engine.put(EventTypes.ACCOUNT_STATUS, account_update)
                logger.debug(f"推送账户状态更新事件: {account_update}")
        except Exception as e:
            logger.error(f"推送账户状态更新事件失败: {e}")

    def _is_state(self, state: TraderState) -> bool:
        """检查是否为指定状态"""
        return self._state == state

    # ==================== 启动/停止 ====================

    async def start(self) -> bool:
        """
        启动 Trader Proxy

        只有STOPPED状态才允许调用start。
        start成功后状态变为CONNECTING，并开始异步连接。

        Returns:
            是否启动成功
        """
        if self._running:
            logger.warning(f"TraderProxy [{self.account_id}] 已经在运行中，当前状态: {self._state}")
            return False
        
        self._running = True
        logger.info(f"TraderProxy [{self.account_id}] 开始启动...")

        # 在后台启动
        self._connect_task = asyncio.create_task(self._connect_async())
        return True

    async def stop(self) -> bool:
        """
        停止 Trader Proxy

        任何状态都允许调用stop，调用后状态变为STOPPED。

        Returns:
            是否停止成功
        """
        self._running = False
        current_state = self._state
        logger.info(f"TraderProxy [{self.account_id}] 开始停止，当前状态: {current_state}")

        # 停止连接任务
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
            logger.info(f"TraderProxy [{self.account_id}] 连接任务已取消")
        self._connect_task = None

        # 断开Socket连接
        if self.socket_client:
            await self.socket_client.disconnect()
            self.socket_client = None

        # 强制停止trader进程
        # await self._force_kill_trader()
        # 状态变为已停止
        await self._set_state(TraderState.STOPPED)
        logger.info(f"TraderProxy [{self.account_id}] 已停止")
        return True

    # ==================== 异步连接 ====================

    async def _connect_async(self) -> None:
        """
        后台异步连接到 Trader

        使用退避算法进行重试：
        - 重试间隔从0.5s开始，每次翻倍
        - 最大重试间隔为30s
        - 最多重试10次

        连接成功 → 状态变为 CONNECTED
        连接失败 → 状态变为 STOPPED
        """
        # 创建Socket客户端
        self.start_time = datetime.now()
        if self.account_id is None:
            raise ValueError("account_id is required for SocketClient")
        self.socket_client = SocketClient(
            self.socket_path, self.account_id, self._on_msg_callback
        )
        attempt = 0
        check_interval = 5
        while self._running:      
            try:
                # 计算当前重试间隔（退避算法：指数增长）
                attempt += 1
                process_exists = await self._check_process_exists()
                if not process_exists:
                    await self._set_state(TraderState.STOPPED)
                    await asyncio.sleep(check_interval)
                    continue
                
                if self.socket_client.is_connected():
                    await asyncio.sleep(check_interval)
                    continue
                
                 # 进程存在，且为未连接
                self.last_heartbeat = datetime.now()
                if self.socket_client.is_connected():
                    attempt = 0
                    continue
                
                # 状态变为连接中
                await self._set_state(TraderState.CONNECTING)
                logger.info(
                    f"TraderProxy [{self.account_id}] 尝试连接 ({attempt + 1})..."
                )
                success = await self.socket_client.connect()
                if success:
                    logger.info(f"TraderProxy [{self.account_id}] 连接成功")
                    await self._set_state(TraderState.CONNECTED)
                    attempt = 0
                    continue
                else:
                    logger.warning(
                        f"TraderProxy [{self.account_id}] 连接失败 ({attempt + 1})"
                    )

            except Exception as e:
                logger.exception(
                    f"TraderProxy [{self.account_id}] 连接异常 ({attempt + 1}): {e}"
                )
            # 等待重试
            await asyncio.sleep(check_interval)

    # ==================== 进程管理 ====================
    async def _check_process_exists(self) -> bool:
        """
        检查进程是否已存在

        通过检查socket文件和PID文件判断

        Returns:
            进程是否存在
        """
        # 检查socket文件是否存在
        socket_file = Path(self.socket_path)
        if not socket_file.exists():
            return False

        # 检查PID文件
        pid_file = Path(self.pid_file)
        if not pid_file.exists():
            return False

        try:
            # 读取PID
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())

            # 检查进程是否运行
            try:
                os.kill(pid, 0)  # 检查进程是否存在，不发送信号
                return True
            except OSError:
                # 清理过期的PID文件
                pid_file.unlink(missing_ok=True)
                return False

        except Exception as e:
            logger.warning(f"TraderProxy [{self.account_id}] 检查进程失败: {e}")
            return False

    async def _create_subprocess(self) -> None:
        """创建新的子进程"""
        self._created_process = True
        # 构建命令
        if self.account_id is None:
            raise ValueError("account_id is required to create subprocess")
        cmd: List[str] = [
            "python",
            "-m",
            "src.run_trader",
            "--account-id",
            self.account_id,
        ]

        # 根据账户配置决定是否添加debug参数
        if hasattr(self.account_config, "debug") and self.account_config.debug:
            cmd.append("--debug")
            logger.info(f"TraderProxy [{self.account_id}] 启用调试模式")

        logger.info(f"TraderProxy [{self.account_id}] 创建子进程: {' '.join(cmd)}")

        # 启动子进程
        self.process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        logger.info(f"TraderProxy [{self.account_id}] 子进程已启动，PID: {self.process.pid}")

    async def _cleanup_subprocess(self) -> None:
        """清理自己创建的子进程"""
        if not self.process:
            return

        try:
            process = self.process

            # 发送SIGTERM信号
            process.terminate()

            # 等待进程结束
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
                logger.info(f"TraderProxy [{self.account_id}] 子进程已停止")
            except asyncio.TimeoutError:
                # 超时则强制杀死
                process.kill()
                await process.wait()
                logger.warning(f"TraderProxy [{self.account_id}] 子进程强制停止")

        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 清理子进程失败: {e}")
        finally:
            self.process = None
            # 清理PID文件
            Path(self.pid_file).unlink(missing_ok=True)

    async def _force_kill_trader(self) -> None:
        """强制停止trader进程"""
        # 检查PID文件并停止进程
        pid_file = Path(self.pid_file)
        if pid_file.exists():
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())

                # 停止进程
                try:
                    os.kill(pid, 15)  # SIGTERM
                    # 等待进程结束
                    for _ in range(10):
                        try:
                            os.kill(pid, 0)
                            await asyncio.sleep(0.1)
                        except OSError:
                            break
                    logger.info(f"TraderProxy [{self.account_id}] 进程 {pid} 已停止")
                except OSError:
                    pass

                # 如果进程还在运行，强制杀死
                try:
                    os.kill(pid, 0)
                    os.kill(pid, 9)  # SIGKILL
                    logger.warning(f"TraderProxy [{self.account_id}] 进程 {pid} 强制停止")
                except OSError:
                    pass

            except Exception as e:
                logger.warning(f"TraderProxy [{self.account_id}] 停止进程失败: {e}")
            finally:
                # 清理PID文件
                pid_file.unlink(missing_ok=True)

    # ==================== 消息处理 ====================

    def _update_heartbeat(self) -> None:
        """更新心跳时间"""
        self.last_heartbeat = datetime.now()

    def _on_msg_callback(self, msg_type: str, data: Dict) -> None:
        """
        统一的消息回调接口

        Args:
            msg_type: 消息类型 (heartbeat, tick等)
            data: 消息数据
        """
        try:
            if msg_type == "heartbeat":
                self._update_heartbeat()
            else:
                self._emit_data(msg_type, data)
        except Exception as e:
            logger.error(f"处理消息 [{msg_type}] 时出错: {e}")

    def _emit_data(self, data_type: str, data: Dict) -> None:
        """
        提交到事件驱动中

        Args:
            data_type: 数据类型
            data: 数据
        """
        event_type = None
        if data_type == "account":
            event_type = EventTypes.ACCOUNT_UPDATE
        elif data_type == "order":
            event_type = EventTypes.ORDER_UPDATE
        elif data_type == "trade":
            event_type = EventTypes.TRADE_UPDATE
        elif data_type == "position":
            event_type = EventTypes.POSITION_UPDATE
        elif data_type == "tick":
            event_type = EventTypes.TICK_UPDATE

        if event_type:
            event_engine = ctx.get_event_engine()
            if event_engine:
                event_engine.put(event_type, data)
                logger.debug(f"推送事件 [{event_type}] 从Trader [{self.account_id}]")

    # ==================== 数据查询接口 ====================

    async def get_account(self) -> Optional[AccountData]:
        """实时获取账户数据"""
        if not self.socket_client:
            if self.account_id is None:
                return None
            return AccountData.model_construct(account_id=self.account_id)
        data = await self.socket_client.request("get_account", {}, timeout=5.0)
        if not data:
            if self.account_id is None:
                return None
            return AccountData.model_construct(account_id=self.account_id)

        account = AccountData(**data)
        account.status = self._state
        return account

    async def get_order(self, order_id: str) -> Optional[OrderData]:
        """实时获取订单数据"""
        if not self.socket_client:
            return None
        data = await self.socket_client.request("get_order", {"order_id": order_id}, timeout=5.0)
        return OrderData(**data) if data else None

    async def get_orders(self) -> List[OrderData]:
        """实时获取所有订单数据"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_orders", {}, timeout=5.0)
        if data:
            items = cast(List[Dict[str, Any]], data)
            return [OrderData(**item) for item in items]
        return []

    async def get_active_orders(self) -> List[OrderData]:
        """实时获取活动订单"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_active_orders", {}, timeout=5.0)
        if data:
            items = cast(List[Dict[str, Any]], data)
            return [OrderData(**item) for item in items]
        return []

    async def get_trade(self, trade_id: str) -> Optional[TradeData]:
        """实时获取成交数据"""
        if not self.socket_client:
            return None
        data = await self.socket_client.request("get_trade", {"trade_id": trade_id}, timeout=5.0)
        return TradeData(**data) if data else None

    async def get_trades(self) -> List[TradeData]:
        """实时获取所有成交数据"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_trades", {}, timeout=5.0)
        if data:
            items = cast(List[Dict[str, Any]], data)
            return [TradeData(**item) for item in items]
        return []

    async def get_positions(self) -> List[PositionData]:
        """实时获取所有持仓数据"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_positions", {}, timeout=5.0)
        if data:
            items = cast(List[Dict[str, Any]], data)
            return [PositionData(**item) for item in items]
        return []

    async def get_quotes(self) -> List[TickData]:
        """实时获取所有行情数据"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_quotes", {}, timeout=5.0)
        if data:
            items = cast(List[Dict[str, Any]], data)
            return [TickData(**item) for item in items]
        return []

    async def get_jobs(self) -> List[Job]:
        """实时获取所有任务数据"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_jobs", {}, timeout=5.0)
        if data:
            items = cast(List[Dict[str, Any]], data)
            return [Job(**item) for item in items]
        return []

    async def send_request(
        self, request_type: str, data: Dict[str, Any], timeout: float = 10.0
    ) -> Any:
        """
        通用请求发送方法

        Args:
            request_type: 请求类型
            data: 请求数据
            timeout: 超时时间

        Returns:
            响应数据
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader")
            return None

        try:
            response = await self.socket_client.request(request_type, data, timeout=timeout)
            return response
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 请求失败 [{request_type}]: {e}")
            return None

    # ==================== 交易接口 ====================

    async def send_order_request(
        self, symbol: str, direction: str, offset: str, volume: int, price: float = 0
    ) -> Optional[str]:
        """
        发送下单请求到 Trader

        Args:
            symbol: 合约代码
            direction: 方向
            offset: 开平
            volume: 数量
            price: 价格

        Returns:
            订单ID，失败返回None
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader")
            return None

        try:
            request_data = {
                "symbol": symbol,
                "direction": direction,
                "offset": offset,
                "volume": volume,
                "price": price,
            }

            response = await self.socket_client.request("order_req", request_data, timeout=10.0)
            order_id = response
            if isinstance(order_id, str):
                return order_id

            logger.error(
                f"TraderProxy [{self.account_id}] 下单失败: {response.get('message') if response else 'No response'}"
            )
            return None

        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 下单请求失败: {e}")
            return None

    async def send_cancel_request(self, order_id: str) -> bool:
        """
        发送撤单请求到 Trader

        Args:
            order_id: 订单ID

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader")
            return False

        try:
            request_data = {"order_id": order_id}

            response = await self.socket_client.request(
                "cancel_req", request_data, timeout=10.0
            )
            return bool(response)

        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 撤单请求失败: {e}")
            return False

    async def subscribe(self, request_data):
        """
        订阅合约行情

        Args:
            symbol: 合约代码
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader")
            return False

        try:
            response = await self.socket_client.request("subscribe", request_data, timeout=10.0)
            return bool(response)

        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 订阅请求失败: {e}")
            return False

    # ==================== 网关控制接口 ====================

    async def connect(self) -> bool:
        """
        连接网关（异步接口，用于路由）

        通过socket发送连接请求到远程Trader

        Returns:
            是否成功发送请求
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送连接请求")
            return False

        try:
            response = await self.socket_client.request("connect_gateway", {}, timeout=10.0)
            return bool(response)
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 连接网关请求失败: {e}")
            return False

    async def disconnect(self) -> bool:
        """
        断开网关（异步接口，用于路由）

        通过socket发送断开请求到远程Trader

        Returns:
            是否成功发送请求
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.warning(f"TraderProxy [{self.account_id}] 未连接到Trader")
            return False

        try:
            response = await self.socket_client.request(
                "disconnect_gateway", {}, timeout=10.0
            )
            return bool(response)
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 断开网关请求失败: {e}")
            return False

    async def pause(self) -> bool:
        """
        暂停交易（异步接口，用于路由）

        通过socket发送暂停请求到远程Trader

        Returns:
            是否成功发送请求
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送暂停请求")
            return False

        try:
            response = await self.socket_client.request("pause_trading", {}, timeout=10.0)
            return bool(response)
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 暂停交易请求失败: {e}")
            return False

    async def resume(self) -> bool:
        """
        恢复交易（异步接口，用于路由）

        通过socket发送恢复请求到远程Trader

        Returns:
            是否成功发送请求
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送恢复请求")
            return False

        try:
            response = await self.socket_client.request("resume_trading", {}, timeout=10.0)
            return bool(response)
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 恢复交易请求失败: {e}")
            return False

    async def update_alert_wechat(self, alert_wechat: bool) -> bool:
        """
        更新微信告警配置

        通过socket发送请求到远程Trader

        Args:
            alert_wechat: 是否启用微信告警

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送更新请求")
            return False

        try:
            response = await self.socket_client.request(
                "update_alert_wechat", {"alert_wechat": alert_wechat}, timeout=10.0
            )
            return response is not None
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 更新微信告警配置请求失败: {e}")
            return False

    async def get_alert_wechat(self) -> Optional[bool]:
        """
        获取微信告警配置

        通过socket发送请求到远程Trader

        Returns:
            alert_wechat 值，失败返回 None
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送获取请求")
            return None

        try:
            response = await self.socket_client.request("get_alert_wechat", {}, timeout=10.0)
            if isinstance(response, dict) and "alert_wechat" in response:
                alert_wechat = response["alert_wechat"]
                return bool(alert_wechat) if isinstance(alert_wechat, bool) else None
            return None
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 获取微信告警配置请求失败: {e}")
            return None

    async def update_strategy_params(self, strategy_id: str, params: dict) -> dict:
        """
        更新策略参数

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID
            params: 要更新的参数字典

        Returns:
            更新结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送更新请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "update_strategy_params",
                {"strategy_id": strategy_id, "params": params},
                timeout=10.0,
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 更新策略参数请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def update_strategy_signal(self, strategy_id: str, signal: dict) -> dict:
        """
        更新策略信号

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID
            signal: 要更新的信号字典

        Returns:
            更新结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送更新请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "update_strategy_signal",
                {"strategy_id": strategy_id, "signal": signal},
                timeout=10.0,
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 更新策略信号请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def set_strategy_trading_status(self, strategy_id: str, status: dict) -> dict:
        """
        设置策略交易状态（统一接口）

        支持同时设置开仓和平仓状态：
        - opening_paused: 暂停/恢复开仓
        - closing_paused: 暂停/恢复平仓

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID
            status: {"opening_paused": boolean, "closing_paused": boolean}

        Returns:
            操作结果，包含 {"success": bool, "message": str, "data": dict}
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "set_strategy_trading_status", {"strategy_id": strategy_id, "status": status}, timeout=10.0
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 设置策略交易状态请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def enable_strategy(self, strategy_id: str) -> dict:
        """
        启用策略

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "enable_strategy", {"strategy_id": strategy_id}, timeout=10.0
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 启用策略请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def disable_strategy(self, strategy_id: str) -> dict:
        """
        禁用策略

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "disable_strategy", {"strategy_id": strategy_id}, timeout=10.0
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 禁用策略请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def reload_strategy_params(self, strategy_id: str) -> dict:
        """
        重载策略参数
        从配置文件重新加载策略参数

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "reload_strategy_params", {"strategy_id": strategy_id}, timeout=10.0
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 重载策略参数请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def init_strategy(self, strategy_id: str) -> dict:
        """
        初始化策略
        调用策略的 init() 方法

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "init_strategy", {"strategy_id": strategy_id}, timeout=30.0
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 初始化策略请求失败: {e}")
            return {"success": False, "message": f"请求失败: {str(e)}"}

    async def get_strategy_order_cmds(self, strategy_id: str, status: Optional[str]) -> list:
        """
        获取策略的报单指令历史

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID
            status: 状态过滤 (active/finished/all)

        Returns:
            报单指令列表
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送请求")
            return []

        try:
            response = await self.socket_client.request(
                "get_strategy_order_cmds",
                {"strategy_id": strategy_id, "status": status},
                timeout=10.0,
            )
            return response if isinstance(response, list) else []
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 获取策略报单指令请求失败: {e}")
            return []

    @property
    def gateway(self) -> "_GatewayStatus":
        """网关状态（用于兼容路由代码）"""
        return self._GatewayStatus(self)

    class _GatewayStatus:
        """网关状态包装类"""

        def __init__(self, proxy: "TraderProxy"):
            self._proxy = proxy

        @property
        def connected(self) -> bool:
            """是否已连接到网关"""
            return self._proxy._is_state(TraderState.CONNECTED)

    # ==================== 辅助方法 ====================

    async def restart(self) -> bool:
        """
        重启 Trader Proxy

        Returns:
            是否重启成功
        """
        logger.info(f"TraderProxy [{self.account_id}] 重启中...")

        # 停止
        await self.stop()

        # 等待一秒
        await asyncio.sleep(1)

        # 启动
        success = await self.start()
        if success:
            self.restart_count += 1
            logger.info(f"TraderProxy [{self.account_id}] 重启成功，重启次数: {self.restart_count}")
        else:
            logger.error(f"TraderProxy [{self.account_id}] 重启失败")

        return success

    def is_running(self) -> bool:
        """检查是否运行中"""
        return not self._is_state(TraderState.STOPPED)

    def is_alive(self) -> bool:
        """检查子进程是否存活"""
        if self.process and self._created_process:
            return self.process.returncode is None
        # 非自己创建的进程，通过心跳判断
        if not self._is_state(TraderState.STOPPED):
            heartbeat_age = (datetime.now() - self.last_heartbeat).total_seconds()
            return heartbeat_age < self.heartbeat_timeout
        return False

    def get_status(self) -> Dict[str, Any]:
        """
        获取状态信息

        Returns:
            状态字典
        """
        return {
            "account_id": self.account_id,
            "state": self._state.value,  # 状态: stopped/connecting/connected
            "running": self.is_running(),
            "alive": self.is_alive(),
            "connected": self._is_state(TraderState.CONNECTED),
            "connecting": self._is_state(TraderState.CONNECTING),
            "created_process": self._created_process,
            "pid": self.process.pid if self.process else None,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "restart_count": self.restart_count,
            "socket_path": self.socket_path,
        }

    async def ping(self) -> bool:
        """
        发送心跳请求到 Trader

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            return False

        try:
            response = await self.socket_client.request("ping", {}, timeout=5.0)
            if response:
                self.last_heartbeat = datetime.now()
                return True
            return False
        except Exception as e:
            logger.error(f"TraderProxy [{self.account_id}] 心跳请求失败: {e}")
            return False
