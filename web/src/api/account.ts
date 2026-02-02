import api from './request'
import type { Account } from '@/types'

/**
 * 账户相关 API
 */
export const accountApi = {
  /**
   * 获取账户信息
   */
  getAccount: async (): Promise<Account> => {
    return await api.get<Account>('/account') as unknown as Account
  },

  /**
   * 获取所有账户信息
   */
  getAllAccounts: async (): Promise<Account[]> => {
    return await api.get<Account[]>('/account/all') as unknown as Account[]
  }
}
