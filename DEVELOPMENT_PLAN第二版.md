# QuantAnalyInvest 开发计划（第二版）

> 状态：修订后待批准执行  
> 版本：0.2  
> 日期：2026-08-12  
> 上游架构契约：[MERGE_DESIGN.md](../MERGE_DESIGN.md)  
> 第一版：[DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)  
> 目标仓库：`QuantAnalyInvest`

---

## 1. 目的与修订结论

本文件将 `MERGE_DESIGN.md` 拆分为可独立实施、验证、回滚和审批的 Plan。第二版保留第一版的核心方向：

- QuantDinger（下称 QD）作为运行、账户、策略、风控与订单底座。
- daily_stock_analysis（下称 DSA）作为多市场研究能力来源。
- PostgreSQL 是生产事实数据的唯一来源。
- 有限研究任务进入 Celery；长期交易循环继续由 QD trading worker 负责。
- 严格执行 `DecisionSignal -> ExecutionEligibility -> StrategySignal -> OrderIntent`。
- LLM 只生成研究结果，不提供可信订单数量，也不能直接下单。
- 第一阶段只允许 `USStock` 进入受控实盘；CN/HK/JP/KR/TW 仅研究和 paper。

第二版修正第一版中与现有代码不一致的部分：

1. P0 改为复制完整 QD 仓库树，保留 `backend_api_python/`、CI、Compose、运维和 MCP 结构。
2. 在研究表之前先建设真正的有序 migration runner。
3. 使用复合外键保证数据库级多租户一致性。
4. 明确定义 DSA shadow/dual-run 的部署拓扑和固定版本。
5. 补齐 JP/KR/TW 能力迁移，防止 DSA 退役后功能倒退。
6. 拆分研究分析、任务接线、持续调度、资源治理和权限接入。
7. 增加 ExecutionBinding，解决研究信号缺少合法策略、账户和运行身份的问题。
8. 增加原子额度预占，消除资格检查与创建订单之间的并发窗口。
9. 在 QD Strategy V2 中正式增加 `paper` 执行模式，不再假设 `signal` 可以产生模拟成交。
10. 区分 Human JWT 与 Agent/MCP 的实盘授权，不滥用 `AGENT_LIVE_TRADING_ENABLED`。

---

## 2. 已确认决策与新增决策

| # | 决策 | 实施影响 |
| --- | --- | --- |
| D-001 | QuantAnalyInvest 是新的统一仓库，QD 是运行底座 | 以完整 QD 仓库树作为初始基线 |
| D-002 | 不导入 QD/DSA Git 历史 | 必须用许可证、NOTICE 和来源清单补足溯源 |
| D-003 | 一次只交付一个 Plan，人工确认后继续 | 不允许跨 Plan 偷跑后续业务能力 |
| D-004 | 初期保留 `backend_api_python/`、`qd_` 表前缀和兼容环境变量 | 产品品牌与内部兼容标识分开处理，禁止在合并功能时大规模改名 |
| D-005 | DSA 过渡期以固定版本的独立 legacy service 提供 shadow 对照 | 新仓库不直接 import DSA 源码，不把两套依赖装入同一进程 |
| D-006 | QD Strategy V2 增加正式 `paper` execution mode | `signal` 仍只通知，`live` 仍只真实执行，三者语义不可混用 |
| D-007 | Human JWT 与 Agent/MCP 共用领域服务和风控，但使用各自授权入口 | Agent 复用现有 R/W/B/N/C/T scope，不新增平行权限体系 |
| D-008 | 旧系统退役以能力等价和生产观察为准，不以代码已复制为准 | JP/KR/TW、调度、通知、历史数据和回滚均须过 gate |

---

## 3. 执行规则

1. 一次只执行一个 Plan；每个 Plan 独立提交、独立测试、独立汇报。
2. 每个 Plan 开始前记录 `git status`、HEAD、依赖版本和数据库 schema version。
3. 不修改或清理两个上游仓库中的用户本地改动；只从已记录的 commit 提取内容。
4. 所有交易相关路径默认 fail closed。市场、账户、策略、价格、额度或身份不明确时必须拒绝。
5. 单元测试不得用 mock 绕过多租户、幂等、额度预占、状态机或订单门禁；关键路径必须有 PostgreSQL 集成测试。
6. 网络测试与离线 CI 分开。离线 CI 使用 fixture/recording；定时 network smoke 只验证 provider 漂移。
7. 数据库变更只允许前向兼容 migration；事故回滚优先停写和关闭功能，不在事故中 DROP 表。
8. API 的 `user_id` 只能来自认证上下文，不接受客户端代填。
9. 金额、价格、数量和费用在领域计算及数据库中使用 Decimal/NUMERIC；仅在不可避免的旧适配器边界转换为 float。
10. 每个功能开关必须有默认值、所有者、删除条件和覆盖测试，避免永久残留死开关。

