import api from './request'
import type { RotationInstruction } from '@/types'

/**
 * 换仓指令 API
 */
export const rotationApi = {
  /**
   * 获取换仓指令列表
   */
  getRotationInstructions: async (accountId: string, params?: {
    limit?: number
    offset?: number
    status?: string
    enabled?: boolean
  }): Promise<{ instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }> => {
    return await api.get<{ instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }>('/rotation', { params: { ...params, account_id: accountId } })
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
  updateRotationInstruction: async (id: number, data: any, accountId: string): Promise<RotationInstruction> => {
    return await api.put<RotationInstruction>(`/rotation/${id}`, data, { params: { account_id: accountId } })
  },

  /**
   * 删除换仓指令
   */
  deleteRotationInstruction: async (id: number, accountId: string): Promise<void> => {
    await api.delete(`/rotation/${id}`, { params: { account_id: accountId } })
  },

  /**
   * 获取换仓指令详情
   */
  getRotationInstruction: async (id: number, accountId: string): Promise<RotationInstruction> => {
    return await api.get<RotationInstruction>(`/rotation/${id}`, { params: { account_id: accountId } })
  },

  /**
   * 执行换仓指令
   */
  executeRotationInstruction: async (id: number, accountId: string): Promise<RotationInstruction> => {
    return await api.post<RotationInstruction>(`/rotation/${id}/execute`, { account_id: accountId })
  },

  /**
   * 清除换仓指令
   */
  clearRotationInstructions: async (accountId: string, status?: string): Promise<void> => {
    await api.post('/rotation/clear', status ? { status } : undefined, { params: { account_id: accountId } })
  },

  /**
   * 批量执行换仓指令
   */
  batchExecuteInstructions: async (ids: number[], accountId: string): Promise<{ success: number; failed: number; total: number }> => {
    return await api.post<{ success: number; failed: number; total: number }>('/rotation/batch/execute', { ids }, { params: { account_id: accountId } })
  },

  /**
   * 批量删除换仓指令
   */
  batchDeleteInstructions: async (ids: number[], accountId: string): Promise<{ deleted: number }> => {
    return await api.post<{ deleted: number }>('/rotation/batch/delete', { ids }, { params: { account_id: accountId } })
  },

  /**
   * 启动换仓流程
   */
  startRotation: async (accountId: string): Promise<void> => {
    await api.post('/rotation/start', undefined, { params: { account_id: accountId } })
  },

  /**
   * 一键平仓
   */
  closeAllPositions: async (accountId: string): Promise<void> => {
    await api.post('/rotation/close-all', undefined, { params: { account_id: accountId } })
  },

  /**
   * 导入换仓指令
   */
  importRotation: async (formData: FormData, accountId: string): Promise<{ imported: number; failed: number; errors?: any[] }> => {
    formData.append('account_id', accountId)
    return await api.post('/rotation/import', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  }
}
