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
    return await api.get<SystemStatus>('/system/status') as unknown as SystemStatus
  },

  /**
   * 获取风控状态
   */
  getRiskControlStatus: async () => {
    return await api.get('/system/risk-control') as unknown as any
  },

  /**
   * 更新风控参数
   */
  updateRiskControl: async (max_daily_orders?: number, max_daily_cancels?: number, max_order_volume?: number, max_split_volume?: number, order_timeout?: number) => {
    return await api.put('/system/risk-control', {
      max_daily_orders,
      max_daily_cancels,
      max_order_volume,
      max_split_volume,
      order_timeout
    }) as unknown as any
  },

  /**
   * 连接到交易系统
   */
  connect: async (username?: string, password?: string): Promise<{ success: boolean }> => {
    return await api.post<{ success: boolean }>('/system/connect', {
      username,
      password
    }) as unknown as { success: boolean }
  },

  /**
   * 断开连接
   */
  disconnect: async (): Promise<{ success: boolean }> => {
    return await api.post<{ success: boolean }>('/system/disconnect') as unknown as { success: boolean }
  },

  /**
   * 暂停交易
   */
  pause: async (): Promise<{ success: boolean }> => {
    return await api.post<{ success: boolean }>('/system/pause') as unknown as { success: boolean }
  },

  /**
   * 恢复交易
   */
  resume: async (): Promise<{ success: boolean }> => {
    return await api.post<{ success: boolean }>('/system/resume') as unknown as { success: boolean }
  },

  /**
   * 获取定时任务列表
   */
  getScheduledTasks: async (): Promise<{ tasks: Job[], count: number }> => {
    return await api.get<{ tasks: Job[], count: number }>('/system/tasks') as unknown as { tasks: Job[], count: number }
  },

  /**
   * 立即触发定时任务
   */
  triggerJob: async (jobId: string) => {
    return await api.post<{ job_id: string, job_name: string }>(`/jobs/${jobId}/trigger`) as unknown as { job_id: string, job_name: string }
  }
}
