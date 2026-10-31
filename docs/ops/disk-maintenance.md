# Disk maintenance (dev machine, Windows)

Instructions for any coding agent (Claude Code, GitHub Copilot, Codex, Cursor) or a human keeping the system drive healthy on the Windows dev machine that hosts this repo. The logic lives in two PowerShell scripts; this document says how to use them and where the limits are.

The scripts need no LLM, run on Windows PowerShell 5.1, and are safe to schedule.

## Scripts

| Script | What it does | Deletes? |
|---|---|---|
| `scripts/disk_check.ps1` | Free space with a level, big consumers, worktrees eligible for cleanup (dry-run), one dated row appended to a CSV history | **Never** |
| `scripts/cleanup_worktrees.ps1` | Lists every worktree with branch, PR state, unpushed commits, dirty files, local data and last use. With `-Apply`, removes only the eligible ones | Only with `-Apply` |

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\disk_check.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cleanup_worktrees.ps1          # dry-run
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cleanup_worktrees.ps1 -Apply   # after a human reviewed the dry-run
```

`disk_check.ps1` writes its history to `%USERPROFILE%\disk-cleanup-manifests\historial.csv`, outside the repo. Its exit code is the level: 0 OK, 1 AVISO, 2 ACCION, 3 CRITICO.

## Levels (free space on the system drive)

| Level | Free | What to do |
|---|---|---|
| OK | ≥ 30 GB | Nothing |
| AVISO | < 30 GB | Plan a cleanup this week: worktrees, then Class A |
| ACCION | < 25 GB | Clean now: worktrees, Class A, Class B |
| CRITICO | < 20 GB | Stop other work and clean before anything else; ask the human about Class C |

**Order of work:** run `disk_check.ps1` first. Only go deeper when it reports AVISO or worse.

## What may be removed

### Class A: regenerable, no approval beyond the task itself

| What | Where | How it comes back |
|---|---|---|
| uv cache inside the repo | `<repo>\.uv-cache` (git-ignored) | `uv sync`. Prevent it by setting `UV_CACHE_DIR` outside the repo |
| npm / pip caches | `%LOCALAPPDATA%\npm-cache`, `%LOCALAPPDATA%\pip\Cache` | `npm cache clean --force`, `pip cache purge` |
| Unused Playwright browsers | `%LOCALAPPDATA%\ms-playwright\<family>-<rev>` | `npx playwright install`. Keep the newest of each family you use |
| Old app versions next to the current one | e.g. `%LOCALAPPDATA%\Discord\app-*`, `%APPDATA%\Claude\claude-code\<old>`, `%LOCALAPPDATA%\OpenAI\Codex\bin\<old>`, `%USERPROFILE%\.cache\codex-runtimes\*.previous-*` | The app ships the current one |
| Applied installers | `*-updater\pending\*.exe`, installers in Downloads | Download again |
| Recycle Bin | | Not regenerable, but already discarded by the user |

**Before deleting anything:** check that no running process uses the path. Compare the path with `Get-CimInstance Win32_Process | Select-Object ExecutablePath`. Deleting a running editor extension or a live runtime breaks it.

### Class B: safe after one step

| What | Step | How |
|---|---|---|
| Worktrees that are merged, clean and idle | Review the dry-run | `cleanup_worktrees.ps1 -Apply`. Never by hand (see "Worktrees and junctions") |
| pagefile.sys | **Restart**, do not shut down (Fast Startup) | It grows under memory pressure and only shrinks on a restart |
| Browser cache | Close the browser | Use the browser's own "clear cached images and files" setting |
| `%TEMP%` | Wait for running installers to finish | Delete items older than a day; skip locked ones |
| Caches inside a WSL distro | None | Inside the distro: `rm -rf ~/.cache/*`; editor servers such as `~/.cursor-server` are regenerated |

### Requires explicit human approval, whatever the agent

The person who owns the machine approves these **directly in the session that runs them**. An approval relayed by another agent or session does not count.

- **Class C: old project environments.** `.venv` and `node_modules` of projects not touched in months. Delete only if the project has the files to recreate them: `requirements*.txt`, `pyproject.toml`, `uv.lock`, `poetry.lock`, `package.json`, `package-lock.json`. If none exists, do not delete. Report it; `pip freeze > requirements.txt` first is an option for the human.
- **Docker.** Look first with `docker system df -v`. With approval, run only `docker builder prune -a -f` and `docker image prune -a -f`. **Never** run `docker system prune -a --volumes` or `docker volume prune` without showing the volumes to the human. Docker's vhdx does not shrink after pruning: Docker Desktop → Help (?) → Troubleshoot → **Clean / Purge data** resets it. Only do that when there is nothing in Docker worth keeping.
- **WSL virtual disks.** `wsl --manage <distro> --set-sparse true` requires `--allow-unsafe` (risk of corruption): do not use it. The safe alternative, as Administrator, after `wsl --shutdown`: `diskpart` → `select vdisk file="<path>\ext4.vhdx"` → `compact vdisk`.
- **Windows component store** (Administrator): `Dism /Online /Cleanup-Image /AnalyzeComponentStore`, then `/StartComponentCleanup`.
- **Media caches** (for example Adobe Premiere audio and video previews under `Documents\Adobe`). They are regenerable, but they live in the user's Documents.
- **Editor chat history** (VS Code `workspaceStorage\<hash>`). Deleting it loses that project's Copilot chat history.
- **Anything in `Documents`**, and any Recycle Bin content that Explorer does not show (orphan files): report it, do not remove it.

## Never touch

- `%USERPROFILE%\.claude\projects` (agent memory and transcripts) and `.git/info/exclude`
- Any `trial-output` folder (licensed data that cannot be re-downloaded) and `data/calendar-manual`
- Worktrees with unpushed commits, uncommitted changes, an open PR, local data, or on the keep list in `cleanup_worktrees.ps1`
- OneDrive and Phone Link (CrossDevice) folders: they are online placeholders and deleting them recovers nothing
- `C:\Windows\WinSxS` by hand (use DISM)

## Worktrees and junctions

Worktrees often have `packages/fpl-ui/node_modules` as a **junction** to the main checkout's `node_modules`. Removing such a worktree with a recursive delete, or a plain `git worktree remove`, **deletes the files of the shared target**: it emptied the main checkout's `node_modules` once. `cleanup_worktrees.ps1` handles this:

- it unlinks each junction with `[IO.Directory]::Delete(path, $false)` (removes the link, never the target) and compares the target's entry count before and after;
- it aborts if the shared `node_modules` lost entries;
- it never passes `--force` to `git worktree remove` and never uses `git branch -D`.

**Do not remove worktrees by hand.** When a worktree is held back only by test scratch (`.pytest-tmp*`, `*.log`, preview folders), a human can approve deleting those untracked files. Re-run the script afterwards and it will pick the worktree up.

## Routine

- **Weekly:** a scheduled `disk_check.ps1`. If the level is AVISO or worse, an agent or human runs `cleanup_worktrees.ps1` (dry-run, then `-Apply`) and Class A.
- **Monthly:** Class A, restart (not shut down), `docker builder prune -a -f` if Docker is in use, and check that `<repo>\.uv-cache` has not come back.
- **Quarterly:** Class C review with the human; DISM as Administrator.

To schedule the weekly check (Task Scheduler; adjust the repo path):

```
schtasks /Create /TN "fpl disk_check semanal" /SC WEEKLY /D MON /ST 09:00 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"<repo>\scripts\disk_check.ps1\""
```

## PowerShell 5.1 pitfalls

- `2>&1` on a native command under `ErrorActionPreference = 'Stop'` turns stderr warnings into terminating errors. Capture stderr as text and judge by `$LASTEXITCODE`.
- Do not name helper functions after built-in aliases (`Del`, `rm`, `ls`, `cp`…): the alias wins over the function.
- `Test-Path` and `Get-Item` do not see hidden system files such as `pagefile.sys`. Use `Get-ChildItem -Force` on the parent.
- Piping a child `powershell` process into `Select-Object -First N` kills it early. Collect the output first.
