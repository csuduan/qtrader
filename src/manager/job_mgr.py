"""
Manager 进程任务执行管理器模块
管理所有 Manager 进程的定时任务执行方法
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from src.manager.service.alarm_service import AlarmService
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

        1. 跳过禁用账户和手动停止的 Trader
        2. 故障时发送通知告警（业务通知，不涉及压制）
        3. 恢复时也发送通知告警
        """
        logger.info("开始执行 Trader 健康检查任务")

        alarm_service: AlarmService = self.trading_manager.alarm_service
        if not alarm_service:
            logger.warning("AlarmService 未初始化，无法执行健康检查告警")
            return

        from src.models.object import AlarmType

        try:
            for account_id, trader_proxy in self.trading_manager.traders.items():
                # 检查账户是否启用
                account_config = self.trading_manager.account_configs_map.get(account_id)
                if not account_config or not account_config.enabled:
                    continue

                is_running = trader_proxy.is_running()

                if is_running:
                    # Trader 运行正常，无需操作
                    pass
                else:
                    # Trader 不在运行
                    if trader_proxy.manual_stop:
                        # 手动停止，不告警
                        logger.info(f"Trader [{account_id}] 为手动停止，跳过告警")
                        continue

                    # 发送通知告警
                    alarm_service.notify_alarm(
                        account_id=account_id,
                        source="HEALTH_CHECK",
                        title="进程异常",
                        detail="Trader 进程未运行，请检查进程状态",
                    )

            logger.info("Trader 健康检查完成")

        except Exception as e:
            logger.exception(f"Trader 健康检查任务执行失败: {e}")

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
                all_issues.append(
                    {
                        "account_id": account_id,
                        "source": "PRE_MARKET_CHECK",
                        "title": f"账户 {account_id} 网关未连接",
                        "detail": "开盘前检查：网关未连接，请检查Trader进程和网关状态",
                    }
                )

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
                    alarm_type="exception",
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
        alarm_type: str = "exception",  # 告警类型: notification/exception
    ) -> None:
        """
        创建告警记录（通过 AlarmService 统一处理）

        Args:
            session: 数据库会话（未使用，保留参数兼容旧代码）
            account_id: 账户ID
            source: 告警来源
            title: 告警标题
            detail: 告警详情
            now: 当前时间（未使用，保留参数兼容旧代码）
            alarm_type: 告警类型，exception-异常告警，notification-通知告警
        """
        alarm_service = self.trading_manager.alarm_service
        if not alarm_service:
            logger.warning("AlarmService 未初始化，无法创建告警")
            return

        from src.models.object import AlarmType

        alarm_type_enum = (
            AlarmType.NOTIFICATION if alarm_type == "notification" else AlarmType.EXCEPTION
        )
        alarm_service.create_alarm(
            account_id=account_id,
            source=source,
            title=title,
            detail=detail,
            alarm_type=alarm_type_enum,
        )

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
            from src.models.po import AlarmPo
            from src.utils.database import get_session

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
                            AlarmPo.source.in_(
                                ["HEALTH_CHECK", "PRE_MARKET_CHECK", "THRESHOLD_ALERT"]
                            ),
                        )
                        .count()
                    )

                    if error_count >= threshold_count:
                        # 发送阈值告警（非免打扰时段）
                        try:
                            from src.utils.wecomm import is_dnd_now, send_wechat

                            if is_dnd_now(app_config.alert.dnd_start, app_config.alert.dnd_end):
                                logger.debug(
                                    f"当前为免打扰时段，跳过阈值告警通知: 账户[{account_id}]"
                                )
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

    async def export_all_positions(self) -> None:
        """
        导出所有账户持仓到 CSV

        通过 TraderProxy 调用各 Trader 进程的 export_positions 接口，
        由 Trader 端自行导出本账户持仓。
        """
        logger.info("开始执行导出所有账户持仓任务")

        try:
            results = {}
            for account_id, trader in self.trading_manager.traders.items():
                try:
                    result = await trader.export_positions()
                    results[account_id] = result
                except Exception as e:
                    logger.exception(f"导出账户 [{account_id}] 持仓失败: {e}")
                    results[account_id] = {"success": False, "message": str(e)}

            success_count = sum(1 for r in results.values() if r.get("success"))
            total = len(results)
            logger.info(f"导出所有账户持仓完成: 成功 {success_count}/{total}")
            for account_id, result in results.items():
                if not result.get("success"):
                    logger.warning(f"账户 [{account_id}] 导出失败: {result.get('message')}")
        except Exception as e:
            logger.exception(f"导出所有账户持仓失败: {e}")

    async def execute_all_rotations(self) -> None:
        """
        执行所有账户的换仓操作

        通过 TradingManager 逐个调用各账户的换仓接口，
        由 Trader 端自行执行换仓逻辑。
        """
        logger.info("开始执行所有账户换仓任务")

        try:
            results = {}
            for account_id, trader in self.trading_manager.traders.items():
                # 检查账户是否启用
                account_config = self.trading_manager.account_configs_map.get(account_id)
                if not account_config or not account_config.enabled:
                    continue

                try:
                    logger.info(f"正在执行账户 [{account_id}] 换仓...")
                    success = await self.trading_manager.execute_rotation(account_id)
                    results[account_id] = {"success": success}
                    if success:
                        logger.info(f"账户 [{account_id}] 换仓执行成功")
                    else:
                        logger.error(f"账户 [{account_id}] 换仓执行失败")
                except Exception as e:
                    logger.exception(f"执行账户 [{account_id}] 换仓时发生异常: {e}")
                    results[account_id] = {"success": False, "message": str(e)}

            success_count = sum(1 for r in results.values() if r.get("success"))
            total = len(results)
            logger.info(f"批量换仓执行完成: 成功 {success_count}/{total}")
            for account_id, result in results.items():
                if not result.get("success"):
                    logger.warning(
                        f"账户 [{account_id}] 换仓失败: {result.get('message', '未知错误')}"
                    )
        except Exception as e:
            logger.exception(f"执行所有账户换仓任务失败: {e}")
