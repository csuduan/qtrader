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
from src.trader.trading_engine import TradingEngine
from src.trader.switch_mgr import SwitchPosManager
from src.utils.config_loader import TraderConfig
from src.utils.database import get_session
from src.utils.logger import get_logger
from src.trader.strategy_manager import StrategyManager

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
        socket_server=None,
    ):
        """
        初始化任务管理器

        Args:
            config: 应用配置
            trading_engine: 交易引擎实例
            position_manager: 换仓管理器实例
            socket_server: Socket服务器实例（可选）
        """
        self.config = config
        self.trading_engine = trading_engine
        self.position_manager = position_manager
        self.socket_server = socket_server

    async def pre_market_connect(self) -> None:
        """盘前自动连接"""
        logger.info("开始执行盘前自动连接任务")
        try:
            if not self.trading_engine.connected:
                await self.trading_engine.connect()
                logger.info("盘前自动连接任务已提交")
            else:
                logger.info("交易引擎已连接，跳过盘前连接任务")
        except Exception as e:
            logger.exception(f"盘前自动连接任务执行失败: {e}")

    async def post_market_disconnect(self) -> None:
        """盘后断开连接（异步版本）"""
        logger.info("开始执行盘后断开连接任务")
        try:
            if self.trading_engine.connected:
                await self.trading_engine.disconnect()
                logger.info("盘后断开连接任务已提交")
            else:
                logger.info("交易引擎已断开，跳过盘后断开连接任务")
        except Exception as e:
            logger.exception(f"盘后断开连接任务执行失败: {e}")

    async def post_market_export(self) -> None:
        """盘后导出持仓"""
        logger.info("开始执行盘后导出持仓任务")
        try:       
            #_run_async()
            await asyncio.to_thread(self._export_positions_to_csv)
            logger.info("盘后导出持仓任务完成")
        except Exception as e:
            logger.exception(f"盘后导出持仓任务执行失败: {e}")


    def _export_positions_to_csv(self) -> None:
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
            logger.exception(f"导出持仓到CSV失败: {e}")

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
            logger.exception(f"换仓任务执行失败: {e}")

    async def scan_orders(self) -> None:
        """扫描并处理订单"""
        # logger.info("开始扫描订单任务")
        try:
            await asyncio.to_thread(self.position_manager.scan_and_process_orders)
            # logger.info("扫描订单任务完成")
        except Exception as e:
            logger.exception(f"扫描订单任务执行失败: {e}")

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
            logger.exception(f"清理旧告警失败: {e}")
            session.rollback()
        finally:
            session.close()

    def reset_strategies(self) -> None:
        """重置所有策略"""
        from src.app_context import get_app_context

        ctx = get_app_context()
        strategy_manager: StrategyManager = ctx.get_strategy_manager()
        logger.info("开始重置所有策略")
        try:
            strategy_manager.reset_all_for_new_day()
            logger.info("所有策略已重置")
        except Exception as e:
            logger.exception(f"重置策略失败: {e}")

    async def check_rotation_result(self) -> None:
        """检查换仓结果，如果当天需要执行的换仓文件还没有全部完成，发出告警通知"""
        from datetime import date

        logger.info("开始检查换仓结果")
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        try:
            from src.models.po import RotationInstructionPo

            # 获取今天的日期
            today = date.today()
            today_str = today.strftime("%Y%m%d")

            # 查询今天启用且未删除的换仓指令
            instructions = (
                session.query(RotationInstructionPo)
                .filter(
                    RotationInstructionPo.trading_date == today_str,
                    RotationInstructionPo.enabled == True,
                    RotationInstructionPo.is_deleted == False,
                )
                .all()
            )

            if not instructions:
                logger.info("今天没有换仓指令需要检查")
                return

            # 统计未完成的换仓指令
            unfinished = []
            for inst in instructions:
                # 判断是否未完成：状态不是 FINISHED 或者还有剩余手数
                if inst.status != "FINISHED" or inst.remaining_volume > 0:
                    unfinished.append({
                        "id": inst.id,
                        "strategy_id": inst.strategy_id,
                        "symbol": inst.symbol,
                        "direction": inst.direction,
                        "offset": inst.offset,
                        "volume": inst.volume,
                        "filled_volume": inst.filled_volume,
                        "remaining_volume": inst.remaining_volume,
                        "status": inst.status,
                    })

            if unfinished:
                # 发送告警
                await self._send_rotation_alarm(today_str, unfinished)
            else:
                logger.info(f"今天({today_str})的所有换仓指令已完成")
        except Exception as e:
            logger.exception(f"检查换仓结果失败: {e}")
        finally:
            session.close()

    async def _send_rotation_alarm(self, trading_date: str, unfinished: list) -> None:
        """发送换仓告警"""
        try:
            from src.models.object import AlarmData

            now = datetime.now()
            unfinished_count = len(unfinished)
            unfinished_detail = "; ".join([
                f"{u['strategy_id']}/{u['symbol']}/{u['direction']}/{u['offset']}"
                f"(剩余{u['remaining_volume']}手)"
                for u in unfinished
            ])

            alarm_data = AlarmData(
                account_id=self.config.account_id,
                alarm_date=now.strftime("%Y-%m-%d"),
                alarm_time=now.strftime("%H:%M:%S"),
                source="ROTATION_CHECK",
                title=f"换仓未完成告警 - 共{unfinished_count}条",
                detail=f"交易日: {trading_date}, 未完成: {unfinished_detail}",
                status="UNCONFIRMED",
                created_at=now,
            )

            # 通过 Socket服务器发送告警到 Manager
            if self.socket_server:
                await self.socket_server.send_push("alarm", alarm_data.model_dump())
                logger.warning(f"已发送换仓告警到Manager: {alarm_data.title}")
            else:
                # 如果没有 Socket服务器，记录 ERROR 日志（会被告警处理器捕获）
                logger.error(f"换仓告警: {alarm_data.title} - {alarm_data.detail}")
        except Exception as e:
            logger.exception(f"发送换仓告警失败: {e}")

    async def opening_check(self) -> None:
        """
        开盘检查任务

        检查项：
        1. 交易接口连接检查
        2. 换仓文件导入检查（可选，如果配置了换仓目录）
        3. 参数文件更新检查（可选，如果配置了参数目录）
        """
        logger.info("开始执行开盘检查任务")
        now = datetime.now()

        try:
            # 1. 交易接口连接检查
            if not self.trading_engine.connected:
                await self._send_opening_alarm(
                    "交易接口未连接",
                    "开盘前交易接口未连接，请检查网络或配置"
                )
                logger.warning("开盘检查：交易接口未连接")
            else:
                logger.info("开盘检查：交易接口已连接")

            # 2. 换仓文件导入检查（如果配置了换仓目录）
            if self.config.paths and self.config.paths.switchPos_files:
                await self._check_switchpos_import(now)

            # 3. 参数文件更新检查（如果配置了参数目录）
            if self.config.paths and self.config.paths.params:
                missing_files = await self._check_param_files()
                if missing_files:
                    await self._send_opening_alarm(
                        "参数文件缺失",
                        f"以下策略参数文件不存在: {', '.join(missing_files)}"
                    )
                    logger.warning(f"开盘检查：参数文件缺失 - {missing_files}")

            logger.info("开盘检查任务完成")

        except Exception as e:
            logger.exception(f"开盘检查任务执行失败: {e}")

    async def _check_switchpos_import(self, now: datetime) -> None:
        """
        检查换仓文件导入

        查询数据库中今日是否有换仓文件导入记录
        如果没有则告警
        """
        try:
            session = get_session()
            if not session:
                logger.warning("开盘检查：无法获取数据库会话")
                return

            try:
                from src.models.po import SwitchPosImportPo
                from datetime import date

                today = date.today()
                today_str = now.strftime("%Y-%m-%d")

                # 查询今天是否有导入记录
                count = (
                    session.query(SwitchPosImportPo)
                    .filter(SwitchPosImportPo.created_at >= today_str)
                    .count()
                )

                if count == 0:
                    await self._send_opening_alarm(
                        "换仓文件未导入",
                        f"今日({today_str})未检测到换仓文件导入记录"
                    )
                    logger.warning("开盘检查：今日无换仓文件导入记录")
                else:
                    logger.info(f"开盘检查：今日已有 {count} 条换仓文件导入记录")

            finally:
                session.close()

        except Exception as e:
            logger.warning(f"检查换仓文件导入失败: {e}")

    async def _check_param_files(self) -> list[str]:
        """
        检查参数文件是否存在

        遍历所有启用的策略，检查其 params_file 配置的文件是否存在

        Returns:
            list[str]: 缺失的文件列表，格式为 "strategy_id: params_file"
        """
        missing_files = []

        if not self.config.strategies:
            return missing_files

        try:
            params_dir = Path(self.config.paths.params)

            for strategy_id, strategy_config in self.config.strategies.items():
                if not strategy_config.enabled:
                    continue

                params_file = strategy_config.params_file
                if params_file:
                    file_path = params_dir / params_file
                    if not file_path.exists():
                        missing_files.append(f"{strategy_id}: {params_file}")

        except Exception as e:
            logger.warning(f"检查参数文件失败: {e}")

        return missing_files

    async def _send_opening_alarm(self, title: str, detail: str) -> None:
        """
        发送开盘检查告警

        Args:
            title: 告警标题
            detail: 告警详情
        """
        try:
            from src.models.object import AlarmData

            now = datetime.now()

            alarm_data = AlarmData(
                account_id=self.config.account_id,
                alarm_date=now.strftime("%Y-%m-%d"),
                alarm_time=now.strftime("%H:%M:%S"),
                source="OPENING_CHECK",
                title=f"开盘检查告警 - {title}",
                detail=detail,
                status="UNCONFIRMED",
                created_at=now,
            )

            # 通过 Socket服务器发送告警到 Manager
            if self.socket_server:
                await self.socket_server.send_push("alarm", alarm_data.model_dump())
                logger.warning(f"已发送开盘检查告警到Manager: {title}")
            else:
                # 如果没有 Socket服务器，记录 ERROR 日志（会被告警处理器捕获）
                logger.error(f"开盘检查告警: {title} - {detail}")

        except Exception as e:
            logger.exception(f"发送开盘检查告警失败: {e}")

    async def closing_process(self) -> None:
        """
        收盘处理任务

        处理项：
        1. 导出持仓到 CSV（使用现有的 post_market_export）
        2. 确保交易记录持久化（事件驱动已自动完成）
        3. 持久化策略持仓状态（占位功能）
        """
        logger.info("开始执行收盘处理任务")

        try:
            # 1. 导出持仓
            await self.post_market_export()

            # 2. 确保交易记录持久化（事件驱动已自动完成）
            logger.info("交易记录由事件驱动自动持久化，无需额外处理")

            # 3. 持久化策略持仓状态（占位功能）
            await self._persist_strategy_positions()

            logger.info("收盘处理任务完成")

        except Exception as e:
            logger.exception(f"收盘处理任务执行失败: {e}")

    async def _persist_strategy_positions(self) -> None:
        """
        持久化策略持仓状态

        获取所有策略的持仓信息并保存到数据库
        保存字段：交易日、策略编号、多头、空头、持仓均价、更新时间

        注：这是占位功能，实际数据结构和持久化方式待完善
        """
        try:
            from src.app_context import get_app_context

            ctx = get_app_context()
            strategy_manager: StrategyManager = ctx.get_strategy_manager()

            if not strategy_manager:
                logger.warning("策略管理器未初始化，跳过策略持仓持久化")
                return

            session = get_session()
            if not session:
                logger.warning("无法获取数据库会话，跳过策略持仓持久化")
                return

            try:
                from src.models.po import StrategyPositionPo
                from datetime import date

                today = date.today()
                trading_date_str = today.strftime("%Y-%m-%d")

                persist_count = 0
                for strategy_id, strategy in strategy_manager.strategies.items():
                    if not strategy.enabled:
                        continue

                    # 检查是否已有今日记录
                    existing = (
                        session.query(StrategyPositionPo)
                        .filter(
                            StrategyPositionPo.account_id == self.config.account_id,
                            StrategyPositionPo.trading_date == trading_date_str,
                            StrategyPositionPo.strategy_id == strategy_id,
                        )
                        .first()
                    )

                    pos_data = {
                        "account_id": self.config.account_id,
                        "trading_date": trading_date_str,
                        "strategy_id": strategy_id,
                        "long_volume": strategy.pos_long,
                        "short_volume": strategy.pos_short,
                        "avg_price": strategy.pos_price,
                    }

                    if existing:
                        # 更新现有记录
                        existing.long_volume = pos_data["long_volume"]
                        existing.short_volume = pos_data["short_volume"]
                        existing.avg_price = pos_data["avg_price"]
                    else:
                        # 创建新记录
                        new_record = StrategyPositionPo(**pos_data)
                        session.add(new_record)

                    persist_count += 1

                session.commit()
                logger.info(f"已持久化 {persist_count} 个策略的持仓状态")

            finally:
                session.close()

        except Exception as e:
            logger.warning(f"持久化策略持仓失败: {e}")
