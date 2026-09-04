# P0 环境保护记录
- 时间: 2026-08-18T03:07:17Z
- QD recorded_commit: e64e1c227bf3174e441a42143620179b286387e1
- DSA recorded_commit: 396d43a4c76ffa940e2b9aea7bbe8686343c694a
- Python: Python 3.11.6
- Docker: Docker version 26.1.3, build b72abbb
- Docker Compose: Docker Compose version v2.27.0
- live 开关: RESEARCH_US_LIVE_BRIDGE_ENABLED 未设置（新仓库无 .env，默认关闭）
- production broker credential: 无（新仓库不包含 .env）

## Test execution log (P0, 2026-08-18)

| # | Command | Exit | Result |
| --- | --- | --- | --- |
| 1 | `python3 scripts/check_version.py` | 0 | OK — canonical 5.0.1, 0 declarations verified, 1 skipped path (`backend_api_python/VERSION` not tracked in QD baseline) |
| 2 | `python3 scripts/check_mojibake.py` | 0 | OK — no corruption markers |
| 3 | `docker compose -f docker-compose.yml config -q` | 0 | OK |
| 4 | `docker compose -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.observability.yml config -q` | 0 | OK |
| 5 | `python3 -m compileall -q app scripts` (in `backend_api_python/`) | 0 | OK — full backend syntax compiles |
| 6 | `python3 -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q` (in `backend_api_python/`) | 4 (usage error) | **BLOCKED** — `ModuleNotFoundError: No module named 'flask'`; sandbox has no network (`pip install` DNS failure) and no readable wheel cache; see Unrun tests |
| 7 | `ruff check app scripts tests` | n/a | **NOT RUN** — `ruff` not installed; same network/pip blockage |
| 8 | QD archive integrity check (747 files) | 0 | OK — 0 missing |
| 9 | Sensitive-file tracking check | 0 | OK — 0 tracked `.env`/secret files |

### Environment blockage details

- `pip install` fails with DNS resolution errors (no network access).
- `/root/.cache/pip/http-v2` contains 211 response bodies owned by `nobody`
  with mode 600 — unreadable, and none are extractable wheels.
- System Python 3.11.6 has `pytest` but no `flask`/`flask_smorest`/`ruff`.
- Consequence: pytest and ruff cannot run in this sandbox. These are
  **unrun tests with a proven environment cause**, not passes.

---

## P0 补验执行记录（2026-08-19，第 2 轮）

上游用户指令 10 项的逐项结果与证据。

### 项 1：.gitignore 修复 — ✅ 完成

新增 `.env.*` 通配 + `!.env.example` / `!**/.env.example` 双白名单（QD 基线块与 DSA 合并块各一份）。
验证 10 个场景全部通过：

- ignored：`.env`、`.env.production`、`.env.staging`、`.env.test`、`.env.local`、`backend_api_python/.env`、`backend_api_python/.env.production`、`sub/.env.test`
- tracked：`.env.example`、`backend_api_python/.env.example`

### 项 2：ADR 状态 — ✅ 完成

`docs/adr/P0-001-baseline-strategy.md` 状态改为
`Pending approval (P0; awaiting human review before Git commit)`。

### 项 3：Python 3.12 测试环境 — ❌ 环境阻塞

已尝试并失败（全部有具体错误证据）：

1. `uv venv --python 3.12` → DNS 解析失败，无法从 GitHub 下载 CPython 3.12
   (`failed to lookup address information: Name or service not known`)。
2. 系统仅 `/usr/bin/python3.11`（3.11.6）；uv 本地缓存仅有 CPython 3.13.14
   (`/root/.local/share/uv/python/cpython-3.13-.../bin/python3.13`)，**不是 3.12**。
3. `uv pip install Flask`（用 3.13 建 venv）→ PyPI DNS 失败。
4. Windows 侧 `/mnt/d/soft/Python/Python314` 为 3.14 且 WSL interop 被禁
   （`UtilBindVsockAnyPort` 错误），不可用。
5. `pip download` / `urllib.urlopen('https://pypi.org')` 均 DNS 失败。
6. `/root/.cache/pip` 的 wheel body 属主 `nobody` mode 600，不可读，无可用 wheel。

结论：**本沙箱无法建立任何可运行 Flask 测试栈的 Python 环境（3.12 或其他）**。
补跑方法（有网络环境）：

```bash
cd backend_api_python
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
```

### 项 4：完整非 network pytest + ruff — ❌ 环境阻塞（同项 3）

无法运行（无 Flask/flask_smorest/ruff，无法安装）。以
`python3 -m compileall -q app scripts`（exit 0）作为最大离线替代。

### 项 5：OpenAPI gate + 安全扫描 — ⚠️ 部分完成（离线子集）

**已运行并通过（离线可执行部分）：**

