$ErrorActionPreference = 'Stop'
$toolkitDirectory = 'C:\Users\Dell\Documents\matlab-cloud-toolkit'
$expectedHashes = @{
    'matlab_cloud_run.py' = '38706D8783EEE398F74E04999B89000BA7DA989662E3EEA953CD428D60B376CF'
    'matlab_cloud.py' = @('2145E45168850F3F1B7D86EDC2C364CDACC6EEF269C12D73BB6F14A35C5463E8',
                          '6629AFA0885B0D8103DD200C4498488ADD1BF2F88EA9EA8409D5CC1A91713AFB',
                          '3A3184AE2CE5CA25E317907B77FEB753138DBC1DEE4E7427ED224ACCAA21C418',
                          'CA8BAAF25F60FA6FF1BA276B92F97F9ADAB41F0EFE5A5287EA429523C39E4660',
                          'C1BBC623A826A778D4BA97EC42334091171E980789F40F1544E2D862058C7426')
    'matlab_cloud_trials.py' = 'F24D451ABDF1A9FBD80CA30254B2D76BE07CBEE8C5BB3FF234D2BCB9B6DECF1E'
    'matlab_cloud_progress.py' = @('B8ECACF12F0EA1FB29469923C6874B1F20668A0F5ADBF767EA4B19547CD0C290',
                                   '6A909626300B008F0E0BAE9070CB8B75D426FFC51B34B764E0786ECB3D92EA2A')
}
$files = @('matlab_cloud_run.py', 'matlab_cloud.py', 'matlab_cloud_trials.py', 'matlab_cloud_progress.py')
foreach ($name in $files) {
    $source = Join-Path $PSScriptRoot $name
    $target = Join-Path $toolkitDirectory $name
    if (!(Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing package file: $source" }
    if (Test-Path -LiteralPath $target) {
        $currentHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        $newHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        if ($currentHash -ne $newHash -and $currentHash -notin @($expectedHashes[$name])) {
            throw "Active file changed since inspection; preserve and review before installing: $target"
        }
    }
}
$backup = Join-Path $toolkitDirectory ('backups\live-reporting-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in $files) {
    $target = Join-Path $toolkitDirectory $name
    if (Test-Path -LiteralPath $target) { Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name) }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $target -Force
    if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name)).Hash) {
        throw "Installed file verification failed: $target"
    }
}
Write-Output "Installed and verified four launcher modules. Backup: $backup"
