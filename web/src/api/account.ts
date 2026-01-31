import api from './request'
import type { Account, TraderStatus } from '@/types'

/**
 * 账户相关 API
 */
export const accountApi = {
  /**
   * 获取账户信息
   */
  getAccount: async (): Promise<Account> => {
    return api.get<Account>('/account')
  },

  /**
   * 获取所有账户信息
   */
  getAllAccounts: async (): Promise<Account[]> => {
    return api.get<Account[]>('/account/all')
  },

  /**
   * 获取所有Trader状态
   */
  getTradersStatus: async (): Promise<TraderStatus[]> => {
    return api.get<TraderStatus[]>('/account/traders/status')
  },

  /**
   * 启动账户Trader
   */
  startTrader: async (accountId: string): Promise<{ running: boolean }> => {
    return api.post<{ running: boolean }>(`/account/${accountId}/start`)
  },

  /**
   * 停止账户Trader
   */
  stopTrader: async (accountId: string): Promise<{ running: boolean }> => {
    return api.post<{ running: boolean }>(`/account/${accountId}/stop`)
  },

  /**
   * 连接账户网关
   */
  connectGateway: async (accountId: string): Promise<{ connected: boolean }> => {
    return api.post<{ connected: boolean }>(`/account/${accountId}/connect`)
  },

  /**
   * 断开账户网关
   */
  disconnectGateway: async (accountId: string): Promise<{ connected: boolean }> => {
    return api.post<{ connected: boolean }>(`/account/${accountId}/disconnect`)
  },

  /**
   * 暂停账户交易
   */
  pauseTrading: async (accountId: string): Promise<{ paused: boolean }> => {
    return api.post<{ paused: boolean }>(`/account/${accountId}/pause`)
  },

  /**
   * 恢复账户交易
   */
  resumeTrading: async (accountId: string): Promise<{ paused: boolean }> => {
    return api.post<{ paused: boolean }>(`/account/${accountId}/resume`)
  }
}