### 3.1 功能与安全开关

```text
RESEARCH_DOMAIN_ENABLED=false
RESEARCH_NEW_DATA_ROUTER_ENABLED=false
RESEARCH_DUAL_RUN_ENABLED=false
RESEARCH_SIGNAL_PERSIST_ENABLED=false
RESEARCH_SCHEDULER_ENABLED=false
RESEARCH_PAPER_BRIDGE_ENABLED=false
RESEARCH_US_LIVE_BRIDGE_ENABLED=false
```

规则：

- `RESEARCH_US_LIVE_BRIDGE_ENABLED` 是研究信号进入 US live 的平台级总开关，默认 false。
- `AGENT_LIVE_TRADING_ENABLED` 仅约束 Agent/MCP 请求；Human JWT 流程不能以它作为唯一门禁。
- 任一上层开关关闭都不得被下层配置绕过。

### 3.2 阶段质量门

| Gate | 通过条件 | 阻止的后续工作 |
| --- | --- | --- |
| G0 基线门 | 完整 QD 构建、CI、Compose、OpenAPI、安全检查可运行 | 所有业务迁移 |
| G1 数据门 | migration runner、租户约束、数据契约通过 | 研究 API 与任务 |
| G2 研究门 | 六市场研究、调度、配额、双跑指标达标 | DSA 退役与订单桥 |
| G3 信号门 | 信号生命周期、outcome、审计和隔离通过 | Eligibility |
| G4 Paper 门 | 策略身份、原子额度、paper 账本及 AAPL E2E 通过 | 任意 live |
| G5 Live 门 | sandbox、人工审批、kill switch、对账和故障演练通过 | US 生产实盘 |
| G6 退役门 | 功能等价、数据迁移、完整观察周期和回滚演练通过 | 停用 DSA |

---

## 4. Plan 总览

| # | 名称 | 主要交付 | 前置 |
| --- | --- | --- | --- |
| P0 | 完整仓库基线与来源治理 | 可运行的完整 QD 基线 | - |
| P1 | PostgreSQL migration runner | 有序、并发安全、可审计迁移 | P0 |
| P2 | Research 契约、标的身份与动作映射 | 六市场身份和纯函数规则 | P0 |
| P3 | Research 数据模型与租户约束 | 研究表、复合外键、repository | P1, P2 |
| P4 | DSA legacy bridge 与能力清单 | 可复现 shadow/dual-run | P0 |
| P5 | StockDataRouter 与 USStock | US 行情契约和双跑 | P2, P4 |
| P6 | CN/HK provider 路由 | 按能力的 fallback | P5 |
| P7 | JP/KR/TW 能力迁移 | 防止非中美港能力回退 | P5 |
| P8 | 研究分析流水线拆分 | 可版本化、可降级的报告服务 | P3, P5, P6, P7 |
| P9 | Celery、API 与权限接线 | 异步研究 API 闭环 | P8 |
| P10 | 自选股、订阅、调度与资源治理 | 每日持续分析 | P9 |
| P11 | DecisionSignal 生命周期 | 信号持久化、反馈和审计 | P9 |
| P12 | SignalOutcome | 方向有效性评估 | P11 |
| P13 | ExecutionBinding 与 Eligibility | 合法策略身份和只读资格判断 | P11 |
| P14 | Decimal sizing 与原子额度预占 | 确定数量和并发风控 | P13 |
| P15 | Strategy V2 paper execution | 规范的 paper 成交及账本 | P3, P14 |
| P16 | Research -> Paper E2E | AAPL 全链路验收 | P12, P15 |
| P17 | 前端、通知与操作台 | 统一用户入口 | P10, P12, P16 |
| P18 | USStock 受控 live | IBKR/Alpaca 受控实盘 | P16, P17 |
| P19 | 历史导入与 DSA 退役 | 唯一生产入口 | P7, P10, P17, P18 |

---

## 5. 各 Plan 详细说明

### P0 · 完整仓库基线与来源治理

**目标**：建立不改变 QD 行为的可重复基线，保留真实构建、部署和质量门。

**任务**

1. 初始化 `QuantAnalyInvest/.git`，但不导入上游 Git 历史。
2. 复制完整 QuantDinger 仓库树，保留：
   - `backend_api_python/` 原目录结构；
   - `.github/`、根目录 `scripts/`、`docs/`、`ops/`、`mcp_server/`；
   - `docker-compose*.yml`、安装脚本、根 `VERSION`、安全与 OpenAPI 配置。
