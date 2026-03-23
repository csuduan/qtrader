"""
Trader进程启动监控器
使用watchdog监听socket目录，当检测到新的socket文件创建时触发回调
用于感知Trader进程的启动，以便及时推送公共数据（合约信息等）
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from src.utils.logger import get_logger

logger = get_logger(__name__)

# socket文件名格式：qtrader_{account_id}.sock
_SOCKET_PATTERN = re.compile(r"^qtrader_(.+)\.sock$")


class TraderMonitor:
    """
    Trader进程启动监控器

    监听socket目录中的文件创建事件，当检测到新的 qtrader_{account_id}.sock
    文件被创建时，触发回调通知Manager推送公共数据给该Trader。

    使用watchdog的Observer+EventHandler实现跨平台文件系统监听。
    """

    def __init__(
        self,
        socket_dir: str,
        on_trader_started: Callable[[str], None],
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """
        初始化监控器

        Args:
            socket_dir: 监听的socket目录路径
            on_trader_started: Trader启动时的回调，参数为account_id
            loop: 事件循环，用于将watchdog线程中的事件调度到异步上下文
        """
        self.socket_dir = Path(socket_dir).expanduser().resolve()
        self.on_trader_started = on_trader_started
        self._loop = loop or asyncio.get_event_loop()
        self._observer = None
        self._running = False
        # 记录已经触发过的socket文件，避免重复触发
        self._seen_sockets: Set[str] = set()

    def start(self) -> None:
        """启动文件监听器"""
        try:
            from watchdog.events import FileSystemEventHandler, FileCreatedEvent
            from watchdog.observers import Observer
        except ImportError:
            logger.error(
                "未安装 watchdog 库，TraderMonitor 无法启动。请执行: pip install watchdog"
            )
            return

        self.socket_dir.mkdir(parents=True, exist_ok=True)

        # 扫描已存在的socket文件（处理Manager重启时Trader已经在运行的情况）
        self._scan_existing_sockets()

        monitor = self

        class _SocketEventHandler(FileSystemEventHandler):
            def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
                if event.is_directory:
                    return
                file_path = Path(event.src_path)
                monitor._on_file_created(file_path)

        self._observer = Observer()
        self._observer.schedule(
            _SocketEventHandler(), str(self.socket_dir), recursive=False
        )
        self._observer.start()
        self._running = True
        logger.info(f"TraderMonitor 已启动，监听目录: {self.socket_dir}")

    def stop(self) -> None:
        """停止文件监听器"""
        self._running = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception as e:
                logger.warning(f"TraderMonitor 停止异常: {e}")
            self._observer = None
        logger.info("TraderMonitor 已停止")

    def _scan_existing_sockets(self) -> None:
        """
        扫描已存在的socket文件
        处理Manager重启后、Trader进程已运行的情况
        """
        try:
            for file_path in self.socket_dir.iterdir():
                if file_path.is_file():
                    self._on_file_created(file_path, is_existing=True)
        except Exception as e:
            logger.warning(f"扫描已有socket文件失败: {e}")

    def _on_file_created(self, file_path: Path, is_existing: bool = False) -> None:
        """
        处理文件创建事件

        Args:
            file_path: 新创建的文件路径
            is_existing: 是否是已存在的文件（Manager重启扫描时）
        """
        match = _SOCKET_PATTERN.match(file_path.name)
        if not match:
            return

        account_id = match.group(1)
        socket_key = str(file_path)

        if socket_key in self._seen_sockets:
            return
        self._seen_sockets.add(socket_key)

        action = "发现已存在" if is_existing else "检测到新建"
        logger.info(f"TraderMonitor: {action} socket文件，账户: {account_id} -> {file_path.name}")

        # 将回调调度到事件循环（watchdog在独立线程中运行）
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._dispatch_trader_started(account_id), self._loop
            )
        else:
            logger.warning(f"TraderMonitor: 事件循环未运行，无法触发回调 [{account_id}]")

    async def _dispatch_trader_started(self, account_id: str) -> None:
        """
        在事件循环中调度 on_trader_started 回调

        Args:
            account_id: Trader的账户ID
        """
        try:
            if asyncio.iscoroutinefunction(self.on_trader_started):
                await self.on_trader_started(account_id)
            else:
                self.on_trader_started(account_id)
        except Exception as e:
            logger.exception(f"TraderMonitor: 触发 on_trader_started 回调失败 [{account_id}]: {e}")

    def forget_socket(self, account_id: str) -> None:
        """
        从已见集合中移除指定账户的socket记录
        当Trader进程停止后调用，使下次启动时能重新触发回调

        Args:
            account_id: 账户ID
        """
        socket_name = f"qtrader_{account_id}.sock"
        socket_key = str(self.socket_dir / socket_name)
        self._seen_sockets.discard(socket_key)
        logger.debug(f"TraderMonitor: 已清除 [{account_id}] 的socket记录")
