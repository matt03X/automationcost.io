#requires -Version 5.1
<#
.SYNOPSIS  Odstraní worktree agenta (po mergi PR).
.EXAMPLE   .\scripts\agents\wt-cleanup.ps1 content-builder zapier-hidden-cost
#>
param(
  [Parameter(Mandatory = $true)][string]$Agent,
  [Parameter(Mandatory = $true)][string]$Slug
)
$ErrorActionPreference = 'Stop'
$repo = (git rev-parse --show-toplevel).Trim()
$wt   = Join-Path (Split-Path $repo -Parent) ".worktrees/$Agent-$Slug"

git worktree remove $wt
git worktree prune
Write-Host "+ Odstranen $wt"
Write-Host "  Vetev $Agent/$Slug zustava lokalne; po mergi smaz: git branch -D $Agent/$Slug"
