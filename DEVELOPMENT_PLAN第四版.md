# QuantAnalyInvest 开发计划（第四版）

> 状态：修订后待批准执行  
> 版本：0.4  
> 日期：2026-08-13  
> 上游架构契约：[MERGE_DESIGN.md](../MERGE_DESIGN.md)  
> 第一版：[DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)  
> 第二版：[DEVELOPMENT_PLAN第二版.md](./DEVELOPMENT_PLAN第二版.md)  
> 第三版：[DEVELOPMENT_PLAN第三版.md](./DEVELOPMENT_PLAN第三版.md)  
> 目标仓库：`QuantAnalyInvest`

### 修订记录

| 版本 | 日期 | 主要变更 |
| --- | --- | --- |
| 0.1 | 2026-08-12 | 初版，把 MERGE_DESIGN Phase 0–8 拆分为 P0–P14 |
| 0.2 | 2026-08-12 | 复制完整 QD 仓库树；新增 migration runner、复合外键、DSA legacy bridge、JP/KR/TW 迁移、ExecutionBinding、原子额度预占、paper 执行模式、Human/Agent 授权区分；拆分为 P0–P19 |
| 0.3 | 2026-08-13 | P0 补回仓库根级文件（README/AGENTS/.gitignore/LICENSE）；补全 §3.2 质量门语义及 §8 批准边界 G1/G2/G3；消除 G2 与 P4 措辞冲突；统一术语 `ResearchExecutionBinding`；P0 增加 commit 漂移校验；P5/P15 前置补全并显式说明缓存策略；§3.1 开关注明对应 Plan/Gate；§6 审计拆为独立维度；P14 显式禁止复用 P13 dry-run 快照；§8 顺序图改分支结构；P19 补凭据占位处理；P13 显式说明 Eligibility 不依赖 SignalOutcome |
| 0.4 | 2026-08-13 | 高危修复：额度预占增加 `reserved→submitting→unknown/executed/released` 状态机，unknown 冻结额度不自动重试；P14 事务改造为支持外部连接或 transactional outbox，范围覆盖 reservation/execution review/OrderIntent/pending order，并增加崩溃故障注入；新增 P0A 生产基线安全加固（凭证密钥持久化、拒绝内存密钥与默认口令、重启解密演练）作为券商凭据与 P18 硬前置；功能开关区分 CI/test/staging-sandbox/production 三级启用边界；P19 解除对 P18/G5 的错误耦合并拆分为 P19A/P19B；P15 建立唯一 canonical paper ledger；P0 改用 `git archive` 生成受控基线并拒绝 dirty；P8 增加外部新闻 Prompt Injection 防护；中等修复：P1 增加旧库 baseline 策略、P14 禁止事务内网络调用、P15 增加公司行动、P19A 明确 4 周观察期、§8 修正 P6/P7 依赖 P5 |

---

## 1. 目的与修订结论

本文件将 `MERGE_DESIGN.md` 拆分为可独立实施、验证、回滚和审批的 Plan。第四版在第三版基础上修复了额度预占并发漏洞、事务边界与现有 QD 代码不兼容、生产凭据失效、开关与 Gate 循环依赖、P19 与 live 上线错误耦合、paper 双账本等重大问题。各版共同保留的核心方向：

- QuantDinger（下称 QD）作为运行、账户、策略、风控与订单底座。
- daily_stock_analysis（下称 DSA）作为多市场研究能力来源。
- PostgreSQL 是生产事实数据的唯一来源。
- 有限研究任务进入 Celery；长期交易循环继续由 QD trading worker 负责。
- 严格执行 `DecisionSignal -> ExecutionEligibility -> StrategySignal -> OrderIntent`。
- LLM 只生成研究结果，不提供可信订单数量，也不能直接下单。
- 第一阶段只允许 `USStock` 进入受控实盘；CN/HK/JP/KR/TW 仅研究和 paper。

各版相对前版修正的内容：

1. P0 改为复制完整 QD 仓库树，保留 `backend_api_python/`、CI、Compose、运维和 MCP 结构。
2. 在研究表之前先建设真正的有序 migration runner。
3. 使用复合外键保证数据库级多租户一致性。
4. 明确定义 DSA shadow/dual-run 的部署拓扑和固定版本。
5. 补齐 JP/KR/TW 能力迁移，防止 DSA 退役后功能倒退。
6. 拆分研究分析、任务接线、持续调度、资源治理和权限接入。
7. 增加 `ResearchExecutionBinding`（下文简称 binding），解决研究信号缺少合法策略、账户和运行身份的问题。
8. 增加原子额度预占，消除资格检查与创建订单之间的并发窗口。
9. 在 QD Strategy V2 中正式增加 `paper` 执行模式，不再假设 `signal` 可以产生模拟成交。
10. 区分 Human JWT 与 Agent/MCP 的实盘授权，不滥用 `AGENT_LIVE_TRADING_ENABLED`。

第三版（0.3）进一步修正第二版的文档一致性与可执行性问题：

