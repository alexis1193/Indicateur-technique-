"""
mt5_check.py - Audit d'un compte MetaTrader 5 avant de developper une strategie.

1. Connexion au terminal (chemin de terminal64.exe detecte automatiquement).
   Reprend la session en cours si le terminal est deja connecte, sinon
   utilise MT5_LOGIN / MT5_PASSWORD / MT5_SERVER (variables d'environnement).
   Verifie que l'AlgoTrading est actif.
2. Infos du compte (login, serveur, devise, solde, equity, levier, demo/reel).
3. Paires forex du broker : prefixe/suffixe utilises, digits, spread, lot min.
4. EURUSD (nom reel chez le broker) : plus ancienne barre M30, profondeur
   d'historique en annees, decalage horaire du serveur par rapport a UTC.

Variables d'environnement (toutes optionnelles) :
  MT5_TERMINAL_PATH  chemin complet de terminal64.exe (force la detection)
  MT5_LOGIN          numero de compte
  MT5_PASSWORD       mot de passe (jamais en dur dans le code)
  MT5_SERVER         nom exact du serveur broker

Codes de sortie : 0 = OK, 1 = point bloquant, 2 = connexion impossible.
"""

import glob
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[ERR]  Module MetaTrader5 absent. Lancez d'abord setup_mt5_python.bat")
    sys.exit(1)

try:
    import pytz
except ImportError:
    pytz = None

# Devises fiat reconnues pour identifier les paires forex (exclut XAU, XAG, BTC...)
FIAT = {
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK",
    "DKK", "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH",
    "RUB", "ILS", "THB", "CNY", "INR", "KRW", "BRL", "RON", "ISK",
}

TRADE_MODE_DISABLED = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)
ACCOUNT_MODES = {
    getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0): "DEMO",
    getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1): "CONCOURS",
    getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2): "REEL",
}

warnings = []


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
def title(text):
    print()
    print("=== " + text + " ===")


def ok(text):
    print("  [OK]   " + text)


def info(text):
    print("  [..]   " + text)


def warn(text):
    print("  [WARN] " + text)
    warnings.append(text)


def err(text):
    print("  [ERR]  " + text)


def ascii_only(text):
    return str(text).encode("ascii", "replace").decode("ascii")


# ---------------------------------------------------------------------------
# 1. Detection du terminal
# ---------------------------------------------------------------------------
def _read_origin(path):
    for enc in ("utf-16", "utf-8-sig", "mbcs"):
        try:
            with open(path, "r", encoding=enc) as f:
                value = f.read().strip().strip("﻿").strip()
            if value:
                return value
        except Exception:
            continue
    return None


def _registry_dirs():
    dirs = []
    try:
        import winreg
    except ImportError:
        return dirs
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, key in roots:
        try:
            k = winreg.OpenKey(hive, key)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(k)[0]):
            try:
                sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
            except OSError:
                continue

            def val(name):
                try:
                    return str(winreg.QueryValueEx(sub, name)[0])
                except OSError:
                    return ""

            name, pub = val("DisplayName"), val("Publisher")
            if "MetaTrader 5" in name or "MetaQuotes" in pub:
                for field in ("InstallLocation", "DisplayIcon", "UninstallString"):
                    v = val(field).strip().strip('"').split(",")[0].strip('"')
                    if not v:
                        continue
                    if v.lower().endswith(".exe"):
                        v = os.path.dirname(v)
                    dirs.append(v)
    return dirs


def find_terminals():
    """Retourne la liste des terminal64.exe trouves, les plus probables d'abord."""
    candidates = []
    appdata = os.environ.get("APPDATA", "")
    for origin in glob.glob(os.path.join(appdata, "MetaQuotes", "Terminal", "*", "origin.txt")):
        d = _read_origin(origin)
        if d:
            candidates.append(os.path.join(d, "terminal64.exe"))
    for d in _registry_dirs():
        candidates.append(os.path.join(d, "terminal64.exe"))
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
                 os.environ.get("SystemDrive", "C:") + "\\"):
        if root:
            candidates.extend(glob.glob(os.path.join(root, "*", "terminal64.exe")))

    seen, result = set(), []
    for c in candidates:
        key = os.path.normcase(os.path.abspath(c))
        if key not in seen and os.path.isfile(c):
            seen.add(key)
            result.append(c)
    return result


