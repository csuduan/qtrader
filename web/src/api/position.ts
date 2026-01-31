import api from './request'
import type { Position } from '@/types'

/**
 * 持仓相关 API
 */
export const positionApi = {
  /**
   * 获取持仓列表
   */
  getPositions: async (accountId?: string): Promise<Position[]> => {
    return api.get<Position[]>('/position', accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 获取指定合约持仓
   */
  getPositionBySymbol: async (symbol: string, accountId?: string): Promise<Position[]> => {
    const params: any = { symbol }
    if (accountId) params.account_id = accountId
    return api.get<Position[]>(`/position/${symbol}`, { params })
  },

  /**
   * 平仓
   */
  closePosition: async (data: {
    symbol: string
    direction: string
    offset: string
    volume: number
    price?: number
    accountId?: string
  }): Promise<{ order_id: string }> => {
    return api.post<{ order_id: string }>('/position/close', data)
  },

  /**
   * 批量平仓
   */
  closeBatchPositions: async (positions: Array<{
    symbol: string
    direction: string
    offset: string
    volume: number
    price?: number
  }>, accountId?: string): Promise<{ success_count: number; total: number; failed_orders: any[] }> => {
    return api.post<{ success_count: number; total: number; failed_orders: any[] }>('/position/close-batch', {
      positions,
      account_id: accountId
    })
  }
}
