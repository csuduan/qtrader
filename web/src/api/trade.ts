import api from './request'
import type { Trade } from '@/types'

/**
 * 成交记录 API
 */
export const tradeApi = {
  /**
   * 获取成交记录
   */
  getTrades: async (params?: { date?: string }): Promise<Trade[]> => {
    return await api.get<Trade[]>('/trade', { params }) as unknown as Trade[]
  },

  /**
   * 获取指定成交详情
   */
  getTradeById: async (tradeId: string): Promise<Trade> => {
    return await api.get<Trade>(`/trade/${tradeId}`) as unknown as Trade
  },

  /**
   * 获取指定委托单的成交记录
   */
  getTradesByOrder: async (orderId: string): Promise<Trade[]> => {
    return await api.get<Trade[]>(`/trade/order/${orderId}`) as unknown as Trade[]
  }
}
