# Q-Trader 前端功能测试指南

使用 Chrome DevTools 验证前端各个页面的功能是否正常。

## 前置条件

- 前端服务运行在 `http://localhost:3000`
- 后端服务运行在 `http://localhost:8000`

---

## 1. Dashboard（总览）页面测试

**访问路径**: `http://localhost:3000/dashboard`

### 功能验证清单

| 功能点 | 验证步骤 | Chrome DevTools 检查项 |
|--------|----------|------------------------|
| **账户概览卡片** | 1. 打开页面，检查是否显示总资产、可用资金、持仓数量、活跃委托 | - Console 无错误<br>- Network 查看 `/api/account` 请求状态 |
| **盈亏统计** | 1. 检查浮动盈亏和平仓盈亏是否正确显示颜色（绿色/红色） | - 验证数值格式正确<br>- 颜色类名 `.profit` / `.loss` 正确应用 |
| **风控进度条** | 1. 检查今日报单/撤单进度条颜色是否根据百分比变化 | - 百分比 < 60%: 绿色<br>- 60%-80%: 橙色<br>- > 80%: 红色 |
| **告警统计** | 1. 检查告警数量是否正确显示 | - Network 查看 `/api/alarm/stats` 请求 |
| **最近成交表格** | 1. 检查表格显示最近5条成交记录 | - 表格数据完整<br>- 日期时间格式正确 |

### DevTools 测试步骤

```javascript
// Console 中执行，验证数据是否正确加载
console.log('Account:', store.account)
console.log('Positions:', store.positions)
console.log('Orders:', store.orders)
console.log('Trades:', store.trades)
```

---

## 2. Account（账户）页面测试

**访问路径**: `http://localhost:3000/account`

### 2.1 账户信息标签页

| 功能点 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **账户信息展示** | 1. 检查账户ID、券商、币种、风险率等信息 | - Network 查看 `/api/account` |
| **持仓列表** | 1. 检查持仓表格显示 | - 多头/空头持仓正确<br>- 开仓价、保证金、浮动盈亏正确 |
| **平仓操作** | 1. 点击"平多"或"平空"按钮<br>2. 确认平仓对话框信息正确 | - Network 查看 POST `/api/position/close` |

### 2.2 账户交易标签页

| 功能点 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **行情订阅** | 1. 检查订阅行情列表<br>2. 点击"订阅"按钮添加新合约 | - Network 查看 `/api/quote`<br>- WebSocket 检查 tick 消息 |
| **挂单/已成交/废单切换** | 1. 切换订单状态标签<br>2. 验证表格数据变化 | - Network 查看 `/api/orders?status=` |
| **报单功能** | 1. 点击"报单"按钮<br>2. 填写合约代码、方向、开平、手数<br>3. 确认对话框信息正确 | - Network 查看 POST `/api/order` |
| **撤单功能** | 1. 在挂单列表点击"撤单"<br>2. 确认撤单对话框 | - Network 查看 DELETE `/api/order/{order_id}` |

### 2.3 成交记录标签页

| 功能点 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **日期筛选** | 1. 选择日期<br>2. 点击刷新 | - Network 查看 `/api/trades?date=` |
| **成交列表** | 1. 检查成交记录显示 | - 成交ID、合约、方向、价格、手数正确 |

### DevTools 测试步骤

```javascript
// Console - 检查 WebSocket 连接
wsManager.connected.value  // 应该返回 true

// Console - 检查当前状态
store.activeTab  // 当前标签页
store.orderTab   // 订单标签状态
```

---

## 3. Rotation（换仓）页面测试

**访问路径**: `http://localhost:3000/rotation`

### 功能验证清单

| 功能点 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **换仓指令列表** | 1. 检查指令表格显示 | - Network 查看 `/api/rotation/instructions` |
| **换仓状态标签** | 1. 检查"手动换仓中"/"自动换仓中"标签显示 | - 标签颜色和文案正确 |
| **开始换仓** | 1. 点击"开始换仓"按钮<br>2. 确认对话框 | - Network 查看 POST `/api/rotation/start` |
| **批量删除** | 1. 勾选多条指令<br>2. 点击"删除选中" | - Network 查看 DELETE `/api/rotation/batch` |
| **清除已完成** | 1. 点击"清除已完成"按钮 | - Network 查看 DELETE `/api/rotation/clear?status=COMPLETED` |
| **启用/禁用开关** | 1. 切换指令的启用开关 | - Network 查看 PATCH `/api/rotation/instructions/{id}` |
| **导入CSV** | 1. 点击"导入CSV"<br>2. 上传文件<br>3. 查看预览 | - Network 查看 POST `/api/rotation/import`<br>- FormData 正确发送 |

### DevTools 测试步骤

```javascript
// Console - 检查换仓状态
rotationStatus.working     // 是否正在换仓
rotationStatus.is_manual   // 是否手动换仓
```

---

## 4. System（系统）页面测试

**访问路径**: `http://localhost:3000/system`

### 功能验证清单

