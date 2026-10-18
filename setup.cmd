@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.lock
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --no-deps -e .
if errorlevel 1 exit /b 1
cd /d "%~dp0apps\dashboard"
call npm.cmd ci --no-fund --no-audit
if errorlevel 1 exit /b 1
call npm.cmd run build
if errorlevel 1 exit /b 1
cd /d "%~dp0"
".venv\Scripts\python.exe" -m mirage migrate
if errorlevel 1 exit /b 1
echo.
echo Setup complete. Run start.cmd to open the native laboratory.
