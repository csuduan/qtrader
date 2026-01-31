import api from './request'
import type { SystemStatus, Job, RiskControlStatus } from '@/types'

/**
 * 系统控制 API
 */
export const systemApi = {
  /**
   * 获取系统状态
   */
  getStatus: async (accountId?: string): Promise<SystemStatus> => {
    return api.get<SystemStatus>('/system/status', { params: { account_id: accountId } })
  },

  /**
   * 获取风控状态
   */
  getRiskControlStatus: async (accountId?: string): Promise<RiskControlStatus> => {
    return api.get<RiskControlStatus>('/system/risk-control', { params: { account_id: accountId } })
  },

  /**
   * 更新风控参数
   */
  updateRiskControl: async (max_daily_orders?: number, max_daily_cancels?: number, max_order_volume?: number, max_split_volume?: number, order_timeout?: number, accountId?: string) => {
    return api.put('/system/risk-control', {
      max_daily_orders,
      max_daily_cancels,
      max_order_volume,
      max_split_volume,
      order_timeout,
      account_id: accountId
    })
  },

  /**
   * 连接到交易系统
   */
  connect: async (username?: string, password?: string, accountId?: string): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/connect', {
      username,
      password,
      account_id: accountId
    })
  },

  /**
   * 断开连接
   */
  disconnect: async (accountId?: string): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/disconnect', {
      account_id: accountId
    })
  },

  /**
   * 暂停交易
   */
  pause: async (accountId?: string): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/pause', {
      account_id: accountId
    })
  },

  /**
   * 恢复交易
   */
  resume: async (accountId?: string): Promise<{ success: boolean }> => {
    return api.post<{ success: boolean }>('/system/resume', {
      account_id: accountId
    })
  },

  /**
   * 断开网关连接
   */
  disconnectGateway: async (accountId?: string): Promise<{ gateway_connected: boolean }> => {
    return api.post<{ gateway_connected: boolean }>('/system/disconnect/gateway', {
      account_id: accountId
    })
  },

  /**
   * 启动Trader
   */
  startTrader: async (accountId?: string): Promise<{ running: boolean }> => {
    return api.post<{ running: boolean }>('/system/trader/start', {
      account_id: accountId
    })
  },

  /**
   * 停止Trader
   */
  stopTrader: async (accountId?: string): Promise<{ running: boolean }> => {
    return api.post<{ running: boolean }>('/system/trader/stop', {
      account_id: accountId
    })
  },

  /**
   * 获取Trader状态
   */
  getTraderStatus: async (accountId?: string): Promise<{ account_id: string; running: boolean; alive: boolean; created_process: boolean; pid: number | null; start_time: string | null; last_heartbeat: string; restart_count: number; socket_path: string }> => {
    return api.get('/system/trader/status', { params: { account_id: accountId } })
  },

  /**
   * 获取定时任务列表
   */
  getScheduledTasks: async (accountId?: string): Promise<{ tasks: Job[], count: number }> => {
    return api.get<{ tasks: Job[], count: number }>('/jobs', { params: { account_id: accountId } })
  },

  /**
   * 立即触发定时任务
   */
  triggerJob: async (jobId: string, accountId?: string) => {
    return api.post<{ job_id: string, job_name: string }>(`/jobs/${jobId}/trigger`, { account_id: accountId })
  }
}
