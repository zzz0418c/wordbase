@echo off
rem Only acts between 18:00 and 21:00.
rem 1) read the "next date" page of every note -> schedule.csv (source of truth)
rem 2) tick off today's reviews -> book.json
rem If the PC is off nothing runs - the cloud still sends whatever is in schedule.csv.
setlocal
for /f "tokens=1 delims=:" %%a in ("%TIME%") do set HH=%%a
set HH=%HH: =%
if %HH% LSS 18 exit /b 0
if %HH% GEQ 21 exit /b 0
call "%~dp0vv.cmd" sync-dates --push
call "%~dp0vv.cmd" sync-vivo --push
