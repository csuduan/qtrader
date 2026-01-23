"""
TqSdk Gateway适配器
"""
from datetime import datetime
from typing import Optional, Dict, Any, List,Union,Set
import threading
import time

from tqsdk import TqApi, TqAuth, TqKq, TqSim, TqAccount
from tqsdk.objs import Account, Order, Position, Quote, Trade

from src.adapters.base_gateway import BaseGateway
from src.models.object import (
    TickData, BarData, OrderData, TradeData,
    PositionData, AccountData, ContractData,
    SubscribeRequest, OrderRequest, CancelRequest,
    Direction, Offset, Status, OrderType, Exchange, ProductType
)
from src.utils.logger import get_logger

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
    """TqSdk Gateway适配器(完整实现)"""

    gateway_name = "TqSdk"

    def __init__(self, trading_engine=None):
        super().__init__()
        self.trading_engine = trading_engine
        self.connected = False
        
        # TqSdk API实例
        self.api: Optional[TqApi] = None
        self.auth: Optional[TqAuth] = None
        
        # 数据缓存(转换为统一模型)
        self._account: Optional[AccountData] = None
        self._positions: Dict[str, List[PositionData]] = {}
        self._orders: Dict[str, OrderData] = {}
        self._trades: Dict[str, TradeData] = {}
        self._quotes: Dict[str, TickData] = {}
        self._contracts: Dict[str, ContractData] = {}
        
        # TqSdk原始数据缓存(用于is_changing检查)
        self._tq_account: Optional[Account] = None
        self._tq_positions: Dict[str, Position] = {}
        self._tq_orders: Dict[str, Order] = {}
        self._tq_trades: Dict[str, Trade] = {}
        self._tq_quotes: Dict[str, Quote] = {}
        
        # 合约符号映射(原始symbol -> 统一symbol)
        self._upper_symbols: Dict[str, str] = {}
        
        # 配置(在connect时设置)
        self.config = None
        self.account_id = None

        # 历史订阅的合约符号列表
        self.hist_subs: Set[str] = []
        
     
        # 订单引用计数
        self._order_ref = 0


    
    
    # ==================== 连接管理 ====================
    
    def connect(self) -> bool:
        """
        连接到TqSdk
        """
        try:
            if not self.trading_engine:
                logger.error("TradingEngine实例未传入，无法连接")
                return False
            
            if self.connected:
                logger.warning("已连接到TqSdk,无需重复连接")
                return True

            config = self.trading_engine.config
            self.config = config
            self.account_id = config.account_id
            account_type = config.account_type
            
            logger.info(f"连接到TqSdk,账户类型: {account_type}, 账户ID: {self.account_id}")

            # 创建认证
            tianqin = config.tianqin if config.tianqin else {}
            username = getattr(tianqin, 'username', '')
            password = getattr(tianqin, 'password', '')
            if username and password:
                self.auth = TqAuth(username, password)
            else:
                self.auth = None

            # 根据账户类型创建账户对象
            if account_type == 'kq':
                account = TqKq()
            elif account_type == 'real':
                trading_cfg = config.trading_account if config.trading_account else {}
                account = TqAccount(
                    broker_id=getattr(trading_cfg, 'broker_name', ''),
                    user_id=getattr(trading_cfg, 'user_id', ''),
                    password=getattr(trading_cfg, 'password', ''),
                )
            else:  # sim
                account = TqSim()
            
            # 创建TqApi
            self.api = TqApi(account, auth=self.auth, web_gui=False)
            
            # 获取账户和持仓、成交、委托单初始数据
            self._tq_account = self.api.get_account()
            self._tq_positions = self.api.get_position()
            self._tq_orders = self.api.get_order()
            self._tq_trades = self.api.get_trade()
            
            # 获取合约列表
            ls = self.api.query_quotes(ins_class=["FUTURE"], expired=False)
            symbol_infos = self.api.query_symbol_info(ls)
            for index,item in symbol_infos.iterrows():
                instrument_id = item.instrument_id
                if item.exchange_id not in exchange_map:
                    continue
                contract = ContractData(
                    symbol=instrument_id,
                    exchange=exchange_map[item.exchange_id],
                    name=item.instrument_name,
                    size=item.volume_multiple,
                    price_tick=item.price_tick,
                    max_volume=item.max_limit_order_volume,
                )
                self._contracts[contract.symbol] = contract     
                self._upper_symbols[contract.symbol.rsplit(".")[1].upper()] = contract.symbol
            logger.info(f"成功加载{len(self._contracts)}个合约")           
            
            # 初始化持仓合约的行情订阅
            pos_symbols =  [symbol for symbol in self._tq_positions if symbol not in self._quotes]
            self.subscribe(pos_symbols)
            self.subscribe(list(self.hist_subs))
              
            # 转换并缓存数据
            self._convert_and_cache_data()
            
            self.connected = True
            self.trading_day = datetime.now().strftime("%Y%m%d")
            logger.info(f"TqSdk连接成功,交易日: {self.trading_day}")

            # 启动主循环线程
            loop_thread = threading.Thread(target=self.loop_run, daemon=True)
            loop_thread.start()

            return True
            
        except Exception as e:
            logger.exception(f"TqSdk连接失败{e}")
            return False
    
    def disconnect(self) -> bool:
        """断开TqSdk连接"""
        try:
            #只设置连接断开，由主线程释放api
            self.connected = False
            logger.info("TqSdk已断开连接")
            return True
        except Exception as e:
            logger.error(f"TqSdk断开连接失败: {e}", exc_info=True)
            return False

    def loop_run(self) -> None:
        """主循环运行"""
        logger.info("Tq主循环已启动")
        while True:
            try:
                # 检查是否有待处理的断开连接请求
                if not self.connected:
                    if self.api:
                        self.api.close()
                        self.api = None
                        logger.info("TqSdk已销毁")
                    break

                self.wait_update()
            except Exception as e:
                logger.error(f"主循环更新出错: {e}")
        logger.info("Tq主循环已退出")
    
    # ==================== 行情订阅 ====================
    
    def subscribe(self, symbol: Union[str, List[str]]) -> bool:
        """订阅行情"""
        try:
            if isinstance(symbol, str):
                symbol = [symbol]
            
            # 添加到订阅列表中     
            self.hist_subs.update(symbol)
            if not self.connected:
                return

            # 格式化合约代码
            std_symbols = [self._format_symbol(sym) for sym in symbol]
            unsubscribe_symbols = [symbol for symbol in std_symbols if symbol not in self._quotes]
            quotes: List[Quote] = self.api.get_quote_list(symbols=unsubscribe_symbols)
            for quote in quotes:
                self._quotes[quote.instrument_id] = quote       
            logger.info(f"订阅行情: {unsubscribe_symbols}")
            
            return True
        except Exception as e:
            logger.error(f"订阅行情失败: {e}")
            return False
    
    
    
    
    # ==================== 交易接口 ====================
    
    def send_order(self, req: OrderRequest) -> Optional[str]:
        """下单"""
        try:
            if not self.connected:
                logger.error("TqSdk未连接")
                return None
            
            formatted_symbol = self._format_symbol(req.symbol)
            if not formatted_symbol:
                logger.error(f"无效的合约代码: {req.symbol}")
                return None
            
            # 获取行情信息(市价单使用对手价)
            price = req.price
            if price is None:
                quote = self._quotes.get(formatted_symbol)
                if not quote:
                    logger.error(f"未获取到行情信息: {formatted_symbol}")
                    return None
                
                # 使用对手价
                if req.direction == Direction.BUY:
                    price = quote.ask_price_1
                else:
                    price = quote.bid_price_1
            
            # 调用TqSdk下单
            order = self.api.insert_order(
                symbol=formatted_symbol,
                direction=req.direction.value,
                offset=req.offset.value,
                volume=req.volume,
                limit_price=price if price else 0
            )
            
            order_id = order.get("order_id")
            logger.info(f"下单成功: {req.symbol} {req.direction.value} {req.offset.value} {req.volume}手 @{price}, order_id: {order_id}")
            
            # 更新缓存
            self._tq_orders[order_id] = order
            self._orders[order_id] = self._convert_order(order, formatted_symbol)
            self._emit_order(self._orders[order_id])
            
            return order_id
        except Exception as e:
            logger.error(f"下单失败: {e}", exc_info=True)
            return None
    
    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单"""
        try:
            if not self.connected:
                return False
            
            order = self._tq_orders.get(req.order_id)
            if not order:
                logger.error(f"订单不存在: {req.order_id}")
                return False
            
            self.api.cancel_order(order)
            logger.info(f"撤单成功: {req.order_id}")
            return True
        except Exception as e:
            logger.error(f"撤单失败: {e}", exc_info=True)
            return False
    
    # ==================== 查询接口 ====================
    
    def query_account(self) -> Optional[AccountData]:
        """查询账户"""
        try:
            if not self._account:
                return None              
            return self._account
        except Exception as e:
            logger.error(f"查询账户失败: {e}")
            return None

    def query_position(self) -> dict[str, PositionData]:
        """查询持仓"""
        try:
            result = {}
            for symbol, positions_list in self._positions.items():
                for position in positions_list:
                    key = f"{symbol}_{position.direction}"
                    result[key] = position
            return result
        except Exception as e:
            logger.error(f"查询持仓失败: {e}")
            return {}
    
    def query_orders(self) -> dict[str, OrderData]:
        """查询活动订单"""
        try:
            return self._orders
        except Exception as e:
            logger.error(f"查询订单失败: {e}")
            return {}

    def query_trades(self) -> dict[str, TradeData]:
        """查询今日成交"""
        try:
            return self._trades
        except Exception as e:
            logger.error(f"查询成交失败: {e}")
            return {}
    
    def query_contracts(self) -> Dict[str, ContractData]:
        """查询合约"""
        try:
            if not self.connected or not self.api:
                return {}
            
            if not self._contracts:
                quotes = self.api.query_quotes(ins_class=["FUTURE"], expired=False)
                for symbol in quotes:
                    self._contracts[symbol] = ContractData(
                        symbol=symbol.split(".")[1] if "." in symbol else symbol,
                        exchange=self._parse_exchange(symbol),
                        name=symbol,
                        product_type=ProductType.FUTURES,
                    )
            
            return self._contracts
        except Exception as e:
            logger.error(f"查询合约失败: {e}")
            return {}
    
    # ==================== 兼容方法(供外部直接调用)====================
    
    def get_account(self) -> Optional[AccountData]:
        """获取账户数据(兼容)"""
        return self._account
    
    def get_positions(self) -> Dict[str, Any]:
        """获取持仓数据(兼容,返回原始格式)"""
        try:
            if not self.connected or not self._tq_positions:
                return {}

            if self.api.is_changing(self._tq_positions):
                self._tq_positions = self.api.get_position()
                self._update_positions_cache()

            # 返回原始tqsdk格式(兼容性)
            return self._tq_positions
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return {}

    def get_orders(self) -> Dict[str, Any]:
        """获取订单数据(兼容,返回原始格式)"""
        try:
            if not self.connected or not self._tq_orders:
                return {}

            if self.api.is_changing(self._tq_orders):
                self._tq_orders = self.api.get_order()
                self._update_orders_cache()

            return self._tq_orders
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return {}

    def get_trades(self) -> Dict[str, Any]:
        """获取成交数据(兼容,返回原始格式)"""
        try:
            if not self.connected or not self._tq_trades:
                return {}

            if self.api.is_changing(self._tq_trades):
                self._tq_trades = self.api.get_trade()
                self._update_trades_cache()

            return self._tq_trades
        except Exception as e:
            logger.error(f"获取成交失败: {e}")
            return {}
    
    def get_quotes(self) -> Dict[str, Any]:
        """获取行情数据(兼容,返回原始格式)"""
        try:
            return self._tq_quotes
        except Exception as e:
            logger.error(f"获取行情失败: {e}")
            return {}
    
    def wait_update(self, timeout: int = 3) -> bool:
        """
        等待数据更新(兼容方法)

        Args:
            timeout: 超时时间(秒)

        Returns:
            bool: 是否有数据更新
        """
        try:
            if not self.connected or not self.api:
                return False

            has_data = self.api.wait_update(time.time()+timeout)

            if has_data:
                if self.api.is_changing(self._tq_account):
                    self._tq_account = self.api.get_account()
                    self._account = self._convert_account(self._tq_account)
                    self._emit_account(self._account)

                if self.api.is_changing(self._tq_positions):
                    self._tq_positions = self.api.get_position()
                    self._update_positions_cache()
                    for positions_list in self._positions.values():
                        for position in positions_list:
                            self._emit_position(position)

                if self.api.is_changing(self._tq_quotes):
                    self._tq_quotes = self.api.get_quote()
                    self._update_quotes_cache()
                    for quote in self._quotes.values():
                        self._emit_tick(quote)

                if self.api.is_changing(self._tq_orders):
                    self._tq_orders = self.api.get_order()
                    self._update_orders_cache()
                    for order in self._orders.values():
                        self._emit_order(order)

                if self.api.is_changing(self._tq_trades):
                    self._tq_trades = self.api.get_trade()
                    self._update_trades_cache()
                    for trade in self._trades.values():
                        self._emit_trade(trade)

            return has_data
        except Exception as e:
            logger.exception(f"等待更新失败: {e}")
            return False
    
    # ==================== 数据转换 ====================

    def _update_positions_cache(self):
        for symbol, pos in self._tq_positions.items():
            positions_list = self._convert_position(pos, symbol)
            self._positions[symbol] = positions_list

    def _update_orders_cache(self):
        for order_id, order in self._tq_orders.items():
            if order_id not in self._orders or self.api.is_changing(order):
                self._orders[order_id] = self._convert_order(order)

    def _update_trades_cache(self):
        for trade_id, trade in self._tq_trades.items():
            if trade_id not in self._trades or self.api.is_changing(trade):
                self._trades[trade_id] = self._convert_trade(trade)

    def _update_quotes_cache(self):
        for symbol, quote in self._tq_quotes.items():
            if symbol not in self._quotes or self.api.is_changing(quote):
                self._quotes[symbol] = self._convert_tick(quote, symbol)

    def _convert_and_cache_data(self):
        """转换所有数据并缓存"""
        try:
            # 转换账户
            if self._tq_account:
                self._account = self._convert_account(self._tq_account)
            
            # 转换持仓
            self._positions = {}
            for symbol, pos in self._tq_positions.items():
                positions_list = self._convert_position(pos, symbol)
                self._positions[symbol] = positions_list
            
            # 转换订单
            self._orders = {}
            for order_id, order in self._tq_orders.items():
                self._orders[order_id] = self._convert_order(order)
            
            # 转换成交
            self._trades = {}
            for trade_id, trade in self._tq_trades.items():
                self._trades[trade_id] = self._convert_trade(trade)
        except Exception as e:
            logger.error(f"数据转换失败: {e}", exc_info=True)
    
    def _convert_account(self, account: Account) -> AccountData:
        """转换账户数据"""
        return AccountData(
            account_id=self.account_id,
            balance=float(account.get("balance", 0)),
            available=float(account.get("available", 0)),
            frozen=float(account.get("frozen", 0)),
            margin=float(account.get("margin", 0)),
            pre_balance=float(account.get("pre_balance", 0)),
            hold_profit=float(account.get("float_profit", 0)),
            close_profit=float(account.get("close_profit", 0)),
            risk_ratio=float(account.get("risk_ratio", 0)),
            update_time=datetime.now()
        )
    
    def _convert_position(self, pos: Position, symbol: str) -> List[PositionData]:
        """转换持仓数据(支持多空)"""
        result = []
        exchange_id = symbol.split(".")[0] if "." in symbol else ""
        instrument_id = symbol.split(".")[1] if "." in symbol else symbol
        
        # 分离长短仓
        if pos.get("pos_long", 0) > 0:
            result.append(PositionData(
                symbol=instrument_id,
                exchange=self._parse_exchange(exchange_id),
                direction="LONG",
                volume=int(pos.get("pos_long", 0)),
                yd_volume=int(pos.get("pos_long_his", 0)),
                td_volume=int(pos.get("pos_long_today", 0)),
                avg_price=pos.get("open_price_long", 0),
                hold_profit=pos.get("float_profit_long", 0),
                margin=pos.get("margin_long", 0)
            ))
        
        if pos.get("pos_short", 0) > 0:
            result.append(PositionData(
                symbol=instrument_id,
                exchange=self._parse_exchange(exchange_id),
                direction="SHORT",
                volume=int(pos.get("pos_short", 0)),
                yd_volume=int(pos.get("pos_short_his", 0)),
                td_volume=int(pos.get("pos_short_today", 0)),
                avg_price=pos.get("open_price_short", 0),
                hold_profit=pos.get("float_profit_short", 0),
                margin=pos.get("margin_short", 0)
            ))
        
        return result
    
    def _convert_order(self, order: Order, symbol: Optional[str] = None) -> OrderData:
        """转换订单数据"""
        if not symbol:
            order_id = order.get("order_id", "")
            if "." in order_id:
                symbol = ".".join(order_id.split(".")[1:-1])  # 去除订单后缀
        
        exchange_id = symbol.split(".")[0] if "." in symbol else ""
        instrument_id = symbol.split(".")[1] if "." in symbol else symbol
        
        return OrderData(
            order_id=order.get("order_id", ""),
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            direction=Direction(order.get("direction", "BUY")),
            offset=Offset(order.get("offset", "OPEN")),
            volume=int(order.get("volume_orign", 0)),
            traded=int(order.get("volume_orign", 0)) - int(order.get("volume_left", 0)),
            price=order.get("limit_price"),
            price_type=OrderType.LIMIT if order.get("limit_price") else OrderType.MARKET,
            status=self._convert_status(order.get("status")),
            status_msg=order.get("last_msg", ""),
            gateway_order_id=order.get("exchange_order_id", ""),
            insert_time=datetime.fromtimestamp(order.get("insert_date_time", 0) / 1e9) if order.get("insert_date_time") else None,
            update_time=datetime.now()
        )
    
    def _convert_trade(self, trade: Trade) -> TradeData:
        """转换成交数据"""
        order_id = trade.get("order_id", "")
        exchange_id = trade.get("exchange_id", "")
        instrument_id = trade.get("instrument_id", "")
        
        return TradeData(
            trade_id=trade.get("trade_id", ""),
            order_id=order_id,
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            direction=Direction(trade.get("direction", "BUY")),
            offset=Offset(trade.get("offset", "OPEN")),
            price=float(trade.get("price", 0)),
            volume=int(trade.get("volume", 0)),
            trade_time=datetime.fromtimestamp(trade.get("trade_date_time", 0) / 1e9) if trade.get("trade_date_time") else None
        )
    
    def _convert_tick(self, quote: Quote, symbol: str) -> TickData:
        """转换tick数据"""
        exchange_id = symbol.split(".")[0] if "." in symbol else ""
        instrument_id = symbol.split(".")[1] if "." in symbol else symbol
        try:
            datetime_obj = int(float(str(quote.get("datetime", 0)).strip()))
        except (ValueError, TypeError):
            datetime_obj = 0

        return TickData(
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            datetime=datetime.fromtimestamp(datetime_obj / 1e9) if datetime_obj else datetime.now(),
            last_price=float(quote.get("last_price", 0)),
            volume=float(quote.get("volume", 0)),
            turnover=float(quote.get("turnover", 0)),
            open_interest=float(quote.get("open_interest", 0)),
            bid_price_1=float(quote.get("bid_price1", 0)),
            ask_price_1=float(quote.get("ask_price1", 0)),
            bid_volume_1=float(quote.get("bid_volume1", 0)),
            ask_volume_1=float(quote.get("ask_volume1", 0)),
            open_price=float(quote.get("open", 0)),
            high_price=float(quote.get("highest", 0)),
            low_price=float(quote.get("lowest", 0)),
            pre_close=float(quote.get("pre_open_interest", 0)),
            limit_up=float(quote.get("upper_limit", 0)),
            limit_down=float(quote.get("lower_limit", 0))
        )
    
    # ==================== 辅助方法 ====================
    
    def _format_symbol(self, symbol: str) -> Optional[str]:
        """格式化合约代码"""
        if not symbol:
            return None
        upper_symbol = symbol.upper()
        for part in upper_symbol.rsplit("."):
            if part in self._upper_symbols:
                return self._upper_symbols[part]
        logger.warning(f"未找到匹配的合约符号: {symbol}")      
        return None
    
    def _parse_exchange(self, exchange_code: str) -> Exchange:
        """解析交易所代码"""
        return exchange_map.get(exchange_code.upper(), Exchange.NONE)
    
    def _convert_status(self, status: str) -> Status:
        """转换订单状态"""
        status_map = {
            "ALIVE": Status.NOTTRADED,
            "FINISHED": Status.ALLTRADED,
            "CANCELED": Status.CANCELLED
        }
        return status_map.get(status, Status.SUBMITTING)
