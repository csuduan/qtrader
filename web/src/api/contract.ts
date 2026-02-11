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
  }
}
