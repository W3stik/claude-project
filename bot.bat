@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Aplikace jeste neni nainstalovana - nejdriv spust install.bat
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Spoustim automatickeho obchodniho bota.
echo Strategie, symboly a interval se nastavuji v souboru .env - radky DT_BOT_...
echo Bota zastavis klavesami Ctrl+C nebo zavrenim tohoto okna.
echo.
".venv\Scripts\python.exe" -m daytrader bot --yes
pause
