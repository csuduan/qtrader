import request from './request'
import type { Alarm, AlarmStats, AlarmStatus } from '@/types'

export const alarmApi = {
  getTodayAlarms(statusFilter?: AlarmStatus, accountId?: string): Promise<Alarm[]> {
    return request.get('/alarm/list', {
      params: {
        ...(statusFilter ? { status_filter: statusFilter } : {}),
        ...(accountId ? { account_id: accountId } : {})
      }
    })
  },

  getAlarmStats(accountId?: string): Promise<AlarmStats> {
    return request.get('/alarm/stats', {
      params: {
        ...(accountId ? { account_id: accountId } : {})
      }
    })
  },

  confirmAlarm(alarmId: number): Promise<Alarm> {
    return request.post(`/alarm/confirm/${alarmId}`)
  },

  confirmAllAlarms(accountId?: string): Promise<{ confirmed_count: number }> {
    return request.post('/alarm/confirm_all', {
      ...(accountId ? { account_id: accountId } : {})
    })
  }
}
