<#
.SYNOPSIS
  Weekly cleanup of finished git worktrees. DRY-RUN by default.

.DESCRIPTION
  Lists every worktree with branch, PR state, unpushed commits, uncommitted
  files, local-data folders, size and last use, and says what it would delete.
  Nothing is touched unless -Apply (or --apply) is passed.

  A worktree is deletable only when ALL hold:
    - not the main checkout and not in the keep list
    - has a branch, and that branch's PR is MERGED (gh) or the branch is an
      ancestor of origin/main
    - 0 commits ahead of its remote branch (never unpushed work)
    - no uncommitted or untracked-not-ignored files
    - no local-data folders (trial-output, *.parquet, *.pkl, *.csv > 1 MB)
    - not touched in the last -MinIdleHours (default 24; protects live sessions)

  Safeguards when applying: junctions/reparse points are unlinked first with
  [IO.Directory]::Delete (non-recursive: removes the link, never the target),
  and the target's entry count is compared before and after each unlink; the
  run aborts if a target lost entries. The shared packages/fpl-ui/node_modules
  entry count is checked after every removal and the run aborts if it dropped.
  `git worktree remove` is NEVER forced, and `git branch -d` is never `-D`.
  A refusal leaves the worktree as pending and the run goes on to the next.

  Works on Windows PowerShell 5.1 and pwsh 7: git's stderr (warnings such as
  "deleting branch ... not yet merged to HEAD") is captured as text and only
  the exit code decides success.

.PARAMETER Apply
  Actually delete. Also accepted as --apply.

.PARAMETER KeepPath
  Extra paths to always keep (added to the built-in list).

.PARAMETER KeepFile
  Optional text file with one path per line to always keep.

.PARAMETER MinIdleHours
  A worktree touched more recently than this is kept as "active".

.EXAMPLE
  powershell -File scripts/cleanup_worktrees.ps1            # dry-run table
  powershell -File scripts/cleanup_worktrees.ps1 -Apply     # delete what the table said
#>
[CmdletBinding()]
param(
  [switch]$Apply,
  [string[]]$KeepPath = @(),
  [string]$KeepFile = '',
  [int]$MinIdleHours = 24,
  [Parameter(ValueFromRemainingArguments = $true)]$Rest
)

$ErrorActionPreference = 'Stop'
if ($Rest -contains '--apply') { $Apply = $true }

# Run git without letting stderr become a terminating error. On Windows
# PowerShell 5.1, `2>&1` on a native command wraps each stderr line in an
# ErrorRecord, which throws under ErrorActionPreference=Stop even when git
# exits 0. Returns the combined output as text; check $LASTEXITCODE after.
function Invoke-Git {
  $eap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { $out = & git @args 2>&1 | ForEach-Object { "$_" } }
  finally { $ErrorActionPreference = $eap }
  ($out -join "`n").Trim()
}

$repo = (git rev-parse --show-toplevel).Trim() -replace '/', '\'
Set-Location $repo
# first entry of the worktree list is always the main checkout
$mainPath = ((git worktree list --porcelain | Select-Object -First 1).Substring(9)) -replace '/', '\'