def resolve_terminal_path():
    forced = os.environ.get("MT5_TERMINAL_PATH", "").strip().strip('"')
    if forced:
        if os.path.isfile(forced):
            ok("Terminal force par MT5_TERMINAL_PATH : " + forced)
            return forced
        warn("MT5_TERMINAL_PATH introuvable (" + forced + "), detection automatique.")
    found = find_terminals()
    if not found:
        warn("Aucun terminal64.exe detecte : MT5 tentera le dernier terminal utilise.")
        return None
    ok("Terminal detecte : " + found[0])
    for other in found[1:]:
        info("Autre terminal present : " + other)
    return found[0]


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------
def wait_connected(timeout_s):
    end = time.time() + timeout_s
    while time.time() < end:
        ti = mt5.terminal_info()
        ai = mt5.account_info()
        if ti is not None and ti.connected and ai is not None and ai.login:
            return True
        time.sleep(1)
    return False


def connect(path):
    login = os.environ.get("MT5_LOGIN", "").strip()
    password = os.environ.get("MT5_PASSWORD", "")
    server = os.environ.get("MT5_SERVER", "").strip()
    base_args = [path] if path else []

    initialized = mt5.initialize(*base_args, timeout=60000)
    if initialized and wait_connected(15):
        ai = mt5.account_info()
        ok("Session en cours reprise (compte %s)" % ai.login)
        if login and login.isdigit() and int(login) != ai.login:
            warn("MT5_LOGIN=%s differe du compte connecte %s : on garde la session en cours."
                 % (login, ai.login))
        return True

    if not (login and password and server):
        err("Terminal non connecte et identifiants absents.")
        if not initialized:
            err("initialize() : %s" % (mt5.last_error(),))
        print("         Definissez-les pour cette fenetre PowerShell uniquement :")
        print('           $env:MT5_LOGIN="12345678"')
        print('           $env:MT5_SERVER="NomDuServeur-Demo"')
        print('           $env:MT5_PASSWORD="votre_mot_de_passe"')
        print("         Ou connectez-vous une fois dans le terminal MT5 puis relancez.")
        return False
    if not login.isdigit():
        err("MT5_LOGIN doit etre un nombre (recu : %s)" % ascii_only(login))
        return False

    info("Connexion avec MT5_LOGIN=%s sur %s ..." % (login, server))
    if initialized:
        done = mt5.login(int(login), password=password, server=server, timeout=60000)
    else:
        done = mt5.initialize(*base_args, login=int(login), password=password,
                              server=server, timeout=60000)
    if not done:
        err("Echec de connexion : %s" % (mt5.last_error(),))
        return False
    if not wait_connected(20):
        err("Le terminal ne se connecte pas au serveur %s." % server)
        return False
    ok("Connecte au compte %s" % login)
    return True


def check_algo_trading():
    ti = mt5.terminal_info()
    ai = mt5.account_info()
    blocking = False
    if ti.trade_allowed:
        ok("AlgoTrading actif dans le terminal")
    else:
        err("AlgoTrading DESACTIVE : cliquez sur le bouton 'Algo Trading' du terminal.")
        blocking = True
    if getattr(ti, "tradeapi_disabled", False):
        err("API de trading Python desactivee : Outils > Options > Expert Advisors.")
        blocking = True
    if not ai.trade_expert:
        err("Le broker interdit le trading automatique sur ce compte.")
        blocking = True
    if not ai.trade_allowed:
        warn("Trading non autorise sur ce compte (compte investisseur / lecture seule ?).")
    return not blocking


