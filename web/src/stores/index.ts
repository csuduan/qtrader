import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Account, Position, Trade, Order, SystemStatus, Quote } from '@/types'
import { accountApi, positionApi, tradeApi, orderApi } from '@/api'
import wsManager from '@/ws'

export const useStore = defineStore('main', () => {
  // 账户信息
  const account = ref<Account | null>(null)
  const accounts = ref<Account[]>([])

  // 多账号模式
  const selectedAccountId = ref<string | null>(null)

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

  // ==================== 计算属性 ====================

  // 是否为多账号模式
  const isMultiAccountMode = computed(() => {
    return accounts.value.length > 1
  })

  // 当前账户（多账号模式下使用选中的账户）
  const currentAccount = computed(() => {
    if (isMultiAccountMode.value) {
      if (selectedAccountId.value) {
        return accounts.value.find(acc => acc.account_id === selectedAccountId.value) || null
      }
      // 如果没有选中，返回第一个
      return accounts.value[0] || null
    }
    return account.value
  })

  // 活动订单
  const activeOrders = computed(() => {
    return orders.value.filter(order => order.status === 'ALIVE')
  })

  // 当前账户的持仓
  const currentPositions = computed(() => {
    if (!selectedAccountId.value) return positions.value
    return positions.value.filter(pos => pos.account_id === selectedAccountId.value)
  })

  // 当前账户的成交
  const currentTrades = computed(() => {
    let filtered = trades.value
    if (selectedAccountId.value) {
      filtered = trades.value.filter(trade => trade.account_id === selectedAccountId.value)
    }
    // 按成交时间倒序排列（最新的在前面）
    return [...filtered].sort((a, b) => b.trade_date_time - a.trade_date_time)
  })

  // 当前账户的订单
  const currentOrders = computed(() => {
    let filtered = orders.value
    if (selectedAccountId.value) {
      filtered = orders.value.filter(order => order.account_id === selectedAccountId.value)
    }
    // 按报单时间倒序排列（最新的在前面）
    // insert_date_time 可能是 number（时间戳）或 string（ISO 格式）
    return [...filtered].sort((a, b) => {
      const timeA = typeof a.insert_date_time === 'number'
        ? a.insert_date_time
        : new Date(a.insert_date_time).getTime()
      const timeB = typeof b.insert_date_time === 'number'
        ? b.insert_date_time
        : new Date(b.insert_date_time).getTime()
      return timeB - timeA
    })
  })

  // 账户汇总信息
  const accountsSummary = computed(() => {
    const totalBalance = accounts.value.reduce((sum, acc) => sum + acc.balance, 0)
    const totalAvailable = accounts.value.reduce((sum, acc) => sum + acc.available, 0)
    const totalMargin = accounts.value.reduce((sum, acc) => sum + acc.margin, 0)
    const totalFloatProfit = accounts.value.reduce((sum, acc) => sum + (acc.float_profit || 0), 0)

    return {
      totalBalance,
      totalAvailable,
      totalMargin,
      totalFloatProfit,
      accountCount: accounts.value.length
    }
  })

  // ==================== 方法 ====================

  /**
   * 加载账户信息
   * @deprecated 已废弃，请使用 loadAllAccounts() 代替
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
      // 如果有账户但还没选中，默认选中第一个已连接的账户
      if (!selectedAccountId.value && accounts.value.length > 0) {
        const firstConnected = accounts.value.find(acc => acc.status === 'connected')
        const firstAccount = accounts.value[0]
        selectedAccountId.value = (firstConnected || firstAccount)?.account_id || null
      }
    } catch (error) {
      console.error('加载账户列表失败:', error)
    }
  }

  /**
   * 切换账户
   */
  function switchAccount(accountId: string) {
    selectedAccountId.value = accountId
    console.log('切换到账户:', accountId)
  }

  /**
   * 加载持仓信息
   */
  async function loadPositions(accountId?: string) {
    try {
      // 如果没有指定 accountId，使用当前选中的账户
      const targetAccountId = accountId || selectedAccountId.value || undefined
      positions.value = await positionApi.getPositions(targetAccountId)
    } catch (error) {
      console.error('加载持仓信息失败:', error)
    }
  }

  /**
   * 加载成交记录
   */
  async function loadTrades(date?: string, accountId?: string) {
    try {
      // 如果没有指定 accountId，使用当前选中的账户
      const targetAccountId = accountId || selectedAccountId.value || undefined
      trades.value = await tradeApi.getTrades({ date, account_id: targetAccountId })
    } catch (error) {
      console.error('加载成交记录失败:', error)
    }
  }

  /**
   * 加载委托单
   */
  async function loadOrders(status?: string, accountId?: string) {
    try {
      // 如果没有指定 accountId，使用当前选中的账户
      const targetAccountId = accountId || selectedAccountId.value || undefined
      orders.value = await orderApi.getOrders(status, targetAccountId)
    } catch (error) {
      console.error('加载委托单失败:', error)
    }
  }

  /**
   * 加载系统状态（已废弃，状态信息现在直接从account接口获取）
   * @deprecated 请直接从账户数据中获取状态
   */
  async function loadSystemStatus(_accountId?: string) {
    // 此函数已废弃，状态信息直接从account接口获取
    console.log('loadSystemStatus已废弃，状态信息直接从account接口获取')
  }

  /**
   * 加载所有数据
   */
  async function loadAllData() {
    // 统一使用 account/all 接口加载所有账户
    await loadAllAccounts()

    // 如果有账户数据，加载持仓、成交、订单
    if (accounts.value.length > 0) {
      await Promise.all([
        loadPositions(),
        loadTrades(),
        loadOrders()
      ])
    }
  }

  /**
   * 更新账户信息
   */
  function updateAccount(data: Account) {
    // 如果是当前选中的账户，更新主账户
    if (isMultiAccountMode.value && data.account_id === selectedAccountId.value) {
      account.value = { ...account.value, ...data }
    }
    // 更新账户列表中的对应账户，保留未更新的字段
    const index = accounts.value.findIndex(acc => acc.account_id === data.account_id)
    if (index > -1) {
      accounts.value[index] = { ...accounts.value[index], ...data }
    }
  }

  /**
   * 更新所有账户信息（多账号模式）
   */
  function updateAccounts(data: Account[]) {
    accounts.value = data
    // 如果当前选中的账户不在新列表中，选择第一个
    if (selectedAccountId.value) {
      const exists = data.some(acc => acc.account_id === selectedAccountId.value)
      if (!exists && data.length > 0) {
        const firstAccount = data[0]
        if (firstAccount) {
          selectedAccountId.value = firstAccount.account_id
        }
      }
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
    wsManager.onAccountsUpdate(updateAccounts)
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
    selectedAccountId,
    positions,
    trades,
    orders,
    quotes,

    // 系统状态
    systemStatus,

    // 计算属性
    isMultiAccountMode,
    currentAccount,
    activeOrders,
    currentPositions,
    currentTrades,
    currentOrders,
    accountsSummary,

    // 方法
    loadAccount,
    loadAllAccounts,
    switchAccount,
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
