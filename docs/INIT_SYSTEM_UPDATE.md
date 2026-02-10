# 系统优化更新说明

## 更新时间
2026-01-18

## 主要变更

### 1. 新增系统参数表
- 创建 `SystemParamPo` 模型（src/models/po.py）
- 支持存储各种系统参数（风控参数、市场参数等）
- 按参数分组管理（risk_control, market, trading 等）

### 2. 系统初始化脚本
- 创建 `src/init_sys.py` 脚本
- 功能：
  - 重建所有数据库表
  - 从 config.yaml 导入定时任务到数据库
  - 从 config.yaml 初始化风控参数到数据库
- 使用方法：`python -m src.init_sys`

### 3. 参数加载器
- 提供从数据库加载风控配置的工具函数
- 支持参数类型转换和默认值处理

### 4. 系统参数API
- 创建 `src/api/routes/system_params.py` 路由
- 提供以下接口：
  - `GET /api/system-params` - 获取所有参数
  - `GET /api/system-params/{param_key}` - 获取单个参数
  - `PUT /api/system-params/{param_key}` - 更新参数
  - `GET /api/system-params/group/{group}` - 按分组获取参数

### 5. 数据库操作增强
- `Database.drop_and_recreate()` 方法（src/database.py）
- 便于系统初始化时重建数据库表

### 6. 交易引擎优化
- TradingEngine 在连接到 TqSdk 后自动从数据库加载风控配置
- 新增 `reload_risk_control_config()` 方法支持运行时重新加载
- 使用数据库参数而非 config.yaml 的风控参数

### 7. 任务调度器优化
- TaskScheduler 只在数据库中不存在任务时才从 config.yaml 创建
- 不再从 config.yaml 覆盖数据库中的现有任务配置
- 始终从数据库加载并执行定时任务

## 行为变化

### 启动流程变化
**之前**：
- 风控参数：使用 config.yaml 中的值
- 定时任务：每次启动从 config.yaml 同步到数据库

**现在**：
- 风控参数：启动时从 `system_params` 表加载
- 定时任务：启动时从 `jobs` 表加载
- config.yaml 仅在数据库缺失记录时作为默认值

### 参数修改方式
**之前**：
- 修改 config.yaml 并重启系统

**现在**：
- 通过 API 修改参数，立即生效（风控参数）
- 或直接修改数据库后重启（定时任务）
- 修改 config.yaml 后需运行 `python -m src.init_sys` 重新初始化

## 部署步骤

### 首次部署或升级
```bash
# 1. 运行系统初始化（重建数据库并导入参数）
python -m src.init_sys

# 2. 启动系统（自动从数据库加载参数）
python -m src.main
```

### 修改风控参数
```bash
# 通过API修改（立即生效）
curl -X PUT http://localhost:8000/api/system-params/risk_control.max_daily_orders \
  -H "Content-Type: application/json" \
  -d '{"param_value": "2000"}'
```

### 修改定时任务
```bash
# 直接修改数据库（需要重启才能生效）
sqlite3 storage/trading.db "UPDATE jobs SET enabled = 0 WHERE job_id = 'pre_market_connect';"

# 或重新初始化系统（会删除所有数据！）
python -m src.init_sys
```

## 注意事项

1. **首次部署必须运行初始化**：`python -m src.init_sys`
2. **config.yaml 不再覆盖数据库**：系统启动时不会用 config.yaml 的值覆盖数据库
3. **参数修改无需重启**：风控参数修改后立即生效，定时任务需要重启
4. **重新初始化会清空数据**：运行 `python -m src.init_sys` 会重建数据库表，清空所有数据
5. **数据库缺失时降级**：如果数据库中没有风控参数，系统会使用 config.yaml 默认值并记录警告

## API 文档

系统参数 API：

```bash
# 获取所有参数
GET /api/system-params

# 获取风控参数组
GET /api/system-params/group/risk_control

# 获取单个参数
GET /api/system-params/risk_control.max_daily_orders

# 更新参数
PUT /api/system-params/risk_control.max_daily_orders
Content-Type: application/json
{
  "param_value": "2000"
}
```

响应格式：
```json
{
  "code": 0,
  "message": "参数更新成功",
  "data": {
    "id": 1,
    "param_key": "risk_control.max_daily_orders",
    "param_value": "2000",
    "param_type": "integer",
    "description": "每日最大报单数量",
    "group": "risk_control",
    "updated_at": "2026-01-18T19:30:00"
  }
}
```
