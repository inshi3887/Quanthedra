# QuantAnalyInvest 开发计划

> 状态：待批准执行
> 版本：0.1
> 日期：2026-08-12
> 上游契约：[MERGE_DESIGN.md](../MERGE_DESIGN.md)
> 新仓库：`QuantAnalyInvest`

---

## 1. 目的与本计划来源

本文件把 `MERGE_DESIGN.md` 的 Phase 0–8 细化为一串**可独立验证、独立交付**的小计划（下称 Plan）。每个 Plan 完成后停下汇报，经人工确认后才进入下一个。

### 1.1 与 MERGE_DESIGN.md 的关系

- 架构契约、领域模型、API、SQL、安全边界、测试策略全部沿用 MERGE_DESIGN.md，本文件不重写它们，只给出**实施顺序与验收**。
- 对 MERGE_DESIGN.md 的一处偏差：其第 7 行写"目标仓库为 QuantDinger 作为最终主仓"，现按项目负责人决定改为**新仓库 QuantAnalyInvest 作为统一仓库**，QD 仍是运行底座（ADR-001 语义不变）。

### 1.2 已确认的关键决策（项目负责人 2026-08-12）

| # | 决策 | 影响 |
| --- | --- | --- |
| D-001 | QuantAnalyInvest 以 QuantDinger 后端为基线整体迁入，作为统一仓库起点 | Phase 0 需要初始化新仓库并迁入 QD 代码 |
| D-002 | 干净基线，不保留 QuantDinger/DSA 的 git 历史 | Phase 0 以 QD 代码作为初始提交，不导入旧 blame |
| D-003 | 逐 Plan 交付，每个 Plan 完成后人工确认再继续 | 本文件所有 Plan 的默认行为 |

---

## 2. 执行规则

1. **一次只执行一个 Plan**，禁止提前实施后续 Plan 的内容。
2. 每个 Plan 开始前执行只读基线检查（git status / HEAD）。
3. 每个 Plan 必须附带测试，运行与改动面匹配的验证。
4. 交易相关代码**默认 fail closed**，不得用 mock 绕过资格、幂等或隔离。
5. 每完成一个 Plan，按第 5 节的交付模板汇报，等待确认。
6. 需要回滚时，优先使用开关停写，不在事故中直接删数据。

### 2.1 每阶段回滚开关（沿用 MERGE_DESIGN §20）

```
RESEARCH_DOMAIN_ENABLED
RESEARCH_NEW_DATA_ROUTER_ENABLED
RESEARCH_DUAL_RUN_ENABLED
RESEARCH_SIGNAL_PERSIST_ENABLED
RESEARCH_PAPER_BRIDGE_ENABLED
RESEARCH_US_LIVE_BRIDGE_ENABLED
```

---

## 3. Plan 总览

| # | 名称 | 所属 Phase | 目标 | 前置 |
| --- | --- | --- | --- | --- |
| P0 | 仓库基线初始化 | Phase 0 | 建立 QuantAnalyInvest 可运行基线，无业务改动 | — |
| P1 | research 骨架 + InstrumentIdentity | Phase 1.1 | 研究域包与标的身份 | P0 |
| P2 | 研究 action 映射纯函数 | Phase 1.2 | 动作×持仓全矩阵映射 | P1 |
| P3 | research PostgreSQL migration | Phase 1.3 | 研究域表与约束 | P1 |
| P4 | StockDataRouter + USStock 双跑 | Phase 2.1 | 行情契约与最小 provider | P1 |
| P5 | CN/HK 规范化与 fallback | Phase 2.2 | 多市场数据源整合 | P4 |
| P6 | 研究任务与报告（Celery + API） | Phase 3.1 | 异步研究闭环，不含信号 | P3, P4 |
| P7 | DecisionSignal 持久化与生命周期 | Phase 4.1 | 信号落地与状态机 | P6 |
| P8 | SignalOutcome 评估 | Phase 4.2 | 信号方向评估 | P7 |
| P9 | ExecutionEligibility dry-run | Phase 5.1 | 确定性资格判断（不建订单） | P7 |
| P10 | deterministic sizing | Phase 5.2 | 服务端数量计算 | P9 |
| P11 | paper OrderIntent 闭环 + AAPL E2E | Phase 5.3 | 研究→paper 全链路 | P9, P10 |
| P12 | USStock live 受控开放 | Phase 6 | 受控实盘门禁 | P11 |
| P13 | 前端与通知统一 | Phase 7 | 统一 UX（依赖独立前端仓库） | P11 |
| P14 | 数据迁移与旧系统退役 | Phase 8 | DSA 退役 | P11 |

