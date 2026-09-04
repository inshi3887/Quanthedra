# P14 Safe Profile

> 状态：开发期强制安全档案  
> 版本：1.0  
> 日期：2026-08-15  
> 适用计划：[DEVELOPMENT_PLAN第八版.md](./DEVELOPMENT_PLAN第八版.md) 的 P14、P15、P16、P18 及所有共享订单执行路径  
> 目的：允许基础功能和 paper 链路先行开发，同时在 P14/P18 最终设计完全收敛前阻止不安全的 live 行为

## 1. 文档优先级

本文件不改变 QuantAnalyInvest 的产品目标，只收紧第八版 P14 中仍有歧义的交易安全边界。

发生冲突时，实施优先级为：

1. 当前用户明确指令；
2. 本文件；
3. `DEVELOPMENT_PLAN第八版.md`；
4. `MERGE_DESIGN.md`；
5. 现有代码行为。

不得用“兼容现有行为”为理由绕过本文件。现有 live stale `processing -> pending`、现场重新生成 client order id、网络异常后直接释放 reservation 等行为必须按本文件 fail closed。

## 2. 当前允许的开发范围

可以开发并验收：

- P0、P0A、P1-P13；
- P14 的 Decimal sizing、账户注册、原子 reservation、状态机、事件账本和对账基础设施；
- P15 canonical paper ledger；
- P16 Research -> Paper E2E；
- P17 前端、通知和操作台；
- 使用隔离 sandbox/fake broker 的 P18 代码和故障演练。

在 G5 正式通过前必须保持：

- `RESEARCH_US_LIVE_BRIDGE_ENABLED=false`；
- 不向真实 broker 提交 live 新开仓订单；
- 不允许跨租户共享真实 broker account；
- 不允许 `unknown` 或 `overrun_locked` 自动释放、自动重试或自动解除 risk lock。

## 3. 首期账户模型

### 3.1 单租户硬边界

首期只支持一个真实 broker account 归属一个 tenant：

```text
(broker, environment, broker_account_id) -> exactly one tenant_id
```

要求：

- 多个 credential 可以映射同一个真实账户，但必须属于同一 tenant；
- 数据库必须以稳定 `broker_account_key` 和唯一约束强制上述关系；
- 检测到跨租户共享时，该账户立即进入 `ACCOUNT_OWNERSHIP_CONFLICT_LOCK`；
- conflict lock 下拒绝新开仓，只允许读取、对账、撤单和确定性减仓；
- 不得通过管理员审批、配置开关、allowlist 或手工改 tenant_id 临时放行；
- 现有冲突数据必须通过有证据、可审计的账户归属迁移处理。

### 3.2 明确延后的能力

“主账户 + 租户子额度”不是首期 P14 的实现范围。若未来确有机构账户需求，必须另建 Plan/ADR，至少定义：

- master account 所有权与 tenant sub-account 身份；
- tenant 子额度和 master 总额度的原子扣减；
- tenant 子账本隔离与 master 全局风险影响；
- master risk lock 对所有共享 tenant 生效；
- 子额度合计、并发调整和跨币种约束；
- 跨租户授权、审计、清算与灾难恢复。

在该独立 Plan 通过前，不在 P14 中留下“临时共享”旁路。

## 4. 三个独立状态域

```text
execution_gate_status:
  awaiting_approval | approved | ready_to_submit |
  submission_started | invalidated | closed

broker_order_status:
  not_submitted | submitting | accepted | working |
  partially_filled | filled | cancelled | rejected |
  expired | unknown

reservation_status:
  reserved | submitting | active | unknown |
  partially_consumed | consumed | released |
  partially_settled | overrun_locked
```

核心语义：

- execution gate 只表达是否允许执行；
- broker order 只表达券商事实；
- reservation 只表达额度冻结、消费和释放；
- `accepted/working` 不等于成交；
- `filled` 永远不能与 `released` 组成合法当前状态；
- `unknown` 与 `overrun_locked` 默认保持额度冻结；
- 只有 `ready_to_submit` 对执行 worker 可领取。

## 5. 强制联合转移

下表是首期允许的最小安全集合。未列出的转移默认非法。

