# Q-Trader 数据与事件流转机制分析

本文档描述 Q-Trader 系统中数据与事件的完整流转路径，涵盖从交易所 Gateway 到前端的端到端链路，以及 Manager-Trader 进程间的通信机制。

---

## 一、整体架构分层

系统采用 **Manager-Trader 分离的多进程架构**，可纵向划分为 5 层：

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 5: 前端 (Vue 3 + WebSocket)                           │
│  - 接收实时推送 / 发起 HTTP API 请求                          │
├──────────────────────────────────────────────────────────────┤
│  Layer 4: Manager 主控进程 (FastAPI + EventEngine)           │
│  - TraderProxy (Unix Socket Client)                          │
│  - WebSocketManager / 公共数据服务 / 持久化层                 │
├──────────────────────────────────────────────────────────────┤
│  Layer 3: IPC 通信层 (Unix Domain Socket)                    │
│  - 请求-响应模式 (RPC) + 服务端主动 Push 模式                 │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: Trader 子进程 (Socket Server + 事件引擎)           │
│  - TradingEngine / StrategyManager / JobManager              │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: Gateway 适配层 (CTP / TQSDK)                       │
│  - 连接交易所、接收行情回报、发送交易指令                     │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、数据流转机制

### 2.1 行情数据流

**订阅下发（自上而下单向）：**

```
前端/Manager → TraderProxy.request("subscribe")
            → SocketClient → SocketServer
            → Trader._req_subscribe()
            → TradingEngine.subscribe_symbol()
            → Gateway.subscribe()
```

**行情上行（自下而上推送）：**

```
交易所/Gateway → TqGateway._sync_queue 或 CtpGateway 回调
             → _event_dispatcher() 协程
             → AsyncEventEngine.emit(EventTypes.TICK_UPDATE, tick)
             → StrategyManager._on_tick() → BaseStrategy.on_tick()
             → (并行) Trader._on_tick_update()
                → socket_server.send_push("tick")
                → Manager TraderProxy._on_msg_callback()
                → EventEngine.put(EventTypes.TICK_UPDATE)
                → WebSocketManager.broadcast_quote()
                → 前端
```

**特点**：Tick 数据在 Trader 内部**先分发给策略**，再**通过 Socket Push 给 Manager**。

### 2.2 交易指令流（自顶向下）

**下单链路：**

```
前端 HTTP POST /api/orders
→ Manager API routes
→ trader_proxy.request("order_req")
→ SocketServer → Trader._req_order()
→ StrategyManager.open() / TradingEngine.insert_order()
→ RiskControl.check_order()
→ Gateway.send_order()
→ 交易所
```

**撤单链路类似**：`cancel_req` → `Trader._req_cancel()` → `Gateway.cancel_order()`

**高阶指令（如 TWAP）**：`BaseStrategy.send_order_cmds()` → `StrategyManager.send_order_cmd()` → `TradingEngine.insert_order_cmd()` → `OrderCmdExecutor` 拆单调度。

### 2.3 订单/成交回报流（自下而上）

**订单状态更新：**

```
交易所回报 → Gateway → TradingEngine._emit_event(ORDER_UPDATE)
         → AsyncEventEngine → StrategyManager._on_order() → BaseStrategy.on_order()
         → (并行) Trader._on_order_update()
            ├── 写入 PostgreSQL (持久化)
            └── socket_server.send_push("order") → Manager
                → TraderProxy._on_msg_callback()
                → EventEngine.put(EventTypes.ORDER_UPDATE)
                → WebSocketManager.broadcast_order()
                → 前端
```

**成交回报**：流程与订单完全一致，事件类型为 `TRADE_UPDATE`，Trader 端同样先写 PG 再推 Manager。

### 2.4 持仓与账户数据流

**持仓更新**：Gateway 检测到持仓变化 → `TradingEngine` 发 `POSITION_UPDATE` 事件 → `StrategyManager` 和 `Trader._on_position_update()` → Socket Push → Manager → WebSocket。

**账户更新**：Gateway 推送账户资金数据 → `ACCOUNT_UPDATE` → `Trader._on_account_update()`（**缓存+批量持久化**，每 30 秒 `_batch_persist()`）→ 同时实时 Socket Push 给 Manager。

