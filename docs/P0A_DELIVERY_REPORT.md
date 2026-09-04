# P0A 交付报告 — 生产基线安全加固

> 按《DEVELOPMENT_PLAN第八版》§7 模板 · 2026-09-03 · 环境：WSL2 / Python 3.12.13 / Docker

## 1. 本 Plan 改了什么

| 领域 | 变更 |
| --- | --- |
| 密文格式 | `credential_crypto.py` 重写为 `v2:<purpose>:<key-fingerprint>:<token>` 信封；purpose 必填且隔离（broker-credential / mfa-secret）；key-id 为密钥内容指纹（自描述，杜绝"换钥静默丢数据"） |
| 密钥配置 | 新增 `CREDENTIAL_ENCRYPTION_KEYS`（版本化集合）与 `CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`；`CREDENTIAL_ENCRYPTION_KEY` 保持兼容并仍为默认 active |
| SECRET_KEY 回退 | **移除**：在线写路径无凭据密钥即失败；在线读路径拒绝 legacy 裸 Fernet；legacy 解密仅存于迁移命令专用 `decrypt_legacy_blob()` |
| 启动守卫 | 新增 `app/security/bootstrap_guards.py`：staging/production 缺持久化密钥或默认管理员口令**拒绝启动**；开发环境无密钥须显式 `ALLOW_INSECURE_DEV_KEY=true`；insecure 模式运行时**禁止**保存 broker/MFA 凭据 |
| entrypoint | 移除内存密钥生成（任何环境）；生产/预发布缺 `SECRET_KEY`、默认 `SECRET_KEY`、默认口令均拒绝启动；支持 `CREDENTIAL_ENCRYPTION_KEY_FILE` 密钥文件注入 |
| Compose | production overlay 注入 `DEPLOYMENT_ENV=production` + 只读密钥文件挂载，结构性解决 `.env:ro` 与 entrypoint 写入冲突 |
| 迁移/轮换 | 新增幂等可断点续传的 `migrate_credentials` 命令（append-only 审计表 `qd_p0a_migration_log`，仅记指纹/校验和，不落明文）；四阶段可逆轮换手册；跨容器 decrypt canary 脚本 |
| 调用方 | 全部 7 个 credential_crypto 调用文件显式声明 purpose（含 execution/Agent 读取路径与 quick_trade） |

## 2. 对应的 ADR / MERGE_DESIGN 契约

- ADR：`docs/adr/P0A-001-credential-security-baseline.md`
- 计划：P0A 全部 9 项任务；D-009（P0A 是凭据保存硬前置）、D-014（安全行为不可作为普通功能回滚）

## 3. 数据库、API、任务和配置变化

- **数据库**：仅新增审计表 `qd_p0a_migration_log`（迁移命令幂等建表）；业务表零改动
- **API**：零路由变化（OpenAPI exact diff 保持 0）
- **任务/进程**：`create_app` 前置 `enforce_startup_security()`（API/trading/scheduler/Celery/migrate 全覆盖）；新命令 `python -m app.commands.migrate_credentials [--dry-run] [--batch-size N]`
- **配置**：新增 `DEPLOYMENT_ENV`、`CREDENTIAL_ENCRYPTION_KEYS`、`CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`、`CREDENTIAL_ENCRYPTION_KEY_FILE`、`ALLOW_INSECURE_DEV_KEY`（env.example 已文档化）

## 4. 向后兼容性与上游来源

- 全部改动位于 QD `e64e1c2` 基线文件内（credential_crypto / entrypoint / compose / settings 文档），上游来源不变
- **兼容性**：部署了旧版凭据的库升级后需先跑 `migrate_credentials`——迁移前在线读取旧密文会**显式报错并给出迁移指引**（fail closed，非静默降级）；新装环境无此问题
- `CREDENTIAL_ENCRYPTION_KEY` 单变量用法完全兼容（成为 active key）

## 5. 已运行测试及结果

| 测试 | 结果 |
| --- | --- |
| `tests/test_p0a_security.py`（26 用例：envelope 往返/purpose 隔离/指纹轮换三阶段/SECRET_KEY 隔离/启动守卫 8 场景/insecure 写拦截/迁移转换与 dry-run） | **26 passed** |
| 全量 `pytest -m "not integration and not stress"` | 见 §8 本轮记录（预期 1425 passed = 1399 + 26） |
| release gate / ruff / bandit / pip-audit | 见 §8 本轮记录 |
| `scripts/decrypt_canary.py` 本地（8 项检查：双 purpose 往返/purpose 绑定/信封形状/legacy 拒收） | **PASS**（有钥/无钥两场景） |
| `sh -n docker-entrypoint.sh`；`docker compose config`（默认+production overlay 合并） | PASS |
| Docker 实测「生产缺密钥拒绝启动」「密钥文件注入启动」「跨容器 canary」 | 见 §8 |

## 6. 未运行测试与原因

- **「保存真实券商凭据 → 重启全部容器 → 成功解密」全链演练**：需要真实凭据与 G0A 批准后的环境；当前以"测试凭据容器内 canary + 单元往返测试"替代，真实凭据演练在 G0A 验收时执行
- `gitleaks git` / CodeQL：需 candidate commit 后经 GitHub Actions（push 后自动触发）

## 7. 安全、租户、精度、幂等和成本风险

- **安全**：密钥指纹泄露密钥 SHA-256 前 12 hex——不可逆、无法暴力还原密钥；审计表只存指纹与校验和
- **租户**：无租户语义变化（凭据表原有 user_id 约束不动）
- **精度/幂等**：迁移按主键序分批、逐行事务，重跑收敛；`qd_p0a_migration_log` 可对账（迁移行数 = legacy + re-encrypted 计数）
- **成本**：无额外运行时成本；迁移为一次性 O(N) 扫描

## 8. 监控指标与告警

- 启动日志输出 `Key inventory`（env/kind/指纹列表/insecure 标志，无密钥材料）
- 每次容器启动的 canary（手册阶段 3）输出 PASS/FAIL，FAIL 应接 P1 告警
- 运行期 `Cannot decrypt credential blob`（凭据指纹缺失）与 `InsecureKeyWriteBlocked` 为 ERROR 级日志，建议接入告警

## 9. 回滚操作和数据收敛方式

- **应用回滚**：回退到 P0A 前代码后，旧代码可读 legacy 与（当时）兼容密钥密文；P0A 信封 `v2:` 前缀值会被旧代码当作原始 token 解析失败——因此**回滚应用前必须先回滚配置到单一 `CREDENTIAL_ENCRYPTION_KEY` 且已跑过迁移**；密文本身无损（手册阶段表逐项可退）
- **D-014**：拒绝启动行为、默认口令拒绝、SECRET_KEY 回退移除不随应用回滚而回退
- 数据收敛：迁移命令幂等重跑 + 审计表对账；任何行迁移失败保持原值可读

## 10. 下一 Plan 的前置条件是否满足

- **G0A（本 Plan 的门）**：代码与本地验收已交付；剩余项（真实凭据重启演练、commit 后 CI 安全扫描）在 candidate commit / 部署环境完成——此前**不保存任何真实券商凭据、不开始 P18 live**
- **P1（migration runner）**：前置 P0 满足；G1 前不开始研究域写入
