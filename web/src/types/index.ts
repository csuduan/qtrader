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
  account_id: string
  name?: string | null
  broker_type?: string | null
  broker_name?: string | null
  currency?: string
  balance: number
  pre_balance?: number
  static_balance?: number
  available: number
  margin: number
  position_profit?: number
  close_profit?: number
  today_profit?: number
  risk_ratio?: number
  updated_at: string
  user_id?: string | null
  status?: 'stopped' | 'connecting' | 'connected'
  md_connected?: boolean
  td_connected?: boolean
  trade_paused?: boolean
  risk_status?: RiskControlStatus
}

/** 持仓信息 */
export interface Position {
  id: number
  account_id: string
  exchange_id?: string | null
  symbol?: string | null
  pos_long: number
  pos_short: number
  pos_long_yd?: number | null
  pos_short_yd?: number | null
  pos_long_td?: number | null
  pos_short_td?: number | null
  hold_price_long?: number | null
  hold_price_short?: number | null
  hold_profit_long?: number | null
  hold_profit_short?: number | null
  close_profit_long?: number | null
  close_profit_short?: number | null
  margin_long?: number | null
  margin_short?: number | null
  updated_at?: string | null
}

/** 成交记录 */
export interface Trade {
  id: number
  account_id: string
  trade_id: string
  order_id?: string | null
  symbol: string
  direction: string
  offset: string
  price: number
  volume: number
  trade_date_time: string  // ISO 字符串（后端由 datetime 转换）
  order_price?: number | null  // 报单价格（用于计算滑点）
  created_at: string
}

