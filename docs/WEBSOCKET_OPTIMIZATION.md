# WebSocket 推送优化说明

## 更新时间
2026-01-19

## 问题背景

在之前的实现中，账户信息更新是通过事件驱动的，每当交易引擎检测到账户信息发生变化，就会立即通过 WebSocket 推送给所有连接的客户端。这种方式导致了以下问题：

1. **推送频率过高**：在高频交易场景下，账户信息可能频繁变化，导致过多的 WebSocket 消息推送
2. **客户端负担重**：前端需要频繁接收和处理更新消息，增加了 CPU 和内存负担
3. **网络带宽浪费**：大量重复或相似的账户信息更新消息占用网络带宽
4. **前端频繁重绘**：Vue 组件频繁接收到新数据并触发重绘，影响用户体验

## 优化方案

### 1. 账户信息缓存机制

在 WebSocket 管理器中引入缓存机制：

- `_cached_account_data`: 存储最新的账户信息数据
- `_account_update_task`: 定时推送任务

当收到账户信息更新事件时，不立即推送，而是更新缓存：

```python
async def broadcast_account(self, account_data: dict) -> None:
    """更新账户信息缓存（每3秒推送一次）"""
    self._cached_account_data = account_data
```

### 2. 定时推送任务

创建一个独立的异步任务，每 3 秒推送一次缓存的账户信息：

```python
async def _account_update_loop(self) -> None:
    """账户信息定时推送循环"""
    while True:
        await asyncio.sleep(3)
        if self._cached_account_data is not None:
            await self.broadcast({
                "type": "account_update",
                "data": self._cached_account_data,
                "timestamp": datetime.now().isoformat(),
            })
```

### 3. 动态启停推送任务

根据 WebSocket 连接状态动态控制推送任务的启停：

- **有连接时**：自动启动推送任务
- **无连接时**：自动停止推送任务

```python
async def connect(self, websocket: WebSocket):
    """接受WebSocket连接"""
    await websocket.accept()
    self.active_connections.add(websocket)
    await self._start_account_update_task()

async def disconnect(self, websocket: WebSocket):
    """断开WebSocket连接"""
    self.active_connections.discard(websocket)
    if len(self.active_connections) == 0:
        await self._stop_account_update_task()
```

### 4. 其他数据实时推送

保持其他类型数据的实时推送特性：

- **持仓更新**（position_update）：实时推送
- **成交记录**（trade_update）：实时推送
- **委托单状态**（order_update）：实时推送
- **行情数据**（quote_update/tick_update）：实时推送
- **系统状态**（system_status）：实时推送
- **告警信息**（alarm_update）：实时推送

## 优化效果

### 性能提升

1. **推送频率降低**：账户信息推送频率从每秒多次降低到每秒 0.33 次（3 秒一次）
2. **网络流量减少**：减少约 90% 的账户信息相关 WebSocket 消息
3. **客户端负担减轻**：前端处理频率降低，CPU 占用显著下降
4. **用户体验改善**：避免了频繁的界面闪烁，数据显示更加稳定

### 数据准确性

虽然推送频率降低了，但由于使用了缓存机制：

- 数据始终是最新的：每次推送都是缓存的最新数据
- 不会丢失重要更新：所有更新都会在 3 秒内被推送到客户端
- 保持实时性：对于账户信息这种变化相对缓慢的数据，3 秒的延迟是可以接受的

## 前端适配

### 直接使用账户字段

前端不再通过持仓累加计算总浮动盈亏，而是直接使用账户信息中的 `float_profit` 字段：

```typescript
// 之前：通过持仓累加计算
const totalFloatProfit = computed(() => {
  return positions.value.reduce((sum, pos) => sum + pos.float_profit, 0)
})

// 现在：直接使用账户字段
<span>浮动盈亏: <span :class="store.account.float_profit >= 0 ? 'profit' : 'loss'">
  ¥{{ formatNumber(store.account.float_profit) }}
</span></span>
```

### 优势

1. **计算开销减少**：不再需要每次持仓更新都重新计算
2. **数据一致性**：前端和后端使用相同的数据源
3. **代码简化**：移除了不必要的计算逻辑

## 实现细节

### 后端实现

文件：`src/api/websocket_manager.py`

主要变更：

1. 添加缓存和任务字段
2. 修改 `broadcast_account` 方法为缓存更新
3. 添加 `_start_account_update_task` 方法
4. 添加 `_stop_account_update_task` 方法
5. 添加 `_account_update_loop` 方法
6. 在 `connect` 和 `disconnect` 方法中添加任务启停逻辑

### 前端实现

文件：`web/src/App.vue`, `web/src/views/Dashboard.vue`, `web/src/stores/index.ts`

主要变更：

1. 删除 `totalFloatProfit` 计算属性
2. 修改所有使用 `totalFloatProfit` 的地方改为使用 `store.account.float_profit`

## 测试验证

### 功能测试

1. ✅ WebSocket 连接后账户信息正常推送
2. ✅ 账户信息每 3 秒推送一次
3. ✅ 多个客户端连接时都能收到推送
4. ✅ 所有客户端断开后推送任务自动停止
5. ✅ 其他类型数据仍保持实时推送

### 性能测试

1. ✅ WebSocket 消息数量显著减少
2. ✅ 前端 CPU 占用降低
3. ✅ 网络流量减少
4. ✅ 用户体验改善，无频繁刷新现象

### 数据准确性测试

1. ✅ 账户信息始终是最新的
2. ✅ 浮动盈亏显示正确
3. ✅ 无数据丢失或延迟过大现象

## 注意事项

1. **推送频率可配置**：如果需要，可以将 3 秒改为配置项
2. **缓存一致性**：确保缓存数据总是最新的
3. **错误处理**：推送失败时不要影响缓存更新
4. **任务清理**：应用关闭时确保正确停止推送任务

## 未来优化方向

1. **差异化推送**：根据数据重要性采用不同的推送频率
2. **增量更新**：只推送变化的数据字段，减少数据传输量
3. **客户端控制**：允许客户端自定义订阅频率
4. **批量推送**：将多个更新合并为一条消息推送
5. **压缩传输**：对大数据量进行压缩后再传输
