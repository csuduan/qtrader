import api from './request'
import type { ResourceSnapshot } from '@/types'

/**
 * 资源监控 API
 */
export const resourceApi = {
  /**
   * 获取当前服务器资源快照
   */
  getResourceCurrent: async (): Promise<ResourceSnapshot> => {
    return api.get<ResourceSnapshot>('/resource/current')
  }
}