11. P0 补回仓库根级基础文件（`README.md`、`AGENTS.md`、`.gitignore`、`LICENSE`），与 G0 验收对齐。
12. 补全 §3.2 质量门语义：G1/G2/G3 在批准边界 §8 中缺失或与前置表矛盾，现已显式列出并消除与 P4 的冲突。
13. 统一术语为 `ResearchExecutionBinding`，消除 `ExecutionBinding`/`ResearchExecutionBinding` 混用。
14. P0 增加 commit 漂移校验步骤；P5/P15 前置补全并显式声明缓存策略与传递依赖。
15. §3.1 功能开关注明对应 Plan/Gate；§6 横切矩阵把审计拆为独立维度。
16. P14 显式禁止复用 P13 dry-run 快照；P13 显式说明 Eligibility 不依赖 SignalOutcome。

第四版（0.4）修复的严重问题与结构性问题：

17. 额度预占状态机改为 `reserved -> submitting -> unknown/executed/released`；`unknown` 冻结额度，仅 rejected/cancelled/expired/未提交成功才释放，对账确认成交转 consumed，禁止 unknown 自动重试下单（消除「超时释放→重复实盘单」）。
18. P14 原子事务与现有 QD 代码解耦：明确改造 service 支持外部连接/cursor 或采用 transactional outbox，事务范围覆盖 reservation、execution review、OrderIntent、pending order，并增加逐步崩溃故障注入测试。
19. 新增 P0A「生产基线安全加固」：生产缺持久化 `CREDENTIAL_ENCRYPTION_KEY` 拒绝启动、禁止内存密钥、非开发环境拒绝默认管理员密码，作为券商凭据保存与 P18 的硬前置。
20. 功能开关区分 CI/test、staging/sandbox、production 三级启用边界，消除「开关要 Gate 通过才开、Gate 又要开关验收」的循环依赖。
21. P19 解除对 P18/G5 的错误耦合，拆分为 P19A（数据迁移与切换候选）与 P19B（停写与退役），使 DSA 退役与是否开放实盘相互独立。
22. P15 建立唯一 `PaperExecutionService` 与 canonical paper ledger，Agent quick-trade 与 Research Strategy 共用，避免两个事实账本导致风控基于错误持仓。
23. P0 改用 `git archive <recorded-commit>` 生成受控基线，要求工作树干净或产出 dirty manifest，本地差异单独成 patch/哈希并人工批准，不凭 HEAD 相同认定源码相同。
24. P8 增加外部新闻/搜索内容 Prompt Injection 防护：不可信数据不是指令、系统规则与外部内容隔离、报告阶段禁调交易/凭据/写工具、外部文本约束与恶意新闻/伪造公告回归测试。

第四版同时落实中等风险补充：

25. P1 定义既有 QD 数据库首次接入 migration ledger 的 baseline 策略。
26. P14 明确事务内禁止行情/券商/账户网络调用，先取带 version/as_of 快照再在事务内锁定校验。
27. P15 增加公司行动（拆股、分红、合股、退市），避免长期 paper 持仓失真。
28. P19A 将「至少一个完整业务周期」量化为至少 4 周并覆盖月末、节假日与各市场交易日。
29. §8 依赖图修正 P6/P7 显式依赖 P5，与 §4 前置表一致。

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
| D-009 | 生产基线安全加固（P0A）是保存券商凭据与任何 live 的硬前置 | 生产缺持久化加密密钥拒绝启动、禁止内存密钥、拒绝默认管理员口令 |
| D-010 | 额度预占引入 `unknown` 状态，券商结果未知时冻结额度 | 仅 rejected/cancelled/expired/未提交成功释放，禁止 unknown 自动重试下单 |
| D-011 | Paper 只有一个 canonical ledger，Agent 与 Research 共用 | 唯一 `PaperExecutionService`；迁移或废弃 `qd_agent_paper_orders`，禁止跨账本汇总风控 |
| D-012 | DSA 退役与是否开放 US 实盘相互独立 | P19 不依赖 P18/G5，拆为 P19A（迁移与切换候选）与 P19B（停写与退役） |

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

每个开关的默认值、所有者、删除条件和覆盖测试见执行规则第 10 条。开关与 Plan/Gate 的对应关系：

