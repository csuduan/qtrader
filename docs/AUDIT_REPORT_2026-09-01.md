# Q-Trader 项目完整审计报告

> 审计日期：2026-09-01
> 审计范围：后端 ~30,000 行 Python（src/qtrader）+ 前端 ~13,000 行 Vue/TS（web/src）+ tests/ + config/ + 打包配置
> 审计方式：6 个专项并行审计（Trader 核心 / Gateway / Manager·API·IPC / 数据层·基础设施 / 前端 / 测试·配置·安全）+ 实跑 pytest、mypy、npm run build
>
> 注：本报告取代旧版 `AUDIT_REPORT.md`（其中"32 个测试文件/1037 个测试函数"等表述已与现状严重不符，建议删除或标注时效）。

---

## 一、总体评价

**架构设计合理，实现质量堪忧。** Manager-Trader 分离、事件引擎解耦、Gateway 抽象双实现（TqSdk/CTP）、OrderCmd 状态机与执行器分离等设计决策都是对的；前端 Pinia store 集中管理 + ws.ts 150ms 批量 flush 合并高频推送的思路也正确；事件引擎跨线程投递（`call_soon_threadsafe`）实现正确；CTP 断线后通过登录全量查询补偿私有流丢失的机制方向正确。

但存在四个系统性溃点：

1. **安全体系形同虚设** —— 对一套管理真实资金的系统，这是最刺眼的问题（JWT 硬编码密钥、WS 无鉴权、无 RBAC、路径穿越、git 历史含真实凭证）。
2. **测试安全网已破** —— 单元测试实测 405 通过 / 149 失败 / 268 错误 / 3 个模块无法收集；无 CI；最近一次"结算权益周报"改动造成的回归未被任何测试拦截。
3. **接口腐化普遍** —— 多个 API 端点调用不存在的方法（100% 报 500）；IPC 返回不可序列化对象；前后端类型定义大量漂移。
4. **sync/async 与线程边界混乱** —— 跨线程调 TqApi、await 同步函数、事件循环内阻塞 DB IO、loguru sink 在无事件循环线程中 create_task。

### 实跑验证结果

| 验证项 | 结果 |
|--------|------|
| `npm run build`（vue-tsc + vite） | ✅ 通过（唯一警告：主 chunk 超 500kB） |
| `pytest tests/unit` | ❌ 按文档命令无法运行（dev 依赖未声明）；临时注入 pytest 后：405 passed / 149 failed / 268 errors / 3 个模块收集失败 |
| `mypy src/` | ❌ mypy.ini `python_version=3.10` 与项目 3.12 冲突直接中止；修正后 285 errors / 20 files，其中含真实运行时 bug |
| `make test-all` / `make lint` / `make format` | ❌ 干净环境必失败（pytest/mypy/black/isort 均未声明为依赖；test-all 引用不存在的 run_tests.py） |

### 发现统计

| 严重度 | 数量（去重后） |
|--------|------|
| 严重 | 14 |
| 高 | ~27 |
| 中 | ~42 |
| 低 | ~46 |

---

