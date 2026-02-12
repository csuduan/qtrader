"""
TqSdk Gateway适配器（异步版本）
参考文档：https://doc.shinnytech.com/tqsdk/latest/usage/
使用 TqSdk 异步 API 实现纯异步协程模式
"""

import asyncio
import queue
import threading
import time
import math
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Union

from pandas import DataFrame
from tqsdk import TqAccount, TqApi, TqAuth, TqKq, TqRohon, TqSim, data_extension
from tqsdk.objs import Account, Order, Position, Quote, Trade




from src.models.object import (
    AccountData,
    BarData,
    CancelRequest,
    ContractData,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderRequest,
    OrderStatus,
    OrderType,
    PositionData,
    ProductType,
    SubscribeRequest,
    TickData,
    TradeData,
)
from src.models.po import ContractPo
from src.trader.gateway.base_gateway import BaseGateway
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.config_loader import GatewayConfig
from src.utils.database import get_database
from src.utils.logger import get_logger
from src.app_context import get_app_context

ctx = get_app_context()
logger = get_logger(__name__)

exchange_map = {
    "SHFE": Exchange.SHFE,
    "DCE": Exchange.DCE,
    "CZCE": Exchange.CZCE,
    "CFFEX": Exchange.CFFEX,
    "INE": Exchange.INE,
    "GFEX": Exchange.GFEX,
}


