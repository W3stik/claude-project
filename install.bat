@echo off
setlocal
cd /d "%~dp0"
echo === Instalace aplikace Daytrader ===
echo.

rem Python: promenna DAYTRADER_PYTHON, jinak spoustec "py", jinak "python"
set "PY=%DAYTRADER_PYTHON%"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :nopython
%PY% --version

if not exist ".venv\Scripts\python.exe" (
    echo Vytvarim virtualni prostredi .venv ...
    %PY% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto :failed

set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
echo.
echo Instaluji aplikaci a knihovny, muze to trvat nekolik minut ...
"%VPY%" -m pip install -e ".[all]"
if errorlevel 1 (
    echo.
    echo [VAROVANI] Plna instalace selhala. Zkousim zakladni verzi bez kryptoburz a AI komentare ...
    "%VPY%" -m pip install -e .
    if errorlevel 1 goto :failed
)
if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo === Hotovo! Aplikaci spustis dvojklikem na start.bat ===
if not defined CI pause
exit /b 0

:nopython
echo [CHYBA] Nenasel jsem Python 3.10 nebo novejsi.
echo Nainstaluj ho z https://www.python.org/downloads/ a pri instalaci zaskrtni "Add python.exe to PATH".
if not defined CI pause
exit /b 1

:failed
echo.
echo [CHYBA] Instalace selhala. Zkopiruj prosim vypis chyby nahore a posli ho.
if not defined CI pause
exit /b 1