| 开关 | 默认 | 控制的能力入口 | 启用前置 | 删除条件 |
| --- | --- | --- | --- | --- |
| `RESEARCH_DOMAIN_ENABLED` | false | 整个研究域 API 与任务（P8/P9） | G1 通过 | 研究域成为唯一入口且 DSA 退役（P19B/G6） |
| `RESEARCH_NEW_DATA_ROUTER_ENABLED` | false | 新 StockDataRouter 成为研究主路径（P5–P7） | P5 双跑达标 | DSA 数据路径停用（P19B） |
| `RESEARCH_DUAL_RUN_ENABLED` | false | 新旧路由同时产出对照（P4/P5） | P4 bridge 就绪 | G2 双跑指标达标后可关闭对照 |
| `RESEARCH_SIGNAL_PERSIST_ENABLED` | false | DecisionSignal 持久化（P11） | G1 通过、P11 就绪 | 信号链路稳定且无回退需求 |
| `RESEARCH_SCHEDULER_ENABLED` | false | Celery beat 调度每日研究（P10） | G2 通过 | 每日持续分析稳定运行（P10/G2） |
| `RESEARCH_PAPER_BRIDGE_ENABLED` | false | 研究信号进入 paper 意图（P16） | G4 通过 | paper 链路稳定后转为常驻能力 |
| `RESEARCH_US_LIVE_BRIDGE_ENABLED` | false | 研究信号进入 US live（P18） | G5 通过 | live 稳定后由更高优先级 kill switch 取代 |

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
- 开关的启用必须与其上表「启用前置」中标注的 Gate/Plan 一致；不得在对应 Gate 未通过前打开。

### 3.1.1 开关的启用边界（避免与 Gate 循环依赖）

开关与 Gate 的验收存在「先有鸡还是先有蛋」关系：Gate 的验收需要开关开启后跑通对应链路，而规则又要求 Gate 通过后才能开开关。为此按**环境**区分启用边界：

| 环境 | 开关启用规则 |
| --- | --- |
| CI / test | 可无条件启用（用 fixture/recording 离线验证），不受 Gate 限制 |
| staging / sandbox | 可在对应 Gate 验收期间启用，用于双跑、E2E 和故障演练；不面向真实资金 |
| production | 只能在对应 Gate 通过后启用；live 类开关还须满足 P0A 与 kill switch 前置 |

- 每个开关必须携带 `env` 维度（`test/staging/production`），同一代码在 staging 与 production 的默认值可不同。
- 开关开启不代表 Gate 通过；Gate 通过以验收清单为准，开关只是 Gate 验收的手段而非证明。
- production 开启 `RESEARCH_SCHEDULER_ENABLED` 需 G2 通过；开启 `RESEARCH_PAPER_BRIDGE_ENABLED` 需 G4 通过；开启 `RESEARCH_US_LIVE_BRIDGE_ENABLED` 需 G5 通过且 P0A 已交付。
- 不因「staging 曾开启」推断 production 已通过 Gate；production 开关状态变更单独审批并留审计。

### 3.2 阶段质量门

| Gate | 通过条件 | 阻止的后续工作 |
| --- | --- | --- |
| G0 基线门 | 完整 QD 构建、CI、Compose、OpenAPI、安全检查可运行 | 所有业务迁移 |
| G0A 生产安全门 | 生产凭证加密持久化、拒绝内存密钥、拒绝默认管理员口令、重启解密演练通过（P0A） | 保存券商凭据与任何 live（P18） |
| G1 数据门 | migration runner、租户约束、数据契约通过 | 研究 API 与任务（P8/P9 及之后的研究域写入） |
| G2 研究门 | 六市场研究、调度、配额、双跑指标达标 | 研究→订单桥（P16 起）与 DSA 切换候选/退役（P19A/P19B）；不阻止 P4 的只读 shadow bridge |
| G3 信号门 | 信号生命周期、审计和隔离通过 | Eligibility 与 ResearchExecutionBinding（P13 及之后的订单前置） |
| G4 Paper 门 | 策略身份、原子额度、paper 账本及 AAPL E2E 通过 | 任意 live |
| G5 Live 门 | sandbox、人工审批、kill switch、对账和故障演练通过 | US 生产实盘 |
| G6 退役门 | 功能等价、数据迁移、完整观察周期和回滚演练通过 | 停用 DSA |

> 说明：G0A 是 P0A 的安全门，先于 G1 之前的业务迁移即可并行推进，但必须先于任何券商凭据保存与 P18 live 交付。G2「阻止订单桥」特指研究信号进入订单的桥接（P16 `RESEARCH_PAPER_BRIDGE_ENABLED` 起），**不**包括 P4 的只读 DSA shadow bridge。P4 仅依赖 P0，是早期建立对照基线的 Plan，不受 G2 约束。G3 评估的是信号生命周期本身（P11），SignalOutcome（P12）的评估结果不作为 G3 的通过条件，也不被 P13 Eligibility 读取（见 P13 说明）。

---

## 4. Plan 总览

