$ErrorActionPreference = 'Stop'
$outputPath = Join-Path $PSScriptRoot 'power-requests-20261029.txt'
$lines = @('Captured: ' + (Get-Date).ToString('o'))
$lines += (& "$env:SystemRoot\System32\powercfg.exe" /requests 2>&1 | Out-String)
$resultCode = $LASTEXITCODE
$lines += 'Exit code: ' + $resultCode
$lines | Set-Content -LiteralPath $outputPath -Encoding UTF8
exit $resultCode