3. 只排除 `.git/`、缓存、日志、测试输出、构建产物、`.env`、凭据和本地数据库。
4. 暂不重命名 `backend_api_python`、`qd_` 表、Celery task 名、容器名和兼容环境变量。
5. 建立：
   - `docs/BASELINE.md`：QD `e64e1c2`、DSA `396d43a4`、Python 3.12 和测试入口；
   - `UPSTREAM_SOURCES.md`：上游仓库、commit、许可证、导入日期、导入路径；
   - `THIRD_PARTY_NOTICES.md`：QD Apache-2.0、DSA MIT 及 DSA screening/数据源声明；
   - `docs/DEPENDENCY_REPORT.md`：pandas、litellm、longbridge、exchange-calendars、Flask/FastAPI 冲突；
   - ADR 与执行 checklist。
6. 产品显示层使用 QuantAnalyInvest 名称；QD 商标和内部标识的后续处理单独记录，不混入功能迁移。

**验收**

- QD 原有离线测试、OpenAPI gate、安全扫描、版本检查均可从新仓库运行。
- Compose 基础服务能启动并通过 health check。
- `backend_api_python/` 路径相关 CI 无需临时修改即可工作。
- 来源、许可证和导入文件范围可追溯。

**回滚**：回退 P0 初始提交；两个上游仓库不受影响。

---

### P1 · PostgreSQL migration runner

**目标**：先补齐 QD 当前缺失的日期 migration 执行机制，再创建研究域表。

**任务**

1. 保留 `migrations/init.sql` 作为既有 schema bootstrap；新增有序 runner 扫描严格命名的日期 SQL。
2. 新增 `qd_schema_migrations(version, name, checksum, applied_at, duration_ms)`。
3. runner 要求：
   - 按版本排序，每个 migration 单独事务；
   - PostgreSQL advisory lock 防止多个实例并发迁移；
   - 已执行文件校验 checksum，发生漂移立即失败；
   - 失败不得记录成功版本；
   - 非法文件名、重复版本、缺失文件明确报错。
4. 修改 `app.commands.migrate`：严格执行 `init.sql -> dated migrations -> access verification`。
5. 应用启动可保持兼容模式，但生产部署必须先运行严格 migrate job；不得依赖多个 Web 实例竞争自动迁移。
6. release gate 增加空库、旧库升级、并发执行、checksum 漂移和失败恢复测试。

**验收**

- 日期 migration 在本地、CI 和部署命令中都真正执行。
- 两个 runner 并发时只应用一次。
- fresh install 与已有 QD 数据库均通过。

**回滚**：保留已应用 schema，回退应用写路径；数据库回退另写补偿 migration，不修改已发布 SQL。

---

### P2 · Research 契约、标的身份与动作映射

**目标**：建立无 IO、无订单副作用的稳定领域契约。

**任务**

1. 新建 `backend_api_python/app/services/research/` 下的 `contracts.py`、`instrument_identity.py`、`action_mapping.py`。
2. `InstrumentIdentity` 包含 market、symbol、canonical_key、exchange、asset_class、currency、timezone。
3. 一开始覆盖全部研究市场：
   - US：`AAPL -> USStock:AAPL`；
   - CN：`600519 -> CNStock:600519`；
   - HK：`hk00700/00700/0700.HK -> HKStock:0700.HK`；
   - JP：`7203.T -> JPStock:7203.T`；
   - KR：`005930.KS/035720.KQ`；
   - TW：`2330.TW/6488.TWO`，严格 suffix-only。
4. 未知市场、裸日韩台歧义代码和空 symbol 必须 fail closed，不回退 Crypto 或 CN。
5. 动作枚举：`buy/add/hold/reduce/sell/watch/avoid/alert`；建立动作 × 持仓状态全矩阵。
6. 股票 `sell` 不得变成 `open_short`；`hold/watch/avoid/alert` 不生成候选交易动作。
7. ReasonCode 使用稳定机器码，显示文案单独本地化。

**验收**

- 所有市场、别名、歧义和失败输入均有参数化测试。
- 纯函数幂等，无数据库、网络、LLM 和订单依赖。

---

### P3 · Research 数据模型与租户约束

**目标**：通过 P1 runner 落地研究域表和数据库级租户一致性。

**任务**

1. 新增日期 migration，创建 runs、run_items、reports、decision_signals、outcomes、feedback、execution_reviews。
2. 每个用户数据表包含非空 `user_id`；repository 的 user_id 只来自认证上下文。
3. 所有跨表租户引用使用复合约束，例如：
   - parent `UNIQUE(user_id, id)`；
   - child `FOREIGN KEY(user_id, report_id) REFERENCES parent(user_id, id)`。
