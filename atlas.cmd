@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo Atlas cannot find its project Python environment at .venv\Scripts\python.exe.
  echo Create the virtual environment first, then run this command again.
  exit /b 1
)

if /I "%~1"=="setup" (
  "%PYTHON%" "%ROOT%backend\scripts\setup.py"
  exit /b %ERRORLEVEL%
)

if /I "%~1"=="doctor" (
  "%PYTHON%" "%ROOT%backend\scripts\doctor.py"
  exit /b %ERRORLEVEL%
)

echo Atlas command helper
echo.
echo   .\atlas setup    First-time setup or change storage.
echo   .\atlas doctor   Check what is ready and what needs attention.
echo.
echo For normal daily use, start the database dependency if needed, then open a fresh Codex task. No Atlas command is required.
exit /b 0
