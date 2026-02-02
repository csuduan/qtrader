import api from './request'
import type { Order, ManualOrderRequest } from '@/types'

/**
 * 委托单 API
 */
export const orderApi = {
  /**
   * 获取委托单列表
   */
  getOrders: async (status?: string): Promise<Order[]> => {
    return await api.get<Order[]>('/order', { params: { status } }) as unknown as Order[]
  },

  /**
   * 获取指定委托单详情
   */
  getOrderById: async (orderId: string): Promise<Order> => {
    return await api.get<Order>(`/order/${orderId}`) as unknown as Order
  },

  /**
   * 手动报单
   */
  createOrder: async (order: ManualOrderRequest): Promise<{ order_id: string }> => {
    return await api.post<{ order_id: string }>('/order', order) as unknown as { order_id: string }
  },

  /**
   * 撤销委托单
   */
  cancelOrder: async (orderId: string): Promise<{ order_id: string }> => {
    return await api.delete<{ order_id: string }>(`/order/${orderId}`) as unknown as { order_id: string }
  },

  /**
   * 批量撤销委托单
   */
  cancelBatchOrders: async (orderIds: string[]): Promise<{ success_count: number; total: number; failed_orders: string[] }> => {
    return await api.post<{ success_count: number; total: number; failed_orders: string[] }>('/order/cancel-batch', { order_ids: orderIds }) as unknown as { success_count: number; total: number; failed_orders: string[] }
  }
}
