/**
 * API 数据类型定义
 */

/** API 统一响应格式 */
export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

/** 账户信息 */
export interface Account {
  id: number
  account_id: string
  broker_name: string | null
  currency: string
  balance: number
  available: number
  margin: number
  float_profit: number
  position_profit: number
  close_profit: number
  risk_ratio: number
  updated_at: string
  user_id?: string | null
}

/** 持仓信息 */
export interface Position {
  id: number
  account_id: string
  exchange_id: string
  instrument_id: string
  pos_long: number
  pos_short: number
  open_price_long: number
  open_price_short: number
  float_profit: number
  margin: number
  updated_at: string
}

/** 成交记录 */
export interface Trade {
  id: number
  account_id: string
  trade_id: string
  order_id: string | null
  exchange_id: string
  instrument_id: string
  direction: string
  offset: string
  price: number
  volume: number
  trade_date_time: number
  created_at: string
}

/** 委托单 */
export interface Order {
  id: number
  account_id: string
  order_id: string
  exchange_order_id: string | null
  symbol: string
  direction: string
  offset: string
  volume_orign: number
  volume_left: number
  limit_price: number | null
  price_type: string
  status: string
  insert_date_time: number
  last_msg: string | null
  created_at: string
  updated_at: string
}

/** 系统状态 */
export interface SystemStatus {
  connected: boolean
  paused: boolean
  account_id: string
  daily_orders: number
  daily_cancels: number
}

/** 定时任务 */
export interface Job {
  job_id: string
  job_name: string
  job_group: string
  job_description: string | null
  cron_expression: string
  last_trigger_time: string | null
  next_trigger_time: string | null
  enabled: boolean
  created_at: string
  updated_at: string
}

/** 手动报单请求 */
export interface ManualOrderRequest {
  symbol: string
  direction: 'BUY' | 'SELL'
  offset: 'OPEN' | 'CLOSE' | 'CLOSETODAY'
  volume: number
  price: number | null
}

/** 换仓指令 */
export interface RotationInstruction {
  id: number
  account_id: string
  strategy_id: string
  symbol: string
  exchange_id: string
  offset: string
  direction: string
  volume: number
  filled_volume: number
  price: number
  order_time: string | null
  trading_date: string | null
  enabled: boolean
  status: string
  attempt_count: number
  remaining_attempts: number
  remaining_volume: number
  current_order_id: string | null
  last_attempt_time: string | null
  error_message: string | null
  source: string | null
  is_deleted: boolean
  created_at: string
  updated_at: string
}

/** WebSocket 消息类型 */
export type WSMessageType =
  | 'connected'
  | 'account_update'
  | 'position_update'
  | 'trade_update'
  | 'order_update'
  | 'tick_update'
  | 'quote_update'
  | 'system_status'
  | 'alarm_update'

/** WebSocket 消息 */
export interface WSMessage<T = any> {
  type: WSMessageType
  data: T
  timestamp: string
}

/** 行情数据 */
export interface Quote {
  symbol: string
  last_price: number | null
  bid_price1: number | null
  ask_price1: number | null
  volume: number
  datetime: string
}

/** 风控状态 */
export interface RiskControlStatus {
  daily_order_count: number
  daily_cancel_count: number
  max_daily_orders: number
  max_daily_cancels: number
  max_order_volume: number
  max_split_volume: number
  order_timeout: number
  remaining_orders: number
  remaining_cancels: number
}

/** 告警信息 */
export interface Alarm {
  id: number
  account_id: string
  alarm_date: string
  alarm_time: string
  source: string
  title: string
  detail: string | null
  status: string
  created_at: string
}

/** 告警统计 */
export interface AlarmStats {
  today_total: number
  unconfirmed: number
  last_hour: number
  last_five_minutes: number
}

/** 告警状态 */
export type AlarmStatus = 'UNCONFIRMED' | 'CONFIRMED'

/** ==================== 新增：适配器与策略系统类型 ==================== */

/** 买卖方向 */
export type Direction = 'BUY' | 'SELL'

/** 开平类型 */
export type Offset = 'OPEN' | 'CLOSE' | 'CLOSETODAY' | 'CLOSEYESTERDAY'

