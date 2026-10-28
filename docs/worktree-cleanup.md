# Worktree cleanup rule

**Every week, right after merging, clean finished worktrees.** Each worktree
carries its own node_modules/venv (0.4-0.6 GB); dozens of stale ones filled
the C: drive and made `npm ci` fail halfway.

```powershell
pwsh scripts/cleanup_worktrees.ps1           # dry-run: table + what it would delete
pwsh scripts/cleanup_worktrees.ps1 -Apply    # apply (also accepts --apply)
```

A worktree is deleted only if its PR is merged, the branch has no unpushed
commits, the tree is clean, it holds no local data, and it was not touched in
the last 24 h (live sessions). Kept always: the keep list (`wt-pressure-harvest`,
`wt-fi9-live`: Sportmonks trial output that cannot be re-downloaded), anything
with `trial-output`, `*.parquet`, `*.pkl` or large `*.csv`, detached HEADs and
branches that were never pushed. Add paths with `-KeepPath` or `-KeepFile`.

## Safety rules (do not bypass)

- Junctions (e.g. a worktree `node_modules` pointing at another checkout) are
  removed first with `cmd /c rmdir`. Recursive delete through a junction deletes
  the target's files (this emptied the shared `fpl-ui` node_modules once).
- `git worktree remove` is never forced; if it refuses, the worktree stays
  pending with the reason. `git branch -d`, never `-D`.
- The script aborts if the entry count of `packages/fpl-ui/node_modules`
  drops during a run.
- Not scheduled automatically; run it by hand.
