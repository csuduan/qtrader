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
  }): Promise<{ instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }> => {
    const result = await api.get<{ instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }>('/rotation', { params })
    return result as unknown as { instructions: RotationInstruction[], rotation_status: { working: boolean, is_manual: boolean } }
  },

  /**
   * 获取指定换仓指令
   */
  getRotationInstruction: async (id: number): Promise<RotationInstruction> => {
    const result = await api.get<RotationInstruction>(`/rotation/${id}`)
    return result as unknown as RotationInstruction
  },

  /**
   * 创建换仓指令
   */
  createRotationInstruction: async (data: any): Promise<RotationInstruction> => {
    const result = await api.post<RotationInstruction>('/rotation', data)
    return result as unknown as RotationInstruction
  },

  /**
   * 更新换仓指令
   */
  updateRotationInstruction: async (id: number, data: any): Promise<RotationInstruction> => {
    const result = await api.put<RotationInstruction>(`/rotation/${id}`, data)
    return result as unknown as RotationInstruction
  },

  /**
   * 删除换仓指令
   */
  deleteRotationInstruction: async (id: number): Promise<void> => {
    await api.delete(`/rotation/${id}`)
  },

  /**
   * 执行换仓指令
   */
  executeRotationInstruction: async (id: number): Promise<RotationInstruction> => {
    const result = await api.post<RotationInstruction>(`/rotation/${id}/execute`)
    return result as unknown as RotationInstruction
  },

  /**
   * 清除换仓指令
   */
  clearRotationInstructions: async (status?: string): Promise<void> => {
    await api.post('/rotation/clear', { status })
  },

  /**
   * 批量执行换仓指令
   */
  batchExecuteInstructions: async (ids: number[]): Promise<{ success: number; failed: number; total: number }> => {
    const result = await api.post<{ success: number; failed: number; total: number }>('/rotation/batch/execute', { ids })
    return result as unknown as { success: number; failed: number; total: number }
  },

  /**
   * 批量删除换仓指令
   */
  batchDeleteInstructions: async (ids: number[]): Promise<{ deleted: number }> => {
    const result = await api.post<{ deleted: number }>('/rotation/batch/delete', { ids })
    return result as unknown as { deleted: number }
  },

  /**
   * 启动换仓流程
   */
  startRotation: async (): Promise<void> => {
    await api.post('/rotation/start')
  }
}
