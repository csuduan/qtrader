import api from './request'
import type { TargetPosInstruction } from '@/types'

/** 目标仓位换仓状态 */
export interface TargetRotationStatus {
  working: boolean
  is_manual: boolean
}

/** 目标仓位换仓列表响应 */
export interface TargetInstructionResult {
  instructions: TargetPosInstruction[]
  rotation_status: TargetRotationStatus
}

/** 导入目标仓位文件响应 */
export interface TargetImportResult {
  imported: number
  skipped: boolean
  plan_id?: string
  reason?: string
  errors?: string[]
}

/**
 * 目标仓位换仓 API
 */
export const targetPositionApi = {
  /** 获取目标仓位差值指令列表 */
  getTargetInstructions: async (accountId: string): Promise<TargetInstructionResult> => {
    return await api.get<TargetInstructionResult>('/target-position', {
      params: { account_id: accountId }
    })
  },

  /** 导入目标仓位文件（CSV） */
  importTarget: async (formData: FormData, accountId: string): Promise<TargetImportResult> => {
    formData.append('account_id', accountId)
    return await api.post<TargetImportResult>('/target-position/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  /** 执行目标仓位换仓 */
  executeTarget: async (accountId: string): Promise<void> => {
    await api.post('/target-position/execute', undefined, { params: { account_id: accountId } })
  },

  /** 停止目标仓位换仓 */
  stopTarget: async (accountId: string): Promise<void> => {
    await api.post('/target-position/stop', undefined, { params: { account_id: accountId } })
  },

  /** 批量删除目标仓位指令（软删除） */
  batchDeleteInstructions: async (ids: number[], accountId: string): Promise<{ deleted: number }> => {
    return await api.post<{ deleted: number }>('/target-position/batch/delete', { ids }, {
      params: { account_id: accountId }
    })
  },

  /** 更新目标仓位指令（启用/禁用、目标手数） */
  updateInstruction: async (
    id: number,
    data: { enabled?: boolean; status?: string; target_volume?: number },
    accountId: string
  ): Promise<TargetPosInstruction> => {
    return await api.put<TargetPosInstruction>(`/target-position/${id}`, data, {
      params: { account_id: accountId }
    })
  }
}