---

## 4. 各 Plan 详细说明

---

### P0 · 仓库基线初始化（Phase 0）

**目标**：建立可重复的开发基线，不改变任何业务行为。

**背景决策**：D-001/D-002。以 QuantDinger 后端代码作为 QuantAnalyInvest 初始提交，干净基线。

**任务**
1. 在 `QuantAnalyInvest/` 执行 `git init`，建立仓库骨架：
   - `README.md`（说明统一平台定位、与 DSA/QD 的关系）
   - `AGENTS.md`（开发代理规则，引用 MERGE_DESIGN.md）
   - `.gitignore`（合并 QD 与 DSA 的忽略项）
   - `LICENSE`、`THIRD_PARTY_NOTICES.md`（沿用 MERGE_DESIGN §22：QD Apache-2.0 + DSA MIT 声明 + screening 来源；正式发布前需单独许可审查）
2. 拷贝 QuantDinger 后端代码（`backend_api_python/`）至新仓库根，作为初始提交。
   - 保留：`app/`、`migrations/`、`tests/`、`pyproject.toml`、`requirements*.txt`、`Dockerfile`、`docker-entrypoint.sh`、`run.py`、`start.sh`、`gunicorn_config.py`、`env.example`、`railway.json`、`VERSION`。
   - 排除：`__pycache__/`、`.git/`、报告产物、本地日志。
3. 记录基线（写入 `docs/BASELINE.md`）：
   - QD HEAD `e64e1c2`、VERSION 5.0.x、DSA HEAD `396d43a4`（v3.30.0）。
   - 两边离线测试入口与运行命令。
   - 确认可用 Python 版本（目标 3.12，注意本机存在的 3.14 不作为生产目标）。
4. 生成**依赖冲突报告**（`docs/DEPENDENCY_REPORT.md`），重点核对：
   - pandas：QD `>=3.0.5` vs DSA `>=2.0.0`。
   - litellm：QD `>=1.93,<1.94` vs DSA `>=1.80,<2.0`。
   - longbridge：QD 条件版本 vs DSA `==0.2.74`（Linux py<3.12）与 `>=4.0.5`（其余）。
   - exchange-calendars：DSA `>=4.13` 需确认 pandas 3 兼容（QD 生产基线）。
   - Flask 3.1.3（QD）vs FastAPI/uvicorn（DSA）共存策略。
   - 数据源 SDK 按 extra 分组，避免所有 worker 安装券商 SDK。
5. 建立 ADR 文档（`docs/adr/ADR-001.md` … `ADR-010.md`），内容取自 MERGE_DESIGN §4，并补充 D-001/D-002/D-003。
6. 建立工作 checklist（`docs/CHECKLIST.md`），列出全部 Plan 与验收项。

**验收**
- 新仓库可构建、QD 现有离线测试通过。
- 未移动任何业务代码，无行为变化。
- 所有架构决策有书面记录。
- 依赖冲突报告产出。

**风险**：环境缺 Python 3.12 / 依赖安装失败 → 报告并停留在 P0，不进入 P1。
**回滚**：整个仓库尚未有业务改动，直接回退到初始提交即可。

---

### P1 · research 骨架 + InstrumentIdentity（Phase 1.1）

**目标**：在 QuantAnalyInvest 内创建不依赖 DSA 运行时的研究域包与唯一标的身份。

**任务**
1. 新建 `app/services/research/`：
   - `__init__.py`、`contracts.py`、`instrument_identity.py`。
2. `InstrumentIdentity`（MERGE_DESIGN §7.1）：market / symbol / canonical_key / exchange / asset_class / currency / timezone。
   - `canonical_key = f"{market}:{symbol}"`。
   - 提供纯函数 `normalize_instrument(market, symbol) -> InstrumentIdentity`，覆盖：
     - 港股 `hk00700` / `00700` / `0700.HK` → `HKStock:0700.HK`（同一 canonical_key）。
     - US `AAPL` → `USStock:AAPL`；CN `600519` → `CNStock:600519`。
   - 显示名称不是身份字段。
3. 研究动作枚举（MERGE_DESIGN §7.4）：`buy / add / hold / reduce / sell / watch / avoid / alert`。
4. 单元测试 `tests/services/research/test_instrument_identity.py`：
   - 各市场规范化、失败用例（未知市场、空 symbol）。
   - 纯函数性质（无副作用、幂等）。
   - 参数化测试覆盖文档 §7.1 规则。

