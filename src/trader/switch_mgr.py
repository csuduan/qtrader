"""
订单文件扫描器和持仓管理器
扫描指定目录中的CSV订单文件并执行交易指令
执行换仓逻辑
"""

import csv
import os
import shutil
import time
import asyncio
from datetime import datetime
from gc import enable
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import True_
from sqlalchemy.orm import Session as SQLASession

from src.models.object import OrderCmdFinishReason
from src.models.po import RotationInstructionPo
from src.models.po import SwitchPosImportPo as OrderFile
from src.trader.trading_engine import TradingEngine
from src.trader.order_cmd import OrderCmd, SplitStrategyType
from src.utils.config_loader import AppConfig,AccountConfig
from src.utils.database import session_scope
from src.utils.helpers import parse_symbol
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Type alias for Session that can be None
OptionalSession = Optional[SQLASession]


class OrderInstruction:
    """订单指令类"""

    def __init__(
        self,
        symbol: str,
        exchange_id: str,
        offset: str,
        direction: str,
        volume: int,
        price: float,
        order_time: Optional[str],
    ):
        self.symbol = symbol  # 合约代码，如 "SHFE.rb2505"
        self.exchange_id = exchange_id  # 交易所代码，如 "SHFE"
        self.offset = offset  # 开平类型: OPEN/CLOSE/CLOSETODAY
        self.direction = direction  # 买卖方向: BUY/SELL
        self.volume = volume  # 手数
        self.price = price  # 价格（0表示使用对手价）
        self.order_time = order_time  # 报单时间（格式HH:MM:SS，空则不限制）

    def __repr__(self):
        return (
            f"OrderInstruction(symbol={self.symbol}, direction={self.direction}, "
            f"offset={self.offset}, volume={self.volume}, price={self.price})"
        )


