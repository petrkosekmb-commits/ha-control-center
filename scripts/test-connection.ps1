param([string]$Name = '')

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $env:APPDATA 'KosekControlCenter\config.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Nejdřív spusťte setup-instance.ps1.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$instances = @($config.instances)
if ($Name) { $instances = @($instances | Where-Object { $_.name -eq $Name }) }
if ($instances.Count -eq 0) { throw 'Požadovaná instance nebyla nalezena.' }

foreach ($item in $instances) {
    $secureToken = ConvertTo-SecureString ([string]$item.encryptedToken)
    $credential = [System.Management.Automation.PSCredential]::new('token', $secureToken)
    $headers = @{ Authorization = 'Bearer ' + $credential.GetNetworkCredential().Password }
    $result = Invoke-RestMethod -Uri (([string]$item.baseUrl).TrimEnd('/') + '/api/') -Headers $headers -Method Get -TimeoutSec 30
    Write-Host ("{0}: {1}" -f $item.name, $result.message)
}
