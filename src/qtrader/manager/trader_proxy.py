"""
Trader Proxy 模块
管理独立Trader子进程，作为Socket客户端连接到Trader的Socket服务器

"""

import asyncio
import contextlib
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from qtrader.app_context import AppContext, get_app_context
from qtrader.models.object import (
    AccountData,
    OrderData,
    PositionData,
    TickData,
    TradeData,
    TraderState,
)
from qtrader.utils.async_event_engine import EventTypes
from qtrader.utils.config_loader import AccountConfig, get_config_loader
from qtrader.utils.ipc import SocketClient
from qtrader.utils.logger import get_logger
from qtrader.utils.scheduler import Job

logger = get_logger(__name__)
ctx: AppContext = get_app_context()


class TraderProxy:
    """
    Trader Proxy
    管理独立Trader子进程，作为Socket客户端连接到Trader的Socket服务器。
    """

    # 连接参数
    MAX_RETRIES = 10  # 最多重试10次
    INITIAL_INTERVAL = 0.5  # 初始间隔0.5秒
    MAX_INTERVAL = 30.0  # 最大间隔30秒

    def __init__(
        self,
        account_config: AccountConfig,
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
        self.heartbeat_timeout = heartbeat_timeout
        self._running = True

        # ==================== 状态管理 ====================
        self._state: TraderState = TraderState.STOPPED
        self._state_lock = asyncio.Lock()
        self.start_time: datetime | None = None
        self.restart_count = 0
        self.last_heartbeat = datetime.now()
        self._manual_stop: bool = False  # 是否为手动停止（手动停止不触发故障告警）

        # ==================== 进程管理 ====================
        self._created_process: bool = False
        # 从全局配置获取 socket_dir
        app_config = get_config_loader()._load_app_config()
        socket_dir = app_config.paths.socket_dir
        socket_dir_abs = Path(socket_dir).expanduser().resolve()
        self.socket_path = str(socket_dir_abs / f"qtrader_{self.account_id}.sock")
        self.pid_file = str(socket_dir_abs / f"qtrader_{self.account_id}.pid")

        # ==================== 连接管理 ====================
        self.socket_client: SocketClient | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._socket_monitor_task: asyncio.Task[None] | None = None  # socket文件监听任务
        self._socket_check_interval: float = 3.0  # socket检测间隔（秒）
        self._bg_tasks: set[asyncio.Task[Any]] = set()  # fire-and-forget后台任务引用，防止被GC

        # ==================== 数据缓存（用于本地计算盈亏）====================
        # 最新行情缓存 (symbol -> tick_data)
        self._tick_cache: dict[str, dict[str, Any]] = {}
        # 持仓缓存（由Trader推送维护，全量快照 + 增量更新）
        self._position_cache: dict[str, PositionData] = {}  # key: symbol
        # 订单缓存（由Trader推送维护，order_id -> order_dict）
        self._order_cache: dict[str, OrderData] = {}
        # 成交缓存（由Trader推送维护，trade_id -> trade_dict）
        self._trade_cache: dict[str, TradeData] = {}
        # 账户内存缓存（常驻，由DB初始化 + Trader推送更新）
        self._account_cache: AccountData | None = None
        self._account_cache_time: datetime | None = None
        # WebSocket推送限制
        self._ws_push_interval: float = 2.0  # 持仓最小推送间隔2秒
        self._last_position_push_time: dict[str, float] = {}

        # 从DB加载初始账户数据
        self._load_account_from_db()

        # 启动 连接任务
        self._connect_task = asyncio.create_task(self._connect_async())
        # 启动定时全量同步任务
        self._socket_monitor_task = asyncio.create_task(self._periodic_sync_loop())

        logger.info(f"TraderProxy [{self.account_id}] 初始化完成，状态: STOPPED")

    async def stop_monitoring(self) -> None:
        """
        停止后台监控任务并断开socket连接（不影响Trader进程本身）

        用于删除账户或替换Proxy实例时清理资源。
        """
        self._running = False
        for task in (self._connect_task, self._socket_monitor_task):
            if task and not task.done():
                task.cancel()
        self._connect_task = None
        self._socket_monitor_task = None

        if self.socket_client:
            try:
                await self.socket_client.disconnect()
            except Exception as e:
                logger.warning("TraderProxy [{}] 断开socket失败: {!r}", self.account_id, e)
            self.socket_client = None
        logger.info(f"TraderProxy [{self.account_id}] 后台监控已停止")

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
                if self._account_cache:
                    self._account_cache.status = self._state
                    if new_state != TraderState.CONNECTED:
                        self._account_cache.md_connected = False
                        self._account_cache.td_connected = False
                    self._emit_data("account", self._account_cache.model_dump())

    def _is_state(self, state: TraderState) -> bool:
        """检查是否为指定状态"""
        return self._state == state

    # ==================== 启动/停止 ====================
    async def start_process(self) -> bool:
        """
        启动 Trader 进程
        Returns:
            是否启动成功
        """
        pid = await self._get_process()
        if pid:
            logger.warning(f"TraderProxy [{self.account_id}] 进程已存在{pid}，不允许重复启动")
            return False

        # 重新启动视为手动干预结束，复位标记，否则后续进程崩溃时健康检查会按"手动停止"跳过告警
        self._manual_stop = False
        self._created_process = False
        logger.info(f"TraderProxy [{self.account_id}] 开始启动...")

        """创建新的子进程"""
        self._created_process = True

        cmd: list[str] = [
            sys.executable,
            "run_trader.py",
            "--account-id",
            self.account_id or "",
        ]

        # 根据账户配置决定是否添加debug参数
        if hasattr(self.account_config, "debug") and self.account_config.debug:
            cmd.append("--debug")
            logger.info(f"TraderProxy [{self.account_id}] 启用调试模式")

        logger.info(f"TraderProxy [{self.account_id}] 创建子进程: {' '.join(cmd)}")

        # 使用nohup包裹命令，确保Manager退出时Trader不会收到SIGHUP信号而终止
        # 使用shell执行: nohup cmd &，使命令完全脱离当前进程控制
        cmd_str = " ".join(cmd)
        shell_cmd = f"nohup {cmd_str} > /dev/null 2>&1 &"

        logger.info(f"TraderProxy [{self.account_id}] 创建子进程: {shell_cmd}")

        # 通过shell启动，使用start_new_session=True脱离控制终端
        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info(
            f"TraderProxy [{self.account_id}] 子进程守护进程已启动，Shell PID: {process.pid}"
        )
        logger.info(f"TraderProxy [{self.account_id}] Trader进程将在启动后自行写入PID文件")

        return True

    async def stop_process(self) -> bool:
        """
        停止 Trader

        停止流程：
        1. 发送SIGTERM，等待最多5x3s让进程优雅退出
        2. 若仍在运行，发送SIGKILL强制停止，并确认退出
        3. 清理残留的PID文件（SIGKILL路径下Trader无法自行清理）

        Returns:
            是否停止成功（进程确实已退出）
        """
        self._manual_stop = True  # 标记为手动停止，健康检查不告警
        current_state = self._state
        logger.info(f"TraderProxy [{self.account_id}] 开始停止，当前状态: {current_state}")

        pid = await self._get_process()
        if pid:
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGTERM)
                logger.warning(f"TraderProxy [{self.account_id}] 进程 {pid} 已发送SIGTERM")
            except ProcessLookupError:
                logger.info(f"TraderProxy [{self.account_id}] 进程 {pid} 已退出")
            except Exception as e:
                logger.warning("TraderProxy [{}] 发送SIGTERM失败: {!r}", self.account_id, e)
            # 循环检测5x3s
            for _ in range(5):
                pid = await self._get_process()
                if not pid:
                    break
                await asyncio.sleep(3)

        # SIGTERM未能停止，升级为SIGKILL
        pid = await self._get_process()
        if pid:
            logger.warning(
                f"TraderProxy [{self.account_id}] SIGTERM后进程 {pid} 仍在运行，发送SIGKILL强制停止"
            )
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.error("TraderProxy [{}] 发送SIGKILL失败: {!r}", self.account_id, e)
            # 确认进程退出
            for _ in range(5):
                pid = await self._get_process()
                if not pid:
                    break
                await asyncio.sleep(1)

        # 检查最终状态
        pid = await self._get_process()
        if not pid:
            # 清理SIGKILL路径下残留的PID文件，避免PID复用误判
            try:
                Path(self.pid_file).unlink(missing_ok=True)
            except Exception as e:
                logger.warning("TraderProxy [{}] 清理PID文件失败: {!r}", self.account_id, e)
            # 设置状态为已停止
            await self._set_state(TraderState.STOPPED)
            logger.info(f"TraderProxy [{self.account_id}] 停止完成")
            return True
        else:
            logger.error(f"TraderProxy [{self.account_id}] 停止失败，进程 {pid} 仍在运行")
            return False

    # ==================== 异步连接 ====================
    async def _connect_async(self) -> None:
        """
        后台异步连接到 Trader

        连接成功 → 状态变为 CONNECTED
        连接失败 → 状态变为 STOPPED
        """
        # 创建Socket客户端
        self.start_time = datetime.now()
        self.socket_client = SocketClient(
            self.socket_path, self.account_id or "", self._on_msg_callback
        )
        check_interval = 5
        attempt = 0
        while self._running:
            try:
                pid = await self._get_process()
                if not pid:
                    await self._set_state(TraderState.STOPPED)
                    # 进程不存在，跳过连接
                    await asyncio.sleep(check_interval)
                    continue

                if self.socket_client.is_connected():
                    # 已连接，跳过连接尝试
                    await self._set_state(TraderState.CONNECTED)
                    await asyncio.sleep(check_interval)
                    continue

                # 进程存在，且为未连接
                self.last_heartbeat = datetime.now()
                # 状态变为连接中
                await self._set_state(TraderState.CONNECTING)
                logger.info(f"TraderProxy [{self.account_id}] 尝试连接 ({attempt + 1})...")
                success = await self.socket_client.connect()
                if success:
                    logger.info(f"TraderProxy [{self.account_id}] 连接成功")
                    await self._set_state(TraderState.CONNECTED)
                    # 连接成功后立即同步一次数据
                    await self._sync_account_detail()
                    attempt = 0
                    continue
                else:
                    logger.warning(f"TraderProxy [{self.account_id}] 连接失败 ({attempt + 1})")

            except Exception:
                logger.exception("TraderProxy [{}] 连接异常 ({})", self.account_id, attempt + 1)
            # 等待重试
            await asyncio.sleep(check_interval)
        logger.warning(f"TraderProxy [{self.account_id}] 连接循环结束")

    async def _get_process(self) -> int | None:
        """
        检查进程是否存在并返回PID

        通过检查socket文件和PID文件判断

        Returns:
            进程是否存在
        """
        # 检查socket文件是否存在
        socket_file = Path(self.socket_path)
        if not socket_file.exists():
            return None

        # 检查PID文件
        pid_file = Path(self.pid_file)
        if not pid_file.exists():
            return None

        try:
            # 读取PID
            with open(pid_file) as f:
                pid = int(f.read().strip())

            # 检查进程是否运行
            try:
                os.kill(pid, 0)  # 检查进程是否存在，不发送信号
                return pid
            except OSError:
                # 清理过期的PID文件
                pid_file.unlink(missing_ok=True)
                return None

        except Exception as e:
            logger.warning("TraderProxy [{}] 检查进程失败: {!r}", self.account_id, e)
            return None

    # ==================== 消息处理 ====================
    def _load_account_from_db(self) -> None:
        """从DB加载账户数据到内存缓存（初始化时调用一次，异步任务执行）"""
        try:
            asyncio.get_running_loop()
            task = asyncio.create_task(self._load_account_from_db_async())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            # 无事件循环（测试等场景），跳过
            pass

    async def _load_account_from_db_async(self) -> None:
        """异步加载账户数据"""
        try:
            from sqlalchemy import select

            from qtrader.models.po import AccountPo
            from qtrader.utils.async_database import get_async_database

            db = get_async_database()
            if not db:
                return

            async with db.get_session() as session:
                account_po = await session.scalar(
                    select(AccountPo).filter_by(account_id=self.account_id)
                )
                if account_po:
                    self._account_cache = AccountData.model_construct(
                        account_id=str(account_po.account_id),
                        balance=float(account_po.balance) if account_po.balance else 0,
                        available=float(account_po.available) if account_po.available else 0,
                        margin=float(account_po.margin) if account_po.margin else 0,
                        hold_profit=(
                            float(account_po.position_profit) if account_po.position_profit else 0
                        ),
                        close_profit=(
                            float(account_po.close_profit) if account_po.close_profit else 0
                        ),
                        risk_ratio=float(account_po.risk_ratio) if account_po.risk_ratio else 0,
                        md_connected=False,
                        td_connected=False,
                        risk_status={},
                    )
                    logger.info(f"TraderProxy [{self.account_id}] 从DB加载账户数据成功")
        except Exception as e:
            logger.warning("TraderProxy [{}] 从DB加载账户数据失败: {!r}", self.account_id, e)

    async def _sync_account_detail(self) -> None:
        """
        从Trader同步完整账户数据（账户、持仓、挂单、成交、行情）

        通过 get_account_details RPC接口一次性获取所有数据
        """
        try:
            if not self.socket_client or not self.socket_client.is_connected():
                return

            data = await self.socket_client.request("get_account_details", {}, timeout=10.0)
            if not data or not isinstance(data, dict):
                logger.warning(f"TraderProxy [{self.account_id}] 获取完整数据失败")
                return

            # 更新账户缓存
            account_data = data.get("account")
            if account_data:
                self._account_cache = AccountData.model_validate(account_data)
                self._emit_data("account", self._account_cache.model_dump())

            # 更新持仓缓存
            positions_data = data.get("positions", [])
            if isinstance(positions_data, list):
                self._position_cache.clear()
                for pos in positions_data:
                    if isinstance(pos, dict) and pos.get("symbol"):
                        self._position_cache[pos["symbol"]] = PositionData.model_validate(pos)

            # 更新订单缓存
            orders_data = data.get("orders", [])
            if isinstance(orders_data, list):
                for order in orders_data:
                    if isinstance(order, dict) and order.get("order_id"):
                        self._order_cache[order["order_id"]] = OrderData.model_validate(order)

            # 更新成交缓存
            trades_data = data.get("trades", [])
            if isinstance(trades_data, list):
                self._trade_cache.clear()
                for trade in trades_data:
                    if isinstance(trade, dict) and trade.get("trade_id"):
                        self._trade_cache[trade["trade_id"]] = TradeData.model_validate(trade)

            # 更新行情缓存
            quotes_data = data.get("quotes", [])
            if isinstance(quotes_data, list):
                for quote in quotes_data:
                    symbol = quote.get("symbol") if isinstance(quote, dict) else None
                    if symbol:
                        self._tick_cache[symbol] = quote

            logger.info(
                f"TraderProxy [{self.account_id}] 完整数据同步完成: "
                f"持仓={len(self._position_cache)}, 挂单={len(orders_data)}, "
                f"成交={len(self._trade_cache)}, 行情={len(self._tick_cache)}"
            )

        except Exception:
            logger.exception("TraderProxy [{}] 同步完整数据失败", self.account_id)

    def _update_heartbeat(self) -> None:
        """更新心跳时间"""
        self.last_heartbeat = datetime.now()

    def _on_msg_callback(self, msg_type: str, data: dict[str, Any]) -> None:
        """
        统一的消息回调接口

        Args:
            msg_type: 消息类型 (heartbeat, tick, account, order, trade, position等)
            data: 消息数据
        """
        try:
            if msg_type == "heartbeat":
                self._update_heartbeat()
            elif msg_type == "tick":
                # 缓存最新行情，用于本地计算盈亏
                symbol = data.get("symbol")
                if not symbol:
                    return
                self._tick_cache[symbol] = data
                # 推送行情到前端
                self._emit_data("tick", data)
                # 根据tick刷新持仓缓存盈亏并推送
                self.update_hold_profit(TickData.model_validate(data))
            elif msg_type == "tick_batch":
                # 批量tick推送：更新缓存、计算盈亏、推送账户、批量推送行情
                ticks = data.get("ticks", [])
                account_data = data.get("account")
                if ticks:
                    for tick_dict in ticks:
                        symbol = tick_dict.get("symbol")
                        if symbol:
                            self._tick_cache[symbol] = tick_dict
                            with contextlib.suppress(Exception):
                                self.update_hold_profit(TickData.model_validate(tick_dict))
                    # 批量推送给前端
                    self._emit_data("tick_batch", {"ticks": ticks, "account_id": self.account_id})
                # 如果携带账户数据，更新缓存并推送
                if account_data and isinstance(account_data, dict):
                    self._account_cache = AccountData.model_validate(account_data)
                    # 限制账户推送推送间隔2秒
                    if (
                        self._account_cache_time is None
                        or (datetime.now() - self._account_cache_time).seconds >= 2
                    ):
                        self._account_cache_time = datetime.now()
                        self._emit_data("account", self._account_cache.model_dump())
            elif msg_type == "account":
                # Trader推送完整账户数据（网关状态变化时），直接更新缓存
                self._handle_account_update(data)
            elif msg_type == "order":
                # 更新订单缓存并推送
                if isinstance(data, dict) and data.get("order_id"):
                    self._order_cache[data["order_id"]] = OrderData.model_validate(data)
                self._emit_data("order", data)
            elif msg_type == "trade":
                # 更新成交缓存并推送
                if isinstance(data, dict) and data.get("trade_id"):
                    self._trade_cache[data["trade_id"]] = TradeData.model_validate(data)
                self._emit_data("trade", data)
            elif msg_type == "position":
                # 更新持仓缓存并推送
                if isinstance(data, dict) and data.get("symbol"):
                    self._position_cache[data["symbol"]] = PositionData.model_validate(data)
                self._emit_data("position", data)
            elif msg_type == "trader_ready":
                # Trader就绪通知，触发全量同步
                self._handle_trader_ready_push(data)
            elif msg_type == "notify":
                # 通知告警，交给AlarmService处理
                self._handle_notify_push(data)
            else:
                self._emit_data(msg_type, data)
        except Exception:
            logger.exception("处理消息 [{}] 时出错", msg_type)

    @logger.catch(message="处理账户状态推送失败")
    def _handle_account_update(self, data: dict[str, Any]) -> None:
        """
        处理Trader推送的完整账户状态数据

        网关连接/断开时，Trader会推送完整的AccountData，
        包含 balance, available, md_connected, td_connected 等全部字段。
        直接更新内存缓存并推送给前端。

        Args:
            data: 完整的账户数据字典
        """
        # 直接用推送数据更新缓存
        self._account_cache = AccountData.model_validate(data)
        # 推送给前端
        self._emit_data("account", self._account_cache.model_dump())
        md = data.get("md_connected", False)
        td = data.get("td_connected", False)
        logger.info(f"账户状态已更新并推送: {self.account_id}, md={md}, td={td}")

    @logger.catch(message="处理Trader就绪通知失败")
    def _handle_trader_ready_push(self, data: dict[str, Any]) -> None:
        """
        处理Trader就绪通知

        Trader就绪（TD和MD连接成功，初始数据加载完成）后触发全量同步
        """
        logger.info(f"Trader [{self.account_id}] 就绪通知收到，准备全量同步")

        # 延迟1秒后执行全量同步，确保Trader数据已准备就绪
        async def delayed_sync() -> None:
            await asyncio.sleep(1)
            await self._sync_account_detail()

        task = asyncio.create_task(delayed_sync())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @logger.catch(message="处理通知推送失败")
    def _handle_notify_push(self, data: dict[str, Any]) -> None:
        """
        处理Trader推送的通知告警

        Args:
            data: 通知数据
        """
        from qtrader.app_context import get_app_context

        ctx = get_app_context()
        if not ctx:
            logger.warning("应用上下文未初始化，无法处理通知")
            return
        alarm_service = ctx.get_alarm_service()
        if not alarm_service:
            logger.warning("告警服务未初始化，无法处理通知")
            return
        # 异步处理通知（notify_alarm 为同步方法，走默认线程池避免阻塞事件循环）
        from qtrader.utils.executors import submit_task

        account_id = data.get("account_id", "SYSTEM")
        title = data.get("title", "")
        detail = data.get("detail", "")
        task = asyncio.create_task(
            submit_task(alarm_service.notify_alarm, account_id, "Trader", title, detail)
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _emit_data(self, data_type: str, data: dict[str, Any]) -> None:
        """
        提交到事件驱动中

        Args:
            data_type: 数据类型
            data: 数据
        """
        event_type = None
        if data_type == "account":
            event_type = EventTypes.ACCOUNT_UPDATE
            if isinstance(data, dict) and "update_time" in data:
                data = {**data, "updated_at": data["update_time"]}
            data["status"] = self._state
        elif data_type == "order":
            event_type = EventTypes.ORDER_UPDATE
        elif data_type == "trade":
            event_type = EventTypes.TRADE_UPDATE
        elif data_type == "position":
            event_type = EventTypes.POSITION_UPDATE
            # PositionData 的 account_id 为缺失字段、pos_long/pos_short 为计算属性，model_dump 均不包含；
            # 前端整行替换并按这些字段展示，需在此补全
            data["account_id"] = self.account_id
            data.setdefault(
                "pos_long", (data.get("pos_long_td") or 0) + (data.get("pos_long_yd") or 0)
            )
            data.setdefault(
                "pos_short", (data.get("pos_short_td") or 0) + (data.get("pos_short_yd") or 0)
            )
        elif data_type == "tick":
            event_type = EventTypes.TICK_UPDATE
        elif data_type == "tick_batch":
            event_type = EventTypes.TICK_BATCH_UPDATE
        elif data_type == "alarm":
            # 告警类型：保存到数据库并触发事件
            self._handle_alarm_data(data)
            return

        if event_type:
            event_engine = ctx.get_event_engine()
            if event_engine:
                event_engine.put(event_type, data)
                logger.debug(f"推送事件 [{event_type}] 从Trader [{self.account_id}]")

    def _handle_alarm_data(self, data: dict[str, Any]) -> None:
        """
        处理异常告警数据（来自Trader的ERROR日志）

        异步保存异常记录到数据库，交由AlarmService的定时任务统计阈值
        并触发告警更新事件推送前端

        Args:
            data: 告警数据
        """
        task = asyncio.create_task(self._save_alarm_data_async(data))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @logger.catch(message="处理告警数据失败")
    async def _save_alarm_data_async(self, data: dict[str, Any]) -> None:
        """异步保存异常告警到数据库"""
        from datetime import datetime

        from qtrader.models.object import AlarmType
        from qtrader.models.po import AlarmPo
        from qtrader.utils.async_database import get_async_database

        db = get_async_database()
        if db is None:
            logger.error("数据库未初始化，无法保存告警")
            return

        async with db.get_session() as session:
            now = datetime.now()
            alarm = AlarmPo(
                account_id=data.get("account_id", self.account_id),
                alarm_type=AlarmType.EXCEPTION,  # 标记为异常类型
                alarm_date=data.get("alarm_date", now.strftime("%Y-%m-%d")),
                alarm_time=data.get("alarm_time", now.strftime("%H:%M:%S")),
                source=data.get("source", "TRADER"),
                title=data.get("title"),
                detail=data.get("detail"),
                status=data.get("status", "UNCONFIRMED"),
            )
            session.add(alarm)
            await session.commit()
            await session.refresh(alarm)
            logger.info(f"异常告警已保存到数据库: [{self.account_id}] {alarm.title}")

    async def _periodic_sync_loop(self) -> None:
        """定时从Trader同步全量数据（兜底机制）"""
        self._sync_interval = 60.0
        # 循环体内部判断连接状态：任务构造时状态为 STOPPED，若写在 while 条件里首轮即退出，兜底永不生效
        while self._running:
            try:
                await asyncio.sleep(self._sync_interval)
                if not self._is_state(TraderState.CONNECTED):
                    continue
                if not self.socket_client or not self.socket_client.is_connected():
                    logger.debug(f"TraderProxy [{self.account_id}] 未连接，跳过本次定时同步")
                    continue
                await self._sync_account_detail()
                logger.info(f"TraderProxy [{self.account_id}] 定时全量同步完成")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("TraderProxy [{}] 定时同步失败", self.account_id)

    def update_hold_profit(self, tick: TickData) -> None:
        """更新所有持仓的盈亏"""
        if not tick or not tick.last_price or tick.last_price <= 0 or self._account_cache is None:
            return

        symbol = tick.symbol
        pos = self._position_cache.get(symbol)
        if not pos:
            return

        try:
            multiple = pos.multiple or 1
            last_price = tick.last_price
            # 计算多头盈亏
            pos_long = (pos.pos_long_td or 0) + (pos.pos_long_yd or 0)
            hold_price_long = pos.hold_price_long or 0
            if pos_long > 0 and hold_price_long > 0:
                pos.hold_profit_long = (last_price - hold_price_long) * pos_long * multiple

            # 计算空头盈亏
            pos_short = (pos.pos_short_td or 0) + (pos.pos_short_yd or 0)
            hold_price_short = pos.hold_price_short or 0
            if pos_short > 0 and hold_price_short > 0:
                pos.hold_profit_short = (hold_price_short - last_price) * pos_short * multiple

            pos.updated_at = datetime.now()
        except Exception:
            logger.exception("更新持仓盈亏失败: {}", tick.symbol)
        try:
            # 推送判断
            now = time.monotonic()
            last_time = self._last_position_push_time.get(symbol)
            if last_time is not None and (now - last_time) < self._ws_push_interval:
                return
            self._last_position_push_time[symbol] = now
            self._emit_data("position", pos.model_dump())
        except Exception:
            logger.exception("Tick驱动持仓/账户推送失败 [{}]", tick.symbol)

    def _recalc_position_profit(self, pos: PositionData, last_price: float) -> PositionData:
        """根据最新价格重新计算持仓盈亏"""
        if not last_price or last_price <= 0:
            return pos

        # 获取合约乘数（从tick缓存中获取，如果没有则使用默认值）
        symbol = pos.symbol
        tick = self._tick_cache.get(symbol, {})
        multiple = tick.get("volume_multiple", 1)

        # 计算多头盈亏
        pos_long = (pos.pos_long_td or 0) + (pos.pos_long_yd or 0)
        hold_price_long = pos.hold_price_long or 0
        if pos_long > 0 and hold_price_long > 0:
            pos.hold_profit_long = (last_price - hold_price_long) * pos_long * multiple

        # 计算空头盈亏
        pos_short = (pos.pos_short_td or 0) + (pos.pos_short_yd or 0)
        hold_price_short = pos.hold_price_short or 0
        if pos_short > 0 and hold_price_short > 0:
            pos.hold_profit_short = (hold_price_short - last_price) * pos_short * multiple

        return pos

    # ==================== 数据同步接口 ====================

    async def sync_all(self) -> dict[str, Any]:
        """
        手动触发全量同步：账户+持仓+挂单+成交+行情

        从Trader进程一次性拉取完整数据，刷新所有内存缓存。

        Returns:
            同步结果字典
        """
        if not self.socket_client or not self.socket_client.is_connected():
            return {"success": False, "message": "未连接到Trader"}

        try:
            await self._sync_account_detail()
            logger.info(f"TraderProxy [{self.account_id}] 手动全量同步完成")
            return {
                "success": True,
                "message": "同步成功",
                "account_id": self.account_id,
                "positions": len(self._position_cache),
                "orders": len(self._order_cache),
                "trades": len(self._trade_cache),
                "quotes": len(self._tick_cache),
            }
        except Exception as e:
            logger.exception("TraderProxy [{}] 全量同步失败", self.account_id)
            return {"success": False, "message": f"同步失败: {e}"}

    # ==================== 数据查询接口 ====================

    async def get_account(self) -> AccountData | None:
        """获取账户数据 - 优先从Trader实时查询，未连接时使用缓存

        内存缓存由以下途径维护：
        1. 初始化时从DB加载
        2. 连接Trader成功后IPC同步
        3. Trader推送的account消息更新
        """
        # 优先从Trader实时查询
        if self.socket_client and self.socket_client.is_connected():
            try:
                data = await self.socket_client.request("get_account", {}, timeout=5.0)
                if data and isinstance(data, dict):
                    if self._account_cache:
                        merged = self._account_cache.model_dump()
                        merged.update(data)
                        account_data = AccountData.model_validate(merged)
                    else:
                        account_data = AccountData.model_validate(data)
                    # 更新缓存
                    self._account_cache = account_data
                    account_data.status = TraderState.CONNECTED
                    return account_data
            except Exception as e:
                logger.warning(
                    "TraderProxy [{}] 从Trader查询账户数据失败: {!r}",
                    self.account_id,
                    e,
                )

        # Trader未连接或查询失败，使用缓存
        if self._account_cache:
            account_data = self._account_cache.model_copy()
            account_data.status = (
                TraderState.CONNECTED if self._is_state(TraderState.CONNECTED) else self._state
            )
            return account_data
        return AccountData.model_construct(
            account_id=self.account_id or "",
            status=TraderState.CONNECTED if self._is_state(TraderState.CONNECTED) else self._state,
        )

    def get_account_cached(self) -> AccountData | None:
        """获取缓存的账户数据（不走RPC）"""
        if self._account_cache:
            account_data = self._account_cache.model_copy()
            account_data.status = (
                TraderState.CONNECTED if self._is_state(TraderState.CONNECTED) else self._state
            )
            return account_data
        return AccountData.model_construct(
            account_id=self.account_id or "",
            status=TraderState.CONNECTED if self._is_state(TraderState.CONNECTED) else self._state,
        )

    async def get_order(self, order_id: str) -> OrderData | None:
        """获取订单数据 - 优先从Trader实时查询，未连接时使用缓存"""
        return self._order_cache.get(order_id)

    async def get_orders(self) -> list[OrderData]:
        """获取所有订单数据 - 优先从Trader实时查询，未连接时使用缓存"""
        if self.socket_client and self.socket_client.is_connected():
            try:
                data = await self.socket_client.request("get_orders", {}, timeout=5.0)
                if isinstance(data, list):
                    self._order_cache.clear()
                    for order in data:
                        if isinstance(order, dict) and order.get("order_id"):
                            self._order_cache[order["order_id"]] = OrderData.model_validate(order)
            except Exception as e:
                logger.warning(
                    "TraderProxy [{}] 从Trader查询订单数据失败: {!r}",
                    self.account_id,
                    e,
                )
        return list(self._order_cache.values())

    async def get_active_orders(self) -> list[OrderData]:
        """获取活动订单 - 优先从Trader实时查询，未连接时使用缓存"""
        orders = await self.get_orders()
        return [item for item in orders if item.is_active()]

    async def get_trade(self, trade_id: str) -> TradeData | None:
        """获取成交数据 - 从内存缓存返回"""
        return self._trade_cache.get(trade_id)

    async def get_trades(self) -> list[TradeData]:
        """获取所有成交数据 - 从内存缓存返回"""
        return list(self._trade_cache.values())

    async def get_positions(self) -> list[PositionData]:
        """获取持仓列表 - 优先从Trader实时查询，未连接时使用缓存"""
        if self.socket_client and self.socket_client.is_connected():
            try:
                data = await self.socket_client.request("get_positions", {}, timeout=5.0)
                if isinstance(data, list):
                    self._position_cache.clear()
                    for pos in data:
                        if isinstance(pos, dict) and pos.get("symbol"):
                            self._position_cache[pos["symbol"]] = PositionData.model_validate(pos)
            except Exception as e:
                logger.warning(
                    "TraderProxy [{}] 从Trader查询持仓数据失败: {!r}",
                    self.account_id,
                    e,
                )
        return list(self._position_cache.values())

    async def get_quotes(self) -> list[TickData]:
        """获取所有行情数据 - 从内存缓存返回"""
        return [TickData(**item) for item in self._tick_cache.values()]

    async def get_quotes_from_trader(self) -> list[TickData]:
        """实时从Trader进程获取行情数据（IPC）"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_quotes", {}, timeout=5.0)
        if data:
            items = cast(list[dict[str, Any]], data)
            return [TickData(**item) for item in items]
        return []

    async def get_jobs(self) -> list[Job]:
        """实时获取所有任务数据"""
        if not self.socket_client:
            return []
        data = await self.socket_client.request("get_jobs", {}, timeout=5.0)
        if data:
            items = cast(list[dict[str, Any]], data)
            return [Job(**item) for item in items]
        return []

    async def send_request(
        self, request_type: str, data: dict[str, Any], timeout: float = 10.0
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
            logger.error("TraderProxy [{}] 请求失败 [{}]: {!r}", self.account_id, request_type, e)
            return None

    # ==================== 交易接口 ====================

    async def send_order_request(
        self, symbol: str, direction: str, offset: str, volume: int, price: float = 0
    ) -> str | None:
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

        except Exception:
            # 记录后重新抛出：异常消息即 Trader 回传的真实失败原因（如非交易时段拦截），
            # 由路由层转换为前端错误提示
            logger.exception("TraderProxy [{}] 下单请求失败", self.account_id)
            raise

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

            response = await self.socket_client.request("cancel_req", request_data, timeout=10.0)
            return bool(response)

        except Exception:
            # 记录后重新抛出，由路由层转换为前端错误提示
            logger.exception("TraderProxy [{}] 撤单请求失败", self.account_id)
            raise

    async def subscribe(self, request_data: dict[str, Any]) -> bool:
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

        except Exception:
            # 记录后重新抛出，由路由层转换为前端错误提示
            logger.exception("TraderProxy [{}] 订阅请求失败", self.account_id)
            raise

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
            # 记录后重新抛出，由路由层转换为前端错误提示
            logger.error("TraderProxy [{}] 连接网关请求失败: {!r}", self.account_id, e)
            raise

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
            response = await self.socket_client.request("disconnect_gateway", {}, timeout=10.0)
            return bool(response)
        except Exception as e:
            # 记录后重新抛出，由路由层转换为前端错误提示
            logger.error("TraderProxy [{}] 断开网关请求失败: {!r}", self.account_id, e)
            raise

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
            logger.error("TraderProxy [{}] 暂停交易请求失败: {!r}", self.account_id, e)
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
            logger.error("TraderProxy [{}] 恢复交易请求失败: {!r}", self.account_id, e)
            return False

    async def reload_risk_config(self) -> bool:
        """
        通知 Trader 从共享数据库重新加载风控配置

        Returns:
            是否成功发送请求
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.warning(
                f"TraderProxy [{self.account_id}] 未连接到Trader，风控配置将在Trader重启后生效"
            )
            return False

        try:
            response = await self.socket_client.request("reload_risk_config", {}, timeout=10.0)
            return bool(response)
        except Exception as e:
            logger.error("TraderProxy [{}] 重载风控配置请求失败: {!r}", self.account_id, e)
            return False

    async def update_alert_wechat(self, alert_wechat: bool) -> bool:
        """
        更新微信告警配置（已废弃，请使用 update_alert_config）

        通过socket发送请求到远程Trader

        Args:
            alert_wechat: 是否启用微信告警

        Returns:
            是否成功
        """
        logger.warning("update_alert_wechat 已废弃，请使用 update_alert_config")
        config = {
            "immediate": alert_wechat,
            "threshold": alert_wechat,
        }
        return await self.update_alert_config(config)

    async def get_alert_wechat(self) -> bool | None:
        """
        获取微信告警配置（已废弃，请使用 get_alert_config）

        通过socket发送请求到远程Trader

        Returns:
            alert_wechat 值，失败返回 None
        """
        logger.warning("get_alert_wechat 已废弃，请使用 get_alert_config")
        config = await self.get_alert_config()
        if config:
            return bool(config.get("immediate", False) or config.get("threshold", False))
        return None

    async def update_alert_config(self, config: dict[str, Any]) -> bool:
        """
        更新告警配置

        通过socket发送请求到远程Trader

        Args:
            config: 告警配置字典

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送更新请求")
            return False

        try:
            response = await self.socket_client.request("update_alert_config", config, timeout=10.0)
            return response is not None
        except Exception as e:
            logger.error("TraderProxy [{}] 更新告警配置请求失败: {!r}", self.account_id, e)
            return False

    async def get_alert_config(self) -> (dict[str, Any]) | None:
        """
        获取告警配置

        通过socket发送请求到远程Trader

        Returns:
            告警配置字典，失败返回 None
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送获取请求")
            return None

        try:
            response = await self.socket_client.request("get_alert_config", {}, timeout=10.0)
            if isinstance(response, dict):
                return response
            return None
        except Exception as e:
            logger.error("TraderProxy [{}] 获取告警配置请求失败: {!r}", self.account_id, e)
            return None

    async def update_strategy_params(
        self, strategy_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
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
            logger.error("TraderProxy [{}] 更新策略参数请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def update_strategy_signal(
        self, strategy_id: str, signal: dict[str, Any]
    ) -> dict[str, Any]:
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
            logger.error("TraderProxy [{}] 更新策略信号请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def clear_strategy_signal(self, strategy_id: str) -> dict[str, Any]:
        """
        清除策略信号（无信号状态）

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送清除请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "clear_strategy_signal",
                {"strategy_id": strategy_id},
                timeout=10.0,
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error("TraderProxy [{}] 清除策略信号请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def update_strategy_position(
        self, strategy_id: str, position: dict[str, Any]
    ) -> dict[str, Any]:
        """
        更新策略持仓

        通过socket发送请求到远程Trader

        Args:
            strategy_id: 策略ID
            position: 持仓数据 {pos_long, pos_short, pos_price}

        Returns:
            更新结果
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送更新请求")
            return {"success": False, "message": "未连接"}

        try:
            response = await self.socket_client.request(
                "update_strategy_position",
                {"strategy_id": strategy_id, "position": position},
                timeout=10.0,
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error("TraderProxy [{}] 更新策略持仓请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def set_strategy_trading_status(
        self, strategy_id: str, status: dict[str, Any]
    ) -> dict[str, Any]:
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
                "set_strategy_trading_status",
                {"strategy_id": strategy_id, "status": status},
                timeout=10.0,
            )
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error("TraderProxy [{}] 设置策略交易状态请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def enable_strategy(self, strategy_id: str) -> dict[str, Any]:
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
            logger.error("TraderProxy [{}] 启用策略请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def disable_strategy(self, strategy_id: str) -> dict[str, Any]:
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
            logger.error("TraderProxy [{}] 禁用策略请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def init_strategy(self, strategy_id: str) -> dict[str, Any]:
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
            logger.error("TraderProxy [{}] 初始化策略请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def get_strategy_order_cmds(self, strategy_id: str, status: str | None) -> list[Any]:
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
            logger.error("TraderProxy [{}] 获取策略报单指令请求失败: {!r}", self.account_id, e)
            return []

    # ==================== 任务管理接口 ====================

    async def trigger_job(self, job_id: str) -> bool:
        """
        手动触发定时任务

        通过socket发送请求到远程Trader

        Args:
            job_id: 任务ID

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送触发任务请求")
            return False

        try:
            response = await self.socket_client.request(
                "trigger_job", {"job_id": job_id}, timeout=10.0
            )
            return bool(response)
        except Exception as e:
            logger.error("TraderProxy [{}] 触发任务请求失败: {!r}", self.account_id, e)
            return False

    async def toggle_job(self, job_id: str, enabled: bool) -> bool:
        """
        切换任务启用状态

        通过socket发送请求到远程Trader

        Args:
            job_id: 任务ID
            enabled: 是否启用

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(
                f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送切换任务状态请求"
            )
            return False

        try:
            response = await self.socket_client.request(
                "toggle_job", {"job_id": job_id, "enabled": enabled}, timeout=10.0
            )
            return bool(response)
        except Exception as e:
            logger.error("TraderProxy [{}] 切换任务状态请求失败: {!r}", self.account_id, e)
            return False

    async def pause_job(self, job_id: str) -> bool:
        """
        暂停任务

        通过socket发送请求到远程Trader

        Args:
            job_id: 任务ID

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送暂停任务请求")
            return False

        try:
            response = await self.socket_client.request(
                "pause_job", {"job_id": job_id}, timeout=10.0
            )
            return bool(response)
        except Exception as e:
            logger.error("TraderProxy [{}] 暂停任务请求失败: {!r}", self.account_id, e)
            return False

    async def resume_job(self, job_id: str) -> bool:
        """
        恢复任务

        通过socket发送请求到远程Trader

        Args:
            job_id: 任务ID

        Returns:
            是否成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法发送恢复任务请求")
            return False

        try:
            response = await self.socket_client.request(
                "resume_job", {"job_id": job_id}, timeout=10.0
            )
            return bool(response)
        except Exception as e:
            logger.error("TraderProxy [{}] 恢复任务请求失败: {!r}", self.account_id, e)
            return False

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

    def is_running(self) -> bool:
        """检查是否运行中"""
        return not self._is_state(TraderState.STOPPED)

    @property
    def manual_stop(self) -> bool:
        """是否为手动停止（手动停止不触发故障告警）"""
        return self._manual_stop

    def is_alive(self) -> bool:
        """检查子进程是否存活"""
        # 自己创建的进程，检查PID是否存活
        if self._created_process:
            pid = self._get_pid()
            if pid:
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False
            return False
        # 非自己创建的进程，通过心跳判断
        if not self._is_state(TraderState.STOPPED):
            heartbeat_age = (datetime.now() - self.last_heartbeat).total_seconds()
            return heartbeat_age < self.heartbeat_timeout
        return False

    def _get_pid(self) -> int | None:
        """获取PID，从 PID 文件读取"""
        pid_file = Path(self.pid_file)
        if pid_file.exists():
            try:
                return int(pid_file.read_text().strip())
            except (ValueError, OSError):
                pass
        return None

    def get_status(self) -> dict[str, Any]:
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
            "pid": self._get_pid(),
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
            logger.error("TraderProxy [{}] 心跳请求失败: {!r}", self.account_id, e)
            return False

    async def export_positions(self) -> dict[str, Any]:
        """
        请求 Trader 导出持仓到 CSV

        Returns:
            {"success": bool, "message": str}
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法导出持仓")
            return {"success": False, "message": "未连接到Trader"}

        try:
            response = await self.socket_client.request("export_positions", {}, timeout=10.0)
            if isinstance(response, dict):
                return response
            return {"success": bool(response), "message": "导出完成"}
        except Exception as e:
            logger.error("TraderProxy [{}] 导出持仓请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def refresh_contracts(self) -> dict[str, Any]:
        """
        强制刷新合约信息

        Returns:
            {"success": bool, "message": str}
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法刷新合约信息")
            return {"success": False, "message": "未连接到Trader"}

        try:
            response = await self.socket_client.request("refresh_contracts", {}, timeout=30.0)
            return response or {"success": False, "message": "无响应"}
        except Exception as e:
            logger.error("TraderProxy [{}] 刷新合约信息请求失败: {!r}", self.account_id, e)
            return {"success": False, "message": f"请求失败: {e}"}

    async def push_public_data(self, contracts: list[dict[str, Any]]) -> bool:
        """
        推送公共数据（合约信息）给 Trader 进程

        Manager 在检测到 Trader 启动后调用此方法，将共享数据库中的
        合约信息主动推送给 Trader，使 Trader 无需自行从网关拉取。

        Args:
            contracts: 合约信息字典列表

        Returns:
            是否推送成功
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法推送公共数据")
            return False

        try:
            response = await self.socket_client.request(
                "init_public_data",
                {"contracts": contracts},
                timeout=30.0,
            )
            return bool(response)
        except Exception as e:
            logger.error("TraderProxy [{}] 推送公共数据失败: {!r}", self.account_id, e)
            return False

    async def get_contracts(self) -> list[dict[str, Any]]:
        """
        获取合约列表

        从 Trader 进程的内存中获取合约信息

        Returns:
            合约信息字典列表
        """
        if not self.socket_client or not self.socket_client.is_connected():
            logger.error(f"TraderProxy [{self.account_id}] 未连接到Trader，无法获取合约信息")
            return []

        try:
            response = await self.socket_client.request("get_contracts", {}, timeout=10.0)
            if response is None:
                return []
            # 如果返回的是列表，直接返回
            if isinstance(response, list):
                return response
            # 如果返回的是字典，包装成列表
            if isinstance(response, dict):
                return [response]
            return []
        except Exception as e:
            logger.error("TraderProxy [{}] 获取合约列表请求失败: {!r}", self.account_id, e)
            return []
