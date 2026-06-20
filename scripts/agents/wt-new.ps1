#requires -Version 5.1
<#
.SYNOPSIS  Vytvoří čistý git worktree off origin/master pro úkol agenta.
.EXAMPLE   .\scripts\agents\wt-new.ps1 content-builder zapier-hidden-cost
Spouštěj z kořene repa v PowerShell terminálu. git push pak taky přes PowerShell (Bash TLS rozbité).
#>
param(
  [Parameter(Mandatory = $true)][string]$Agent,
  [Parameter(Mandatory = $true)][string]$Slug
)
$ErrorActionPreference = 'Stop'
$repo   = (git rev-parse --show-toplevel).Trim()
$branch = "$Agent/$Slug"
$wt     = Join-Path (Split-Path $repo -Parent) ".worktrees/$Agent-$Slug"

git fetch origin --quiet
git worktree add $wt -b $branch origin/master
if ($LASTEXITCODE -ne 0) { throw "worktree add selhal (existuje už větev $branch? zvol jiný slug)" }

Write-Host "+ Worktree: $wt"
Write-Host "+ Branch:   $branch  (off origin/master)"
Write-Host "  Dal: cd `"$wt`"  ->  edit  ->  python automation/build.py --check  ->  commit JEN explicitnich souboru  ->  git push -u origin $branch  ->  gh pr create"
