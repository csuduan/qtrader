"""
Trader子进程入口
支持两种启动模式：
1. Managed模式：连接到TradingManager
2. Standalone模式：独立运行（用于测试）
"""

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.app_context import AppContext, get_app_context
from src.trader.trader import Trader
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.config_loader import AppConfig, TraderConfig, get_config_loader
from src.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)
ctx = get_app_context()

# 全局变量
trader: Optional[Trader] = None


def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"收到信号 {signum}，准备退出...")
    if trader:
        asyncio.create_task(trader.stop())


async def main_async(args):
    """异步主函数"""
    global trader
    account_id = args.account_id

    # 加载配置
    config: TraderConfig = get_config_loader().load_trader_config(account_id)
    ctx.register(AppContext.KEY_CONFIG, config)

    if not config:
        logger.error(f"未找到账户 [{args.account_id}] 的配置")
        sys.exit(1)

    # 检查是否已有进程运行
    socket_dir = config.socket.socket_dir
    socket_dir_abs = Path(socket_dir).expanduser().resolve()
    pid_file = socket_dir_abs / f"qtrader_{account_id}.pid"

    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            # 检查进程是否存在
            try:
                os.kill(pid, 0)  # 检查进程是否存在，不发送信号
                logger.error(f"检测到已有进程运行 (PID: {pid})，请先停止该进程")
                sys.exit(1)
            except OSError:
                # 进程不存在，清理过期的PID文件
                pid_file.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"检查PID文件失败: {e}")
            pid_file.unlink(missing_ok=True)

    # 设置日志
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logger(app_name=f"trader-{account_id}", log_dir=config.paths.logs, log_level=log_level)

    logger.info("=" * 60)
    logger.info(f"Q-Trader Trader[{account_id}] 启动")
    logger.info(f"账户ID: {account_id}")
    logger.info(f"调试模式: {args.debug}")
    logger.info("=" * 60)

    # 注册当前事件循环到 AppContext
    loop = asyncio.get_running_loop()
    ctx.register(AppContext.KEY_EVENT_LOOP, loop)

    # 启动事件引擎
    event_engine = AsyncEventEngine(name=f"Trader")
    event_engine.start()
    ctx.register(AppContext.KEY_EVENT_ENGINE, event_engine)

    # 创建Trader
    trader = Trader(config)

    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动Trader
    # 构建完整的socket文件路径（目录/账户ID.sock）
    socket_path = str(socket_dir_abs / f"qtrader_{account_id}.sock")

    try:
        # 写入PID文件
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"已写入PID文件: {pid_file} (PID: {os.getpid()})")

        await trader.start(socket_path=socket_path)
    except Exception as e:
        logger.exception(f"Trader运行出错: {e}")
    finally:
        await trader.stop()

        # 清理PID文件（使用绝对路径）
        pid_file = socket_dir_abs / f"qtrader_{account_id}.pid"
        try:
            pid_file.unlink(missing_ok=True)
            logger.info(f"已清理PID文件: {pid_file}")
        except Exception as e:
            logger.warning(f"清理PID文件失败: {e}")

        logger.info("Trader 已退出")


def main(args):
    asyncio.run(main_async(args))