| # | 名称 | 主要交付 | 前置 |
| --- | --- | --- | --- |
| P0 | 完整仓库基线与来源治理 | 可运行的完整 QD 基线 | - |
| P0A | 生产基线安全加固 | 凭证加密持久化、无内存密钥、无默认口令 | P0 |
| P1 | PostgreSQL migration runner | 有序、并发安全、可审计迁移 | P0 |
| P2 | Research 契约、标的身份与动作映射 | 六市场身份和纯函数规则 | P0 |
| P3 | Research 数据模型与租户约束 | 研究表、复合外键、repository | P1, P2 |
| P4 | DSA legacy bridge 与能力清单 | 可复现 shadow/dual-run | P0 |
| P5 | StockDataRouter 与 USStock | US 行情契约和双跑 | P2, P4（缓存先用 Redis/内存，研究表落库见 P3，不阻塞本 Plan） |
| P6 | CN/HK provider 路由 | 按能力的 fallback | P5 |
| P7 | JP/KR/TW 能力迁移 | 防止非中美港能力回退 | P5 |
| P8 | 研究分析流水线拆分 | 可版本化、可降级的报告服务 | P3, P5, P6, P7 |
| P9 | Celery、API 与权限接线 | 异步研究 API 闭环 | P8 |
| P10 | 自选股、订阅、调度与资源治理 | 每日持续分析 | P9 |
| P11 | DecisionSignal 生命周期 | 信号持久化、反馈和审计 | P9 |
| P12 | SignalOutcome | 方向有效性评估 | P11 |
| P13 | ResearchExecutionBinding 与 Eligibility | 合法策略身份和只读资格判断 | P11（G3 守护，见 §3.2/§8） |
| P14 | Decimal sizing 与原子额度预占 | 确定数量和并发风控 | P13 |
| P15 | Strategy V2 paper execution | 规范的 paper 成交及 canonical ledger | P3, P13, P14 |
| P16 | Research -> Paper E2E | AAPL 全链路验收 | P12, P13, P14, P15 |
| P17 | 前端、通知与操作台 | 统一用户入口 | P10, P12, P16 |
| P18 | USStock 受控 live | IBKR/Alpaca 受控实盘 | P16, P17, P0A（安全前置） |
| P19A | 历史导入与切换候选 | 数据迁移完成、可切换候选态 | P7, P10, P17（不依赖 P18/G5） |
| P19B | DSA 停写与退役 | DSA 停写、bridge 删除与归档 | P19A、G6 人工批准 |

---

## 5. 各 Plan 详细说明

### P0 · 完整仓库基线与来源治理

**目标**：建立不改变 QD 行为的可重复基线，保留真实构建、部署和质量门。

**任务**

1. 初始化 `QuantAnalyInvest/.git`，但不导入上游 Git 历史。
2. 用 `git archive <recorded-commit> | tar -x` 从已记录 commit 生成受控基线（QD `e64e1c2`、DSA `396d43a4`），**不直接复制上游工作树**。保留：
   - `backend_api_python/` 原目录结构；
   - `.github/`、根目录 `scripts/`、`docs/`、`ops/`、`mcp_server/`；
   - `docker-compose*.yml`、安装脚本、根 `VERSION`、安全与 OpenAPI 配置。
3. 只排除 `.git/`、缓存、日志、测试输出、构建产物、`.env`、凭据和本地数据库；通过新建或合并的 `.gitignore`（合并 QD 与 DSA 忽略项，显式覆盖 `.env*`、`__pycache__/`、`.pytest_cache/`、`*.log`、本地 SQLite、`node_modules/`、构建产物）固化这些排除规则，不依赖人工记忆。
4. 暂不重命名 `backend_api_python`、`qd_` 表、Celery task 名、容器名和兼容环境变量。
5. 建立仓库根级基础文件（第二版遗漏，第三版补回）：
   - `README.md`：统一平台定位、与 QD/DSA 的关系、构建与测试入口；
   - `AGENTS.md`：开发代理规则，引用 MERGE_DESIGN.md 与本开发计划；
   - `.gitignore`：见任务 3；
   - `LICENSE`：后端沿用 QD Apache License 2.0 全文（前端源码接入前单独审核，不套用此结论）；
   - `THIRD_PARTY_NOTICES.md`：QD Apache-2.0、DSA MIT 及 DSA `src/services/screening` 数据源声明。
6. 建立：
   - `docs/BASELINE.md`：QD `e64e1c2`、DSA `396d43a4`、Python 3.12 和测试入口；
   - `UPSTREAM_SOURCES.md`：上游仓库、commit、许可证、导入日期、导入路径；
   - `docs/DEPENDENCY_REPORT.md`：pandas、litellm、longbridge、exchange-calendars、Flask/FastAPI 冲突；
   - ADR 与执行 checklist。
7. 执行前校验上游 HEAD 与记录 commit 一致，并执行 `git status --porcelain`：
   - 工作树必须干净；若存在未提交改动，**不得**静默带入基线；
   - 若确有需要的本地改动，必须单独生成 patch + 逐文件哈希 + 人工批准记录，并与受控基线分开放置，注明来源与批准人；
   - 仅凭「HEAD 与记录 commit 相同」不足以证明源码相同，必须以工作树干净或已批准的 dirty manifest 为准。
8. 若上游 HEAD 与记录 commit 漂移，必须更新 BASELINE.md 并记录漂移原因和新 commit，不得在未记录的情况下静默采用新 HEAD。
9. 产品显示层使用 QuantAnalyInvest 名称；QD 商标和内部标识的后续处理单独记录，不混入功能迁移。

**验收**

