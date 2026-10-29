param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [bool]$VerifySsl = $true,
    [string]$LocalExportRoot = ''
)

$ErrorActionPreference = 'Stop'
$Name = $Name.Trim()
$BaseUrl = $BaseUrl.Trim().TrimEnd('/')
if (-not $Name) { throw 'Název instance nesmí být prázdný.' }
if ($BaseUrl -notmatch '^https?://') { throw 'BaseUrl musí začínat http:// nebo https://.' }

$secureToken = Read-Host "Vložte dlouhodobý Home Assistant token pro $Name (nebude zobrazen)" -AsSecureString
$encryptedToken = ConvertFrom-SecureString $secureToken
$configDir = Join-Path $env:APPDATA 'KosekControlCenter'
$configPath = Join-Path $configDir 'config.json'
New-Item -ItemType Directory -Path $configDir -Force | Out-Null

if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
} else {
    $config = [pscustomobject]@{
        instances = @()
        localBackupRoot = (Join-Path $env:LOCALAPPDATA 'KosekControlCenter\backups')
        localExportRoot = (Join-Path $env:USERPROFILE 'Documents\Codex\Home Assistant')
    }
}

$existing = @($config.instances | Where-Object { ([string]$_.name).ToLowerInvariant() -eq $Name.ToLowerInvariant() })
$newItem = if ($existing.Count) { $existing[0] } else { [pscustomobject]@{} }
foreach ($entry in @{ name = $Name; baseUrl = $BaseUrl; encryptedToken = $encryptedToken; verifySsl = $VerifySsl }.GetEnumerator()) {
    $newItem | Add-Member -MemberType NoteProperty -Name $entry.Key -Value $entry.Value -Force
}
$remaining = @($config.instances | Where-Object { ([string]$_.name).ToLowerInvariant() -ne $Name.ToLowerInvariant() })
$config.instances = @($remaining) + @($newItem)
if ($LocalExportRoot) { $config | Add-Member -MemberType NoteProperty -Name localExportRoot -Value $LocalExportRoot -Force }
$config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8

Write-Host "Instance '$Name' byla bezpečně nastavena v $configPath"
Write-Host 'Token je chráněn Windows DPAPI pro aktuálního uživatele a nebude uložen na OneDrive.'
