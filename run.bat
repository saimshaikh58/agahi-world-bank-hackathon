@echo off
REM agahi_hackathon: one-command start for Windows.
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -c "import fastapi, uvicorn, sklearn, pandas, rapidfuzz, httpx, PIL, jinja2, multipart, docx" >nul 2>nul
if errorlevel 1 (
  echo Installing requirements, first time only...
  python -m pip install --upgrade pip >nul
  python -m pip install -r requirements-train.txt
)
if not exist ".env" copy ".env.example" ".env" >nul
python scripts\first_run.py
set "PORT=8000"
for /f "tokens=2 delims==" %%a in ('findstr /b "PORT=" .env') do set "PORT=%%a"
python -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', %PORT%))==0 else 1)"
if not errorlevel 1 (
  echo Port %PORT% is busy, using 8001
  set "PORT=8001"
)
set "PW=agahi-admin"
for /f "tokens=2 delims==" %%a in ('findstr /b "ADMIN_PASSWORD=" .env') do set "PW=%%a"
echo.
echo   Chat:  http://localhost:%PORT%/   Admin: http://localhost:%PORT%/admin   Password: %PW%
echo   Change ADMIN_PASSWORD in .env before sharing. Press Ctrl+C to stop.
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