4. 相同约束应用于 run-item、report-signal、signal-outcome、signal-feedback、signal-execution-review。
5. 金额、价格、数量、收益和费用使用 NUMERIC；时间使用 UTC `TIMESTAMPTZ`；结构化快照使用 JSONB。
6. 唯一键必须考虑 user、canonical instrument、pipeline/schema version、有效日期和 profile。
7. repository 所有 get/list/update/delete 都显式带 user_id；禁止先按 id 查出再做应用层过滤。
8. 对配置快照、Prompt 输入和报告正文分别定义敏感字段脱敏规则。

**验收**

- 数据库直接拒绝用户 A 引用用户 B 的 run/report/signal。
- 空库、旧库、幂等执行和并发唯一键测试通过。
- repository 有水平越权和枚举攻击测试。

---

### P4 · DSA legacy bridge 与能力清单

**目标**：让双跑、回退和最终退役具有可复现的技术边界。

**任务**

1. 过渡期不在 QD 进程中 import DSA；DSA 以固定 commit 构建独立 legacy service/container。
2. 定义最小只读 shadow contract：bars、quote、fundamentals、analysis report；请求必须携带明确 market/symbol 和 correlation id。
3. 环境配置：legacy base URL、认证、版本、超时、并发上限；禁止把 DSA 密钥复制到 QD 日志或研究报告。
4. CI 使用 contract fake；staging 使用固定 commit 镜像；生产 shadow 不影响主请求结果。
5. 建立 `docs/RESEARCH_CAPABILITY_MATRIX.md`，逐市场、逐能力记录：主 provider、fallback、复权、频率、时区、币种、质量字段和 DSA 当前边界。
6. 建立双跑差异阈值：日期范围、行数、最新 close、缺失率、复权、币种、时区、关键分析字段。
7. 明确开关语义：
   - 新 router 关闭时，统一平台停止使用新研究入口；
   - 旧 DSA 仍作为独立入口保留，而不是假装新平台能无条件切回一个不存在的内嵌模块。

**验收**

- 任意环境都能确认正在对照的 DSA commit/version。
- legacy service 不可用时主路径按约定继续或拒绝，绝不进入交易决策。
- bridge 有明确删除清单和退役 gate。

---

### P5 · StockDataRouter 与 USStock

**目标**：先建立按“市场 × 能力”路由的统一数据契约，并完成 US shadow。

**任务**

1. 实现 bars、quote、fundamentals、corporate_actions 能力接口；结果包含 provider、fallback_chain、as_of、timezone、currency、adjustment、quality、warnings/error_code。
2. 禁止用空列表同时表达无数据、休市、provider 故障和不支持。
3. provider 路由按能力选择，不使用一条全局 fallback 链。
4. 缓存键包含 market、canonical symbol、exchange、asset class、timeframe、range、adjustment、provider policy version。
5. 公共行情缓存不带 user_id；用户授权数据、账户数据和付费查询结果必须隔离。
6. 迁移 DSA 的超时、错误分类、熔断、冷却和质量标记，先接 yfinance US 日线/报价/基础基本面。
7. AAPL 双跑只记录差异，不进入信号和订单。

**验收**

- AAPL 离线契约测试、fallback 测试和 staging network smoke 通过。
- provider 故障、休市、空数据、不支持可明确区分。

---

### P6 · CN/HK provider 路由

**目标**：迁移 CN/HK 多源能力，但避免把 provider 名单误当成统一能力。

**任务**

1. 按能力矩阵选择 efinance、AkShare、Tushare、Baostock、PyTDX 和 yfinance；未用到的 SDK 不进入默认 worker 镜像。
2. 每个 provider 明确支持市场、bars 频率、quote、fundamentals、corporate actions、复权语义、凭据要求和限流。
3. provider 不支持某能力时返回 `not_supported`，不得静默返回空成功。
4. CN/HK 各选代表性股票、ETF、停牌和退市/无数据样本做 fixture。
5. 双跑达到预设阈值后才允许新 router 成为研究主路径。

**验收**

- `600519`、`0700.HK` 身份和行情契约通过。
- fallback 顺序可从配置版本和 provenance 复现。
- 未配置 Tushare token 等凭据时按能力降级，不拖垮整个报告。

---

### P7 · JP/KR/TW 能力迁移

**目标**：在 DSA 退役前保留现有日韩台研究能力和已声明边界。

**任务**