class TqGateway(BaseGateway):
    """TqSdk Gateway适配器（纯异步实现）"""

    gateway_name = "TqSdk"

    def __init__(self, config: GatewayConfig):
        super().__init__()
        self._running = False
        self.connected = False
        self.config = config
        self.account_id = self.config.account_id
        logger.info(f"TqGateway初始化, account_id: {self.account_id}, id: {id(self)}")

        # TqSdk API实例
        self.api: Optional[TqApi] = None
        self.auth: Optional[TqAuth] = None

        # TqSdk原始数据缓存(用于is_changing检查)
        self._account: Optional[Account] = None
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, Order] = {}
        self._trades: Dict[str, Trade] = {}
        self._quotes: Dict[str, Quote] = {}
        # 自定义换仓
        self._klines: Dict[str, DataFrame] = {}
        self._pending_orders: Dict[str, Order] = {}
        # 合约符号映射(原始symbol -> 统一symbol)
        self._upper_symbols: Dict[str, str] = {}
        self._contracts: Dict[str, ContractData] = {}

        # 历史订阅的合约符号列表
        self.hist_subs: List[str] = []
        self.kline_subs: List[tuple[str, str]] = []

        # 订单引用计数
        self._order_ref = 0



        # 线程优化相关变量
        # 线程同步队列（线程安全）
        self._sync_queue: queue.Queue = queue.Queue(maxsize=1000)
        # tq主线程
        self._tq_thead: Optional[threading.Thread] = None
        # 事件分发协程
        self._dispatcher_task: Optional[asyncio.Task] = None

        # AsyncEventEngine引用（直接发送事件）
        self._event_engine: Optional[AsyncEventEngine] = ctx.get_event_engine()

        if self.config.subscribe_symbols:
            self.hist_subs.extend(self.config.subscribe_symbols)

    # ==================== 连接管理 ====================
    async def connect(self) -> bool:
        """
        连接到TqSdk
        """
        try:
            if self._running:
                logger.warning("TqSdk已启动，无需重复启动")
                return True

            # 先尝试从数据库加载今天的合约信息
            today = datetime.now().strftime("%Y-%m-%d")
            result = self._load_contracts_from_db(today)
            if result is not None:
                logger.info(f"从数据库加载了 {len(self._contracts)} 个合约信息")

            # 启动tq主线程
            self._tq_thead = threading.Thread(target=self._tq_run, name=f"TqSdk_Thread", daemon=True)
            self._tq_thead.start()
            self._running = True

            # 启动事件分发协程
            self._dispatcher_task = asyncio.create_task(self._event_dispatcher())
            logger.info("TqSdk启动完成")
            return True

        except Exception as e:
            logger.exception(f"TqSdk连接失败: {e}")
            self.connected = False
            return False

    async def disconnect(self) -> bool:
        """断开TqSdk连接（线程优化版本）"""
        try:
            logger.info("正在断开TqSdk连接...")

            # 停止轮询
            self._running = False
            self.connected = False
            self._push_account(self._convert_account(self._account))

            # 取消事件分发协程
            if self._dispatcher_task:
                self._dispatcher_task.cancel()
                try:
                    await self._dispatcher_task
                except asyncio.CancelledError:
                    pass
            logger.info("TqSdk已断开连接")
            return True

        except Exception as e:
            logger.error(f"TqSdk断开连接失败: {e}", exc_info=True)
            return False

    def get_trading_day(self) -> Optional[str]:
        """获取当前交易日"""
        now = datetime.now()
        # 如果当前时间晚于20点，则交易日切换到下一天
        if now.hour >= 20:
            trading_day = now.date() + timedelta(days=1)
        else:
            trading_day = now.date()

        # 根据交易日历查找下一个交易日
        if self.connected:
            trading_calendar = self.api.get_trading_calendar(now, now + timedelta(days=30))  # type: ignore[union-attr]
            while not trading_calendar[trading_calendar.date == trading_day.strftime("%Y-%m-%d")][
                "trading"
            ].iloc[0]:
                trading_day += timedelta(days=1)
        return trading_day.strftime("%Y%m%d")


    def subscribe(self, symbol: Union[str, List[str]]) -> bool:
        """订阅行情"""
        try:
            if isinstance(symbol, str):
                symbol = [symbol]

            # 添加到订阅列表中
            self.hist_subs.extend(symbol)
            if not self.connected:
                return True

            # 格式化合约代码
            std_symbols = [self._format_symbol(sym) for sym in self.hist_subs]
            subscribe_symbols = [s for s in std_symbols if s and s not in self._quotes]
            if len(subscribe_symbols) == 0:
                return True
            if self.api is None:
                return True

            for s in subscribe_symbols:
                quote = self.api.get_quote(s)
                self._quotes[s] = quote
            logger.info(f"订阅行情: {subscribe_symbols}")

            return True
        except Exception as e:
            logger.exception(f"订阅行情失败: {e}")
            return False

    def subscribe_bars(self, symbol: str, interval: str) -> bool:
        """订阅K线数据"""
        if (symbol, interval) not in self.kline_subs:
            self.kline_subs.append((symbol, interval))

        if not self.connected:
            return False

        seconds = self._interval_to_seconds(interval)
        data_length = 240 * 3
        if self.api is None:
            return False
        kline = self.api.get_kline_serial(  # type: ignore[union-attr]
            symbol=self._format_symbol(symbol), duration_seconds=seconds, data_length=data_length
        )
        self._klines[(symbol, interval)] = kline  # type: ignore[assignment, index]
        logger.info(f"订阅K线数据: {symbol} {interval}")
        return True

    def send_order(self, req: OrderRequest) -> Optional[OrderData]:
        """下单"""
        try:
            if not self.connected:
                logger.error("TqSdk未连接")
                return None
            
            # 调用TqSdk下单
            if self.api is None:
                raise Exception("TqSdk未连接")

            formatted_symbol = self._format_symbol(req.symbol)
            if not formatted_symbol:
                logger.error(f"无效的合约代码: {req.symbol}")
                raise Exception(f"无效的合约代码: {req.symbol}")

            # 获取行情信息(市价单使用对手价)
            price = req.price
            if price is None or price == 0:
                quote = self._quotes.get(formatted_symbol)
                if not quote or math.isnan(quote.last_price):
                    logger.error(f"未获取到行情信息: {formatted_symbol}")
                    raise Exception(f"未获取到行情信息: {formatted_symbol}")

                # 使用对手价
                if req.direction == Direction.BUY:
                    price = quote.ask_price1
                else:
                    price = quote.bid_price1


            order = self.api.insert_order(
                symbol=formatted_symbol,
                direction=req.direction.value,
                offset=req.offset.value,
                volume=req.volume,
                limit_price=price,
            )
            order_id = order.get("order_id", "")
            logger.info(
                f"下单成功: {req.symbol} {req.direction.value} {req.offset.value} {req.volume}手 价格：{price}, order_id: {order_id}"
            )

            # 推送通知
            self._pending_orders[order_id] = order
            order_data = self._convert_order(order)
            return order_data
        except Exception as e:
            logger.exception(f"下单失败: {e}")
            raise e

    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单"""
        try:
            if not self.connected:
                logger.error("TqSdk未连接")
                return False

            order = self._orders.get(req.order_id)
            if not order:
                logger.error(f"订单不存在: {req.order_id}")
                return False
            if self.api is None:
                return False
            self.api.cancel_order(order)
            logger.info(f"撤单成功: {req.order_id}")
            return True
        except Exception as e:
            logger.exception(f"撤单失败: {e}")
            raise e


    def _load_contracts_from_db(self, update_date: str) -> Optional[Dict[str, ContractData]]:
        """
        从数据库加载指定更新日期的合约信息

        Args:
            update_date: 更新日期 (YYYY-MM-DD)

        Returns:
            合约信息字典，如果没有则返回None
        """
        try:
            db = get_database()
            if not db:
                logger.warning("数据库未初始化，无法加载合约信息")
                return None

            with db.get_session() as session:
                contract_pos = (
                    session.query(ContractPo)
                    .filter(ContractPo.update_date == update_date)
                    .all()
                )

                if not contract_pos:
                    logger.info(f"数据库中没有更新日期为 {update_date} 的合约信息")
                    return None

                loaded_count = 0
                for po in contract_pos:
                    exchange = exchange_map.get(po.exchange_id, Exchange.NONE)
                    if exchange == Exchange.NONE:
                        continue
                    contract = ContractData(
                        symbol=po.symbol,
                        exchange=exchange,
                        name=po.instrument_name or po.symbol,
                        product_type=ProductType.FUTURES,
                        multiple=po.volume_multiple,
                        pricetick=float(po.price_tick),
                        min_volume=po.min_volume,
                        option_strike=float(po.option_strike) if po.option_strike else None,
                        option_underlying=po.option_underlying,
                        option_type=po.option_type,
                    )
                    self._contracts[contract.symbol] = contract
                    self._upper_symbols[contract.symbol.rsplit(".")[1].upper()] = contract.symbol
                    loaded_count += 1

                logger.info(f"从数据库加载了 {loaded_count} 个合约信息 (更新日期: {update_date})")
                return self._contracts
        except Exception as e:
            logger.error(f"从数据库加载合约信息失败: {e}")
            return None

    def _query_and_save_contracts(self, update_date: str) -> None:
        """
        从API查询合约信息并保存到数据库

        Args:
            update_date: 更新日期 (YYYY-MM-DD)
        """
        try:
            if self.api is None:
                logger.error("TqSdk未连接，无法查询合约信息")
                return

            # 查询合约列表
            quotes = self.api.query_quotes(ins_class=["FUTURE"], expired=False)
            quotes = [x for x in quotes if len(x) <= 12]
            symbol_infos = self.api.query_symbol_info(quotes)
            logger.info(f"从API查询到 {len(symbol_infos)} 个合约")

            db = get_database()
            if not db:
                logger.warning("数据库未初始化，无法保存合约信息")
            else:
                # 确保表已创建
                try:
                    db.create_tables()
                    logger.info("确保合约信息表已创建")
                except Exception as e:
                    logger.warning(f"创建表时出现错误（可能是表已存在）: {e}")

            contracts_to_save = []

            for index, item in symbol_infos.iterrows():
                instrument_id = item.instrument_id
                if item.exchange_id not in exchange_map:
                    continue

                exchange = exchange_map[item.exchange_id]
                contract = ContractData(
                    symbol=instrument_id,
                    exchange=exchange,
                    name=item.instrument_name,
                    product_type=ProductType.FUTURES,
                    multiple=item.volume_multiple,
                    pricetick=item.price_tick,
                    min_volume=1,
                    option_strike=None,
                    option_underlying=None,
                    option_type=None,
                )
                self._contracts[contract.symbol] = contract
                self._upper_symbols[contract.symbol.rsplit(".")[1].upper()] = contract.symbol

                # 准备保存到数据库的数据
                if db:
                    contract_po = ContractPo(
                        symbol=instrument_id,
                        exchange_id=item.exchange_id,
                        instrument_name=item.instrument_name,
                        product_type="FUTURES",
                        volume_multiple=item.volume_multiple,
                        price_tick=item.price_tick,
                        min_volume=1,
                        option_strike=None,
                        option_underlying=None,
                        option_type=None,
                        update_date=update_date,
                    )
                    contracts_to_save.append(contract_po)

            logger.info(f"从API加载了 {len(self._contracts)} 个合约信息，准备保存 {len(contracts_to_save)} 个到数据库")

            # 批量保存到数据库
            # if db and contracts_to_save:
            #     try:
            #         with db.get_session() as session:
            #             # 先删除今天之前的数据
            #             deleted_count = session.query(ContractPo).filter(
            #                 ContractPo.update_date < update_date
            #             ).delete(synchronize_session=False)
            #             logger.info(f"删除了 {deleted_count} 条旧合约信息")
            #             # 批量插入新数据
            #             session.add_all(contracts_to_save)
            #             session.commit()
            #             logger.info(f"成功保存 {len(contracts_to_save)} 个合约信息到数据库")
            #     except Exception as e:
            #         logger.error(f"保存合约信息到数据库失败: {e}", exc_info=True)

            logger.info(f"成功从API加载 {len(self._contracts)} 个合约信息")

        except Exception as e:
            logger.error(f"从API查询合约信息失败: {e}", exc_info=True)

    def get_contracts(self) -> Dict[str, ContractData]:
        """查询合约（兼容）"""
        try:
            if not self.connected or not self.api:
                logger.error("TqSdk未连接")
                return {}

            if not self._contracts:
                if self.api is None:
                    return {}
                quotes = self.api.query_quotes(ins_class=["FUTURE"], expired=False)
                for symbol in quotes:
                    self._contracts[symbol] = ContractData(
                        symbol=symbol.split(".")[1] if "." in symbol else symbol,
                        exchange=self._parse_exchange(symbol),
                        name=symbol,
                        product_type=ProductType.FUTURES,
                        multiple=1,
                        pricetick=0.01,
                        min_volume=1,
                        option_strike=None,
                        option_underlying=None,
                        option_type=None,
                    )

            return self._contracts
        except Exception as e:
            logger.error(f"查询合约失败: {e}")
            return {}

    def get_account(self) -> Optional[AccountData]:
        """获取账户数据(兼容)"""
        if self._account is None:
            return AccountData.model_construct(account_id=self.account_id or "", balance=0)
        return self._convert_account(self._account)

    def get_positions(self) -> Dict[str, PositionData]:
        """获取持仓数据(兼容,返回原始格式)"""
        return {
            symbol: self._convert_position(position) for symbol, position in self._positions.items()
        }

    def get_orders(self) -> Dict[str, OrderData]:
        """获取订单数据(兼容,返回原始格式)"""
        return {order_id: self._convert_order(order) for order_id, order in self._orders.items()}

    def get_trades(self) -> Dict[str, TradeData]:
        """获取成交数据(兼容,返回原始格式)"""
        return {trade_id: self._convert_trade(trade) for trade_id, trade in self._trades.items()}

    def get_quotes(self) -> Dict[str, TickData]:
        """获取行情数据(兼容,返回原始格式)"""
        return {symbol: self._convert_tick(quote) for symbol, quote in self._quotes.items() if quote.instrument_id}

    def get_kline(self, symbol: str, interval: str) -> Optional[DataFrame]:
        """获取K线数据"""
        try:
            if not self.connected or not self.api:
                logger.warning("TqSdk未连接")
                return None

            kline_data = self._klines.get((symbol, interval))  # type: ignore[call-overload]
            if kline_data is None:
                return None
            kline = kline_data.copy()
            kline["datetime"] = kline["datetime"].apply(lambda x: datetime.fromtimestamp(x / 1e9))
            return kline
        except Exception as e:
            logger.exception(f"获取K线数据失败: {e}")
            raise e

    # ==================== 数据转换 ====================
    def _interval_to_seconds(self, interval: str) -> int:
        """将时间间隔转换为秒数"""
        if interval.startswith("M"):
            return int(interval[1:]) * 60
        elif interval.startswith("H"):
            return int(interval[1:]) * 60 * 60
        else:
            raise ValueError(f"暂不支持的时间间隔: {interval}")

    def _convert_account(self, account: Account) -> AccountData:
        """转换账户数据"""
        return AccountData(
            account_id=self.account_id or "",
            balance=account.balance,
            available=account.available,
            margin=account.margin or 0,
            pre_balance=account.pre_balance or 0,
            hold_profit=account.position_profit or 0,
            close_profit=account.close_profit or 0,
            risk_ratio=account.risk_ratio or 0,
            update_time=datetime.now(),
            frozen=0,
            float_profit=account.position_profit or 0,
            broker_name=(
                getattr(self.config.broker, "broker_name", "--") if self.config.broker else "--"
            ),
            broker_type=getattr(self.config.broker, "type", "") if self.config.broker else "",
            currency="CNY",
            user_id="",
            gateway_connected=self.connected,
            status=None,
        )

    def _convert_position(self, pos: Position) -> PositionData:
        """转换持仓数据"""
        return PositionData(
            account_id=self.account_id,
            symbol=pos.instrument_id,
            exchange=self._parse_exchange(pos.exchange_id),
            pos=pos.pos_long - pos.pos_short,
            pos_long=int(pos.pos_long),
            pos_short=int(pos.pos_short),
            pos_long_yd=int(pos.pos_long_his),
            pos_short_yd=int(pos.pos_short_his),
            pos_long_td=int(pos.pos_long_today),
            pos_short_td=int(pos.pos_short_today),
            open_price_long=float(pos.open_price_long) or 0,
            open_price_short=float(pos.open_price_short) or 0,
            float_profit_long=float(pos.float_profit_long) or 0,
            float_profit_short=float(pos.float_profit_short) or 0,
            hold_profit_long=float(pos.position_profit_long) or 0,
            hold_profit_short=float(pos.position_profit_short) or 0,
            margin_long=float(pos.margin_long) or 0,
            margin_short=float(pos.margin_short) or 0,
        )

    def _convert_order(self, order: Order) -> OrderData:
        """转换订单数据"""
        # 判断订单状态
        error_msg = [
            "拒绝",
            "取消",
            "不足",
            "暂停",
            "禁止",
            "错误",
            "闭市",
            "未连接",
            "最小单位",
            "失败",
            "不",
            "超过",
        ]
        status_msg = order.get("last_msg", "")
        status = OrderStatus.PENDING
        if any(keyword in status_msg for keyword in error_msg):
            status = OrderStatus.REJECTED
        elif order.status == "FINISHED":
            status = OrderStatus.FINISHED

        data = OrderData(
            account_id=self.account_id or "",
            order_id=order.order_id,
            symbol=order.instrument_id,
            exchange=self._parse_exchange(order.exchange_id),
            direction=Direction(order.get("direction", "BUY")),
            offset=Offset(order.get("offset", "OPEN")),
            volume=int(order.volume_orign),
            traded=int(order.volume_orign) - int(order.volume_left),
            traded_price=float(order.trade_price) or 0,
            price=order.limit_price or 0,
            price_type=OrderType.LIMIT if order.limit_price else OrderType.MARKET,
            status=status,
            status_msg=status_msg,
            gateway_order_id=order.get("exchange_order_id", ""),
            insert_time=(
                datetime.fromtimestamp(order.get("insert_date_time", 0) / 1e9)
                if order.get("insert_date_time")
                else None
            ),
            update_time=datetime.now(),
            trading_day=self.trading_day,
        )
        return data

    def _convert_trade(self, trade: Trade) -> TradeData:
        """转换成交数据"""
        order_id = trade.get("order_id", "")
        exchange_id = trade.get("exchange_id", "")
        instrument_id = trade.get("instrument_id", "")

        return TradeData(
            account_id=self.account_id or "",
            trade_id=trade.get("trade_id", ""),
            order_id=order_id,
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            direction=Direction(trade.get("direction", "BUY")),
            offset=Offset(trade.get("offset", "OPEN")),
            price=float(trade.get("price", 0)),
            volume=int(trade.get("volume", 0)),
            trade_time=(
                datetime.fromtimestamp(trade.get("trade_date_time", 0) / 1e9)
                if trade.get("trade_date_time")
                else None
            ),
            trading_day=self.trading_day,
            commission=0,
        )

    def _convert_tick(self, quote: Quote) -> TickData:
        """转换tick数据"""
        exchange_id = quote.get("exchange_id", "")
        instrument_id = quote.get("instrument_id", "")
        try:
            datetime_obj = int(float(str(quote.get("datetime", 0)).strip()))
        except (ValueError, TypeError):
            datetime_obj = 0

        return TickData(
            symbol=instrument_id.split(".")[1],
            exchange=self._parse_exchange(exchange_id),
            datetime=datetime.fromtimestamp(datetime_obj / 1e9) if datetime_obj else datetime.now(),
            last_price=float(quote.get("last_price", 0)),
            volume=float(quote.get("volume", 0)),
            turnover=float(quote.get("turnover", 0)),
            open_interest=float(quote.get("open_interest", 0)),
            bid_price1=float(quote.get("bid_price1", 0)),
            ask_price1=float(quote.get("ask_price1", 0)),
            bid_volume1=float(quote.get("bid_volume1", 0)),
            ask_volume1=float(quote.get("ask_volume1", 0)),
            open_price=float(quote.get("open", 0)),
            high_price=float(quote.get("highest", 0)),
            low_price=float(quote.get("lowest", 0)),
            pre_close=float(quote.get("pre_open_interest", 0)),
            limit_up=float(quote.get("upper_limit", 0)),
            limit_down=float(quote.get("lower_limit", 0)),
        )

    def _convert_bar(self, symbol: str, interval: str, data, update: Union[int, float]) -> BarData:
        """
        转换K线数据

        Args:
            update: K线更新时间（纳秒时间戳，TqSdk格式）
        """
        bar = BarData(
            symbol=symbol,
            interval=interval,
            datetime=datetime.fromtimestamp(data["datetime"] / 1e9),
            open_price=float(data["open"]),
            high_price=float(data["high"]),
            low_price=float(data["low"]),
            close_price=float(data["close"]),
            volume=float(data["volume"]),
            turnover=float(data.get("turnover", 0)),
            open_interest=float(data.get("open_interest", 0)),
            update_time=datetime.fromtimestamp(update / 1e9),
        )
        # logger.info(f"收到新Bar: {data}")
        return bar


    def _collect_and_push_updates(self):
        """收集数据变化并推送到同步队列（在轮询线程中调用）"""
        try:
            if self.api is None:
                return
            # 检查订单变化(只需检查挂单)
            to_delete = []
            for order in list(self._pending_orders.values()):
                if self.api.is_changing(order):
                    order_data = self._convert_order(order)
                    self._push_order(order_data)
                    if order.status == "FINISHED":
                        to_delete.append(order.order_id)
            for order_id in to_delete:
                self._pending_orders.pop(order_id, None)

            # 检查成交变化
            if self.api.is_changing(self._trades):
                for trade in self._trades.values():
                    if self.api.is_changing(trade):
                        trade_data = self._convert_trade(trade)
                        self._push_trade(trade_data)

            # 检查持仓变化
            if self.api.is_changing(self._positions):
                for position in self._positions.values():
                    if self.api.is_changing(position, ["pos_long", "pos_short"]):
                        position_data = self._convert_position(position)
                        self._push_position(position_data)

            # 检查账户变化
            #if self.api.is_changing(self._account):
            #    account_data = self._convert_account(self._account)
            #    self._push_account(account_data)

            # 检查行情变化
            for quote in self._quotes.values():
                if self.api.is_changing(quote):
                    tick_data = self._convert_tick(quote)
                    self._push_tick(tick_data)

            # 检查K线变化
            for key, kline in self._klines.items():
                symbol, interval = key[0], key[1]
                if self.api.is_changing(kline.iloc[-1], "datetime"):
                    bar_data = self._convert_bar(
                        symbol, interval, kline.iloc[-2], kline.iloc[-1]["datetime"]
                    )
                    self._push_bar(bar_data)

        except Exception as e:
            logger.exception(f"收集数据变化异常: {e}")

    def _push_to_queue(self, event_type: str, data: Any):
        """推送数据到同步队列（非阻塞）"""
        try:
            self._sync_queue.put_nowait((event_type, data))
        except queue.Full:
            logger.warning(f"事件队列已满，丢弃事件: {event_type}")

    def _push_tick(self, tick_data: TickData):
        """推送Tick数据到同步队列（非阻塞）"""
        self._push_to_queue("tick", tick_data)

    def _push_bar(self, bar_data: BarData):
        """推送Bar数据到同步队列（非阻塞）"""
        self._push_to_queue("bar", bar_data)

    def _push_trade(self, trade_data: TradeData):
        """推送Trade数据到同步队列（非阻塞）"""
        self._push_to_queue("trade", trade_data)
        logger.info(f"成交回报: {trade_data}")

    def _push_position(self, position_data: PositionData):
        """推送Position数据到同步队列（非阻塞）"""
        self._push_to_queue("position", position_data)

    def _push_account(self, account_data: AccountData):

        """推送Account数据到同步队列（非阻塞）"""
        self._push_to_queue("account", account_data)
    def _push_order(self, order_data: OrderData):
        """推送Order数据到同步队列（非阻塞）"""
        self._push_to_queue("order", order_data)
        logger.info(f"报单回报: {order_data}")

    def _push_contract(self, contract_data: ContractData):
        """推送Contract数据到同步队列（非阻塞）"""
        self._push_to_queue("contract", contract_data)
     

    def _tq_run(self):
        """
        TqSdk主线程（独立线程中运行）

        职责：
        1. 连接API
        2. 检测数据变化
        3. 将变化数据推送到同步队列
        """
        try:
            #开始连接
            self._running = True

            # 创建认证
            tianqin_config: Any = self.config.tianqin if self.config.tianqin else None
            username = getattr(tianqin_config, "username", "") if tianqin_config else ""
            password = getattr(tianqin_config, "password", "") if tianqin_config else ""
            if username and password:
                self.auth = TqAuth(username, password)
            else:
                self.auth = None

            # 根据账户类型创建账户对象
            broker_type = self.config.broker.type if self.config.broker else "sim"
            if broker_type == "kq":
                account = TqKq()
            elif broker_type == "real":
                account = TqAccount(
                    broker_id=self.config.broker.broker_name if self.config.broker else "",
                    account_id=self.config.broker.user_id if self.config.broker else "",
                    password=self.config.broker.password if self.config.broker else "",
                )
            elif broker_type == "rohon":
                account = TqRohon(
                    front_broker=self.config.broker.broker_name if self.config.broker else "",
                    account_id=self.config.broker.user_id if self.config.broker else "",
                    password=self.config.broker.password if self.config.broker else "",
                    app_id=self.config.broker.app_id if self.config.broker else "",
                    auth_code=self.config.broker.auth_code if self.config.broker else "",
                    front_url=self.config.broker.url if self.config.broker else "",
                )
            else:  # sim
                account = TqSim()

            # 创建TqApi
            self.api = TqApi( account, auth=self.auth, web_gui=False)
            assert self.api is not None  # 确保类型检查器知道 api 不是 None

            # 获取账户和持仓、成交、委托单初始数据
            self._account = self.api.get_account()
            self._positions = self.api.get_position()
            self._orders = self.api.get_order()
            self._trades = self.api.get_trade()

            # 发送初始数据
            self.connected = True
            self._push_account(self._convert_account(self._account))

            # 加载合约列表：先从数据库加载今天的，如果没有则从API查询
            #if len(self._contracts) <= 0:
            self._query_and_save_contracts(datetime.now().strftime("%Y-%m-%d"))

            self.trading_day = self.get_trading_day()
            logger.info(f"TqSdk连接成功,交易日: {self.trading_day}")

            # 初始化持仓合约的行情订阅
            pos_symbols = [symbol for symbol in self._positions if symbol not in self._quotes]
            self.hist_subs.extend(pos_symbols)
            self.subscribe(list(self.hist_subs))

            # 订阅kline
            for symbol, interval in self.kline_subs:
                self.subscribe_bars(symbol, interval)

            logger.info("TqSdk开始轮询...")
            while self._running:
                if self.api is None:
                    break

                try:
                    has_data = self.api.wait_update(deadline=time.time() + 3)

                    if has_data:
                        self._collect_and_push_updates()

                except Exception as e:
                    logger.error(f"轮询线程异常: {e}")
                    time.sleep(1)
            self.connected = False
            self._push_account(self._convert_account(self._account))
            logger.info("TqSdk轮询线程已退出")

        except Exception as e:
            logger.exception(f"轮询线程致命错误: {e}")
        finally:
            if self.api:
                self.api.close()
                self.api = None

    async def _event_dispatcher(self):
        """
        事件分发协程（在主线程事件循环中运行）

        职责：
        1. 从同步队列获取数据
        2. 转换为AsyncEventEngine事件类型
        3. 直接推送到AsyncEventEngine
        """
        try:
            logger.info("事件分发协程已启动")

            while self._running:
                try:
                    # 从同步队列获取数据（超时1秒）
                    if self._sync_queue.empty():
                        await asyncio.sleep(0)
                        continue
                    event_type, data = await asyncio.to_thread(self._sync_queue.get, timeout=1.0)
                    # 映射到AsyncEventEngine事件类型
                    engine_event_type = self._map_event_type(event_type)
                    # 直接推送到AsyncEventEngine
                    if self._event_engine and engine_event_type:
                        self._event_engine.put(engine_event_type, data)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.exception(f"事件分发异常: {e}")

            logger.info("事件分发协程已退出")

        except asyncio.CancelledError:
            logger.info("事件分发协程已取消")
        except Exception as e:
            logger.exception(f"事件分发协程致命错误: {e}")

    def _map_event_type(self, gateway_event: str) -> Optional[str]:
        """映射Gateway事件类型到AsyncEventEngine事件类型"""
        from src.utils.event_engine import EventTypes

        mapping = {
            "tick": EventTypes.TICK_UPDATE,
            "bar": EventTypes.KLINE_UPDATE,
            "order": EventTypes.ORDER_UPDATE,
            "trade": EventTypes.TRADE_UPDATE,
            "position": EventTypes.POSITION_UPDATE,
            "account": EventTypes.ACCOUNT_UPDATE,
            "contract": EventTypes.CONTRACT_UPDATE,
        }
        return mapping.get(gateway_event)

    def _format_symbol(self, symbol: str) -> Optional[str]:
        """格式化合约代码"""
        if not symbol:
            return None
        upper_symbol = symbol.upper()
        for part in upper_symbol.rsplit("."):
            if part in self._upper_symbols:
                return self._upper_symbols[part]
        logger.warning(f"未找到匹配的合约符号: {symbol}")

    def _parse_exchange(self, exchange_code: str) -> Exchange:
        """解析交易所代码"""
        return exchange_map.get(exchange_code.upper(), Exchange.NONE)
