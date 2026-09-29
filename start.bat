@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Aplikace jeste neni nainstalovana - nejdriv spust install.bat
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Spoustim dashboard na http://localhost:8501
echo Toto okno nezavirej, jinak se aplikace vypne.
".venv\Scripts\python.exe" -m daytrader dashboard
pause
