# Dependency Report (P0)

> Comparison of key dependency constraints between the two upstream projects,
> based on the recorded baseline commits. Produced by inspecting
> `requirements*.txt` in both repositories; no dependency was changed in P0.

## Baseline facts

- **QuantDinger** (this repository's baseline) pins Flask and does **not**
  depend on FastAPI in the backend (`mcp_server` also has no FastAPI).
- **daily_stock_analysis** (migration source, not imported in P0) uses
  FastAPI for its web layer and a much wider data-source SDK set.

## Key dependency matrix

| Package | QuantDinger (baseline) | daily_stock_analysis | Conflict / note |
| --- | --- | --- | --- |
| Flask | `Flask==3.1.3`, `flask-smorest<0.48`, `flask-cors==6.0.5` | not used | QD's OpenAPI gate depends on flask-smorest; DSA endpoints must be re-mounted as Flask blueprints, never kept as FastAPI (P9). |
| FastAPI | none | `fastapi>=0.109.0` | **Do not install into the QD backend.** DSA's FastAPI layer is replaced by Flask blueprints during migration. |
| pandas | `>=3.0.5` | `>=2.0.0` (exchange-calendars comment warns <4.5 incompatible with pandas 3 "T") | QD already targets pandas 3; DSA code must be validated against pandas 3 during P5-P8. |
| litellm | `>=1.93.0,<1.94` | `>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0` | Overlap exists but QD's upper bound is stricter; unify on QD's bound and re-test DSA prompt paths. |
| longbridge | not in QD backend | `==0.2.74` (Linux, py<3.12) / `>=4.0.5,<5` otherwise | Two incompatible major versions with platform markers; introduce only in the Plan that needs it, with an explicit pin decision. |
| exchange-calendars | `>=4.13.2,<5` | `>=4.13.0` | Compatible ranges; keep QD's `<5` bound. |
| akshare | `>=1.18.80` | `>=1.12.0` | Keep QD's newer floor. |
| yfinance | `>=1.5.2` | `>=0.2.0` | Keep QD's newer floor. |
| efinance / baostock / tushare / PyTDX | not in QD | used by DSA | CN/HK providers migrate in P6; unused SDKs must not enter the default worker image (P6 task 1). |
| SQLAlchemy | not in QD backend | `>=2.0.0` (DSA) | DSA repository bindings are removed during migration (P11 task 1). |
| celery[redis] | `>=5.6.3,<6` | not core-listed | QD's Celery remains the task base (P9/P10). |
| redis | `>=6.4.0,<6.5` | indirect | Keep QD's bound. |
| numpy | indirect | `>=1.24.0` | Follow pandas 3 resolution. |

## Policy

1. P0 changes **no** dependencies; the baseline stays runnable as-is.
2. DSA dependencies are introduced only in the Plan that migrates the
   corresponding capability, each addition recorded in `UPSTREAM_SOURCES.md`
   and pinned to a version compatible with the table above.
3. The backend stays Flask/flask-smorest; FastAPI is not added.
4. Any future bump of pandas/litellm/exchange-calendars must run the full
   backend regression plus the affected DSA-migrated module tests.
