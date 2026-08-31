import api from './request'

/** K线数据项 */
export interface BarItem {
  datetime: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  source: string
}

/** 数据服务状态 */
export interface BarFeedStatus {
  enabled: boolean
  connected: boolean
  subscriptions?: { symbol: string; interval: string }[]
}

/**
 * K线数据 API（数据由 Manager 数据服务统一落库）
 */
export const barsApi = {
  /**
   * 查询K线数据（bars_history + bars_today 合并去重）
   */
  getBars: async (params: {
    symbol: string
    interval?: string
    start: string
    end: string
    limit?: number
  }): Promise<BarItem[]> => {
    return api.get<BarItem[]>('/bars', { params })
  },

  /**
   * 手动同步K线数据（故障恢复）
   */
  syncBars: async (): Promise<{ message: string }> => {
    return api.post<{ message: string }>('/bars/sync')
  },

  /**
   * 查询数据服务状态
   */
  getFeedStatus: async (): Promise<BarFeedStatus> => {
    return api.get<BarFeedStatus>('/bars/feed/status')
  }
}
