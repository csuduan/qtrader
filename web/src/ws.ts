import { ref, type Ref } from 'vue'
import type { WSMessage, Account, Position, Trade, Order } from '@/types'

/**
 * 获取 WebSocket URL
 * 根据环境自动选择正确的 URL
 */
function getWebSocketUrl(): string {
  // 开发环境：使用相对路径，由 Vite 代理转发
  if (import.meta.env.DEV) {
    return '/ws'
  }
  // 生产环境：使用完整的 WebSocket URL
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/ws`
}

class WebSocketManager {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 3000
  private reconnectTimer: any = null

   // 消息回调
   private onConnectedCallbacks: Array<() => void> = []
   private onDisconnectedCallbacks: Array<() => void> = []
   private onAccountUpdateCallbacks: Array<(data: Account) => void> = []
   private onPositionUpdateCallbacks: Array<(data: Position) => void> = []
   private onTradeUpdateCallbacks: Array<(data: Trade) => void> = []
   private onOrderUpdateCallbacks: Array<(data: Order) => void> = []
   private onTickUpdateCallbacks: Array<(data: any) => void> = []

  // 批处理队列：换仓等高峰期消息量大，先合并再批量分发，避免每条消息都触发响应式更新和表格重渲染
  private flushDelay = 150
  private flushTimer: any = null
  private pendingAccounts: Map<string, Account> = new Map()
  private pendingPositions: Map<string, Position> = new Map()
  private pendingOrders: Map<string, Order> = new Map()
  private pendingTrades: Map<string, Trade> = new Map()
  private pendingTicks: Map<string, any> = new Map()

  // 连接状态
  public connected: Ref<boolean> = ref(false)
  public connecting: Ref<boolean> = ref(false)

  /**
   * 连接 WebSocket（自动附加登录 token，未登录时跳过）
   */
  connect(url: string = getWebSocketUrl()): void {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      console.log('WebSocket 已连接或正在连接')
      return
    }

    const token = localStorage.getItem('token')
    if (!token) {
      console.warn('未登录，跳过 WebSocket 连接')
      this.connecting.value = false
      return
    }

    const sep = url.includes('?') ? '&' : '?'
    const authedUrl = `${url}${sep}token=${encodeURIComponent(token)}`

    this.connecting.value = true
    this.ws = new WebSocket(authedUrl)

    this.ws.onopen = () => {
      console.log('WebSocket 连接成功')
      this.connected.value = true
      this.connecting.value = false
      this.reconnectAttempts = 0
      this.onConnectedCallbacks.forEach(cb => cb())
    }

    this.ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data)
        this.handleMessage(message)
      } catch (error) {
        console.error('解析 WebSocket 消息失败:', error)
      }
    }

    this.ws.onclose = (event) => {
      console.log('WebSocket 连接关闭')
      this.connected.value = false
      this.connecting.value = false
      this.onDisconnectedCallbacks.forEach(cb => cb())

      // 4401: 服务端鉴权拒绝（token 无效/过期），不再自动重连
      if (event.code === 4401) {
        console.warn('WebSocket 鉴权失败，停止重连')
        return
      }

      // 自动重连
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++
        console.log(`尝试重连 (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`)
        this.reconnectTimer = setTimeout(() => {
          this.connect(url)
        }, this.reconnectDelay)
      }
    }

    this.ws.onerror = (error) => {
      console.error('WebSocket 错误:', error)
      this.connecting.value = false
    }
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.flushTimer) {
      clearTimeout(this.flushTimer)
      this.flushTimer = null
    }

    // 清空未分发的消息，避免断线前的陈旧状态在重连后被推入 store
    this.pendingAccounts.clear()
    this.pendingPositions.clear()
    this.pendingOrders.clear()
    this.pendingTrades.clear()
    this.pendingTicks.clear()

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.connected.value = false
    this.connecting.value = false
    this.reconnectAttempts = 0
  }

  /**
   * 发送消息到服务端
   */
  private send(type: string, data?: any): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }))
    }
  }

  /**
   * 订阅行情推送
   */
  subscribeQuotes(): void {
    this.send('subscribe_quotes')
  }

  /**
   * 取消订阅行情推送
   */
  unsubscribeQuotes(): void {
    this.send('unsubscribe_quotes')
  }

   /**
    * 处理消息：先入队合并，由 flush 定时批量分发
    */
     private handleMessage(message: WSMessage): void {
       switch (message.type) {
         case 'connected':
           console.log('收到连接确认消息:', message.data)
           break
         case 'account_update': {
           //console.log('收到账户更新:', message.data)
           const account = message.data as Account
           this.pendingAccounts.set(account.account_id, account)
           break
         }
         case 'position_update': {
           const position = message.data as Position
           this.pendingPositions.set(`${position.account_id}|${position.symbol}`, position)
           break
         }
         case 'trade_update': {
           // 成交是事件流，按 trade_id 去重保留最新；order_ref/trade_id 跨账户可能重复，键加账户前缀
           const trade = message.data as Trade
           this.pendingTrades.set(`${trade.account_id}|${trade.trade_id}`, trade)
           break
         }
         case 'order_update': {
           // 同一订单在窗口期内只保留最终状态；order_ref 跨账户可能重复，键加账户前缀
           const order = message.data as Order
           this.pendingOrders.set(`${order.account_id}|${order.order_id}`, order)
           break
         }
         case 'tick_update':
         case 'quote_update': {
           const tick = message.data
           this.pendingTicks.set(tick.symbol, tick)
           break
         }
         case 'quote_batch_update': {
           // 批量行情推送：data.ticks 为 tick 数组，data.account_id 为账户ID
           const batchData = message.data as { ticks?: any[], account_id?: string }
           if (batchData.ticks) {
             batchData.ticks.forEach(tick => this.pendingTicks.set(tick.symbol, tick))
           }
           break
         }
         default:
           console.warn('未知消息类型:', message.type)
           return
        }
        this.scheduleFlush()
      }

   /**
    * 调度批量分发（消息到达后延迟 flushDelay 毫秒统一分发）
    */
     private scheduleFlush(): void {
       if (this.flushTimer) {
         return
       }
       this.flushTimer = setTimeout(() => {
         this.flushTimer = null
         this.flush()
       }, this.flushDelay)
     }

   /**
    * 批量分发队列中的消息
    */
     private flush(): void {
       if (this.pendingAccounts.size > 0) {
         const items = Array.from(this.pendingAccounts.values())
         this.pendingAccounts.clear()
         items.forEach(data => this.onAccountUpdateCallbacks.forEach(cb => cb(data)))
       }
       if (this.pendingPositions.size > 0) {
         const items = Array.from(this.pendingPositions.values())
         this.pendingPositions.clear()
         items.forEach(data => this.onPositionUpdateCallbacks.forEach(cb => cb(data)))
       }
       if (this.pendingTrades.size > 0) {
         const items = Array.from(this.pendingTrades.values())
         this.pendingTrades.clear()
         items.forEach(data => this.onTradeUpdateCallbacks.forEach(cb => cb(data)))
       }
       if (this.pendingOrders.size > 0) {
         const items = Array.from(this.pendingOrders.values())
         this.pendingOrders.clear()
         items.forEach(data => this.onOrderUpdateCallbacks.forEach(cb => cb(data)))
       }
       if (this.pendingTicks.size > 0) {
         const items = Array.from(this.pendingTicks.values())
         this.pendingTicks.clear()
         items.forEach(data => this.onTickUpdateCallbacks.forEach(cb => cb(data)))
       }
     }

  /**
   * 订阅连接成功事件
   */
  onConnected(callback: () => void): () => void {
    this.onConnectedCallbacks.push(callback)
    return () => {
      const index = this.onConnectedCallbacks.indexOf(callback)
      if (index > -1) {
        this.onConnectedCallbacks.splice(index, 1)
      }
    }
  }

  /**
   * 订阅断开连接事件
   */
  onDisconnected(callback: () => void): () => void {
    this.onDisconnectedCallbacks.push(callback)
    return () => {
      const index = this.onDisconnectedCallbacks.indexOf(callback)
      if (index > -1) {
        this.onDisconnectedCallbacks.splice(index, 1)
      }
    }
  }

  /**
   * 订阅账户更新事件
   */
  onAccountUpdate(callback: (data: Account) => void): () => void {
    this.onAccountUpdateCallbacks.push(callback)
    return () => {
      const index = this.onAccountUpdateCallbacks.indexOf(callback)
      if (index > -1) {
        this.onAccountUpdateCallbacks.splice(index, 1)
      }
    }
  }

  /**
   * 订阅持仓更新事件
   */
  onPositionUpdate(callback: (data: Position) => void): () => void {
    this.onPositionUpdateCallbacks.push(callback)
    return () => {
      const index = this.onPositionUpdateCallbacks.indexOf(callback)
      if (index > -1) {
        this.onPositionUpdateCallbacks.splice(index, 1)
      }
    }
  }

  /**
   * 订阅成交更新事件
   */
  onTradeUpdate(callback: (data: Trade) => void): () => void {
    this.onTradeUpdateCallbacks.push(callback)
    return () => {
      const index = this.onTradeUpdateCallbacks.indexOf(callback)
      if (index > -1) {
        this.onTradeUpdateCallbacks.splice(index, 1)
      }
    }
  }

  /**
   * 订阅委托单更新事件
   */
  onOrderUpdate(callback: (data: Order) => void): () => void {
    this.onOrderUpdateCallbacks.push(callback)
    return () => {
      const index = this.onOrderUpdateCallbacks.indexOf(callback)
      if (index > -1) {
        this.onOrderUpdateCallbacks.splice(index, 1)
      }
    }
  }

  /**
   * 订阅行情更新事件
   */
  onTickUpdate(callback: (data: any) => void): () => void {
    this.onTickUpdateCallbacks.push(callback)
    return () => {
      const index = this.onTickUpdateCallbacks.indexOf(callback)
      if (index > -1) {
        this.onTickUpdateCallbacks.splice(index, 1)
      }
    }
  }
}

// 导出单例
export const wsManager = new WebSocketManager()

export default wsManager