- 仓库根存在 `README.md`、`AGENTS.md`、`.gitignore`、`LICENSE`、`THIRD_PARTY_NOTICES.md`，且 `.gitignore` 覆盖任务 3 列出的全部排除项。
- 基线由 `git archive <recorded-commit>` 生成；上游 `git status --porcelain` 为空，或已产出经批准的 dirty manifest + patch + 文件哈希。
- `docs/BASELINE.md` 记录的 commit 与执行时上游 HEAD 一致（或在漂移时已显式更新并记录原因）。
- QD 原有离线测试、OpenAPI gate、安全扫描、版本检查均可从新仓库运行。
- Compose 基础服务能启动并通过 health check。
- `backend_api_python/` 路径相关 CI 无需临时修改即可工作。
- 来源、许可证和导入文件范围可追溯。

**回滚**：回退 P0 初始提交；两个上游仓库不受影响。

---

### P0A · 生产基线安全加固

**目标**：修复 QD 现有生产凭据加密与默认口令隐患，作为保存任何券商凭据及 P18 live 的硬前置（D-009 / G0A）。

**背景**（已核实上游代码）：

- `docker-compose.production.yml` 将 `.env` 只读挂载为 `/app/.env:ro`；
- `docker-entrypoint.sh` 在缺少 `CREDENTIAL_ENCRYPTION_KEY` 且 `.env` 不可写时，生成**内存**密钥；
- 二者叠加导致生产重启后轮换加密密钥，已有券商凭据无法解密；
- `settings.py` 默认管理员密码为 `123456`。

**任务**

1. 生产环境缺少持久化 `CREDENTIAL_ENCRYPTION_KEY` 时**拒绝启动**，并输出明确错误，不降级为内存密钥。
2. 禁止任何环境（含 staging/sandbox）在缺少持久化密钥时生成临时内存密钥用于券商凭据加密；开发环境如需临时密钥必须显式 `ALLOW_INSECURE_DEV_KEY=true` 且不得用于真实凭据。
3. 非开发环境（production/staging）检测到默认管理员密码 `123456`（或 `ADMIN_PASSWORD` 未显式设置）时拒绝启动。
4. 分离凭证加密密钥与 JWT/session 密钥的生成、轮换和备份流程，避免一方轮换破坏另一方。
5. 统一默认 Compose 路径与 production overlay 的安全配置，消除「只读 .env 挂载 vs entrypoint 写密钥」冲突；生产 overlay 必须提供密钥注入的安全路径（如 Docker secret / 挂载独立密钥文件）。
6. 提供密钥轮换手册：旧密钥解密 → 新密钥重加密 → 原子切换 → 验证，支持回滚到旧密钥。

**验收**

- 生产容器在缺少持久化密钥时启动失败，而非静默生成内存密钥。
- staging/production 使用默认管理员密码时启动失败。
- 完成「保存券商凭据 -> 重启全部容器 -> 成功解密」验收：重启后凭据可解密，且密钥未变化。
- 默认 Compose 路径与 production overlay 安全配置一致，无只读/写冲突。
- 密钥轮换可逆，轮换失败可回退到旧密钥继续解密。

**回滚**：回退 P0A 提交；恢复原有 QD 生产 overlay 行为前必须确认无已加密凭据。

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
7. 定义既有 QD 数据库首次接入 migration ledger 的 baseline 策略：以当前 `init.sql` 已落地的 schema 为基线，将已有 schema 标记为 `baseline`（不重复执行已存在的表），后续日期 migration 从基线之后开始；避免旧 schema 被当成「未迁移的空库」而重复建表或失败。

**验收**

- 日期 migration 在本地、CI 和部署命令中都真正执行。
- 两个 runner 并发时只应用一次。
- fresh install 与已有 QD 数据库均通过；已有 QD 数据库首次接入 ledger 时被正确识别为 baseline 而非空库。

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
6. 缓存存储层在本 Plan 使用 Redis/内存（公共行情）与进程内结构（provenance/quality 元数据），**不依赖 P3 的研究域表**；后续若需落库审计，在 P3 之后的独立 Plan 中处理，不阻塞本 Plan。
7. 迁移 DSA 的超时、错误分类、熔断、冷却和质量标记，先接 yfinance US 日线/报价/基础基本面。
8. AAPL 双跑只记录差异，不进入信号和订单。

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
6. **外部新闻/搜索/公告内容一律视为不可信数据而非指令**（Prompt Injection 防护）：
   - 系统规则、交易约束与外部内容分离开来，外部文本只能作为数据填入受限字段，不得进入系统提示词的可执行区；
   - 报告生成阶段禁调交易、凭据读取和任何写操作工具（工具白名单默认拒绝，逐一审批）；
   - 对外部文本施加长度、编码、隐藏指令（如「忽略之前指令」「你现在是…」）、来源白名单约束，超限或异常直接标记为不可信并降级；
   - schema 校验只保证 JSON 结构正确，不视为 Prompt Injection 防护，两者都必须具备。
7. 明确 MVP 包含项和不包含项，未迁移能力继续经 P4 shadow 对比，但不形成隐式运行依赖。
8. 提供请求级取消检查和阶段预算，避免取消后继续消耗 LLM/数据源额度。

