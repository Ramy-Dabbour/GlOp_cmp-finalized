[CmdletBinding()]
param([string]$TestRoot = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$project = Split-Path -Parent $PSScriptRoot
if (-not $TestRoot) { $TestRoot = Join-Path $project ('tests\results\supervisor-' + [Guid]::NewGuid().ToString('N')) }
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
$null = New-Item -ItemType Directory -Path $TestRoot -Force
$utf8 = New-Object Text.UTF8Encoding($false)
$workerScript = Join-Path $TestRoot 'fake-worker.ps1'
$workerSource = @'
param([string]$StatePath,[string]$LogPath,[string]$StopPath)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
$root = Split-Path -Parent $StatePath
$count = 0
if (Test-Path -LiteralPath $StatePath) { $count = [int](Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json).completed_trials }
function Publish($status) {
    $value = @{status=$status;completed_trials=$count;total_trials=24} | ConvertTo-Json
    [IO.File]::WriteAllText("$StatePath.$PID.tmp",$value,$utf8)
    if (Test-Path -LiteralPath $StatePath) { [IO.File]::Replace("$StatePath.$PID.tmp",$StatePath,[System.Management.Automation.Language.NullString]::Value) }
    else { [IO.File]::Move("$StatePath.$PID.tmp",$StatePath) }
}
[IO.File]::AppendAllText($LogPath,"RESUME $count/24`r`n",$utf8)
Publish 'running'
while ($count -lt 24) {
    if (Test-Path -LiteralPath $StopPath) { Publish 'stopped'; exit 0 }
    Start-Sleep -Milliseconds 400
    $count++
    Publish 'running'
    [IO.File]::AppendAllText((Join-Path $root 'commits.txt'),"$count`r`n",$utf8)
    [IO.File]::AppendAllText($LogPath,"COMMITTED $count/24`r`n",$utf8)
}
Publish 'completed'
'@
[IO.File]::WriteAllText($workerScript,$workerSource,$utf8)
$launcher = Join-Path $PSScriptRoot 'local-benchmark.ps1'
$powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$stateDirectory = Join-Path $TestRoot 'run'
$supervisors = New-Object Collections.Generic.List[Diagnostics.Process]
function Assert($condition,[string]$message) { if (-not $condition) { throw $message } }
function Read-State { try { return Get-Content -LiteralPath (Join-Path $stateDirectory 'state.json') -Raw -ErrorAction Stop | ConvertFrom-Json } catch { return $null } }
function Wait-Until([scriptblock]$condition,[int]$seconds=30) {
    $until = [DateTime]::UtcNow.AddSeconds($seconds)
    do { if (& $condition) { return }; Start-Sleep -Milliseconds 150 } while ([DateTime]::UtcNow -lt $until)
    throw "Timed out: $condition"
}
function Start-TestSupervisor([string]$name) {
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $launcher + '" -Action Run -ProjectRoot "' + $project + '" -StateDirectory "' + $stateDirectory + '" -TestWorkerScript "' + $workerScript + '" -RetrySeconds 1 -MaximumRetrySeconds 2'
    $process = Start-Process -FilePath $powerShell -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $TestRoot "$name.stdout.log") -RedirectStandardError (Join-Path $TestRoot "$name.stderr.log")
    $null = $process.Handle
    $supervisors.Add($process)
    return $process
}
try {
    $first = Start-TestSupervisor 'first'
    Wait-Until { $state = Read-State; $state -and $state.completed_trials -ge 2 }
    $attempt = Get-Content -LiteralPath (Join-Path $stateDirectory 'active-attempt.json') -Raw | ConvertFrom-Json
    $initialPid = [int]$attempt.worker_pid
    Stop-Process -Id $initialPid -Force
    Wait-Until { $a = Get-Content -LiteralPath (Join-Path $stateDirectory 'active-attempt.json') -Raw | ConvertFrom-Json; [int]$a.worker_pid -ne $initialPid }
    Wait-Until { $state = Read-State; $state -and $state.completed_trials -ge 5 }
    $survivingAttempt = Get-Content -LiteralPath (Join-Path $stateDirectory 'active-attempt.json') -Raw | ConvertFrom-Json
    Stop-Process -Id $first.Id -Force
    $replacement = Start-TestSupervisor 'replacement'
    Wait-Until { Select-String -LiteralPath (Join-Path $stateDirectory 'supervisor.log') -SimpleMatch 'Reattached to surviving worker' -Quiet }
    $duplicate = Start-TestSupervisor 'duplicate'
    Assert ($duplicate.WaitForExit(15000)) 'Duplicate supervisor did not exit promptly.'
    Assert ($duplicate.ExitCode -eq 0) 'Duplicate supervisor should exit without error.'
    Assert ($replacement.WaitForExit(30000)) 'Recovered supervisor did not finish.'
    Assert ($replacement.ExitCode -eq 0) 'Recovered supervisor failed.'
    $state = Read-State
    Assert ($state.status -eq 'completed' -and $state.completed_trials -eq 24) 'Run did not complete all 24 fixture trials.'
    $commits = @(Get-Content -LiteralPath (Join-Path $stateDirectory 'commits.txt'))
    Assert ($commits.Count -eq 24 -and ($commits -join ',') -eq ((1..24) -join ',')) 'Committed trials were lost or duplicated.'
    $attempts = @(Get-ChildItem -LiteralPath (Join-Path $stateDirectory 'attempts') -Directory)
    Assert ($attempts.Count -eq 2) "Expected exactly two attempts, got $($attempts.Count)."
    $failedResult = Get-Content -LiteralPath (Join-Path $attempts[0].FullName 'exit.json') -Raw | ConvertFrom-Json
    $successfulResult = Get-Content -LiteralPath (Join-Path $attempts[1].FullName 'exit.json') -Raw | ConvertFrom-Json
    Assert ($failedResult.outcome -eq 'failed') 'Killed attempt was not recorded as failed.'
    Assert ($successfulResult.outcome -eq 'completed' -and $successfulResult.exit_code -eq 0 -and $successfulResult.reattached) 'Reattached completion and exit code were not recorded.'
    & $launcher -Action Stop -ProjectRoot $project -StateDirectory $stateDirectory
    Assert (Test-Path -LiteralPath (Join-Path $stateDirectory 'STOP')) 'Stop sentinel was not saved.'
    & $launcher -Action Watch -ProjectRoot $project -StateDirectory $stateDirectory -TestWorkerScript $workerScript
    Assert (-not (Test-Path -LiteralPath (Join-Path $stateDirectory 'launch-request.json'))) 'Watch tried to launch despite STOP.'
    $result = @{passed=$true;trials=24;attempts=$attempts.Count;forced_worker_kill=$true;forced_supervisor_kill=$true;reattached=$true;duplicate_suppressed=$true;stop_suppressed_watch=$true;test_root=$TestRoot}
    [IO.File]::WriteAllText((Join-Path $TestRoot 'test-result.json'),($result | ConvertTo-Json),$utf8)
    $result | ConvertTo-Json | Write-Output
} finally {
    $null = New-Item -ItemType Directory -Path $stateDirectory -Force
    [IO.File]::WriteAllText((Join-Path $stateDirectory 'STOP'),'Test cleanup',$utf8)
    $activePath = Join-Path $stateDirectory 'active-attempt.json'
    if (Test-Path -LiteralPath $activePath) {
        $active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
        $activeProcess = Get-Process -Id $active.worker_pid -ErrorAction SilentlyContinue
        if ($activeProcess -and $activeProcess.StartTime.ToUniversalTime().Ticks.ToString() -eq $active.worker_start_ticks) { Stop-Process -Id $activeProcess.Id -Force }
    }
    foreach ($process in $supervisors) { if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }; $process.Dispose() }
}