/** 委托单 */
export interface Order {
  id: number
  account_id: string
  order_id: string
  exchange_order_id?: string | null
  symbol: string
  direction: string
  offset: string
  volume_orign: number
  volume_left: number
  limit_price?: number | null
  price_type: string
  status: string
  insert_date_time: string  // ISO 字符串
  last_msg?: string | null
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
  account_id: string
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
  pending_volume: number
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

/** 目标仓位比对行（目标持仓 vs 当前持仓） */
export interface TargetPositionCompare {
  account_id: string
  symbol: string
  side: string // LONG / SHORT
  strategy_id: string | null
  target_volume: number | null // 无目标仓位时为 null
  current_volume: number
  deviation: number | null // 无目标仓位时为 null
  direction: string | null // 无目标仓位时为 null
  offset: string | null // 无目标仓位时为 null
  volume: number | null // 无目标仓位时为 null
  source: string | null
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
  | 'alarm_update'
  | 'quote_batch_update'

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

/** 资源监控单个采样点 */
export interface ResourcePoint {
  timestamp: string
  cpu_percent: number
  memory_percent: number
  memory_used_gb: number
  memory_total_gb: number
  disk_percent: number
  disk_used_gb: number
  disk_total_gb: number
}

/** 服务器资源实时快照 */
export interface ResourceSnapshot {
  timestamp: string
  cpu_percent: number
  memory_percent: number
  memory_used_gb: number
  memory_total_gb: number
  disk_percent: number
  disk_used_gb: number
  disk_total_gb: number
  process_count: number
  boot_time: string
}

/** 资源监控历史数据 */
export interface ResourceHistory {
  points: ResourcePoint[]
  interval_seconds: number
}

/** ==================== 新增：适配器与策略系统类型 ==================== */

/** 买卖方向 */
export type Direction = 'BUY' | 'SELL'

/** 开平类型 */
export type Offset = 'OPEN' | 'CLOSE' | 'CLOSETODAY' | 'CLOSEYESTERDAY'

/** 订单状态（与后端 OrderStatus 一致：PENDING 挂单中 / FINISHED 已成或已撤 / REJECTED 已拒绝；'ALIVE' 为查询过滤值） */
export type OrderStatus = 'PENDING' | 'FINISHED' | 'REJECTED' | 'ALIVE'

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
  order_price?: number | null  // 报单价格（用于计算滑点）
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

/** 参数定义 */
export interface ParamDefinition {
  key: string
  label: string
  type: 'string' | 'int' | 'float' | 'bool' | 'time'
  value: any
}

/** 策略状态 */
export interface StrategyRes {
  strategy_id: string
  active: boolean
  enabled: boolean
  inited: boolean
  // 运行时实际生效的合约代码（优先从params取，否则从config取）
  symbol: string
  config: StrategyConfig
  params?: StrategyParams
  base_params?: ParamDefinition[]
  ext_params?: ParamDefinition[]
  signal?: StrategySignalData
  // 持仓信息（区分多头和空头）
  pos_long: number  // 多头持仓量
  pos_short: number  // 空头持仓量
  pos_price: number | null  // 持仓均价
  // 多合约持仓详情
  positions?: StrategyPosition[]
  // 保留旧字段以兼容
  pos_volume?: number  // 净持仓量（pos_long - pos_short）
  trading_status?: string
  opening_paused?: boolean
  closing_paused?: boolean
}

/** 兼容旧名称 */
export type StrategyStatus = StrategyRes

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

/** Trader状态 */
export interface TraderStatus {
  account_id: string
  state: 'stopped' | 'connecting' | 'connected'
  running: boolean
  alive: boolean
  connected: boolean
  connecting: boolean
  created_process: boolean
  pid: number | null
  start_time: string | null
  last_heartbeat: string | null
  restart_count: number
  socket_path: string | null
}

/** 报单指令 */
export interface OrderCmd {
  cmd_id: string
  status: string
  symbol: string
  filled_volume: number
  volume: number
  direction?: 'BUY' | 'SELL' | null
  offset?: 'OPEN' | 'CLOSE' | 'CLOSETODAY' | null
  limit_price?: number | null
  source?: string | null
  started_at?: string | null
  finished_at?: string | null
  total_orders?: number
  finish_reason?: string | null
  created_at: string
  updated_at: string
}

/** 报单指令响应（用于前端显示） */
export type OrderCmdRes = OrderCmd

/** 合约信息 */
export interface ContractInfo {
  symbol: string
  exchange_id: string
  name: string
  product_type: string
  volume_multiple: number
  price_tick: number
  min_volume: number
  option_strike: number | null
  option_underlying: string | null
  option_type: string | null
  is_main: boolean
  update_date: string
  updated_at: string | null
}

/** 交易所信息 */
export interface ExchangeInfo {
  exchange_id: string
  contract_count: number
}

/** 策略操作状态 */
export interface StrategyOperationState {
  enabled: boolean
  active: boolean
  opening_paused: boolean
  closing_paused: boolean
}

/** 策略报单指令过滤器 */
export interface StrategyOrderCmdFilter {
  status?: 'active' | 'finished' | 'all'
}

/** 策略参数 */
export interface StrategyParams {
  symbol: string
  bar?: string
  volume_per_trade: number
  slippage?: number
  max_position: number
  take_profit_pct: number
  stop_loss_pct: number
  external_signal?: boolean
  overnight?: boolean
  force_exit_time?: string
  // RSI 策略扩展参数
  rsi_n?: number
  rsi_period?: number
  short_k?: number
  short_kline_period?: number
  long_k?: number
  long_kline_period?: number
  long_threshold?: number
  rsi_long_threshold?: number
  short_threshold?: number
  rsi_short_threshold?: number
  dir_thr?: number
  use_signal?: boolean
  one_trade_per_day?: boolean
  fee_rate?: number
}

/** 策略信号数据 */
export interface StrategySignalData {
  side: number // 1多头, -1空头, 0无信号
  entry_price: number
  entry_time: string | null
  entry_volume: number
  exit_price: number
  exit_time: string | null
  exit_reason: string
  entry_order_id: string | null
  exit_order_id: string | null
  pos_volume: number
  pos_price: number | null
  started_at?: string | null
  created_at: string
  updated_at: string
}

/** 策略持仓 */
export interface StrategyPosition {
  symbol: string
  pos_long: number
  pos_long_td: number
  pos_long_yd: number
  pos_short: number
  pos_short_td: number
  pos_short_yd: number
  pos_net: number
  hold_price_long: number
  hold_price_short: number
  position_profit: number
  close_profit: number
}

/** 更新策略持仓请求 */
export interface UpdateStrategyPositionRequest {
  symbol: string
  pos_long_td: number
  pos_long_yd: number
  pos_short_td: number
  pos_short_yd: number
  hold_price_long: number
  hold_price_short: number
  close_profit_long: number
  close_profit_short: number
}
