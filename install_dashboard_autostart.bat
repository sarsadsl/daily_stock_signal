@echo off
setlocal

set "ROOT=%~dp0"
set "TARGET=%ROOT%open_dashboard.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup = [Environment]::GetFolderPath('Startup'); $shortcut = Join-Path $startup 'Signal Dashboard.lnk'; $shell = New-Object -ComObject WScript.Shell; $link = $shell.CreateShortcut($shortcut); $link.TargetPath = '%TARGET%'; $link.WorkingDirectory = '%ROOT%'; $link.WindowStyle = 7; $link.Description = 'Open stock signal dashboard'; $link.Save(); Write-Host ('Startup shortcut created: ' + $shortcut)"

echo.
echo Done. Signal Dashboard will open automatically when you sign in to Windows.
pause
