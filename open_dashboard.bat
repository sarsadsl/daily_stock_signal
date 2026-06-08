@echo off
setlocal

set "ROOT=%~dp0"
set "URL=http://localhost:8766/signal_dashboard.html"
set "API=http://127.0.0.1:8766/api/status"

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

call :check_server
if errorlevel 1 (
    echo Dashboard server is not running. Starting it now...
    call :start_server
    call :wait_for_server
    if errorlevel 1 (
        echo Failed to start dashboard server. Check logs\dashboard_server.err.log.
        pause
        endlocal
        exit /b 1
    )
) else (
    echo Dashboard server is already running.
)

echo Opening %URL%
start "" "%URL%"
endlocal
exit /b 0

:check_server
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri '%API%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { exit 0 }; exit 1 } catch { exit 1 }"
exit /b %errorlevel%

:start_server
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start_dashboard_server.ps1"
exit /b %errorlevel%

:wait_for_server
for /l %%i in (1,1,20) do (
    call :check_server
    if not errorlevel 1 (
        echo Dashboard server is ready.
        exit /b 0
    )
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1"
)
echo Dashboard server did not respond within 20 seconds. Please check logs\dashboard_server.err.log.
exit /b 1