1. JP `.T`、KR `.KS/.KQ`、TW `.TW/.TWO` 使用 yfinance suffix-only 主路径。
2. 注册交易所、币种和时区：XTKS/JPY/Asia-Tokyo、XKRX/KRW/Asia-Seoul、XTAI/TWD/Asia-Taipei。
3. 迁移市场阶段和午休/收盘竞价语义；日历不可用时明确区分研究 fail-open 与执行 fail-closed。
4. 迁移日韩台 Prompt 市场语义，防止套用 A 股北向资金、龙虎榜等概念。
5. 迁移台股三大法人数据能力及其缓存、熔断、日期和来源署名；保留 `not_supported` 边界。
6. 将 JP/KR/TW 加入报告、DecisionSignal、outcome、筛选枚举和测试数据；仍禁止 live。
7. 文档明确 partial portfolio、实时性、FX、市场宽度和股票池未覆盖项。

**验收**

- `7203.T`、`005930.KS`、`035720.KQ`、`2330.TW`、`6488.TWO` 完成基础研究报告。
- 币种、时区、交易日、Prompt 语义和 provenance 正确。
- DSA 能力矩阵中无未处置的 JP/KR/TW 退役阻塞项。

---

### P8 · 研究分析流水线拆分

**目标**：迁移可控的研究 MVP，避免用一个大 `report_service.py` 包装整个 DSA。

**任务**

1. 拆分为 market context、technical、fundamentals、news/intelligence、LLM generation、schema validation、report rendering 七个阶段。
2. 每个阶段定义输入输出 schema、超时、错误分类、provenance 和降级策略。
3. Prompt、输出 schema、provider policy 和 pipeline 都有独立版本；版本进入幂等键和报告快照。
4. LLM 输出先通过结构化 schema 校验，再产生报告；不得从自由文本提取可信数量或订单参数。
5. 新闻和搜索内容标记来源、发布时间、抓取时间、缓存命中和可信度；防止陈旧新闻伪装成当前事实。
6. 明确 MVP 包含项和不包含项，未迁移能力继续经 P4 shadow 对比，但不形成隐式运行依赖。
7. 提供请求级取消检查和阶段预算，避免取消后继续消耗 LLM/数据源额度。

**验收**

- 单阶段失败按契约降级或使报告失败，状态可解释。
- 相同配置和 fixture 产生 schema 稳定的报告；敏感配置不入库。
- 六市场报告都带 pipeline/schema/provider/prompt 版本和数据时间。

---

### P9 · Celery、API 与权限接线

**目标**：形成异步研究闭环，并完整接入 QD 任务和授权体系。

**任务**

1. 实现 batch orchestration 和单标的任务，单 item 可重试，批次不因单项失败整体失败。
2. 在 `celery_app.py` 注册 imports、task routes、queue、soft/hard timeout、acks 和 worker heartbeat。
3. 幂等键包含 user、instrument、report type、effective date、profile、pipeline version；成功和运行中请求复用已有记录，失败生成明确 attempt。
4. Human JWT API：创建/取消 run，查询 run/items/reports；user_id 从 JWT 注入。
5. Agent Gateway 复用现有 scope：R 查询，W 创建研究/反馈；交易类动作仍要求 T。不得另建 `research:*` scope。
6. Agent 端点接入现有市场/标的 allowlist、rate limit、审计和 Idempotency-Key。
7. 更新 Flask blueprint、OpenAPI、Agent 文档、导出快照和兼容性 gate。
8. 日志携带 request_id、run_id、item_id、user_id、market、symbol、task_id，但不记录 token、Prompt 私密上下文和密钥。

**验收**

- API 返回 202，Web 进程不启动分析线程或内置 scheduler。
- 任务能被真实 worker 消费，而不是仅能直接调用 Python 函数。
- Human/Agent 水平越权、scope、限流、幂等和审计测试通过。

---

### P10 · 自选股、订阅、调度与资源治理

**目标**：支持用户真正需要的每日持续分析，并控制存储与 LLM 成本。

**任务**

1. 增加用户 watchlist、watchlist item、research subscription、schedule 和 notification preference。
2. schedule 保存用户时区、目标市场、交易日策略、运行窗口、报告 profile 和启停状态。
3. Celery beat 只触发轻量 dispatcher；dispatcher 按交易日历生成幂等 research run，分析仍进入 jobs/ai queue。
4. 数据库唯一约束保证同一用户、订阅和有效日期只由一个调度者创建任务。
5. 提供暂停、恢复、取消和错过窗口策略；取消必须在每个昂贵阶段前协作检查。
6. 建立 per-user 并发、每日 run、LLM token/金额、provider 请求额度和全局熔断。
7. 增加 usage ledger，记录 model、token、估算成本、cache hit、失败阶段，不记录密钥。
8. 定义 reports、raw context、news cache、task result、audit 的保留和归档周期；清理任务必须 tenant-safe 且可 dry-run。
9. 通知按用户订阅去重；通知失败不回滚报告或信号状态。