**验收**
- 测试全绿；无生产路由、无交易行为变化。
- `AAPL` 不会被默认成 Crypto（fail closed）。

**风险**：低。仅新增包与测试。
**回滚**：删除 `app/services/research/` 与对应测试，无其他影响。

---

### P2 · 研究 action 映射纯函数（Phase 1.2）

**目标**：实现"研究动作 → 候选交易动作"的确定性映射，**不创建任何订单**。

**任务**
1. `app/services/research/action_mapping.py`：
   - 输入：研究 action + 持仓状态（无持仓 / 有多头持仓 / 持仓超限）。
   - 输出：候选 QD 动作列表或 `None`（参考 MERGE_DESIGN §8 表格）。
   - 定义 `ReasonCode` 枚举（MERGE_DESIGN §8 reason codes 全部 16 个）。
2. 硬规则（必须有测试）：
   - 股票 `sell` 不得转成 `open_short`。
   - `hold / watch / avoid / alert` 不产生 OrderIntent。
   - `reduce` 无持仓时拒绝；`add` 需要最大仓位检查。
3. 单元测试 `tests/services/research/test_action_mapping.py`：全动作 × 全持仓状态矩阵。

**验收**
- 覆盖 §8 全部组合，硬规则均有断言。
- 纯函数、无 IO、无订单副作用。

**风险**：低。
**回滚**：删除映射模块与测试。

---

### P3 · research PostgreSQL migration（Phase 1.3）

**目标**：落地研究域表结构，遵循 QD 现有 migration 命名与幂等风格。

**任务**
1. 新增 `migrations/YYYYMMDD_research_domain.sql`（沿用 QD 的 `YYYYMMDD_*.sql` 命名与 release gate）。
2. 表（MERGE_DESIGN §13）：`qd_research_runs`、`qd_research_run_items`、`qd_research_reports`、`qd_decision_signals`、`qd_decision_signal_outcomes`、`qd_decision_signal_feedback`、`qd_signal_execution_reviews`。
3. 约束（§13.1）：
   - 所有用户数据表外键 `qd_users(id)`。
   - 报告版本唯一键：`(user_id, instrument_market, instrument_symbol, report_type, report_version)`。
   - 信号幂等索引：`(user_id, source_report_id, instrument_market, instrument_symbol, decision_profile, action, horizon, market_phase)`。
   - JSONB 存 JSON；金额/价格/数量用 `NUMERIC`；时间存 UTC timestamp。
   - 幂等：`CREATE TABLE IF NOT EXISTS`，可重复执行。
4. migration 测试（沿用 QD migration 测试方式）：
   - 空库成功、已有库幂等。
   - 唯一索引阻止重复信号。
   - 用户 A 无法引用用户 B 的报告（外键 + 查询隔离后续在 repository 层验证）。
   - 并发创建相同信号只产生一条记录。

**验收**
- migration 空库/已有库均通过；唯一索引语义正确。

**风险**：低-中。表设计错误后续难改，需在 P3 确认索引与字段。
**回滚**：本次仅建表，不改旧表；回滚可保留表、停止写入。

---

### P4 · StockDataRouter + USStock 双跑（Phase 2.1）

**目标**：把 DSA 数据 fallback 能力接入 QD 市场数据层，先支持 USStock 日线。

**任务**
1. `app/data_sources/stock_fallback/`（MERGE_DESIGN §6 目标结构）：
   - `router.py`：`StockDataRouter` Protocol（`fetch_bars` / `fetch_quote` / `fetch_fundamentals`）。
   - 契约类型 `MarketDataResult` / `QuoteResult`（含 `source`、`fallback_chain`、`warnings`、`as_of`、`timezone`、`adjustment`、`quality`）。
   - `health.py`、`adapters/yfinance.py`。
   - 禁止用空列表同时表示"无数据"与"故障"；必须通过 warning/error code 区分。
2. 迁移 DSA 的 capability 判断、错误分类、fallback 优先级、熔断/冷却、超时（从 `daily_stock_analysis/data_provider/` 提取，不搬 SQLite 与全局单例）。
3. 缓存键（§10.3）：`market/symbol/exchange/asset_class/timeframe/start|limit/adjustment/provider_policy_version`；公共行情不加 user_id。
4. **双跑**（§10.4）：同一请求同时调旧 DSA DataFetcherManager 与新 router，只比较记录（行数、日期范围、最新 close、缺失率、复权、数据源、fallback），不进入生产决策。
   - 开关 `RESEARCH_DUAL_RUN_ENABLED`。
