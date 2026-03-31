@echo off
setlocal

if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=0.0.0.0

if exist "%~dp0\.venv\Scripts\activate.bat" (
  call "%~dp0\.venv\Scripts\activate.bat"
)

python -m uvicorn app.main:app --reload --host %HOST% --port %PORT%

