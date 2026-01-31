import request from './request'
import type { Alarm, AlarmStats, AlarmStatus } from '@/types'

export const alarmApi = {
  getTodayAlarms(accountId?: string, statusFilter?: AlarmStatus): Promise<Alarm[]> {
    return request.get('/alarm/list', {
      params: {
        ...(accountId ? { account_id: accountId } : {}),
        ...(statusFilter ? { status_filter: statusFilter } : {})
      }
    })
  },

  getAlarmStats(accountId?: string): Promise<AlarmStats> {
    return request.get('/alarm/stats', {
      params: { ...(accountId ? { account_id: accountId } : {}) }
    })
  },

  confirmAlarm(alarmId: number, accountId?: string): Promise<Alarm> {
    return request.post(`/alarm/confirm/${alarmId}`, {
      ...(accountId ? { account_id: accountId } : {})
    })
  }
}
