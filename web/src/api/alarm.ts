import request from './request'
import type { Alarm, AlarmStats, AlarmStatus } from '@/types'

export const alarmApi = {
  getTodayAlarms(statusFilter?: AlarmStatus): Promise<Alarm[]> {
    return request.get('/alarm/list', {
      params: {
        ...(statusFilter ? { status_filter: statusFilter } : {})
      }
    })
  },

  getAlarmStats(): Promise<AlarmStats> {
    return request.get('/alarm/stats')
  },

  confirmAlarm(alarmId: number): Promise<Alarm> {
    return request.post(`/alarm/confirm/${alarmId}`)
  },

  confirmAllAlarms(): Promise<{ confirmed_count: number }> {
    return request.post('/alarm/confirm_all')
  }
}
