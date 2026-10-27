param([string]$SkillsRoot)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SkillsRoot) {
    $SkillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
}
$source = Join-Path $projectRoot 'skills\occ-draw'
$target = Join-Path $SkillsRoot 'occ-draw'
# Copy only files owned by this skill; preserve any other user-added resources.
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'SKILL.md') -Destination $target -Force
foreach ($folder in @('agents', 'references', 'scripts')) {
    Copy-Item -LiteralPath (Join-Path $source $folder) -Destination $target -Recurse -Force
}
@{project_root = $projectRoot} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'location.json') -Encoding UTF8
Write-Output "Installed skill: $target"
