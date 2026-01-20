"""
订单文件扫描器和持仓管理器
扫描指定目录中的CSV订单文件并执行交易指令
执行换仓逻辑
"""
import csv
from gc import enable
import os
import time
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import True_

from src.config_loader import AppConfig
from src.database import get_session
from src.models.po import SwitchPosImportPo as OrderFile, RotationInstructionPo
from src.trading_engine import TradingEngine
from src.utils.helpers import parse_symbol
from src.utils.logger import get_logger

logger = get_logger(__name__)


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

    def __init__(self, config: AppConfig, trading_engine: TradingEngine):
        """
        初始化持仓管理器

        Args:
            config: 应用配置
            trading_engine: 交易引擎实例
        """
        self.config = config
        self.trading_engine = trading_engine
        self.switchPos_files_dir = config.paths.switchPos_files
        self.working = False
        self.running_instructions = None
        self.is_manual = False

    def import_csv(self, csv_text:str,filename:str,mode:str = "replace"):
        """
        导入换仓指令文件

        Args:
            file_path: 换仓指令文件路径
        """
        try:
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
                matchs = re.findall(r'\d{8}', filename)
                if matchs:
                    trading_date = matchs[0]
                    logger.info(f"从文件名提取交易日: {trading_date}")
                else:
                    raise ValueError(f"文件名格式错误，无法提取交易日: {filename}")

            session = get_session()
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

                    instrument_str = instrument_str.replace(" ", "")

                    if "." not in instrument_str:
                        logger.warning(f"第{line_num}行合约格式错误: {instrument_str}")
                        failed_count += 1
                        continue
                    symbol = instrument_str

                    offset_map = {
                        "Open": "OPEN",
                        "Close": "CLOSE",
                        "开仓": "OPEN",
                        "平仓": "CLOSE"
                    }
                    direction_map = {
                        "Buy": "BUY",
                        "Sell": "SELL",
                        "买入": "BUY",
                        "卖出": "SELL"
                    }

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


                    if mode == "replace" and trading_date:
                        # 替换模式下，将相同交易日的旧记录设为已删除
                        session.query(RotationInstructionPo).filter_by(
                            trading_date=trading_date
                        ).update({"is_deleted": True})

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
                        is_deleted=False,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )

                    session.add(instruction)
                    imported_count += 1

                except Exception as e:
                    logger.error(f"第{line_num}行解析失败: {e}, 内容: {line}")
                    failed_count += 1
                    errors.append({"row": line_num, "error": str(e), "content": line})
                    session.rollback()
                    continue

            session.commit()
            logger.info(f"CSV导入完成，成功: {imported_count}, 失败: {failed_count}")

            data={
                    "imported": imported_count,
                    "failed": failed_count,
                    "errors": errors[:10]
                }
            return data
        except Exception as e:
            raise Exception(f"导入文件失败{e}")

    def scan_and_process_orders(self) -> None:
        """扫描并处理交易指令文件"""
        try:
            today_dir = Path(self.switchPos_files_dir) / datetime.now().strftime("%Y%m%d")
            today_str = datetime.now().strftime("%Y%m%d")
            csv_files = [f for f in today_dir.glob("*.csv") if today_str in f.name and self.config.account_id in f.name]
            if not csv_files:
                return
            
            #logger.info(f"扫描到 {len(csv_files)} 个换仓文件")
            session = get_session()
            for csv_file in csv_files:
                # 检查该文件是否已导入
                existing = session.query(OrderFile).filter_by(file_name=csv_file.name).first()
                if existing:
                    continue

                # 导入文件
                result = self.import_csv(csv_file.read_text(encoding="utf-8-sig"), csv_file.name, mode="replace")
                # 记录导入成功，写入导入记录
                if result and result.get("imported", 0) > 0:
                    record = OrderFile(
                        file_name=csv_file.name,
                        file_path=str(csv_file.parent),
                        created_at=datetime.now(),
                    )
                    session.add(record)
                    session.commit()
                    logger.info(f"文件 {csv_file.name} 导入记录已保存")

        except Exception as e:
            logger.error(f"扫描订单文件时出错: {e}")

    def execute_position_rotation(self, trading_type: str = "", is_manual: bool = False) -> None:
        """
        执行换仓逻辑

        Args:
            is_manual: 是否手动换仓
        """
        if self.working:
            logger.info("换仓任务已在进行中，跳过")
            return
        self.working = True
        self.is_manual = is_manual
        logger.info(f"开始换仓, 手动: {is_manual}")
        all_instructions = self._get_all_instructions()
        self.running_instructions = all_instructions
        if not all_instructions:
            logger.info("今日无换仓指令")
            return
        logger.info(f"获取到 {len(all_instructions)} 条可执行换仓指令")

        try:
            for instruction in all_instructions:
                instruction.status = "PENDING"
                instruction.error_message = None
                instruction.remaining_attempts = (instruction.volume // self.config.risk_control.max_split_volume + 1) * 2
            turn = 0
            while True:
                # 每轮循环重新从数据库查询（确保获取到最新换仓指令）
                # db_instructions = self._get_all_instructions()
                # 获取所有可换仓的指令
                instructions = [inst for inst in all_instructions if self._check_instruction(inst, is_manual)]
                if len(instructions) <= 0:
                    logger.info("结束换仓, [全部换仓指令已完成]")
                    break
                all_retry_times = sum([inst.remaining_attempts for inst in instructions])
                if all_retry_times <= 0:
                    logger.info("结束换仓, [所有换仓指令尝试次数用完！]")
                    break

                turn += 1
                logger.info(f"第 {turn} 轮换仓开始。。。")
                for instruction in instructions:
                    try:
                        current_order = self.trading_engine.orders.get(instruction.current_order_id)
                        if current_order:
                            # 有报单则等待下一次循环
                            if current_order.status == "FINISHED":
                                instruction.current_order_id = None
                                instruction.remaining_volume = instruction.remaining_volume - (current_order.volume_orign - current_order.volume_left)
                                if instruction.remaining_volume <= 0:
                                    instruction.status = "COMPLETED"
                                if current_order.is_error:
                                    # 报单错误
                                    instruction.status = "FAILED"
                                    instruction.error_message = current_order.last_msg
                                
                            else:
                                # 检测报单是否超时，且剩余可报单次数大于0，才可以撤单
                                order_age_seconds = (datetime.now() - current_order.insert_date_time).total_seconds()
                                if order_age_seconds >= self.config.risk_control.order_timeout and int(instruction.remaining_attempts) > 0:
                                    self._cancel_order(str(current_order.order_id))
                                else:
                                    logger.info(f"指令 {instruction.symbol} 报单未超时或者剩余次数不足")
                        else:
                            # 不存在报单，则进行报单处理
                            order_volume = min(instruction.remaining_volume, self.config.risk_control.max_split_volume)
                            self._insert_order(instruction, order_volume)
                    except Exception as e:
                        logger.error(f"处理指令 {instruction.symbol} 时出错: {e}")
                        instruction.status = "FAILED"
                        instruction.error_message = str(e)
                time.sleep(1)        
        except Exception as e:
            logger.error(f"换仓执行时出错: {e}")

        self._update_instructions(all_instructions)
        self.working = False
    
    def _update_instructions(self, instructions: List[RotationInstructionPo]) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        session = get_session()
        if not session:
            return

        try:
            for instruction in instructions:
                session.merge(instruction)
            session.commit()
        except Exception as e:
            logger.error(f"更新指令状态时出错: {e}")
            session.rollback()

    def _check_instruction(self, instruction: RotationInstructionPo, is_manual: bool = False) -> None:
        """
        检查指令状态并更新

        Args:
            instruction: 待检查的指令
        """
        try:
            if not instruction.enabled:
                return False

            if instruction.status == "COMPLETED" or instruction.status == "FAILED":
                return False

            if instruction.remaining_attempts <= 0:
                return False

            if not is_manual:
                # 不满足换仓时间
                now_time = datetime.now().strftime("%H:%M:%S")
                if instruction.order_time and instruction.order_time > now_time:
                    return False

        except Exception as e:
            logger.error(f"检查指令状态时出错: {e}")

        return True

    def _get_all_instructions(self) -> List[RotationInstructionPo]:
        """
        获取所有指令列表

        Returns:
            List[RotationInstructionPo]: 所有指令列表
        """
        session = get_session()
        if not session:
            return []

        try:
            today = datetime.now().strftime("%Y%m%d")
            instructions = session.query(RotationInstructionPo).filter(
                RotationInstructionPo.status != "COMPLETED",
                RotationInstructionPo.trading_date == today,
                RotationInstructionPo.is_deleted == False,
                RotationInstructionPo.enabled == True
            ).all()
            return instructions
        except Exception as e:
            logger.error(f"获取所有指令列表时出错: {e}")
            return []
        finally:
            session.close()

    def _update_instruction(self, instruction: RotationInstructionPo) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        session = get_session()
        if not session:
            return

        try:
            session.merge(instruction)
            session.commit()
        except Exception as e:
            logger.error(f"更新指令状态时出错: {e}")
        finally:
            session.close()

    def _cancel_order(self, order_id: str) -> bool:
        """
        撤单

        Args:
            order_id: 委托单ID

        Returns:
            bool: 是否成功
        """
        try:
            if order_id and self.trading_engine.cancel_order(str(order_id)):
                logger.info(f"撤单成功: {order_id}")
                return True
            else:
                logger.warning(f"撤单失败: {order_id}")
                return False
        except Exception as e:
            logger.error(f"撤单时出错: {e}")
            return False

    def _insert_order(self, instruction: RotationInstructionPo, volume: int) -> None:
        """
        拆单并报单

        Args:
            instruction: 换仓指令
            volume: 需要报单的手数

        Returns:
            str: 委托单ID
        """
        order_id = self.trading_engine.insert_order(
                symbol=instruction.symbol,
                direction=instruction.direction,
                offset=instruction.offset,
                volume=volume,
                price=instruction.price,
        )
        instruction.current_order_id = order_id
        instruction.remaining_attempts -= 1
        instruction.status = "RUNNING"        
        logger.info(f"换仓报单成功: {instruction.symbol} {instruction.direction} {volume}手, 委托单ID: {order_id}")
        

    def _load_all_instructions(self) -> List[OrderInstruction]:
        """
        加载所有交易指令

        Returns:
            List[OrderInstruction]: 订单指令列表
        """
        instructions = []

        try:
            csv_files = list(Path(self.switchPos_files_dir).glob("*.csv"))

            for csv_file in csv_files:
                instructions.extend(self._parse_csv_file(csv_file))

            return instructions

        except Exception as e:
            logger.error(f"加载交易指令时出错: {e}")
            return []

    def _parse_csv_file(self, file_path: Path) -> List[OrderInstruction]:
        """
        解析CSV订单文件

        Args:
            file_path: 文件路径

        Returns:
            List[OrderInstruction]: 订单指令列表
        """
        instructions = []

        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)

                required_columns = ["实盘账户", "合约代码", "交易所代码", "开平类型", "买卖方向", "手数", "价格"]
                for col in required_columns:
                    if col not in reader.fieldnames or []:
                        logger.error(f"CSV文件缺少必需的列: {col}")
                        return []

                for row in reader:
                    try:
                        symbol = row["实盘账户"].strip()
                        exchange_id = row["交易所代码"].strip()
                        offset = row["开平类型"].strip().upper()
                        direction = row["买卖方向"].strip().upper()
                        volume = int(row["手数"])
                        price_str = row["价格"].strip()
                        order_time = row.get("报单时间", "").strip() or None

                        if offset not in ("OPEN", "CLOSE", "CLOSETODAY"):
                            continue

                        if direction not in ("BUY", "SELL"):
                            continue

                        if volume <= 0:
                            continue

                        price = 0
                        if price_str and price_str != "0":
                            try:
                                price = float(price_str)
                            except ValueError:
                                price = 0

                        instruction = OrderInstruction(
                            symbol=symbol,
                            exchange_id=exchange_id,
                            offset=offset,
                            direction=direction,
                            volume=volume,
                            price=price,
                            order_time=order_time,
                        )
                        instructions.append(instruction)

                    except Exception as e:
                        logger.warning(f"解析行失败: {e}，跳过")

            return instructions

        except Exception as e:
            logger.error(f"读取CSV文件失败: {e}")
            return []

    def _execute_instruction(self, instruction: OrderInstruction) -> bool:
        """
        执行订单指令

        Args:
            instruction: 订单指令

        Returns:
            bool: 是否执行成功
        """
        try:
            if not self.trading_engine.is_subscribed(instruction.symbol):
                self.trading_engine.subscribe_symbol(instruction.symbol)

            order_id = self.trading_engine.insert_order(
                symbol=instruction.symbol,
                direction=instruction.direction,
                offset=instruction.offset,
                volume=instruction.volume,
                price=instruction.price,
            )

            if order_id:
                logger.info(
                    f"执行订单指令成功: {instruction.symbol} {instruction.direction} "
                    f"{instruction.offset} {instruction.volume}手, 委托单ID: {order_id}"
                )
                return True
            else:
                logger.warning(f"执行订单指令失败: {instruction}")
                return False

        except Exception as e:
            logger.error(f"执行订单指令时出错: {e}")
            return False
