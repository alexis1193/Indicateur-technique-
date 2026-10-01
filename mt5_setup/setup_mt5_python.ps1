#Requires -Version 5.1
<#
.SYNOPSIS
    Prepare un environnement Python 3.10 64-bit pour l'API MetaTrader5.

.DESCRIPTION
    Script relancable sans risque (idempotent) :
      1. Detecte le terminal MT5 (terminal64.exe) via le registre et le disque.
         N'installe PAS MT5. S'il est absent, tout s'arrete avant les installs.
      2. Verifie Python 3.10 64-bit. Absent -> installation silencieuse en
         profil utilisateur (sans droits admin). Le 32-bit est refuse.
      3. Verifie pip. Casse -> reparation via ensurepip, puis mise a jour.
      4. Verifie / installe MetaTrader5, numpy, pandas, scipy, pytz.
      5. Affiche un resume final avec les points bloquants.

.PARAMETER CheckOnly
    Audit seul : n'installe et ne modifie rien.

.PARAMETER TestMT5
    Teste la connexion au terminal MT5 et au symbole (XAUUSD par defaut).

.PARAMETER Symbol
    Symbole a tester avec -TestMT5 (defaut : XAUUSD).

.EXAMPLE
    .\setup_mt5_python.ps1
    .\setup_mt5_python.ps1 -CheckOnly
    .\setup_mt5_python.ps1 -TestMT5
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$TestMT5,
    [string]$Symbol = 'XAUUSD'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$PY_VERSION   = '3.10.11'   # derniere version 3.10 avec installeur Windows officiel
$PY_URL       = "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-amd64.exe"
$PY_USER_DIR  = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310'
$PACKAGES     = @('MetaTrader5', 'numpy', 'pandas', 'scipy', 'pytz')
$LOG_FILE     = Join-Path $PSScriptRoot 'setup_mt5_python.log'

$script:Results = New-Object System.Collections.Generic.List[object]
$script:Advice  = New-Object System.Collections.Generic.List[string]

