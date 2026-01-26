# Chrome DevTools 快速测试指南

## 🚀 快速开始

### 1. 打开浏览器并访问前端
```bash
# 前端地址
http://localhost:3000
```

### 2. 打开 Chrome DevTools
- **Windows/Linux**: `F12` 或 `Ctrl + Shift + I`
- **macOS**: `Cmd + Option + I`

---

## 📊 测试检查清单

### Dashboard 页面 (/dashboard)
- [ ] 账户概览卡片显示（总资产、可用资金、持仓数量、活跃委托）
- [ ] 盈亏统计显示（浮动盈亏、平仓盈亏）
- [ ] 风控进度条显示（今日报单/撤单）
- [ ] 告警统计卡片显示
- [ ] 最近成交表格显示

### Account 页面 (/account)
- [ ] 标签页切换正常（账户信息、账户交易、成交记录）
- [ ] 持仓列表显示
- [ ] 行情订阅列表显示
- [ ] 委托单列表显示（挂单、已成交、废单）
- [ ] 成交记录列表显示

### Rotation 页面 (/rotation)
- [ ] 换仓指令表格显示
- [ ] 换仓状态标签显示（手动/自动）
- [ ] 操作按钮显示（开始换仓、导入CSV等）

### System 页面 (/system)
- [ ] 系统状态显示（连接状态、交易状态）
- [ ] 连接控制按钮显示（连接/断开）
- [ ] 风控参数配置表单显示
- [ ] 定时任务列表显示

### Alarms 页面 (/alarms)
- [ ] 告警统计卡片显示
- [ ] 状态筛选器显示（未处理/已处理/全部）
- [ ] 告警列表表格显示

---

## 🔍 DevTools 测试技巧

### Console 测试

#### 快速健康检查
```javascript
// 检查 Vue 应用是否加载
console.log('Vue:', window.Vue ? '✓' : '✗')

// 检查 Element Plus 是否加载
console.log('Element Plus:', window.ElementPlus ? '✓' : '✗')

// 检查 Router 是否可用
console.log('Router:', window.$router ? '✓' : '✗')

// 检查 Pinia 是否可用
console.log('Pinia:', window.$pinia ? '✓' : '✗')
```

#### 检查当前路由
```javascript
// 当前路由路径
console.log('Current path:', window.location.pathname)

// 当前路由信息（如果 $router 可用）
console.log('Route:', window.$router?.currentRoute?.value)
```

#### 测试API连通性
```javascript
// 测试账户API
fetch('/api/account')
  .then(r => r.json())
  .then(data => console.log('Account:', data))
  .catch(e => console.error('Error:', e))

// 测试系统状态API
fetch('/api/system/status')
  .then(r => r.json())
  .then(data => console.log('System Status:', data))
  .catch(e => console.error('Error:', e))

// 测试告警统计API
fetch('/api/alarm/stats')
  .then(r => r.json())
  .then(data => console.log('Alarm Stats:', data))
  .catch(e => console.error('Error:', e))
```

#### 检查WebSocket连接
```javascript
// 在 Network 标签中查看 WS 连接
// 或者在 Console 中执行
console.log('WebSocket 连接状态: 待验证（查看 Network > WS 标签）')
```

### Network 标签测试

#### 监控API请求
1. 打开 **Network** 标签
2. 筛选 **Fetch/XHR** 请求
3. 刷新页面或执行操作
4. 查看请求和响应

#### 检查API响应格式
所有成功响应应该符合以下格式：
```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

#### 常见API端点
- `GET /api/account` - 获取账户信息
- `GET /api/positions` - 获取持仓列表
- `GET /api/orders?status=ALIVE` - 获取活跃委托
- `GET /api/trades` - 获取成交记录
- `GET /api/system/status` - 获取系统状态
- `GET /api/alarm/stats` - 获取告警统计

### Elements 标签测试

#### 检查关键元素
```javascript
// 检查根元素
document.querySelector('#app')

