@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Aplikace jeste neni nainstalovana - nejdriv spust install.bat
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Spoustim kryptobota - 30 kryptomen na Binance (@binance), obchoduje nonstop i o vikendu.
echo Ceny bere primo z burzy Binance (verejna data, bez registrace), obchoduje na papirovem uctu.
echo Trh kontroluje kazdou minutu, pozici drzi nejdele 3 minuty, az 10 pozic najednou, i sazky na pokles.
echo Bota zastavis klavesami Ctrl+C nebo zavrenim okna.
echo.
".venv\Scripts\python.exe" -m daytrader bot --provider ccxt --strategy scalp --interval 1m --param rsi=2 --param dip=45 --param take=55 --param max_hold=3 --symbols "@binance" --lookback 2d --max-positions 10 --max-trades 2000 --short --yes
pause
