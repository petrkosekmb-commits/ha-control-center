param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$BaseUrl = '',
    [switch]$Gui
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $env:APPDATA 'KosekControlCenter\config.json'
$temporaryPath = $null
try {
    if (-not (Test-Path -LiteralPath $configPath)) { throw 'Nastaveni konektoru nebylo nalezeno.' }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $instances = @($config.instances | Where-Object name -eq $Name)
    if ($instances.Count -ne 1) { throw 'Pozadovana instance nebyla jednoznacne nalezena.' }
    if (-not $BaseUrl) { $BaseUrl = [string]$instances[0].baseUrl }
    $BaseUrl = $BaseUrl.Trim().TrimEnd('/')
    $parsedUrl = [uri]$BaseUrl
    if ($parsedUrl.Scheme -notin @('http','https') -or -not $parsedUrl.Host -or $parsedUrl.UserInfo -or $parsedUrl.Query -or $parsedUrl.Fragment) {
        throw 'Zadejte adresu Home Assistantu bez prihlasovacich udaju, dotazu a fragmentu.'
    }
    if ($Gui) {
        Add-Type -AssemblyName System.Windows.Forms
        $form = New-Object System.Windows.Forms.Form
        $form.Text = 'HA Control Center - obnova pristupu'
        $form.Width = 580; $form.Height = 210; $form.StartPosition = 'CenterScreen'
        $label = New-Object System.Windows.Forms.Label
        $label.Text = 'Vlozte novy dlouhodoby token. Overi se a ulozi pouze sifrovane v tomto PC.'
        $label.SetBounds(15,15,540,40)
        $inputBox = New-Object System.Windows.Forms.TextBox
        $inputBox.UseSystemPasswordChar = $true
        $inputBox.SetBounds(15,60,530,25)
        $ok = New-Object System.Windows.Forms.Button
        $ok.Text = 'Overit a ulozit'; $ok.SetBounds(290,105,125,30)
        $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $cancel = New-Object System.Windows.Forms.Button
        $cancel.Text = 'Zrusit'; $cancel.SetBounds(430,105,100,30)
        $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $form.Controls.AddRange(@($label,$inputBox,$ok,$cancel))
        $form.AcceptButton=$ok; $form.CancelButton=$cancel
        if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { $form.Dispose(); return }
        $secureToken = ConvertTo-SecureString $inputBox.Text.Trim() -AsPlainText -Force
        $inputBox.Clear(); $form.Dispose()
    } else {
        $secureToken = Read-Host 'Vlozte NOVY dlouhodoby token z Home Assistantu (skryty vstup)' -AsSecureString
    }
    if ($secureToken.Length -eq 0) { throw 'Token je prazdny. Nastaveni nebylo zmeneno.' }
    $credential = [System.Management.Automation.PSCredential]::new('token', $secureToken)
    $headers = @{ Authorization = 'Bearer ' + $credential.GetNetworkCredential().Password }
    try {
        $reply = Invoke-RestMethod -Uri ($BaseUrl + '/api/') -Headers $headers -Method Get -TimeoutSec 15
        if ($reply.message -ne 'API running.') { throw 'Neocekavana odpoved API.' }
        $haInfo = Invoke-RestMethod -Uri ($BaseUrl + '/api/config') -Headers $headers -Method Get -TimeoutSec 15
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
            throw 'Home Assistant novy token odmitl (401). Puvodni nastaveni zustalo zachovano.'
        }
        throw 'Overeni API selhalo. Zkontrolujte adresu a dostupnost HA. Puvodni nastaveni zustalo zachovano.'
    } finally {
        $headers = $null
        $credential = $null
    }
    Write-Host ('Overeno: {0}, verze {1}, adresa {2}' -f $haInfo.location_name, $haInfo.version, $BaseUrl)
    $instance = $instances[0]
    $instance.baseUrl = $BaseUrl
    $instance.encryptedToken = ConvertFrom-SecureString $secureToken
    $instance.verifySsl = $true
    $temporaryPath = Join-Path (Split-Path -Parent $configPath) ('config-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    # Windows PowerShell 5.1 prevede $null pro treti argument na prazdnou cestu.
    # Platna docasna cesta zachova atomickou vymenu i puvodni soubor pri chybe.
    $replacementBackupPath = Join-Path (Split-Path -Parent $configPath) ('config-' + [guid]::NewGuid().ToString('N') + '.bak')
    [System.IO.File]::Replace($temporaryPath, $configPath, $replacementBackupPath)
    $temporaryPath = $null
    Write-Host 'Token byl ulozen sifrovane pomoci Windows DPAPI pro aktualniho uzivatele.'
    try { Remove-Item -LiteralPath $replacementBackupPath -Force } catch {
        Write-Host 'Docasnou sifrovanou zalohu se nepodarilo odstranit. Novy token je ulozen.' -ForegroundColor Yellow
    }
    Write-Host 'Konektor verze 0.1.1 a novejsi token nacte pri dalsim volani bez restartu.'
    if ($Gui) { [System.Windows.Forms.MessageBox]::Show('Pripojeni overeno. Token byl ulozen sifrovane.','HA Control Center') | Out-Null }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($Gui) { [System.Windows.Forms.MessageBox]::Show('Overeni nebo ulozeni selhalo. Puvodni nastaveni zustalo zachovano, pokud vymena jeste neprobehla. Spustte kontrolu pripojeni.','HA Control Center') | Out-Null }
    exit 1
} finally {
    $secureToken = $null
    $config = $null
    if ($temporaryPath -and (Test-Path -LiteralPath $temporaryPath)) { Remove-Item -LiteralPath $temporaryPath -Force }
}