# Trial data that cannot be re-downloaded: never delete, whatever the table says.
$builtinKeep = @(
  'C:\Users\thera\wt-pressure-harvest',
  'C:\Users\thera\wt-fi9-live',
  'C:\Users\thera\fpl-platform\.worktrees\hist-sm',
  'C:\Users\thera\fpl-platform\.worktrees\hist-bt',
  'C:\Users\thera\fpl-platform\.worktrees\ab-run'
)
$keep = @($builtinKeep + $KeepPath)
if ($KeepFile -and (Test-Path $KeepFile)) {
  $keep += Get-Content $KeepFile | Where-Object { $_.Trim() -and -not $_.StartsWith('#') }
}
$keep = $keep | ForEach-Object { ($_ -replace '/', '\').TrimEnd('\').ToLowerInvariant() }

$uiNm = Join-Path $repo 'packages\fpl-ui\node_modules'
function Get-UiCount { if (Test-Path $uiNm) { (Get-ChildItem $uiNm -Force | Measure-Object).Count } else { 0 } }

$fo = Invoke-Git fetch origin --quiet
if ($LASTEXITCODE -ne 0) { Write-Warning "git fetch failed, using cached origin refs: $fo" }
$prs = @{}
try {
  # parentheses unroll the array on Windows PowerShell 5.1
  (gh pr list --state all --limit 500 --json headRefName,state | ConvertFrom-Json) | ForEach-Object {
    if (-not $prs.ContainsKey($_.headRefName) -or $_.state -eq 'MERGED') { $prs[$_.headRefName] = $_.state }
  }
} catch { Write-Warning 'gh unavailable: PR state unknown, only ancestor-of-origin/main counts as merged' }

# Parse worktrees
$wts = @(); $cur = $null
foreach ($l in (git worktree list --porcelain)) {
  if ($l -like 'worktree *') { if ($cur) { $wts += $cur }; $cur = @{ path = ($l.Substring(9) -replace '/', '\'); branch = '' } }
  elseif ($l -like 'branch *') { $cur.branch = $l.Substring(7) -replace '^refs/heads/', '' }
}
if ($cur) { $wts += $cur }

function Find-Reparse([string]$p) {
  $found = @(Get-ChildItem $p -Recurse -Depth 3 -Attributes ReparsePoint -Force -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -notmatch '\\node_modules\\.+\\node_modules' } | Sort-Object { $_.FullName.Length })
  # outermost links only: anything below a link lives in its target, not in this worktree
  $outer = @()
  foreach ($f in $found) {
    if (-not ($outer | Where-Object { $f.FullName.StartsWith($_.FullName + '\', [StringComparison]::OrdinalIgnoreCase) })) { $outer += $f }
  }
  $outer
}

$rows = foreach ($w in $wts) {
  $p = $w.path; $b = $w.branch
  if ($p.ToLowerInvariant() -eq $mainPath.ToLowerInvariant()) { continue }
  if ($p.ToLowerInvariant() -eq $repo.ToLowerInvariant()) { continue }  # the worktree running this script
  if (-not (Test-Path $p)) { Write-Warning "missing on disk (run git worktree prune): $p"; continue }
  $reasons = @()
  if ($keep -contains $p.ToLowerInvariant()) { $reasons += 'keep-list' }
  if (-not $b) { $reasons += 'detached/no branch' }
  $pr = if ($b) { $prs[$b] } else { $null }
  $anc = $false
  if ($b) { $null = Invoke-Git merge-base --is-ancestor $b origin/main; $anc = ($LASTEXITCODE -eq 0) }
  if ($b -and $pr -ne 'MERGED' -and -not $anc) { $reasons += "PR not merged ($(if ($pr) { $pr } else { 'none' }))" }
  $hasRemote = $false
  if ($b) { $null = Invoke-Git rev-parse --verify --quiet "refs/remotes/origin/$b"; $hasRemote = ($LASTEXITCODE -eq 0) }
  $ahead = if ($b) { if ($hasRemote) { [int](git rev-list --count "origin/$b..$b") } else { [int](git rev-list --count "origin/main..$b") } } else { 0 }
  if ($b -and -not $hasRemote -and -not $anc) { $reasons += 'branch not on origin' }
  if ($ahead -gt 0 -and -not $anc) { $reasons += "$ahead unpushed commits" }
  $dirty = @(git -C $p status --porcelain).Count
  if ($dirty -gt 0) { $reasons += "$dirty uncommitted/untracked" }
  # ignored-but-present local data (fast: git already knows the ignored paths)
  $ign = @(git -C $p status --porcelain --ignored | Where-Object { $_ -like '!! *' } | ForEach-Object { $_.Substring(3) })
  $data = @($ign | Where-Object { $_ -match '(^|/)trial-output(/|$)|\.(parquet|pkl|csv|ndjson)$|(^|/)(data|captures?)/' })
  if ($data.Count -gt 0) { $reasons += "local ignored data ($($data[0]))" }
  $last = (Get-ChildItem $p -Force -ErrorAction SilentlyContinue | Measure-Object LastWriteTime -Maximum).Maximum
  if ($last -and ((Get-Date) - $last).TotalHours -lt $MinIdleHours) { $reasons += "active (<${MinIdleHours}h)" }
  # size only for deletion candidates (the recursive walk is slow)
  $sz = $null
  if ($reasons.Count -eq 0) { $sz = [math]::Round((Get-ChildItem $p -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1GB, 2) }
  [pscustomobject]@{
    Path = $p; Branch = $b; PR = $pr; Ahead = $ahead; Dirty = $dirty; GB = $sz
    LastUse = $last; Action = $(if ($reasons.Count -eq 0) { 'DELETE' } else { 'KEEP' })
    Why = ($reasons -join '; ')
  }
}

$rows | Sort-Object Action, Path | Format-Table Action, Path, Branch, PR, Ahead, Dirty, GB, LastUse, Why -AutoSize | Out-String -Width 300 | Write-Host
$del = @($rows | Where-Object Action -eq 'DELETE')
Write-Host ("Would delete {0} worktrees (~{1} GB)." -f $del.Count, (($del | Measure-Object GB -Sum).Sum))

if (-not $Apply) { Write-Host 'DRY-RUN: nothing deleted. Re-run with -Apply to proceed.'; return }

function Get-EntryCount([string]$dir) {
  if ($dir -and (Test-Path -LiteralPath $dir)) { @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue).Count } else { -1 }
}

# Unlink one reparse point without touching what it points to. Returns $true
# when the link is gone and its target kept every entry it had.
function Remove-LinkOnly($item) {
  $target = @($item.Target)[0]
  if ($target -and -not [IO.Path]::IsPathRooted($target)) { $target = Join-Path (Split-Path $item.FullName) $target }
  $before = Get-EntryCount $target
  Write-Host "  unlink $($item.FullName) -> $target ($before entries)"
  # non-recursive: on a junction or symlink this deletes the link itself only
  if ($item.PSIsContainer) { [IO.Directory]::Delete($item.FullName, $false) } else { [IO.File]::Delete($item.FullName) }
  $after = Get-EntryCount $target
  if ($after -lt $before) { throw "link target $target dropped from $before to $after entries after unlinking $($item.FullName); aborting" }
  -not (Test-Path -LiteralPath $item.FullName)
}

$baseline = Get-UiCount
Write-Host "fpl-ui/node_modules baseline entries: $baseline"
$n = 0; $pending = @()
foreach ($r in $del) {
  $p = $r.Path
  try {
    foreach ($j in (Find-Reparse $p)) {
      if (-not (Remove-LinkOnly $j)) { throw "could not unlink $($j.FullName)" }
    }
    if ((Find-Reparse $p).Count -gt 0) { throw 'reparse points remain' }
    $out = Invoke-Git worktree remove $p
    if ($LASTEXITCODE -ne 0) { throw "git worktree remove refused: $out" }
    Write-Host "REMOVED $p"
    $bo = Invoke-Git branch -d $r.Branch
    if ($LASTEXITCODE -eq 0) { Write-Host "  branch -d $($r.Branch): $bo" }
    else { Write-Warning "  branch -d $($r.Branch) refused (branch kept): $bo" }
    $n++
  } catch {
    # a failed link check is not a per-worktree refusal: stop everything
    if ("$_" -like '*dropped from*') { throw }
    Write-Warning "PENDING $p : $_"
    $pending += $p
  }
  if ((Get-UiCount) -lt $baseline) { throw "fpl-ui/node_modules entries dropped below $baseline after $n removals; aborting" }
}
$null = Invoke-Git worktree prune
Write-Host ("Done. Removed {0} of {1}; pending {2}. Free on C: {3:N1} GB" -f $n, $del.Count, $pending.Count, ((Get-PSDrive C).Free / 1GB))
foreach ($p in $pending) { Write-Host "  pending: $p" }