| 检查 | 结果 |
| --- | --- |
| OpenAPI 产物结构校验（agent JSON 可解析、openapi=3.0.3、51 paths；web YAML 含 info/components/tags/servers/paths/openapi 顶层键，7049 行） | ✅ PASS |
| 离线 secret 扫描（对 git index 全部 722 个文本文件，模式含 private key/AWS AKIA/GitHub token/Slack/Google API/JWT/密码赋值） | ✅ PASS，0 真实凭据；2 处命中为 AWS 官方文档占位符 `AKIAIOSFODNN7EXAMPLE`（与上游 QD e64e1c2 逐字一致） |
| 高危源码模式离线近似（`shell=True`=0、`pickle.loads`=0、不安全 `yaml.load`=0、`verify=False`=0） | ✅ PASS |
| `eval/exec` 命中 10 处复核 | ✅ 全部为上游安全实现：`safe_exec.py` 沙箱 exec（与上游逐字一致）、Redis Lua `client.eval` 限流、`ast.literal_eval`；0 新增风险 |

**未能运行（需网络/依赖）：**

- `spectral lint`（需 npm install @stoplight/spectral-cli）
- `oasdiff breaking`（需下载 oasdiff 二进制）
- `python scripts/export_openapi.py`（需 Flask）
- `pytest tests/test_openapi.py`（需 Flask）
- `bandit`、`pip-audit`、Gitleaks、CodeQL（需安装工具/网络）

### 项 6：Compose 基础服务 + health check — ❌ 环境阻塞

`docker info` → daemon socket `operation not permitted`（沙箱无 Docker daemon 权限）。
配置层验证已通过：

- `docker compose -f docker-compose.yml config -q` → exit 0
- `docker compose -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.observability.yml config -q` → exit 0

运行时 up + health check 无法在本环境执行。

### 项 7：blob hash 对比 — ✅ 完成（PASS）

`docs/P0_BLOB_HASH_COMPARISON.md`：
对 QD `e64e1c2` 全部 **747** 个 tracked blob 做了 sha1 对比。

- 被修改且属治理集（允许）：`.gitignore`、`README.md`
- 意外修改：**0**
- 缺失：**0**
- 结论：**PASS — only governed files modified**

过程中发现并修复：`.env.example` 曾因清理误删，已从
`git show e64e1c2:.env.example` 恢复，复检后 0 缺失。

### 项 8：Git index 后重跑检查 — ✅ 完成

`git add -A` 后（768 个文件入 index）：

| 检查 | 首轮（未入 index） | 本轮（入 index 后） |
| --- | --- | --- |
| `python3 scripts/check_version.py` | `0 declarations verified`（不可接受） | **`1 declarations verified`** ✅ exit 0 |
| `python3 scripts/check_mojibake.py` | OK | OK ✅ exit 0 |
| 真实敏感文件入 index 检查 | — | **0 个** ✅（严格模式：`.env*` 非 example、`.pem/.key/.p12/.pfx`、`id_rsa`、`credentials.json` 等均无） |

说明：宽松 grep 曾命中 4 个文件名含 "secret" 的上游文件
（`tests/test_settings_secret_masking.py`、`tests/test_strategy_secret_handling.py`、
`scripts/generate-secret-key.ps1/.sh`），经逐一复核均为 QD 自带的**测试代码与密钥
生成工具**，不含任何真实凭据值，属合法基线内容。

### 项 9：本文档即项 9 的落实 — ✅ 完成

保留首轮全部失败记录（见上文「Test execution log」），本轮记录追加于其后，
未删除或改写任何历史失败条目。

### 项 10：边界遵守 — ✅ 完成

未实施 P0A（无任何 entrypoint/settings/compose 安全改动）；
未执行 `git commit`（文件仅停留在 index，768 staged, 0 committed）；
等待人工审核。

### 本轮全部可运行命令汇总

| # | 命令 | 退出码 | 结果 |
| --- | --- | --- | --- |
| 1 | `.gitignore` 行为验证（10 场景 git check-ignore） | 0 | 全 PASS |
| 2 | `python3 scripts/check_version.py`（index 后） | 0 | 1 declarations verified ✅ |
| 3 | `python3 scripts/check_mojibake.py`（index 后） | 0 | PASS |
| 4 | 真实敏感文件 index 检查（严格 grep 模式） | 0 | 0 命中 ✅ |
| 5 | OpenAPI 产物结构校验（agent JSON + web YAML 顶层键） | 0 | PASS |
| 6 | 离线 secret 扫描（722 个 staged 文本文件 × 7 模式） | 0 | PASS（0 真实凭据） |
| 7 | 高危源码模式离线扫描（shell/pickle/yaml/verify） | 0 | PASS |
| 8 | eval/exec 10 处复核（与上游 diff） | 0 | 全部上游自带，0 新增 |
| 9 | blob hash 对比（747 文件） | 0 | PASS（仅 2 治理文件改） |
| 10 | `docker compose ... config -q` ×2 | 0/0 | PASS |
| 11 | `python3 -m compileall -q app scripts` | 0 | PASS |
| 12 | `uv venv --python 3.12` | 2 | ❌ DNS（阻塞证据） |
| 13 | `uv pip install Flask` | 1 | ❌ DNS（阻塞证据） |
| 14 | `docker info` | 1 | ❌ daemon 权限（阻塞证据） |

### G0 结论（本轮）

