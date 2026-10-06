@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Aplikace jeste neni nainstalovana - nejdriv spust install.bat
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Spoustim bota s co nejcastejsim obchodovanim - 40 americkych akcii a 14 ETF (@us, @etf).
echo Trh kontroluje kazdou minutu, pozici drzi nejdele 3 minuty, az 10 pozic najednou, i sazky na pokles.
echo Obchoduje po-pa 15:30-22:00 naseho casu. Kryptomeny nonstop obchoduje bot-krypto.bat.
echo Papirovy ucet - falesne penize. Bota zastavis klavesami Ctrl+C nebo zavrenim okna.
echo.
".venv\Scripts\python.exe" -m daytrader bot --strategy scalp --interval 1m --param rsi=2 --param dip=45 --param take=55 --param max_hold=3 --symbols "@us,@etf" --max-positions 10 --max-trades 2000 --short --yes
pause
