@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first. No Docker is required.
  exit /b 1
)
".venv\Scripts\python.exe" -m mirage run %*