5. 指标：`research_provider_requests_total{provider,status}`、`research_provider_fallback_total`。
6. 测试：AAPL 规范化与行情契约、provider 故障 fallback、缓存键、fail closed（无市场字符串不回退 Crypto）。

**验收**
- AAPL 日线契约通过；双跑差异在约定阈值内并有报告。
- provider 故障按预期 fallback；无市场字符串 fail closed。

**风险**：中。依赖网络数据源 → 网络相关测试显式标记，CI 不依赖外网。
**回滚**：`RESEARCH_NEW_DATA_ROUTER_ENABLED=false` 切回旧 DSA 服务。

---

### P5 · CN/HK 规范化与 fallback（Phase 2.2）

**目标**：扩展到 CNStock / HKStock 的规范化、行情与多 provider fallback。

**任务**
1. 规范化：`600519` → `CNStock:600519`；`hk00700 / 00700 / 0700.HK` → 同一 `canonical_key`。
2. 适配器：`adapters/efinance.py`、`akshare.py`、`tushare.py`、`baostock.py`、`pytdx.py`（按需），能力判断与 fallback 优先级按 DSA 语义迁移。
3. 市场字符串 fail closed：未知市场明确报错，不得回退 Crypto。
4. 双跑扩展到 CN/HK。
5. 测试：600519、0700.HK 规范化与行情契约；fallback 链。

**验收**
- CN/HK 行情契约与 fallback 通过；fail closed 有测试。
- 双跑差异报告无异常。

**风险**：中（外网依赖）。
**回滚**：同 P4。

---

### P6 · 研究任务与报告（Celery + API，Phase 3.1）

**目标**：在 Celery worker 中运行有限研究任务并持久化报告，不接信号。

**任务**
1. repository：`qd_research_runs` / `qd_research_run_items` / `qd_research_reports`（PostgreSQL，替代 DSA SQLite storage）。
2. Celery 任务（`app/tasks/research.py`，走 jobs Redis）：
   - `research.run_batch`（fan-out + 汇总，只负责编排）。
   - `research.analyze_instrument`（单标的，可独立重试；soft/hard timeout）。
   - 幂等键：`user:{user_id}:instrument:{canonical_key}:report:{type}:date:{effective_date}:profile:{profile}:version:{pipeline_version}`。
   - 同键重复提交：成功→返回原结果；执行中→返回同一 run/item；失败按重试政策创建 attempt。
   - 单标的失败不得导致批次整体失败。
3. 将 DSA 纯分析能力封装到 `app/services/research/report_service.py`；`dsa_bridge.py` 只封装尚未迁移的服务。
4. Flask 路由 `app/routes/research.py` + OpenAPI（`app/openapi/research.py`）：
   - `POST /api/research/v1/runs` → 202，返回 runId + items。
   - `GET /api/research/v1/runs/{id}`、`GET /api/research/v1/reports`、`GET /api/research/v1/reports/{id}`。
   - 配置快照只存非敏感有效配置；model 配置脱敏。
5. 保留 DSA 旧路径，结果双跑（`RESEARCH_DUAL_RUN_ENABLED`）。
6. 指标与日志（§17）：日志携带 request_id/run_id/user_id/market/symbol/task_id；不记录密钥。

**验收**
- API 返回 202 且任务异步完成；API 进程不运行分析线程/scheduler。
- 单标的失败不拖垮批次；报告带 provenance、user_id、有效配置快照。
- 幂等键行为正确。

**风险**：中。Celery worker 资源与限流（LLM/行情/新闻分别限流）。
**回滚**：`RESEARCH_DOMAIN_ENABLED=false`；API 不注册研究路由，任务不调度。

---

### P7 · DecisionSignal 持久化与生命周期（Phase 4.1）

**目标**：迁移结构化信号、状态机与研究结果评估的核心语义。

**任务**
1. 迁移 `decision_signal_extractor.py` / `decision_signal_service.py` 核心语义到 `app/services/research/signal_service.py`，去掉 SQLite/SQLAlchemy 绑定，用 QD PostgreSQL repository。
2. 信号状态机（§7.4）：`active → expired / invalidated / closed / archived`。
   - 状态改变只能由服务、任务或明确 API 完成并写审计记录，不得因查询隐式改变。
   - `research.expire_signals` 定时任务。