class SwitchPosManager:
    """换仓管理器，负责换仓逻辑"""

    def __init__(self, config: AccountConfig, trading_engine: TradingEngine):
        """
        初始化持仓管理器

        Args:
            config: 应用配置（AppConfig 或 AccountConfig）
            trading_engine: 交易引擎实例
        """
        self.config: AccountConfig = config
        self.trading_engine: TradingEngine = trading_engine
        self.switchPos_files_dir = config.paths.switchPos_files
        self.working = False
        self.running_instructions: Optional[List[RotationInstructionPo]] = None
        self.is_manual = False
        self.all_instructions = []

    def start(self):
        """启动换仓管理器"""
        # 加载所有换仓指令
        self.load_rotation_instructions()
        pass
    
    def get_today_instructions(self) -> List[RotationInstructionPo]:
        """获取今日换仓指令"""
        today = datetime.now().strftime("%Y%m%d")
        return [x for x in self.all_instructions if x.trading_date == today]
    
    def update_instruction(self, data: dict):
        """更新换仓指令"""
        instruction_id = data.get("instruction_id")
        if not instruction_id:
            raise ValueError("缺少指令ID")
        
        instruction = next((x for x in self.all_instructions if x.id == instruction_id), None)
        if not instruction:
            raise ValueError("指令不存在")
        
        if data.get("enabled") is not None:
            instruction.enabled = data["enabled"]
        if data.get("status") is not None:
            instruction.status = data["status"]
        if data.get("filled_volume") is not None:
            instruction.filled_volume = data["filled_volume"]   
        instruction.updated_at = datetime.now()

        # 更新数据库
        with session_scope() as session:
            session.merge(instruction)
        
        return instruction
    
    def delete_instruction(self, ids: List[str]):
        """删除换仓指令"""
        self.all_instructions = [x for x in self.all_instructions if x.id not in ids]
        # 更新数据库
        with session_scope() as session:
            session.query(RotationInstructionPo).filter(RotationInstructionPo.id.in_(ids)).update(
                {"is_deleted": True}, synchronize_session=False
            )

    def load_rotation_instructions(self):
        """加载所有换仓指令"""
        try:
            # 从数据库加载今日换仓指令
            with session_scope() as session:
                today = datetime.now().strftime("%Y%m%d")
                instructions = (
                    session.query(RotationInstructionPo)
                    .filter(
                        RotationInstructionPo.trading_date == today,
                        RotationInstructionPo.is_deleted == False,
                    )
                    .all()
                )
                self.all_instructions = instructions

            # 订阅所有指令中的合约
            symbols = list(set([instruction.symbol for instruction in self.all_instructions]))
            self.trading_engine.subscribe_symbol(symbols)
        except Exception as e:
            logger.error(f"获取所有指令列表时出错: {e}")
        logger.info(f"加载换仓指令完成，共 {len(self.all_instructions)} 条")

        



    def import_csv(self, csv_text: str, filename: str, mode: str = "replace"):
        """
        导入换仓指令文件

        Args:
            file_path: 换仓指令文件路径
        """
        lines = csv_text.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("CSV文件为空或格式错误")

        header = lines[0].strip().split(",")
        logger.info(f"准备导入换仓文件，文件名: {filename}, 模式: {mode}, 列: {header}")

        imported_count = 0
        failed_count = 0
        errors = []

        trading_date = None
        if filename:
            import re

            matchs = re.findall(r"\d{8}", filename)
            if matchs:
                trading_date = matchs[0]
                logger.info(f"从文件名提取交易日: {trading_date}")
            else:
                raise ValueError(f"文件名格式错误，无法提取交易日: {filename}")

        add_instruction = []
        for line_num, line in enumerate(lines[1:], start=2):
            try:
                values = line.strip().split(",")
                if len(values) < 6:
                    logger.warning(f"第{line_num}行数据不完整，跳过: {line}")
                    failed_count += 1
                    continue

                account_id = values[0].strip()
                strategy_id = values[1].strip()
                instrument_str = values[2].strip()
                offset_str = values[3].strip()
                direction_str = values[4].strip()
                volume_str = values[5].strip()
                order_time_str = values[6].strip() if len(values) > 6 else None

                if not account_id or not strategy_id or not instrument_str:
                    logger.warning(f"第{line_num}行缺少必要字段，跳过")
                    failed_count += 1
                    continue

                if self.config.account_id != account_id:
                    logger.warning(f"第{line_num}行账户ID {account_id} 与配置账户ID {self.config.account_id} 不一致，跳过")
                    failed_count += 1
                    continue

                instrument_str = instrument_str.replace(" ", "")

                if "." not in instrument_str:
                    logger.warning(f"第{line_num}行合约格式错误: {instrument_str}")
                    failed_count += 1
                    continue
                symbol = instrument_str

                offset_map = {"Open": "OPEN", "Close": "CLOSE", "开仓": "OPEN", "平仓": "CLOSE"}
                direction_map = {"Buy": "BUY", "Sell": "SELL", "买入": "BUY", "卖出": "SELL"}

                offset = offset_map.get(offset_str, offset_str.upper())
                direction = direction_map.get(direction_str, direction_str.upper())

                try:
                    volume = int(volume_str)
                except ValueError:
                    logger.warning(f"第{line_num}行手数格式错误: {volume_str}")
                    failed_count += 1
                    continue

                if volume <= 0:
                    logger.warning(f"第{line_num}行手数必须大于0")
                    failed_count += 1
                    continue

                instruction = RotationInstructionPo(
                    account_id=account_id,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    offset=offset,
                    direction=direction,
                    volume=volume,
                    filled_volume=0,
                    price=0,
                    order_time=order_time_str,
                    trading_date=trading_date,
                    enabled=True,
                    status="PENDING",
                    attempt_count=0,
                    remaining_attempts=0,
                    remaining_volume=volume,
                    current_order_id=None,
                    order_placed_time=None,
                    last_attempt_time=None,
                    error_message=None,
                    source=filename,
                    is_deleted=False,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                add_instruction.append(instruction)
                imported_count += 1

            except Exception as e:
                logger.exception(f"第{line_num}行解析失败: {e}, 内容: {line}")
                failed_count += 1
                errors.append({"row": line_num, "error": str(e), "content": line})
                continue
        
        if mode == "replace":
            with session_scope() as session:
                # 先删除已存在的记录
                session.query(RotationInstructionPo).filter_by(
                    trading_date=trading_date
                ).update({"is_deleted": True})
                session.bulk_save_objects(add_instruction)
        else:
            with session_scope() as session:
                session.bulk_save_objects(add_instruction)
        
        #重新加载数据
        self.load_rotation_instructions()
        logger.info(f"CSV导入完成，成功: {imported_count}, 失败: {failed_count}")
        data = {"imported": imported_count, "failed": failed_count, "errors": errors[:10]}
        return data

    def scan_and_process_orders(self) -> None:
        """扫描并处理交易指令文件"""
        try:
            today_dir = Path(self.switchPos_files_dir) / datetime.now().strftime("%Y%m%d")
            today_str = datetime.now().strftime("%Y%m%d")
            csv_files = [
                f
                for f in today_dir.glob("*.csv")
                if today_str in f.name and self.config.account_id in f.name
            ]
            if not csv_files:
                return

            # logger.info(f"扫描到 {len(csv_files)} 个换仓文件")
            with session_scope() as session:
                for csv_file in csv_files:
                    # 检查该文件是否已导入
                    existing = session.query(OrderFile).filter_by(file_name=csv_file.name).first()
                    if existing:
                        continue

                    # 导入文件
                    result = self.import_csv(
                        csv_file.read_text(encoding="gbk"), csv_file.name, mode="replace"
                    )
                    # 记录导入成功，写入导入记录
                    if result and result.get("imported", 0) > 0:
                        record = OrderFile(
                            file_name=csv_file.name,
                            file_path=str(csv_file.parent),
                            created_at=datetime.now(),
                        )
                        session.add(record)
                        #session.commit()
                        logger.info(f"文件 {csv_file.name} 导入记录已保存")

        except Exception as e:
            logger.exception(f"扫描订单文件时出错: {e}")

    async def execute_position_rotation(self, trading_type: str = "", is_manual: bool = False) -> None:
        """
        执行换仓逻辑（使用OrderCmd）

        Args:
            is_manual: 是否手动换仓
        """
        if self.working:
            logger.info("换仓任务已在进行中，跳过")
            return
        self.working = True
        self.is_manual = is_manual
        logger.info(f"开始换仓, 手动: {is_manual}")

        todo_instructions = [x for x in self.get_today_instructions() if x.status not in ("COMPLETED") and x.enabled]
        if not todo_instructions:
            logger.info("今日无换仓指令")
            self.working = False
            return
        logger.info(f"获取到 {len(todo_instructions)} 条可执行换仓指令")

        try:
            # 重置所有指令状态
            for instruction in todo_instructions:
                if instruction.filled_volume >= instruction.volume:
                    instruction.status = "COMPLETED"

                if instruction.status not in ("COMPLETED"):
                    instruction.status = "PENDING"
                    instruction.error_message = None
                    instruction.current_order_id = None

            # 为每个指令创建OrderCmd
            for instruction in todo_instructions:
                if instruction.status != "PENDING":
                    continue

                # 检查是否满足换仓时间
                if not self._check_instruction(instruction, is_manual):
                    continue

                # 创建报单指令
                price = instruction.price if instruction.price and instruction.price > 0 else None
                order_cmd: OrderCmd = OrderCmd(
                    symbol=instruction.symbol,
                    direction=instruction.direction,
                    offset=instruction.offset,
                    volume=instruction.remaining_volume,
                    price=price,
                    max_volume_per_order=self.config.trading.risk_control.max_split_volume,
                    order_interval=0.5,
                    total_timeout=self.config.trading.risk_control.order_timeout * 10,  # 总超时为单笔超时的10倍
                    order_timeout=self.config.trading.risk_control.order_timeout,
                    source=f"换仓:{instruction.symbol}",
                    on_change=self._on_cmd_changed,
                )
                self.trading_engine.insert_order_cmd(order_cmd)
                if order_cmd:
                    instruction.current_order_id = order_cmd.cmd_id
                    instruction.status = "RUNNING"
                    instruction.order_placed_time = datetime.now()
                    logger.info(f"为指令 {instruction.symbol} 创建报单指令: {order_cmd.cmd_id}")

            # 监控OrderCmd执行状态
            #self._monitor_order_commands(all_instructions)
            await self._monitor_order_commands(todo_instructions)

        except Exception as e:
            logger.exception(f"换仓执行时出错: {e}")
        finally:
            self._update_instructions(todo_instructions)
            self.working = False
            logger.info("换仓任务结束")

    def _on_cmd_changed(self, order_cmd: OrderCmd):
        """处理订单状态变化"""
        if not order_cmd.is_finished:
            return

        pass

    async def _monitor_order_commands(
        self,
        instructions: List[RotationInstructionPo],
    ) -> None:
        """
        监控OrderCmd执行状态

        Args:
            instructions: 所有换仓指令
            cmd_map: 指令symbol到cmd_id的映射
            is_manual: 是否手动换仓
        """
        active_instructions = [inst for inst in instructions if inst.status == "RUNNING"]
        if not active_instructions:
            logger.info("没有活动的报单指令")
            return

        logger.info(f"开始监控 {len(active_instructions)} 个报单指令...")
        check_interval = 2.0  # 每2秒检查一次
        max_wait_time = 600  # 最大等待时间10分钟
        start_time = time.time()

        while True:
            # 检查总超时
            if time.time() - start_time > max_wait_time:
                logger.warning("换仓监控超时，强制退出")
                break

            # 检查所有指令状态
            all_finished = True
            for instruction in active_instructions:
                cmd_id = instruction.current_order_id
                if not cmd_id:
                    continue

                # 获取OrderCmd状态
                cmd = self.trading_engine.get_order_cmd(cmd_id)
                if cmd is None:
                    logger.warning(f"未找到OrderCmd: {cmd_id}")
                    continue

                if cmd["is_active"]:
                    # 指令仍在运行
                    all_finished = False

                else:
                    # 指令已结束
                    finish_reason = cmd.get("finish_reason")
                    filled = cmd["filled_volume"]
                    instruction.filled_volume += filled
                    instruction.remaining_volume -= filled
                    if finish_reason == OrderCmdFinishReason.ALL_COMPLETED:
                        instruction.status = "COMPLETED"
                    else:
                        instruction.status = "FAILED"
                        instruction.error_message = finish_reason
                    instruction.current_order_id = None

            # 更新数据库
            self._update_instructions(active_instructions)

            # 检查是否全部完成
            if all_finished:
                logger.info("所有报单指令已完成")
                break

            await asyncio.sleep(check_interval)

        # 清理已完成的OrderCmd
        # self.trading_engine.cleanup_finished_order_cmds()

    def _update_instructions(self, instructions: List[RotationInstructionPo]) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        if not instructions:
            return

        try:
            with session_scope() as session:
                for instruction in instructions:
                    session.merge(instruction)
        except Exception as e:
            logger.error(f"更新指令状态时出错: {e}")

    def _check_instruction(
        self, instruction: RotationInstructionPo, is_manual: bool = False
    ) -> bool:
        """
        检查指令是否可以执行

        Args:
            instruction: 待检查的指令
            is_manual: 是否手动换仓

        Returns:
            是否可以执行
        """
        try:
            if not instruction.enabled:
                return False

            if instruction.status in ("COMPLETED", "FAILED"):
                return False

            if instruction.remaining_volume <= 0:
                return False

            if not is_manual:
                # 不满足换仓时间
                now_time = datetime.now().strftime("%H:%M:%S")
                if instruction.order_time and instruction.order_time > now_time:
                    return False

        except Exception as e:
            logger.error(f"检查指令状态时出错: {e}")

        return True

    

    def _update_instruction(self, instruction: RotationInstructionPo) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        try:
            with session_scope() as session:
                session.merge(instruction)
        except Exception as e:
            logger.error(f"更新指令状态时出错: {e}")