/** 订单状态 */
export type OrderStatus = 'SUBMITTING' | 'NOTTRADED' | 'PARTTRADED' | 'ALLTRADED' | 'CANCELLED' | 'REJECTED'

/** 订单类型 */
export type OrderType = 'LIMIT' | 'MARKET' | 'FOK' | 'FAK'

/** 交易所 */
export type Exchange = 'CFFEX' | 'SHFE' | 'CZCE' | 'DCE' | 'INE' | 'GFEX' | 'SSE' | 'SZSE' | 'LOCAL' | ''

/** 产品类型 */
export type ProductType = 'FUTURES' | 'OPTION' | 'SPOT' | 'INDEX' | 'ETF'

/** K线周期 */
export type Interval = 'tick' | '1m' | '1h' | 'd' | 'w'

/** 策略类型 */
export type StrategyType = 'tick' | 'bar' | 'both'

/** 统一Tick数据 */
export interface TickData {
  symbol: string
  exchange: Exchange
  datetime: string
  last_price: number
  volume?: number
  turnover?: number
  open_interest?: number
  bid_price1?: number
  bid_volume1?: number
  ask_price1?: number
  ask_volume1?: number
  open_price?: number
  high_price?: number
  low_price?: number
  pre_close?: number
  limit_up?: number
  limit_down?: number
  extras?: Record<string, any>
}

/** 统一Bar数据 */
export interface BarData {
  symbol: string
  exchange: Exchange
  interval: Interval
  datetime: string
  open_price: number
  high_price: number
  low_price: number
  close_price: number
  volume?: number
  turnover?: number
  open_interest?: number
  extras?: Record<string, any>
}

/** 统一订单数据 */
export interface OrderData {
  order_id: string
  symbol: string
  exchange: Exchange
  direction: Direction
  offset: Offset
  volume: number
  traded: number
  price?: number
  price_type: OrderType
  status: OrderStatus
  status_msg: string
  gateway_order_id?: string
  trading_day?: string
  insert_time?: string
  update_time?: string
  extras?: Record<string, any>
}

/** 统一成交数据 */
export interface TradeData {
  trade_id: string
  order_id: string
  symbol: string
  exchange: Exchange
  direction: Direction
  offset: Offset
  price: number
  volume: number
  trading_day?: string
  trade_time?: string
  commission?: number
  extras?: Record<string, any>
}

/** 统一持仓数据 */
export interface PositionData {
  symbol: string
  exchange: Exchange
  direction: 'LONG' | 'SHORT' | 'NET'
  volume: number
  yd_volume?: number
  td_volume?: number
  frozen?: number
  available?: number
  avg_price?: number
  hold_cost?: number
  hold_profit?: number
  close_profit?: number
  margin?: number
  extras?: Record<string, any>
}

/** 统一账户数据 */
export interface AccountData {
  account_id: string
  balance: number
  available: number
  frozen?: number
  margin?: number
  pre_balance?: number
  hold_profit?: number
  close_profit?: number
  risk_ratio?: number
  update_time?: string
  extras?: Record<string, any>
}

/** 统一合约数据 */
export interface ContractData {
  symbol: string
  exchange: Exchange
  name: string
  product_type: ProductType
  multiple?: number
  pricetick?: number
  min_volume?: number
  option_strike?: number
  option_underlying?: string
  option_type?: string
  extras?: Record<string, any>
}

/** 策略配置 */
export interface StrategyConfig {
  enabled: boolean
  strategy_type: StrategyType
  symbol: string
  exchange: string
  volume_per_trade: number
  max_position: number
  take_profit_pct?: number
  stop_loss_pct?: number
  fee_rate?: number
  trade_start_time?: string
  trade_end_time?: string
  force_exit_time?: string
  one_trade_per_day?: boolean
  params_file?: string
  params?: Record<string, any>
}

/** 策略状态 */
export interface StrategyRes {
  strategy_id: string
  active: boolean
  config: StrategyConfig
}

/** 兼容旧名称 */
export type StrategyStatus = StrategyRes

/** 策略事件类型 */
export type StrategyEventType = 'strategy_status' | 'strategy_signal'

/** 策略信号 */
export interface StrategySignal {
  strategy_id: string
  symbol: string
  action: 'BUY' | 'SELL' | 'CLOSE'
  price?: number
  volume?: number
  reason?: string
  timestamp?: string
}