**验收**

- 跨时区、节假日、重复 beat、worker 重启不会重复分析和通知。
- 配额超限有稳定 reason code，不继续调用付费服务。
- 清理和归档不会删除仍被信号、审计或执行记录引用的数据。

---

### P11 · DecisionSignal 生命周期

**目标**：从结构化报告生成可审计信号，但不连接订单。

**任务**

1. 迁移 extractor/service 核心语义，去除 SQLite/SQLAlchemy 绑定。
2. 状态机：`active -> expired/invalidated/closed/archived`；查询不得隐式改状态。
3. 相反信号 invalidation 在事务内执行，并保留原因、来源报告和审计记录。
4. 数据不足、schema 校验失败、关键行情过期或市场语义不完整时，信号可保存为不可执行状态，但不得获得 execution eligibility。
5. 注册 expire task 的 import、route、beat schedule、超时和监控。
6. 提供 Human 和 Agent 查询/反馈接口，沿用 P9 授权约束。

**验收**

- 重试和并发只生成一条逻辑信号。
- 状态转换、相反信号、多租户和审计集成测试通过。
- 此 Plan 不能创建 StrategySignal、OrderIntent 或 pending order。

---

### P12 · SignalOutcome

**目标**：评估研究方向有效性，并与策略收益严格区分。

**任务**

1. 按 horizon 和市场交易日历调度 outcome；复权、币种和基准口径进入版本化配置。
2. 每个 signal/horizon 只允许一条当前评估；修订使用版本，不静默覆盖。
3. API/UI 明确区分 Research Outcome 与 Strategy Backtest/Paper PnL。
4. 缺失价格、停牌和 provider 故障使用明确状态，不计为普通失败预测。

**验收**

- 重试、晚到行情、复权和多市场交易日测试通过。
- outcome 不读取 paper/live 成交来篡改原始方向评估。

---

### P13 · ExecutionBinding 与 Eligibility

**目标**：为研究信号建立合法策略、账户和运行身份，并提供无副作用资格判断。

**任务**

1. 新增 `ResearchExecutionBinding`：user、account、真实 QD strategy deployment、market/instrument allowlist、execution mode、额度、有效期、审批策略和状态。
2. 明确一对一或多对一规则；禁止临时伪造 `strategy_id`、`strategy_run_id` 或使用 0。
3. paper/live 创建意图前必须获得真实策略运行记录；one-off paper 也通过受控 system-managed strategy/binding 创建合法 run。
4. Eligibility 检查：租户归属、binding、信号状态、数据质量、市场模式、broker 支持、持仓、账户和策略额度、集中度、交易状态、停牌、allowlist、kill switch、paper-only 和幂等。
5. dry-run 只返回决定、reason codes、输入版本和有效时间，不保留额度、不创建任何订单。
6. Eligibility 结果是诊断快照，不是随后下单的授权票据。

**验收**

- 缺少合法 binding/run/account 时明确拒绝。
- `hold/watch/avoid/alert`、无持仓 sell、股票开空、非美 live 均拒绝。
- dry-run 无订单、无额度预占、无交易状态副作用。

---

### P14 · Decimal sizing 与原子额度预占

**目标**：确定性计算数量，并在创建 OrderIntent 时原子消除 TOCTOU 风险。

**任务**

1. sizing 全程使用 Decimal，输入账户净值、可信价格、lot size、tick size、最小名义金额、集中度、账户/策略限额和当前持仓。
2. 定义统一舍入策略：数量向下到交易单位，价格按 venue tick 量化；保存量化前后值和 policy version。
3. LLM 的“满仓、半仓、梭哈”及文本数量只能作为不可信展示内容。
4. 新增 reservation 模型；真正创建 intent 时在同一事务中：
   - 锁定 signal/binding/额度行；
   - 重新执行关键 eligibility；
   - 计算 sizing；
   - 占用账户和策略额度；
   - 写唯一 OrderIntent 和 execution review。
5. 重复请求返回同一 intent/reservation；失败、取消、超时和最终拒绝释放预占；成交后转为已消费。
6. 旧 QD float 接口只在适配器边界转换，并校验往返误差不超过交易单位。

**验收**

- 并发请求不能突破账户、策略、每日或单标的额度。
- Decimal 边界、极小值、舍入、费用和 notional drift 测试通过。
- 数据库故障时不会出现有 intent 无 reservation 或重复占用。

---

### P15 · Strategy V2 paper execution

**目标**：在 QD 原生 StrategySignal/OrderIntent/pending order 链路中建立正式 paper 模式。

**任务**

1. 扩展 Strategy V2 execution mode 为 `signal/paper/live`：
   - signal：仅通知；
   - paper：只调用 PaperExecutionService；
   - live：只调用真实 broker/exchange。
