# P2 交付报告 — Research 契约、标的身份与动作映射

> 按《DEVELOPMENT_PLAN第八版》§7 模板 · 分支 `p2-research-contracts-shi`

## 1. 本 Plan 改了什么

新增 `backend_api_python/app/services/research/`（纯函数领域包，零依赖）：

| 模块 | 内容 |
| --- | --- |
| `contracts.py` | `Market`（六市场规范码）、`ReasonCode`（稳定机器码，点命名空间，文案本地化分离）、`ContractResult`（统一结果信封：ok/value/reasons） |
| `instrument_identity.py` | `InstrumentIdentity(market, symbol, canonical_key, exchange, asset_class, currency, timezone)` + `resolve_instrument(market, raw)` 六市场解析；`is_bare_ambiguous_code` 诊断助手 |
| `action_mapping.py` | `Action`（buy/add/hold/reduce/sell/watch/avoid/alert）、`PositionState`（flat/long——结构上无 short 态）、`TradeSide`（open/add/reduce/close_long 四个 spot-long 意图）、完整动作×持仓矩阵 |

## 2. 对应的 ADR / MERGE_DESIGN 契约

- 计划 P2 全部 7 项任务；无新 ADR（纯新增包，无行为替换）

## 3. 数据库、API、任务和配置变化

- **零**：无 migration、无路由、无任务、无配置变化（P2 是纯契约层，P3 才落表）

## 4. 向后兼容性与上游来源

- 纯新增文件，不触碰任何现有代码路径；上游来源：本仓库自研（无 DSA 代码导入）

## 5. 已运行测试及结果

`tests/test_research_contracts.py` — **63 passed**：

- 正例 14 项：六市场规范形态（`AAPL`、`600519`/SH/SZ 前缀、HK 三别名→`0700.HK`、`7203.T`、`.KS/.KQ`、`.TW/.TWO`）+ 币种/时区元数据 + CN 交易所前缀规则
- fail-closed 17 项：未知市场（含 Crypto 不回退）、空 symbol、裸日韩台代码（`7203`/`005930`/`2330` → AMBIGUOUS）、错 suffix、非法位数、US 含数字等
- 幂等/纯度：canonical 回代解析结果相等、frozen dataclass 不可变、`sys.modules` 断言研究包未引入 requests/psycopg2/celery/litellm/redis
- 动作矩阵 24 项全组合 + 大小写输入 + 未知输入 fail-closed + 短侧结构性排除（`short` 字符串断言 + PositionState 无 SHORT 成员）

全量回归 1497 passed（1434 + 63）；ruff 通过。

## 6. 未运行测试与原因

- 网络/数据库集成测试：P2 契约层无 IO，不适用（验收条款「无数据库、网络、LLM 和订单依赖」已由纯度测试直接覆盖）

## 7. 安全、租户、精度、幂等和成本风险

- 安全：无外部输入执行路径；所有失败输出仅为机器码，无异常文本外泄面
- 租户：不涉及（无用户数据）
- 精度：不涉及（无数值计算）
- 幂等：纯函数天然幂等（测试覆盖）
- 成本：零运行时成本（import 即完成全部构建）

## 8. 监控指标与告警

- 不适用；后续 P8 流水线接入后，`ReasonCode` 将成为报告失败分类的维度

## 9. 回滚操作和数据收敛方式

- 删除 `app/services/research/` 与对应测试文件即可，无数据、无 schema、无配置残留

## 10. 下一 Plan 的前置条件是否满足

- **P3（研究数据模型与租户约束）前置 = P1 + P2**：均已完成，可开工；P3 完成后过 G1 门
- HK 规范形态说明：计划示例 `0700.HK` 采用「去前导零、≥4 位补齐」规则（`00700→0700`、`5→0005`），已在模块 docstring 与测试中固化
