---
mode: agent
description: Check disk space on the Windows dev machine and propose a cleanup by class
---

Follow [docs/ops/disk-maintenance.md](../../docs/ops/disk-maintenance.md).

1. Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\disk_check.ps1`, then report the level, the free GB and the biggest consumers.
2. If the level is OK, stop there.
3. Otherwise, propose a cleanup grouped by class (A, B, approval-required). For each item give the path, GB, how it regenerates and the exact command.
4. Delete nothing until the user approves each class in this chat. Worktrees go only through `scripts\cleanup_worktrees.ps1` (dry-run first).
5. Afterwards, run `disk_check.ps1` again and report the before and after free GB.