2. `pending_order_worker` 增加显式 paper 分支；未知 mode 继续失败。禁止用 live + paper credentials 伪装 paper。
3. 继续使用现有 StrategySignal、OrderIntent 和 `pending_orders`，不新增第二套订单意图表。
4. 增加 paper 专用事实表：fills、cash ledger、positions/snapshots；与现有 Agent paper orders 的边界写入 ADR，暂不静默混表。
5. 定义 market/limit 订单、submitted/partial/filled/cancelled/rejected/expired 状态、成交价源、滑点、费用、交易日和取消语义。
6. 每个 pending order/fill 使用唯一 idempotency key；worker 重投、崩溃恢复不能重复成交。
7. PaperExecutionService 永远不能读取或调用真实 broker credentials/client。
8. 增加余额不足、卖出超持仓、报价陈旧、休市、部分成交、撤单和对账测试。

**验收**

- `execution_mode=paper` 能产生 paper fill、现金流水和持仓；signal 不成交，live 不被调用。
- 进程在任意事务边界崩溃并重启后不重复成交。
- paper 与 live 数据在 API、审计、指标和 UI 字段上可明确区分。

---

### P16 · Research -> Paper E2E

**目标**：完成 AAPL 从研究到模拟持仓的全链路，并证明并发安全。

**流程**

```text
ResearchRun
  -> Report
  -> DecisionSignal(active buy)
  -> ResearchExecutionBinding(paper)
  -> Eligibility recheck
  -> Decimal sizing + atomic reservation
  -> StrategySignal(open_long, spot)
  -> unique OrderIntent
  -> pending order
  -> paper fill
  -> cash/position/audit/outcome views
```

**任务与验收**

- `POST /api/research/v1/signals/{id}/paper-intents` 不信任之前的 dry-run，执行 P14 原子流程。
- 相同 signal/binding 重复或并发请求只得到一个有效 intent。
- 无持仓 sell 不能开空；非交易动作不能进入意图；过期信号和陈旧价格拒绝。
- E2E 使用 PostgreSQL、Redis/Celery worker 和真实 paper worker 分支，不以内存 mock 代替事务边界。
- 指标能从 report_id 追踪到 signal、binding、strategy run、intent、pending order、fill 和 position。
- 连续稳定运行预设观察周期后才通过 G4。

**回滚**：关闭 `RESEARCH_PAPER_BRIDGE_ENABLED`，停止创建新 intent；已存在 paper order 依照取消/完成策略收敛。

---

### P17 · 前端、通知与操作台

**目标**：提供统一且不误导用户的研究、paper 和审批体验。

**任务**

1. 接入独立 QD 前端仓库前，记录其 commit、许可证、构建和 OpenAPI client 生成流程。
2. 页面：Watchlists、Schedules、Research Runs、Reports、Decision Signals、Outcomes、Execution Bindings、Execution Review、Paper Orders/Positions。
3. 显式展示数据时间、quality、provider、缺失能力、paper/live 模式和审批状态。
4. 通知只携带必要摘要和 report/signal id；通知按钮不构成 live 授权。
5. 所有列表和详情验证多租户；前端隐藏按钮不能替代后端授权。
6. 增加管理员运行视图：队列积压、provider 熔断、LLM 用量、失败任务、migration version、paper 对账异常。

**验收**

- 桌面和移动端核心流程可完成，无 paper/live 混淆。
- 通知失败不改变研究、信号或订单状态。
- OpenAPI 兼容、权限和端到端 UI 测试通过。

---

### P18 · USStock 受控 live

**目标**：只在 QD 既有 IBKR/Alpaca 边界内开放美股实盘。

**前置条件**：G4 已通过；sandbox/paper broker、kill switch、审批、额度、lease、对账和故障演练通过。

**任务**

1. live 复用 P13 binding、P14 sizing/reservation 和 QD 原生 OrderIntent，不创建研究旁路。
2. Human JWT 必须满足用户角色、资源归属、显式 live binding、审批策略和平台 `RESEARCH_US_LIVE_BRIDGE_ENABLED`。
3. Agent/MCP 在上述条件之外还必须具有 T scope、`paper_only=false` 和 `AGENT_LIVE_TRADING_ENABLED=true`。
4. 所有 live 请求要求 USStock、受支持账户、account/market/instrument allowlist、策略 lease/fencing、kill switch、client order id 和额度预占。
5. 每笔人工确认必须绑定不可变 intent 摘要和有效期；修改标的、方向、数量、账户或价格保护后重新审批。
6. 增加 broker 提交超时/未知结果对账，禁止网络超时后直接重复下单。
7. CN/HK/JP/KR/TW live 在 API、service 和 broker adapter 三层拒绝。

