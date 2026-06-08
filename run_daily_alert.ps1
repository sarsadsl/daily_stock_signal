$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Workspace

$PythonCandidates = @(
    "python",
    "py",
    "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

$Python = $null
foreach ($Candidate in $PythonCandidates) {
    $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($Command) {
        $Python = $Command.Source
        break
    }
    if (Test-Path -LiteralPath $Candidate) {
        $Python = $Candidate
        break
    }
}

if (-not $Python) {
    throw "找不到 Python。請安裝 Python，或確認 Codex runtime Python 仍存在。"
}

& $Python alert_signals.py
