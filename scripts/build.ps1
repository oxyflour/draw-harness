param(
    [string]$OcctRoot = 'C:\Programs\OpenCASCADE-7.7.0-vc14-64\opencascade-7.7.0'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$cmake = Get-Command cmake -ErrorAction SilentlyContinue
$cmakePath = if ($cmake) { $cmake.Source } else { 'C:\Program Files\CMake\bin\cmake.exe' }
if (-not (Test-Path -LiteralPath $cmakePath)) { throw 'CMake 3.20+ is required' }
& $cmakePath -S $projectRoot -B "$projectRoot\build" -G 'Visual Studio 17 2022' -A x64 "-DOCCT_ROOT=$OcctRoot"
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
& $cmakePath --build "$projectRoot\build" --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
