import api from './request'
import type { Trade } from '@/types'

/**
 * 成交记录 API
 */
export const tradeApi = {
  /**
   * 获取成交记录
   */
  getTrades: async (params?: { date?: string; account_id?: string }): Promise<Trade[]> => {
    return api.get<Trade[]>('/trade', { params })
  },

  /**
   * 获取指定成交详情
   */
  getTradeById: async (tradeId: string, accountId?: string): Promise<Trade> => {
    return api.get<Trade>(`/trade/${tradeId}`, accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 获取指定委托单的成交记录
   */
  getTradesByOrder: async (orderId: string, accountId?: string): Promise<Trade[]> => {
    return api.get<Trade[]>(`/trade/order/${orderId}`, accountId ? { params: { account_id: accountId } } : undefined)
  }
}
