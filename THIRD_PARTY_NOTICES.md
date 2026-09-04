# Third-Party Notices

This file contains license attribution for upstream projects and third-party
code whose functionality is migrated into QuantAnalyInvest.

## QuantDinger (Apache License 2.0)

- Upstream repository: QuantDinger (local source of truth; see
  `docs/BASELINE.md` for the recorded commit)
- License: Apache License 2.0 — see [LICENSE](./LICENSE)
- Imported: full repository tree at commit `e64e1c2`, via `git archive`
- Trademark notice: see [TRADEMARKS.md](./TRADEMARKS.md)
- Attribution requirement: retain Apache-2.0 headers and NOTICE where present

## daily_stock_analysis (MIT License)

- Upstream repository: daily_stock_analysis (local source of truth; see
  `docs/BASELINE.md` for the recorded commit)
- License: MIT — Copyright (c) 2026 ZhuLinsen
- Imported: **not imported as a source tree**. Only selected functional
  modules are migrated Plan-by-Plan (P5-P8) into this repository. Each module
  records its source commit and path in `UPSTREAM_SOURCES.md`.
- MIT license text is reproduced below.

```
MIT License

Copyright (c) 2026 ZhuLinsen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## daily_stock_analysis screening (Apache-2.0 derived)

`src/services/screening/` in daily_stock_analysis contains files marked
"Licensed under Apache-2.0 and modified for daily_stock_analysis" and an
`Apache License 2.0` LICENSE file in that directory. When any screening
functionality is migrated (later Plans), the Apache-2.0 attribution and
modification notices must be preserved in the migrated files, and the source
commit recorded in `UPSTREAM_SOURCES.md`.

## Frontend (pending)

The QuantDinger frontend lives in a separate repository and is **not** part of
this baseline. Before any frontend source is imported (P17), a separate license
review is required; the Apache-2.0 conclusion above must not be assumed to
apply to it.