## 二、必须立即处理的安全问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| SEC-1 | **真实天勤凭证硬编码且已进 git 历史** | `tests/test_tq.py:5` | 任何拿到仓库的人可登录该天勤账号；pytest 收集（`testpaths = tests`）时 import 即实例化 `TqApi(web_gui=True)` 连接真实服务器 |
| SEC-2 | **JWT 密钥硬编码 + 无签名 token 回退** | `manager/api/routes/auth.py:24, 54-66, 87-103` | 密钥在源码公开，可签发任意角色 token；部署环境缺 PyJWT 时退化为 base64 无签名 token，验证端只解码不验签 |
| SEC-3 | **WebSocket `/ws` 完全无鉴权**，前端登录前即连接 | `manager/app.py:232-270`、`web/src/main.ts:30-34` | 无需登录即可实时接收全部账户资金/持仓/订单/成交广播；可挂慢连接拖垮广播 |
| SEC-4 | **无 RBAC**：任何角色（含 guest）可下单、批量撤单、一键平仓、停止 Trader、改风控 | `routes/order.py:223`、`manager.py:799`、`routes/account.py:227`、`routes/system.py:63`；`require_admin` 仅用于用户管理接口 | 最低权限账户可操作真实资金 |
| SEC-5 | **日志接口路径穿越** | `routes/log.py:48, 140, 181` | `account_id="../../etc"` 类输入可逃逸日志目录，任意读文件（含 config.yaml 中的券商/邮箱密码） |
| SEC-6 | 密码无盐 SHA256；`init_default_users()` 每次启动用 config.yaml 密码覆盖数据库 admin 密码；代码内默认口令 `admin123` | `auth.py:118-130, 280-322`、`config_loader.py:292-296` | 彩虹表可破；界面改密后重启即还原 |
| SEC-7 | IPC socket 无消息长度上限（对端可声明 4GB 致内存耗尽）、无对端认证、socket 文件权限未收紧（同机任意进程可连上直接发 `order_req` 下单） | `ipc/protocol.py:150-158`、`socket_server.py:260-275` | 本机权限即交易权限 |
| SEC-8 | CORS `allow_origins=["*"]` 与 `allow_credentials=True` 组合无效且危险；AuthMiddleware 未豁免 OPTIONS 预检 | `manager/app.py:185-194`、`middleware/auth.py:67` | 跨域部署时 preflight 一律 401（潜伏）；配置本身危险 |
| SEC-9 | 全局异常处理将内部异常原文（DB 错误、路径、堆栈信息）返回客户端 | `responses.py:112-116` 及大量路由 `error_response(message=str(e))` | 内部实现细节外泄 |
| SEC-10 | 明文凭证落盘：config.yaml（PG 密码、SMTP 授权码、弱 admin 口令）+ 12 个 account-*.yaml（券商/天勤密码）；wecomm.py 硬编码 IP+sendkey | `config/`、`utils/wecomm.py:11` | 未进 git（好），但文件权限/备份策略未知 |

**处置顺序**：① 删除 test_tq.py、**立即修改该天勤账号密码**、`git filter-repo` 清除历史、引入 gitleaks 类扫描；② 修改 admin 弱口令；③ JWT 密钥外置 + 删除 base64 回退（PyJWT 缺失即拒绝启动）；④ WS 握手鉴权 + 登录后再 connect + logout 断连；⑤ 写操作统一挂角色校验；⑥ log 接口 account_id 白名单 + resolve 后 `is_relative_to` 校验。

---