| 功能点 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **系统状态显示** | 1. 检查连接状态、交易状态标签 | - 颜色正确（已连接=绿色，未连接=红色） |
| **连接系统** | 1. 点击"连接系统"按钮<br>2. 输入用户名密码<br>3. 确认连接 | - Network 查看 POST `/api/system/connect`<br>- WebSocket 重新连接 |
| **断开连接** | 1. 点击"断开连接"按钮<br>2. 确认对话框 | - Network 查看 POST `/api/system/disconnect` |
| **暂停/恢复交易** | 1. 点击"暂停交易"或"恢复交易" | - Network 查看 POST `/api/system/pause` 或 `/resume` |
| **风控参数配置** | 1. 修改风控参数<br>2. 点击"保存配置" | - Network 查看 PUT `/api/system/risk-control` |
| **定时任务列表** | 1. 检查任务列表显示 | - Network 查看 `/api/system/scheduled-tasks` |
| **暂停/恢复/触发任务** | 1. 点击对应操作按钮 | - Network 查看 POST `/api/jobs/{job_id}/operate` |

### DevTools 测试步骤

```javascript
// Console - 检查系统状态
store.systemStatus.connected  // 连接状态
store.systemStatus.paused     // 暂停状态
```

---

## 5. Alarm（告警）页面测试

**访问路径**: `http://localhost:3000/alarms`

### 功能验证清单

| 功能点 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **告警统计** | 1. 检查四个统计卡片数据 | - Network 查看 `/api/alarm/stats` |
| **状态筛选** | 1. 切换"未处理"/"已处理"/"全部"<br>2. 验证表格数据变化 | - Network 查看 `/api/alarm/today?status=` |
| **告警列表** | 1. 检查表格显示 | - ID、时间、来源、标题、详情、状态正确 |
| **标记已处理** | 1. 点击"标记已处理"按钮 | - Network 查看 POST `/api/alarm/{id}/confirm` |
| **定时刷新统计** | 1. 等待30秒<br>2. 验证统计数据自动更新 | - Network 每隔30秒有新请求 |

### DevTools 测试步骤

```javascript
// Console - 检告警数据
alarms          // 告警列表
stats           // 统计数据
statusFilter    // 当前筛选状态
```

---

## 全局功能测试

### WebSocket 实时数据

| 测试项 | 验证步骤 | DevTools 检查项 |
|--------|----------|-----------------|
| **WebSocket 连接** | 1. 打开 DevTools > WS 标签<br>2. 查看 ws://localhost:3000/ws 连接 | - 连接状态为 101 Switching Protocols |
| **实时消息接收** | 1. 观察接收到的消息帧 | - account, position, order, trade, tick 消息 |
| **断线重连** | 1. 模拟网络断开<br>2. 恢复网络 | - 自动重新连接成功 |

### Console 错误检查

```javascript
// Console 执行 - 清空并监控
console.clear()
// 执行各种操作，观察是否有错误
```

**预期**: Console 应该无红色错误信息（允许部分警告）

### Network 请求验证

所有 API 请求应该:
- 状态码为 2xx（成功）或合理的错误响应
- 请求头包含正确的认证信息
- 响应时间合理（< 1s）

---

## 快速测试脚本

在 DevTools Console 中执行以下代码进行快速验证:

```javascript
// 快速健康检查
async function quickHealthCheck() {
  const checks = {
    dashboard: 'Dashboard 页面加载',
    account: 'Account 页面数据',
    rotation: 'Rotation 指令列表',
    system: 'System 状态',
    alarms: 'Alarm 告警列表'
  }

  console.log('=== 开始健康检查 ===')

  // 检查 store 数据
  if (store.account) console.log('✓ 账户数据已加载')
  else console.warn('✗ 账户数据未加载')

  if (store.positions.length >= 0) console.log('✓ 持仓数据已加载')
  else console.warn('✗ 持仓数据异常')

  if (store.systemStatus) console.log('✓ 系统状态已加载')
  else console.warn('✗ 系统状态未加载')

  // 检查 WebSocket
  if (wsManager.connected.value) console.log('✓ WebSocket 已连接')
  else console.warn('✗ WebSocket 未连接')

  console.log('=== 检查完成 ===')
}

quickHealthCheck()
```

---

## 常见问题排查

### 问题 1: WebSocket 连接失败
**检查**:
- DevTools > Network > WS 标签
- 查看连接错误消息
- 确认后端服务运行在 8000 端口

### 问题 2: API 请求 404
**检查**:
- DevTools > Network
- 确认请求 URL 正确
- 检查 vite.config.ts 代理配置

### 问题 3: 数据不更新
**检查**:
- WebSocket 是否正常接收消息
- Pinia store 是否正确更新
- Console 查看是否有更新逻辑错误

---

## 测试记录模板

| 页面 | 功能点 | 测试结果 | 问题描述 | 测试日期 |
|------|--------|----------|----------|----------|
| Dashboard | 账户概览 | ✓ / ✗ | | |
| Dashboard | 盈亏统计 | ✓ / ✗ | | |
| Account | 账户信息 | ✓ / ✗ | | |
| Account | 报单功能 | ✓ / ✗ | | |
| Rotation | 换仓指令 | ✓ / ✗ | | |
| System | 连接控制 | ✓ / ✗ | | |
| Alarm | 告警列表 | ✓ / ✗ | | |