# ---------------------------------------------------------------------------
# Helpers d'affichage
# ---------------------------------------------------------------------------
function Write-Step([string]$Text) { Write-Host ''; Write-Host "=== $Text ===" -ForegroundColor Cyan }
function Write-Ok([string]$Text)   { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Inf([string]$Text)  { Write-Host "  [..]   $Text" -ForegroundColor Gray }
function Write-Wrn([string]$Text)  { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Err([string]$Text)  { Write-Host "  [ERR]  $Text" -ForegroundColor Red }

function Add-Result {
    param(
        [string]$Item,
        [ValidateSet('OK', 'INFO', 'WARN', 'A FAIRE', 'BLOQUANT')][string]$Status,
        [string]$Detail
    )
    $script:Results.Add([pscustomobject]@{ Element = $Item; Statut = $Status; Detail = $Detail })
}

function Get-PropValue($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

# ---------------------------------------------------------------------------
# Execution de programmes externes (stderr capture sans faire planter PS 5.1)
# ---------------------------------------------------------------------------
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments = @())
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out  = @()
    $code = -1
    try {
        $out  = @(& $Exe @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    } catch {
        $out  = @("$_")
        $code = -1
    } finally {
        $ErrorActionPreference = $old
    }
    return [pscustomobject]@{ ExitCode = $code; Output = ($out -join "`n") }
}

function Invoke-PyCode {
    param([string]$Python, [string]$Code, [string[]]$ScriptArgs = @())
    $f = Join-Path $env:TEMP ('mt5setup_' + [guid]::NewGuid().ToString('N') + '.py')
    Set-Content -LiteralPath $f -Value $Code -Encoding Ascii
    try {
        return Invoke-Native -Exe $Python -Arguments (@($f) + $ScriptArgs)
    } finally {
        Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    }
}

function Get-LastLines([string]$Text, [int]$Count = 15) {
    $lines = @($Text -split "`r?`n" | Where-Object { $_.Trim() -ne '' })
    if ($lines.Count -le $Count) { return ($lines -join "`n") }
    return (($lines | Select-Object -Last $Count) -join "`n")
}

# ---------------------------------------------------------------------------
# 1. Detection du terminal MetaTrader 5
# ---------------------------------------------------------------------------
function Get-DirFromRegValue([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    $s = $Value.Trim()
    if ($s.StartsWith('"')) {
        $s = $s.Substring(1)
        $i = $s.IndexOf('"')
        if ($i -ge 0) { $s = $s.Substring(0, $i) }
    } else {
        $s = $s -replace ',\s*-?\d+$', ''
        $i = $s.IndexOf('.exe', [StringComparison]::OrdinalIgnoreCase)
        if ($i -ge 0) { $s = $s.Substring(0, $i + 4) }
    }
    if ($s -match '\.exe$') { $s = Split-Path -Path $s -Parent }
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    return $s.TrimEnd('\')
}

function Find-MT5Terminal {
    $candidates = New-Object System.Collections.Generic.List[string]
    $launched   = New-Object System.Collections.Generic.List[string]

    # a) Registre : cles de desinstallation
    $uninstallKeys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($k in $uninstallKeys) {
        $items = @(Get-ItemProperty -Path $k -ErrorAction SilentlyContinue)
        foreach ($it in $items) {
            $name = [string](Get-PropValue $it 'DisplayName')
            $pub  = [string](Get-PropValue $it 'Publisher')
            if ($name -match 'MetaTrader 5|MT5' -or $pub -match 'MetaQuotes') {
                foreach ($prop in @('InstallLocation', 'DisplayIcon', 'UninstallString')) {
                    $dir = Get-DirFromRegValue ([string](Get-PropValue $it $prop))
                    if ($dir) { $candidates.Add((Join-Path $dir 'terminal64.exe')) }
                }
            }
        }
    }

    # b) Dossiers de donnees : origin.txt = terminal deja lance au moins une fois
    $dataRoot = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if (Test-Path -LiteralPath $dataRoot) {
        foreach ($d in @(Get-ChildItem -LiteralPath $dataRoot -Directory -ErrorAction SilentlyContinue)) {
            $origin = Join-Path $d.FullName 'origin.txt'
            if (Test-Path -LiteralPath $origin) {
                try {
                    $o = [string](Get-Content -LiteralPath $origin -TotalCount 1 -ErrorAction Stop)
                    $o = $o.Trim().TrimEnd('\')
                    if ($o) {
                        $launched.Add($o)
                        $candidates.Add((Join-Path $o 'terminal64.exe'))
                    }
                } catch { }
            }
        }
    }

    # c) Disque : sous-dossiers de premier niveau des emplacements usuels
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs'), ($env:SystemDrive + '\'))
    foreach ($r in $roots) {
        if ([string]::IsNullOrWhiteSpace($r) -or -not (Test-Path -LiteralPath $r)) { continue }
        foreach ($d in @(Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue)) {
            $candidates.Add((Join-Path $d.FullName 'terminal64.exe'))
        }
    }

    # Dedoublonnage + verification d'existence
    $seen   = @{}
    $result = New-Object System.Collections.Generic.List[object]
    foreach ($c in $candidates) {
        $key = $c.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            $dir = (Split-Path -Path $c -Parent).TrimEnd('\')
            $wasLaunched = $false
            foreach ($l in $launched) { if ($l -ieq $dir) { $wasLaunched = $true } }
            $result.Add([pscustomobject]@{ Path = $c; Launched = $wasLaunched })
        }
    }
    # Les terminaux deja lances en premier
    return @($result | Sort-Object -Property @{ Expression = 'Launched'; Descending = $true }, 'Path')
}

# ---------------------------------------------------------------------------
# 2. Detection de Python 3.10 64-bit
# ---------------------------------------------------------------------------
$PY_PROBE = @'
import sys, struct
print('%d.%d.%d|%d|%s' % (sys.version_info[0], sys.version_info[1], sys.version_info[2], struct.calcsize('P') * 8, sys.executable))
'@

function Get-PythonInfo([string]$Exe) {
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $null }
    $r = Invoke-PyCode -Python $Exe -Code $PY_PROBE
    if ($r.ExitCode -ne 0) { return $null }
    $line = @($r.Output -split "`r?`n" | Where-Object { $_ -match '^\d+\.\d+\.\d+\|\d+\|' }) | Select-Object -Last 1
    if (-not $line) { return $null }
    $parts = $line.Split('|')
    return [pscustomobject]@{ Version = $parts[0]; Bits = [int]$parts[1]; Path = $parts[2].Trim() }
}

function Find-Python310x64 {
    $cands = New-Object System.Collections.Generic.List[string]

    # a) Lanceur py
    $r = Invoke-Native -Exe 'py' -Arguments @('-3.10-64', '-c', 'import sys;print(sys.executable)')
    if ($r.ExitCode -eq 0) {
        $p = @($r.Output -split "`r?`n" | Where-Object { $_ -match 'python.*\.exe$' }) | Select-Object -Last 1
        if ($p) { $cands.Add($p.Trim()) }
    }

    # b) Registre PEP 514
    foreach ($hive in @('HKCU:\SOFTWARE', 'HKLM:\SOFTWARE', 'HKLM:\SOFTWARE\WOW6432Node')) {
        foreach ($tag in @('3.10', '3.10-32')) {
            $ip = Get-ItemProperty -LiteralPath "$hive\Python\PythonCore\$tag\InstallPath" -ErrorAction SilentlyContinue
            if ($ip) {
                $exe = [string](Get-PropValue $ip 'ExecutablePath')
                if (-not $exe) {
                    $d = [string](Get-PropValue $ip '(default)')
                    if ($d) { $exe = Join-Path $d 'python.exe' }
                }
                if ($exe) { $cands.Add($exe) }
            }
        }
    }

    # c) Emplacements par defaut
    $cands.Add((Join-Path $PY_USER_DIR 'python.exe'))
    if ($env:ProgramFiles) { $cands.Add((Join-Path $env:ProgramFiles 'Python310\python.exe')) }
    $cands.Add(($env:SystemDrive + '\Python310\python.exe'))

    # d) PATH (on ignore l'alias Microsoft Store)
    foreach ($c in @(Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue)) {
        if ($c.Source -notlike '*\WindowsApps\*') { $cands.Add($c.Source) }
    }

    $seen  = @{}
    $found = $null
    foreach ($c in $cands) {
        $key = $c.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $info = Get-PythonInfo $c
        if ($null -eq $info) { continue }
        if ($info.Version -like '3.10.*') {
            if ($info.Bits -eq 64) {
                if ($null -eq $found) { $found = $info }
            } else {
                Write-Wrn "Python $($info.Version) 32-bit refuse : $($info.Path)"
                if (-not @($script:Results | Where-Object { $_.Detail -like "*$($info.Path)" })) { Add-Result 'Python 32-bit' 'WARN' "Ignore (MT5 exige du 64-bit) : $($info.Path)" }
            }
        } else {
            Write-Inf "Autre Python ignore : $($info.Version) $($info.Bits)-bit ($($info.Path))"
        }
    }
    return $found
}

function Install-Python310 {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    $installer = Join-Path $env:TEMP "python-$PY_VERSION-amd64.exe"
    if ((Test-Path -LiteralPath $installer) -and ((Get-Item -LiteralPath $installer).Length -lt 20MB)) {
        Remove-Item -LiteralPath $installer -Force
    }
    if (-not (Test-Path -LiteralPath $installer)) {
        Write-Inf "Telechargement de $PY_URL"
        Invoke-WebRequest -Uri $PY_URL -OutFile $installer -UseBasicParsing
    } else {
        Write-Inf "Installeur deja present : $installer"
    }

    $sig = Get-AuthenticodeSignature -FilePath $installer
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        throw "Signature de l'installeur invalide ($($sig.Status)). Fichier supprime, relancez le script."
    }
    Write-Ok 'Signature de l installeur valide (Python Software Foundation)'

    # Installation profil utilisateur, sans admin, sans le lanceur py (qui peut exiger l'admin)
    $installArgs = @(
        '/quiet',
        'InstallAllUsers=0',
        'PrependPath=1',
        'Include_launcher=0',
        'Include_test=0',
        'Include_doc=0',
        'Include_pip=1',
        'Shortcuts=0'
    )
    Write-Inf 'Installation silencieuse en cours (1 a 3 minutes)...'
    $p = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        throw "L'installeur Python a echoue (code $($p.ExitCode)). Journaux : $env:TEMP\Python 3.10*.log"
    }

    # Rafraichir le PATH de la session courante
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

# ---------------------------------------------------------------------------
# 3. pip
# ---------------------------------------------------------------------------
$SITE_PROBE = @'
import os, sysconfig, tempfile
p = sysconfig.get_paths()['purelib']
try:
    fd, n = tempfile.mkstemp(dir=p)
    os.close(fd)
    os.remove(n)
    w = 1
except Exception:
    w = 0
print('W|%d|%s' % (w, p))
'@

function Test-SiteWritable([string]$Python) {
    $r = Invoke-PyCode -Python $Python -Code $SITE_PROBE
    return ($r.Output -match 'W\|1\|')
}

function Test-Pip([string]$Python) {
    $r = Invoke-Native -Exe $Python -Arguments @('-m', 'pip', '--version', '--disable-pip-version-check')
    if ($r.ExitCode -eq 0 -and $r.Output -match 'pip\s+(\S+)') { return $Matches[1] }
    return $null
}

# ---------------------------------------------------------------------------
# 4. Paquets
# ---------------------------------------------------------------------------
$PKG_PROBE = @'
import importlib
try:
    from importlib import metadata as md
except ImportError:
    md = None
for dist in ['MetaTrader5', 'numpy', 'pandas', 'scipy', 'pytz']:
    ver = ''
    try:
        ver = md.version(dist)
    except Exception:
        pass
    try:
        importlib.import_module(dist)
        state, err = 'OK', ''
    except Exception as e:
        state = 'BROKEN' if ver else 'MISSING'
        err = str(e).replace('|', '/').replace('\n', ' ')[:200]
    print('PKG|%s|%s|%s|%s' % (dist, state, ver, err))
'@

function Get-PackageState([string]$Python) {
    $r = Invoke-PyCode -Python $Python -Code $PKG_PROBE
    $list = @()
    foreach ($line in ($r.Output -split "`r?`n")) {
        if ($line -match '^PKG\|') {
            $p = $line.Split('|')
            $list += [pscustomobject]@{ Name = $p[1]; State = $p[2]; Version = $p[3]; Error = ($p[4..($p.Count - 1)] -join '|') }
        }
    }
    return $list
}

# ---------------------------------------------------------------------------
# 5. Test de connexion MT5
# ---------------------------------------------------------------------------
$MT5_TEST = @'
import sys, time
import MetaTrader5 as mt5

path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != '-' else None
sym = sys.argv[2] if len(sys.argv) > 2 else 'XAUUSD'

ok = mt5.initialize(path, timeout=60000) if path else mt5.initialize(timeout=60000)
if not ok:
    print('ERR|initialize() a echoue : %s' % (mt5.last_error(),))
    sys.exit(2)

try:
    ti = mt5.terminal_info()
    ver = mt5.version()
    print('INFO|Terminal : %s (build %s) connecte=%s algo_trading=%s' % (ti.name, ver[1] if ver else '?', ti.connected, ti.trade_allowed))
    ai = mt5.account_info()
    if ai is None:
        print('WARN|Aucun compte connecte dans le terminal (connectez-vous a votre compte broker).')
    else:
        print('INFO|Compte : %s sur %s (%s)' % (ai.login, ai.server, ai.currency))

    name = sym
    info = mt5.symbol_info(name)
    if info is None:
        alts = [s.name for s in (mt5.symbols_get('*XAU*') or [])] + [s.name for s in (mt5.symbols_get('*GOLD*') or [])]
        if alts:
            print('WARN|Symbole %s introuvable. Variantes chez ce broker : %s' % (sym, ', '.join(alts[:10])))
            name = alts[0]
            info = mt5.symbol_info(name)
        if info is None:
            print('ERR|Aucun symbole or (XAU/GOLD) disponible chez ce broker.')
            sys.exit(3)

    if not mt5.symbol_select(name, True):
        print('ERR|symbol_select(%s) a echoue : %s' % (name, mt5.last_error()))
        sys.exit(3)
    time.sleep(1)
    tick = mt5.symbol_info_tick(name)
    if tick is None or (tick.bid == 0 and tick.ask == 0):
        print('WARN|Pas de cotation pour %s (marche ferme ou compte non connecte).' % name)
    else:
        print('OK|%s bid=%s ask=%s heure_serveur=%s' % (name, tick.bid, tick.ask, time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(tick.time))))
    sys.exit(0)
finally:
    mt5.shutdown()
'@

# ---------------------------------------------------------------------------
# Resume final
# ---------------------------------------------------------------------------
function Show-Summary {
    Write-Step 'RESUME'
    foreach ($r in $script:Results) {
        $color = switch ($r.Statut) {
            'OK'       { 'Green' }
            'INFO'     { 'Gray' }
            'WARN'     { 'Yellow' }
            'A FAIRE'  { 'Yellow' }
            'BLOQUANT' { 'Red' }
        }
        Write-Host ('  {0,-9} {1,-22} {2}' -f $r.Statut, $r.Element, $r.Detail) -ForegroundColor $color
    }

    $blockers = @($script:Results | Where-Object { $_.Statut -eq 'BLOQUANT' })
    Write-Host ''
    if ($blockers.Count -eq 0) {
        if ($CheckOnly -and @($script:Results | Where-Object { $_.Statut -eq 'A FAIRE' }).Count -gt 0) {
            Write-Host '  Audit termine : des actions sont a faire. Relancez sans -CheckOnly.' -ForegroundColor Yellow
        } else {
            Write-Host '  Aucun point bloquant. Environnement pret.' -ForegroundColor Green
        }
    } else {
        Write-Host "  $($blockers.Count) point(s) bloquant(s) :" -ForegroundColor Red
        foreach ($b in $blockers) { Write-Host "   - $($b.Element) : $($b.Detail)" -ForegroundColor Red }
    }
    if ($script:Advice.Count -gt 0) {
        Write-Host ''
        Write-Host '  A faire :' -ForegroundColor Yellow
        foreach ($a in $script:Advice) { Write-Host "   $a" -ForegroundColor Yellow }
    }
    Write-Host ''
    Write-Host "  Journal complet : $LOG_FILE" -ForegroundColor Gray
}

# ===========================================================================
# PROGRAMME PRINCIPAL
# ===========================================================================
$script:ExitCode = 0

function Invoke-Main {
    $mode = if ($CheckOnly) { 'AUDIT SEUL (-CheckOnly)' } else { 'INSTALLATION' }
    Write-Host ''
    Write-Host "Preparation Python pour MetaTrader5 - mode : $mode" -ForegroundColor White
    Write-Host ("Date : {0}   Utilisateur : {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $env:USERNAME) -ForegroundColor Gray

    if (-not [Environment]::Is64BitOperatingSystem) {
        Write-Err 'Windows 32-bit detecte. MetaTrader5 pour Python exige Windows 64-bit.'
        Add-Result 'Windows' 'BLOQUANT' 'Systeme 32-bit non supporte'
        $script:ExitCode = 1
        return
    }

    # ---- Etape MT5 (avant toute installation) -----------------------------
    Write-Step '1/4 Terminal MetaTrader 5'
    $terminals = @(Find-MT5Terminal)
    $mt5Path = $null
    if ($terminals.Count -eq 0) {
        Write-Err 'terminal64.exe introuvable (registre + disque).'
        Add-Result 'Terminal MT5' 'BLOQUANT' 'terminal64.exe introuvable'
        $script:Advice.Add('Ce script n installe PAS MetaTrader 5. Pour continuer :')
        $script:Advice.Add('  1. Telechargez le terminal MT5 depuis le site de VOTRE broker.')
        $script:Advice.Add('  2. Installez-le (options par defaut).')
        $script:Advice.Add('  3. Lancez-le une fois et connectez-vous a votre compte (demo ou reel).')
        $script:Advice.Add('  4. Fermez-le puis relancez ce script.')
        if (-not $CheckOnly) {
            Write-Err 'Arret avant toute installation.'
            $script:ExitCode = 2
            return
        }
    } else {
        foreach ($t in $terminals) {
            $tag = if ($t.Launched) { 'deja lance' } else { 'jamais lance (ou mode portable)' }
            Write-Ok "$($t.Path) [$tag]"
        }
        $mt5Path = $terminals[0].Path
        if ($terminals[0].Launched) {
            Add-Result 'Terminal MT5' 'OK' $mt5Path
        } else {
            Add-Result 'Terminal MT5' 'WARN' "$mt5Path (jamais lance ?)"
            $script:Advice.Add('Lancez le terminal MT5 une fois et connectez-vous a votre compte.')
        }
        if ($terminals.Count -gt 1) {
            Add-Result 'Terminaux MT5' 'INFO' "$($terminals.Count) terminaux trouves, utilise : $mt5Path"
        }
    }

    # ---- Etape Python ---------------------------------------------------------
    Write-Step '2/4 Python 3.10 64-bit'
    $py = Find-Python310x64
    if ($null -eq $py) {
        if ($CheckOnly) {
            Write-Wrn 'Python 3.10 64-bit absent.'
            Add-Result 'Python 3.10 x64' 'A FAIRE' 'Absent (sera installe sans -CheckOnly)'
        } else {
            Write-Inf "Python 3.10 64-bit absent : installation de $PY_VERSION en profil utilisateur."
            try {
                Install-Python310
                $py = Find-Python310x64
            } catch {
                Write-Err "$_"
            }
            if ($null -eq $py) {
                Add-Result 'Python 3.10 x64' 'BLOQUANT' 'Installation echouee'
                $script:Advice.Add("Installez manuellement $PY_URL (cochez 'Add python.exe to PATH').")
                $script:ExitCode = 1
                return
            }
            Write-Ok "Python $($py.Version) installe : $($py.Path)"
            Add-Result 'Python 3.10 x64' 'OK' "$($py.Version) installe : $($py.Path)"
        }
    } else {
        Write-Ok "Python $($py.Version) 64-bit : $($py.Path)"
        Add-Result 'Python 3.10 x64' 'OK' "$($py.Version) : $($py.Path)"
    }

    if ($null -eq $py) {
        Add-Result 'pip' 'INFO' 'Non verifie (Python absent)'
        Add-Result 'Paquets' 'INFO' 'Non verifies (Python absent)'
        return
    }
    $pyExe = $py.Path

    # ---- Etape pip ------------------------------------------------------------
    Write-Step '3/4 pip'
    $userFlag = @()
    if (-not (Test-SiteWritable $pyExe)) {
        $userFlag = @('--user')
        Write-Inf 'site-packages non inscriptible : installation des paquets en --user.'
    }
    $pipCommon = @('--disable-pip-version-check', '--no-warn-script-location')

    $pipVer = Test-Pip $pyExe
    if (-not $pipVer) {
        if ($CheckOnly) {
            Write-Wrn 'pip absent ou casse.'
            Add-Result 'pip' 'A FAIRE' 'Absent/casse (sera repare sans -CheckOnly)'
        } else {
            Write-Wrn 'pip absent ou casse : reparation via ensurepip.'
            $r = Invoke-Native -Exe $pyExe -Arguments (@('-m', 'ensurepip', '--upgrade', '--default-pip') + $userFlag)
            if ($r.ExitCode -ne 0) { Write-Err (Get-LastLines $r.Output) }
            $pipVer = Test-Pip $pyExe
            if (-not $pipVer) {
                Add-Result 'pip' 'BLOQUANT' 'Reparation ensurepip echouee'
                $script:Advice.Add('Reinstallez Python 3.10 (option Repair dans Parametres > Applications).')
                $script:ExitCode = 1
                return
            }
            Write-Ok "pip repare ($pipVer)"
        }
    }
    if ($pipVer) {
        if (-not $CheckOnly) {
            $r = Invoke-Native -Exe $pyExe -Arguments (@('-m', 'pip', 'install', '--upgrade', 'pip') + $pipCommon + $userFlag)
            if ($r.ExitCode -ne 0) {
                Write-Wrn "Mise a jour de pip echouee (on continue avec $pipVer)."
                Write-Inf (Get-LastLines $r.Output 5)
            }
            $pipVer = Test-Pip $pyExe
        }
        Write-Ok "pip $pipVer"
        Add-Result 'pip' 'OK' $pipVer
    }

    # ---- Etape paquets --------------------------------------------------------
    Write-Step '4/4 Paquets Python'
    $state   = @(Get-PackageState $pyExe)
    $missing = @($state | Where-Object { $_.State -eq 'MISSING' } | ForEach-Object { $_.Name })
    $broken  = @($state | Where-Object { $_.State -eq 'BROKEN' }  | ForEach-Object { $_.Name })

    if (-not $CheckOnly -and $pipVer) {
        if ($missing.Count -gt 0) {
            Write-Inf ("Installation : " + ($missing -join ', '))
            $r = Invoke-Native -Exe $pyExe -Arguments (@('-m', 'pip', 'install') + $missing + $pipCommon + $userFlag)
            if ($r.ExitCode -ne 0) { Write-Err (Get-LastLines $r.Output) }
        }
        if ($broken.Count -gt 0) {
            Write-Inf ("Reinstallation (import en echec) : " + ($broken -join ', '))
            $r = Invoke-Native -Exe $pyExe -Arguments (@('-m', 'pip', 'install', '--force-reinstall') + $broken + $pipCommon + $userFlag)
            if ($r.ExitCode -ne 0) { Write-Err (Get-LastLines $r.Output) }
        }
        if ($missing.Count -gt 0 -or $broken.Count -gt 0) { $state = @(Get-PackageState $pyExe) }
    }

    $pkgBlocked = $false
    foreach ($name in $PACKAGES) {
        $s = $state | Where-Object { $_.Name -eq $name } | Select-Object -First 1
        if ($null -eq $s) {
            Write-Err "$name : etat inconnu"
            Add-Result $name 'BLOQUANT' 'Verification impossible'
            $pkgBlocked = $true
        } elseif ($s.State -eq 'OK') {
            Write-Ok ("{0,-12} {1}" -f $name, $s.Version)
            Add-Result $name 'OK' $s.Version
        } elseif ($CheckOnly) {
            Write-Wrn "$name : $($s.State) $($s.Error)"
            Add-Result $name 'A FAIRE' "$($s.State) (sera installe sans -CheckOnly)"
        } else {
            Write-Err "$name : $($s.State) $($s.Error)"
            Add-Result $name 'BLOQUANT' "$($s.State) : $($s.Error)"
            $pkgBlocked = $true
        }
    }
    if ($pkgBlocked) {
        $script:Advice.Add('Consultez les erreurs pip ci-dessus (connexion internet, proxy, antivirus).')
        $script:ExitCode = 1
    }

    # ---- Test MT5 -------------------------------------------------------------
    if ($TestMT5) {
        Write-Step "Test de connexion MT5 ($Symbol)"
        $mt5Ok = $state | Where-Object { $_.Name -eq 'MetaTrader5' -and $_.State -eq 'OK' }
        if (-not $mt5Ok) {
            Add-Result 'Test MT5' 'BLOQUANT' 'Module MetaTrader5 non importable'
            $script:ExitCode = 1
        } else {
            $argPath = if ($mt5Path) { $mt5Path } else { '-' }
            Write-Inf 'Connexion au terminal (il peut s ouvrir, jusqu a 60 s)...'
            $r = Invoke-PyCode -Python $pyExe -Code $MT5_TEST -ScriptArgs @($argPath, $Symbol)
            foreach ($line in ($r.Output -split "`r?`n")) {
                if     ($line -match '^OK\|(.*)')   { Write-Ok $Matches[1] }
                elseif ($line -match '^INFO\|(.*)') { Write-Inf $Matches[1] }
                elseif ($line -match '^WARN\|(.*)') { Write-Wrn $Matches[1]; Add-Result 'Test MT5' 'WARN' $Matches[1] }
                elseif ($line -match '^ERR\|(.*)')  { Write-Err $Matches[1] }
                elseif ($line.Trim() -ne '')        { Write-Inf $line }
            }
            if ($r.ExitCode -eq 0) {
                Add-Result 'Test MT5' 'OK' "Connexion + symbole $Symbol"
            } else {
                $detail = switch ($r.ExitCode) { 2 { 'initialize() en echec' } 3 { "Symbole $Symbol indisponible" } default { "Erreur (code $($r.ExitCode))" } }
                Add-Result 'Test MT5' 'BLOQUANT' $detail
                $script:Advice.Add('Ouvrez le terminal MT5, connectez-vous, et activez Outils > Options > Expert Advisors > Autoriser le trading algorithmique.')
                if ($script:ExitCode -eq 0) { $script:ExitCode = 1 }
            }
        }
    }
}
$transcript = $false
try { Start-Transcript -LiteralPath $LOG_FILE -Force | Out-Null; $transcript = $true } catch { }
try {
    Invoke-Main
}
catch {
    Write-Err "Erreur inattendue : $_"
    Add-Result 'Script' 'BLOQUANT' "$_"
    $script:ExitCode = 1
}
finally {
    Show-Summary
    if ($transcript) { try { Stop-Transcript | Out-Null } catch { } }
}

exit $script:ExitCode