## 三、严重功能缺陷（确定性 bug，影响交易正确性）

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| BUG-1 | **换仓指令全部成交也被标 FAILED**：`OrderCmd.trig()` 完成时 `finish_reason="全部完成"`（中文字符串），`switch_mgr._monitor_order_commands` 用 `OrderCmdFinishReason.ALL_COMPLETED`（值 `"ALL_COMPLETED"`）判断成功，永不相等 | `order_cmd.py:289,293` + `switch_mgr.py:527` | 所有换仓误标 FAILED 并触发"换仓未完成"告警，自动重试/人工判断全被误导 |
| BUG-2 | **手动下单 IPC 返回 OrderData 对象而非订单 ID**：`insert_order()` 返回 OrderData，经 `simplejson(default=str)` 序列化为 repr 字符串，Manager 端 `isinstance(str)` 为 True 直接当作订单 ID 返回 | `trader_req.py:95-104`、`trader_proxy.py:1072` | Web 手动下单拿到的"订单ID"是对象 repr，按 ID 撤单/查询必然失败 |
| BUG-3 | **TqGateway 跨线程调用 TqApi**：TqApi 在 `_tq_run` 线程创建并由其 wait_update 驱动，`send_order`/`cancel_order`/`subscribe` 由主事件循环线程直接调用，违反 TqSdk 单线程约束 | `tq_gateway.py:122-125, 300-431` | 实盘下单/撤单在压力下可能内部状态错乱、消息乱序、静默失败 |
| BUG-4 | **CTP 未处理交易所错单回报**：`OnErrRtnOrderInsert`/`OnErrRtnOrderAction` 未实现（交易所拒绝走私私有流，柜台拒绝才走已实现的 `OnRspOrderInsert`） | `ctp_api.py` 整个 CtpTdApi | 被交易所拒绝的订单永远停留 PENDING，策略认为挂单有效 → 重复下单、仓位敞口失真 |
| BUG-5 | **`_convert_tick` 把 pre_close 赋成昨持仓量** `pre_close=float(quote.get("pre_open_interest", 0))`（Gateway 与数据层两个审计独立发现） | `tq_gateway.py:716` | 依赖昨收的策略计算（涨跌幅、跳空、风控）全部基于错误数据，持仓量量级远超价格极易触发错误信号 |
| BUG-6 | **BarGenerator 成交量语义错误**：tick.volume 是当日累计成交量（TQ/CTP 均如此），却 `current_bar["volume"] += tick.volume` 直接累加 | `bar_generator.py:140,164,175-178` | 合成 K 线 volume/turnover 虚高约 N 倍（N=bar 内 tick 数），量比/均量指标全部失真 |
| BUG-7 | **`BatchPersistDao` 导入不存在的 `PositionDao`**，模块 import 即 ImportError；`flush()` 调用的 `save_dict` 也不存在 | `dao/batch_persist_dao.py:10,95` | 死模块，账户/持仓批量落库机制形同虚设 |
| BUG-8 | **OrderDao 将内部 order_id 错写入 exchange_order_id**：判定的属性 `exchange_order_id` 在对象层不存在（实际叫 `gateway_order_id`），赋的值却是 `data.order_id` | `dao/order_dao.py:48` | 交易所单号列永远存内部 order_ref，对账/排查拿到错误数据 |
| BUG-9 | **多个 API 端点因方法名腐化 100% 报 500**：`trader.update_risk_control/connect_gateway/disconnect_gateway/pause_trading/resume_trading`、`trading_manager.get_all_account_ids()`、`websocket_manager.is_log_monitoring_enabled()` 均不存在；`manager.get_trades` 收集后 `return []` | `routes/system.py:88-372`、`routes/order.py:179,287,329`、`manager.py:632-635`、`job_mgr.py:327`（restart_trader） | 系统控制（连接/暂停/风控）、日志监控开关、跨账户查单/撤单/成交、定时重启全部不可用或返回错误数据 |
| BUG-10 | **trader_req 告警配置 handler 访问不存在的 AlertConfig 属性**（mypy 实跑发现）：访问 `alert.immediate/.threshold/...`，新 AlertConfig 只有 `notification`/`exception` 两字段 | `trader_req.py:1479-1496` | 调用即 AttributeError，旧配置结构重构遗留死代码 |

---

## 四、高危问题（按主题归并）

### 4.1 进程管理与兜底机制失效

- **PID 复用误杀 + SIGKILL 未实现 + stop 永远返回 True**：`trader_proxy.py:241-265` 从 PID 文件读 PID 只做存在性检查就 SIGTERM（PID 被系统复用时误杀无关进程）；docstring 承诺的 SIGKILL 不存在；杀不掉也只记日志且 `return True`，UI 显示与实际状态不符。
- **定时兜底同步永不执行**：`trader_proxy.py:785` `while self._running and self._is_state(CONNECTED)` —— 任务构造时状态必为 STOPPED，首轮即退出，60 秒全量同步兜底从未生效。
- **`_manual_stop` 状态泄漏**：`stop_process` 置 True 后 `start_process` 不复位（`trader_proxy.py:236`），手动停止→重启后进程崩溃，健康检查仍按"手动停止"跳过告警。
- **健康守护永久误报**：`run_health.py:37,51-67` 依赖 `qtrader_manager.pid`，全代码库无写入点；且健康检查请求 `http://0.0.0.0:port` 在部分平台不可达（应固定 127.0.0.1）。
- **重复启动竞态**：`_get_process` 要求 socket+PID 文件同时存在，PID 文件缺失时重复拉起新 Trader，新进程 unlink 旧 socket 文件 → 旧 Trader 成失联孤儿，双实例并发交易（`trader_proxy.py:167-220, 317-352`、`socket_server.py:266-267`）。
- **scheduler 配置缺失导致数据服务静默不启动**：`manager.py:978-988` 的 `return` 跳过了 `_start_data_feed()`，CTP 账户策略预热数据无声缺失。
- **Manager 停止不清理 TraderProxy 后台任务**：`manager.py:1146-1184` 未调用 `stop_monitoring()`，循环关闭时强杀任务产生半包风险。

