[CmdletBinding()]
param(
    [ValidateSet('Install','Start','Watch','Run','Stop','Resume','Remove','Status')]
    [string]$Action = 'Start',
    [string]$ProjectRoot = '',
    [string]$OutputDirectory = '',
    [string]$StateDirectory = '',
    [string]$MatlabExecutable = '',
    [string]$MatlabCommand = 'fpf.runLocalBenchmark',
    [string]$TaskName = '',
    [switch]$ForceStop,
    # Test-only substitution; the script receives StatePath, LogPath and StopPath.
    [string]$TestWorkerScript = '',
    [int]$RetrySeconds = 15,
    [int]$MaximumRetrySeconds = 300
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "Project directory does not exist: $ProjectRoot" }
if (-not $OutputDirectory) { $OutputDirectory = $ProjectRoot }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $StateDirectory) { $StateDirectory = Join-Path $OutputDirectory 'local-results' }
$StateDirectory = [IO.Path]::GetFullPath($StateDirectory)
$null = New-Item -ItemType Directory -Path $StateDirectory -Force
$scriptPath = $PSCommandPath
$statePath = Join-Path $StateDirectory 'state.json'
$stopPath = Join-Path $StateDirectory 'STOP'
$activePath = Join-Path $StateDirectory 'active-attempt.json'
$controlPath = Join-Path $StateDirectory 'supervisor.json'
$progressPath = Join-Path $StateDirectory 'supervisor.log'
$lockPath = Join-Path $StateDirectory 'supervisor.lock'
$launchLockPath = Join-Path $StateDirectory 'launcher.lock'
$launchRequestPath = Join-Path $StateDirectory 'launch-request.json'
$utf8 = New-Object Text.UTF8Encoding($false)
$sha = [Security.Cryptography.SHA256]::Create()
try { $pathHash = ([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($StateDirectory.ToLowerInvariant())))).Replace('-','').Substring(0,12) }
finally { $sha.Dispose() }
if (-not $TaskName) { $TaskName = "GlOp_cmp Local Recovery $pathHash" }
if ($RetrySeconds -lt 1 -or $MaximumRetrySeconds -lt $RetrySeconds) { throw 'Invalid retry intervals.' }

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json) }
    catch { return $null } # MATLAB publishes state atomically; tolerate transient sharing errors.
}

function Write-JsonAtomic([string]$Path, $Value) {
    $temporary = "$Path.$PID.tmp"
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 12), $utf8)
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary,$Path,[System.Management.Automation.Language.NullString]::Value) }
    else { [IO.File]::Move($temporary,$Path) }
}

