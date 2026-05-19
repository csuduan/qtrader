# AppContext 全局单例优化方案

> 关联问题: code_review_2025-05-18.md #4
> 优先级: P1

---

## 一、当前问题诊断

### 使用模式统计

- **25个文件**直接 `ctx = get_app_context()`（模块级导入时初始化）
- **28处**调用 `ctx.get_xxx()` / `ctx.set()` / `ctx.register()`
- 两类使用场景：
  1. **启动时注册**: `app.py`, `trader.py`, `manager.py` 在初始化时 `register` 组件
  2. **运行时获取**: Gateway、StrategyManager、API routes、JobManager 等运行时从全局容器取依赖

### 最严重的问题

1. **模块级变量在导入时即绑定** — `ctx = get_app_context()` 在 Python 导入模块时就执行，测试时无法替换

2. **ctp_api.py 模块级导入依赖** — 第36-48行在模块导入时就 `ctx.get_config()` 读取配置来决定导入哪个 pyctp 模块（rohon/jees/ctp）。这意味着：
   - 测试时必须先初始化 AppContext 才能导入这个模块
   - 无法同时测试多个 broker 类型
   - 循环导入风险

3. **隐式依赖链** — 组件不声明自己需要什么，运行时从全局"抓"，导致：
   - 无法静态分析依赖关系
   - 单元测试必须搭完整环境
   - 组件初始化顺序隐含在代码执行顺序中

---

## 二、优化策略：渐进式改造

目标：**从"全局服务定位器"模式 → "依赖注入 + 显式传参"模式**

分三个阶段，每阶段独立可交付。

---

## 三、阶段一：消除模块级 ctx 绑定（最小改动，立即可做）

**核心改动**：把 `ctx = get_app_context()` 从模块顶部移到函数内部。

### 3.1 base_gateway.py

**改造前**:
```python
ctx = get_app_context()

class BaseGateway(ABC):
    def __init__(self):
        self._event_engine: AsyncEventEngine | None = ctx.get_event_engine()
```

**改造后**:
```python
class BaseGateway(ABC):
    def __init__(self, event_engine: AsyncEventEngine | None = None):
        self._event_engine: AsyncEventEngine | None = event_engine
        if self._event_engine is None:
            from src.app_context import get_app_context
            self._event_engine = get_app_context().get_event_engine()
```

### 3.2 ctp_api.py（最棘手）

**改造前**:
```python
ctx = get_app_context()
config: TraderConfig = ctx.get_config()
logger = get_logger(__name__)

ctp_type = config.gateway.broker.type
if ctp_type == "rohon":
    from pyctp.rohon import mdapi, tdapi
elif ctp_type == "jees":
    from pyctp.jees import mdapi, tdapi
else:
    from pyctp.ctp import mdapi, tdapi
```

**改造后**:
```python
logger = get_logger(__name__)

# 延迟导入的CTP API缓存
_ctp_apis: dict[str, tuple] = {}

def _get_ctp_apis(config: TraderConfig):
    """根据配置延迟导入对应的CTP API模块"""
    ctp_type = config.gateway.broker.type
    if ctp_type not in _ctp_apis:
        if ctp_type == "rohon":
            from pyctp.rohon import mdapi, tdapi
        elif ctp_type == "jees":
            from pyctp.jees import mdapi, tdapi
        else:
            from pyctp.ctp import mdapi, tdapi
        _ctp_apis[ctp_type] = (mdapi, tdapi)
    return _ctp_apis[ctp_type]

# 后续在 CtpMdApi / CtpTdApi 的 __init__ 中:
# mdapi, tdapi = _get_ctp_apis(config)
```

### 3.3 tq_gateway.py

**改造前**:
```python
ctx = get_app_context()

class TqGateway(BaseGateway):
    def __init__(self, config: GatewayConfig):
        super().__init__()
        self.event_engine = ctx.get_event_engine()
```

**改造后**:
```python
class TqGateway(BaseGateway):
    def __init__(self, config: GatewayConfig, event_engine: AsyncEventEngine | None = None):
        super().__init__(event_engine)
```

### 3.4 strategy_manager.py

**改造前**:
```python
ctx = get_app_context()

class StrategyManager:
    def __init__(self, strategies_config: dict[str, StrategyConfig], trading_engine: TradingEngine):
        self.trading_engine = trading_engine
        # ... 后续使用 ctx.get_event_engine()
```

**改造后**:
```python
class StrategyManager:
    def __init__(
        self,
        strategies_config: dict[str, StrategyConfig],
        trading_engine: TradingEngine,
        event_engine: AsyncEventEngine | None = None,
    ):
        self.trading_engine = trading_engine
        self.event_engine = event_engine
        if self.event_engine is None:
            from src.app_context import get_app_context
            self.event_engine = get_app_context().get_event_engine()
```

### 3.5 阶段一改造清单

| 文件 | 改动内容 | 工作量 |
|------|---------|--------|
| src/trader/gateway/base_gateway.py | 移除模块级ctx，__init__接收event_engine | 10分钟 |
| src/trader/gateway/ctp_api.py | 延迟导入pyctp模块 | 20分钟 |
| src/trader/gateway/ctp_gateway.py | 移除模块级ctx | 5分钟 |
| src/trader/gateway/tq_gateway.py | 移除模块级ctx | 5分钟 |
| src/trader/strategy_manager.py | 移除模块级ctx，构造函数注入event_engine | 10分钟 |

---

