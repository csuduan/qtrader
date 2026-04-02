import api from './request'
import type { ResourceSnapshot, ResourceHistory } from '@/types'

/**
 * 资源监控 API
 */
export const resourceApi = {
  /**
   * 获取当前服务器资源快照
   */
  getResourceCurrent: async (): Promise<ResourceSnapshot> => {
    return api.get<ResourceSnapshot>('/resource/current')
  },

  /**
   * 获取最近的服务器资源历史数据
   */
  getResourceHistory: async (points: number = 60): Promise<ResourceHistory> => {
    return api.get<ResourceHistory>('/resource/history', { params: { points } })
  }
}