function Write-RunLog([string]$Message) {
    $line = ('[{0}] {1}' -f [DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss zzz'),$Message) + [Environment]::NewLine
    [IO.File]::AppendAllText($progressPath,$line,$utf8)
    Write-Host -NoNewline $line
}

function Get-ExclusiveLock([string]$Path) {
    try { return [IO.File]::Open($Path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
    catch [IO.IOException] { return $null }
}

# Quote argv for Windows native command parsing, including trailing backslashes.
function Quote-Argument([string]$Value) {
    if ($Value -notmatch '[\s"]' -and $Value.Length -gt 0) { return $Value }
    $quoted = [regex]::Replace($Value,'(\\*)"','$1$1\"')
    $quoted = [regex]::Replace($quoted,'(\\+)$','$1$1')
    return '"' + $quoted + '"'
}

function Join-Arguments([string[]]$Values) { return (($Values | ForEach-Object { Quote-Argument $_ }) -join ' ') }

function Get-SelfArguments([string]$RequestedAction) {
    $values = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$scriptPath,'-Action',$RequestedAction,
        '-ProjectRoot',$ProjectRoot,'-OutputDirectory',$OutputDirectory,'-StateDirectory',$StateDirectory,'-TaskName',$TaskName,
        '-RetrySeconds',[string]$RetrySeconds,'-MaximumRetrySeconds',[string]$MaximumRetrySeconds)
    if ($MatlabExecutable) { $values += @('-MatlabExecutable',$MatlabExecutable) }
    if ($MatlabCommand -ne 'fpf.runLocalBenchmark') { $values += @('-MatlabCommand',$MatlabCommand) }
    if ($TestWorkerScript) { $values += @('-TestWorkerScript',$TestWorkerScript) }
    return $values
}

function Get-RecordedProcess($Attempt) {
    if (-not $Attempt -or -not $Attempt.worker_pid) { return $null }
    try {
        $process = Get-Process -Id ([int]$Attempt.worker_pid) -ErrorAction Stop
        $null = $process.Handle # Retain access to its exit code after it exits.
        if ($process.StartTime.ToUniversalTime().Ticks.ToString() -ne [string]$Attempt.worker_start_ticks) { return $null }
        return $process
    } catch { return $null }
}

function Test-Completed {
    $state = Read-Json $statePath
    return ($null -ne $state -and $state.status -eq 'completed')
}

function Test-NeedsAttention {
    $state = Read-Json $statePath
    if (-not $state -or -not $state.PSObject.Properties['failure_identifier']) { return $false }
    return ([string]$state.failure_identifier -match '^fpf:(CheckpointMismatch|CorruptCheckpoint|CheckpointCorrupt|SourceMismatch)$')
}

function Stop-RecordedWorker {
    $attempt = Read-Json $activePath
    $process = Get-RecordedProcess $attempt
    if ($process) {
        # The PID and creation time were checked immediately above. /T includes its local workers.
        & "$env:SystemRoot\System32\taskkill.exe" /PID ([string]$process.Id) /T /F | Out-Host
        if ($LASTEXITCODE -ne 0 -and (Get-RecordedProcess $attempt)) { throw "Could not stop recorded worker PID $($process.Id)." }
    }
}

function Show-Status {
    $state = Read-Json $statePath
    $control = Read-Json $controlPath
    $attempt = Read-Json $activePath
    $process = Get-RecordedProcess $attempt
    $lock = Get-ExclusiveLock $lockPath
    $supervisorRunning = $null -eq $lock
    if ($lock) { $lock.Dispose() }
    [pscustomobject]@{
        Project = $ProjectRoot
        OutputDirectory = $OutputDirectory
        StopRequested = (Test-Path -LiteralPath $stopPath)
        SupervisorRunning = $supervisorRunning
        WorkerPID = $(if ($process) { $process.Id } else { $null })
        BenchmarkState = $state
        SupervisorState = $control
        ScheduledTask = $TaskName
        ProgressLog = $progressPath
        BenchmarkProgressLog = (Join-Path $StateDirectory 'progress.log')
    } | ConvertTo-Json -Depth 12 | Write-Output
}

function Start-VisibleTerminal {
    $launchLock = Get-ExclusiveLock $launchLockPath
    if (-not $launchLock) { return }
    try {
        if (Test-Path -LiteralPath $stopPath) { return }
        $control = Read-Json $controlPath
        if ((Test-Completed) -and $control -and $control.status -eq 'completed') { return }
        if ($control -and $control.status -eq 'needs_attention') { return }
        $runLock = Get-ExclusiveLock $lockPath
        if (-not $runLock) { return }
        $runLock.Dispose()
        $request = Read-Json $launchRequestPath
        if ($request -and ([DateTime]::UtcNow - [DateTime]::Parse($request.requested_utc).ToUniversalTime()).TotalSeconds -lt 45) { return }
        Write-JsonAtomic $launchRequestPath @{ requested_utc = [DateTime]::UtcNow.ToString('o') }
        $powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $runArguments = @('-NoExit') + @(Get-SelfArguments 'Run')
        $terminal = Get-Command wt.exe -ErrorAction SilentlyContinue
        if ($terminal) {
            $terminalArguments = @('-w','new','new-tab','--title','GlOp_cmp - LOCAL Processes - resumable batch',
                '--startingDirectory',$ProjectRoot,$powerShell) + $runArguments
            $null = Start-Process -FilePath $terminal.Source -ArgumentList (Join-Arguments $terminalArguments) -WindowStyle Normal -PassThru
        } else {
            $null = Start-Process -FilePath $powerShell -ArgumentList (Join-Arguments $runArguments) -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
        }
    } finally { $launchLock.Dispose() }
}

function Install-RecoveryTask {
    if ($TestWorkerScript) { throw 'Installing automatic recovery for a test worker is disabled.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $userSid = $identity.User.Value
    $powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $watchArguments = Join-Arguments (@('-WindowStyle','Hidden') + @(Get-SelfArguments 'Watch'))
    $escape = { param($value) [Security.SecurityElement]::Escape([string]$value) }
    $commandXml = & $escape $powerShell
    $argumentsXml = & $escape $watchArguments
    $workingDirectoryXml = & $escape $ProjectRoot
    $startBoundary = [DateTime]::Now.AddMinutes(1).ToString('yyyy-MM-ddTHH:mm:ss')
    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Recover this local GlOp_cmp benchmark after a terminal closes or after Windows sign-in. STOP suppresses recovery.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>$userSid</UserId></LogonTrigger>
    <TimeTrigger><Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>$startBoundary</StartBoundary><Enabled>true</Enabled></TimeTrigger>
  </Triggers>
  <Principals><Principal id="User"><UserId>$userSid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="User"><Exec><Command>$commandXml</Command><Arguments>$argumentsXml</Arguments><WorkingDirectory>$workingDirectoryXml</WorkingDirectory></Exec></Actions>
</Task>
"@
    $null = Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force
    Write-RunLog "Installed recovery task '$TaskName': checks every minute while signed in and at sign-in."
}

function Relay-LogFile($Attempt,[string]$PathProperty,[string]$OffsetProperty) {
    if (-not $Attempt.PSObject.Properties[$PathProperty]) { return }
    $path = [string]$Attempt.$PathProperty
    if (-not (Test-Path -LiteralPath $path)) { return }
    $stream = $null
    $reader = $null
    try {
        $stream = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
        if ($stream.Length -lt [long]$Attempt.$OffsetProperty) { $Attempt.$OffsetProperty = 0 }
        $null = $stream.Seek([long]$Attempt.$OffsetProperty,[IO.SeekOrigin]::Begin)
        $reader = New-Object IO.StreamReader($stream,$utf8,$true,4096,$true)
        $chunk = $reader.ReadToEnd()
        if ($chunk.Length -gt 0) {
            Write-Host -NoNewline $chunk
            $Attempt.$OffsetProperty = $stream.Position
            Write-JsonAtomic $activePath $Attempt
        }
    } catch [IO.IOException] {
        # The MATLAB log can briefly be locked while being created.
    } finally {
        if ($reader) { $reader.Dispose() }
        if ($stream) { $stream.Dispose() }
    }
}

function Relay-AttemptLog($Attempt,[switch]$Finished) {
    Relay-LogFile $Attempt 'log_path' 'log_offset'
    Relay-LogFile $Attempt 'stderr_path' 'stderr_offset'
    if ($Finished -and (-not (Test-Path -LiteralPath $Attempt.log_path) -or (Get-Item -LiteralPath $Attempt.log_path).Length -eq 0)) {
        Relay-LogFile $Attempt 'stdout_path' 'stdout_offset'
    }
}

function New-Attempt {
    $attemptName = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff') + "-$PID"
    $attemptDirectory = Join-Path (Join-Path $StateDirectory 'attempts') $attemptName
    $null = New-Item -ItemType Directory -Path $attemptDirectory -Force
    $logPath = Join-Path $attemptDirectory 'matlab.log'
    $stdoutPath = Join-Path $attemptDirectory 'stdout.log'
    $stderrPath = Join-Path $attemptDirectory 'stderr.log'
    $savedEnvironment = @{}
    if ($TestWorkerScript) {
        $workerExecutable = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $workerArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',[IO.Path]::GetFullPath($TestWorkerScript),
            '-StatePath',$statePath,'-LogPath',$logPath,'-StopPath',$stopPath)
    } else {
        if (-not $MatlabExecutable) {
            $discoveredMatlabCommand = Get-Command matlab.exe -ErrorAction Stop
            $workerExecutable = $discoveredMatlabCommand.Source
        } else { $workerExecutable = $MatlabExecutable }
        $actualCommand = $MatlabCommand
        if ($actualCommand -eq 'fpf.runLocalBenchmark') {
            $actualCommand = "fpf.runLocalBenchmark(OutputDirectory='" + $OutputDirectory.Replace("'","''") + "')"
            if ($StateDirectory -ne (Join-Path $OutputDirectory 'local-results')) { throw 'StateDirectory must match OutputDirectory/local-results unless MatlabCommand or TestWorkerScript is supplied.' }
        }
        $workerArguments = @('-wait','-batch',$actualCommand,'-logfile',$logPath)
        # Clear deployment-only settings inherited by a terminal environment.
        foreach ($name in @('BATCH_TASK_INDEX','BATCH_TASK_COUNT','FPF_OUTPUT_DIR','FPF_WORKERS_PER_TASK','FPF_LIVE_DIR')) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name,'Process')
            [Environment]::SetEnvironmentVariable($name,$null,'Process')
        }
    }
    try {
        $process = Start-Process -FilePath $workerExecutable -ArgumentList (Join-Arguments $workerArguments) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $null = $process.Handle
    } finally {
        foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name,$savedEnvironment[$name],'Process') }
    }
    $attempt = [pscustomobject]@{
        attempt = $attemptName
        worker_pid = $process.Id
        worker_start_ticks = $process.StartTime.ToUniversalTime().Ticks.ToString()
        started_utc = [DateTime]::UtcNow.ToString('o')
        log_path = $logPath
        log_offset = 0
        stdout_path = $stdoutPath
        stdout_offset = 0
        stderr_path = $stderrPath
        stderr_offset = 0
        result_path = (Join-Path $attemptDirectory 'exit.json')
    }
    Write-JsonAtomic $activePath $attempt
    Write-RunLog "Started attempt $attemptName, worker PID $($process.Id). Log: $logPath"
    return @{ attempt = $attempt; process = $process }
}