### 4.2 async / 线程边界混乱

- **策略层撤单永远失败**：`strategy_manager.py:543` `await self.trading_engine.cancel_order(...)`，而 `cancel_order` 是同步函数返回 bool → `await bool` 抛 TypeError 被吞，返回 False。
- **`StrategyManager.open/close` 同步函数返回协程**：`strategy_manager.py:471-517`，订单永远不会真正发出（当前无调用方，但接口误导性强）。
- **告警 sink 线程不安全**：`trader.py:129` loguru sink 内 `asyncio.create_task`，而大量日志产生于无线程 loop 的线程（to_thread 持久化、threading.Timer）→ RuntimeError、告警丢失；且无节流，ERROR 刷屏放大故障。
- **`send_wechat` 无超时同步阻塞事件循环**：`wecomm.py:38-42` 无 timeout/try-except，`rsp.json()["errcode"]` 非 JSON 响应直接 KeyError；在 `alarm_service.py:117,231` 的 async 方法内直接调用 → 告警通道挂起时 Manager 事件循环卡死。
- **事件循环内阻塞 DB/文件 IO**：`trader_req.py` 多个 handler（list_system_params:1287、update_system_param:1355、import_rotation_instructions:1163、update_target_volume:1266 等）同步 SQLAlchemy 查询；`target_pos_mgr.py:86` 同步扫目录读文件且是前端轮询接口。
- **`TqGateway.connect` 中 `self.disconnect()` 未 await**：`tq_gateway.py:115-118`。
- **共享字典跨线程读写无保护**：`tq_gateway.py:525-539` 主线程迭代 dict 而 tq 线程随时增删；CTP 侧 order_map 在 C++ 回调线程与主线程间共享；`ctp_api.py:514-518` order_ref/reqid 自增无锁。
- **CTP `on_status` 在 C++ 回调线程操作 `_bar_subs`/`_bar_generator`**：`ctp_gateway.py:443-471`。

### 4.3 数据落库静默失败

- **TradeDao**：`trade_time` 为 None 时写入非空 DateTime 列失败被外层吞掉；`else 0` 分支把整数写入 DateTime 列；`hasattr` 防御掩盖 None 问题 → 成交数据静默丢失（`trade_dao.py:43`）。
- **AccountDao**：`Decimal(str(None))` 抛 InvalidOperation 致整账户保存失败；`float_profit` 列从未被赋值（`account_dao.py:38-52`）。
- **换仓导入**：`import_csv` 抛异常后仍无条件写入 OrderFile 导入记录，文件永久不再处理，指令静默丢失（`switch_mgr.py:350-365`）。
- **PositionPo 唯一约束对 strategy_id=NULL 失效**：PG 中 NULL≠NULL，账户级持仓可插入重复行（`models/po.py:93-95`）。
- **settlement 清空再插入跨两事务**：权益已更新、持仓快照缺失的半完成状态可能（`settlement_dao.py:66-71`）。

### 4.4 订单/行情语义错误

