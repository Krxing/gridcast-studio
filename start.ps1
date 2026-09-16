param([switch]$Install, [switch]$Hybrid, [switch]$Rebuild)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program $Arguments" }
}

if (-not (Test-Path -LiteralPath $python)) {
    if (-not $Install) { throw 'Environment missing. Install Python 3.12 and run: .\start.ps1 -Install' }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Checked 'py' @('-3.12', '-m', 'venv', '.venv')
    } else {
        Invoke-Checked 'python' @('-c', 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"')
        Invoke-Checked 'python' @('-m', 'venv', '.venv')
    }
}

if ($Install) { Invoke-Checked $python @('-m', 'pip', 'install', '-r', 'requirements.txt') }
if ($Hybrid) { Invoke-Checked $python @('-m', 'pip', 'install', 'torch==2.8.0', '--index-url', 'https://download.pytorch.org/whl/cpu') }
if ($Install -or $Rebuild -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    Push-Location -LiteralPath 'frontend'
    try {
        Invoke-Checked $npm @('ci')
        Invoke-Checked $npm @('run', 'build')
    } finally { Pop-Location }
}

Write-Host 'GridCast Studio - default address: http://127.0.0.1:8000'
Write-Host 'Create your own administrator on first launch. Press Ctrl+C to stop.'
Invoke-Checked $python @('run.py')
