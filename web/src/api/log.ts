import api from './request'

/**
 * 日志文件信息
 */
export interface LogFile {
  name: string
  size: number
  mtime: string
}

/**
 * 日志内容响应
 */
export interface LogContent {
  lines: string[]
  offset: number
  has_more: boolean
  file_size: number
}

/**
 * 日志 API
 */
export const logApi = {
  /**
   * 获取日志内容
   * @param accountId 账户ID
   * @param filename 日志文件名（app 或 error，默认为 app）
   * @param offset 文件字节偏移量
   * @param limit 最大行数
   */
  getLog: async (
    accountId: string,
    filename: string = 'app',
    offset: number = 0,
    limit: number = 1000
  ): Promise<LogContent> => {
    return api.get<LogContent>('/log', {
      params: {
        account_id: accountId,
        filename,
        offset,
        limit,
      },
    })
  },

  /**
   * 获取日志文件列表
   * @param accountId 账户ID
   */
  getLogFiles: async (accountId: string): Promise<{ files: LogFile[] }> => {
    return api.get<{ files: LogFile[] }>('/log/files', {
      params: { account_id: accountId },
    })
  },

  /**
   * 下载完整日志文件
   * @param accountId 账户ID
   * @param filename 日志文件名
   */
  downloadLog: async (
    accountId: string,
    filename: string = 'app'
  ): Promise<{
    filename: string
    content: string
    size: number
  }> => {
    return api.get<{
      filename: string
      content: string
      size: number
    }>('/log/download', {
      params: { account_id: accountId, filename },
    })
  },
}