仍**未完全达到 G0**。已达成：基线完整性（747/747）、来源治理、P0 文档结构检查、
版本/mojibake/index 检查、compose 配置解析、OpenAPI 产物结构、离线 secret 扫描、
源码高危模式扫描、全量语法编译。未达成（均为已证明的环境阻塞，非代码问题）：
完整 pytest、ruff、spectral/oasdiff、export_openapi、bandit/pip-audit/gitleaks、
compose up + health check。需在有网络与 Docker 权限的环境按补跑方法执行后，G0 方可最终确认。

### P0 修复补验（2026-08-19，本次会话）

| # | 完整命令 | 执行目录 | 退出码 | 结果 |
| --- | --- | --- | ---: | --- |
| 1 | `python3 scripts/check_docs.py` | 仓库根 | 0 | PASS；方案 B 允许列表生效 |
| 2 | `git -C ../QuantDinger status --short --branch` | 仓库根 | 0 | PASS；clean，HEAD 为 recorded commit |
| 3 | `git -C ../daily_stock_analysis status --short --branch` | 仓库根 | 0 | PASS；clean，HEAD 为 recorded commit |
| 4 | `git -C ../QuantDinger rev-parse HEAD` | 仓库根 | 0 | PASS；`e64e1c227bf3174e441a42143620179b286387e1` |
| 5 | `git -C ../daily_stock_analysis rev-parse HEAD` | 仓库根 | 0 | PASS；`396d43a4c76ffa940e2b9aea7bbe8686343c694a` |
| 6 | Git tree/index blob + mode 核对脚本 | 仓库根 | 0 | PASS；QD 747/747、missing 0、unexpected 0、shared mode diff 0 |

本轮开始时发现目标工作区有未跟踪的空 `.env.example`，未直接覆盖用户文件；经与记录 QD commit 对比确认该文件应为 QD 基线内容，已从 `git -C ../QuantDinger show e64e1c2:.env.example` 恢复并暂存。复核后 staged 文件数为 768、QD 基线覆盖 747/747。

### 环境与开关快照

- Python 当前可执行版本：3.11.6；项目目标：3.12。
- Docker：26.1.3；Docker Compose：v2.27.0（配置解析可执行，daemon 运行权限不足）。
- `RESEARCH_US_LIVE_BRIDGE_ENABLED`：未设置，按默认关闭。
- production broker/MFA credential：未提供，未写入任何真实凭据。
- 目标仓库 HEAD：无 commit（P0 baseline 尚未人工批准提交）。
- staged 文件数：768；QD recorded baseline tracked 文件数：747。

### 仍未运行 / 必须补跑

以下项目**不能标记为通过**：

1. Python 3.12 venv、依赖安装、完整非 integration/stress pytest、ruff：当前无 Python 3.12，网络/DNS 不可用，依赖无法安装。
2. `SKIP_STARTUP_HOOKS=1 OPENAPI_ENABLED=false python scripts/export_openapi.py ...`、OpenAPI diff、`pytest tests/test_openapi.py`：缺 Flask 依赖。
3. `bandit`、`pip-audit`、`spectral`、`oasdiff`：工具未安装且无法联网安装。
4. Gitleaks、CodeQL：当前环境未具备可执行工具/运行条件，未运行。
5. `docker compose ... up -d`、`docker compose ... ps`、health check：Docker daemon socket 权限拒绝；两条 `config -q` 仅证明静态配置可解析，不等同于服务启动通过。

### 本轮实际执行补充（2026-08-19）

| 完整命令 | 执行目录 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `python3 -m compileall -q app scripts` | `backend_api_python/` | 0 | PASS |
| `python3 scripts/check_requirements_lock.py` | `backend_api_python/` | 0 | PASS；33 direct dependencies |
| `python3 scripts/backend_quality_check.py` | `backend_api_python/` | 0 | PASS |
| `python3 -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q` | `backend_api_python/` | 4 | 未通过/环境阻塞；收集阶段 `ModuleNotFoundError: No module named 'flask'`；2 skipped，2 errors |
| `ruff check app scripts tests` | `backend_api_python/` | 127 | 未运行；`ruff` 未安装 |
| `docker compose -f docker-compose.yml config -q` | 仓库根 | 0 | PASS |
| `docker compose -f docker-compose.yml -f docker-compose.production.yml -f docker-compose.observability.yml config -q` | 仓库根 | 0 | PASS |
| `SKIP_STARTUP_HOOKS=1 OPENAPI_ENABLED=false python3 scripts/export_openapi.py --output ../docs/api/openapi.generated.yaml` | `backend_api_python/` | 2 | 未运行；脚本存在，但第一次调用未切换到 `backend_api_python/`，保留该失败记录 | 
| `SKIP_STARTUP_HOOKS=1 OPENAPI_ENABLED=false python3 scripts/export_openapi.py --output ../docs/api/openapi.generated.yaml` | `backend_api_python/` | 1 | 未通过/环境阻塞；正确入口执行后 `ModuleNotFoundError: No module named 'yaml'` |
| `spectral lint docs/api/openapi.yaml --ruleset .spectral.yaml` | 仓库根 | 127 | 未运行；`spectral` 未安装 |
| `spectral lint docs/agent/agent-openapi.json --ruleset .spectral.agent.yaml` | 仓库根 | 127 | 未运行；`spectral` 未安装 |
| `docker info` | 仓库根 | 0 | PASS；daemon 可访问，本轮之前记录的 socket 权限阻塞未复现 |
| `docker compose -f docker-compose.yml up -d` | 仓库根 | 18 | 未完成；Docker Hub 拉取超时，服务未启动/未做 health check |

