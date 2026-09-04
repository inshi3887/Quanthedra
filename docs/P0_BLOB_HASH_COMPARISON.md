# P0 Blob Hash and Git Mode Comparison (QD e64e1c2 baseline)

- Generated: 2026-09-02T04:30:00Z (recomputed from the current candidate index; 2026-08-31T08:42:36Z snapshot below)
- Recorded upstream commit: `e64e1c227bf3174e441a42143620179b286387e1`
- QD tracked files at recorded commit: **747**
- QuantAnalyInvest staged files: **772**
- Baseline coverage: **747/747** tracked files present; missing **0**

## Comparison summary

| Dimension | Result | Notes |
| --- | ---: | --- |
| QD baseline tracked files | 747 | `git ls-tree -r --name-only e64e1c2` |
| Staged files | 772 | Includes 25 explicitly governed P0 files |
| Missing QD baseline files | 0 | Every QD path is staged |
| Content differences against QD blob | 8 | Governance files plus the documented OpenAPI/dependency/security G0 repairs and ADR-P0-002 mock-payment seam below |
| Allowed P0 content differences | 8 | All eight are documented P0/G0 corrections |
| Unexpected content differences | 0 | No unrelated business/runtime source drift found |
| Git mode differences for shared paths | 0 | Compared from upstream tree mode to index mode |
| Worktree/index mode differences | 11 | drvfs mode-only artifacts on governance Markdown (see Worktree note); content diffs 0 |

## Content changes

| File | Classification | Reason |
| --- | --- | --- |
| `.gitignore` | Allowed governance change | P0 ignore policy, including `.env*` handling |
| `README.md` | Allowed governance change | Unified repository/P0 baseline documentation |
| `scripts/check_docs.py` | Allowed governance change | Explicitly permits canonical P0 audit documents in `docs/` root |
| `docs/api/openapi.yaml` | Allowed G0 contract repair | Synchronizes three routes already present in the recorded QD code with the exact-diff OpenAPI gate |
| `backend_api_python/requirements.txt` | Allowed G0 security repair | Raises the cryptography and pypdf security floors without changing application code |
| `backend_api_python/requirements.lock` | Allowed G0 security repair | 2026-09-02 resolver re-lock: aiohttp 3.14.3 / cryptography 50.0.1 / pypdf 6.16.2 (+ forced ccxt 4.5.76; setuptools pin dropped) — pip-audit clean |
| `backend_api_python/app/services/usdt_payment/watchers/base.py` | Allowed ADR-P0-002 seam | Mock payment provider resolution in `get_watcher` (opt-in `USDT_PAY_PROVIDER=mock`; default behaviour unchanged) |
| `backend_api_python/app/services/usdt_payment/chains.py` | Allowed ADR-P0-002 seam | Adds the doubly-hidden `MOCK` chain spec for the simulated payment flow |

New governance additions (2026-09-02): `backend_api_python/app/services/usdt_payment/mock_provider.py`, `backend_api_python/tests/test_usdt_payment_mock.py`, `backend_api_python/tests/test_usdt_payment_mock_service.py`, `docs/adr/P0-002-mock-payment-provider.md` — all authorised by the user during the P0 round and documented in ADR-P0-002; production billing path untouched.

## Git mode comparison

Git mode was compared independently from blob content. The following required executable paths retain their upstream modes:

| File | QD mode | Staged mode | Result |
| --- | ---: | ---: | --- |
| `install.sh` | `100755` | `100755` | PASS |
| `scripts/generate-secret-key.sh` | `100755` | `100755` | PASS |
| `backend_api_python/scripts/verify_moex.py` | `100755` | `100755` | PASS |
| `backend_api_python/docker-entrypoint.sh` | `100644` | `100644` | PASS (upstream is non-executable) |

No permission change is classified as an unexpected change.

## Missing files

- None. QD baseline coverage is 747/747.

## Governance set

The P0 governance set permits audit/documentation changes in:

- `.gitignore`
- `README.md`
- `AGENTS.md`
- `THIRD_PARTY_NOTICES.md`
- `UPSTREAM_SOURCES.md`
- `scripts/check_docs.py`
- `docs/BASELINE.md`
- `docs/DEPENDENCY_REPORT.md`
- `docs/DIRTY_MANIFEST_DSA.md`
- `docs/DIRTY_MANIFEST_QUANTDINGER.md`
- `docs/P0_BLOB_HASH_COMPARISON.md`
- `docs/P0_CHECKLIST.md`
- `docs/P0_ENVIRONMENT.md`
- `docs/adr/P0-001-baseline-strategy.md`
- `docs/adr/P0-002-mock-payment-provider.md`

The other 25 staged paths are P0 governance additions (21 from earlier rounds plus the 4 ADR-P0-002 files listed under Content changes) that do not replace or alter QD baseline files beyond the documented seam. DSA source tree files are not present.

## Governance-file mode audit (21 additions)

Previous rounds only audited shared-path modes. The 2026-08-20 round found that
9 governance Markdown files had been staged with executable mode `100755`
(a Windows/WSL artifact of the drvfs mount). They were corrected in the index
only, via `git update-index --chmod=-x` — file contents untouched, no upstream
chmod performed:

- `CLAUDE_DEVELOPMENT_PROMPT.md`
- `DEVELOPMENT_PLAN第二版.md` / `第三版.md` / `第四版.md` / `第五版.md` / `第六版.md` / `第七版.md` / `第八版.md`
- `P14_SAFE_PROFILE.md`

Post-fix verification (`git ls-files --stage | grep '^100755'`) lists exactly 3
entries — all genuine executable scripts:

| File | Index mode | Upstream mode |
| --- | ---: | ---: |
| `install.sh` | `100755` | `100755` |
| `scripts/generate-secret-key.sh` | `100755` | `100755` |
| `backend_api_python/scripts/verify_moex.py` | `100755` | `100755` |

All 73 staged `*.md` files are `100644`. `backend_api_python/docker-entrypoint.sh`
remains `100644` (matches QD upstream; the Dockerfile chmods it inside the image).
All 21 governance additions are `100644`.

## Worktree note

The 2026-09-02 WSL2 observation reports **11 mode-only** worktree differences,
all on governance Markdown files (8 development-plan/prompt files plus 3
docs/manifests): drvfs mount presents worktree files as `100755` while the
index holds `100644`. The content-oriented view
(`git -c core.filemode=false diff --numstat`) is **empty** — zero content
differences. The earlier Windows-only 3-script observation no longer applies:
from WSL2 the three genuine scripts match their index modes exactly. The
index, which is what a commit records, retains the correct upstream modes.

## Verdict

**P0 candidate baseline comparison: PASS (2026-09-02).** Content changes are
limited to the documented P0 governance, OpenAPI, dependency-security, and
ADR-P0-002 mock-payment corrections. No unexpected content change, index mode
change, or missing QD baseline file was found. This integrity result does not
by itself mark G0 complete; commit-based CI evidence (`gitleaks git`, CodeQL,
GitHub Actions matrix) is tracked separately.
