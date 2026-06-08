param(
    [string]$Root = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

$pythonCandidates = @(
    "C:\Users\a1430\AppData\Local\Programs\Python\Python314\python.exe"
)

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonCandidates += $pythonCommand.Source
}

$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) {
    throw "Python executable was not found."
}

$rootPath = (Resolve-Path -LiteralPath $Root).Path
$serverPath = Join-Path $rootPath "dashboard_server.py"
if (-not (Test-Path -LiteralPath $serverPath)) {
    throw "dashboard_server.py was not found in $rootPath."
}

$logDir = Join-Path $rootPath "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$outLog = Join-Path $logDir "dashboard_server.out.log"
$errLog = Join-Path $logDir "dashboard_server.err.log"
$cmd = "`"$pythonExe`" `"$serverPath`" >> `"$outLog`" 2>> `"$errLog`""

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $env:ComSpec
$psi.Arguments = "/c `"$cmd`""
$psi.WorkingDirectory = $rootPath
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$psi.UseShellExecute = $true

[System.Diagnostics.Process]::Start($psi) | Out-Null
