/**
 * 将成交的交易时间换算为自然时间（毫秒时间戳），用于排序。
 * 夜盘成交（20:00 之后）归属于下一交易日，其交易时间比自然时间晚一天，需回退一天。
 */
export function getTradeNaturalTime(tradeDateTime: number | string | null | undefined): number {
  if (tradeDateTime === null || tradeDateTime === undefined) return 0
  let ms: number
  if (typeof tradeDateTime === 'number') {
    ms = tradeDateTime > 1e12 ? tradeDateTime : tradeDateTime * 1000
  } else {
    ms = new Date(tradeDateTime).getTime()
  }
  if (Number.isNaN(ms)) return 0
  if (new Date(ms).getHours() >= 20) {
    ms -= 24 * 60 * 60 * 1000
  }
  return ms
}
