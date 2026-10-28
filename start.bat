@echo off
rem Double-click launcher (Windows): starts the local web UI and opens the browser.
rem First run installs dependencies once. The page itself is in Chinese; this script
rem stays ASCII-only because cmd.exe parses .bat files with the local code page.
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython

rem 3.10+ is the package floor; a stray old interpreter would only produce noise.
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython

rem Already usable (package + Flask present)? Then skip straight to starting.
%PY% -c "import westlake_survival, flask" >nul 2>nul
if not errorlevel 1 goto :run

%PY% -m pip --version >nul 2>nul
if errorlevel 1 goto :nopip

echo First run: installing dependencies, about 1-2 minutes. Keep this window open...
%PY% -m pip install -e ".[webui]"
if errorlevel 1 (
  echo.
  echo Install failed. Send the messages above to the maintainer, or run manually:
  echo   %PY% -m pip install -e ".[webui]"
  pause
  exit /b 1
)

:run
echo.
echo Starting... the browser will open at the setup page.
echo Close this window to stop the service.
%PY% -m westlake_survival
pause
exit /b 0

:nopip
echo This Python has no pip, so dependencies cannot be installed: %PY%
echo Install Python from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
echo then double-click this file again.
pause
exit /b 1

:nopython
echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during setup, then double-click this file again.
pause
exit /b 1
