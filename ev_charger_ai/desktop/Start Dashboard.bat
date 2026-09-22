@echo off
REM EGAT charger dashboard - visible-console launcher.
REM The Desktop shortcut uses pythonw.exe and shows no window; run this one
REM instead when something goes wrong and you want to see the messages.
setlocal
cd /d "%~dp0"

set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "C:\Users\%USERNAME%\anaconda3\envs\ev_ai\python.exe" set "PY=C:\Users\%USERNAME%\anaconda3\envs\ev_ai\python.exe"
if not defined PY for %%P in (python.exe) do if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"

if not defined PY (
  echo Python was not found. Install Python 3 or edit this file to point at it.
  pause
  exit /b 1
)

echo Using %PY%
"%PY%" -X utf8 app.py %*
if errorlevel 1 (
  echo.
  echo The dashboard exited with an error. See state\app.log
  pause
)
endlocal
