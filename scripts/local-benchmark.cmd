@echo off
if "%~1"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-benchmark.ps1" -Action Start
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-benchmark.ps1" -Action %*
)