- **CTP 订阅去重失效**：`ctp_api.py:292` `set.update(字符串)` 逐字符入集合，去重形同虚设（目前反而掩盖了重连重订阅缺失——修复时必须同步在断线时清空 subscribed）。
- **CTP 拒单判定永不命中**：`ctp_api.py:817` `StatusMsg in error_msg` 是全等比较，StatusMsg 是完整句子；应为子串匹配。
- **TQ 正常撤单被误判 REJECTED**：`tq_gateway.py:619-640` error_msg 含"取消""不"等宽泛子串，正常撤单 last_msg 命中"取消"。
- **`refresh_contracts` 假成功 + 信号量污染**：`ctp_gateway.py:240-262` → `ctp_api.py:645-653`，缓存判断查数量不查日期，且未持锁就释放信号量，污染计数后查询串行化失效触发 CTP 流控。
- **风控撤单限制从未生效**：`risk_control.py:185` `check_cancel` 无调用方，`max_daily_cancels` 形同虚设。
- **`get_orders` 语义不符 + 缓存无界**：CTP `_orders` 只增不减，含当日全部终态订单（`ctp_gateway.py:228-230, 372-374`）。
- **活动订单过滤值不存在**：`trader_req.py:174,236` 过滤 `"ACTIVE"/"ALIVE"`，而 OrderStatus 枚举只有 PENDING/FINISHED/REJECTED → 活动订单列表恒空。
- **TqGateway 重连后历史成交/持仓重复全量推送**：`tq_gateway.py:219-228, 744-792`，下游按成交记账/平历史仓的逻辑会重复执行。

### 4.5 前端高危

- **WS 重连后行情订阅丢失、数据静默停更**：服务端订阅按连接记录，`onopen` 不重发 subscribe_quotes 也不重新拉取快照（`web/src/ws.ts:60-91`）。
- **取消订阅写法错误导致回调泄漏**：`AccountCombined.vue:776,780` 丢弃取消函数，`onUnmounted` 中"再次注册并移除第一个匹配项"，卸载后残留回调继续执行。
- **路由重复注册含自循环重定向**：`router/index.ts:57-62 vs 84-87`（/setting 两次）、`29-34 vs 116-119`（/rotation → /rotation 自循环）。
- **类型层与后端 schema 大量漂移**（`types/index.ts` vs `manager/api/schemas.py`）：
  - `Trade`：声明 exchange_id/instrument_id，后端返回 symbol（前端接口反而没有 symbol，模板却在用 `row.symbol`）
  - `Account`：必填的 id/float_profit 后端不返回；后端 pre_balance 前端缺
  - `Order`：必填 created_at/updated_at 后端不返回；insert_date_time 声明 number 实为 ISO 字符串
  - `OrderCmd`：声明 filled_price/remaining_volume/is_active，后端实为 finished_at/total_orders
  - `Position`：必填 open_price_long/open_price_short/float_profit/margin 后端均无
  - 目前靠 el-table 模板 `row` 为 any 掩盖，TS 逻辑一旦信任必填字段即运行时 undefined。
- **订单状态枚举两套并存**：`types/index.ts:287` 声明的 OrderStatus（SUBMITTING/NOTTRADED...）与实际业务值（ALIVE/FINISHED/REJECTED）完全不同且未被使用。

---

## 五、架构层面值得正视的问题