| 场景 | execution gate | broker order | reservation | 处理 |
| --- | --- | --- | --- | --- |
| 创建 live intent | `awaiting_approval` | `not_submitted` | `reserved` | 初始三态固定 |
| 审批通过并重新校验 | `awaiting_approval -> approved -> ready_to_submit` | `not_submitted` | `reserved` | 只有最终状态可领取 |
| 审批过期、撤销或用户取消 | `awaiting_approval/approved -> invalidated -> closed` | `not_submitted` | `reserved -> released` | 未调用 broker |
| ready 后 kill switch、lease/fencing 失效或用户取消 | `ready_to_submit -> invalidated -> closed` | `not_submitted` | `reserved -> released` | 条件更新必须赢得 worker claim 竞态 |
| worker 领取、broker 调用前 | `ready_to_submit -> submission_started` | `not_submitted -> submitting` | `reserved -> submitting` | 同一短事务先持久化提交身份 |
| 可证明请求未离开进程的本地错误 | `submission_started -> closed` | `submitting -> not_submitted` | `submitting -> released` | 必须有本地证据 |
| broker 直接拒绝、取消或过期且零成交 | `submission_started -> closed` | `submitting -> rejected/cancelled/expired` | `submitting -> released` | 保存 broker 原始响应 |
| broker 接受且零成交 | `submission_started` | `submitting -> accepted/working` | `submitting -> active` | 冻结 remaining |
| accepted/working 后零成交终止 | `submission_started -> closed` | `accepted/working -> cancelled/rejected/expired` | `active -> released` | 全额释放 |
| 部分成交 | `submission_started` | `accepted/working -> partially_filled` | `active -> partially_consumed` | 累计成交消费，剩余冻结 |
| 部分成交后剩余终止 | `submission_started -> closed` | `partially_filled -> cancelled/rejected/expired` | `partially_consumed -> partially_settled` | 成交 consumed，未成交 released |
| 全部成交 | `submission_started -> closed` | `accepted/working/partially_filled -> filled` | `active/partially_consumed -> consumed` | 不得释放成交额度 |
| 提交结果不确定 | `submission_started` | `submitting -> unknown` | `submitting -> unknown` | 禁止重下和释放 |
| unknown 对账确认零成交终态 | `submission_started -> closed` | `unknown -> not_submitted/rejected/cancelled/expired` | `unknown -> released` | 必须满足第八版 reconciliation evidence |
| unknown 对账确认部分成交且订单仍活动 | `submission_started` | `unknown -> partially_filled` | `unknown -> partially_consumed` | 已成交消费，剩余继续冻结 |
| unknown 对账确认部分成交且剩余已终止 | `submission_started -> closed` | `unknown -> cancelled/rejected/expired` | `unknown -> partially_settled` | 必须同时取得成交和剩余终止证据 |
| unknown 对账确认全部成交 | `submission_started -> closed` | `unknown -> filled` | `unknown -> consumed` | 按 broker 事实结算 |
| 任意实际成交发生 overrun | 保持当前或转 `closed` | 保持真实 broker 状态 | `partially_consumed/consumed -> overrun_locked` | 立即账户级 risk lock |

补充规则：

- intent 关键字段变化不允许原地保留 approval；原 intent 必须失效，修改后的版本重新进入 `awaiting_approval`；
- `ready_to_submit` 与 worker claim 使用同一条件更新/fencing，只有一个动作成功；
- 一旦 `submission_started` 已提交到数据库，除非可证明请求未离开进程，否则只能提交一次或进入对账，不能再次 place order；
- 同一逻辑订单的 broker 幂等身份始终使用同一个不可变 `client_order_id`。

## 6. reservation 金额不变量

```text
covered_consumed_exposure =
  LEAST(consumed_exposure, initial_reserved_exposure)

initial_reserved_exposure =
  covered_consumed_exposure
  + released_exposure
  + remaining_reserved_exposure

overrun_exposure =
  GREATEST(consumed_exposure - initial_reserved_exposure, 0)
```

同时满足：

