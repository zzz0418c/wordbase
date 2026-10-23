@echo off
rem Only acts between 18:00 and 21:00: read vivo notes, tick off today's reviews, push.
rem If the PC is off nothing runs - that is intended.
setlocal
for /f "tokens=1 delims=:" %%a in ("%TIME%") do set HH=%%a
set HH=%HH: =%
if %HH% LSS 18 exit /b 0
if %HH% GEQ 21 exit /b 0
call "%~dp0vv.cmd" sync-vivo --push
