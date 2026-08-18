import request from './request'
import type { OrderCmd } from '@/types'

export const orderCmdApi = {
  async getOrderCmdsStatus(accountId?: string, status?: 'active' | 'finished' | null): Promise<OrderCmd[]> {
    const params: any = {}
    if (accountId) {
      params.account_id = accountId
    }
    if (status !== undefined) {
      params.status = status
    }
    return request.get('/order-cmd', { params })
  },

  async sendOrderCmd(
    data: { symbol: string; direction: 'BUY' | 'SELL'; offset: string; volume: number; price: number },
    accountId?: string
  ): Promise<{ cmd_id: string }> {
    const params: any = {}
    if (accountId) {
      params.account_id = accountId
    }
    return request.post('/order-cmd', data, { params })
  },

  async cancelOrderCmd(cmdId: string, accountId?: string): Promise<void> {
    const params: any = {}
    if (accountId) {
      params.account_id = accountId
    }
    return request.post(`/order-cmd/${cmdId}/cancel`, null, { params })
  }
}
