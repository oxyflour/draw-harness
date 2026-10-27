# Entrypoint preserving the caller's working directory (and workspace memory).
$ErrorActionPreference = 'Stop'
$runtime = $env:OCC_HARNESS_PYTHON
if (-not $runtime) {
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike '*WindowsApps*') { $runtime = $candidate.Source }
}
if (-not $runtime) {
    $runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $runtime)) { throw 'Python 3.10+ required; set OCC_HARNESS_PYTHON' }
$previousPath = $env:PYTHONPATH
$previousConsoleOutput = [Console]::OutputEncoding
$previousConsoleInput = [Console]::InputEncoding
$previousPipelineEncoding = $OutputEncoding
try {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $env:PYTHONPATH = if ($previousPath) { "$PSScriptRoot;$previousPath" } else { $PSScriptRoot }
    & $runtime -m occ_harness @args
    $harnessExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPath
    [Console]::OutputEncoding = $previousConsoleOutput
    [Console]::InputEncoding = $previousConsoleInput
    $OutputEncoding = $previousPipelineEncoding
}
exit $harnessExitCode
