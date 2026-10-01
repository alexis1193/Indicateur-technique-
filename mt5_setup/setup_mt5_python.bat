@echo off
REM Lanceur double-clic pour setup_mt5_python.ps1
REM Usage : setup_mt5_python.bat [-CheckOnly] [-TestMT5] [-Symbol XAUUSD]
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_mt5_python.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
echo Code de sortie : %RC%  (0 = OK, 1 = point bloquant, 2 = MT5 absent)
pause
exit /b %RC%