工具盘点：`oasdiff`、`bandit`、`pip-audit`、`gitleaks`、`codeql` 不在 PATH；Node/npm/uv 可用，但未安装所需 npm/扫描工具。`docker info` 显示 Docker daemon 可访问，但 `compose up` 仍因外网 registry 超时失败，不能把运行时验收标记为通过。

本轮新增的失败和阻塞记录保留在此处；未用 compileall、静态扫描或定向检查替代完整验收。

---

## P0 收尾第三轮（2026-08-19T10:33Z，按 CLAUDE_NEXT_WORK_PROMPT.md）

### Git 状态证据

| 命令 | 输出摘要 |
| --- | --- |
| `git status --short --branch` | `## No commits yet on main`；768 staged（全为 A）；无 unstaged 修改 |
| `git diff --name-status` / `git diff --summary` | 空（0 个 unstaged 差异） |
| `git diff --cached --name-only` | 768 |
| `git ls-files --others --exclude-standard` | `CLAUDE_NEXT_WORK_PROMPT.md`、`CLAUDE_REVIEW_FIX_PROMPT.md`（两个提示词均未加入 baseline） |

### 上游实测（与提示词预期不同，以实测为准）

`git -C ../QuantDinger status --porcelain=v1 --untracked-files=all` 输出为空；
`git -C ../daily_stock_analysis ...` 输出为空；两仓库 `git diff --summary` 与
`git diff --name-only` 均为空；`core.filemode=true`。HEAD 分别仍为
`e64e1c227bf3174e441a42143620179b286387e1` 与 `396d43a4c76ffa940e2b9aea7bbe8686343c694a`，
无漂移。

结论：**当前实测两个上游均为 clean**（此前规划文档记录的 QD 3 项 / DSA 8 项
mode 变化在本次检查时不存在；上一轮 manifest 写 clean 与当时实测一致，本轮按
扩展格式重生成并附带说明）。未对上游做任何清理、还原或提交。

### staged vs 工作树 mode 说明

文件系统 `stat` 显示 747 个共享文件 mode 为 664/775（WSL drvfs/9p `metadata`
挂载产物），但 `git diff` 与 `git status` 均报告 **0 个 unstaged mode 变化**，
且 index 中 mode 正确（`install.sh` 等三脚本 `100755`、`docker-entrypoint.sh`
`100644`，与 QD 上游一致）。按提示词要求不 chmod、不清理用户文件；commit 时
以 index mode 为准，权限不会降级。

### 本轮命令结果

| 完整命令 | 执行目录 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `python3 scripts/check_docs.py` | 仓库根 | 0 | PASS |
| `python3 scripts/check_version.py` | 仓库根 | 0 | PASS（1 declarations verified） |
| `python3 scripts/check_mojibake.py` | 仓库根 | 0 | PASS |
| `python3 scripts/check_requirements_lock.py` | `backend_api_python/` | 0 | PASS（33 direct deps） |
| `python3 scripts/backend_quality_check.py` | `backend_api_python/` | 0 | PASS |
| `python3 -m compileall -q app scripts` | `backend_api_python/` | 0 | PASS（无权限失败） |
| index 对比脚本（blob hash + mode） | 仓库根 | 0 | QD 747/747、missing 0、unexpected content 0、index mode diff 0、治理新增 21、无 DSA 源码树 |

### 仍未运行（阻塞，不得标记 PASS）

与上一节相同：完整 pytest（无 Flask）、ruff（未安装）、export_openapi/diff/
test_openapi（无 PyYAML/Flask）、spectral/oasdiff（未安装）、bandit/pip-audit/
gitleaks/CodeQL（未安装、无法联网）、compose up + ps + health check（Docker Hub
拉取超时；`config -q` 仅证明静态配置）。补跑命令见本文件上方补跑方法；
责任环境：具备 Python 3.12、网络、Docker daemon + registry 访问的执行者。


---

## G0 完整验收（第四轮，2026-08-21T02:32Z，按 CLAUDE_P0_CANDIDATE_FINALIZATION_PROMPT.md）

### 环境变化

本轮网络与 Python 3.12 已可用（此前轮次的环境阻塞部分解除）：

- 解释器：`backend_api_python/.venv` = CPython 3.12.13（`uv venv --python 3.12`）；
- 依赖：`uv pip install -r requirements.lock -r requirements-dev.txt` 全部安装成功；
- 系统解释器仍为 3.11.6（仅用于此前轮次的离线检查）；
- PostgreSQL 18.3-alpine 与 Redis 8-alpine 以隔离容器运行（127.0.0.1:5432 / :6379，测试专用）；
- Docker Hub 直连超时，经镜像源（daocloud/ghcr.nju 等）拉取镜像后打本地标签。

### index mode 修复（第三节要求）