3. 信号查询 / 反馈：
   - `GET /api/research/v1/signals`、`GET .../signals/{id}`、`POST .../signals/{id}/feedback`。
4. 数据质量 guardrail（§14.3）：数据不足时不能输出自动执行资格。
5. 唯一索引防重复；**相反信号使旧信号失效**（by invalidation 规则）。
6. 测试：并发创建只一条、相反信号失效、多租户隔离、状态机。

**验收**
- 同一报告重试不重复创建信号；相反信号按规则失效。
- 多租户隔离测试通过；状态改变有审计。

**风险**：中。状态机并发边界。
**回滚**：`RESEARCH_SIGNAL_PERSIST_ENABLED=false` 停写，保留表。

---

### P8 · SignalOutcome 评估（Phase 4.2）

**目标**：研究信号方向评估，明确与策略回测的展示边界。

**任务**
1. 迁移 outcome engine 核心语义（`decision_signal_outcome_service.py` / `skill_opinion_outcome_evaluator.py` 参考）到 `app/services/research/outcome_service.py`。
2. `research.evaluate_signal_outcomes` 任务：按 horizon 评估，可独立重试且不重复。
3. 明确 UI/API 文案区分：Research outcome（方向有效性）vs Strategy backtest（仓位/成交/费用/滑点收益）。
4. `GET /api/research/v1/signals/{id}/outcomes`。

**验收**
- outcome 可重试不重复；方向判断正确；与 strategy backtest 区分清晰。

**风险**：低-中。
**回滚**：任务与路由开关。

---

### P9 · ExecutionEligibility dry-run（Phase 5.1）

**目标**：研究信号与订单意图之间的确定性安全边界，**只 dry-run，不建订单**。

**任务**
1. `app/services/research/eligibility_service.py`：实现 §7.6 十项检查：
   用户/账户归属、信号 active 未过期、报告与数据质量阈值、市场执行模式、券商支持、当前/目标持仓、账户额度与集中度、交易时间与停牌、allowlist/kill switch/paper-only、幂等键。
2. `ExecutionEligibility` 冻结 dataclass（§7.6）。
3. 端点 `POST /api/research/v1/signals/{id}/eligibility`（dry-run）。
4. reason codes 完整返回（§8 的 16 个）。
5. 测试：十项检查各场景、边界、fail closed。

**验收**
- dry-run 不产生任何订单；reason code 正确；`hold/watch/avoid/alert` 一律拒绝产生意图。

**风险**：中。检查项遗漏会直接威胁安全 → 逐项测试。
**回滚**：端点仅读，未落库写入；可整体关闭。

---

### P10 · deterministic sizing（Phase 5.2）

**目标**：服务端确定性计算目标数量/名义金额，禁止 LLM 文本数量入数。

**任务**
1. `app/services/research/action_mapping.py` 的 sizing 部分或独立 `sizing.py`：
   - 输入：账户净值、价格、风险限额、最小交易单位、集中度、策略额度。
   - 输出：`target_position_qty` / `target_notional`（可审计）。
2. 硬规则：
   - "满仓/半仓/梭哈"等 LLM 文本不得直接作为数量。
   - 数量必须由确定性 sizing policy 计算。
3. 测试：sizing 边界、账户额度、集中度、最小交易单位、风险限额。

**验收**
- sizing 只读账户/风控数据，输出可审计；无法被任意文本绕过。

**风险**：中。金额精度用 NUMERIC，不用 float。
**回滚**：sizing 未落库、未下单，可独立关闭。

---

### P11 · paper OrderIntent 闭环 + AAPL E2E（Phase 5.3）

**目标**：完成研究信号 → QD paper OrderIntent 的闭环。

**任务**
1. 复用 QD 现有：
   - `app/services/strategy_runtime/signals.py::StrategySignal`
   - `app/services/strategy_runtime/order_intents.py::OrderIntentService`
   - `app/services/strategy_v2/live_execution.py::StrategyV2OrderGateway`
   - `pending_orders` + `pending_order_worker`（不新增第二套订单表）。
   - 股票 `StrategySignal.market_type` 显式 `spot`，不用默认 `swap`。
2. 端点 `POST /api/research/v1/signals/{id}/paper-intents`：
   - 再次执行资格检查（不信任客户端上次结果）。
   - 使用服务端计算的数量。
   - 创建 QD 原生 StrategySignal 和 OrderIntent，返回现有或新建 intent id。
3. 审计、指标（`signal_to_intent_total{market,action,result}`）、并发测试：
   - 相同 signal 只产生一个有效 order intent（幂等）。
   - 重复请求得到同一 intent。
