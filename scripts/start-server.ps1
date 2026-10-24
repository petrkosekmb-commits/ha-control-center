$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$configPath = Join-Path $env:APPDATA 'KosekControlCenter\config.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw 'HA Control Center není nastaven. Spusťte scripts\setup-instance.ps1.'
}

$env:KCC_CONFIG_PATH = $configPath

$candidates = @(
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
    'python.exe',
    'py.exe'
)
$python = $null
foreach ($candidate in $candidates) {
    if ([System.IO.Path]::IsPathRooted($candidate)) {
        if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
    } else {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { $python = $command.Source; break }
    }
}
if (-not $python) { throw 'Python nebyl nalezen.' }

try {
    & $python -X utf8 (Join-Path $PSScriptRoot 'kosek_control_center_mcp.py')
} finally {
    Remove-Item Env:KCC_CONFIG_PATH -ErrorAction SilentlyContinue
}