9 个治理 Markdown 曾被错误暂存为 100755（drvfs 产物），已用
`git update-index --chmod=-x` 仅修 index，未改内容、未触碰上游。
修复后 `git ls-files --stage | grep '^100755'` 仅剩 3 个真实脚本
（install.sh / generate-secret-key.sh / verify_moex.py）；66 个 `*.md` 全部 100644。

### 本轮命令结果

| 完整命令 | 执行目录 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `check_docs.py` / `check_version.py` / `check_mojibake.py` | 根 | 0/0/0 | PASS |
| `check_requirements_lock.py` / `backend_quality_check.py`（3.12 venv） | backend | 0/0 | PASS |
| `python -m py_compile run.py` | backend | 0 | PASS |
| `python -m compileall -q app scripts tests`（3.11） | backend | 0 | PASS |
| `docker compose … config -q` ×5（含 ghcr / build / observability / production 组合） | 根 | 0 | 全 PASS |
| 核心模块导入冒烟（create_app/settings/init_openapi） | backend | 0 | PASS |
| `QD_PROCESS_ROLE=migration python -m app.commands.migrate`（真实 PostgreSQL） | backend | 0 | PASS（迁移后 77 张表） |
| `pytest -m "not integration and not stress" --ignore=tests/release_gate -q` | backend | 0 | **1381 passed, 5 deselected, 155.87s** |
| `pytest tests/release_gate -q` | backend | 0 | 1 passed, 1.56s |
| `pytest -m db_integration -q` | backend | 5 | no tests ran（无此标记用例） |
| `ruff check app scripts tests` | backend | 0 | All checks passed |
| `export_openapi.py --output ../docs/api/openapi.generated.yaml` | backend | 0 | 导出成功 |
| `diff -u docs/api/openapi.yaml docs/api/openapi.generated.yaml` | 根 | 1 | **FAIL — 见下述 OpenAPI 漂移** |
| `spectral lint docs/api/openapi.yaml`（v6.16.3） | 根 | 0 | 0 errors, 127 warnings |
| `spectral lint docs/agent/agent-openapi.json` | 根 | 0 | 0 errors（0 problems 子集） |
| `oasdiff breaking … --fail-on ERR`（v1.10.4） | 根 | 0 | 无破坏性变更 |
| `pytest tests/test_openapi.py -q` | backend | 0 | 5 passed, 35.46s |
| `bandit -q -r app -x app/data -lll -ii` | backend | 0 | 无命中 |
| `pip-audit -r requirements.lock` | backend | 1 | **5 个已知漏洞公告**：aiohttp PYSEC-2026-3546/3547（3.14.1→3.14.2）、cryptography PYSEC-2026-3552（49.0.0→50.0.0）、pypdf PYSEC-2026-3655/3656（6.14.2→6.15.0） |
| `gitleaks dir --redact .`（v8.24.3） | 根 | 1（2 命中） | 2 处 generic-api-key：README.md（架构表误报，P0 前缀致行号漂移使上游 .gitleaksignore 指纹失配）、AGENT_QUICKSTART.md（`$QUANTDINGER_AGENT_TOKEN` shell 变量，文件与上游逐字节一致）；均为上游已接受的文档误报 |
| `pip install -e './mcp_server[dev]'` | 根 | 0 | PASS |
| `pytest mcp_server/tests -q` | 根 | 0 | **29 passed, 18.78s** |
| `python -m build mcp_server` | 根 | 0 | quantdinger_mcp-0.5.0 sdist+wheel 构建成功 |
| `docker build -t quantanalyinvest-p0-g0:local backend_api_python` | 根 | 100 | 首次：容器内 apt 无法访问 deb.debian.org；第二次（BUILD_REGION=cn）：aliyun bookworm 主仓间歇不可达，`libssl-dev`/`gosu` 缺失；第三次重试进行中 |

### OpenAPI spec 漂移（重要发现）

`docs/api/openapi.yaml`（与 QD e64e1c2 逐字节一致）缺少代码中存在的 3 个端点：
`/api/indicator/chart-preview`、`/api/strategies/position-ownership`、
`/api/strategies/position-ownership/repair`。已核实上游 QD e64e1c2 的同名 spec
同样不含这些端点（`git show e64e1c2:docs/api/openapi.yaml | grep -c chart-preview` = 0），
即**该漂移为 QD 基线 commit 固有**，非 P0 引入。所有差异均为新增（0 删除），
oasdiff 判定无破坏性变更。是否在 P0 内重新生成 spec 属基线内容变更，需人工决策；
`openapi.generated.yaml` 为验证产物，未加入 baseline。

### MCP matrix 说明

仅 Python 3.12 已验证（29 passed）。3.10 / 3.13 未运行，未声明完整 matrix 复现。

### 仍未完成

- Docker build（第三次重试中）/ compose up / ps / health check：镜像源间歇故障，未通过前不得标记 PASS；
- CodeQL 与 `gitleaks git` 模式（CI v8.30.1 镜像）：依赖 commit 后的 GitHub Actions，本地不可替代；
- pip-audit 5 个漏洞公告需依赖升级决策（属治理决策，非本轮范围）。


