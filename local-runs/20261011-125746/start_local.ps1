$ErrorActionPreference = 'Stop'
$projectDirectory = 'C:\Users\Dell\Documents\MATLAB\GlOp_cmp'
$runDirectory = $PSScriptRoot
$logPath = Join-Path $runDirectory 'matlab.log'
$matlabCommand = "parallel.defaultProfile('Processes'); setenv('BATCH_TASK_INDEX',''); setenv('BATCH_TASK_COUNT',''); setenv('FPF_OUTPUT_DIR',''); setenv('FPF_WORKERS_PER_TASK',''); setenv('FPF_LIVE_DIR',''); fprintf('LOCAL_BATCH_STARTED\n'); main; fprintf('LOCAL_BATCH_COMPLETED\n');"
$matlabArguments = '-wait -sd "' + $projectDirectory + '" -batch "' + $matlabCommand + '" -logfile "' + $logPath + '"'
$matlabProcess = Start-Process -FilePath 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe' -ArgumentList $matlabArguments -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru
$runInfo = [ordered]@{
    processId = $matlabProcess.Id
    startedAt = (Get-Date).ToUniversalTime().ToString('o')
    project = $projectDirectory
    profile = 'Processes'
    log = $logPath
    arguments = $matlabArguments
}
$runInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDirectory 'launch.json') -Encoding utf8
$runInfo | ConvertTo-Json
