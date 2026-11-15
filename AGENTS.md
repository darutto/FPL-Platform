# Agent instructions

## Disk maintenance

For disk space checks or cleanup on the Windows dev machine, follow [docs/ops/disk-maintenance.md](docs/ops/disk-maintenance.md).

- Start with `scripts/disk_check.ps1`, which is read-only. Go deeper only when it reports AVISO or worse.
- Remove worktrees only through `scripts/cleanup_worktrees.ps1`: dry-run first, then `-Apply`. Never by hand: worktrees may hold `node_modules` junctions.
- Class C (old project environments), Docker, WSL disks, DISM and media caches need the human's direct approval in the session that runs them.
