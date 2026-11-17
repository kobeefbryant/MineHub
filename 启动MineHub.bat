@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo MineHub: .venv\Scripts\pythonw.exe not found.
  echo Run the project setup first.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m mh.desktop
set /a tries=0

:wait
"%SystemRoot%\System32\curl.exe" -fsS --noproxy "*" --max-time 1 "http://127.0.0.1:9999/mh/api/health" >nul 2>nul
if not errorlevel 1 goto open
set /a tries+=1
if %tries% GEQ 60 goto timeout
"%SystemRoot%\System32\PING.EXE" -n 2 127.0.0.1 >nul
goto wait

:open
start "" "http://127.0.0.1:9999/mh"
exit /b 0

:timeout
echo MineHub did not become ready within 60 seconds.
echo Check data\logs\desktop.log, data\logs\gateway.log and data\logs\stash_stdout.log.
pause
exit /b 1
