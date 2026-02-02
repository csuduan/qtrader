import api from './request'
import type { Job } from '@/types'

/**
 * 定时任务 API
 */
export const jobsApi = {
  /**
   * 获取定时任务列表
   */
  getJobs: async (params?: {
    group?: string
    enabled?: boolean
  }): Promise<Job[]> => {
    return await api.get<Job[]>('/jobs', { params }) as unknown as Job[]
  },

  /**
   * 获取指定任务
   */
  getJob: async (jobId: string): Promise<Job> => {
    return await api.get<Job>(`/jobs/${jobId}`) as unknown as Job
  },

  /**
   * 切换任务启用状态
   */
  toggleJob: async (jobId: string, enabled: boolean): Promise<void> => {
    await api.put(`/jobs/${jobId}/toggle`, { enabled })
  },

  /**
   * 操作任务（暂停/恢复/触发）
   */
  operateJob: async (jobId: string, action: 'pause' | 'resume' | 'trigger'): Promise<void> => {
    await api.post(`/jobs/${jobId}/operate`, { action })
  }
}
