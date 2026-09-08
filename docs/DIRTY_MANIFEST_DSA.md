# daily_stock_analysis dirty manifest

repo: daily_stock_analysis
recorded_commit: 396d43a4c76ffa940e2b9aea7bbe8686343c694a
head_commit: 396d43a4c76ffa940e2b9aea7bbe8686343c694a
head_drift: none
checked_at: 2026-09-02T03:20:00Z
observation_environment: WSL2 (Linux 6.6.87.2-microsoft-standard-x86_64), ext4-backed filesystem
core.filemode: file:.git/config true

## Raw view (core.filemode=true)

```text
(empty — no entries)
```

## Content-oriented view (core.filemode=false)

```text
(empty — no entries)
```

## CLAUDE.md status (resolved this round)

Previous 2026-08-31 Windows snapshot reported `M CLAUDE.md` with content
status **indeterminate** (`Function not implemented` on hash-object). This
round, observed from WSL2:

- `CLAUDE.md` is a **symlink** (git mode `120000`, blob
  `47dc3e3d863cfb5727b87d785d09abf9743c0a72`) whose target is `AGENTS.md`.
- The symlink resolves and its target is readable;
  `git hash-object CLAUDE.md` now succeeds
  (`6c90718d4aec85e4763f009ce46dc4f654cd16e2` computed over the dereferenced
  file this round; the committed link blob itself is unchanged).
- `git status` reports **no modification** in either raw or
  content-oriented view.

Conclusion: the earlier `M CLAUDE.md` was a Windows/drvfs symlink-metadata
artifact, not a content change. Content status is now **verified clean**
from a POSIX filesystem view; the indeterminate note in the 2026-08-31
snapshot is superseded (kept below as historical evidence).

## Conclusion

**Clean.** HEAD matches the recorded commit; porcelain is empty in both
views; the previously indeterminate `CLAUDE.md` is a committed symlink to
`AGENTS.md` and shows no content drift from WSL2. No upstream file was
modified, cleaned, staged, or committed while producing this snapshot.

---

## Historical snapshot 2026-08-31T08:42:36Z (Windows 11 PowerShell)

Raw view reported 7 mode-only script changes plus `M CLAUDE.md`; CLAUDE.md
bytes were unreadable (`Function not implemented`), so its content status
was recorded as **indeterminate**. That snapshot was an observation of the
Windows/drvfs view only and is superseded by the 2026-09-02 WSL2 snapshot
above. No action was taken against the upstream worktree in either round.
