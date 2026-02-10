"""
任务执行管理器模块
管理所有定时任务的执行方法（支持异步 TradingEngine）
"""

import asyncio
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.po import AlarmPo as AlarmModel
from src.trader.core.trading_engine import TradingEngine
from src.trader.switch_mgr import SwitchPosManager
from src.utils.config_loader import TraderConfig
from src.utils.database import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _run_async(coro, timeout: float = 300):
    """
    在当前运行的事件循环中运行协程并等待结果

    Args:
        coro: 协程对象
        timeout: 超时时间（秒），默认300秒

    Returns:
        协程的返回值，超时或失败返回 None
    """
    try:
        loop = asyncio.get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    except RuntimeError:
        logger.warning("没有运行的事件循环，无法执行异步任务")
        return None
    except asyncio.TimeoutError:
        logger.error(f"异步任务执行超时（{timeout}秒）")
        return None
    except Exception as e:
        logger.error(f"异步任务执行失败: {e}")
        return None


class JobManager:
    """任务执行管理器类"""

    def __init__(
        self,
        config: TraderConfig,
        trading_engine: TradingEngine,
        position_manager: SwitchPosManager,
    ):
        """
        初始化任务管理器

        Args:
            config: 应用配置
            trading_engine: 交易引擎实例
            position_manager: 换仓管理器实例
        """
        self.config = config
        self.trading_engine = trading_engine
        self.position_manager = position_manager

    def pre_market_connect(self) -> None:
        """盘前自动连接（异步版本）"""
        logger.info("开始执行盘前自动连接任务")
        try:
            if not self.trading_engine.connected:
                _run_async(self.trading_engine.connect())
                logger.info("盘前自动连接任务已提交")
            else:
                logger.info("交易引擎已连接，跳过盘前连接任务")
        except Exception as e:
            logger.error(f"盘前自动连接任务执行失败: {e}")

    def post_market_export(self) -> None:
        """盘后导出持仓"""
        logger.info("开始执行盘后导出持仓任务")
        try:
            self.export_positions_to_csv()
            logger.info("盘后导出持仓任务完成")
        except Exception as e:
            logger.error(f"盘后导出持仓任务执行失败: {e}")

    def post_market_disconnect(self) -> None:
        """盘后断开连接（异步版本）"""
        logger.info("开始执行盘后断开连接任务")
        try:
            if self.trading_engine.connected:
                _run_async(self.trading_engine.disconnect())
                logger.info("盘后断开连接任务已提交")
            else:
                logger.info("交易引擎已断开，跳过盘后断开连接任务")
        except Exception as e:
            logger.error(f"盘后断开连接任务执行失败: {e}")

    def export_positions_to_csv(self) -> None:
        """导出持仓到CSV文件"""
        try:
            # 从内存获取所有持仓
            positions = self.trading_engine.positions

            if not positions:
                logger.info("当前没有持仓，跳过导出")
                return

            # 准备导出目录
            export_dir = Path(self.config.paths.export)
            export_dir.mkdir(parents=True, exist_ok=True)

            # 生成文件名
            today = datetime.now().strftime("%Y%m%d")
            file_name = f"position-{self.config.account_id}-{today}.csv"
            file_path = export_dir / file_name

            # 导出数据
            with open(file_path, "w", encoding="gbk", newline="") as f:
                fieldnames = ["账户", "交易日期", "合约代码", "方向", "今仓", "昨仓"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for symbol, pos in positions.items():
                    pos_long = pos.pos_long
                    pos_short = pos.pos_short

                    # 如果多空都有值，拆分成两条记录
                    if pos_long > 0 and pos_short > 0:
                        # 多头记录
                        row_long = {
                            "账户ID": self.config.account_id,
                            "交易日期": today,
                            "合约代码": symbol,
                            "方向": "多",
                            "今仓": pos_long,
                            "昨仓": 0,
                        }
                        writer.writerow(row_long)

                        # 空头记录
                        row_short = {
                            "账户ID": self.config.account_id,
                            "交易日期": today,
                            "合约代码": symbol,
                            "方向": "空",
                            "今仓": pos_short,
                            "昨仓": 0,
                        }
                        writer.writerow(row_short)
                    elif pos_long > 0:
                        # 只有多头
                        row = {
                            "账户": self.config.account_id,
                            "交易日期": today,
                            "合约代码": symbol,
                            "方向": "Buy",
                            "今仓": pos_long,
                            "昨仓": 0,
                        }
                        writer.writerow(row)
                    if pos_short > 0:
                        # 空头
                        row = {
                            "账户": self.config.account_id,
                            "交易日期": today,
                            "合约代码": symbol,
                            "方向": "Sell",
                            "今仓": pos_short,
                            "昨仓": 0,
                        }
                        writer.writerow(row)

            logger.info(f"持仓已导出到: {file_path}")

        except Exception as e:
            logger.error(f"导出持仓到CSV失败: {e}")

    def test_log(self) -> None:
        """测试日志任务（每5秒执行）"""
        logger.info("这是一条测试日志 - 定时任务运行中")

    async def execute_position_rotation(self, instruction: Optional[str] = "") -> None:
        """执行换仓操作"""
        logger.info("开始执行换仓任务")
        try:
            await self.position_manager.execute_position_rotation(instruction)
            logger.info("换仓任务完成")
        except Exception as e:
            logger.error(f"换仓任务执行失败: {e}")

    def scan_orders(self) -> None:
        """扫描并处理订单"""
        # logger.info("开始扫描订单任务")
        try:
            self.position_manager.scan_and_process_orders()
            # logger.info("扫描订单任务完成")
        except Exception as e:
            logger.error(f"扫描订单任务执行失败: {e}")

    def cleanup_old_alarms(self) -> None:
        """清理3天前的告警"""
        logger.info("开始清理旧告警")
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        try:
            from datetime import timedelta

            three_days_ago = datetime.now() - timedelta(days=3)

            deleted_count = (
                session.query(AlarmModel).filter(AlarmModel.created_at < three_days_ago).delete()
            )

            session.commit()

            if deleted_count > 0:
                logger.info(f"已清理 {deleted_count} 条旧告警记录")
            else:
                logger.info("没有需要清理的旧告警记录")
        except Exception as e:
            logger.error(f"清理旧告警失败: {e}")
            session.rollback()
        finally:
            session.close()

    def reset_strategies(self) -> None:
        """重置所有策略"""
        from src.app_context import get_app_context

        ctx = get_app_context()
        strategy_manager = ctx.get_strategy_manager()
        logger.info("开始重置所有策略")
        try:
            strategy_manager.reset_all_for_new_day()
            logger.info("所有策略已重置")
        except Exception as e:
            logger.error(f"重置策略失败: {e}")