**盈亏计算**：`TraderProxy` 有一个定时任务（默认 2 秒），用最新 Tick 重新计算持仓浮动盈亏，汇总后推送给前端。这意味着**前端看到的盈亏是 Manager 本地计算的**，而非完全依赖 Trader 推送。

---

## 三、事件流转机制

系统存在**两个事件引擎**：

### 3.1 Trader 内：AsyncEventEngine

- 纯异步协程实现
- 所有 Gateway 产生的数据变更都通过它分发
- 订阅者包括：`StrategyManager`、`Trader`（持久化+转发）、`AlarmHandler`、其他内部组件

### 3.2 Manager 内：EventEngine（同步线程版）

- 基于 `Queue + Thread`
- 订阅者包括：`WebSocketManager`、`ManagerPersistence`
- 处理 TraderProxy 转发来的各类事件

### 3.3 核心事件类型映射

| 事件类型 | 生产者 | Trader 内消费者 | Manager 消费者 |
|---------|--------|----------------|---------------|
| `TICK_UPDATE` | Gateway | StrategyManager | WebSocketManager |
| `ORDER_UPDATE` | Gateway | StrategyManager | WebSocketManager + ManagerPersistence |
| `TRADE_UPDATE` | Gateway | StrategyManager | WebSocketManager + ManagerPersistence |
| `POSITION_UPDATE` | Gateway | StrategyManager | WebSocketManager + ManagerPersistence |
| `ACCOUNT_UPDATE` | Gateway | Trader(缓存+Push) | WebSocketManager + ManagerPersistence |
| `ACCOUNT_READY` | TradingEngine | Trader(Push) | WebSocketManager |
| `ALARM_UPDATE` | 任意组件 | Trader(Push) | WebSocketManager(告警处理+DND检查) |
| `ORDER_CMD_UPDATE` | OrderCmdExecutor | StrategyManager | — |

### 3.4 策略层事件分发规则

`StrategyManager` 是策略的路由器：

- **Tick/Bar**：按 `symbol` 过滤，只发给订阅了该合约且 `enabled=True` 的策略
- **Order/Trade**：通过 `order_strategy_map: Dict[order_id, strategy_id]` 精确路由到所属策略

这意味着**策略实例只能看到与自己相关的交易事件**，但**能看到所有订阅合约的行情**。

---

## 四、进程间通信（IPC）机制

### 4.1 协议格式

位于 `src/utils/ipc/protocol.py`：

- **帧格式**：`4字节大端长度 + JSON 报文体`
- **消息结构**（`MessageBody`）：`msg_type` / `request_id` / `data` / `timestamp` / `error`

### 4.2 消息类型

| msg_type | 用途 | 方向 |
|---------|------|------|
| `request` | Manager 查询/指令 Trader | M → T |
| `response` | Trader 返回请求结果 | T → M |
| `push` | Trader 主动推送数据更新 | T → M |
| `heartbeat` | 双向保活 | M ↔ T |
| `error` | 错误响应 | T → M |

### 4.3 连接可靠性

- **Trader 作为 Socket Server**，Manager 的 `TraderProxy` 作为 `SocketClient`
- 客户端带**退避重连机制**（指数退避，最大 60 秒间隔）
- 心跳周期 **15 秒**，服务端 **60 秒** 未收到心跳则断开
- Manager 断线时，Trader 的 `SocketServer` 会**缓冲关键推送**（account/order/trade/position，队列长度 1000），重连后自动 flush

### 4.4 公共数据分发

`PublicDataService` 管理跨账户共享的合约信息：

- **双层存储**：PostgreSQL（持久层）+ 内存缓存（运行时）
- 每个 Trader 启动后，Manager 通过 `push_public_data()` 将合约信息注入 Trader Gateway，避免各 Gateway 重复拉取数据库

---

## 五、前端推送链路（WebSocket）

### 5.1 连接管理

- 端点：`/ws`
- `WebSocketManager` 维护 `active_connections: set[WebSocket]`
- 连接成功先发送 `{"type": "connected", ...}`

### 5.2 事件到 WebSocket 的映射

`WebSocketManager.start()` 向 Manager 的 `EventEngine` 注册以下处理器：