# ---------------------------------------------------------------------------
# 2. Compte
# ---------------------------------------------------------------------------
def show_account():
    ai = mt5.account_info()
    mode = ACCOUNT_MODES.get(ai.trade_mode, "INCONNU (%s)" % ai.trade_mode)
    rows = [
        ("Login", ai.login),
        ("Serveur", ascii_only(ai.server)),
        ("Societe", ascii_only(ai.company)),
        ("Devise", ai.currency),
        ("Solde", "%.2f %s" % (ai.balance, ai.currency)),
        ("Equity", "%.2f %s" % (ai.equity, ai.currency)),
        ("Levier", "1:%s" % ai.leverage),
        ("Type", mode),
    ]
    for k, v in rows:
        print("  %-9s: %s" % (k, v))
    if mode == "REEL":
        warn("Compte REEL : developpez et testez d'abord sur un compte demo.")


# ---------------------------------------------------------------------------
# 3. Paires forex
# ---------------------------------------------------------------------------
def forex_symbols():
    result = []
    for s in mt5.symbols_get() or []:
        base, quote = s.currency_base, s.currency_profit
        pair = base + quote
        if base in FIAT and quote in FIAT and base != quote:
            pos = s.name.upper().find(pair)
            if pos >= 0:
                result.append((s, s.name[:pos], s.name[pos + 6:]))
    return result


def fmt_affix(prefix, suffix):
    p = "'%s'" % prefix if prefix else "aucun"
    s = "'%s'" % suffix if suffix else "aucun"
    return "prefixe %s, suffixe %s (ex: %sEURUSD%s)" % (p, s, prefix, suffix)


def show_forex(fx):
    if not fx:
        err("Aucune paire forex trouvee chez ce broker.")
        return
    counts = Counter((p, s) for _, p, s in fx)
    parts = ["%s -> %d paire(s)" % (fmt_affix(p, s), n) for (p, s), n in counts.most_common()]
    print("  Format broker : " + " | ".join(parts))
    print()
    print("  %-16s %6s %10s %10s %8s" % ("Symbole", "Digits", "Spread pt", "Spread pip", "Lot min"))
    print("  " + "-" * 54)
    for s, _, _ in sorted(fx, key=lambda x: x[0].name):
        if s.spread == 0 and not s.visible:
            spread_pt, spread_pip = "n/d", "n/d"
        else:
            factor = 10.0 if s.digits in (3, 5) else 1.0
            spread_pt, spread_pip = str(s.spread), "%.1f" % (s.spread / factor)
        print("  %-16s %6d %10s %10s %8s" % (ascii_only(s.name), s.digits, spread_pt,
                                              spread_pip, ("%g" % s.volume_min)))
    print("  (n/d = symbole hors Market Watch, spread non actualise)")


# ---------------------------------------------------------------------------
# 4. EURUSD : historique et decalage serveur
# ---------------------------------------------------------------------------
def resolve_eurusd(fx):
    cands = [s for s, _, _ in fx
             if s.currency_base == "EUR" and s.currency_profit == "USD"
             and s.trade_mode != TRADE_MODE_DISABLED]
    if not cands:
        return None
    cands.sort(key=lambda s: (s.name != "EURUSD", not s.visible, len(s.name), s.name))
    return cands[0].name


def _bar_exists(symbol, pos):
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, pos, 1)
    return r is not None and len(r) > 0


def oldest_m30_bar(symbol):
    """Recherche dichotomique : une seule barre demandee a chaque appel."""
    for _ in range(15):  # le premier appel declenche la synchro de l'historique
        if _bar_exists(symbol, 0):
            break
        time.sleep(1)
    else:
        return None, 0
    lo, hi = 0, 1
    while _bar_exists(symbol, hi):
        lo, hi = hi, hi * 2
        if hi > 100000000:
            break
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _bar_exists(symbol, mid):
            lo = mid
        else:
            hi = mid
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, lo, 1)
    return int(r[0]["time"]), lo + 1


