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