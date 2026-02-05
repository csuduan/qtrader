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
  }
}