def server_dt(ts):
    """Les heures MT5 sont l'heure serveur stockee comme un timestamp 'UTC'."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def offset_from_tick(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or not tick.time:
        return None
    diff = tick.time - time.time()
    q = round(diff / 1800.0) * 1800
    if abs(diff - q) < 90 and abs(q) <= 14 * 3600:
        return q / 3600.0
    return None  # tick ancien : marche ferme


def offset_from_week_open(symbol):
    """Le forex ouvre le dimanche a 17h00 heure de New York."""
    if pytz is None:
        return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, 0, 48 * 14)
    if rates is None or len(rates) < 2:
        return None
    open_ts = None
    for i in range(len(rates) - 1, 0, -1):
        if rates[i]["time"] - rates[i - 1]["time"] > 36 * 3600:
            open_ts = int(rates[i]["time"])
            break
    if open_ts is None:
        return None
    d = server_dt(open_ts)
    sunday = (d - timedelta(days=(d.weekday() + 1) % 7)).date()
    ny = pytz.timezone("America/New_York")
    open_utc = ny.localize(datetime(sunday.year, sunday.month, sunday.day, 17, 0))
    open_utc = open_utc.astimezone(pytz.utc).replace(tzinfo=None)
    hours = (d - open_utc).total_seconds() / 3600.0
    return round(hours * 2) / 2.0


def fmt_offset(h):
    sign = "+" if h >= 0 else "-"
    h = abs(h)
    return "UTC%s%d:%02d" % (sign, int(h), int(round((h - int(h)) * 60)))


def show_eurusd(fx):
    name = resolve_eurusd(fx)
    if name is None:
        err("EURUSD introuvable chez ce broker.")
        return False
    mt5.symbol_select(name, True)
    ok("Nom reel chez le broker : " + ascii_only(name))

    oldest, count = oldest_m30_bar(name)
    if oldest is None:
        err("Aucune barre M30 disponible (historique non telecharge ?).")
        return False
    last = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M30, 0, 1)
    years = (int(last[0]["time"]) - oldest) / (365.25 * 86400)
    print("  Plus ancienne barre M30 : %s (heure serveur)" % server_dt(oldest).strftime("%Y-%m-%d %H:%M"))
    print("  Profondeur d'historique : %.1f ans (%d barres M30)" % (years, count))
    maxbars = mt5.terminal_info().maxbars
    if maxbars and count >= maxbars - 1:
        warn("Limite 'Max barres dans le graphique' (%d) atteinte : augmentez-la dans "
             "Outils > Options > Graphiques pour voir plus loin." % maxbars)

    off = offset_from_tick(name)
    method = "tick en direct"
    if off is None:
        off = offset_from_week_open(name)
        method = "ouverture hebdo du forex (marche ferme)"
    if off is None:
        warn("Decalage horaire serveur indeterminable (marche ferme et pytz absent ?).")
    else:
        print("  Decalage serveur / UTC  : %s  (methode : %s)" % (fmt_offset(off), method))
        info("La plupart des brokers changent de decalage avec l'heure d'ete US.")
    return True


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------
def main():
    print("Audit MT5 - %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    title("1. Connexion")
    path = resolve_terminal_path()
    if not connect(path):
        return 2
    try:
        algo_ok = check_algo_trading()

        title("2. Compte")
        show_account()

        title("3. Paires forex")
        fx = forex_symbols()
        show_forex(fx)

        title("4. Historique EURUSD")
        eur_ok = show_eurusd(fx)

        title("RESUME")
        if warnings:
            for w in warnings:
                print("  [WARN] " + w)
        if algo_ok and eur_ok:
            ok("Compte pret pour le developpement de strategie.")
            return 0
        err("Point(s) bloquant(s) ci-dessus a corriger.")
        return 1
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
