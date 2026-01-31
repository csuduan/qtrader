import api from './request'
import type { RotationInstruction } from '@/types'

/**
 * 换仓指令 API
 */
export const rotationApi = {
  /**
   * 获取换仓指令列表
   */
  getRotationInstructions: async (params?: {
    limit?: number
    offset?: number
    status?: string
    enabled?: boolean
    account_id?: string
  }): Promise<{ instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }> => {
    return await api.get<{ instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }>('/rotation', { params })
  },

  /**
   * 获取指定换仓指令
   */
  getRotationInstruction: async (id: number, accountId?: string): Promise<RotationInstruction> => {
    return await api.get<RotationInstruction>(`/rotation/${id}`, accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 创建换仓指令
   */
  createRotationInstruction: async (data: any): Promise<RotationInstruction> => {
    return await api.post<RotationInstruction>('/rotation', data)
  },

  /**
   * 更新换仓指令
   */
  updateRotationInstruction: async (id: number, data: any): Promise<RotationInstruction> => {
    return await api.put<RotationInstruction>(`/rotation/${id}`, data)
  },

  /**
   * 删除换仓指令
   */
  deleteRotationInstruction: async (id: number, accountId?: string): Promise<void> => {
    await api.delete(`/rotation/${id}`, accountId ? { params: { account_id: accountId } } : undefined)
  },

  /**
   * 执行换仓指令
   */
  executeRotationInstruction: async (id: number, accountId?: string): Promise<RotationInstruction> => {
    return await api.post<RotationInstruction>(`/rotation/${id}/execute`, { account_id: accountId })
  },

  /**
   * 清除换仓指令
   */
  clearRotationInstructions: async (status?: string, accountId?: string): Promise<void> => {
    await api.post('/rotation/clear', { status, account_id: accountId })
  },

  /**
   * 批量执行换仓指令
   */
  batchExecuteInstructions: async (ids: number[], accountId?: string): Promise<{ success: number; failed: number; total: number }> => {
    return await api.post<{ success: number; failed: number; total: number }>('/rotation/batch/execute', { ids, account_id: accountId })
  },

  /**
   * 批量删除换仓指令
   */
  batchDeleteInstructions: async (ids: number[], accountId?: string): Promise<{ deleted: number }> => {
    return await api.post<{ deleted: number }>('/rotation/batch/delete', { ids, account_id: accountId })
  },

  /**
   * 启动换仓流程
   */
  startRotation: async (accountId?: string): Promise<void> => {
    await api.post('/rotation/start', { account_id: accountId })
  },

  /**
   * 一键平仓
   */
  closeAllPositions: async (accountId?: string): Promise<void> => {
    await api.post('/rotation/close-all', { account_id: accountId })
  }
}