// 检查统计卡片
document.querySelectorAll('.el-statistic')

// 检查表格
document.querySelectorAll('.el-table')

// 检查按钮
document.querySelectorAll('button')
```

### Application 标签测试

#### 检查本地存储
```javascript
// 查看 localStorage
console.log('LocalStorage keys:', Object.keys(localStorage))
for (let key in localStorage) {
  console.log(key, localStorage[key])
}

// 查看 sessionStorage
console.log('SessionStorage keys:', Object.keys(sessionStorage))
```

---

## 🧪 快速测试脚本

在 Console 中执行以下脚本进行快速验证：

```javascript
(function() {
  console.log('=== Q-Trader 快速测试 ===\n')

  // 1. 环境检查
  console.log('1. 环境检查:')
  console.log('  Vue:', window.Vue ? '✓' : '✗')
  console.log('  Element Plus:', window.ElementPlus ? '✓' : '✗')
  console.log('  Router:', window.$router ? '✓' : '✗')
  console.log('  Pinia:', window.$pinia ? '✓' : '✗')

  // 2. DOM 检查
  console.log('\n2. DOM 检查:')
  console.log('  #app:', document.querySelector('#app') ? '✓' : '✗')
  console.log('  .el-container:', document.querySelector('.el-container') ? '✓' : '✗')
  console.log('  nav:', document.querySelector('nav') ? '✓' : '✗')

  // 3. 组件检查
  console.log('\n3. 组件检查:')
  console.log('  统计卡片:', document.querySelectorAll('.el-statistic').length, '个')
  console.log('  表格:', document.querySelectorAll('.el-table').length, '个')
  console.log('  按钮:', document.querySelectorAll('button').length, '个')

  // 4. 路由检查
  console.log('\n4. 路由检查:')
  console.log('  当前路径:', window.location.pathname)

  // 5. Network 请求提示
  console.log('\n5. Network 检查:')
  console.log('  请在 Network 标签中查看 API 请求')
  console.log('  筛选 Fetch/XHR，查看请求状态和响应')

  console.log('\n=== 测试完成 ===')
  console.log('📝 提示: 详细测试请查看 CHROME_DEVTOOLS_TEST_GUIDE.md')
})();
```

---

## 🎯 常见问题排查

### 问题 1: 页面白屏或加载失败
**检查项**:
1. Console 是否有错误信息
2. Network 标签中是否有失败的请求
3. 前端和后端服务是否正常运行

### 问题 2: API 请求 404 或连接失败
**检查项**:
1. 后端服务是否运行在 8000 端口
2. vite.config.ts 中的代理配置是否正确
3. 浏览器网络是否正常

### 问题 3: 数据不更新
**检查项**:
1. WebSocket 是否连接（查看 Network > WS 标签）
2. Pinia store 是否正确更新
3. Console 中是否有更新逻辑错误

### 问题 4: 样式显示异常
**检查项**:
1. Elements 标签中查看 CSS 样式
2. Element Plus 组件是否正确加载
3. 浏览器兼容性问题

---

## 📚 相关文档

- **详细测试指南**: `/web/CHROME_DEVTOOLS_TEST_GUIDE.md`
- **自动化测试脚本**: `/test_frontend.py`
- **测试报告**: `/TEST_REPORT.md`

---

## 🔗 有用的快捷键

| 快捷键 | 功能 |
|--------|------|
| `F12` / `Cmd+Option+I` | 打开/关闭 DevTools |
| `Ctrl+Shift+C` / `Cmd+Shift+C` | 选择元素 |
| `Ctrl+Shift+J` / `Cmd+Option+J` | 聚焦 Console |
| `Ctrl+R` | 刷新页面 |
| `Ctrl+Shift+R` | 强制刷新（清除缓存） |
| `Ctrl+Shift+I` | 打开设备模拟器 |
| `Ctrl+Shift+M` | 切换设备模式 |