1. **事件引擎是单点串行管道**：`AsyncEventEngine._run` 逐个 await 所有 handler，`Trader._on_order_update` 里 `await asyncio.to_thread(self._persist_order)` 意味着一次慢 DB 写阻塞其后所有事件（含 tick 分发）；队列无界（`QueueFull` 分支是死代码），tick 风暴下内存无上限；`stop()` 直接 cancel 不 drain，残留事件丢失；异步 handler 异常被 `gather(return_exceptions=True)` 静默吞掉完全不记录（`async_event_engine.py:80,112,127,219,244`）。
2. **订单→策略分发未按 CLAUDE.md 设计实现**：文档声明按 `order_strategy_map` 分发，实际 `StrategyManager._on_order/_on_trade` 按 symbol 匹配广播——同合约多策略互相收到对方订单/成交；`order_strategy_map` 只在撤单校验中使用（`strategy_manager.py:275-293`）。
3. **职责渗漏**：`Trader` 类 960 行内含 ~300 行 ORM 持久化代码（应在 DAO 层）；`trader_req.py` 1580 行 handler 直接写 SQL 且 import manager 层 `api.schemas`，破坏 Manager/Trader 分层；`utils/scheduler.py` import trader 层类，下层依赖上层。
4. **无界字典（内存泄漏）**：`OrderCmdExecutor._history_cmds`（order_executor.py:61，永不清理）、`TradingEngine._order_cmds`（唯一清理方法无调用方）、`StrategyManager.order_strategy_map`（只增不减）、`BarGenerator._completed_bars`、前端回调数组。
5. **策略持仓崩溃漂移**：`base_strategy.py:570-602` 仅在 OrderCmd 结束时聚合更新策略持仓，进程中途崩溃则已成交部分丢失，重启后持仓漂移可能引发重复开仓；`close_stale_positions` 的 `return` 在 for 循环内（371 行），每日只平第一个遗留合约。
6. **死代码存量**：`manager/persistence.py` 整模块（docstring 声称"Manager 是唯一写入者"与现状矛盾）、`BatchPersistDao`、`_update_close_profit`、`StrategyManager.open/close`、`_sync_account_from_trader` 等多个 `_sync_*`、`job_mgr.py:24-47` 的 `_run_async`（且若在事件循环线程调用会死锁）、`utils/json_util.py`、前端死 API 方法/死消息类型/死路由、5 个已删测试文件的 pyc 残留。
7. **重复实现**：`utils/alarm_handler.py` 与 `trader/alarm_handler.py` 约 80 行逐字重复；`database.py` 与 `shared_database.py` 约 120 行重复；前端 App.vue 与 Dashboard.vue 的 `handleAccountAction` 几乎完全相同。
8. **文档与实现脱节**：TESTING.md 宣称"覆盖率 ≥95%、四阶段流程"与实际（大面积红色、无 CI、dev 依赖未声明、Makefile 引用不存在的脚本）严重不符；CLAUDE.md 声明的分发机制未实现；E2E 测试选择器在前端不存在、断言为空，从未真正验证过业务流程。
9. **BarGenerator 不感知交易时段**：D1 按自然日 00:00 切分（夜盘同一交易日被切成两根"日线"），分钟线跨 10:15-10:30/午休边界拼接（`bar_generator.py:210-220`）。
10. **前端工程债**：主 chunk 1.28MB/1.12MB（echarts/Element Plus/图标全量注册）；`router/index.ts:2` 静态 import AccountCombined 破坏懒加载；API 层无 AbortController，快速切换账户时慢响应覆盖新数据；SystemAdmin 编辑用户时密码恒 required 无法保存（`SystemAdmin.vue:714-717`）。

---

## 六、测试体系现状（实跑结论）

- **dev 工具链完全未声明**：pyproject.toml 无 pytest/pytest-asyncio/mypy/black/isort/pytest-cov/playwright → 干净环境 `uv sync` 后所有 `make test-*/lint/format` 必失败。
- **mypy 配置自相矛盾**：mypy.ini `python_version=3.10`（优先于 pyproject 的 3.12）→ 直接 syntax error 中止；9 个核心模块 `ignore_errors=True` + `check_untyped_defs=False`，类型检查名存实亡。修正后 285 errors/20 files，并实际暴露了 BUG-10 这类运行时 bug。
- **测试失修主因**：① 大量过时 patch 路径 `patch("src.trader....")`（重构为 qtrader.* 后未同步，268 errors 的主因）；② 3 个模块 import 已搬迁/删除的模块；③ TraderProxy 构造签名漂移；④ StrategyManager API 漂移（stop_strategy/stop_all/get_status/_dispatch_event 已不存在，open/close 已 async 化）；⑤ `test_weekly_settlement_report.py` 6 个失败属最近一次提交引入的真实回归。
- **测试有效性**：`tests/integration/test_api.py:36-44` 断言 `status_code in [200,400,404]` 等价于没测；test_trading_engine 大量 mock 空转；质量最好的对照样本是 test_risk_control.py。
- **核心模块零覆盖**：ctp_gateway/ctp_api（实盘网关，风险最高）、order_executor、trader_req（1580 行 IPC 核心）、strategy_rsi（唯一生产策略）、全部 DAO、auth 中间件、websocket_manager、26 个 routes 仅被空断言浅覆盖。
- **tests/ 根目录杂散脚本**（test_tq.py 含真实凭证、test_socket_* 起真实 socket、test_examples.py `assert 1+1==2` 虚增计数）被 `testpaths = tests` 全部纳入收集。
- **依赖风险**：全部依赖 `>=` 无上限；uv.lock registry 写死清华镜像 URL。