**验收**

- 单阶段失败按契约降级或使报告失败，状态可解释。
- 相同配置和 fixture 产生 schema 稳定的报告；敏感配置不入库。
- 六市场报告都带 pipeline/schema/provider/prompt 版本和数据时间。
- 恶意新闻、伪造公告、隐藏指令的 Prompt Injection 回归测试通过，且不改变 buy/sell 信号方向；报告生成期间无交易/凭据/写工具被调用。

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

### P13 · ResearchExecutionBinding 与 Eligibility

**目标**：为研究信号建立合法策略、账户和运行身份，并提供无副作用资格判断。

**任务**

1. 新增 `ResearchExecutionBinding`：user、account、真实 QD strategy deployment、market/instrument allowlist、execution mode、额度、有效期、审批策略和状态。
2. 明确一对一或多对一规则；禁止临时伪造 `strategy_id`、`strategy_run_id` 或使用 0。
3. paper/live 创建意图前必须获得真实策略运行记录；one-off paper 也通过受控 system-managed strategy/binding 创建合法 run。
4. Eligibility 检查：租户归属、binding、信号状态、数据质量、市场模式、broker 支持、持仓、账户和策略额度、集中度、交易状态、停牌、allowlist、kill switch、paper-only 和幂等。**Eligibility 不读取 SignalOutcome（P12）**：outcome 是研究方向有效性评估，不作为下单资格依据，避免「历史预测准」被当作下单授权。
5. dry-run 只返回决定、reason codes、输入版本和有效时间，不保留额度、不创建任何订单。
6. Eligibility 结果是诊断快照，不是随后下单的授权票据。

**验收**

- 缺少合法 binding/run/account 时明确拒绝。
- `hold/watch/avoid/alert`、无持仓 sell、股票开空、非美 live 均拒绝。
- dry-run 无订单、无额度预占、无交易状态副作用。
- Eligibility 结果与 SignalOutcome 状态相互独立，无数据依赖。

---

### P14 · Decimal sizing 与原子额度预占

**目标**：确定性计算数量，并在创建 OrderIntent 时原子消除 TOCTOU 风险。

**任务**

1. sizing 全程使用 Decimal，输入账户净值、可信价格、lot size、tick size、最小名义金额、集中度、账户/策略限额和当前持仓。
2. 定义统一舍入策略：数量向下到交易单位，价格按 venue tick 量化；保存量化前后值和 policy version。
3. LLM 的“满仓、半仓、梭哈”及文本数量只能作为不可信展示内容。
4. 事务边界与现有 QD 代码兼容（已核实 `order_intents.py` 与 `live_execution.py` 各自 `with get_db_connection()` 开启独立连接）：必须二选一并明确落地——
   - 方案 A：改造 `OrderIntentService`、`pending_orders` 写路径等 service 支持**外部传入 connection/cursor**，由 P14 统一事务控制；
   - 方案 B：采用 **transactional outbox**（先写 outbox 与业务状态在同一事务，再由后台 worker 消费 outbox 生成 pending order）。
   事务范围至少覆盖：reservation、execution review、OrderIntent、pending order（或 outbox 记录）。
5. 新增 reservation 模型；真正创建 intent 时在同一事务中：
   - 锁定 signal/binding/额度行；
   - 重新执行关键 eligibility（不得复用 P13 dry-run 的快照结果作为事务内 eligibility 依据，必须在事务内重新求值）；
   - 计算 sizing；
   - 占用账户和策略额度；
   - 写唯一 OrderIntent 和 execution review。
6. **事务内禁止行情、券商或账户网络调用**：进入事务前先取得带 `version/as_of` 的确定性快照，事务内只锁定并校验快照版本未变化；版本漂移则回滚并重新快照。
7. reservation 状态机（消除「超时释放→重复实盘单」）：
   - 合法状态：`reserved -> submitting -> unknown/executed/released`；
   - `unknown`（券商结果未知，可能已接单但响应丢失）**冻结额度**，禁止自动重试下单；
   - 只有确认 `rejected/cancelled/expired/未提交成功` 才释放额度；
   - 对账确认成交后转 `consumed`（不再释放）；
   - 任何从 `unknown` 的推进都必须先经对账确认券商侧最终状态，不得仅凭本地超时判定。
8. 重复请求返回同一 intent/reservation；失败、取消、超时和最终拒绝释放预占；成交后转为已消费。
9. 增加「每一步写入后进程崩溃」的故障注入测试：在 reservation 写后、OrderIntent 写后、pending order/outbox 写后分别 kill 进程并重启，验证不会出现有 intent 无 reservation、重复占用或额度泄漏。
10. 旧 QD float 接口只在适配器边界转换，并校验往返误差不超过交易单位。

**验收**