### Docker / Compose 最终结果（2026-08-21T03:26Z）

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `docker build --build-arg BUILD_REGION=cn -t quantanalyinvest-p0-g0:local backend_api_python` | 0 | **构建成功**（第三次；前两次因 deb.debian.org 不可达与 aliyun bookworm 主仓间歇故障失败，失败记录保留） |
| `BACKEND_LOCAL_IMAGE=quantanalyinvest-p0-g0:local docker compose -f docker-compose.yml up -d` | 0 | **10 服务全部启动**（首次因本会话测试容器占用 6379 失败一次，移除测试容器后成功） |
| `docker compose -f docker-compose.yml ps` | 0 | backend/celery-beat/celery-worker/scheduler-worker/trading-worker/frontend/mobile/redis/redis-jobs/postgres 全部 **Up (healthy)**；migration **Exited (0)** |
| `docker compose -f docker-compose.yml ps --format json` | 0 | 逐容器 State/Health 均为 running/healthy |
| `curl http://127.0.0.1:5000/api/health` | 0 | **HTTP 200**，`{"status":"healthy","role":"api"}` |
| `curl http://127.0.0.1:5000/api/health/ready` | 0 | **HTTP 200** |
| 容器日志密钥扫描（backend/worker×4/migration，比对 SECRET_KEY/CREDENTIAL_ENCRYPTION_KEY/ADMIN_PASSWORD 与默认口令） | 0 | **0 命中** |
| `docker compose -f docker-compose.yml down`（未使用 -v） | 0 | 栈已停止，volume 未删除 |

frontend/mobile 镜像经 ghcr 镜像源（ghcr.nju.edu.cn）拉取后打官方标签；MCP 服务不在默认 compose（仅 build overlay），MCP 已以 pip + pytest + build 方式验证。

### G0 结论（第四轮）

**本地可执行的全部 G0 验收已通过**：完整 pytest（1381 passed）、release gate、ruff、
backend quality、依赖锁、真实 PostgreSQL 迁移、OpenAPI 契约测试、spectral、oasdiff、
bandit、MCP（29 passed + 构建）、Docker build、Compose 10 服务 healthy、health/ready 200、
日志无密钥泄漏。

**遗留（需人工/commit 后处理，不阻塞 candidate 评定但 G0 正式确认需过 CI）**：

1. OpenAPI spec 漂移：基线 spec 缺 3 个代码中存在的端点（QD e64e1c2 固有，纯新增，无破坏性）；是否重新生成 spec 待人工决策；
2. pip-audit 5 个 PYSEC 公告（aiohttp/cryptography/pypdf）需依赖升级决策；
3. gitleaks `dir` 模式 2 处上游已接受误报（README 前缀致 .gitleaksignore 指纹失配）；CI 的 `gitleaks git`（v8.30.1）与 CodeQL 需 commit 后经 GitHub Actions 执行；
4. MCP matrix 仅 3.12 验证（3.10/3.13 未运行）。


---

## P0/G0 第五轮现场复核（2026-08-31T08:42:36Z）

### 当前环境与 Git 状态

- 执行环境：Windows 11 PowerShell，NT 10.0.26200.0。
- 当前解释器：`D:\soft\Python\Python314\python.exe`，Python 3.14.2；目标仍为 Python 3.12。
- WSL 查询返回 `Wsl/EnumerateDistros/Service/E_ACCESSDENIED`；仓库内 Linux `.venv` 不能由 Windows 直接执行。
- Docker、Ruff、pip-audit、Bandit、Gitleaks、Spectral、oasdiff 均不在 PATH。
- 目标仓库：`No commits yet on main`；768 staged、3 个 mode-only unstaged、5 个 untracked；content-oriented unstaged diff 为 0。
- untracked 提示词、`.claude/settings.local.json` 和 `docs/api/openapi.generated.yaml` 未加入 baseline。
- 当前进程环境未设置 research/live 开关；未读取本地 ignored `.env` 的敏感内容。本轮未使用 broker/MFA 凭据，未启动服务或进行真实交易。

### 本轮修复

1. `docs/api/openapi.yaml` 同步 3 个已经存在于 QD baseline 代码中的端点；未新增、删除或修改 runtime route。
2. `requirements.txt` 将 cryptography floor 提升到 50.0.0、pypdf floor 提升到 6.15.0；`requirements.lock` 最小提升 aiohttp/cryptography/pypdf 到 3.14.2/50.0.0/6.15.0。
3. `docs/adr/P0-001-baseline-strategy.md` 记录 OpenAPI exact-diff 决策，未降低 CI 规则。
4. dirty manifest、baseline、blob/mode 对比和本 checklist 按当前现场刷新；未修改两个上游工作树。

### 当前执行结果

