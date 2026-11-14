@echo off
title GlOp_cmp - LOCAL Processes - MATLAB batch
cd /d "C:\Users\Dell\Documents\MATLAB\GlOp_cmp"
echo GlOp_cmp: full local benchmark using MATLAB Processes
echo Starting 77,760 trials using the configured 2 local workers.
echo Log: %~dp0matlab.log
echo.
"C:\Program Files\MATLAB\R2026a\bin\matlab.exe" -wait -batch "parallel.defaultProfile('Processes'); setenv('BATCH_TASK_INDEX',''); setenv('BATCH_TASK_COUNT',''); setenv('FPF_OUTPUT_DIR',''); setenv('FPF_WORKERS_PER_TASK',''); setenv('FPF_LIVE_DIR',''); fprintf('LOCAL_BATCH_STARTED\n'); main; fprintf('LOCAL_BATCH_COMPLETED\n');" -logfile "%~dp0matlab.log"
set "MATLAB_EXIT_CODE=%ERRORLEVEL%"
echo.
echo MATLAB batch exited with code %MATLAB_EXIT_CODE%.
