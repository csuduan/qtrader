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
        # 告警压制集合：已触发故障告警的账户ID，恢复后移除
        self._alarm_suppressed: set = set()

    def trader_health_check(self) -> None:
        """
        检查所有 Trader 进程的连接状态

        1. 跳过禁用账户和手动停止的 Trader
        2. 故障的 Trader 首次发现时触发告警，后续压制（不重复告警）
        3. 故障恢复后清除压制并发送恢复通知
        """
        logger.info("开始执行 Trader 健康检查任务")
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        try:
            now = datetime.now()

            for account_id, trader_proxy in self.trading_manager.traders.items():
                # 检查账户是否启用
                account_config = self.trading_manager.account_configs_map.get(account_id)
                if not account_config or not account_config.enabled:
                    continue

                is_running = trader_proxy.is_running()

                if is_running:
                    # Trader 运行正常
                    if account_id in self._alarm_suppressed:
                        # 之前故障过，现在恢复了 → 清除压制并发恢复通知
                        self._alarm_suppressed.discard(account_id)
                        logger.info(f"Trader [{account_id}] 故障已恢复")
                        self._create_alarm(
                            session=session,
                            account_id=account_id,
                            source="TRADER_HEALTH_CHECK",
                            title=f"Trader {account_id} 已恢复",
                            detail="Trader 进程已恢复正常运行",
                            now=now,
                        )
                else:
                    # Trader 不在运行
                    if trader_proxy.manual_stop:
                        # 手动停止，不告警
                        logger.debug(f"Trader [{account_id}] 为手动停止，跳过告警")
                        continue

                    if account_id in self._alarm_suppressed:
                        # 已压制，不重复告警
                        logger.debug(f"Trader [{account_id}] 告警已压制，跳过")
                        continue

                    # 首次发现故障 → 触发告警并压制
                    self._alarm_suppressed.add(account_id)
                    self._create_alarm(
                        session=session,
                        account_id=account_id,
                        source="TRADER_HEALTH_CHECK",
                        title=f"Trader {account_id} 连接异常",
                        detail="Trader 进程未运行，请检查进程状态",
                        now=now,
                    )

            suppressed_count = len(self._alarm_suppressed)
            if suppressed_count > 0:
                logger.warning(f"Trader 健康检查完成: {suppressed_count} 个账户告警已压制")
            else:
                logger.info("所有 Trader 连接正常")

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
                session.query(AlarmPo).filter(AlarmPo.created_at < three_days_ago).delete()
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

    def pre_market_check(self) -> None:
        """
        开盘前检查任务

        检查项：
        1. 检查网关是否都已连接
        2. [预留] 其他检查项（待补充）
        """
        logger.info("开始执行开盘前检查任务")
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        try:
            now = datetime.now()
            all_issues = []

            # ========== 检查项 1: 网关连接状态 ==========
            disconnected_gateways = self._check_gateway_connection()
            for account_id in disconnected_gateways:
                all_issues.append({
                    "account_id": account_id,
                    "source": "PRE_MARKET_CHECK",
                    "title": f"账户 {account_id} 网关未连接",
                    "detail": "开盘前检查：网关未连接，请检查Trader进程和网关状态",
                })

            # ========== 检查项 2: [预留] ==========
            # TODO: 添加其他开盘前检查项
            # 示例：检查策略状态、检查资金充足性、检查持仓一致性等

            # 创建告警
            for issue in all_issues:
                self._create_alarm(
                    session=session,
                    account_id=issue["account_id"],
                    source=issue["source"],
                    title=issue["title"],
                    detail=issue["detail"],
                    now=now,
                )

            if not all_issues:
                logger.info("开盘前检查完成：所有检查项通过")
            else:
                logger.warning(f"开盘前检查完成：发现 {len(all_issues)} 个问题")

        except Exception as e:
            logger.exception(f"开盘前检查任务执行失败: {e}")
        finally:
            session.close()

    def _check_gateway_connection(self) -> list:
        """
        检查网关连接状态

        Returns:
            未连接网关的账户ID列表
        """
        disconnected = []
        for account_id, trader_proxy in self.trading_manager.traders.items():
            # 检查账户是否启用
            account_config = self.trading_manager.account_configs_map.get(account_id)
            if not account_config or not account_config.enabled:
                continue

            # 检查网关连接状态
            if not trader_proxy.gateway.connected:
                disconnected.append(account_id)

        return disconnected

    def _create_alarm(
        self,
        session,
        account_id: str,
        source: str,
        title: str,
        detail: str,
        now: datetime,
        immediate_alert: bool = True,  # 是否发送即时告警
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
            immediate_alert: 是否发送即时告警（微信通知）
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

            # 发送即时告警通知（如果启用且非免打扰时段）
            # 注意：旧版本的 alert.immediate 已废弃，现在通过 AlarmService 统一处理通知告警
            if immediate_alert:
                # 从全局配置获取告警配置
                app_config = self.trading_manager.app_config
                if app_config and app_config.alert.notification.enabled:
                    try:
                        from src.utils.wecomm import is_dnd_now, send_wechat

                        if is_dnd_now(app_config.alert.notification.dnd_start, app_config.alert.notification.dnd_end):
                            logger.debug(f"当前为免打扰时段({app_config.alert.notification.dnd_start}-{app_config.alert.notification.dnd_end})，跳过告警通知: {title}")
                        else:
                            send_wechat(f"【即时告警】{title}\n{detail}")
                    except Exception as e:
                        logger.error(f"发送即时告警通知失败: {e}")

        except Exception as e:
            logger.error(f"创建告警失败: {e}")
            session.rollback()

    def refresh_contracts(self) -> None:
        """定时刷新合约信息（由调度器调用）"""
        logger.info("开始定时刷新合约信息...")
        try:
            import asyncio

            pd_service = self.trading_manager.public_data_service
            if pd_service and not pd_service.has_fresh_contracts():
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(
                    self.trading_manager._refresh_contracts_from_tq(), loop
                )
            else:
                logger.info("合约信息新鲜，无需刷新")
        except Exception as e:
            logger.exception(f"定时刷新合约信息失败: {e}")

    def restart_all_traders(self) -> None:
        """
        重启所有 Trader 进程

        用于定时清理内存、重置状态。建议在非交易时段执行。
        """
        import asyncio

        logger.info("开始执行重启所有 Trader 任务")

        async def _restart_all():
            success_count = 0
            failed_count = 0

            for account_id, trader_proxy in self.trading_manager.traders.items():
                # 检查账户是否启用
                account_config = self.trading_manager.account_configs_map.get(account_id)
                if not account_config or not account_config.enabled:
                    continue

                try:
                    logger.info(f"正在重启 Trader [{account_id}]...")
                    success = await self.trading_manager.restart_trader(account_id)
                    if success:
                        success_count += 1
                        logger.info(f"Trader [{account_id}] 重启成功")
                    else:
                        failed_count += 1
                        logger.error(f"Trader [{account_id}] 重启失败")
                except Exception as e:
                    failed_count += 1
                    logger.exception(f"重启 Trader [{account_id}] 时发生异常: {e}")

            logger.info(f"批量重启完成: 成功 {success_count} 个, 失败 {failed_count} 个")

        try:
            # 获取当前事件循环并执行
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(_restart_all(), loop)
        except Exception as e:
            logger.exception(f"执行重启所有 Trader 任务失败: {e}")

    def check_threshold_alerts(self) -> None:
        """
        检查阈值告警

        统计各账户在指定时间窗口内的异常日志数量，
        如果达到阈值则发送阈值告警通知。
        """
        from datetime import datetime, timedelta

        logger.info("开始检查阈值告警")

        try:
            from src.utils.database import get_session
            from src.models.po import AlarmPo

            session = get_session()
            if not session:
                logger.error("无法获取数据库会话")
                return

            try:
                now = datetime.now()

                # 从全局配置获取阈值告警配置
                # 注意：旧版本的 alert.threshold 已废弃，现在通过 AlarmService 统一处理异常告警
                app_config = self.trading_manager.app_config
                if not app_config or not app_config.alert.exception.enabled:
                    return

                threshold_count = app_config.alert.threshold_count
                threshold_window = app_config.alert.threshold_window

                for account_id, account_config in self.trading_manager.account_configs_map.items():
                    # 检查账户是否启用
                    if not account_config or not account_config.enabled:
                        continue

                    # 计算时间窗口
                    window_start = now - timedelta(seconds=threshold_window)

                    # 统计该账户在时间窗口内的异常告警数量
                    # 来源为 TRADER_HEALTH_CHECK 或包含 "异常" 的告警
                    error_count = (
                        session.query(AlarmPo)
                        .filter(
                            AlarmPo.account_id == account_id,
                            AlarmPo.created_at >= window_start,
                            AlarmPo.source.in_([
                                "TRADER_HEALTH_CHECK",
                                "PRE_MARKET_CHECK",
                                "THRESHOLD_ALERT"
                            ])
                        )
                        .count()
                    )

                    if error_count >= threshold_count:
                        # 发送阈值告警（非免打扰时段）
                        try:
                            from src.utils.wecomm import is_dnd_now, send_wechat

                            if is_dnd_now(app_config.alert.dnd_start, app_config.alert.dnd_end):
                                logger.debug(f"当前为免打扰时段，跳过阈值告警通知: 账户[{account_id}]")
                            else:
                                send_wechat(
                                    f"【阈值告警】账户 [{account_id}] 在 {threshold_window // 60} 分钟内 "
                                    f"发生 {error_count} 次异常，已达到阈值 {threshold_count}\n"
                                    f"请检查系统状态。"
                                )
                            logger.warning(
                                f"账户 [{account_id}] 阈值告警触发: {error_count}/{threshold_count} "
                                f"(窗口: {threshold_window}s)"
                            )

                            # 创建一条阈值告警记录
                            alarm = AlarmPo(
                                account_id=account_id,
                                alarm_date=now.strftime("%Y-%m-%d"),
                                alarm_time=now.strftime("%H:%M:%S"),
                                source="THRESHOLD_ALERT",
                                title=f"阈值告警：{error_count} 次异常",
                                detail=f"在 {threshold_window // 60} 分钟内发生 {error_count} 次异常，"
                                       f"阈值: {threshold_count}",
                                status="UNCONFIRMED",
                                created_at=now,
                            )
                            session.add(alarm)
                            session.commit()

                        except Exception as e:
                            logger.error(f"发送阈值告警通知失败: {e}")

                logger.info("阈值告警检查完成")

            finally:
                session.close()

        except Exception as e:
            logger.exception(f"检查阈值告警失败: {e}")

    async def check_exception_thresholds(self) -> None:
        """
        检查异常阈值告警（每分钟执行）

        调用 AlarmService 的 check_exception_thresholds 方法
        """
        try:
            alarm_service = self.trading_manager.alarm_service
            if alarm_service:
                await alarm_service.check_exception_thresholds()
        except Exception as e:
            logger.exception(f"检查异常阈值失败: {e}")