- 所有金额非负；
- `consumed_exposure`、`released_exposure` 单调增加；
- `remaining_reserved_exposure` 单调减少；
- `consumed`：`consumed > 0`、`remaining = 0`，真实全部成交时不得转 `released`；
- `released`：`consumed = 0`、`remaining = 0`；
- `partially_settled`：`consumed > 0`、`released > 0`、`remaining = 0`；
- 重复或乱序 fill event 不得重复消费额度；
- 金额变化和三个状态字段必须在同一数据库事务内推进。

## 7. unknown 安全策略

- 每 30 秒进入 reconciliation 扫描；
- 2 分钟未确认触发 P1 告警；
- 5 分钟未确认对真实 broker account 启用 `OPENING_ORDER_RISK_LOCK`；
- unknown 不自动 place order、不自动释放、不根据本地超时推断未成交；
- 只有满足第八版 broker consistency window、连续查询和原始响应留存要求后，才允许结算；
- broker 返回“处理中、未知、超时、未授权或暂不可查询”时继续保持 unknown；
- 人工处理不能无证据地把 unknown 标记为未成交。

## 8. overrun 安全策略

任何部分或全部成交都可能 overrun。发生时：

1. reservation 进入 `overrun_locked`；
2. 对真实 broker account 启用 `OPENING_ORDER_RISK_LOCK`；
3. 如果订单仍有未成交剩余量，优先请求撤销，但撤销结果本身仍需对账；
4. 原 fill、reservation 和事件历史不可修改或删除；
5. 所有处理使用 append-only adjustment event；
6. 在证据不足时永久保持 locked，不以可用性为理由释放。

首期不实现 `overrun_locked` reservation 的自动或人工状态退出；它是该 reservation 的不可变事故终态。事故处理只允许：

- 追加额度补足、负向 compensation 或 broker 纠正证据事件；
- 依据事件重放重新计算真实持仓、现金和账户可用额度；
- 经交易安全负责人复核后，单独解除账户的 `OPENING_ORDER_RISK_LOCK`。

解除账户 risk lock 不得把原 reservation 从 `overrun_locked` 改成 `consumed`、`partially_settled` 或 `released`。若未来需要可退出的 reservation 状态，必须在替代本文件的正式 Plan 中定义新的状态和事件投影迁移。

明确禁止：

```text
broker_order_status = filled/partially_filled
reservation_status = released
```

## 9. 状态机强制方式

首期固定同时使用数据库约束和统一服务，不允许二选一：

1. 数据库 CHECK 约束合法的当前状态组合与金额不变量；
2. 唯一 `OrderExecutionTransitionService` 实现转移白名单；
3. 应用运行角色撤销对状态和金额字段的直接 UPDATE 权限，只允许调用受控函数/服务写路径；
4. migration/运维修复使用独立受审计角色，不与应用角色共用；
5. 每次转移在同一事务中完成：锁定当前投影、验证版本/前态、插入 append-only event、更新投影、提交；
6. event 使用唯一幂等键，重复 broker event 只返回原结果；
7. projection 必须能从事件表确定性重放，并在 CI 中校验一致性。

## 10. G5 前的硬门禁

满足以下全部条件前不得开放真实 US live：

- 真实 broker account 单租户唯一约束和冲突迁移完成；
- 三个 live 入口全部接入同一 `AccountExposureReservationService`；
- 本文件全部合法转移和非法组合测试通过；
- submitting 前持久化、崩溃窗口和 client order id 幂等测试通过；
- unknown reconciliation、告警和账户 risk lock 演练通过；
- partial fill、剩余撤单、直接拒单、审批撤销和 overrun 测试通过；
- append-only event 与 projection 重放一致；
- 未审批/仅 approved intent 对 worker 零可见；
- 人工审批并记录 G5 结果。

## 11. 测试执行流程

### 11.1 测试原则

