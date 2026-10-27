param([Parameter(Mandatory = $true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
try {
    $stored = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    $instances = @(foreach ($item in @($stored.instances)) {
        $secureToken = ConvertTo-SecureString ([string]$item.encryptedToken)
        $credential = [System.Management.Automation.PSCredential]::new('token', $secureToken)
        [ordered]@{
            name = [string]$item.name
            baseUrl = ([string]$item.baseUrl).TrimEnd('/')
            token = $credential.GetNetworkCredential().Password
            verifySsl = if ($null -eq $item.verifySsl) { $true } else { [bool]$item.verifySsl }
            tailscale = $item.tailscale
        }
    })
    $runtime = [ordered]@{
        instances = $instances
        localBackupRoot = $stored.localBackupRoot
        localExportRoot = $stored.localExportRoot
    } | ConvertTo-Json -Depth 8 -Compress
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($runtime)
    $stream = [Console]::OpenStandardOutput()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
} catch {
    # Stdout is a private pipe to the MCP server. Do not run this helper interactively.
    [Console]::Error.WriteLine(('Nacteni sifrovaneho nastaveni selhalo: {0}, radek {1}' -f $_.Exception.GetType().Name, $_.InvocationInfo.ScriptLineNumber))
    exit 1
}
