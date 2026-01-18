import api from './request'
import type { SystemStatus, Job } from '@/types'

/**
 * 系统控制 API
 */
export const systemApi = {
  /**
   * 获取系统状态
   */
  getStatus: async (): Promise<SystemStatus> => {
    return api.get<SystemStatus>('/system/status')
  },

  /**
   * 获取风控状态
   */
  getRiskControlStatus: async () => {
    return api.get('/system/risk-control')
  },

  /**
   * 更新风控参数
   */
  updateRiskControl: async (max_daily_orders?: number, max_daily_cancels?: number, max_order_volume?: number, max_split_volume?: number, order_timeout?: number) => {
    return api.put('/system/risk-control', {
      max_daily_orders,
      max_daily_cancels,
      max_order_volume,
      max_split_volume,
      order_timeout
    })
  },

  /**
   * 连接到交易系统
   */
  connect: async (username?: string, password?: string): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/connect', {
      username,
      password
    })
  },

  /**
   * 断开连接
   */
  disconnect: async (): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/disconnect')
  },

  /**
   * 暂停交易
   */
  pause: async (): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/pause')
  },

  /**
   * 恢复交易
   */
  resume: async (): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/resume')
  },

  /**
   * 获取定时任务列表
   */
  getScheduledTasks: async (): Promise<{ tasks: Job[], count: number }> => {
    return api.get<{ tasks: Job[], count: number }>('/system/tasks')
  },

  /**
   * 立即触发定时任务
   */
  triggerJob: async (jobId: string) => {
    return api.post<{ job_id: string, job_name: string }>(`/jobs/${jobId}/trigger`)
  }
}