- 测试按固定顺序执行，前一层失败时不得用后一层成功掩盖；
- 关键安全测试使用真实 PostgreSQL 事务、Redis、Celery/trading worker 进程边界；
- 离线 CI 可以用确定性 fake broker 替代外部 HTTP，但 fake 只能位于 broker adapter 网络边界，不能替代数据库、transition service、worker claim、reservation 或事件账本；
- sandbox 测试只允许券商官方测试环境和专用测试账户，不使用真实资金、真实生产凭据或 production endpoint；
- 测试时 `RESEARCH_US_LIVE_BRIDGE_ENABLED=false`，任何意外真实网络下单请求都使整个测试失败；
- 每条验收要求必须映射到至少一个稳定测试 ID，禁止只依靠人工点击或日志目测；
- flaky、skip、xfail、quarantine 测试不能作为 Gate 通过证据。

### 11.2 测试环境

至少维护三种环境：

| 环境 | 基础设施 | broker | 用途 |
| --- | --- | --- | --- |
| unit | 进程内纯领域对象 | 不创建 client | Decimal、纯函数、状态规则 |
| CI integration | 独立 PostgreSQL + Redis + 真实 worker | 确定性 fake/recording adapter | migration、事务、并发、崩溃、幂等、事件重放 |
| staging sandbox | 与生产同拓扑的隔离环境 | IBKR/Alpaca 官方 sandbox/paper | 协议兼容、最终一致性、对账和运行手册演练 |

约束：

- 每个测试 run 使用独立数据库/schema、Redis namespace、tenant、broker account key 和 client order id 前缀；
- 禁止复用开发者日常 paper 数据或任何 production 数据库快照中的敏感值；
- 测试结束只清理本次 run 创建的数据，不能使用指向工作区根、共享数据库或生产资源的宽泛删除命令；
- fake broker 必须能脚本化返回 accepted、working、partial fill、fill、reject、cancel、expire、timeout、connection reset、重复事件、乱序事件和查询最终一致性延迟。

### 11.3 测试目录与标记

P14 实施时至少建立以下逻辑测试套件；可按现有仓库命名规范调整路径，但不能减少覆盖：

```text
tests/p14_safety/
  test_decimal_sizing.py
  test_account_identity.py
  test_state_matrix.py
  test_amount_invariants.py
  test_worker_claim_races.py
  test_submission_crash_windows.py
  test_reconciliation.py
  test_partial_fill.py
  test_overrun.py
  test_event_replay.py
  test_live_visibility_gate.py
```

在 `pytest.ini` 注册并使用：

```text
p14_safety       P14 安全契约测试
db_integration   真实 PostgreSQL/Redis 集成测试
fault_injection  进程崩溃和不确定结果测试
sandbox_broker   官方 sandbox/paper broker 测试，默认 CI 不运行
```

### 11.4 固定执行顺序

#### 第 0 层：测试计划和环境保护

执行前必须：

1. 记录 Git HEAD、dirty manifest、Python/Node/PostgreSQL/Redis 版本和 schema migration version；
2. 建立“安全条款/状态表行 -> test ID -> 测试文件”的追踪矩阵；
3. 验证所有 live 开关关闭、broker endpoint 指向 fake 或 sandbox；
4. 扫描环境变量，确认没有 production broker credential；报告只记录变量名和是否存在，不输出值；
5. 对目标测试数据库执行写入 canary，确认它是隔离测试实例。

任一保护检查失败立即停止，不运行订单测试。

#### 第 1 层：静态检查和纯单元测试

覆盖：

- Decimal sizing、lot/tick 舍入、极小值、费用和 FX buffer；
- 状态白名单的所有合法/非法组合；
- canonical digest、client order id 和 event idempotency key；
- lint、类型/语法、安全扫描和敏感日志检查。

退出条件：零失败、零未解释 skip；修改涉及的所有纯领域分支均有断言。

#### 第 2 层：migration 和数据库约束

依次验证：

1. 空库执行 `init.sql + 全部 dated migrations`；
2. recorded baseline 数据库升级；
3. migration 重复执行不产生重复对象或事件；
4. 两个 migration runner 并发时只应用一次；
5. checksum 漂移、部分 schema 和非法历史状态均 fail closed；
6. 应用角色直接 UPDATE 状态/金额字段被数据库拒绝；
7. `filled + released`、`working + released`、`unknown + consumed` 等非法组合被约束拒绝；
8. `(broker_account_key, client_order_id)` 和真实 broker account 单租户唯一约束生效。

