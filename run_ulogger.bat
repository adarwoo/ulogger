@echo off
REM Run ulogger in Windows Terminal if available, otherwise use cmd
where wt >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    start wt -w 0 nt --title "uLogger" "%~dp0dist\ulogger.exe" %*
) else (
    start "uLogger" "%~dp0dist\ulogger.exe" %*
)
