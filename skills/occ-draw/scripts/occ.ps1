$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path -Parent $PSScriptRoot
$location = Join-Path $skillRoot 'location.json'
if (Test-Path -LiteralPath $location) {
    $projectRoot = (Get-Content -LiteralPath $location -Raw | ConvertFrom-Json).project_root
} else {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $skillRoot '..\..'))
}
$entrypoint = Join-Path $projectRoot 'occ-harness.ps1'
if (-not (Test-Path -LiteralPath $entrypoint)) { throw 'Harness moved; run scripts/install-skill.ps1 from the harness project again' }
& $entrypoint @args
exit $LASTEXITCODE