退出条件：fresh、upgrade、repeat、concurrent、negative 五类路径全部通过。

#### 第 3 层：服务和真实事务集成

使用真实 PostgreSQL 和 Redis，验证：

- reservation、execution review、OrderIntent、pending order 和 append-only event 同事务提交/回滚；
- transition event 插入与 projection 更新原子完成；
- 三个 live 入口都调用同一个账户级 reservation service；
- 多 credential 映射同一 tenant/account 时额度合计正确；
- 跨租户复用真实 broker account 进入 ownership conflict lock；
- event replay 与当前 projection 完全一致；
- 重复 API、Celery 重投和 broker event 不重复创建订单、fill 或消费额度。

退出条件：事务中任一步注入异常后都不存在半条订单、孤立 reservation 或缺失事件。

#### 第 4 层：worker、并发和竞态

至少重复运行并发场景，覆盖：

- 两个 worker 同时 claim，只有一个成功；
- approval 撤销与 claim 竞争，只有一个合法结果；
- kill switch、lease/fencing 失效与 claim 竞争，未开始的订单不调用 broker；
- 同账户多个 intent 并发预占不突破账户、策略、每日和单标的限额；
- stale live processing 不会自动回到 pending；
- awaiting/approved 对 worker 查询结果始终为零可见。

退出条件：连续多轮无重复提交、无额度超限、无非法状态；并发测试不能只运行一次。

#### 第 5 层：崩溃窗口和故障注入

按第 11.5 节的每个 checkpoint 杀进程/抛异常，然后重启 worker 和 reconciler。每个场景必须验证：

- broker place 调用次数；
- client order id 是否保持不变；
- 三状态和金额是否守恒；
- event 是否恰好一次；
- reservation 是否冻结、消费或有证据释放；
- 重启后是否只对账而不重下。

退出条件：所有 checkpoint 都有自动化断言和恢复后最终状态证据。

#### 第 6 层：broker 生命周期和对账

使用确定性 fake broker 覆盖：

- 直接 reject/cancel/expire；
- accepted/working 零成交后终止；
- 部分成交后取消、拒绝、过期；
- 部分成交仍活动，remaining 继续冻结；
- 全部成交；
- 重复/乱序 fill；
- 响应丢失和查询最终一致性延迟；
- unknown 连续查询不足、证据不足时不释放；
- 部分/全部成交 overrun 进入不可退出的 `overrun_locked`；
- 账户 risk lock 只经独立事故解决事件和审批解除。

退出条件：联合状态、金额不变量、原始证据和 append-only event 全部匹配本文件。

#### 第 7 层：API、权限、契约和 UI

仅在当前 Plan 涉及时执行：

- Human JWT 与 Agent/MCP scope/ownership/allowlist 矩阵；
- OpenAPI 生成物与兼容性检查；
- 未审批订单在 API、worker、UI 中均不可伪装成已提交；
- paper/live 字段、标签和确认提示不可混淆；
- 前端单元测试、lint 和 production build；
- Compose 默认与 production overlay 配置解析。

退出条件：无水平越权、无敏感字段泄漏、无 OpenAPI 非兼容变化、构建成功。

#### 第 8 层：完整回归和 release gate

执行完整的非 network backend 测试、release gate、受影响前端测试和 Compose 检查。P14 定向测试通过但完整回归失败时，P14 仍视为未完成。

#### 第 9 层：staging sandbox 演练

该层不在普通离线 CI 中运行，只在 G5 候选阶段执行：

1. 使用专用 sandbox tenant、credential 和 broker account；
2. 先验证 quote/account/read-only，再启用 sandbox 下单；
3. 覆盖 market/limit、取消、部分成交、拒绝和查询对账；
4. 演练 worker 重启、broker timeout、kill switch、unknown 告警和 risk lock；
5. 对比 broker 与本地 orders/fills/cash/positions/reservations；
6. 完成后撤销测试订单和临时权限，保留脱敏证据。

退出条件：sandbox 零未解释差异，运行手册可以由另一名执行者重复完成。sandbox 通过仍不等于 production G5 自动批准。

