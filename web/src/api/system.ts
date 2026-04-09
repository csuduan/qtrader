import api from './request'
import type { SystemStatus, Job, RiskControlStatus } from '@/types'

/**
 * 告警指标配置
 */
export interface IndicatorConfig {
  name: string
  window: number
  threshold: number
  description: string
}

/**
 * 通知告警配置
 */
export interface NotificationConfig {
  enabled: boolean
  dnd_start?: number
  dnd_end?: number
}

/**
 * 异常告警配置
 */
export interface ExceptionConfig {
  enabled: boolean
  dnd_start?: number
  dnd_end?: number
  indicators?: IndicatorConfig[]
}

/**
 * 告警配置类型（新结构）
 */
export interface AlertConfig {
  notification: NotificationConfig
  exception: ExceptionConfig
}

/**
 * 旧版告警配置类型（已废弃）
 */
export interface LegacyAlertConfig {
  immediate: boolean
  threshold: boolean
  threshold_count: number
  threshold_window: number
  dnd_start: number
  dnd_end: number
}

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
   * 获取微信告警配置（已废弃，请使用 getAlertConfig）
   */
  getAlertWechat: async (accountId?: string): Promise<{ alert_wechat: boolean }> => {
    return api.get<{ alert_wechat: boolean }>('/system/alert-wechat', { params: { account_id: accountId } })
  },

  /**
   * 更新微信告警配置（已废弃，请使用 updateAlertConfig）
   */
  updateAlertWechat: async (alertWechat: boolean, accountId?: string) => {
    return api.put('/system/alert-wechat', {
      alert_wechat: alertWechat,
      account_id: accountId
    })
  },

  /**
   * 获取告警配置（账户级别，已废弃，请使用 getManagerAlertConfig）
   */
  getAlertConfig: async (accountId?: string): Promise<LegacyAlertConfig> => {
    return api.get<LegacyAlertConfig>('/system/alert-config', { params: { account_id: accountId } })
  },

  /**
   * 更新告警配置（账户级别，已废弃，请使用 updateManagerAlertConfig）
   */
  updateAlertConfig: async (config: Partial<LegacyAlertConfig>, accountId?: string): Promise<LegacyAlertConfig> => {
    return api.put<LegacyAlertConfig>('/system/alert-config', {
      ...config,
      account_id: accountId
    })
  },

  /**
   * 获取Manager全局告警配置（新结构：notification + exception）
   */
  getManagerAlertConfig: async (): Promise<AlertConfig> => {
    return api.get<AlertConfig>('/system/manager/alert-config')
  },

  /**
   * 更新Manager全局告警配置（新结构：notification + exception）
   */
  updateManagerAlertConfig: async (config: { notification: NotificationConfig, exception: ExceptionConfig }): Promise<AlertConfig> => {
    return api.put<AlertConfig>('/system/manager/alert-config', config)
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
  disconnectGateway: async (accountId?: string): Promise<{ md_connected: boolean; td_connected: boolean }> => {
    return api.post<{ md_connected: boolean; td_connected: boolean }>('/system/disconnect/gateway', {
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
  },

  /**
   * 获取Manager级别的定时任务列表
   */
  getManagerSchedulerJobs: async (): Promise<{ tasks: Job[], count: number }> => {
    return api.get<{ tasks: Job[], count: number }>('/system/scheduler/jobs')
  },

  /**
   * 操作Manager级别的定时任务
   */
  operateManagerSchedulerJob: async (jobId: string, action: 'pause' | 'resume' | 'trigger'): Promise<void> => {
    return api.post(`/system/scheduler/jobs/${jobId}/operate`, { action })
  },

  /**
   * 切换Manager级别定时任务的启用状态
   */
  toggleManagerSchedulerJob: async (jobId: string, enabled: boolean): Promise<void> => {
    return api.put(`/system/scheduler/jobs/${jobId}/toggle`, { enabled })
  }
}
