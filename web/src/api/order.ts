import api from './request'
import type { Order, ManualOrderRequest } from '@/types'

/**
 * 委托单 API
 */
export const orderApi = {
  /**
   * 获取委托单列表
   */
  getOrders: async (status?: string, accountId?: string): Promise<Order[]> => {
    const params: any = {}
    if (status) params.status = status
    if (accountId) params.account_id = accountId
    return api.get<Order[]>('/order', { params })
  },

  /**
   * 获取指定委托单详情
   */
  getOrderById: async (orderId: string, accountId?: string): Promise<Order> => {
    return api.get<Order>(`/order/${orderId}`, accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 手动报单
   */
  createOrder: async (order: ManualOrderRequest & { accountId?: string }): Promise<{ order_id: string }> => {
    return api.post<{ order_id: string }>('/order', order)
  },

  /**
   * 撤销委托单
   */
  cancelOrder: async (orderId: string, accountId?: string): Promise<{ order_id: string }> => {
    return api.delete<{ order_id: string }>(`/order/${orderId}`, accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 批量撤销委托单
   */
  cancelBatchOrders: async (orderIds: string[], accountId?: string): Promise<{ success_count: number; total: number; failed_orders: string[] }> => {
    return api.post<{ success_count: number; total: number; failed_orders: string[] }>('/order/cancel-batch', {
      order_ids: orderIds,
      account_id: accountId
    })
  }
}
