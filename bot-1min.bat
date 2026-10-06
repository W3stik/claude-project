@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Aplikace jeste neni nainstalovana - nejdriv spust install.bat
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Spoustim minutoveho bota - skalpovani na 1minutovych svickach.
echo Trh kontroluje kazdou minutu, pozici drzi nejdele 10 minut, nejvys 100 obchodu za den.
echo Symboly bere ze souboru .env - radek DT_BOT_SYMBOLS.
echo Bota zastavis klavesami Ctrl+C nebo zavrenim tohoto okna.
echo.
".venv\Scripts\python.exe" -m daytrader bot --strategy scalp --interval 1m --max-trades 100 --yes
pause
