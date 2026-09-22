@echo off
REM Launch the v4 full-fleet run so it OUTLIVES the Claude Code session.
REM
REM Start-Process is not enough: the children stay inside the session's job
REM object and die with it (the 14:09 attempt was killed 2.5 min in). Start this
REM wrapper through WMI instead, so the new process is parented by WmiPrvSE:
REM
REM   Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
REM     -Arguments @{ CommandLine = 'cmd.exe /c F:\pcap_downloads\ev_charger_ai\run_v4.cmd' }
REM
REM Progress: Get-Content G:\ev_charger_ai_data_v4\logs\driver.log -Tail 20
setlocal

REM The data volume is a USB drive whose letter moves; these are resolved by
REM name at launch time by find_roots.ps1 rather than hardcoded here.
for /f "usebackq delims=" %%R in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_roots.ps1" data v4`) do set "EV_AI_DATA=%%R"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_roots.ps1" telemetry`) do set "EV_AI_TELEMETRY=%%R"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_roots.ps1" pcaps`) do set "EV_AI_PCAPS=%%R"
for /f "usebackq delims=" %%R in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_roots.ps1" prevsplit`) do set "EV_AI_PREV_SPLIT=%%R"

if not defined EV_AI_DATA exit /b 1
if not exist "%EV_AI_DATA%\logs" mkdir "%EV_AI_DATA%\logs"

echo [%DATE% %TIME%] launching v4  data=%EV_AI_DATA%  telemetry=%EV_AI_TELEMETRY%  pcaps=%EV_AI_PCAPS%>> "%EV_AI_DATA%\logs\launch.log"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_full_fleet.ps1" ^
  -SessionizeWorkers 4 -DatasetWorkers 6 -BenchWorkers 18 ^
  1>> "%EV_AI_DATA%\logs\driver.stdout.log" 2>> "%EV_AI_DATA%\logs\driver.stderr.log"

echo [%DATE% %TIME%] driver exited rc=%ERRORLEVEL%>> "%EV_AI_DATA%\logs\launch.log"
endlocal