function Run-Supervisor {
    $lock = Get-ExclusiveLock $lockPath
    if (-not $lock) { Write-Host 'A supervisor is already running for this results directory.'; return }
    try {
        $Host.UI.RawUI.WindowTitle = 'GlOp_cmp - LOCAL Processes - resumable batch'
        Write-RunLog "Local benchmark supervisor PID $PID. Live log: $progressPath"
        Write-Host 'Intentional stop: scripts\local-benchmark.cmd Stop. Resume: scripts\local-benchmark.cmd Resume.'
        $control = Read-Json $controlPath
        $failures = 0
        if ($control -and $control.consecutive_failures) { $failures = [int]$control.consecutive_failures }
        while ($true) {
            if (Test-Path -LiteralPath $stopPath) {
                Write-RunLog 'STOP is present. Automatic restart is paused.'
                Write-JsonAtomic $controlPath @{status='stopped';consecutive_failures=$failures;updated_utc=[DateTime]::UtcNow.ToString('o')}
                return
            }
            if ((Test-Completed) -and $control -and $control.status -eq 'completed') { Write-RunLog 'All trials were already completed successfully.'; return }
            if ($control -and $control.PSObject.Properties['retry_after_utc'] -and $control.retry_after_utc) {
                $retryAfter = [DateTime]::Parse($control.retry_after_utc).ToUniversalTime()
                while ([DateTime]::UtcNow -lt $retryAfter) {
                    if (Test-Path -LiteralPath $stopPath) { return }
                    Start-Sleep -Milliseconds 250
                }
            }
            $attempt = Read-Json $activePath
            $process = Get-RecordedProcess $attempt
            $reattached = $null -ne $process
            if ($process) {
                Write-RunLog "Reattached to surviving worker PID $($process.Id); no duplicate trial execution was started."
            } else {
                if ($attempt -and -not (Test-Path -LiteralPath $attempt.result_path)) {
                    Relay-AttemptLog $attempt -Finished
                    Write-JsonAtomic $attempt.result_path @{attempt=$attempt.attempt;exit_code=$null;outcome='interrupted';finished_utc=[DateTime]::UtcNow.ToString('o')}
                    Write-RunLog "Previous attempt $($attempt.attempt) was interrupted. Resuming committed results."
                }
                $started = New-Attempt
                $attempt = $started.attempt
                $process = $started.process
            }
            $control = @{status='running';supervisor_pid=$PID;worker_pid=$process.Id;consecutive_failures=$failures;updated_utc=[DateTime]::UtcNow.ToString('o')}
            Write-JsonAtomic $controlPath $control
            $stopNoticeShown = $false
            while (-not $process.HasExited) {
                Relay-AttemptLog $attempt
                if ((Test-Path -LiteralPath $stopPath) -and -not $stopNoticeShown) {
                    Write-RunLog 'STOP requested. MATLAB will preserve committed results and exit at its next cancellation check.'
                    $stopNoticeShown = $true
                }
                Start-Sleep -Milliseconds 200
                $process.Refresh()
            }
            $process.WaitForExit()
            Relay-AttemptLog $attempt -Finished
            $exitCode = $null
            try { $exitCode = $process.ExitCode } catch { }
            $process.Dispose()
            $complete = (Test-Completed) -and $exitCode -eq 0
            $outcome = 'failed'
            if ($complete) { $outcome = 'completed' }
            elseif (Test-Path -LiteralPath $stopPath) { $outcome = 'stopped' }
            Write-JsonAtomic $attempt.result_path @{attempt=$attempt.attempt;exit_code=$exitCode;outcome=$outcome;reattached=$reattached;finished_utc=[DateTime]::UtcNow.ToString('o')}
            Write-RunLog "Attempt $($attempt.attempt) exited with code $exitCode. Outcome: $outcome."
            if ($complete) {
                Write-JsonAtomic $controlPath @{status='completed';consecutive_failures=0;updated_utc=[DateTime]::UtcNow.ToString('o')}
                Write-RunLog 'BENCHMARK COMPLETED SUCCESSFULLY. MAT and CSV exports are saved in the project directory.'
                return
            }
            if (Test-NeedsAttention) {
                Write-JsonAtomic $controlPath @{status='needs_attention';consecutive_failures=$failures;updated_utc=[DateTime]::UtcNow.ToString('o')}
                Write-RunLog 'Recovery paused: MATLAB reported incompatible or corrupt checkpoints. Review state.json, repair the cause, then use Resume.'
                return
            }
            if (Test-Path -LiteralPath $stopPath) {
                Write-JsonAtomic $controlPath @{status='stopped';consecutive_failures=$failures;updated_utc=[DateTime]::UtcNow.ToString('o')}
                return
            }
            $failures++
            $delay = [Math]::Min($MaximumRetrySeconds,$RetrySeconds * [Math]::Pow(2,[Math]::Min($failures-1,10)))
            $control = @{status='retrying';consecutive_failures=$failures;retry_after_utc=[DateTime]::UtcNow.AddSeconds($delay).ToString('o');updated_utc=[DateTime]::UtcNow.ToString('o')}
            Write-JsonAtomic $controlPath $control
            $control = Read-Json $controlPath
            Write-RunLog "Restarting in $delay seconds from the saved trials. STOP suppresses restart."
        }
    } finally { $lock.Dispose() }
}

