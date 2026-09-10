import api from './request'
import type { Quote } from '@/types'

/**
 * 行情 API
 */
export const quoteApi = {
  /**
   * 获取所有已订阅的行情列表
   */
  getSubscribedQuotes: async (accountId?: string): Promise<Quote[]> => {
    return api.get<Quote[]>('/quote', accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 订阅合约行情
   */
  subscribeSymbol: async (symbol: string, accountId?: string): Promise<{ symbol: string }> => {
    return api.post<{ symbol: string }>('/quote/subscribe', { symbol, account_id: accountId })
  }
}
