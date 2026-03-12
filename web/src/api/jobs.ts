import api from './request'
import type { Job } from '@/types'

/**
 * 定时任务 API
 */
export const jobsApi = {
  /**
   * 获取定时任务列表
   */
  getJobs: async (params: {
    account_id: string
    group?: string
    enabled?: boolean
  }): Promise<Job[]> => {
    return api.get<Job[]>('/jobs', { params })
  },

  /**
   * 获取指定任务
   */
  getJob: async (jobId: string, accountId: string): Promise<Job> => {
    return api.get<Job>(`/jobs/${jobId}`, { params: { account_id: accountId } })
  },

  /**
   * 切换任务启用状态
   */
  toggleJob: async (jobId: string, enabled: boolean, accountId: string): Promise<void> => {
    return api.put(`/jobs/${jobId}/toggle`, { enabled }, { params: { account_id: accountId } })
  },

  /**
   * 操作任务（暂停/恢复/触发）
   */
  operateJob: async (
    jobId: string,
    action: 'pause' | 'resume' | 'trigger',
    accountId: string
  ): Promise<void> => {
    return api.post(`/jobs/${jobId}/operate`, { action }, { params: { account_id: accountId } })
  }
}