---

## 七、修复路线图（按投入产出比）

### 第 1 批 —— 安全底线（约 1 天）
凭证轮换与 git 历史清除（SEC-1）、admin 弱口令（SEC-6/SEC-10）、JWT 密钥外置 + 删 base64 回退（SEC-2）、WS 鉴权（SEC-3）、写操作挂角色校验（SEC-4）、log 路径白名单（SEC-5）、IPC 消息上限 + socket 0600（SEC-7）。

### 第 2 批 —— 确定性功能 bug（约 1-2 天，均为小改动）
换仓状态枚举对齐（BUG-1）、下单返回 order_id（BUG-2）、pre_close 字段（BUG-5）、`get_trades` 返回值与方法名对齐（BUG-9）、告警配置 handler（BUG-10）、`_manual_stop` 复位 + `_periodic_sync_loop` 条件（4.1）、Manager PID 文件（4.1）、`check_cancel` 接入（4.4）、前端取消订阅与路由重复（4.5）。

### 第 3 批 —— 交易正确性（需设计，约 3-5 天）
TqApi 调用收敛到 tq 线程或官方协程模式（BUG-3）、CTP 错单回报 + 拒单子串匹配 + 订阅去重/重订阅联动（BUG-4、4.4）、BarGenerator 成交量增量语义 + 夜盘/时段切分（BUG-6、五-9）、DAO 字段错配与 None 防御（BUG-7/8、4.3）、订单→策略分发修正（五-2）、成交落库失败告警、事件引擎异步异常记录 + 背压（五-1）。

### 第 4 批 —— 测试与工具链重建
声明 dev 依赖 → 修 mypy.ini（python_version、收敛 ignore_errors）→ 批量修 patch 路径（`src.trader.`→`qtrader.trader.`）→ 修周报回归 → 重写 strategy_manager/trader_proxy 测试 → 补 CTP 网关/trader_req/策略/auth 测试 → 清理 tests/ 根目录杂散脚本 → 上最小 CI（pytest + mypy 强制绿）。

### 第 5 批 —— 架构与工程债（择机）
事件引擎背压与 drain、无界字典清理、持久化代码下沉 DAO、trader_req 拆分、删除死代码、前后端类型对齐（以 schemas.py 为准）、前端分包与懒加载、IPC handler 统一 to_thread 包装、config.yaml 写操作集中加锁。

---

## 附录：低级问题摘选（完整清单见各专项审计上下文）

- `base_gateway.py:64-68` close() 设置 `self.running` 而实现都用 `_running`（无效赋值）
- `object.py:11` 残留无用 import `from sqlalchemy.util import b`
- `ctp_gateway.py:474-506` `_update_close_profit` 死代码
- 合约过滤魔法数字不一致：CTP `len(symbol)<=6` 会排除期权合约（`ctp_api.py:1041`）
- `tq_gateway.py:282-298` get_trading_day 用 hour>=20 推断夜盘，周五夜盘算到周六
- `ctp_api.py:37-47` 模块导入期读全局配置决定 CTP 库类型，单进程多账户混合类型只生效第一个
- `scheduler.py` Job `job_id: str = None` 类型与默认值不匹配；任务 pause/resume 不落库不持久化
- `order_cmd.py:35` OrderCmdStatus 是普通 str 子类而非 Enum，与 OrderStatus 混判
- `trader_req.py:1047-1049` 先调用再做 None 检查，顺序颠倒
- `app.py:54-58` ctx.register 在判空之前执行
- 前端：`api/quote.ts` 死 API 方法、`stores/index.ts:154-173` `as unknown as Account` 伪造对象、`types/index.ts:299` Interval 类型与实际不符、App.vue:360 残留 console.log
- 每个报单/成交回报全量对象 INFO 日志（`ctp_gateway.py:400,412`、`tq_gateway.py:814,835`），高频下日志量过大建议降 debug
