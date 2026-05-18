"""
Manager 进程健康检查守护脚本

每10秒检查一次 Manager 进程状态（PID文件+ /health 接口），
连续6次检查失败则发送企业微信告警通知。

用法：
    python run_health.py

配置（从 config.yaml 加载）：
    - api.host / api.port: Manager API 地址
    - socket.socket_dir: PID 文件目录
    - paths.logs: 日志目录
"""

import os
import signal
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import requests

from qtrader.utils.config_loader import get_config_loader
from qtrader.utils.logger import get_logger, setup_logger
from qtrader.utils.wecomm import send_wechat

# ==================== 配置 ====================

CHECK_INTERVAL = 10  # 检查间隔（秒）
MAX_FAILURES = 6  # 最大连续失败次数
MAX_ALERTS = 3  # 最大连续告警次数（告警压制阈值）
PID_FILE_NAME = "qtrader_manager.pid"  # Manager PID 文件名

# ==================== 全局状态 ====================

consecutive_failures = 0  # 连续失败次数
consecutive_alerts = 0  # 连续告警次数（用于告警压制）
last_known_pid: int | None = None  # 上次检测到的 PID，用于检测重启
running = True
logger = get_logger(__name__)


# ==================== 函数 ====================


def get_manager_pid(socket_dir: str) -> int | None:
    """
    从 PID 文件读取 Manager 进程 ID

    Args:
        socket_dir: socket 目录路径（PID 文件所在目录）

    Returns:
        进程 ID，如果文件不存在或读取失败则返回 None
    """
    pid_file = Path(socket_dir) / PID_FILE_NAME
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, IOError):
        return None


def check_process_exists(pid: int) -> bool:
    """
    检查进程是否存在

    Args:
        pid: 进程 ID

    Returns:
        True 如果进程存在，否则 False
    """
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def check_health_endpoint(host: str, port: int) -> bool:
    """
    调用 /health 接口检查服务状态

    Args:
        host: API 主机地址
        port: API 端口

    Returns:
        True 如果健康检查通过，否则 False
    """
    try:
        response = requests.get(f"http://{host}:{port}/health", timeout=5)
        return response.status_code == 200 and response.json().get("status") == "ok"
    except Exception:
        return False


def health_check_iteration(host: str, port: int, socket_dir: str) -> tuple[bool, int | None]:
    """
    执行一次健康检查

    检查项：
    1. PID 文件是否存在
    2. 进程是否存在
    3. /health 接口是否返回正常

    Args:
        host: API 主机地址
        port: API 端口
        socket_dir: PID 文件目录

    Returns:
        (是否通过, 当前PID)
    """
    # 1. 检查 PID 文件
    pid = get_manager_pid(socket_dir)
    if pid is None:
        logger.warning("Manager PID 文件不存在")
        return False, None

    # 2. 检查进程是否存在
    if not check_process_exists(pid):
        logger.warning(f"Manager 进程不存在 (PID: {pid})")
        return False, pid

    # 3. 检查 /health 接口
    if not check_health_endpoint(host, port):
        logger.warning(f"Manager /health 检查失败 (PID: {pid})")
        return False, pid

    return True, pid


def send_alert_with_throttle(message: str, current_pid: int | None) -> bool:
    """
    发送告警通知（带告警压制）

    逻辑：
    - 如果 PID 变化（Manager 重启），重置告警计数
    - 连续告警 MAX_ALERTS 次后不再发送告警

    Args:
        message: 告警消息内容
        current_pid: 当前检测到的 PID

    Returns:
        True 如果实际发送了告警，False 如果告警被压制
    """
    global consecutive_alerts, last_known_pid

    # 检测 PID 变化（Manager 重启），重置告警计数
    if current_pid is not None and last_known_pid is not None and current_pid != last_known_pid:
        logger.info(f"检测到 Manager 重启 (PID: {last_known_pid} -> {current_pid})，重置告警计数")
        consecutive_alerts = 0

    # 更新上次检测的 PID
    if current_pid is not None:
        last_known_pid = current_pid

    # 告警压制：超过阈值不再发送
    if consecutive_alerts >= MAX_ALERTS:
        logger.debug(f"告警已压制（连续 {consecutive_alerts} 次），不发送告警")
        return False

    # 发送告警
    try:
        send_wechat(f"[Q-Trader告警] {message}")
        consecutive_alerts += 1
        logger.info(f"告警已发送: {message} (第 {consecutive_alerts}/{MAX_ALERTS} 次)")
        return True
    except Exception as e:
        logger.error(f"发送告警失败: {e}")
        return False


def main():
    """主循环"""
    global consecutive_failures, consecutive_alerts, last_known_pid, running

    # 加载配置
    config = get_config_loader().load_config()
    host = config.api.host
    port = config.api.port
    socket_dir = config.socket.socket_dir

    # 设置日志
    log_dir = Path(config.paths.logs) / "health"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logger("health", log_dir=str(log_dir))

    logger.info("=" * 60)
    logger.info("Manager 健康检查启动")
    logger.info(f"目标地址: {host}:{port}")
    logger.info(f"PID目录: {socket_dir}")
    logger.info(f"检查间隔: {CHECK_INTERVAL}秒, 告警阈值: {MAX_FAILURES}次")
    logger.info(f"告警压制: 连续 {MAX_ALERTS} 次后停止告警，PID 变化后重置")
    logger.info("=" * 60)

    while running:
        is_healthy, current_pid = health_check_iteration(host, port, socket_dir)

        if is_healthy:
            # 恢复时记录日志
            if consecutive_failures > 0:
                logger.info(f"Manager 恢复正常，之前连续失败 {consecutive_failures} 次")
            # 重置失败计数和告警计数（服务恢复后下次告警重新计数）
            consecutive_failures = 0
            consecutive_alerts = 0
        else:
            consecutive_failures += 1
            logger.warning(f"健康检查失败，连续失败次数: {consecutive_failures}/{MAX_FAILURES}")

            if consecutive_failures >= MAX_FAILURES:
                send_alert_with_throttle(
                    f"Manager 进程异常，连续 {MAX_FAILURES} 次健康检查失败！", current_pid
                )
                # 重置失败计数，继续监控
                consecutive_failures = 0

        time.sleep(CHECK_INTERVAL)

    logger.info("健康检查已停止")


def signal_handler(signum, frame):
    """处理终止信号"""
    global running
    logger.info(f"收到信号 {signum}，准备退出...")
    running = False


# ==================== 入口 ====================

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()
