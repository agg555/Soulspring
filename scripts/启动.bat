@echo off
rem Soulspring local launcher (F16): venv -> deps -> frontend build (first run) -> serve -> open browser
setlocal
cd /d "%~dp0.."

set PORT=8600
set URL=http://127.0.0.1:%PORT%

if not exist "backend\.venv\Scripts\python.exe" (
  echo [Soulspring] First run: creating Python venv ...
  python -m venv backend\.venv || goto :fail
)

set PY=backend\.venv\Scripts\python.exe
echo [Soulspring] Installing backend dependencies ...
"%PY%" -m pip install -q -r backend\requirements.txt || goto :fail

if not exist "frontend\dist\index.html" (
  echo [Soulspring] First run: building frontend ^(needs Node.js^) ...
  pushd frontend
  call npm install --no-fund --no-audit
  if errorlevel 1 (popd & goto :fail)
  call npm run build
  if errorlevel 1 (popd & goto :fail)
  popd
)

echo [Soulspring] Starting server at %URL% ...
start "" cmd /c "timeout /t 3 >nul & start %URL%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --app-dir backend
goto :eof

:fail
echo.
echo [Soulspring] Startup FAILED. Read the messages above.
pause
