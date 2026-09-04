# Upstream Sources

> Created by P0 on 2026-08-18. Every functional module migrated from an
> upstream repository into QuantAnalyInvest must be recorded here.

## Repositories

| Repository | Recorded commit | License | Import policy |
| --- | --- | --- | --- |
| QuantDinger | `e64e1c227bf3174e441a42143620179b286387e1` | Apache-2.0 (+ trademarks) | Full tree via `git archive` at P0 |
| daily_stock_analysis | `396d43a4c76ffa940e2b9aea7bbe8686343c694a` | MIT (screening: Apache-2.0 derived) | **No tree import.** Module-by-module in P5-P8 |

## Import log

| Date | Plan | Upstream | Source path(s) | Target path(s) | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-08-18 | P0 | QuantDinger | `/` (full tree) | `/` | `git archive e64e1c2`; baseline only, no behavior change |
| 2026-08-18 | P0 | daily_stock_analysis | — | — | Not imported; commit recorded for future P4 legacy image only |

Rules:

1. Later Plans append rows here **before** merging DSA code.
2. Each row must name the upstream commit, exact source paths, target paths,
   and any license/attribution notes.
3. DSA screening files carry Apache-2.0 headers — preserve them on migration.
