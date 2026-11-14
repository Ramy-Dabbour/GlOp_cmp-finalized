$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class GlOpIdleParameters {
    [DllImport("user32.dll", EntryPoint="SystemParametersInfoW", SetLastError=true)]
    public static extern bool Get(uint action, uint param, ref uint value, uint flags);
    [DllImport("user32.dll", EntryPoint="SystemParametersInfoW", SetLastError=true)]
    public static extern bool Set(uint action, uint param, IntPtr value, uint flags);
}
'@
function Get-IdleParameter([uint32]$Action) {
    [uint32]$value = 0
    if (-not [GlOpIdleParameters]::Get($Action, 0, [ref]$value, 0)) {
        throw "Reading system parameter $Action failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    return $value
}
function Set-IdleParameter([uint32]$Action, [uint32]$Value) {
    if (-not [GlOpIdleParameters]::Set($Action, $Value, [IntPtr]::Zero, 3)) {
        throw "Setting system parameter $Action failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
}
$desktopKey = 'HKCU:\Control Panel\Desktop'
$beforeProperties = Get-ItemProperty -LiteralPath $desktopKey
$before = [ordered]@{
    captured = (Get-Date).ToString('o')
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    active = Get-IdleParameter 0x0010
    secure = Get-IdleParameter 0x0076
    timeoutSeconds = Get-IdleParameter 0x000E
    registry = [ordered]@{}
}
foreach ($name in @('ScreenSaveActive','ScreenSaverIsSecure','ScreenSaveTimeOut','SCRNSAVE.EXE')) {
    $property = $beforeProperties.PSObject.Properties[$name]
    $before.registry[$name] = @{exists=($null -ne $property);value=$property.Value}
}
$backupPath = Join-Path $PSScriptRoot ('idle-lock-before-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
$before | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $backupPath -Encoding UTF8
$screensaver = $beforeProperties.'SCRNSAVE.EXE'
if ([string]::IsNullOrWhiteSpace($screensaver)) {
    $screensaver = Join-Path $env:SystemRoot 'System32\scrnsave.scr'
    if (-not (Test-Path -LiteralPath $screensaver -PathType Leaf)) { throw 'Windows blank screen saver is missing.' }
    New-ItemProperty -LiteralPath $desktopKey -Name 'SCRNSAVE.EXE' -PropertyType String -Value $screensaver -Force | Out-Null
}
Set-IdleParameter 0x000F 180
Set-IdleParameter 0x0077 1
Set-IdleParameter 0x0011 1
$after = [ordered]@{
    captured = (Get-Date).ToString('o')
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    active = Get-IdleParameter 0x0010
    secure = Get-IdleParameter 0x0076
    timeoutSeconds = Get-IdleParameter 0x000E
    screensaver = (Get-ItemProperty -LiteralPath $desktopKey).'SCRNSAVE.EXE'
    backup = $backupPath
}
if ($after.active -ne 1 -or $after.secure -ne 1 -or $after.timeoutSeconds -ne 180) {
    throw 'The live screen-lock settings did not match the requested values.'
}
$after | ConvertTo-Json | Tee-Object -FilePath (Join-Path $PSScriptRoot 'idle-lock-restored-20261029.json')
