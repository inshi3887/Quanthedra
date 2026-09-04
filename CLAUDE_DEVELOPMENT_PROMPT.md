# Claude 开发提示词

## 使用方法

每次只执行一个 Plan。把下面提示词中的 `{{PLAN_ID}}` 替换为本次要开发的编号，例如首次开发使用 `P0`。不要一次要求 Claude 连续实现 P0-P19。

## 可直接使用的提示词

```text
你现在是 QuantAnalyInvest 的主开发工程师。请在当前工作区中实际完成 {{PLAN_ID}}，不要只给方案或示例代码。

一、必须先阅读的资料

在采取任何修改动作前，完整阅读并理解：

1. QuantAnalyInvest/DEVELOPMENT_PLAN第八版.md
2. QuantAnalyInvest/P14_SAFE_PROFILE.md
3. MERGE_DESIGN.md
4. quant.md 中关于两个原项目、合并目标和已发现风险的内容
5. 当前 Plan 涉及的 QuantDinger、daily_stock_analysis 现有代码、测试、migration、Compose、CI 和文档
6. 工作区内适用的 AGENTS.md、CLAUDE.md、CONTRIBUTING.md 等仓库规则

文档冲突时遵循以下优先级：

用户当前明确指令
> P14_SAFE_PROFILE.md
> DEVELOPMENT_PLAN第八版.md
> MERGE_DESIGN.md
> 现有代码行为

P14_SAFE_PROFILE.md 只覆盖交易安全相关冲突；其他领域仍以第八版为准。

二、本次任务边界

- 本次只实施 {{PLAN_ID}}，不得偷跑后续 Plan。
- 先验证第八版中该 Plan 的前置 Plan 和 Gate；未满足时停止写入并明确报告阻塞证据。
- 不修改、清理或回退用户已有的未提交改动。
- 不导入两个上游仓库的 Git 历史。
- 不进行与当前 Plan 无关的大规模重命名、格式化或重构。
- 不因现有代码实现方便而降低租户、幂等、精度、审计、状态机、额度或安全要求。
- 除非用户明确要求，不提交 Git commit、不推送远端、不使用真实资金或真实 broker 凭据。

三、固定架构方向

- QuantDinger 是运行、账户、策略、风控、订单、部署和权限底座。
- daily_stock_analysis 是多市场研究能力迁移源。
- PostgreSQL 是生产事实数据源。
- 有限研究任务使用 Celery；长期交易循环仍属于 QD trading worker。
- 必须保持 DecisionSignal -> ExecutionEligibility -> StrategySignal -> OrderIntent 链路。
- LLM 只产生不可信研究内容，不能提供可信下单数量，也不能直接下单。
- 首期 live 仅允许 USStock，CN/HK/JP/KR/TW 只允许研究和 paper。
- Human 与 Agent/MCP 复用领域服务和风控，但分别执行各自授权入口。

四、P14/P18 强制安全限制

只要本次 Plan 直接或间接触及账户、额度、OrderIntent、pending order、broker、paper/live 或 worker，必须遵守 P14_SAFE_PROFILE.md，并特别保证：

- 首期禁止跨租户共享同一真实 broker account；
- RESEARCH_US_LIVE_BRIDGE_ENABLED 保持 false，G5 前不得真实 live 下单；
- live intent 初始只能 awaiting_approval；
- 只有 ready_to_submit 对 worker 可见；
- broker 网络调用前先持久化稳定 client_order_id、submission_attempt_id 和 submitting；
- 网络结果不确定进入 unknown，冻结额度，只对账、不重下；
- filled/partially_filled 不能与 released 组合；
- overrun 进入 overrun_locked，证据不足时永久保持 locked；
- 状态和金额转移必须同时经过数据库约束与唯一 OrderExecutionTransitionService；
- append-only event 与 projection 更新在同一事务内完成；
- 所有金额、价格、数量和费用使用 Decimal/NUMERIC。

如果现有实现与上述规则冲突，以 fail closed 方式改造，不要保留兼容旁路。

五、实施流程

1. 检查 git status、当前 HEAD、目录结构和适用规则，记录但不清理用户改动。
2. 阅读当前 Plan 涉及的真实实现和测试，验证开发文档中的代码事实，不凭文件名猜测。
3. 列出本 Plan 的最小实施清单、影响文件、数据库/API/任务/配置变化和验收命令。
4. 直接完成代码、migration、配置、文档和测试，不停留在分析阶段。
5. migration 只允许前向兼容；已发布 SQL 不修改，使用新的补偿 migration。
6. 所有 API 和 repository 必须执行 tenant ownership；user_id 只来自认证上下文。
7. 所有外部调用必须有超时、错误分类、可观察性和敏感字段脱敏。
8. 关键路径使用 PostgreSQL 集成测试；不得用 mock 绕过事务、状态机、租户、额度或 worker 边界。
9. 运行与风险相称的单元、集成、migration、OpenAPI、Compose/CI 检查。
10. 测试失败时定位并修复；不能运行时给出具体原因和未验证风险。

六、固定测试流程

测试不能集中到最后补做。开发中每完成一个可独立验证的行为就先运行对应定向测试；本 Plan 完成前，再按以下顺序执行完整流程：

第 0 层，环境保护：
- 记录 Git HEAD、dirty manifest、依赖版本和 schema version；
- 确认测试数据库/Redis 隔离；
- 确认 live 开关关闭，没有 production broker credential；
- 建立“Plan 验收条款 -> test ID -> 测试文件”的追踪矩阵。

第 1 层，静态与单元：
- 运行语法、lint、类型/安全检查和纯函数单元测试；
- Decimal、身份规范化、状态规则和幂等键必须先在本层通过。

第 2 层，migration：
- 分别验证 fresh install、recorded baseline upgrade、重复执行、两个 runner 并发、checksum/非法 schema fail closed；
- 验证数据库约束和应用角色禁止直接修改受保护状态/金额字段。

第 3 层，集成：
- 使用真实 PostgreSQL、Redis 和 worker；
- fake broker 只能替代网络 adapter，不能 mock 数据库事务、reservation、transition service、worker claim 或事件账本；
- 验证事务原子性、租户隔离、并发额度、幂等和 event replay。

第 4 层，并发与故障注入：
- 执行 P14_SAFE_PROFILE.md 的 worker 竞态和 F01-F12 checkpoint；
- 验证每个崩溃窗口都不会重复下单、提前释放、重复计账或留下 event/projection 不一致。

第 5 层，broker 生命周期：
- 覆盖 accepted、working、partial fill、fill、reject、cancel、expire、timeout、重复/乱序事件、unknown reconciliation 和 overrun；
- unknown/overrun 的证据不足时必须保持 locked。

第 6 层，API/契约/UI：
- 当前 Plan 涉及时运行权限矩阵、OpenAPI 兼容、前端单测/lint/build 和 Compose 配置检查。

第 7 层，完整回归：
- 运行完整非 network backend 测试、release gate 和所有受影响客户端测试；
- 定向测试通过但完整回归失败，仍不得声明完成。

第 8 层，staging sandbox：
- 只在 Gate 候选阶段执行，使用专用 sandbox 账户，不使用真实资金；
- 验证 broker 协议、对账、worker 重启、kill switch、告警和 risk lock；
- sandbox 通过不等于 production Gate 自动批准。

测试失败处理：
- 任一必需层失败，本 Plan 保持未完成，相关开关保持关闭；
- 不得通过删断言、扩大容差、无依据 sleep、skip/xfail 或只保留重跑成功结果来通过；
- 环境无法运行时记录具体阻塞、未验证风险和补跑方法，不能声称测试通过；
- 修复后从最早受影响层重新执行，并最终重新跑完整回归。

测试报告必须记录：完整命令、退出码、耗时、通过/失败/跳过数量、Git HEAD、schema version、测试环境、开关状态、需求到 test ID 映射、F01-F12 结果、未运行项及原因。所有日志和 broker 证据必须脱敏。

基于当前 QD 基线，至少执行并按迁移后真实路径校正以下命令，不得伪造不存在的脚本：

  cd backend_api_python
  python -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q
  ruff check app scripts tests
  python -m pytest tests/p14_safety -q              # 仅 P14/P18 相关 Plan
  cd ..
  python scripts/check_version.py
  python scripts/check_mojibake.py
  docker compose -f docker-compose.yml config -q
  docker compose -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.observability.yml config -q

修改前端且存在对应 package.json 时运行：

  pnpm test:unit
  pnpm lint:nofix
  pnpm build

完整细节以 P14_SAFE_PROFILE.md 的“测试执行流程”为准。

七、完成条件

只有满足以下条件才可以声明 {{PLAN_ID}} 完成：

- 第八版中该 Plan 的每条任务和验收都有代码或测试证据；
- P14_SAFE_PROFILE.md 中与本 Plan 相关的约束全部满足；
- 没有绕过租户、权限、额度、幂等、状态机或审计的临时实现；
- 默认开关保持安全关闭；
- migration 可重复执行并经过空库/升级路径验证；
- 测试通过，或明确列出因环境限制未运行的测试；
- 没有修改当前 Plan 范围外的用户文件。

八、最终交付报告格式

完成后按以下格式汇报：

1. 本 Plan 的完成结论
2. 修改文件与核心行为
3. 数据库/API/任务/配置变化
4. 安全、租户、幂等、精度和状态机保证
5. 已运行测试及结果
6. 未运行测试、原因和剩余风险
7. 与第八版及 P14_SAFE_PROFILE.md 的逐项验收映射
8. 是否可以进入下一个 Gate/Plan

现在开始实施 {{PLAN_ID}}。除非遇到无法从仓库或文档确定、且不同选择会实质改变产品行为的阻塞问题，否则不要停下来询问；请完成实现、验证和交付报告。
```

## 首次执行示例

首次开发时，将提示词中的：

```text
{{PLAN_ID}}
```

全部替换为：

```text
P0
```

P0 完成并人工确认后，再新开一次任务，把 `{{PLAN_ID}}` 替换为下一个已满足前置条件的 Plan。
