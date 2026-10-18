@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m ruff check mirage tests tools\evaluation.py tools\export_schema.py tools\review_foundations.py tools\check_secrets.py tools\audit_dependencies.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m ruff format --check mirage tests tools\evaluation.py tools\export_schema.py tools\review_foundations.py tools\check_secrets.py tools\audit_dependencies.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\check_secrets.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\validate_blueprint.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pytest -q --junitxml=.local\backend-tests.xml
if errorlevel 1 exit /b 1
cd /d "%~dp0apps\dashboard"
call npm.cmd run lint
if errorlevel 1 exit /b 1
call npm.cmd run format:check
if errorlevel 1 exit /b 1
call npm.cmd run build
if errorlevel 1 exit /b 1
call npm.cmd run test:e2e
if errorlevel 1 exit /b 1
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\evaluation.py
if errorlevel 1 exit /b 1
echo P1-native gates completed. Explicit P2/P3/provider/PostgreSQL skips remain release limitations.
