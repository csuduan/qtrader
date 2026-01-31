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
  },

  /**
   * 取消订阅合约行情
   */
  unsubscribeSymbol: async (symbol: string, accountId?: string): Promise<{ symbol: string }> => {
    return api.post<{ symbol: string }>('/quote/unsubscribe', { symbol, account_id: accountId })
  },

  /**
   * 检查合约是否已订阅
   */
  checkSubscription: async (symbol: string, accountId?: string): Promise<{ symbol: string; subscribed: boolean }> => {
    return api.get<{ symbol: string; subscribed: boolean }>(`/quote/check/${symbol}`, accountId ? { params: { account_id: accountId } } : undefined)
  }
}