- 并发请求不能突破账户、策略、每日或单标的额度。
- Decimal 边界、极小值、舍入、费用和 notional drift 测试通过。
- 数据库故障或逐步崩溃时不会出现有 intent 无 reservation 或重复占用。
- `unknown` 状态下额度被冻结，不释放、不自动重试；只有对账确认 rejected/cancelled/expired/未提交才释放。
- 事务内无行情/券商/账户网络调用（以代码审查或连接追踪验证）。

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
4. 建立**唯一的 `PaperExecutionService` 与 canonical paper ledger**（fills、cash ledger、positions/snapshots）：
   - Agent quick-trade 与 Research Strategy 的 paper 都调用同一个 `PaperExecutionService`，共享同一现金与持仓事实；
   - 迁移或废弃 `qd_agent_paper_orders` 旧表，不保留第二个事实账本；
   - 若确有隔离需求，必须使用明确的 paper portfolio/account 维度，禁止跨账本汇总风控（eligibility 与 sizing 必须基于 canonical ledger 的单一账本持仓）。
5. 定义 market/limit 订单、submitted/partial/filled/cancelled/rejected/expired 状态、成交价源、滑点、费用、交易日和取消语义。
6. 每个 pending order/fill 使用唯一 idempotency key；worker 重投、崩溃恢复不能重复成交。
7. PaperExecutionService 永远不能读取或调用真实 broker credentials/client。
8. 增加公司行动处理（拆股、分红、合股、退市），否则长期 paper 持仓会失真；未处理公司行动的市场/标的明确标记 `not_supported`，不得静默用错误持仓继续风控。
9. 增加余额不足、卖出超持仓、报价陈旧、休市、部分成交、撤单和对账测试。

**验收**

- `execution_mode=paper` 能产生 paper fill、现金流水和持仓；signal 不成交，live 不被调用。
- Agent quick-trade 与 Research paper 读取同一 canonical ledger，无第二个事实账本导致的持仓不一致。
- 进程在任意事务边界崩溃并重启后不重复成交。
- paper 与 live 数据在 API、审计、指标和 UI 字段上可明确区分。
- 拆股/分红/合股/退市样本测试通过，公司行动后持仓与现金正确调整。

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

**前置条件**：G0A 已通过（P0A 生产基线安全加固交付）；G4 已通过；sandbox/paper broker、kill switch、审批、额度、lease、对账和故障演练通过。

**任务**

1. live 复用 P13 binding、P14 sizing/reservation 和 QD 原生 OrderIntent，不创建研究旁路。
2. Human JWT 必须满足用户角色、资源归属、显式 live binding、审批策略和平台 `RESEARCH_US_LIVE_BRIDGE_ENABLED`。
3. Agent/MCP 在上述条件之外还必须具有 T scope、`paper_only=false` 和 `AGENT_LIVE_TRADING_ENABLED=true`。
4. 所有 live 请求要求 USStock、受支持账户、account/market/instrument allowlist、策略 lease/fencing、kill switch、client order id 和额度预占。
5. 每笔人工确认必须绑定不可变 intent 摘要和有效期；修改标的、方向、数量、账户或价格保护后重新审批。
6. 增加 broker 提交超时/未知结果对账，禁止网络超时后直接重复下单；券商结果未知时进入 P14 定义的 `unknown` 状态冻结额度，先对账确认最终状态再决定释放或转 consumed，**禁止 unknown 自动重试下单**。
7. CN/HK/JP/KR/TW live 在 API、service 和 broker adapter 三层拒绝。

**验收**

- 默认 paper-only；所有开关默认关闭。
- Human 与 Agent 授权矩阵、kill switch、并发额度和未知 broker 状态（unknown 冻结额度、不自动重试）测试通过。
- sandbox 全链路可从 report 追踪到 broker order/fill，并完成对账与事故演练。

**回滚**：优先关闭平台 live kill switch，停止新订单；已有订单按运行手册撤单/对账，不通过删除数据回滚。

---

### P19A · 历史导入与切换候选

**目标**：完成历史数据迁移，使 QuantAnalyInvest 达到「可作为唯一生产入口」的候选态。**不依赖 P18/G5**——即使长期不开放 US 实盘，本 Plan 仍可推进，DSA 退役与是否开实盘相互独立（D-012）。

**前置**：P7、P10、P17（§4）；G2 研究门通过。**不依赖 P18 或 G5。**

**任务**

1. 导入命令默认 dry-run，支持 source counts、冲突、跳过、错误报告、legacy id mapping、断点续传和可重复执行。
2. 导入报告、信号、outcome、反馈、watchlist、schedule 和通知偏好；不导入明文密钥。历史配置中的凭据字段（API key、token、secret）一律替换为占位符或 null 并在错误报告中标记，不猜测归属，不保留任何可能生效的凭据值。
3. 无法规范化或租户归属不明确的数据进入隔离错误报告，不猜市场或用户。
4. 正式切换前完成备份恢复演练、增量补录、引用完整性和抽样内容校验。
5. 对照 P4 能力矩阵逐项签字，特别确认 JP/KR/TW、台股三大法人、持续调度、通知和历史查询。
6. 观察至少 **4 周** 的生产并行期，并覆盖月末/月初、周末、节假日以及各目标市场交易日、outcome 到期任务。
7. 指标证明无重复任务、报告、信号、通知后，产出「切换候选」报告并提交 G6 人工批准。