4. 最小 paper E2E（§18.5）：
   提交 AAPL 研究 → 报告 → active buy signal → 资格通过 paper → open_long StrategySignal → 唯一 OrderIntent → paper fill → 查询持仓与审计。

**验收**
- `hold/watch/avoid/alert` 无法生成订单；无持仓 sell 无法开空。
- 重复请求只一个 intent；LLM 文本不能绕过 sizing/风险。
- AAPL paper E2E 通过。

**风险**：高。涉及订单链路 → 严格并发与幂等测试，任何失败 fail closed。
**回滚**：`RESEARCH_PAPER_BRIDGE_ENABLED=false`，不影响 QD 原有交易链路。

---

### P12 · USStock live 受控开放（Phase 6）

**目标**：只在现有 QD 券商边界内开放美股实盘。

**前置条件**：P11 稳定运行；IBKR/Alpaca sandbox 或 paper broker 测试通过；kill switch / allowlist / 额度 / 审计测试通过。

**任务**
1. 复用 QD live policy（ibkr / alpaca），不创建旁路。
2. live 门禁（§15.3）：用户显式开 live、账户 IBKR/Alpaca、`AGENT_LIVE_TRADING_ENABLED`、account/market/instrument allowlist、账户+策略 notional、策略 lease、order intent 幂等、kill switch、broker client order id。
3. 人工审批（§15.4）：每笔人工确认，或用户预创建自动化策略（明确账户/标的/额度/有效期/审批策略）。
4. 测试：paper-only 无法 live；CN/HK/JP/KR/TW live 拒绝；live 订单 signal→intent→pending order→broker order 全链路可追踪。

**验收**
- 默认仍 paper-only；非美实盘全部拒绝。
- live 全链路可追踪；kill switch 优先。

**风险**：高。实盘资金 → 全部 fail closed，先验证 sandbox。
**回滚**：`RESEARCH_US_LIVE_BRIDGE_ENABLED=false`（最高优先级 kill switch）。

---

### P13 · 前端与通知统一（Phase 7）

**目标**：统一用户体验。依赖独立 QD 前端仓库（本工作区不含前端源码，需另行获取）。

**任务**
1. 页面：Research Runs、Research Reports、Decision Signals、Execution Review、Signal Performance（§16）。
2. 通知：只发研究与执行状态；通知载荷引用 report/signal id，不发送完整敏感上下文；通知按钮不等于 live 授权。
3. 保留权限显示：用户只能看到自己的报告/信号；paper/live 状态明确区分。

**验收**
- 多租户前端可见性正确；通知失败不影响研究/交易状态。

**风险**：中（依赖独立前端仓库许可与接入）。
**回滚**：后端 API 兼容，前端可独立回退。

---

### P14 · 数据迁移与旧系统退役（Phase 8）

**目标**：QuantAnalyInvest 成为唯一生产入口，DSA 退役。

**任务**
1. 离线导入命令（默认 dry-run）：
   - `python -m app.commands.import_dsa --sqlite PATH --user-id ID --dry-run`
   - `python -m app.commands.import_dsa --sqlite PATH --user-id ID --apply`
   - 输出源表/行数/跳过/冲突/目标；支持断点续传；保存 legacy id 映射；不导入明文密钥；无法规范化的标进入错误报告不猜市场。
2. 备份并执行正式导入；观察至少一个完整运行周期。
3. 停用 DSA scheduler、API 写路径、重复通知。
4. 删除 `dsa_bridge.py` 与重复实现。

**验收**
- DSA 不再产生新的生产事实数据；旧报告可查询。
- 无重复任务/通知/信号/订单；有已验证的回滚与备份。

**风险**：中-高。数据完整性 → dry-run 先行，断点续传。
**回滚**：保留导入映射与备份；DSA 停用前有回滚验证。

---

## 5. 每个 Plan 交付报告模板

每个 Plan 完成后，向项目负责人汇报：

```text
1. 改了什么
2. 为什么符合 MERGE_DESIGN.md
3. 数据/API/任务契约变化
4. 测试结果
5. 未测试项
6. 风险
7. 回滚方式
8. 下一 Plan 前置条件
```

等待确认后才进入下一个 Plan。

---

## 6. 第一批建议顺序

按依赖关系，首批执行：**P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9 → P10 → P11**。P12/P13/P14 在 P11 通过后再规划细化。

在 P11（AAPL paper E2E）通过之前，不开始任何 AI 信号实盘功能。
