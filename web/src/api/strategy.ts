/**
 * 策略相关 API
 */
import api from './request'
import type { StrategyRes, StrategyParams, StrategySignalData, OrderCmdRes, StrategyOrderCmdFilter } from '@/types'

export const strategyApi = {
  /**
   * 获取所有策略状态
   */
  getStrategies: async (accountId?: string): Promise<StrategyRes[]> => {
    return api.get<StrategyRes[]>('/strategies', accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 启动策略
   */
  startStrategy: async (strategyId: string, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/start`, null, config)
  },

  /**
   * 停止策略
   */
  stopStrategy: async (strategyId: string, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/stop`, null, config)
  },

  /**
   * 获取单个策略状态
   */
  getStrategy: async (strategyId: string, accountId?: string): Promise<StrategyRes> => {
    return api.get<StrategyRes>(`/strategies/${strategyId}`, accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 启动所有策略
   */
  startAllStrategies: async (accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post('/strategies/start-all', null, config)
  },

  /**
   * 停止所有策略
   */
  stopAllStrategies: async (accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post('/strategies/stop-all', null, config)
  },

  /**
   * 回播所有有效策略行情
   */
  replayAllStrategies: async (accountId?: string): Promise<{ replayed_count: number }> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    return api.post<{ replayed_count: number }>('/strategies/replay-all', null, config)
  },

  /**
   * 更新策略参数
   */
  updateStrategy: async (strategyId: string, params: Partial<StrategyParams>, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.patch(`/strategies/${strategyId}`, { params, restart: false }, config)
  },

  /**
   * 更新策略信号
   * 无信号时（side=0或未选择信号），body传空对象{}
   */
  updateStrategySignal: async (strategyId: string, signal: Partial<StrategySignalData>, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    // 无信号时（side=0或未定义），传空对象
    const body = signal.side ? signal : {}
    await api.post(`/strategies/${strategyId}/update-signal`, body, config)
  },

  /**
   * 更新策略持仓详情（单个合约）
   */
  updateStrategyPositionDetail: async (strategyId: string, position: {
    symbol: string
    pos_long_td: number
    pos_long_yd: number
    pos_short_td: number
    pos_short_yd: number
    hold_price_long: number
    hold_price_short: number
    close_profit_long: number
    close_profit_short: number
  }, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/update-position-detail`, position, config)
  },

  /**
   * 删除策略持仓（单个合约）
   */
  deleteStrategyPosition: async (strategyId: string, symbol: string, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/delete-position`, { symbol }, config)
  },

  /**
   * 设置策略交易状态（统一接口）
   * 支持同时设置开仓和平仓状态
   */
  setTradingStatus: async (strategyId: string, status: { opening_paused?: boolean, closing_paused?: boolean }, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/trading-status`, status, config)
  },

  /**
   * 启用策略
   */
  enableStrategy: async (strategyId: string, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/enable`, null, config)
  },

  /**
   * 禁用策略
   */
  disableStrategy: async (strategyId: string, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/disable`, null, config)
  },

  /**
   * 初始化策略
   */
  initStrategy: async (strategyId: string, accountId?: string): Promise<void> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    await api.post(`/strategies/${strategyId}/init`, null, config)
  },

  /**
   * 获取策略的报单指令历史
   */
  getStrategyOrderCmds: async (strategyId: string, filter?: StrategyOrderCmdFilter, accountId?: string): Promise<OrderCmdRes[]> => {
    const params: Record<string, string> = accountId ? { account_id: accountId } : {}
    if (filter?.status && filter.status !== 'all') {
      params.status = filter.status
    }
    return api.get<OrderCmdRes[]>(`/strategies/${strategyId}/order-cmds`, { params })
  },

  /**
   * 发送策略报单指令
   */
  sendStrategyOrderCmd: async (strategyId: string, orderCmd: {
    symbol: string
    direction: 'BUY' | 'SELL'
    offset: 'OPEN' | 'CLOSE' | 'CLOSETODAY'
    volume: number
    price: number
  }, accountId?: string): Promise<{ cmd_id: string }> => {
    const config = accountId ? { params: { account_id: accountId } } : undefined
    return api.post<{ cmd_id: string }>(`/strategies/${strategyId}/send-order-cmd`, orderCmd, config)
  }
}