### 11.5 故障注入 checkpoint

至少在以下位置注入异常：

| ID | 注入点 | 安全期望 |
| --- | --- | --- |
| F01 | reservation 写入前 | 无任何事实记录 |
| F02 | reservation 后、intent 前 | 整个本地事务回滚 |
| F03 | intent 后、pending order 前 | 整个本地事务回滚 |
| F04 | pending order 后、本地事务提交前 | 整个本地事务回滚 |
| F05 | submitting 短事务提交前 | 不允许调用 broker |
| F06 | submitting 已提交、broker 调用前 | 恢复时先证据判断；不得盲目重下 |
| F07 | broker 已接收、响应返回前 | 进入 unknown，只按 client order id 对账 |
| F08 | broker 响应后、结果事务前 | 重启后对账，不重复 place |
| F09 | partial fill event 写入中 | event/projection 同时提交或同时回滚 |
| F10 | reconciliation 查询后、结算前 | 重试不重复释放或消费 |
| F11 | adjustment event 后、projection 前 | 同事务回滚，不产生半条补偿 |
| F12 | projection 更新后、事务提交前 | event/projection 同时回滚 |

### 11.6 标准命令与项目适配

P0 完成后，以新仓库中的实际脚本为准，并把最终命令固化到 README/CI。基于 QD 当前基线，最低检查命令为：

```bash
cd backend_api_python
python -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q
ruff check app scripts tests
python -m pytest tests/p14_safety -q

cd ..
python scripts/check_version.py
python scripts/check_mojibake.py
docker compose -f docker-compose.yml config -q
docker compose -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.observability.yml config -q
```

如果当前 Plan 修改前端且仓库中存在对应 `package.json`：

```bash
pnpm test:unit
pnpm lint:nofix
pnpm build
```

要求：

- 不得伪造不存在的命令；若迁移后路径或脚本不同，先读取真实配置再更新本节和 CI；
- P14 实现必须提供一个可稳定执行的定向入口，例如 `python -m pytest tests/p14_safety -q`；
- db integration、fault injection、sandbox 命令必须分别可选，不能让普通单元测试意外访问网络；
- 所有命令在报告中记录完整命令、退出码和耗时。

### 11.7 失败处理

- 任一必需测试失败，本 Plan 状态保持“未完成”，相关功能开关保持关闭；
- 可为定位目的单独重跑失败用例，但必须同时保留首次失败和重跑结果；
- 不允许通过删除断言、扩大容差、增加无依据 sleep、标记 skip/xfail 或只重跑成功结果来通过 Gate；
- 环境故障必须证明是环境问题，并记录未验证的行为；“本机无法运行”不等于测试通过；
- 涉及重复订单、错误释放、越权、金额不守恒或事件不可重放的失败均按 P0 阻断处理；
- 修复后从最早受影响层重新开始，并最终重新运行完整回归。

### 11.8 测试证据与报告

每次测试报告至少包含：

- Plan ID、Git HEAD、dirty manifest、schema version 和测试时间；
- 环境类型、依赖版本、broker 类型（fake/sandbox）和开关快照；
- 需求/安全条款到 test ID 的追踪矩阵；
- 每条命令、退出码、通过/失败/跳过数量和耗时；
- migration fresh/upgrade/repeat/concurrent 结果；
- 故障注入 F01-F12 结果；
- broker place 调用计数、重复订单检查、金额守恒和 event replay 摘要；
- 未运行测试、具体原因、风险和补跑责任人；
- 所有失败及修复记录；
- 是否满足当前 Gate 的明确结论。

日志、broker 响应和截图必须脱敏，不得包含 token、secret、完整 account id、MFA secret 或用户隐私数据。

## 12. 退出本安全档案

本文件只能由后续正式版本替代，不能由普通功能开关绕过。替代版本必须：

- 逐项覆盖本文件的状态、金额、账户、unknown 和 overrun 不变量；
- 给出迁移现有事件和 projection 的兼容方案；
- 通过交易安全负责人审批；
- 在 sandbox 完成故障注入和对账演练；
- 不降低 G5 的现有门槛。