**验收**

- 历史数据在统一平台可按租户查询，导入可重复执行且断点续传。
- 六市场能力无未经批准的回退；4 周并行期指标达标。
- 已产出 G6 人工批准所需的切换候选材料（能力矩阵签字、并行指标、备份与回滚预案）。
- **本 Plan 不产生任何停写或删除动作。**

---

### P19B · DSA 停写与退役

**目标**：在 G6 人工批准后执行 DSA 停写、删除 bridge 与归档，使 QuantAnalyInvest 成为唯一生产入口。

**前置**：P19A 完成且 **G6 人工批准通过**。

**任务**

1. 先停 DSA scheduler，再停写 API 和通知；保留只读查询及回滚窗口。
2. 切换为只读期间继续对账，确认无新的生产事实数据产生。
3. 删除前归档固定 DSA 镜像、配置 schema、迁移映射和运维手册。
4. 删除 bridge 和重复实现；删除前确认无引用（任务、信号、通知、订单）。
5. 完成从切换点恢复 DSA 只读/写路径和撤销调度切换的演练。

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
| 安全 | Human JWT、Agent scope、allowlist、kill switch、敏感字段脱敏 |
| 审计 | request/run/signal/intent/order/fill 全链路可追溯、不可篡改、按租户隔离可查询 |
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

建议按以下依赖关系推进（实际依赖以 §4 前置表为准；同一层级的 Plan 在人员充足时可并行分析，但仍应独立交付和审批）：

```text
P0 ─ P0A ─(G0A 生产安全门)

P0 ─ P1 ─┐
P0 ─ P2 ─┴─ P3 ─┐
P0 ─ P4 ─ P5 ─┬─ P6 ─┐
              └─ P7 ─┤
                      └─ P8 ─ P9 ─┬─ P10 ──────────────┐
                                    └─ P11 ─┬─ P12 ────┤
                                             └─ P13 ─ P14 ─ P15 ─┐
                                                                   └─ P16 ─ P17 ─┬─ P18 ─(G5)
                                                                                  └─ P19A ─(G6 人工批准)─ P19B
```

> 上图中 P6/P7 显式位于 P5 之下（依赖 P5），与 §4 前置表一致；P0A 与 P1/P2/P4 并行；P19A 不依赖 P18。

Gate 与 Plan 的主要对应关系（精确阻止范围见 §3.2）：

- **G0** 在 P0 后：完整 QD 基线可运行。
- **G0A** 在 P0A 后：生产凭证加密持久化、无内存密钥、无默认管理员口令、重启解密演练通过。
- **G1** 在 P1/P3 后：migration runner、租户约束、数据契约通过。
- **G2** 在 P5–P10 后：六市场研究、调度、配额、双跑达标。
- **G3** 在 P11 后：信号生命周期、审计、隔离通过。
- **G4** 在 P15/P16 后：paper 身份、原子额度、AAPL E2E 通过。
- **G5** 在 P18 后：sandbox、审批、kill switch、对账、故障演练通过。
- **G6** 在 P19A 切换候选 + 4 周观察后由人工批准；P19B 退役动作在 G6 批准后执行。

P1/P2、P3/P4、P0A 在人员充足时可并行分析。

开发实施不得跨越对应 Gate：

- **G0 未通过（P0）**，不开始迁移业务代码。
- **G0A 未通过（P0A）**，不保存任何券商凭据、不开始任何 live（P18）。
- **G1 未通过（P1/P3 后）**，不开始研究 API 与任务（P8/P9 及之后的研究域写入）。
- **G2 未通过（P5–P10 后）**，不批准研究→订单桥（P16 起）与 DSA 切换候选（P19A）；P4 的只读 shadow bridge 不受此限制。
- **G3 未通过（P11 后）**，不开始 Eligibility 与 ResearchExecutionBinding（P13 及之后的订单前置）。
- **G4 未通过（P15/P16 后）**，不开始任何研究信号 live 功能。
- **G5 未通过（P18 后）**，不开放 US 生产实盘。
- **G6 未批准（P19A 后）**，不执行 DSA 停写、不删除 bridge、镜像、备份或迁移映射（P19B）。

> 注：第二版的批准边界以 Plan 编号描述 Gate，与 §3.2 定义的 Gate 编号不一致且遗漏 G1/G2/G3；第三版统一为 Gate 编号；第四版新增 G0A，并将 G6 从「退役完成后的确认」修正为「P19A 候选后、P19B 停写前的人工批准」，使 DSA 退役与 US live 解耦。

第一批建议只批准 **P0、P0A、P1–P4**。完成完整仓库基线、生产安全加固、migration runner、领域契约、租户约束和 legacy bridge 后，再根据真实测试结果细化 P5–P10 的工期与 provider 范围。
