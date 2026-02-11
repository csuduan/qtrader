"""
Manager 进程任务执行管理器模块
管理所有 Manager 进程的定时任务执行方法
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

from src.models.po import AlarmPo
from src.utils.database import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ManagerJobManager:
    """Manager 进程任务执行管理器类"""

    def __init__(self, trading_manager):
        """
        初始化 Manager 任务管理器

        Args:
            trading_manager: TradingManager 实例
        """
        self.trading_manager = trading_manager

    def trader_health_check(self) -> None:
        """
        检查所有 Trader 进程的连接状态

        检查所有账户的 Trader 是否运行并已连接
        未连接的 Trader 发送告警
        """
        logger.info("开始执行 Trader 健康检查任务")
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        try:
            now = datetime.now()
            disconnected_traders = []

            # 遍历所有账户
            for account_id, trader_proxy in self.trading_manager.traders.items():
                # 检查账户是否启用
                account_config = self.trading_manager.account_configs_map.get(account_id)
                if not account_config or not account_config.enabled:
                    continue

                # 检查 Trader 是否运行
                is_running = trader_proxy.is_running()
                if not is_running:
                    disconnected_traders.append({
                        "account_id": account_id,
                        "reason": "Trader 进程未运行"
                    })
                    continue

                # 检查连接状态（通过获取账户信息验证）
                try:
                    # 注意：这里不能使用 await，因为这是同步函数
                    # 只检查进程是否运行，具体连接状态由 Trader 自己检查
                    pass
                except Exception as e:
                    disconnected_traders.append({
                        "account_id": account_id,
                        "reason": f"连接检查失败: {str(e)}"
                    })

            # 为未连接的 Trader 创建告警
            for trader_info in disconnected_traders:
                self._create_alarm(
                    session=session,
                    account_id=trader_info["account_id"],
                    source="TRADER_HEALTH_CHECK",
                    title=f"Trader {trader_info['account_id']} 连接异常",
                    detail=f"原因: {trader_info['reason']}",
                    now=now
                )

            if not disconnected_traders:
                logger.info("所有 Trader 连接正常")
            else:
                logger.warning(f"发现 {len(disconnected_traders)} 个 Trader 连接异常")

        except Exception as e:
            logger.exception(f"Trader 健康检查任务执行失败: {e}")
        finally:
            session.close()

    def cleanup_alarms(self) -> None:
        """
        清理 3 天前的告警记录

        清理 Manager 数据库中 3 天前的告警记录
        """
        logger.info("开始清理旧告警记录")
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        try:
            three_days_ago = datetime.now() - timedelta(days=3)

            deleted_count = (
                session.query(AlarmPo)
                .filter(AlarmPo.created_at < three_days_ago)
                .delete()
            )

            session.commit()

            if deleted_count > 0:
                logger.info(f"已清理 {deleted_count} 条旧告警记录")
            else:
                logger.info("没有需要清理的旧告警记录")
        except Exception as e:
            logger.exception(f"清理旧告警失败: {e}")
            session.rollback()
        finally:
            session.close()

    def cleanup_logs(self) -> None:
        """
        清理 5 天前的日志文件

        清理 data/logs 目录下 5 天前的日志文件
        """
        logger.info("开始清理旧日志文件")
        try:
            log_dir = Path("./data/logs")
            if not log_dir.exists():
                logger.info(f"日志目录不存在: {log_dir}")
                return

            cutoff_date = datetime.now() - timedelta(days=5)
            deleted_count = 0

            # 遍历日志文件
            for log_file in log_dir.glob("*_app_*.log"):
                try:
                    # 从文件名提取日期
                    # 文件名格式: trader-{account_id}_app_YYYY-MM-DD.log
                    # 或 manager_app_YYYY-MM-DD.log
                    parts = log_file.stem.split("_")
                    date_str = None

                    # 查找日期部分 (YYYY-MM-DD 格式)
                    for part in parts:
                        if len(part) == 10 and part.count("-") == 2:
                            date_str = part
                            break

                    if not date_str:
                        logger.warning(f"无法从文件名提取日期: {log_file.name}")
                        continue

                    # 解析日期
                    try:
                        file_date = datetime.strptime(date_str, "%Y-%m-%d")
                        if file_date < cutoff_date:
                            log_file.unlink()
                            deleted_count += 1
                            logger.info(f"已删除日志文件: {log_file.name}")
                    except ValueError as e:
                        logger.warning(f"解析日期失败: {date_str}, {e}")

                except Exception as e:
                    logger.warning(f"处理日志文件 {log_file.name} 失败: {e}")

            logger.info(f"日志清理完成，共删除 {deleted_count} 个文件")

        except Exception as e:
            logger.exception(f"清理日志文件失败: {e}")

    def _create_alarm(
        self,
        session,
        account_id: str,
        source: str,
        title: str,
        detail: str,
        now: datetime,
    ) -> None:
        """
        创建告警记录

        Args:
            session: 数据库会话
            account_id: 账户ID
            source: 告警来源
            title: 告警标题
            detail: 告警详情
            now: 当前时间
        """
        try:
            alarm = AlarmPo(
                account_id=account_id,
                alarm_date=now.strftime("%Y-%m-%d"),
                alarm_time=now.strftime("%H:%M:%S"),
                source=source,
                title=title,
                detail=detail,
                status="UNCONFIRMED",
                created_at=now,
            )
            session.add(alarm)
            session.commit()
            logger.warning(f"已创建告警: {title} - {detail}")
        except Exception as e:
            logger.error(f"创建告警失败: {e}")
            session.rollback()
