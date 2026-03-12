import { ref, type Ref } from 'vue'
import type { WSMessage, Account, Position, Trade, Order, SystemStatus, Alarm } from '@/types'

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
   private onAccountsUpdateCallbacks: Array<(data: Account[]) => void> = []
   private onPositionUpdateCallbacks: Array<(data: Position) => void> = []
   private onTradeUpdateCallbacks: Array<(data: Trade) => void> = []
   private onOrderUpdateCallbacks: Array<(data: Order) => void> = []
    private onSystemStatusCallbacks: Array<(data: SystemStatus) => void> = []
    private onTickUpdateCallbacks: Array<(data: any) => void> = []
    private onAlarmUpdateCallbacks: Array<(data: Alarm) => void> = []

  // 连接状态
  public connected: Ref<boolean> = ref(false)
  public connecting: Ref<boolean> = ref(false)

  /**
   * 连接 WebSocket
   */
  connect(url: string = getWebSocketUrl()): void {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      console.log('WebSocket 已连接或正在连接')
      return
    }

    this.connecting.value = true
    this.ws = new WebSocket(url)

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

    this.ws.onclose = () => {
      console.log('WebSocket 连接关闭')
      this.connected.value = false
      this.connecting.value = false
      this.onDisconnectedCallbacks.forEach(cb => cb())

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

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.connected.value = false
    this.connecting.value = false
    this.reconnectAttempts = 0
  }

   /**
    * 处理消息
    */
     private handleMessage(message: WSMessage): void {
       switch (message.type) {
         case 'connected':
           console.log('收到连接确认消息:', message.data)
           break
         case 'account_update':
           this.onAccountUpdateCallbacks.forEach(cb => cb(message.data))
           break
         case 'accounts_update':
           this.onAccountsUpdateCallbacks.forEach(cb => cb(message.data))
           break
         case 'position_update':
           this.onPositionUpdateCallbacks.forEach(cb => cb(message.data))
           break
         case 'trade_update':
           this.onTradeUpdateCallbacks.forEach(cb => cb(message.data))
           break
         case 'order_update':
           this.onOrderUpdateCallbacks.forEach(cb => cb(message.data))
           break
         case 'system_status':
           this.onSystemStatusCallbacks.forEach(cb => cb(message.data))
           break
           case 'tick_update':
           case 'quote_update':
             this.onTickUpdateCallbacks.forEach(cb => cb(message.data))
             break
           case 'alarm_update':
             this.onAlarmUpdateCallbacks.forEach(cb => cb(message.data))
             break
           default:
             console.warn('未知消息类型:', message.type)
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
   * 订阅所有账户更新事件（多账号模式）
   */
  onAccountsUpdate(callback: (data: Account[]) => void): () => void {
    this.onAccountsUpdateCallbacks.push(callback)
    return () => {
      const index = this.onAccountsUpdateCallbacks.indexOf(callback)
      if (index > -1) {
        this.onAccountsUpdateCallbacks.splice(index, 1)
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
    * 订阅系统状态更新事件
    */
   onSystemStatus(callback: (data: SystemStatus) => void): () => void {
     this.onSystemStatusCallbacks.push(callback)
     return () => {
       const index = this.onSystemStatusCallbacks.indexOf(callback)
       if (index > -1) {
         this.onSystemStatusCallbacks.splice(index, 1)
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

     /**
       * 订阅告警更新事件
       */
     onAlarmUpdate(callback: (data: Alarm) => void): () => void {
       this.onAlarmUpdateCallbacks.push(callback)
       return () => {
         const index = this.onAlarmUpdateCallbacks.indexOf(callback)
         if (index > -1) {
           this.onAlarmUpdateCallbacks.splice(index, 1)
         }
       }
     }
   }

// 导出单例
export const wsManager = new WebSocketManager()

export default wsManager
