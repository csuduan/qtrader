import request from './request'
import type { ContractInfo, ExchangeInfo } from '@/types'

export const contractApi = {
  getContracts(params?: {
    exchange_id?: string
    product_type?: string
    symbol_keyword?: string
  }): Promise<ContractInfo[]> {
    return request.get('/contract/list', { params })
  },

  getExchanges(): Promise<ExchangeInfo[]> {
    return request.get('/contract/exchanges')
  },

  refreshContracts(account_id?: string): Promise<{ success: boolean; results: Record<string, { success: boolean; message: string }> }> {
    return request.post('/contract/refresh', null, { params: { account_id } })
  }
}
