# 换仓功能测试计划

## 测试环境

- 前端地址: http://localhost:3004
- 后端地址: http://localhost:8000
- 测试页面: /rotation (换仓指令管理)

## 功能概述

换仓功能允许用户管理期货合约的换仓指令，包括：
- 创建换仓指令
- 导入CSV批量导入
- 启动/停止换仓流程
- 批量删除指令
- 清除已完成指令

## 测试场景

### 1. 页面加载测试

**步骤:**
1. 导航到 http://localhost:3004/rotation
2. 验证页面元素加载正确

**预期结果:**
- 页面标题显示 "换仓指令管理"
- 显示操作按钮: 开始换仓、删除选中、清除已完成、导入CSV、刷新
- 显示数据表格，包含以下列:
  - 选择框
  - 策略编号
  - 合约
  - 方向 (买/卖)
  - 开平 (开仓/平仓/平今)
  - 手数
  - 进度
  - 信息
  - 报单时间
  - 启用开关
  - 更新时间
  - 来源

### 2. API 端点测试

#### 2.1 获取换仓指令列表

**请求:**
```
GET /api/rotation
```

**预期响应:**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "instructions": [],
    "rotation_status": {
      "working": false,
      "is_manual": false
    }
  }
}
```

#### 2.2 创建换仓指令

**请求:**
```
POST /api/rotation
Content-Type: application/json

{
  "account_id": "DQ",
  "strategy_id": "StrategyTest",
  "symbol": "rb2505",
  "exchange_id": "SHFE",
  "direction": "BUY",
  "offset": "OPEN",
  "volume": 10,
  "price": 3500.0,
  "order_time": "09:30:00",
  "enabled": true
}
```

**预期响应:**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "account_id": "DQ",
    "strategy_id": "StrategyTest",
    "symbol": "rb2505",
    "direction": "BUY",
    "offset": "OPEN",
    "volume": 10,
    "remaining_volume": 10,
    "status": "PENDING",
    "enabled": true,
    ...
  }
}
```

#### 2.3 启动换仓流程

**请求:**
```
POST /api/rotation/start
Content-Type: application/json

{
  "account_id": "DQ"
}
```

**预期响应:**
```json
{
  "code": 0,
  "message": "success",
  "data": null
}
```

#### 2.4 批量删除指令

**请求:**
```
POST /api/rotation/batch/delete
Content-Type: application/json

{
  "ids": [1, 2, 3],
  "account_id": "DQ"
}
```

**预期响应:**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "deleted": 3
  }
}
```

#### 2.5 导入CSV

**请求:**
```
POST /api/rotation/import
Content-Type: multipart/form-data

file: <CSV文件>
mode: replace (或 append)
```

**CSV格式示例:**
```
账户编号,策略编号,合约,开平,方向,手数,报单时间
DQ,StrategyFix_PK,PK603.CZC,Close,Sell,2,09:05:00
DQ,StrategyFix_RM,RM605.CZC,Close,Sell,4,
DQ,StrategyFix_JD,JD2603.DCE,Open,Sell,1,09:05:00
```

**预期响应:**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "imported": 3,
    "failed": 0,
    "errors": []
  }
}
```

### 3. 前端交互测试

#### 3.1 创建新指令

**步骤:**
1. 点击"导入CSV"按钮或直接在表格中操作
2. 填写表单字段
3. 点击"确认导入"或"创建"

**验证点:**
- 表单验证: 必填字段检查
- 成功后显示成功消息
- 数据自动刷新

#### 3.2 启用/禁用指令

**步骤:**
1. 找到表格中的"启用"列
2. 切换开关

**验证点:**
- 开关状态切换
- API调用成功
- 状态保存

#### 3.3 批量选择和删除

**步骤:**
1. 勾选多个指令
2. 点击"删除选中"按钮
3. 确认删除

**验证点:**
- 确认对话框显示
- 删除成功消息
- 数据刷新

#### 3.4 启动换仓流程

**步骤:**
1. 点击"开始换仓"按钮
2. 确认操作

**验证点:**
- 确认对话框显示
- 换仓状态标签显示"换仓中"
- 按钮状态变为禁用

### 4. 边界情况测试

#### 4.1 无数据状态
- 验证空数据时显示"暂无换仓指令"

#### 4.2 网络错误
- 验证API调用失败时的错误处理
- 验证错误消息显示

#### 4.3 并发操作
- 验证换仓进行中时其他操作被禁用

### 5. 性能测试

#### 5.1 大数据量
- 测试100+条指令的加载和渲染性能

#### 5.2 CSV导入
- 测试大文件导入性能
- 测试导入进度显示

## 自动化测试脚本

### 使用 Playwright 进行自动化测试

```javascript
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  // 导航到换仓页面
  await page.goto('http://localhost:3004/rotation');

  // 等待页面加载
  await page.waitForLoadState('networkidle');

  // 截图
  await page.screenshot({ path: 'rotation-page.png' });

  // 测试创建指令
  await page.click('button:has-text("导入CSV")');
  await page.waitForSelector('.el-dialog');

  // 测试刷新功能
  await page.click('button:has-text("刷新")');
  await page.waitForLoadState('networkidle');

  // 检查控制台错误
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log('Page error:', msg.text());
    }
  });

  await browser.close();
})();
```

## 测试检查清单

- [ ] 页面正常加载
- [ ] 数据表格正确显示
- [ ] 创建指令功能正常
- [ ] 导入CSV功能正常
- [ ] 启用/禁用开关正常
- [ ] 批量删除功能正常
- [ ] 清除已完成功能正常
- [ ] 启动换仓功能正常
- [ ] 错误处理正确
- [ ] 无控制台错误
- [ ] 响应式布局正常

## 已知问题和限制

1. 后端需要正确配置才能运行
2. 需要有效的账户配置
3. CSV导入需要正确的编码格式 (GBK)

## 测试结果模板

| 测试项 | 状态 | 备注 |
|--------|------|------|
| 页面加载 | ⬜ 未测试 | |
| 创建指令 | ⬜ 未测试 | |
| CSV导入 | ⬜ 未测试 | |
| 批量删除 | ⬜ 未测试 | |
| 启动换仓 | ⬜ 未测试 | |
