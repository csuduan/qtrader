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
  last_price: number
  bid_price1: number
  ask_price1: number
  volume: number
  open_interest: number
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