switch ($Action) {
    'Install' { Install-RecoveryTask }
    'Start' { Start-VisibleTerminal }
    'Watch' { Start-VisibleTerminal }
    'Run' { Run-Supervisor }
    'Stop' {
        [IO.File]::WriteAllText($stopPath,"Intentional stop requested at $([DateTime]::UtcNow.ToString('o'))",$utf8)
        if ($ForceStop) { Stop-RecordedWorker }
        Write-Host 'STOP saved. Recovery is paused; committed trials are retained. Use Resume to continue.'
    }
    'Resume' {
        if (Test-Path -LiteralPath $stopPath) { Remove-Item -LiteralPath $stopPath }
        $control = Read-Json $controlPath
        if ($control -and $control.status -eq 'needs_attention') {
            Write-JsonAtomic $controlPath @{status='resume_requested';consecutive_failures=0;updated_utc=[DateTime]::UtcNow.ToString('o')}
        }
        Start-VisibleTerminal
    }
    'Remove' {
        [IO.File]::WriteAllText($stopPath,"Recovery removed at $([DateTime]::UtcNow.ToString('o'))",$utf8)
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
        if ($ForceStop) { Stop-RecordedWorker }
        Write-Host 'Automatic recovery was removed. Saved results and logs were retained.'
    }
    'Status' { Show-Status }
}
