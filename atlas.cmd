@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if /I "%~1"=="setup" (
  if not exist "%PYTHON%" (
    echo Creating Atlas virtual environment at .venv...
    py -3.11 -m venv "%ROOT%.venv" 2>nul
    if errorlevel 1 py -m venv "%ROOT%.venv" 2>nul
    if errorlevel 1 python -m venv "%ROOT%.venv"
    if errorlevel 1 (
      echo Atlas could not create .venv. Install Python 3.11 or newer, then run setup again.
      exit /b 1
    )
  )
  "%PYTHON%" "%ROOT%backend\scripts\setup.py"
  exit /b %ERRORLEVEL%
)

if not exist "%PYTHON%" (
  echo Atlas cannot find its Python environment at .venv\Scripts\python.exe.
  echo Run atlas setup first.
  exit /b 1
)

if /I "%~1"=="attach" (
  "%PYTHON%" "%ROOT%backend\scripts\attach.py" %*
  exit /b %ERRORLEVEL%
)

if /I "%~1"=="stop" (
  "%PYTHON%" "%ROOT%backend\scripts\stop.py"
  exit /b %ERRORLEVEL%
)

if /I "%~1"=="doctor" (
  "%PYTHON%" "%ROOT%backend\scripts\doctor.py"
  exit /b %ERRORLEVEL%
)

echo Atlas command helper
echo.
echo   .\atlas setup    First-time setup or change storage.
echo   .\atlas attach   Attach the current Codex project to this Atlas install.
echo   .\atlas stop     Stop the local Atlas API if it is running.
echo   .\atlas doctor   Check what is ready and what needs attention.
echo.
echo For normal daily use, start the database dependency if needed, then open a fresh Codex task. No Atlas command is required.
exit /b 0
