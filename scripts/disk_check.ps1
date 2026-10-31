<#
.SYNOPSIS
  Read-only disk health check for the dev machine. Deletes nothing.

.DESCRIPTION
  Reports free space on the system drive, the size of the usual big consumers
  (pagefile, Docker and WSL virtual disks, package and tool caches) and the
  worktrees that scripts/cleanup_worktrees.ps1 would remove (its dry-run).
  Compares free space with a baseline and prints a level:

    OK        free >= WarnGB
    AVISO     free <  WarnGB      (plan a cleanup this week)
    ACCION    free <  ActionGB    (run the cleanup now)
    CRITICO   free <  CriticalGB  (stop and clean before anything else)

  Appends one dated line to a CSV history file, so trends are visible.
  Works on Windows PowerShell 5.1 and pwsh 7.

.PARAMETER HistoryFile
  CSV to append to. Defaults to %USERPROFILE%\disk-cleanup-manifests\historial.csv.

.PARAMETER BaselineFreeGB
  Free GB to compare against. Defaults to the free_gb of the first row of the
  history file; with no history, no delta is printed.

.PARAMETER SkipWorktrees
  Do not run the cleanup_worktrees.ps1 dry-run (it fetches and calls gh).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\disk_check.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\disk_check.ps1 -BaselineFreeGB 37.6
#>
[CmdletBinding()]
param(
  [string]$HistoryFile = (Join-Path $env:USERPROFILE 'disk-cleanup-manifests\historial.csv'),
  [double]$BaselineFreeGB = 0,
  [double]$WarnGB = 30,
  [double]$ActionGB = 25,
  [double]$CriticalGB = 20,
  [switch]$SkipWorktrees
)

$ErrorActionPreference = 'Continue'
$drive = $env:SystemDrive.TrimEnd(':')
$repo = Split-Path $PSScriptRoot -Parent

# Sum of file sizes under a path; links are not followed (placeholders and
# junction targets would be counted twice otherwise). -1 when absent.
function Get-SizeGB([string]$path) {
  if (-not $path -or -not (Test-Path -LiteralPath $path)) { return -1 }
  $item = Get-Item -LiteralPath $path -Force
  if (-not $item.PSIsContainer) { return [math]::Round($item.Length / 1GB, 2) }
  $sum = (Get-ChildItem -LiteralPath $path -Recurse -File -Force -Attributes !ReparsePoint -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum
  [math]::Round([double]$sum / 1GB, 2)
}

# Hidden system files (pagefile.sys, hiberfil.sys) are invisible to Test-Path
# and Get-Item on Windows PowerShell 5.1; list the parent with -Force instead.
function Get-SystemFileGB([string]$name) {
  $f = Get-ChildItem "$($env:SystemDrive)\" -Force -File -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($f) { [math]::Round($f.Length / 1GB, 2) } else { -1 }
}

function Get-FirstExisting([string[]]$paths) {
  foreach ($p in $paths) { if ($p -and (Test-Path -LiteralPath $p)) { return $p } }
  $null
}

$free = [math]::Round((Get-PSDrive $drive).Free / 1GB, 2)
$used = [math]::Round((Get-PSDrive $drive).Used / 1GB, 2)

# Big single files
$pagefile = Get-SystemFileGB 'pagefile.sys'
$hiberfil = Get-SystemFileGB 'hiberfil.sys'
$docker = Get-SizeGB (Get-FirstExisting @(
    "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx",
    "$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx"))
$wslDisks = @(Get-ChildItem "$env:LOCALAPPDATA\wsl" -Recurse -Filter '*.vhdx' -Force -ErrorAction SilentlyContinue) +
  @(Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter '*Ubuntu*' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem (Join-Path $_.FullName 'LocalState') -Filter '*.vhdx' -Force -ErrorAction SilentlyContinue })
$wsl = [math]::Round(([double]($wslDisks | Measure-Object Length -Sum).Sum) / 1GB, 2)

# Caches that regrow on their own (all regenerable)
$caches = [ordered]@{
  'uv (repo .uv-cache)'    = Join-Path $repo '.uv-cache'
  'uv (user cache)'        = "$env:LOCALAPPDATA\uv\cache"
  'npm cache'              = "$env:LOCALAPPDATA\npm-cache"
  'pip cache'              = "$env:LOCALAPPDATA\pip\Cache"
  'Playwright browsers'    = "$env:LOCALAPPDATA\ms-playwright"
  'Codex runtimes'         = "$env:USERPROFILE\.cache\codex-runtimes"
  'VS Code workspaceStorage' = "$env:APPDATA\Code\User\workspaceStorage"
  'Edge cache'             = "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache"
  'OneDrive ListSync'      = "$env:LOCALAPPDATA\Microsoft\OneDrive\ListSync"
  'Temp'                   = $env:TEMP
}
$cacheRows = foreach ($k in $caches.Keys) {
  [pscustomobject]@{ Item = $k; GB = (Get-SizeGB $caches[$k]) }
}
$cacheTotal = [math]::Round((($cacheRows | Where-Object GB -ge 0 | Measure-Object GB -Sum).Sum), 2)
$recycle = Get-SizeGB "$($env:SystemDrive)\`$Recycle.Bin"

