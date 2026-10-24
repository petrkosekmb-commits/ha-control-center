param([switch]$Notify)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'KosekControlCenter\health'
New-Item -ItemType Directory -Path $root -Force | Out-Null
$statusPath = Join-Path $root 'status.json'
$previous = $null
if (Test-Path -LiteralPath $statusPath) {
    try { $previous = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json } catch {}
}
$python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python.exe -ErrorAction Stop).Source }
$env:KCC_CONFIG_PATH = Join-Path $env:APPDATA 'KosekControlCenter\config.json'
$json = & $python -X utf8 (Join-Path $PSScriptRoot 'kosek_control_center_mcp.py') --health-check
$checkExit = $LASTEXITCODE
$status = $json | ConvertFrom-Json
$signature = if ($status.status) { [string]$status.status } else {
    (@($status.checks | ForEach-Object { $_.instance + ':' + $_.status + ':' + $_.token.expiry_state + ':' + $_.token.warning_days }) -join '|')
}
$priorSignature = if ($previous) { [string]$previous.signature } else { '' }
$record = [ordered]@{checkedUtc=[DateTime]::UtcNow.ToString('o'); signature=$signature; result=$status}
$temp = Join-Path $root ('status-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    $record | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $statusPath -Force
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp } }
if ($Notify -and $signature -ne $priorSignature -and ($checkExit -ne 0 -or $previous)) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = New-Object System.Windows.Forms.NotifyIcon
    try {
        $icon.Icon = [System.Drawing.SystemIcons]::Information
        $icon.Visible = $true
        $body = if ($checkExit -eq 0) { 'Pripojeni k Home Assistantu je opet v poradku.' } else { 'Pripojeni vyzaduje pozornost. Otevrete kontrolu connection_health v pluginu.' }
        $icon.ShowBalloonTip(10000, 'HA Control Center', $body, [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Seconds 12
    } finally { $icon.Dispose() }
}
Write-Output ($record | ConvertTo-Json -Depth 10 -Compress)
exit $checkExit
