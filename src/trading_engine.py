"""
交易引擎核心模块
负责连接TqSdk、管理交易会话、处理行情和交易
"""
import asyncio
import math
from datetime import datetime
import time
from os import listdrives
from typing import Any, Dict, List, Optional
from threading import Thread


from tqsdk import TqApi, TqAuth, TqKq, TqSim
from tqsdk.objs import Account, Order, Position, Quote, Trade

from src.config_loader import AppConfig
from src.risk_control import RiskControl
from src.utils.helpers import nanos_to_datetime_str, parse_symbol
from src.utils.logger import get_logger
from src.utils.event import event_engine, EventTypes


logger = get_logger(__name__)

class TradingEngine:
    """交易引擎类"""

    def __init__(self, config: AppConfig):
        """
        初始化交易引擎

        Args:
            config: 应用配置对象
        """

        self.config = config
        self.account_id = config.account_id
        self.api: Optional[TqApi] = None
        self.auth: Optional[TqAuth] = None
        self.account: Optional[Any] = None
        self.connected = False
        self.paused = config.trading.paused
        self._running = False
        self._pending_disconnect = False

        # 订阅的数据（从tqsdk获取）
        self.quotes: Dict[str, Quote] = {}
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.trades: Dict[str, Trade] = {}

        # 风控模块
        self.risk_control = RiskControl(config.risk_control)

        # 事件引擎
        self.event_engine = event_engine

        logger.info(f"交易引擎初始化完成，账户类型: {config.account_type}")

    def connect(self) -> bool:
        """
        连接到TqSdk

        Returns:
            bool: 连接是否成功
        """
        try:
            logger.info("连接到TqSdk...")
            # 创建认证
            self.auth = TqAuth(self.config.tianqin.username, self.config.tianqin.password)

            # 根据账户类型创建对应的账户对象
            if self.config.account_type == "kq":
                # 快期模拟账户
                account = TqKq()
                logger.info("使用快期模拟账户连接")
            elif self.config.account_type == "sim":
                # 本地模拟账户
                account = TqSim()
                logger.info("使用本地模拟账户连接")
            else:  # account_type == "account"
                # 实盘账户
                if not self.config.trading_account:
                    raise ValueError("实盘账户需要配置 trading_account")
                from tqsdk import TqAccount
                account = TqAccount(
                    self.config.trading_account.broker_name,
                    self.config.trading_account.user_id,
                    self.config.trading_account.password,
                )
                logger.info(f"使用实盘账户连接: {self.config.trading_account.broker_name}")

            # 创建TqApi实例
            self.api = TqApi(account, auth=self.auth, web_gui=False)
            self.connected = True
            self._running = True


            # 获取账户信息
            self.account = self.api.get_account()
            logger.info(f"成功连接到TqSdk，账户ID: {self.config.account_id},账户详情：{self.account}")

            # 获取持仓信息
            self.positions = self.api.get_position()
            logger.info(f"成功获取持仓信息: {len(self.positions)}条")

            # 获取成交记录
            self.trades = self.api.get_trade()
            logger.info(f"成功获取成交记录: {len(self.trades)}条")

            # 获取挂单
            #orders = self.api.get_order()
            #self.orders = {id:order for id, order in orders.items() if order.status == "ALIVE"}
            self.orders = self.api.get_order()
            logger.info(f"成功获取挂单信息: {len(self.orders)}条")

            # 根据orders列表初始化当日已发送的报单次数和撤单次数
            self._init_risk_counts_from_orders()

            # 查询合约信息
            list = self.api.query_quotes(ins_class=["FUTURE"],expired=False)
            # 将合约列表如(['SHFE.ru2608', 'GFEX.ps2611') 转为dict,key为合约代码，value为交易所代码
            self.symbols = {symbol.split(".")[1]: symbol.split(".")[0] for symbol in list}
            # 大写合约代码：合约全称 JD2605:DCE.jd2605
            self.upper_symbols = {symbol.split(".")[1].upper(): symbol for symbol in list}
            logger.info(f"成功查询到{len(list)}个合约")

            # 初始化订阅
            self._init_subscriptions()

            # 推送账户状态事件
            self._emit_event(EventTypes.ACCOUNT_STATUS, {
                "account_id": self.config.account_id,
                "account_type": self.config.account_type,
                "status": "connected",
            })

            # 开启接收数据循环
            self.loop_thread = Thread(target=self.loop_run,daemon=True)
            self.loop_thread.start()
            return True

        except Exception as e:
            logger.error(f"连接TqSdk失败: {e}")
            self.connected = False
            return False

    def loop_run(self) -> None:
        """主循环运行"""
        while self._running:
            try:
                # 检查是否有待处理的断开连接请求
                if self._pending_disconnect:
                    self._do_disconnect()
                    break

                self.update()
            except Exception as e:
                logger.error(f"主循环更新出错: {e}")
            #sleep(1)


    def disconnect(self) -> None:
        """请求断开TqSdk连接（设置标志位，由主循环执行）"""
        if not self._pending_disconnect and self.connected:
            self._pending_disconnect = True
            logger.info("已设置断开连接请求")

    def _do_disconnect(self) -> None:
        """实际执行断开TqSdk连接（在主循环中调用）"""
        if self.api:
            try:
                self.api.close()
                logger.info("已断开TqSdk连接")

                # 推送账户状态事件
                self._emit_event(EventTypes.ACCOUNT_STATUS, {
                    "account_id": self.config.account_id,
                    "status": "disconnected",
                    "timestamp": datetime.now().isoformat(),
                })

            except Exception as e:
                logger.error(f"断开连接时出错: {e}")
        self.connected = False
        self._pending_disconnect = False
        self._running = False
        self.api = None

    def _init_risk_counts_from_orders(self) -> None:
        """
        根据orders列表初始化当日已发送的报单次数和撤单次数
        """
        try:
            today = datetime.now().date()
            daily_order_count = 0
            daily_cancel_count = 0

            for order_id, order in self.orders.items():
                insert_time = order.get("insert_date_time", 0)
                order_time = datetime.fromtimestamp(insert_time / 1e9).date()

                # 只统计今日的报单
                if order_time == today:
                    daily_order_count += 1

                    # 统计已撤单的订单（状态为FINISHED且不是正常成交的）
                    order_status = order.get("status", "")
                    if order_status == "FINISHED" and order.get("volume_left", 0) > 0:
                        daily_cancel_count += 1
                    elif order_status in ["ALIVE", "CANCELED", "CANCELLED"]:
                        # 也可以根据实际订单状态判断
                        pass

            self.risk_control.daily_order_count = daily_order_count
            self.risk_control.daily_cancel_count = daily_cancel_count
            self.risk_control._last_reset_date = today

            logger.info(
                f"从orders列表初始化风控计数 - 当日报单: {daily_order_count}, "
                f"当日撤单: {daily_cancel_count}"
            )

        except Exception as e:
            logger.error(f"初始化风控计数失败: {e}")

    def _init_subscriptions(self) -> None:
        """初始化行情订阅"""
        # 订阅tick行情
        for symbol in self.positions.keys():
            try:
                quote = self.api.get_quote(symbol)
                self.quotes[symbol] = quote
                logger.info(f"已订阅tick行情: {symbol}")

            except Exception as e:
                logger.error(f"订阅 {symbol} 失败: {e}")

    def update(self) -> bool:
        """
        更新交易数据（在主循环中调用）

        Returns:
            bool: 是否继续运行
        """
        if not self.connected or not self.api:
            return False

        try:
            # 等待数据更新（设置3秒超时，以便及时响应断开连接请求）
            has_data = self.api.wait_update(time.time() + 3)
            if not has_data:
                return False

            # 检查是否有数据更新
            self._check_and_save_account()
            self._check_and_save_positions()
            self._check_and_save_orders()
            self._check_and_save_trades()
            # 检查行情更新
            self._check_and_emit_tick_updates()
            return True

        except Exception as e:
            logger.error(f"更新数据时出错: {e}")
            self._emit_event(EventTypes.SYSTEM_ERROR, {"error": str(e)})
            return False

    def _check_and_save_account(self) -> None:
        """检查并推送账户信息"""
        if self.api.is_changing(self.account):
            try:
                user_id = None
                if self.config.account_type == "account" and self.config.trading_account:
                    user_id = self.config.trading_account.user_id

                account_id = user_id if user_id else "-"
                account_data = {
                    "account_id": account_id,
                    "balance": float(self.account.get("balance", 0)),
                    "available": float(self.account.get("available", 0)),
                    "margin": float(self.account.get("margin", 0)),
                    "float_profit": float(self.account.get("float_profit", 0)),
                    "position_profit": float(self.account.get("position_profit", 0)),
                    "close_profit": float(self.account.get("close_profit", 0)),
                    "risk_ratio": float(self.account.get("risk_ratio", 0)),
                    "updated_at": datetime.now().isoformat(),
                    "user_id": user_id,
                }

                # logger.info(f"账户更新 - balance: {account_data['balance']:.2f}, "
                #           f"available: {account_data['available']:.2f}, "
                #           f"float_profit: {account_data['float_profit']:.2f}, "
                #           f"position_profit: {account_data['position_profit']:.2f}")

                # 推送事件
                self._emit_event(EventTypes.ACCOUNT_UPDATE, account_data)

            except Exception as e:
                logger.error(f"处理账户信息时出错: {e}")

    def _check_and_save_positions(self) -> None:
        """检查并推送持仓信息"""
        # 获取所有持仓
        all_positions = self.api.get_position()
        if self.api.is_changing(all_positions):
            try:
                account_id = self.config.account_id

                for symbol, pos in all_positions.items():
                    if self.api.is_changing(pos):
                        self.positions[symbol] = pos

                        # 推送持仓更新事件（tqsdk原始数据）
                        event_data = {
                            "account_id": account_id,
                            "symbol": symbol,
                            "pos_long": pos.get("pos_long", 0),
                            "pos_short": pos.get("pos_short", 0),
                            "open_price_long": pos.get("open_price_long", 0),
                            "open_price_short": pos.get("open_price_short", 0),
                            "float_profit": float(pos.get("float_profit", 0)),
                            "margin": float(pos.get("margin", 0)),
                            "updated_at": datetime.now().isoformat(),
                        }

                        # logger.info(f"持仓更新 - symbol: {symbol}, "
                        #           f"pos_long: {event_data['pos_long']}, "
                        #           f"pos_short: {event_data['pos_short']}, "
                        #           f"float_profit: {event_data['float_profit']:.2f}")

                        # 推送持仓更新事件
                        self._emit_event(EventTypes.POSITION_UPDATE, event_data)

            except Exception as e:
                logger.error(f"处理持仓信息时出错: {e}")

    def _check_and_save_orders(self) -> None:
        """检查并推送委托单信息"""
        # 获取所有委托单
        all_orders = self.api.get_order()
        if self.api.is_changing(all_orders):
            try:
                account_id = self.config.account_id

                for order_id, order in all_orders.items():
                    if self.api.is_changing(order):
                        self.orders[order_id] = order

                        # 推送事件（tqsdk原始数据）
                        event_data = {
                            "order_id": order_id,
                            "account_id": account_id,
                            "exchange_order_id": order.get("exchange_order_id", ""),
                            "symbol": order.get("exchange_id", "") + "." + order.get("instrument_id", ""),
                            "direction": order.get("direction", ""),
                            "offset": order.get("offset", ""),
                            "volume_orign": order.get("volume_orign", 0),
                            "volume_left": order.get("volume_left", 0),
                            "limit_price": float(order.get("limit_price", 0)) if order.get("limit_price") else None,
                            "price_type": order.get("price_type", ""),
                            "status": order.get("status", ""),
                            "insert_date_time": order.get("insert_date_time", 0),
                            "last_msg": order.get("last_msg", ""),
                            "updated_at": datetime.now().isoformat(),
                        }

                        logger.info(f"委托单更新 - order_id: {order_id}, "
                                  f"symbol: {event_data['symbol']}, "
                                  f"direction: {event_data['direction']}, "
                                  f"offset: {event_data['offset']}, "
                                  f"volume_orign: {event_data['volume_orign']}, "
                                  f"volume_left: {event_data['volume_left']}, "
                                  f"limit_price: {event_data['limit_price']:.2f} " if event_data['limit_price'] else "None",
                                  f"price_type: {event_data['price_type']}, "
                                  f"status: {event_data['status']}, ")

                        # 推送委托单更新事件
                        self._emit_event(EventTypes.ORDER_UPDATE, event_data)

            except Exception as e:
                logger.error(f"处理委托单信息时出错: {e}")

    def _check_and_save_trades(self) -> None:
        """检查并推送成交信息"""
        # 获取所有委托单的成交记录
        all_orders = self.api.get_order()

        for order_id, order in all_orders.items():
            if self.api.is_changing(order):
                trade_records = order.get("trade_records", {})
                for trade_id, trade in trade_records.items():
                    try:
                        account_id = self.account.get("account_id", "")

                        # 检查是否已记录
                        existing = next((t for t in self.trades if t.get("trade_id") == trade_id), None)
                        if existing:
                            continue

                        # 添加到成交列表
                        trade_data = {
                            "trade_id": trade_id,
                            "order_id": order_id,
                            "account_id": account_id,
                            "symbol": trade.get("exchange_id", "") + "." + trade.get("instrument_id", ""),
                            "direction": trade.get("direction", ""),
                            "offset": trade.get("offset", ""),
                            "price": float(trade.get("price", 0)),
                            "volume": trade.get("volume", 0),
                            "trade_date_time": trade.get("trade_date_time", 0),
                            "created_at": datetime.now().isoformat(),
                        }
                        self.trades.append(trade_data)

                        logger.bind(tags=["trade"]).info(
                            f"成交更新 - trade_id: {trade_id}, "
                            f"symbol: {trade_data['symbol']}, "
                            f"direction: {trade_data['direction']}, "
                            f"offset: {trade_data['offset']}, "
                            f"volume: {trade_data['volume']}, "
                            f"price: {trade_data['price']:.2f}"
                        )

                        # 推送成交更新事件（tqsdk原始数据）
                        self._emit_event(EventTypes.TRADE_UPDATE, trade_data)

                    except Exception as e:
                        logger.error(f"处理成交信息时出错: {e}")

    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
    ) -> Optional[str]:
        """
        下单

        Args:
            symbol: 合约代码，支持格式：合约编号(如a2605)、合约编号.交易所(如a2605.DCE)、交易所.合约编号(如DCE.a2605)
            direction: 方向 (BUY/SELL)
            offset: 开平 (OPEN/CLOSE/CLOSETODAY)
            volume: 手数
            price: 0-市价，>0限价

        Returns:
            Optional[str]: 委托单ID，失败返回None
        """
        if not self.connected or not self.api:
            logger.error("交易引擎未连接，无法下单")
            raise Exception("交易引擎未连接，无法下单")

        if self.paused:
            logger.warning("交易已暂停，无法下单")
            raise Exception("交易已暂停，无法下单")

        # 风控检查
        if not self.risk_control.check_order(volume):
            logger.error(f"风控检查失败: 手数 {volume} 超过限制")
            raise Exception(f"风控检查失败: 手数 {volume} 超过限制")

        # 格式化合约代码
        formatted_symbol = self._format_symbol(symbol)
        if not formatted_symbol:
            logger.error(f"无效的合约代码: {symbol}")
            raise Exception(f"无效的合约代码: {symbol}")

        try:
            # 获取行情信息（用于市价单）
            if formatted_symbol not in self.quotes:
                self.subscribe_symbol(formatted_symbol)
            quote = self.quotes.get(formatted_symbol)
            if math.isnan(quote.get('last_price')):
                logger.error(f"未获取到行情信息: {formatted_symbol}")
                raise Exception(f"未获取到行情信息: {formatted_symbol}")
            if price==0  or not price:
                # 市价单使用对手价
                if direction == "BUY":
                    price = quote.get("ask_price1", 0)
                else:
                    price = quote.get("bid_price1", 0)
            else:
                upper_limit = quote.get("upper_limit", 0)
                low_limit = quote.get("low_limit", 0)
                if price > upper_limit or price < low_limit:
                    logger.error(f"限价 {price} 超过涨跌幅 {low_limit}-{upper_limit}")
                    raise Exception(f"限价 {price} 超过涨跌幅 {low_limit}-{upper_limit}")

            # 下单
            order = self.api.insert_order(
                symbol=formatted_symbol,
                direction=direction,
                offset=offset,
                volume=volume,
                limit_price=price,
            )

            order_id = order.get("order_id", "")

            logger.bind(tags=["trade"]).info(
                f"下单: {formatted_symbol} {direction} {offset} {volume}手 @{price}, 委托单ID: {order_id}"
            )

            self.orders[order_id] = order
            # 更新风控计数
            self.risk_control.on_order_inserted()

            # 推送委托单更新事件
            self._emit_event(EventTypes.ORDER_UPDATE, {
                "order_id": order_id,
                "account_id": self.config.account_id,
                "symbol": formatted_symbol,
                "direction": direction,
                "offset": offset,
                "volume": volume,
                "price": float(price) if price else None,
                "price_type": "LIMIT" if price else "MARKET",
                "timestamp": datetime.now().isoformat(),
            })

            return order_id

        except Exception as e:
            raise Exception(f"下单失败: {e}")

    def _format_symbol(self, symbol: str) -> Optional[str]:
        """
        格式化合约代码

        Args:
            symbol: 合约代码，支持：
                    - 合约编号，如 a2605
                    - 合约编号.交易所，如 a2605.DCE
                    - 交易所.合约编号，如 DCE.a2605

        Returns:
            Optional[str]: 格式化后的合约代码（交易所.合约编号），失败返回None
        """
        if not symbol:
            return None

        # 如果包含点号
        if "." in symbol:
            parts = symbol.split(".")
            if len(parts) != 2:
                return None
            part1, part2 = parts[0], parts[1]

            # 判断是 "交易所.合约编号" 还是 "合约编号.交易所"
            if part1.upper() in self.upper_symbols.keys():
                return self.upper_symbols[part1.upper()]
            elif part2.upper() in self.upper_symbols.keys():
                # part2是交易所，格式为 "合约编号.交易所"，如 "a2605.DCE"
                return self.upper_symbols[part2.upper()]  
            else:
                return None
        else:
            # 没有点号，认为是合约编号，需要查询交易所
            if symbol.upper() in self.upper_symbols.keys():
                return self.upper_symbols[symbol.upper()]
            else:
                return None

    def cancel_order(self, order_id: str) -> bool:
        """
        撤单

        Args:
            order_id: 委托单ID

        Returns:
            bool: 是否成功
        """
        if not self.connected or not self.api:
            logger.error("交易引擎未连接，无法撤单")
            return False

        try:
            # 获取委托单
            all_orders = self.api.get_order()
            order = all_orders.get(order_id)

            if not order:
                logger.error(f"委托单不存在: {order_id}")
                return False

            # 撤单
            self.api.cancel_order(order)

            logger.bind(tags=["trade"]).info(f"撤单: {order_id}")

            # 更新风控计数
            self.risk_control.on_order_cancelled()

            # 推送委托单更新事件
            self._emit_event(EventTypes.ORDER_UPDATE, {
                "order_id": order_id,
                "status": "cancelled",
                "timestamp": datetime.now().isoformat(),
            })

            return True

        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    def pause(self) -> None:
        """暂停交易"""
        self.paused = True
        logger.info("交易已暂停")

        self._emit_event(EventTypes.ACCOUNT_STATUS, {
            "account_id": self.config.account_id,
            "status": "paused",
            "timestamp": datetime.now().isoformat(),
        })

    def resume(self) -> None:
        """恢复交易"""
        self.paused = False
        logger.info("交易已恢复")

        self._emit_event(EventTypes.ACCOUNT_STATUS, {
            "account_id": self.config.account_id,
            "status": "running",
            "timestamp": datetime.now().isoformat(),
        })

    def get_status(self) -> Dict[str, Any]:
        """
        获取引擎状态

        Returns:
            状态字典
        """
        return {
            "connected": self.connected,
            "paused": self.paused,
            "account_id": getattr(self.account, "user_id", "") if self.account else "",
            "daily_orders": self.risk_control.daily_order_count,
            "daily_cancels": self.risk_control.daily_cancel_count,
        }

    def subscribe_symbol(self, symbol: str) -> bool:
        """
        订阅合约行情

        Args:
            symbol: 合约代码

        Returns:
            bool: 是否订阅成功
        """
        if not self.connected or not self.api:
            logger.error("交易引擎未连接，无法订阅行情")
            return False

        try:
            if symbol in self.quotes:
                logger.debug(f"合约 {symbol} 已订阅")
                return True

            quote = self.api.get_quote(symbol)
            self.quotes[symbol] = quote
            logger.info(f"已订阅行情: {symbol}")
            return True

        except Exception as e:
            logger.error(f"订阅 {symbol} 失败: {e}")
            return False

    def is_subscribed(self, symbol: str) -> bool:
        """
        检查合约是否已订阅

        Args:
            symbol: 合约代码

        Returns:
            bool: 是否已订阅
        """
        return symbol in self.quotes

    def get_subscribed_symbols(self) -> List[str]:
        """
        获取所有已订阅的合约代码

        Returns:
            List[str]: 已订阅的合约代码列表
        """
        return list(self.quotes.keys())

    def unsubscribe_symbol(self, symbol: str) -> bool:
        """
        取消订阅合约行情

        Args:
            symbol: 合约代码

        Returns:
            bool: 是否取消成功
        """
        if not self.connected or not self.api:
            logger.error("交易引擎未连接，无法取消订阅")
            return False

        try:
            if symbol in self.quotes:
                del self.quotes[symbol]
                logger.info(f"已取消订阅: {symbol}")
                return True
            else:
                logger.warning(f"合约 {symbol} 未订阅，无需取消")
                return False
        except Exception as e:
            logger.error(f"取消订阅 {symbol} 失败: {e}")
            return False

    def _check_and_emit_tick_updates(self) -> None:
        """检查并推送tick行情更新事件"""
        for symbol, quote in self.quotes.items():
            if self.api.is_changing(quote):
                try:
                    if  math.isnan(quote.get("last_price", 0)):
                        continue

                    # 推送tick更新事件（tqsdk原始数据）
                    event_data = {
                        "symbol": symbol,
                        "last_price": quote.get("last_price", 0),
                        "bid_price1": quote.get("bid_price1", 0),
                        "ask_price1": quote.get("ask_price1", 0),
                        "volume": quote.get("volume", 0),
                        "open_interest": quote.get("open_interest", 0),
                        "datetime": quote.get("datetime", 0),
                        "timestamp": datetime.now().isoformat(),
                    }

                    logger.debug(f"行情更新 - symbol: {symbol}, "
                                f"last_price: {event_data['last_price']:.2f}, "
                                f"bid_price1: {event_data['bid_price1']:.2f}, "
                                f"ask_price1: {event_data['ask_price1']:.2f}")

                    self._emit_event(EventTypes.TICK_UPDATE, event_data)

                except Exception as e:
                    logger.error(f"推送tick事件失败 {symbol}: {e}")

    def _emit_event(self, event_type: str, data: Any) -> None:
        """
        推送事件到事件引擎

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        try:
            self.event_engine.put(event_type, data)
        except Exception as e:
            logger.error(f"推送事件失败 [{event_type}]: {e}")