| 完整命令 | 执行目录 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `python scripts/check_docs.py` | 根 | 0 | PASS；文档结构、链接、fence、资产有效 |
| `python scripts/check_version.py` | 根 | 0 | PASS；canonical 5.0.1，1 declaration |
| `python scripts/check_mojibake.py` | 根 | 0 | PASS |
| `python scripts/check_requirements_lock.py` | backend | 0 | PASS；33 direct dependencies |
| `python scripts/backend_quality_check.py` | backend | 0 | PASS |
| `python -m py_compile run.py` | backend | 0 | PASS |
| `python -m compileall -q app scripts tests` | backend | 0 | PASS；仅语法层，不替代 pytest |
| PyYAML parse + 3 required paths assertion | 根 | 0 | PASS；246 paths |
| `git diff --no-index --quiet -- docs/api/openapi.yaml docs/api/openapi.generated.yaml` | 根 | 0 | PASS；两个文件 SHA-256 均为 `40F7E7E4427F28EFA46CF572D3DE5A9B1EF905F21462438E5679675790B6CB4B` |
| QD tree/index blob+mode 复核 | 根 | 0 | 747/747、missing 0、allowed content diff 6、unexpected 0、index mode diff 0、extra 21 |

### 依赖修复验证边界

三个 pin 使用 2026-08-21 pip-audit 报告给出的 fixed versions。当前 `check_requirements_lock.py`
证明 direct constraints 与 exact pins 一致，但它不是依赖解析器或漏洞扫描器。尝试把
`uv` 临时安装到系统临时目录，两次均因权限审批服务超时而未执行。因此以下结论仍待
Python 3.12 + 网络环境复核：新 wheel 可安装、传递依赖可解析、完整回归通过、
`pip-audit` 零未处理漏洞。

### 仍未运行 / 必须补跑

```bash
cd backend_api_python
uv pip compile requirements.txt --output-file requirements.lock --python-version 3.12 \
  --upgrade-package aiohttp --upgrade-package cryptography --upgrade-package pypdf
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.lock -r requirements-dev.txt
.venv/bin/python -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q
.venv/bin/python -m pytest tests/release_gate -q
.venv/bin/ruff check app scripts tests
.venv/bin/bandit -q -r app -x app/data -lll -ii
.venv/bin/pip-audit -r requirements.lock --progress-spinner off
SKIP_STARTUP_HOOKS=1 OPENAPI_ENABLED=false \
  .venv/bin/python scripts/export_openapi.py --output ../docs/api/openapi.generated.yaml
.venv/bin/python -m pytest tests/test_openapi.py -q
cd ..
spectral lint docs/api/openapi.yaml --ruleset .spectral.yaml
spectral lint docs/agent/agent-openapi.json --ruleset .spectral.agent.yaml
oasdiff breaking docs/api/openapi.yaml docs/api/openapi.generated.yaml --fail-on ERR
```

还需执行 MCP Python 3.10/3.12/3.13 matrix、Docker build/Compose healthy/API
health/log secret scan，以及 candidate commit 后的 `gitleaks git`、CodeQL 和 GitHub CI。
在这些检查完成前，P0/G0 状态保持未完成，不创建 baseline commit，不开始业务迁移。

---

## P0/G0 第六轮：新锁完整复验（2026-09-02T04:30Z，WSL2 Linux）

### 环境

- WSL2（Linux 6.6.87.2-microsoft-standard-x86_64），仓库位于 /mnt/d（drvfs）。
- `.venv` = Python 3.12.13（仓库内）；uv 0.11.32（`/root/.local/bin/uv`）。
- Docker daemon 可用；网络可达（PyPI / GitHub，经代理）。spectral 经 nvm npm；oasdiff 1.30.0 经 GitHub release deb 手动解包（npm "oasdiff" 是占位包，不可用）。

### 依赖重锁（本轮关键发现）

第五轮手工 pin 的 `aiohttp==3.14.2` **无法通过 Python 3.12 resolver**：`ccxt==4.5.70` 精确依赖 `aiohttp==3.14.1`。按本文件第五轮记录的官方命令重编译：

```bash
cd backend_api_python
uv pip compile requirements.txt --output-file requirements.lock --python-version 3.12 \
  --upgrade-package aiohttp --upgrade-package cryptography --upgrade-package pypdf
```

结果（全锁仅 4 个版本变化，范围最小）：

| 包 | 第五轮手工 pin | 第六轮 resolver | 说明 |
| --- | --- | --- | --- |
| aiohttp | 3.14.2（不可解析） | **3.14.3** | pip-audit 公告修复线之上 |
| cryptography | 50.0.0 | **50.0.1** | 同上 |
| pypdf | 6.15.0 | **6.16.2** | 同上 |
| ccxt | 4.5.70 | **4.5.76**（连带） | 4.5.70 精确 pin aiohttp==3.14.1，必须升级 |
| setuptools | 83.0.0 | 移除（resolver 决定） | 代码无 `pkg_resources` 运行时依赖（已 grep 核实） |

`requirements.lock` 文件头已记录本轮 re-lock 命令与决策。`requirements.txt` 的 cryptography>=50.0.0 / pypdf>=6.15.0,<7 floor 与新锁兼容（3.14.3/6.16.2 满足），无需改动；aiohttp 为传递依赖，无 direct 约束。`check_requirements_lock.py` 通过（33 direct）。

### 执行结果

