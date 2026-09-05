# Quanthedra

> 自托管一体化量化平台：**AI 研究 → 策略 → 回测 → 模拟盘 → 实盘 → 监控**，全流程闭环。
>
> Quanthedra（原 QuantAnalyInvest）以 [QuantDinger](https://github.com/OpenByteInc/QuantDinger)
> 完整代码树为运行底座（账户 / 策略 / 风控 / 订单 / 部署 / 权限），并按
> [《DEVELOPMENT_PLAN第八版》](./DEVELOPMENT_PLAN第八版.md) 逐 Plan 迁移
> daily_stock_analysis 的多市场研究能力。

---

## 项目简介

Quanthedra 将两个上游项目合并为统一仓库：

| 来源 | 角色 | 许可 |
| --- | --- | --- |
| **QuantDinger (QD)** `e64e1c2` | 运行底座：完整交易系统（后端 API / Celery / 交易 worker / 调度 / 前端 / 移动端 / MCP） | Apache-2.0 |
| **daily_stock_analysis (DSA)** `396d43a4` | 研究能力来源：美股 / A股 / 港股 / 日股 / 韩股 / 台股 多市场研究报告流水线 | MIT |

合并遵循《DEVELOPMENT_PLAN第八版》的 21 个 Plan（P0–P19B）与 8 个质量门
（G0–G6）：每个 Plan 独立交付、独立验收、独立回滚，生产事实数据只进
PostgreSQL，交易链路默认 fail-closed。

## 功能特性（当前基线即可用）

- **AI 交易操作系统**：自然语言生成策略代码 → 历史回测 → 模拟盘 → 实盘执行 → 持仓监控
- **多市场行情与研究**：美股、A股、港股、日股、韩股、台股，多数据源自动降级路由
- **实盘券商对接**：IBKR / Alpaca（受控边界内），US 市场先行
- **AI Agent / MCP**：通过 Agent Gateway 与 MCP Server 以受控 scope 驱动研究与交易
- **会员与支付**：套餐订阅 + USDT 链上支付；内置 **Mock 支付提供商**
  （`USDT_PAY_PROVIDER=mock`，开发/测试零链上依赖，真实支付路径零改动）
- **生产安全基线（P0A）**：凭据 v2 信封加密（purpose 隔离 + 密钥指纹轮换）、
  生产缺持久化密钥 / 默认管理员口令拒绝启动、密钥轮换手册与跨容器解密 canary
- **可观测性**：Prometheus / Grafana overlay、结构化审计日志、任务级 correlation

## 快速开始

```bash
# 1. 准备环境变量
cp backend_api_python/env.example backend_api_python/.env
#    开发模式会自动生成 SECRET_KEY 与 CREDENTIAL_ENCRYPTION_KEY

# 2. 启动（10 个服务：postgres / redis / redis-jobs / migration / backend /
#    mcp / trading-worker / scheduler-worker / celery-worker / celery-beat /
#    frontend / mobile）
docker compose up -d

# 3. 访问
#    Web:      http://localhost:8888
#    Mobile:   http://localhost:8889
#    API:      http://localhost:5000/api/health
```

> **生产部署**：使用 `docker-compose.production.yml` overlay
> （只读根文件系统 + 非root + 密钥文件注入），并设置 `DEPLOYMENT_ENV=production`。
> 生产环境缺失持久化 `CREDENTIAL_ENCRYPTION_KEY` 或使用默认管理员口令
> `123456` 时**拒绝启动**。详见
> [docs/P0A_DELIVERY_REPORT.md](./docs/P0A_DELIVERY_REPORT.md)。

## 本地开发与测试

```bash
cd backend_api_python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock -r requirements-dev.txt

# 全量单元测试（离线）
python -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q
python -m pytest tests/release_gate -q

# 静态检查与安全审计
ruff check app scripts tests
bandit -q -r app -x app/data -lll -ii
pip-audit -r requirements.lock --progress-spinner off

# OpenAPI 契约
SKIP_STARTUP_HOOKS=1 OPENAPI_ENABLED=false \
  python scripts/export_openapi.py --output ../docs/api/openapi.generated.yaml
python -m pytest tests/test_openapi.py -q

# 凭据加密 canary（任意容器内可运行）
python scripts/decrypt_canary.py
```

## 目录结构

```text
backend_api_python/     # 后端（Flask + Celery + trading worker），qd_ 前缀 PostgreSQL schema
mcp_server/             # MCP Server（Python 3.10–3.13）
frontend/  mobile/      # Web 与移动端（Docker 镜像构建）
docs/                   # 审计文档 / ADR / API 契约 / 部署与轮换手册
docker-compose*.yml     # 默认 / 生产 / GHCR / 可观测性 overlay
DEVELOPMENT_PLAN第八版.md   # 全量开发计划（P0–P19B + G0–G6）
```

## 开发路线图

| Plan | 内容 | 状态 |
| --- | --- | --- |
| P0 | 完整仓库基线与来源治理（G0） | ✅ 完成 |
| P0A | 生产基线安全加固（G0A） | ✅ 完成（真实凭据重启演练待 G0A 环境签署） |
| P1 | PostgreSQL migration runner | ⏳ 下一步 |
| P2–P7 | 研究契约 / 数据模型 / DSA bridge / 六市场行情路由 | 未开始（可并行） |
| P8–P10 | 研究流水线 / Celery 接线 / 调度与配额 | 未开始 |
| P11–P13 | DecisionSignal / Outcome / ExecutionBinding | 未开始 |
| P14–P16 | Decimal sizing / 原子额度预占 / Paper E2E | 未开始 |
| P17–P18 | 前端操作台 / US 受控实盘（G5） | 未开始 |
| P19A/P19B | DSA 历史导入 / 停写退役（G6） | 未开始 |

进度明细见 [docs/P0_CHECKLIST.md](./docs/P0_CHECKLIST.md) 与
[docs/P0_ENVIRONMENT.md](./docs/P0_ENVIRONMENT.md)。

## 安全基线（P0A 要点）

- 凭据密文格式 `v2:<purpose>:<key-fingerprint>:<token>`；`broker-credential`
  与 `mfa-secret` 用途隔离，跨用途替换在解密层被拒绝
- 密钥轮换 = 配置变更 + 一次幂等迁移（`python -m app.commands.migrate_credentials`），
  全程可回滚，审计表只记指纹与校验和
- 开发环境 `ALLOW_INSECURE_DEV_KEY=true` 可无密钥启动，但**禁止**保存
  券商凭据与 MFA 密钥（运行时 fail-closed）
- 轮换手册：[docs/deployment/CREDENTIAL_KEY_ROTATION.md](./docs/deployment/CREDENTIAL_KEY_ROTATION.md)

## 文档索引

- [开发计划（第八版）](./DEVELOPMENT_PLAN第八版.md) — P0–P19B 全量拆解
- [AGENTS.md](./AGENTS.md) — 开发代理规则
- [docs/BASELINE.md](./docs/BASELINE.md) — 基线 commit 与上游来源
- [docs/adr/](./docs/adr/) — 关键决策记录（基线策略 / Mock 支付 / P0A / 更名）
- [docs/P0A_DELIVERY_REPORT.md](./docs/P0A_DELIVERY_REPORT.md) — P0A 交付报告
- [README_UPSTREAM_QUANTDINGER.md](./README_UPSTREAM_QUANTDINGER.md) —
  QuantDinger 上游原 README（功能截图与详细特性说明）
- [docs/README_CN.md](./docs/README_CN.md) — 上游中文说明

## 致谢与许可

- [QuantDinger](https://github.com/OpenByteInc/QuantDinger)（Open Byte Inc）—
  后端沿用 **Apache License 2.0**
- `daily_stock_analysis`（commit `396d43a4`，本地归档）— **MIT**
  （screening 模块为 Apache-2.0 衍生；逐模块迁移，来源见
  [UPSTREAM_SOURCES.md](./UPSTREAM_SOURCES.md)）
- 上游商标与产品名（QuantDinger 等）归各自所有者；本仓库更名决策见
  [docs/adr/P0A-002-repository-renamed-quanthedra.md](./docs/adr/P0A-002-repository-renamed-quanthedra.md)
