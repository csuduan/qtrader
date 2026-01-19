import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Account, Position, Trade, Order, SystemStatus, Quote } from '@/types'
import { accountApi, positionApi, tradeApi, orderApi, systemApi } from '@/api'
import wsManager from '@/ws'

export const useStore = defineStore('main', () => {
  // 账户信息
  const account = ref<Account | null>(null)
  const accounts = ref<Account[]>([])

  // 持仓信息
  const positions = ref<Position[]>([])

  // 成交记录
  const trades = ref<Trade[]>([])

  // 委托单
  const orders = ref<Order[]>([])

  // 行情数据
  const quotes = ref<Map<string, Quote>>(new Map())

  // 系统状态
  const systemStatus = ref<SystemStatus>({
    connected: false,
    paused: false,
    account_id: '',
    daily_orders: 0,
    daily_cancels: 0
  })

  // 计算属性
  const activeOrders = computed(() => {
    return orders.value.filter(order => order.status === 'ALIVE')
  })

  /**
   * 加载账户信息
   */
  async function loadAccount() {
    try {
      account.value = await accountApi.getAccount()
    } catch (error) {
      console.error('加载账户信息失败:', error)
    }
  }

  /**
   * 加载所有账户信息
   */
  async function loadAllAccounts() {
    try {
      accounts.value = await accountApi.getAllAccounts()
    } catch (error) {
      console.error('加载账户列表失败:', error)
    }
  }

  /**
   * 加载持仓信息
   */
  async function loadPositions() {
    try {
      positions.value = await positionApi.getPositions()
    } catch (error) {
      console.error('加载持仓信息失败:', error)
    }
  }

  /**
   * 加载成交记录
   */
  async function loadTrades(date?: string) {
    try {
      trades.value = await tradeApi.getTrades({ date })
    } catch (error) {
      console.error('加载成交记录失败:', error)
    }
  }

  /**
   * 加载委托单
   */
  async function loadOrders(status?: string) {
    try {
      orders.value = await orderApi.getOrders(status)
    } catch (error) {
      console.error('加载委托单失败:', error)
    }
  }

  /**
   * 加载系统状态
   */
  async function loadSystemStatus() {
    try {
      systemStatus.value = await systemApi.getStatus()
    } catch (error) {
      console.error('加载系统状态失败:', error)
    }
  }

  /**
   * 加载所有数据
   */
  async function loadAllData() {
    await Promise.all([
      loadAccount(),
      loadPositions(),
      loadTrades(),
      loadOrders(),
      loadSystemStatus()
    ])
  }

  /**
   * 更新账户信息
   */
  function updateAccount(data: Account) {
    account.value = data
    // 更新账户列表中的对应账户
    const index = accounts.value.findIndex(acc => acc.account_id === data.account_id)
    if (index > -1) {
      accounts.value[index] = data
    }
  }

  /**
   * 更新持仓信息
   */
  function updatePosition(data: Position) {
    const index = positions.value.findIndex(pos =>
      pos.account_id === data.account_id && pos.instrument_id === data.instrument_id
    )
    if (index > -1) {
      positions.value[index] = data
    } else {
      positions.value.push(data)
    }
  }

  /**
   * 添加成交记录
   */
  function addTrade(data: Trade) {
    // 检查是否已存在
    const exists = trades.value.some(trade => trade.trade_id === data.trade_id)
    if (!exists) {
      trades.value.unshift(data)
    }
  }

  /**
   * 更新委托单
   */
  function updateOrder(data: Order) {
    const index = orders.value.findIndex(order => order.order_id === data.order_id)
    if (index > -1) {
      orders.value[index] = data
    } else {
      orders.value.unshift(data)
    }
  }

  /**
   * 更新系统状态
   */
  function updateSystemStatus(data: SystemStatus) {
    systemStatus.value = data
  }

  /**
   * 更新行情数据
   */
  function updateQuote(data: any) {
    const symbol = data.symbol
    quotes.value.set(symbol, data)
  }

  /**
   * 获取行情数据
   */
  function getQuote(symbol: string): Quote | undefined {
    return quotes.value.get(symbol)
  }

  /**
   * 初始化 WebSocket
   */
  function initWebSocket() {
    wsManager.onAccountUpdate(updateAccount)
    wsManager.onPositionUpdate(updatePosition)
    wsManager.onTradeUpdate(addTrade)
    wsManager.onOrderUpdate(updateOrder)
    wsManager.onSystemStatus(updateSystemStatus)
    wsManager.onTickUpdate(updateQuote)

    wsManager.connect()
  }

  return {
    // 状态
    account,
    accounts,
    positions,
    trades,
    orders,
    quotes,

    // 系统状态
    systemStatus,

    // 计算属性
    activeOrders,

    // 方法
    loadAccount,
    loadAllAccounts,
    loadPositions,
    loadTrades,
    loadOrders,
    loadSystemStatus,
    loadAllData,
    initWebSocket,
    updateAccount,
    updatePosition,
    addTrade,
    updateOrder,
    updateSystemStatus,
    updateQuote,
    getQuote
  }
})