## 四、阶段二：核心组件构造函数注入（中等改动）

**目标**：TradingEngine、StrategyManager、Gateway 等核心类不再从全局容器取依赖，而是显式接收。

### 4.1 TradingEngine 改造

**改造前**:
```python
class TradingEngine:
    def __init__(self, account_config: TraderConfig):
        self.config = account_config
        self.event_engine = ctx.get_event_engine()  # 从全局取
```

**改造后**:
```python
class TradingEngine:
    def __init__(
        self,
        account_config: TraderConfig,
        event_engine: AsyncEventEngine,
        risk_control: RiskControl | None = None,
    ):
        self.config = account_config
        self.event_engine = event_engine
        self.risk_control = risk_control or RiskControl(account_config.risk_control)
```

### 4.2 Trader 作为依赖组装器

保留 Trader 作为组装器角色，但组件各自接收依赖：

```python
# app.py 或 trader.py 中的启动代码
async def main_async(args):
    config = get_config_loader().load_trader_config(account_id)
    
    # 创建基础设施
    event_engine = AsyncEventEngine(name=f"Trader-{account_id}")
    event_engine.start()
    
    # 创建组件（显式传递依赖）
    trading_engine = TradingEngine(config, event_engine)
    await trading_engine.start()
    
    switch_mgr = SwitchPosManager(config, trading_engine)
    switch_mgr.start()
    
    strategy_manager = StrategyManager(
        config.strategies, 
        trading_engine,
        event_engine=event_engine,
    )
    await strategy_manager.start()
    
    # Trader 只是协调者
    trader = Trader(
        config=config,
        event_engine=event_engine,
        trading_engine=trading_engine,
        switchPos_manager=switch_mgr,
        strategy_manager=strategy_manager,
    )
```

### 4.3 阶段二改造清单

| 文件 | 改动内容 | 工作量 |
|------|---------|--------|
| src/trader/trading_engine.py | 构造函数接收event_engine和risk_control | 15分钟 |
| src/trader/trader.py | 改为组装器模式，接收已创建的组件 | 30分钟 |
| src/trader/app.py | 调整启动顺序，显式创建并传递依赖 | 20分钟 |
| src/manager/manager.py | TradingManager构造函数注入 | 20分钟 |
| src/manager/app.py | 调整启动顺序，显式创建并传递依赖 | 20分钟 |

---

## 五、阶段三：FastAPI 依赖注入 + 完全移除 AppContext（长期目标）

### 5.1 API Routes 改造

**改造前**:
```python
# src/manager/api/routes/account.py
ctx = get_app_context()

@router.get("/accounts")
async def get_accounts():
    manager = ctx.get_trading_manager()
    ...
```

**改造后**:
```python
# src/manager/api/dependencies.py
from fastapi import Request

def get_trading_manager(request: Request) -> TradingManager:
    return request.app.state.trading_manager

def get_alarm_service(request: Request) -> AlarmService:
    return request.app.state.alarm_service

# src/manager/api/routes/account.py
from src.manager.api.dependencies import get_trading_manager

@router.get("/accounts")
async def get_accounts(manager: TradingManager = Depends(get_trading_manager)):
    ...
```

### 5.2 WebSocketManager 改造

**改造前**:
```python
ctx = get_app_context()

class WebSocketManager:
    def start(self):
        event_engine = ctx.get(AppContext.KEY_EVENT_ENGINE)
        event_engine.register(...)
```

**改造后**:
```python
class WebSocketManager:
    def __init__(self, event_engine: AsyncEventEngine):
        self.event_engine = event_engine
    
    def start(self):
        self.event_engine.register(EventTypes.POSITION_UPDATE, self.broadcast_position)
```

### 5.3 阶段三改造清单

| 文件 | 改动内容 | 工作量 |
|------|---------|--------|
| src/manager/api/dependencies.py | 创建FastAPI依赖函数 | 20分钟 |
| src/manager/api/routes/*.py | 全部改为Depends注入 | 1小时 |
| src/manager/api/websocket_manager.py | 构造函数接收event_engine | 10分钟 |
| src/app_context.py | 标记为废弃，或完全删除 | 10分钟 |

---

## 六、改造优先级建议

| 阶段 | 改动范围 | 工作量 | 收益 |
|------|---------|--------|------|
| **阶段一** | 消除模块级 `ctx` 绑定，ctp_api 延迟导入 | 1-2小时 | 测试可mock，消除导入时副作用 |
| **阶段二** | Gateway/StrategyManager/TradingEngine 构造函数注入 | 半天 | 组件可独立测试，依赖显式 |
| **阶段三** | API routes 用 FastAPI Depends，移除 AppContext | 半天 | 完全解耦，符合FastAPI最佳实践 |

---

## 七、测试策略

每阶段改造后应验证：

1. **单元测试**: `pytest tests/unit/ -v` 应全部通过
2. **集成测试**: `pytest tests/ -v` 应全部通过
3. **启动测试**: 
   - Manager启动: `python run_manager.py`
   - Trader启动: `python run_trader.py --account-id test`
4. **功能测试**: 
   - WebSocket连接正常
   - API接口响应正常
   - 下单/撤单流程正常

---

## 八、回滚预案

每个阶段独立提交，使用独立分支：

```bash
git checkout -b refactor/app-context-phase1
git checkout -b refactor/app-context-phase2
git checkout -b refactor/app-context-phase3
```

如发现问题可快速回滚到上一阶段：

```bash
git checkout main
```
