import api from './request'
import type { Quote } from '@/types'

/**
 * 行情 API
 */
export const quoteApi = {
  /**
   * 获取所有已订阅的行情列表
   */
  getSubscribedQuotes: async (): Promise<Quote[]> => {
    return await api.get<Quote[]>('/quote') as unknown as Quote[]
  },

  /**
   * 订阅合约行情
   */
  subscribeSymbol: async (symbol: string): Promise<{ symbol: string }> => {
    return await api.post<{ symbol: string }>('/quote/subscribe', { symbol }) as unknown as { symbol: string }
  },

  /**
   * 取消订阅合约行情
   */
  unsubscribeSymbol: async (symbol: string): Promise<{ symbol: string }> => {
    return await api.post<{ symbol: string }>('/quote/unsubscribe', { symbol }) as unknown as { symbol: string }
  },

  /**
   * 检查合约是否已订阅
   */
  checkSubscription: async (symbol: string): Promise<{ symbol: string; subscribed: boolean }> => {
    return await api.get<{ symbol: string; subscribed: boolean }>(`/quote/check/${symbol}`) as unknown as { symbol: string; subscribed: boolean }
  }
}