| 事件类型 | WebSocket type | 说明 |
|---------|---------------|------|
| `ACCOUNT_UPDATE` | `account_update` | 含资金、连接状态 |
| `POSITION_UPDATE` | `position_update` | 持仓明细 |
| `ORDER_UPDATE` | `order_update` | 委托单状态 |
| `TRADE_UPDATE` | `trade_update` | 成交记录 |
| `TICK_UPDATE` | `quote_update` | 行情快照 |
| `ACCOUNT_STATUS` | `account_update` | 账户启停状态 |
| `ALARM_UPDATE` | `alarm_update` | 告警消息 |

所有消息格式统一：

```json
{
  "type": "<event_type>",
  "data": {...},
  "timestamp": "2026-04-02T..."
}
```

---

## 六、数据持久化链路

### 6.1 Trader 端持久化

`Trader` 内的事件处理器负责将数据写入 PostgreSQL：

- **订单/成交**：实时写入（`_persist_order()` / `_persist_trade()`）
- **账户/持仓**：先缓存到内存字典，每 30 秒批量写入（`_batch_persist()`）

### 6.2 Manager 端持久化

`ManagerPersistence` 订阅 Manager `EventEngine`，将 Trader 推送的数据写入共享数据库：

- `ACCOUNT_UPDATE` → `AccountPo` (upsert)
- `POSITION_UPDATE` → `PositionPo` (upsert)
- `TRADE_UPDATE` → `TradePo` (insert，幂等去重)

**注意**：当前 `Trader` 直接写 PG，同时 `Manager` 端 `ManagerPersistence` 也会写入共享库，存在**双写路径**，需注意数据一致性。

---

## 七、核心委托链总结

### 7.1 请求/指令向下委托

| 场景 | 委托链 |
|------|--------|
| 前端下单 | 前端 → Manager API → `TraderProxy.request("order_req")` → `SocketClient` → `SocketServer` → `Trader._req_order()` → `StrategyManager.open()` / `TradingEngine.insert_order()` → `Gateway.send_order()` → 交易所 |
| 查询账户 | Manager API → `TraderProxy.request("get_account")` → `Trader._req_get_account()` → `TradingEngine.account` → 返回 |
| 策略控制 | Manager API → `TraderProxy` → `Trader` (Socket RPC) → `StrategyManager` → `BaseStrategy` |

### 7.2 事件/数据向上传播

| 场景 | 传播链 |
|------|--------|
| 行情到策略 | `Gateway` → `TradingEngine.emit(TICK_UPDATE)` → `AsyncEventEngine` → `StrategyManager._on_tick()` → `BaseStrategy.on_tick()` |
| 订单回报到 Manager | `Gateway` → `TradingEngine.emit(ORDER_UPDATE)` → `Trader._on_order_update()` → **写PG** + `socket_server.send_push("order")` → `TraderProxy` → `EventEngine` → `WebSocketManager` → 前端 |
| 策略下单 | `BaseStrategy.send_order_cmds()` → `StrategyManager.send_order_cmd()` → `TradingEngine.insert_order_cmd()` → `OrderCmdExecutor` → `Gateway` |

---

## 八、设计亮点与值得关注的地方

### 8.1 亮点

1. **Gateway 抽象层设计良好**：通过 `BaseGateway` 统一了 CTP 和 TQSDK 的差异，`Pydantic` 模型作为统一数据语言。
2. **事件驱动解耦**：TradingEngine 不直接依赖策略或持久化，全部通过事件引擎发布，模块间耦合度低。
3. **IPC 可靠性考虑充分**：心跳、自动重连、断线缓冲（`BUFFERED_PUSH_TYPES`）、退避策略一应俱全。
4. **策略事件路由精确**：`order_strategy_map` 保证订单/成交只路由到相关策略，避免策略间干扰。

### 8.2 需要关注的风险点

1. **双写持久化**：Trader 直接写 PG，Manager 也写共享库，如果事务边界不一致，可能出现数据竞争或覆盖。
2. **Tick 推送频率**：Trader 将每个 Tick 都通过 Socket Push 给 Manager，如果合约数量多、Tick 频率高，Manager 进程可能成为瓶颈。
3. **盈亏计算分离**：Manager 本地用缓存 Tick 计算盈亏（2 秒定时任务），若 Tick 延迟或缺失，前端看到的盈亏可能与 Trader 端不一致。
4. **事件引擎版本差异**：Trader 用 `AsyncEventEngine`（纯异步），Manager 用 `EventEngine`（同步线程 + `asyncio.run_coroutine_threadsafe`），跨进程事件处理语义存在差异。
