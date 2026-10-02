# install_all.ps1 - Installation complete en une commande (Windows PowerShell 5.1)
#
# Lancement (Windows + R, coller, Entree) :
#   powershell -NoExit -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; irm https://raw.githubusercontent.com/alexis1193/Indicateur-technique-/mt5-setup/mt5_setup/install_all.ps1 | iex"
#
# 1. Cree C:\mt5_bot et y telecharge tous les scripts du projet
# 2. Installe MetaTrader 5 (installeur officiel MetaQuotes) s'il est absent
# 3. Installe Python 3.10 + librairies (setup_mt5_python.ps1) et teste MT5
# 4. Lance l'audit du compte (mt5_check.py)
# Relancable sans risque. N'envoie aucun ordre de trading.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$BotDir  = 'C:\mt5_bot'
$RawBase = 'https://raw.githubusercontent.com/alexis1193/Indicateur-technique-/mt5-setup/mt5_setup'
$Files   = @('setup_mt5_python.ps1', 'setup_mt5_python.bat', 'mt5_check.py', 'xau_fvg_ea.py', 'check-ea.ps1')
$Mt5Url  = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'

function Step([string]$t) { Write-Host ''; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Ok([string]$t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Inf([string]$t)  { Write-Host "  [..]   $t" -ForegroundColor Gray }
function Bad([string]$t)  { Write-Host "  [ERR]  $t" -ForegroundColor Red }

function Find-Terminal {
    $c = @()
    $data = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if (Test-Path $data) {
        foreach ($o in @(Get-ChildItem -Path $data -Filter origin.txt -Recurse -Depth 1 -ErrorAction SilentlyContinue)) {
            try { $c += Join-Path ((Get-Content -LiteralPath $o.FullName -TotalCount 1).Trim()) 'terminal64.exe' } catch { }
        }
    }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($root -and (Test-Path $root)) {
            foreach ($d in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
                $c += Join-Path $d.FullName 'terminal64.exe'
            }
        }
    }
    return @($c | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -Unique)
}

function Wait-Enter([string]$msg) {
    Write-Host ''
    Write-Host $msg -ForegroundColor Yellow
    [void](Read-Host 'Appuie sur Entree pour continuer')
}

function Install-All {
Write-Host ''
Write-Host 'INSTALLATION COMPLETE MT5 + PYTHON + BOT' -ForegroundColor White

# ---------------------------------------------------------------------------
Step '1/4 Telechargement des scripts dans C:\mt5_bot'
New-Item -ItemType Directory -Path $BotDir -Force | Out-Null
foreach ($f in $Files) {
    $dest = Join-Path $BotDir $f
    try {
        Invoke-WebRequest -Uri "$RawBase/$f" -OutFile $dest -UseBasicParsing
        Ok $f
    } catch {
        Bad "$f : $_"
        Bad 'Verifie ta connexion internet puis relance la commande.'
        return
    }
}

# ---------------------------------------------------------------------------
Step '2/4 MetaTrader 5'
$terms = @(Find-Terminal)
if ($terms.Count -gt 0) {
    Ok "Deja installe : $($terms[0])"
} else {
    Inf 'MetaTrader 5 absent : telechargement de l installeur officiel MetaQuotes...'
    $setup = Join-Path $env:TEMP 'mt5setup.exe'
    Invoke-WebRequest -Uri $Mt5Url -OutFile $setup -UseBasicParsing
    $sig = Get-AuthenticodeSignature -FilePath $setup
    if ($sig.Status -ne 'Valid') {
        Bad "Signature de l installeur MT5 invalide ($($sig.Status)). Arret par securite."
        Remove-Item $setup -Force -ErrorAction SilentlyContinue
        return
    }
    Ok "Installeur signe : $($sig.SignerCertificate.Subject)"
    Inf 'Une fenetre d installation va s ouvrir : clique sur Suivant / Next jusqu a la fin.'
    Start-Process -FilePath $setup -Wait
    $terms = @(Find-Terminal)
    if ($terms.Count -eq 0) {
        Wait-Enter 'Attends que l installation soit terminee et que MetaTrader 5 soit ouvert.'
        $terms = @(Find-Terminal)
    }
    if ($terms.Count -eq 0) {
        Bad 'MetaTrader 5 toujours introuvable. Relance cette commande apres l installation.'
        return
    }
    Ok "Installe : $($terms[0])"
}

Wait-Enter @'
Dans MetaTrader 5 (ouvre-le s il est ferme) :
  1. Si aucun compte n est connecte : Fichier > Ouvrir un compte > MetaQuotes-Demo
     (ou le serveur DEMO de ton broker) > compte demo, remplis le formulaire.
  2. Verifie en bas a droite que la connexion affiche des Ko/s (pas "Pas de connexion").
  3. Clique sur le bouton "Algo Trading" en haut (il doit etre vert).
  4. Laisse MetaTrader 5 OUVERT.
'@

# ---------------------------------------------------------------------------
Step '3/4 Python 3.10 + librairies + test MT5'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $BotDir 'setup_mt5_python.ps1') -TestMT5
if ($LASTEXITCODE -ne 0) {
    Bad "Le setup Python signale un point bloquant (code $LASTEXITCODE). Lis le resume au-dessus."
    Bad "Journal : $BotDir\setup_mt5_python.log  -> envoie-le a Claude."
    return
}

# ---------------------------------------------------------------------------
Step '4/4 Audit du compte'
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
Push-Location $BotDir
try { & $py mt5_check.py } finally { Pop-Location }

Write-Host ''
Write-Host 'TERMINE.' -ForegroundColor Green
Write-Host "Tout est dans $BotDir" -ForegroundColor Green
Write-Host 'Pour lancer le bot en SIMULATION (aucun ordre reel) :' -ForegroundColor White
Write-Host "  cd $BotDir; & '$py' xau_fvg_ea.py" -ForegroundColor White
Write-Host 'Pour verifier qu il tourne :' -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File $BotDir\check-ea.ps1" -ForegroundColor White
}

Install-All
