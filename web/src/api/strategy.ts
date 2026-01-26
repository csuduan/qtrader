/**
 * 策略相关 API
 */
import api from './request'
import type { StrategyRes } from '@/types'

export const strategyApi = {
  /**
   * 获取所有策略状态
   */
  getStrategies: async (): Promise<StrategyRes[]> => {
    return api.get<StrategyRes[]>('/strategies')
  },

  /**
   * 启动策略
   */
  startStrategy: async (strategyId: string): Promise<void> => {
    await api.post(`/strategies/${strategyId}/start`)
  },

  /**
   * 停止策略
   */
  stopStrategy: async (strategyId: string): Promise<void> => {
    await api.post(`/strategies/${strategyId}/stop`)
  },

  /**
   * 获取单个策略状态
   */
  getStrategy: async (strategyId: string): Promise<StrategyRes> => {
    return api.get<StrategyRes>(`/strategies/${strategyId}`)
  },

  /**
   * 启动所有策略
   */
  startAllStrategies: async (): Promise<void> => {
    await api.post('/strategies/start-all')
  },

  /**
   * 停止所有策略
   */
  stopAllStrategies: async (): Promise<void> => {
    await api.post('/strategies/stop-all')
  }
}
