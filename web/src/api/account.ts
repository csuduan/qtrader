import api from './request'
import type { Account, TraderStatus } from '@/types'

/**
 * 账户相关 API
 */
export const accountApi = {
  /**
   * 获取账户信息
   */
  getAccount: async (accountId?: string): Promise<Account> => {
    return api.get<Account>('/account', { params: { account_id: accountId } })
  },

  /**
   * 获取所有账户信息
   */
  getAllAccounts: async (): Promise<Account[]> => {
    return api.get<Account[]>('/account/all')
  },

  /**
   * 获取账户ID列表
   */
  getAccountList: async (): Promise<string[]> => {
    return api.get<string[]>('/account/list')
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
   * 重启账户Trader
   */
  restartTrader: async (accountId: string): Promise<{ running: boolean }> => {
    return api.post<{ running: boolean }>(`/account/${accountId}/restart`)
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
  },

  /**
   * 手动同步账户数据（全量拉取账户+持仓+报单+成交）
   */
  syncAccount: async (accountId: string): Promise<{
    success: boolean
    positions: number
    orders: number
    trades: number
  }> => {
    return api.post(`/account/${accountId}/sync`)
  },

  /**
   * 获取可添加的账户列表（config目录中存在配置文件但未添加）
   */
  getAvailableAccounts: async (): Promise<{ accounts: string[] }> => {
    return api.get<{ accounts: string[] }>('/account/available/list')
  },

  /**
   * 添加账户
   */
  addAccount: async (accountId: string): Promise<{ account_id: string }> => {
    return api.post<{ account_id: string }>(`/account/${accountId}/add`)
  },

  /**
   * 删除账户（仅限已停止账户，从 account_ids 移除，配置文件保留）
   */
  removeAccount: async (accountId: string): Promise<{ account_id: string }> => {
    return api.post<{ account_id: string }>(`/account/${accountId}/remove`)
  }
}