| 完整命令 | 执行目录 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| `uv pip install --python .venv/bin/python -r requirements.lock -r requirements-dev.txt` | backend | 0 | 新锁安装成功；导入验证 aiohttp=3.14.3 ccxt=4.5.76 cryptography=50.0.1 pypdf=6.16.2 |
| `.venv/bin/python -m pytest -m "not integration and not stress" --ignore=tests/release_gate -q` | backend | 0 | **1399 passed**（1381 基线 + 18 新 Mock 扣费测试），5 deselected，99-111s |
| `.venv/bin/python -m pytest tests/release_gate -q` | backend | 0 | 1 passed |
| `.venv/bin/ruff check app scripts tests` | backend | 0 | All checks passed |
| `.venv/bin/bandit -q -r app -x app/data -lll -ii` | backend | 0 | 0 命中 |
| `.venv/bin/pip-audit -r requirements.lock --progress-spinner off` | backend | 0 | **No known vulnerabilities found** |
| `SKIP_STARTUP_HOOKS=1 OPENAPI_ENABLED=false .venv/bin/python scripts/export_openapi.py --output ../docs/api/openapi.generated.yaml` | backend | 0 | 导出成功 |
| `diff -u ../docs/api/openapi.yaml ../docs/api/openapi.generated.yaml` | backend | 0 | exact diff 0；两文件 SHA-256 `40F7E7E4427F28EFA46CF572D3DE5A9B1EF905F21462438E5679675790B6CB4B`（与第五轮一致） |
| `SKIP_STARTUP_HOOKS=1 .venv/bin/python -m pytest tests/test_openapi.py -q` | backend | 0 | 5 passed |
| `spectral lint docs/api/openapi.yaml --ruleset .spectral.yaml` | root | 0 | 0 errors（201 warnings，上游既有风格警告） |
| `spectral lint docs/agent/agent-openapi.json --ruleset .spectral.agent.yaml` | root | 0 | 0 errors（127 warnings，同上） |
| `oasdiff breaking docs/api/openapi.yaml docs/api/openapi.generated.yaml --fail-on ERR`（1.30.0 本地二进制） | root | 0 | No changes detected |
| `python scripts/check_docs.py` / `check_version.py` / `check_mojibake.py` | root | 0 | PASS（含新 ADR P0-002） |
| `docker compose build backend`（BUILD_REGION=cn） | root | 0 | build 成功（见环境备注） |
| `docker compose up -d` → 10 服务 healthy | root | 0 | backend/celery-worker/celery-beat/scheduler-worker/trading-worker/postgres/redis/redis-jobs/frontend/mobile 全部 healthy |
| `curl /api/health`、`curl /api/health/ready`（容器内） | - | 0 | 均 200；ready 含 postgres=true、celery_broker=true |
| PostgreSQL 表数核对 | - | 0 | 78 表 = init.sql 78 个 CREATE TABLE（含 `qd_usdt_orders`；8-21 记录 77 为计数口径差异） |
| 日志密钥扫描（backend 等 5 服务） | - | 0 | 0 密钥泄漏（唯一关键词匹配为 `[OK] SECRET_KEY is configured` 状态消息）；0 traceback |
| `docker compose down`（无 `-v`） | root | 0 | 卷保留（postgres_data 等 4 卷） |
| MCP 3.10：`uv venv --python 3.10` + `-e './mcp_server[dev]'` + `pytest mcp_server/tests -q` | root | 0 | **29 passed** |
| MCP 3.13：同上（3.13.14） | root | 0 | **29 passed** |
| MCP build：`python -m build mcp_server`（3.13） | root | 0 | sdist + wheel 构建成功 |
| MCP 3.12：29 passed + 构建（2026-08-21 第四轮） | root | 0 | 历史证据（本轮未复跑；3.10/3.13 已补齐 matrix） |
| 上游 manifest 刷新（QD / DSA，raw + content 双视图） | - | - | 双仓库均 **clean**，HEAD 无漂移；DSA `CLAUDE.md` 已确认为 symlink（mode 120000，blob 47dc3e3d）→ `AGENTS.md`，第五轮 indeterminate 结案（drvfs symlink 元数据误报） |

### Docker 构建环境备注

容器内无法直连 `deb.debian.org`（WSL2 NAT/网络特征；宿主可达 PyPI/GitHub 但容器内 80 端口到该域不可达，global 分支 apt update 拿不到索引 → `Unable to locate package`，重试 2 次确认）。`BUILD_REGION=cn`（Dockerfile 自带分支，走 mirrors.aliyun.com）构建成功。这是**本地环境网络特征**，非 Dockerfile 缺陷；GitHub Actions CI 的 global 分支不受影响。

### 未运行 / 待 commit 后执行

- `gitleaks git`（v8.30.1）：需要 candidate commit；本地仅可 `gitleaks dir`（8-21 已跑，2 处上游已接受误报）。
- CodeQL、GitHub Actions 全矩阵（basic-ci / mcp-ci / openapi-ci / security-ci / docker-publish）。
- 当前仍为 0 commits：等待人工批准 candidate commit。

### G0 结论（第六轮）

第五轮列出的全部本地复验阻塞项已在新锁上完成并全部通过。**P0/G0 本地验收完整，candidate baseline ready for human commit**；G0 正式通过以 commit 后 CI（gitleaks git / CodeQL / Actions）为最终证据。
