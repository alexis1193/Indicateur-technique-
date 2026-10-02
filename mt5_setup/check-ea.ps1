#Requires -Version 5.1
<#
.SYNOPSIS
    Etat de l'EA xau_fvg_ea.py en une commande.

.DESCRIPTION
    - Processus Python de l'EA actif ou non, avec son temps de fonctionnement
    - Avertissement si plusieurs processus Python tournent
    - Terminal MT5 (terminal64.exe) actif ou non
    - Fraicheur du fichier de log (alerte au-dela de 20 min)
    - 15 dernieres lignes du log
    - Nombre d'erreurs dans le log complet
    Vert = OK, jaune = avertissement, rouge = bloquant.
    Code de sortie : 0 = OK, 1 = au moins un point bloquant.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\check-ea.ps1
#>
[CmdletBinding()]
param(
    [string]$LogPath = (Join-Path $PSScriptRoot 'xau_fvg_ea.log'),
    [string]$ScriptName = 'xau_fvg_ea.py',
    [int]$MaxLogAgeMinutes = 20,
    [int]$TailLines = 15
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Blocking = 0

function Write-Ok([string]$t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Write-Wrn([string]$t)  { Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Write-Bad([string]$t)  { Write-Host "  [KO]   $t" -ForegroundColor Red; $script:Blocking++ }
function Write-Title([string]$t){ Write-Host ''; Write-Host "=== $t ===" -ForegroundColor Cyan }

function Format-Duration([TimeSpan]$d) {
    if ($d.TotalDays -ge 1) { return ('{0}j {1:00}h{2:00}' -f [int][math]::Floor($d.TotalDays), $d.Hours, $d.Minutes) }
    return ('{0:00}h{1:00}m{2:00}s' -f $d.Hours, $d.Minutes, $d.Seconds)
}

Write-Host ''
Write-Host ("Controle EA XAU FVG - {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor White

# ---------------------------------------------------------------------------
# 1. Processus Python
# ---------------------------------------------------------------------------
Write-Title 'Processus Python'
$allPython = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue)
$eaProcs = @($allPython | Where-Object { $_.CommandLine -and $_.CommandLine -like "*$ScriptName*" })

if ($eaProcs.Count -eq 0) {
    Write-Bad "Aucun processus Python n'execute $ScriptName : l'EA est ARRETE."
} else {
    foreach ($p in $eaProcs) {
        $uptime = (Get-Date) - $p.CreationDate
        Write-Ok ("EA actif : PID {0}, en marche depuis {1} (demarre le {2:yyyy-MM-dd HH:mm})" -f $p.ProcessId, (Format-Duration $uptime), $p.CreationDate)
    }
    if ($eaProcs.Count -gt 1) {
        Write-Bad "$($eaProcs.Count) instances de l'EA tournent en meme temps : arretez-en une."
    }
}
if ($allPython.Count -gt 1) {
    Write-Wrn "$($allPython.Count) processus Python tournent sur cette machine :"
    foreach ($p in $allPython) {
        $cmd = if ($p.CommandLine) { $p.CommandLine } else { '(ligne de commande inaccessible)' }
        if ($cmd.Length -gt 110) { $cmd = $cmd.Substring(0, 107) + '...' }
        Write-Host ("         PID {0,-6} {1}" -f $p.ProcessId, $cmd) -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------------
# 2. Terminal MT5
# ---------------------------------------------------------------------------
Write-Title 'Terminal MetaTrader 5'
$terms = @(Get-Process -Name 'terminal64' -ErrorAction SilentlyContinue)
if ($terms.Count -eq 0) {
    Write-Bad 'terminal64.exe ne tourne pas : l EA ne peut pas trader.'
} else {
    foreach ($t in $terms) {
        $since = ''
        try { $since = ', en marche depuis ' + (Format-Duration ((Get-Date) - $t.StartTime)) } catch { }
        $path = ''
        try { $path = $t.Path } catch { }
        Write-Ok ("Terminal actif : PID {0}{1} {2}" -f $t.Id, $since, $path)
    }
}

# ---------------------------------------------------------------------------
# 3. Fichier de log
# ---------------------------------------------------------------------------
Write-Title 'Log'
if (-not (Test-Path -LiteralPath $LogPath)) {
    Write-Bad "Log introuvable : $LogPath"
} else {
    $item = Get-Item -LiteralPath $LogPath
    $age = (Get-Date) - $item.LastWriteTime
    $ageText = "derniere ecriture il y a {0:N1} min ({1:HH:mm:ss})" -f $age.TotalMinutes, $item.LastWriteTime
    if ($age.TotalMinutes -gt $MaxLogAgeMinutes) {
        Write-Bad "Log PAS a jour : $ageText (seuil $MaxLogAgeMinutes min). EA bloque ou arrete ?"
    } else {
        Write-Ok "Log a jour : $ageText"
    }

    $vivant = Select-String -LiteralPath $LogPath -Pattern '\| VIVANT \|' -SimpleMatch:$false | Select-Object -Last 1
    if ($vivant) { Write-Host ('         Derniere ligne de vie : ' + $vivant.Line.Trim()) -ForegroundColor Gray }

    $errors = @(Select-String -LiteralPath $LogPath -Pattern '\| (ERROR|CRITICAL) +\|')
    $nCrit = @($errors | Where-Object { $_.Line -match '\| CRITICAL' }).Count
    if ($errors.Count -eq 0) {
        Write-Ok 'Aucune erreur dans le log.'
    } elseif ($nCrit -gt 0) {
        Write-Bad "$($errors.Count) erreur(s) dans le log dont $nCrit CRITICAL."
    } else {
        Write-Wrn "$($errors.Count) erreur(s) dans le log (aucune CRITICAL)."
    }
    if ($errors.Count -gt 0) {
        Write-Host ('         Derniere : ' + ($errors[-1].Line.Trim())) -ForegroundColor Gray
    }
    $rotated = @(Get-ChildItem -Path ($LogPath + '.*') -ErrorAction SilentlyContinue)
    if ($rotated.Count -gt 0) {
        Write-Host "         ($($rotated.Count) ancien(s) fichier(s) de log archive(s) non compte(s))" -ForegroundColor Gray
    }

    Write-Title "$TailLines dernieres lignes du log"
    foreach ($line in @(Get-Content -LiteralPath $LogPath -Tail $TailLines)) {
        $color = 'Gray'
        if ($line -match '\| (ERROR|CRITICAL) ') { $color = 'Red' }
        elseif ($line -match '\| WARNING ') { $color = 'Yellow' }
        elseif ($line -match '\| VIVANT \|') { $color = 'Green' }
        Write-Host "  $line" -ForegroundColor $color
    }
}

# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------
Write-Host ''
if ($script:Blocking -eq 0) {
    Write-Host '  ETAT : OK' -ForegroundColor Green
    exit 0
}
Write-Host "  ETAT : $($script:Blocking) point(s) bloquant(s)" -ForegroundColor Red
exit 1