# Worktrees the cleanup script would remove (dry-run only, never -Apply)
$wtCount = ''; $wtGB = ''; $wtLines = @()
$cleanup = Join-Path $PSScriptRoot 'cleanup_worktrees.ps1'
if (-not $SkipWorktrees -and (Test-Path $cleanup)) {
  # cleanup_worktrees.ps1 finds the repo from the current directory; a
  # scheduled task starts in System32
  Push-Location $repo
  try { $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $cleanup 2>&1 | ForEach-Object { "$_" } }
  finally { Pop-Location }
  $wtLines = @($out | Where-Object { $_ -match '^DELETE ' })
  $sum = $out | Where-Object { $_ -match 'Would delete (\d+) worktrees \(~([\d.]*) GB\)' } | Select-Object -Last 1
  if ($sum -match 'Would delete (\d+) worktrees \(~([\d.]*) GB\)') { $wtCount = $Matches[1]; $wtGB = $Matches[2] }
}

# Baseline: explicit, else first row of the history
if ($BaselineFreeGB -le 0 -and (Test-Path $HistoryFile)) {
  $first = Import-Csv $HistoryFile | Select-Object -First 1
  if ($first) { $BaselineFreeGB = [double]$first.free_gb }
}
$delta = if ($BaselineFreeGB -gt 0) { [math]::Round($free - $BaselineFreeGB, 2) } else { $null }

$level = if ($free -lt $CriticalGB) { 'CRITICO' }
  elseif ($free -lt $ActionGB) { 'ACCION' }
  elseif ($free -lt $WarnGB) { 'AVISO' }
  else { 'OK' }

# Report
Write-Host ''
Write-Host ("{0}: {1:N2} GB libres / {2:N2} GB usados  ->  {3}" -f $drive, $free, $used, $level)
if ($null -ne $delta) { Write-Host ("Base {0:N2} GB libres; diferencia {1:+0.00;-0.00;0.00} GB" -f $BaselineFreeGB, $delta) }
Write-Host ("Umbrales: aviso < {0} | accion < {1} | critico < {2}" -f $WarnGB, $ActionGB, $CriticalGB)
Write-Host ''
Write-Host 'Grandes consumidores (GB, -1 = no existe):'
Write-Host ("  pagefile.sys        {0,6}   (solo baja reiniciando)" -f $pagefile)
Write-Host ("  hiberfil.sys        {0,6}" -f $hiberfil)
Write-Host ("  Docker vhdx         {0,6}" -f $docker)
Write-Host ("  WSL vhdx (total)    {0,6}" -f $wsl)
Write-Host ("  Papelera            {0,6}" -f $recycle)
foreach ($r in $cacheRows) { Write-Host ("  {0,-24} {1,6}" -f $r.Item, $r.GB) }
Write-Host ("  caches total        {0,6}" -f $cacheTotal)
Write-Host ''
if ($SkipWorktrees) { Write-Host 'Worktrees: omitido (-SkipWorktrees)' }
else {
  Write-Host ("Worktrees elegibles (dry-run de cleanup_worktrees.ps1): {0} (~{1} GB)" -f $wtCount, $wtGB)
  foreach ($l in $wtLines) { Write-Host "  $($l.Trim())" }
}

# History
$dir = Split-Path $HistoryFile -Parent
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory $dir | Out-Null }
$row = [pscustomobject]@{
  fecha = (Get-Date).ToString('yyyy-MM-dd HH:mm'); free_gb = $free; used_gb = $used; nivel = $level
  delta_vs_base = $delta; pagefile_gb = $pagefile; docker_vhdx_gb = $docker; wsl_vhdx_gb = $wsl
  caches_gb = $cacheTotal; papelera_gb = $recycle; worktrees_elegibles = $wtCount; worktrees_gb = $wtGB
}
$row | Export-Csv $HistoryFile -Append -NoTypeInformation -Encoding UTF8
Write-Host ''
Write-Host "Historial: $HistoryFile"

# Exit code lets a scheduler or caller react: 0 OK, 1 aviso, 2 accion, 3 critico
exit @{ OK = 0; AVISO = 1; ACCION = 2; CRITICO = 3 }[$level]
