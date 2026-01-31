/**
 * 策略相关 API
 */
import api from './request'
import type { StrategyRes } from '@/types'

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
    await api.post(`/strategies/${strategyId}/start`, { account_id: accountId })
  },

  /**
   * 停止策略
   */
  stopStrategy: async (strategyId: string, accountId?: string): Promise<void> => {
    await api.post(`/strategies/${strategyId}/stop`, { account_id: accountId })
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
    await api.post('/strategies/start-all', { account_id: accountId })
  },

  /**
   * 停止所有策略
   */
  stopAllStrategies: async (accountId?: string): Promise<void> => {
    await api.post('/strategies/stop-all', { account_id: accountId })
  }
}
