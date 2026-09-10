import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Account, Position, Trade, Order, SystemStatus, Quote } from '@/types'
import { accountApi, positionApi, tradeApi, orderApi, contractApi } from '@/api'
import wsManager from '@/ws'
import { getTradeNaturalTime } from '@/utils/dateTime'

export const useStore = defineStore('main', () => {
  // 账户信息
  const account = ref<Account | null>(null)
  const accounts = ref<Account[]>([])

  // 主力合约代码（如 rb2701），用于表单占位提示；惰性加载，会话内缓存
  const mainSymbol = ref('')

  // 多账号模式
  const selectedAccountId = ref<string | null>(null)

  // 持仓信息
  const positions = ref<Position[]>([])

  // 成交记录
  const trades = ref<Trade[]>([])

  // 委托单
  // 委托单列表（Map 存储，键为 account_id|order_id：order_ref 跨账户可能重复，且更新为 O(1)）
  const orders = ref(new Map<string, Order>())

  function orderKey(order: Order): string {
    return `${order.account_id}|${order.order_id}`
  }

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

  // 是否为多账号模式（始终使用多账户模式，即使只有一个账户）
  const isMultiAccountMode = computed(() => {
    return accounts.value.length >= 1
  })

  // 当前账户（使用选中的账户）
  const currentAccount = computed(() => {
    if (selectedAccountId.value) {
      return accounts.value.find(acc => acc.account_id === selectedAccountId.value) || null
    }
    // 如果没有选中，返回第一个
    return accounts.value[0] || null
  })

  // 活动订单
  const activeOrders = computed(() => {
    return Array.from(orders.value.values()).filter(order => order.status === 'ALIVE')
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
    // 按成交的自然时间倒序排列（夜盘成交按实际发生时间排，而非交易日时间）
    return [...filtered].sort(
      (a, b) => getTradeNaturalTime(b.trade_date_time) - getTradeNaturalTime(a.trade_date_time)
    )
  })

  // 当前账户的订单
  const currentOrders = computed(() => {
    let filtered = Array.from(orders.value.values())
    if (selectedAccountId.value) {
      filtered = filtered.filter(order => order.account_id === selectedAccountId.value)
    }
    // 按报单时间倒序排列（最新的在前面），insert_date_time 为 ISO 字符串
    return [...filtered].sort((a, b) => {
      const timeA = new Date(a.insert_date_time).getTime()
      const timeB = new Date(b.insert_date_time).getTime()
      return timeB - timeA
    })
  })

  // 账户汇总信息
  const accountsSummary = computed(() => {
    const totalBalance = accounts.value.reduce((sum, acc) => sum + acc.balance, 0)
    const totalAvailable = accounts.value.reduce((sum, acc) => sum + acc.available, 0)
    const totalMargin = accounts.value.reduce((sum, acc) => sum + acc.margin, 0)
    const totalFloatProfit = accounts.value.reduce((sum, acc) => sum + (acc.position_profit || 0), 0)

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
   * 加载账户ID列表（轻量级，只返回ID列表）
   */
  async function loadAccountList(): Promise<string[]> {
    try {
      const accountIds = await accountApi.getAccountList()
      // 初始化 accounts 数组，只包含 account_id
      accounts.value = accountIds.map(id => ({
        account_id: id,
        broker_type: '--',
        broker_name: '--',
        currency: 'CNY',
        balance: 0,
        available: 0,
        margin: 0,
        pre_balance: 0,
        static_balance: 0,
        position_profit: 0,
        close_profit: 0,
        today_profit: 0,
        risk_ratio: 0,
        updated_at: new Date().toISOString(),
        user_id: '--',
        status: 'stopped'
      } as Account))

      // 如果有账户但还没选中，默认选中第一个
      if (!selectedAccountId.value && accountIds.length > 0) {
        selectedAccountId.value = accountIds[0] || null
      }
      return accountIds
    } catch (error) {
      console.error('加载账户ID列表失败:', error)
      return []
    }
  }

  /**
   * 加载当前选中账户的详情
   */
  async function loadCurrentAccount() {
    try {
      if (!selectedAccountId.value) {
        return
      }
      const accountData = await accountApi.getAccount(selectedAccountId.value)
      // 更新账户列表中的对应账户
      const index = accounts.value.findIndex(acc => acc.account_id === accountData.account_id)
      if (index > -1) {
        accounts.value[index] = accountData
      }
    } catch (error) {
      console.error('加载当前账户详情失败:', error)
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
  async function loadOrders(status: string, accountId?: string) {
    try {
      // 如果没有指定 accountId，使用当前选中的账户
      const targetAccountId = accountId || selectedAccountId.value || undefined
      const list = await orderApi.getOrders(status, targetAccountId)
      orders.value = new Map(list.map(o => [orderKey(o), o]))
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
   * 优化：先加载账户列表（轻量级），再加载当前账户详情
   */
  async function loadAllData() {
    // 先加载账户ID列表（轻量级）
    await loadAccountList()

    // 加载当前选中账户的详情
    await loadCurrentAccount()

    // 如果有账户数据，加载持仓、成交、订单
    if (accounts.value.length > 0) {
      await Promise.all([
        loadPositions(),
        loadTrades(),
        loadOrders('ALIVE')
      ])
    }
  }

  /**
   * 获取主力合约代码（供合约输入框占位提示用）
   * 首次调用拉取主力合约列表取螺纹钢主力，失败静默返回空串
   */
  async function loadMainSymbol(): Promise<string> {
    if (mainSymbol.value) return mainSymbol.value
    try {
      const mains = await contractApi.getContracts({ symbol_keyword: 'rb', is_main: true })
      mainSymbol.value = mains[0]?.symbol || ''
    } catch (error) {
      console.error('加载主力合约失败:', error)
    }
    return mainSymbol.value
  }

  /**
   * 更新账户信息
   */
  function updateAccount(data: Account) {
    // 更新账户列表中的对应账户，保留未更新的字段
    const index = accounts.value.findIndex(acc => acc.account_id === data.account_id)
    if (index > -1) {
      accounts.value[index] = { ...accounts.value[index], ...data }
    }
  }

  /**
   * 更新持仓信息
   */
  function updatePosition(data: Position) {
    const index = positions.value.findIndex(pos =>
      pos.account_id === data.account_id && pos.symbol === data.symbol
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
    // 检查是否已存在（trade_id 跨账户可能重复，需连同账户一起判断）
    const exists = trades.value.some(
      trade => trade.trade_id === data.trade_id && trade.account_id === data.account_id
    )
    if (!exists) {
      trades.value.unshift(data)
    }
  }

  /**
   * 更新委托单
   */
  function updateOrder(data: Order) {
    orders.value.set(orderKey(data), data)
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
    mainSymbol,

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
    loadAccountList,
    loadCurrentAccount,
    switchAccount,
    loadPositions,
    loadTrades,
    loadOrders,
    loadSystemStatus,
    loadAllData,
    loadMainSymbol,
    initWebSocket,
    updateAccount,
    updatePosition,
    addTrade,
    updateOrder,
    updateQuote,
    getQuote
  }
}, {
  persist: {
    pick: ['selectedAccountId']
  }
})
