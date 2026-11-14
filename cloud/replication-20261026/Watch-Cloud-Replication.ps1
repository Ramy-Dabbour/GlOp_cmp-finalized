param([Parameter(Mandatory=$true)][string]$Plan)
$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'GlOp_cmp - Google Cloud replication progress and recovery'
$replicationPython = 'C:\Users\Dell\AppData\Local\Programs\Python\Python312\python.exe'
$replicationManager = Join-Path $PSScriptRoot 'manage_replication.py'
Write-Host 'GlOp_cmp cloud replication: live durable counts, MAT/CSV downloads, and automatic recovery.'
Write-Host ('Plan: ' + $Plan)
Write-Host 'Cloud computation continues if this terminal closes; the monitor resumes at Windows logon.'
& $replicationPython -B -u $replicationManager watch --plan $Plan
exit $LASTEXITCODE
