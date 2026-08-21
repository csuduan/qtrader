import api from './request'
import type { TargetPositionCompare } from '@/types'

/** 目标仓位比对列表响应 */
export interface TargetComparisonResult {
  trading_date: string
  comparisons: TargetPositionCompare[]
}

/** 导入目标仓位文件响应 */
export interface TargetImportResult {
  saved?: boolean
  file_name?: string
  error?: string
}

/** 导出换仓指令文件响应 */
export interface TargetExportResult {
  exported: number
  file_name: string | null
  file_path: string | null
  content_base64?: string
  encoding?: string
  error?: string
}

/** 导出目标仓位文件响应 */
export interface TargetExportPositionsResult {
  exported: number
  file_name: string | null
  file_path: string | null
  content_base64?: string
  encoding?: string
  error?: string
}

/**
 * 目标仓位比对 API
 */
export const targetPositionApi = {
  /** 获取目标仓位与当前持仓的比对结果 */
  getComparison: async (accountId: string): Promise<TargetComparisonResult> => {
    return await api.get<TargetComparisonResult>('/target-position', {
      params: { account_id: accountId }
    })
  },

  /** 导入目标仓位文件（保存到目标仓位目录，供比对扫描读取） */
  importTarget: async (formData: FormData, accountId: string): Promise<TargetImportResult> => {
    formData.append('account_id', accountId)
    return await api.post<TargetImportResult>('/target-position/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  /** 按偏差导出换仓指令文件（由指令换仓流程扫描执行） */
  exportInstructions: async (accountId: string): Promise<TargetExportResult> => {
    return await api.post<TargetExportResult>('/target-position/export', undefined, {
      params: { account_id: accountId }
    })
  },

  /** 按当前持仓导出目标仓位文件（默认导出所有持仓） */
  exportTargetPositions: async (accountId: string, strategyId: string = 'manual'): Promise<TargetExportPositionsResult> => {
    return await api.post<TargetExportPositionsResult>('/target-position/export-positions', undefined, {
      params: { account_id: accountId, strategy_id: strategyId }
    })
  },

  /** 手动更新某合约某侧的目标手数（为空表示删除目标） */
  updateTarget: async (
    accountId: string,
    symbol: string,
    side: string,
    targetVolume: number | null
  ): Promise<TargetImportResult> => {
    return await api.post<TargetImportResult>('/target-position/update', {
      symbol,
      side,
      target_volume: targetVolume
    }, {
      params: { account_id: accountId }
    })
  }
}