**验收**

- 默认 paper-only；所有开关默认关闭。
- Human 与 Agent 授权矩阵、kill switch、并发额度和未知 broker 状态测试通过。
- sandbox 全链路可从 report 追踪到 broker order/fill，并完成对账与事故演练。

**回滚**：优先关闭平台 live kill switch，停止新订单；已有订单按运行手册撤单/对账，不通过删除数据回滚。

---

### P19 · 历史导入与 DSA 退役

**目标**：在能力等价和可恢复的前提下，使 QuantAnalyInvest 成为唯一生产入口。

**任务**

1. 导入命令默认 dry-run，支持 source counts、冲突、跳过、错误报告、legacy id mapping、断点续传和可重复执行。
2. 导入报告、信号、outcome、反馈、watchlist、schedule 和通知偏好；不导入明文密钥。
3. 无法规范化或租户归属不明确的数据进入隔离错误报告，不猜市场或用户。
4. 正式切换前完成备份恢复演练、增量补录、引用完整性和抽样内容校验。
5. 对照 P4 能力矩阵逐项签字，特别确认 JP/KR/TW、台股三大法人、持续调度、通知和历史查询。
6. 先停 DSA scheduler，再停写 API和通知；保留只读查询及回滚窗口。
7. 至少观察一个完整业务周期，且覆盖各目标市场交易日、周末/节假日和 outcome 到期任务。
8. 指标证明无重复任务、报告、信号、通知和订单后，才删除 bridge 和重复实现。
9. 删除前归档固定 DSA 镜像、配置 schema、迁移映射和运维手册。

**验收**

- DSA 不再产生生产事实数据，旧数据在统一平台可按租户查询。
- 六市场能力没有未经批准的回退。
- 已实际演练从切换点恢复 DSA 只读/写路径和撤销调度切换。
- G6 由项目负责人、运维和交易安全负责人共同确认。

---

## 6. 横切验收矩阵

每个涉及相应能力的 Plan 都必须更新以下矩阵，不能只在最终阶段补测。

| 维度 | 最低要求 |
| --- | --- |
| 多租户 | API、repository、数据库复合 FK 三层验证 |
| 幂等 | HTTP 重试、Celery 重投、worker 崩溃、并发提交 |
| 精度 | Decimal/NUMERIC、lot/tick 量化、费用和 notional drift |
| 时间 | UTC 存储、用户时区、市场时区、节假日、午休、竞价 |
| 数据质量 | stale、partial、not_supported、provider_error、no_data 可区分 |
| 安全 | Human JWT、Agent scope、allowlist、kill switch、脱敏、审计 |
| 可观察性 | request/run/task/signal/intent/order/fill correlation |
| 恢复 | DB/Redis/provider/LLM/broker 故障及未知结果处理 |
| 兼容性 | OpenAPI、migration、已有 QD 策略和 Agent 行为不回退 |
| 成本 | 用户配额、全局限额、取消、usage ledger、retention |

---

## 7. 每个 Plan 的交付报告模板

```text
1. 本 Plan 改了什么
2. 对应的 ADR / MERGE_DESIGN 契约
3. 数据库、API、任务和配置变化
4. 向后兼容性与上游来源
5. 已运行测试及结果
6. 未运行测试与原因
7. 安全、租户、精度、幂等和成本风险
8. 监控指标与告警
9. 回滚操作和数据收敛方式
10. 下一 Plan 的前置条件是否满足
```

每个 Plan 完成后等待人工确认，不因单元测试通过自动进入下一 Plan。

---

## 8. 建议实施顺序与批准边界

建议按以下主序列推进：

```text
P0 -> P1 -> P2 -> P3 -> P4 -> P5 -> P6 -> P7
   -> P8 -> P9 -> P10 -> P11 -> P12
   -> P13 -> P14 -> P15 -> P16 -> P17 -> P18 -> P19
```

其中 P1/P2、P3/P4 可在人员充足时并行分析，但仍应独立交付和审批。开发实施不得跨越对应 Gate：

- P0 未通过，不开始迁移业务代码。
- P7 未通过，不批准 DSA 退役方案。
- P10 未通过，不宣称已支持“每日持续分析”。
- P16 未通过，不开始任何研究信号 live 功能。
- P18 未通过，不开放 US 生产实盘。
- P19 未完成，不删除 DSA bridge、镜像、备份或迁移映射。

第一批建议只批准 **P0-P4**。完成完整仓库基线、migration runner、领域契约、租户约束和 legacy bridge 后，再根据真实测试结果细化 P5-P10 的工期与 provider 范围。
