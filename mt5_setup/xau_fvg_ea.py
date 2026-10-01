"""
xau_fvg_ea.py - EA Python pour MetaTrader 5 : XAUUSD M15, retest de FVG
dans le sens du dernier BOS H1.

STRATEGIE
  - Biais : direction du dernier BOS H1 (structure par fractales).
  - Entree : ordre limit sur retest d'un FVG M15 dans le sens du biais.
      FVG haussier : low[i]  > high[i-2]   zone = [high[i-2], low[i]]
      FVG baissier : high[i] < low[i-2]    zone = [high[i],   low[i-2]]
    La couleur des bougies est ignoree. Entree sur le bord proche de la zone.
  - Filtres : taille FVG >= 3 % ADR14 D1, spread <= 0,40 $, une seule
    position a la fois, pas de reentree sur un FVG deja utilise.
  - Session : 09h-22h heure de Paris (heure d'ete geree), pas le week-end.

RISQUE
  - 1 % de l'equity par trade, SL fixe 5,00 $.
  - TP1 a +5,00 $ : ferme 50 % et SL au BE + 0,10 $.
  - Runner : trailing sur le dernier swing M15, cloture forcee a 22h.
  - Kill switch : -3 % sur la journee ou 5 trades -> arret jusqu'au lendemain.
  - Magic number dedie : ne touche jamais aux positions manuelles.

FONCTIONNEMENT 24/5
  - Boucle incassable : exception loguee, reprise apres 30 s ; 20 erreurs
    consecutives -> fermeture des positions de l'EA et arret propre.
  - Reconnexion automatique si le terminal devient injoignable.
  - Ligne de vie toutes les 15 min :
    VIVANT | heure Paris | equity | nb positions | nb ordres | en session

CONNEXION / LANCEMENT (variables d'environnement)
  TERMINAL_PATH  chemin de terminal64.exe (repli sur detection auto)
  DEMO_ONLY      1 = refuse un compte reel (defaut 1)
  DRY_RUN        1 = simulation, aucun ordre envoye (defaut 1)
  AUTO_DETACH    1 = se relance dans une fenetre PowerShell dediee (defaut 1)
  MT5_LOGIN / MT5_PASSWORD / MT5_SERVER : optionnels si le terminal est
                 deja connecte. Mot de passe jamais en dur.

Python 3.10, librairies : MetaTrader5, pytz.
"""

import glob
import json
import logging
import math
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

# ===========================================================================
# CONFIGURATION
# ===========================================================================
def env_bool(name, default):
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "oui", "on")


TERMINAL_PATH = os.environ.get("TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
DEMO_ONLY = env_bool("DEMO_ONLY", True)
DRY_RUN = env_bool("DRY_RUN", True)
AUTO_DETACH = env_bool("AUTO_DETACH", True)

SYMBOL_BASE = "XAUUSD"
MAGIC = 7711501
COMMENT_TAG = "XFVG"

# Strategie
FRACTAL_N = 2                 # barres de chaque cote pour une fractale
H1_BARS = 500                 # barres H1 analysees pour le BOS
M15_BARS = 300                # barres M15 analysees pour les FVG
FVG_MAX_AGE_BARS = 48         # un FVG plus vieux que 12h est ignore
FVG_MIN_ADR_PCT = 3.0         # taille mini du FVG en % de l'ADR14
ADR_PERIOD = 14
MAX_SPREAD_USD = 0.40
PENDING_MAX_MINUTES = 240     # un ordre limit non execute est annule apres 4h

# Session (heure de Paris)
SESSION_START_HOUR = 9
SESSION_END_HOUR = 22

# Risque
RISK_PCT = 1.0
SL_USD = 5.00
TP1_USD = 5.00
TP1_CLOSE_FRACTION = 0.5
BE_OFFSET_USD = 0.10
TRAIL_BUFFER_USD = 0.00       # marge sous/au-dessus du swing pour le trailing
DAILY_LOSS_PCT = 3.0
MAX_TRADES_PER_DAY = 5
DEVIATION_POINTS = 30

# Technique
LOOP_SECONDS = 5
ERROR_PAUSE_SECONDS = 30      # pause apres une exception
MAX_CONSECUTIVE_ERRORS = 20   # au-dela : positions fermees et arret propre
RECONNECT_PAUSE_SECONDS = 30  # pause entre deux tentatives de reconnexion
HEARTBEAT_MINUTES = 15        # ligne de vie dans le log
LOCK_PORT = 47615             # verrou anti double-lancement (127.0.0.1)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "xau_fvg_ea.log")
STATE_FILE = os.path.join(BASE_DIR, "xau_fvg_ea_state.json")


# ===========================================================================
# AUTO_DETACH : relance dans une fenetre PowerShell dediee
# ===========================================================================
def detach():
    def q(s):
        return "'" + s.replace("'", "''") + "'"
    cmd = ("$Host.UI.RawUI.WindowTitle = 'XAU FVG EA'; "
           "& %s %s --child" % (q(sys.executable), q(os.path.abspath(__file__))))
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-Command", cmd],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )
    print("EA lance dans une fenetre PowerShell dediee. Log : " + LOG_FILE)


# ===========================================================================
# LOGS (ASCII pur)
# ===========================================================================
class AsciiFormatter(logging.Formatter):
    def format(self, record):
        return super().format(record).encode("ascii", "replace").decode("ascii")


log = logging.getLogger("xau_fvg_ea")


def setup_logging():
    log.setLevel(logging.INFO)
    fmt = AsciiFormatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="ascii")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.handlers[:] = [fh, ch]


# ===========================================================================
# VERROU RESEAU
# ===========================================================================
def acquire_lock():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


# ===========================================================================
# IMPORTS MT5 (apres le detach pour que le parent rende la main vite)
# ===========================================================================
mt5 = None
pytz = None
PARIS = None


def load_libs():
    global mt5, pytz, PARIS
    import MetaTrader5 as _mt5
    import pytz as _pytz
    mt5, pytz = _mt5, _pytz
    PARIS = pytz.timezone("Europe/Paris")


# ===========================================================================
# CONNEXION
# ===========================================================================
def find_terminals():
    cands = []
    appdata = os.environ.get("APPDATA", "")
    for origin in glob.glob(os.path.join(appdata, "MetaQuotes", "Terminal", "*", "origin.txt")):
        for enc in ("utf-16", "utf-8-sig"):
            try:
                with open(origin, "r", encoding=enc) as f:
                    d = f.read().strip().strip("\ufeff").strip()
                if d:
                    cands.append(os.path.join(d, "terminal64.exe"))
                    break
            except Exception:
                continue
    try:
        import winreg
        for hive, key in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ):
            try:
                k = winreg.OpenKey(hive, key)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                    name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                    if "MetaTrader 5" not in name:
                        continue
                    loc = str(winreg.QueryValueEx(sub, "InstallLocation")[0]).strip('"')
                    cands.append(os.path.join(loc, "terminal64.exe"))
                except OSError:
                    continue
    except ImportError:
        pass
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            cands.extend(glob.glob(os.path.join(root, "*", "terminal64.exe")))
    return [c for c in cands if os.path.isfile(c)]


def terminal_path():
    if TERMINAL_PATH and os.path.isfile(TERMINAL_PATH):
        log.info("Terminal (TERMINAL_PATH) : %s", TERMINAL_PATH)
        return TERMINAL_PATH
    log.warning("TERMINAL_PATH introuvable (%s), detection automatique.", TERMINAL_PATH)
    found = find_terminals()
    if found:
        log.info("Terminal detecte : %s", found[0])
        return found[0]
    log.warning("Aucun terminal detecte : MT5 utilisera le dernier terminal lance.")
    return None


def wait_connected(timeout_s):
    end = time.time() + timeout_s
    while time.time() < end:
        ti, ai = mt5.terminal_info(), mt5.account_info()
        if ti is not None and ti.connected and ai is not None and ai.login:
            return True
        time.sleep(1)
    return False


def connect():
    path = terminal_path()
    args = [path] if path else []
    login = os.environ.get("MT5_LOGIN", "").strip()
    password = os.environ.get("MT5_PASSWORD", "")
    server = os.environ.get("MT5_SERVER", "").strip()

    ok = mt5.initialize(*args, timeout=60000)
    if ok and wait_connected(15):
        log.info("Session MT5 en cours reprise.")
        return True
    if not (login.isdigit() and password and server):
        log.error("Terminal non connecte et MT5_LOGIN/MT5_PASSWORD/MT5_SERVER absents. (%s)",
                  mt5.last_error())
        return False
    if ok:
        ok = mt5.login(int(login), password=password, server=server, timeout=60000)
    else:
        ok = mt5.initialize(*args, login=int(login), password=password, server=server, timeout=60000)
    if not ok or not wait_connected(20):
        log.error("Connexion impossible : %s", mt5.last_error())
        return False
    log.info("Connecte au compte %s.", login)
    return True


def check_account():
    ai, ti = mt5.account_info(), mt5.terminal_info()
    is_demo = ai.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    log.info("Compte %s | %s | %s | equity %.2f | levier 1:%s | %s",
             ai.login, ai.server, ai.currency, ai.equity, ai.leverage, "DEMO" if is_demo else "REEL")
    if DEMO_ONLY and not is_demo:
        log.critical("DEMO_ONLY actif et compte REEL : arret.")
        return False
    if not DRY_RUN:
        if not ti.trade_allowed:
            log.critical("AlgoTrading desactive dans le terminal : arret.")
            return False
        if not ai.trade_expert:
            log.critical("Le broker interdit le trading automatique sur ce compte : arret.")
            return False
    return True


def resolve_symbol():
    syms = mt5.symbols_get() or []
    cands = [s for s in syms if SYMBOL_BASE in s.name.upper()
             and s.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED]
    if not cands:
        cands = [s for s in syms if s.currency_base == "XAU" and s.currency_profit == "USD"]
    if not cands:
        return None
    cands.sort(key=lambda s: (s.name != SYMBOL_BASE, not s.visible, len(s.name)))
    name = cands[0].name
    mt5.symbol_select(name, True)
    return name


class FatalError(Exception):
    """Erreur qui doit arreter l'EA sans relance (ex : compte reel en DEMO_ONLY)."""


def in_session(now_paris):
    return now_paris.weekday() < 5 and SESSION_START_HOUR <= now_paris.hour < SESSION_END_HOUR


# ===========================================================================
# OUTILS DE MARCHE
# ===========================================================================
def is_fractal_high(h, j, n):
    return all(h[j] > h[j - k] and h[j] > h[j + k] for k in range(1, n + 1))


def is_fractal_low(l, j, n):
    return all(l[j] < l[j - k] and l[j] < l[j + k] for k in range(1, n + 1))


def h1_bias(rates, n=FRACTAL_N):
    """Direction du dernier BOS : +1 haussier, -1 baissier, 0 inconnu.
    Un BOS = cloture au-dela de la derniere fractale confirmee non cassee."""
    h, l, c = rates["high"], rates["low"], rates["close"]
    swing_h = swing_l = None
    bias = 0
    for i in range(len(rates)):
        j = i - n
        if j >= n:
            if is_fractal_high(h, j, n):
                swing_h = h[j]
            if is_fractal_low(l, j, n):
                swing_l = l[j]
        if swing_h is not None and c[i] > swing_h:
            bias, swing_h = 1, None
        elif swing_l is not None and c[i] < swing_l:
            bias, swing_l = -1, None
    return bias


def last_swing(rates, direction, n=FRACTAL_N):
    """Dernier swing M15 confirme : bas si direction=+1, haut si -1."""
    h, l = rates["high"], rates["low"]
    for j in range(len(rates) - 1 - n, n - 1, -1):
        if direction > 0 and is_fractal_low(l, j, n):
            return float(l[j])
        if direction < 0 and is_fractal_high(h, j, n):
            return float(h[j])
    return None


def adr(rates_d1):
    if rates_d1 is None or len(rates_d1) < ADR_PERIOD:
        return None
    r = rates_d1[-ADR_PERIOD:]
    return float((r["high"] - r["low"]).mean())


def find_fvgs(rates, bias):
    """FVG non mitiges dans le sens du biais, du plus recent au plus ancien."""
    h, l, t = rates["high"], rates["low"], rates["time"]
    out = []
    last = len(rates) - 1
    for i in range(last, max(1, last - FVG_MAX_AGE_BARS), -1):
        if bias > 0 and l[i] > h[i - 2]:
            bottom, top = float(h[i - 2]), float(l[i])
            if i < last and l[i + 1:].min() <= top:
                continue  # deja retouche
            out.append({"id": "%dB" % int(t[i]), "dir": 1, "bottom": bottom, "top": top})
        elif bias < 0 and h[i] < l[i - 2]:
            bottom, top = float(h[i]), float(l[i - 2])
            if i < last and h[i + 1:].max() >= bottom:
                continue
            out.append({"id": "%dS" % int(t[i]), "dir": -1, "bottom": bottom, "top": top})
    return out


# ===========================================================================
# EA
# ===========================================================================
class EA:
    def __init__(self, symbol):
        self.symbol = symbol
        self.state = self.load_state()
        self.dry_used = set()
        self.last_bar_time = None
        self.disconnected_since = None
        self.reconnect_attempts = 0

    # ---- connexion -------------------------------------------------------
    def ensure_connection(self):
        """True si le terminal repond et est connecte, sinon tente une reconnexion."""
        ti, ai = mt5.terminal_info(), mt5.account_info()
        if ti is not None and ti.connected and ai is not None and ai.login:
            return True
        if self.disconnected_since is None:
            self.disconnected_since = time.time()
            log.warning("Terminal MT5 injoignable ou deconnecte (%s). Reconnexion...", mt5.last_error())
        try:
            mt5.shutdown()
        except Exception:
            pass
        # Detail des tentatives seulement a la 1re puis toutes les 10 (evite le spam du log)
        self.reconnect_attempts += 1
        verbose = self.reconnect_attempts == 1 or self.reconnect_attempts % 10 == 0
        if not verbose:
            log.setLevel(logging.CRITICAL)
        try:
            ok = connect()
        finally:
            log.setLevel(logging.INFO)
        if ok:
            if not check_account():
                raise FatalError("compte refuse apres reconnexion")
            mt5.symbol_select(self.symbol, True)
            log.info("Reconnecte apres %d s de coupure.", time.time() - self.disconnected_since)
            self.disconnected_since = None
            self.reconnect_attempts = 0
            return True
        log.warning("Reconnexion echouee (coupure depuis %d s). Nouvel essai dans %d s.",
                    time.time() - self.disconnected_since, RECONNECT_PAUSE_SECONDS)
        return False

    def heartbeat(self):
        now = datetime.now(PARIS)
        ai = mt5.account_info()
        equity = "%.2f" % ai.equity if ai is not None else "n/d"
        try:
            npos, nord = len(self.my_positions()), len(self.my_orders())
        except Exception:
            npos = nord = "n/d"
        log.info("VIVANT | %s Paris | equity %s | positions %s | ordres %s | en session %s",
                 now.strftime("%Y-%m-%d %H:%M"), equity, npos, nord,
                 "OUI" if in_session(now) else "NON")

    # ---- etat persistant -------------------------------------------------
    def load_state(self):
        try:
            with open(STATE_FILE, "r") as f:
                st = json.load(f)
        except Exception:
            st = {}
        st.setdefault("day", "")
        st.setdefault("day_start_equity", 0.0)
        st.setdefault("trades_today", 0)
        st.setdefault("halted", False)
        st.setdefault("known_positions", [])
        st.setdefault("used_fvgs", [])
        st.setdefault("tp1_done", [])
        return st

    def save_state(self):
        st = self.state
        st["used_fvgs"] = st["used_fvgs"][-500:]
        st["known_positions"] = st["known_positions"][-200:]
        st["tp1_done"] = st["tp1_done"][-200:]
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, STATE_FILE)

    # ---- infos -----------------------------------------------------------
    def info(self):
        return mt5.symbol_info(self.symbol)

    def my_positions(self):
        return [p for p in (mt5.positions_get(symbol=self.symbol) or []) if p.magic == MAGIC]

    def my_orders(self):
        return [o for o in (mt5.orders_get(symbol=self.symbol) or []) if o.magic == MAGIC]

    def norm_price(self, price, si):
        step = si.trade_tick_size or si.point
        return round(round(price / step) * step, si.digits)

    def stops_distance(self, si):
        return max(si.trade_stops_level, si.trade_freeze_level) * si.point

    # ---- envoi d'ordres --------------------------------------------------
    def send(self, request, what):
        if DRY_RUN:
            log.info("[DRY_RUN] %s | %s", what,
                     {k: v for k, v in request.items() if k in ("type", "volume", "price", "sl", "position")})
            return True
        fillings = [request.get("type_filling")]
        for f in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
            if f not in fillings:
                fillings.append(f)
        for f in fillings:
            request["type_filling"] = f
            res = mt5.order_send(request)
            if res is None:
                log.error("%s : order_send a renvoye None %s", what, mt5.last_error())
                return False
            if res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED,
                               mt5.TRADE_RETCODE_DONE_PARTIAL):
                log.info("%s : OK (retcode %s, ordre %s)", what, res.retcode, res.order)
                return True
            if res.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                log.error("%s : refuse retcode %s (%s)", what, res.retcode, res.comment)
                return False
        log.error("%s : aucun mode de remplissage accepte.", what)
        return False

    def market_filling(self, si):
        if si.filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        if si.filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def close_position(self, p, volume=None, why=""):
        tick = mt5.symbol_info_tick(self.symbol)
        si = self.info()
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": p.ticket,
            "volume": volume or p.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": DEVIATION_POINTS, "magic": MAGIC, "comment": COMMENT_TAG + " close",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": self.market_filling(si),
        }
        return self.send(req, "Cloture %s %.2f lot(s) #%s %s" % ("BUY" if is_buy else "SELL",
                                                                 req["volume"], p.ticket, why))

    def modify_sl(self, p, sl, why):
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": self.symbol, "position": p.ticket,
               "sl": sl, "tp": p.tp, "magic": MAGIC}
        return self.send(req, "SL #%s -> %s (%s)" % (p.ticket, sl, why))

    def cancel_order(self, o, why):
        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket, "symbol": self.symbol}
        return self.send(req, "Annulation ordre #%s (%s)" % (o.ticket, why))

    def flatten(self, why):
        for o in self.my_orders():
            self.cancel_order(o, why)
        for p in self.my_positions():
            self.close_position(p, why=why)

    # ---- journee / kill switch -------------------------------------------
    def update_day(self, now_paris):
        day = now_paris.strftime("%Y-%m-%d")
        if self.state["day"] != day:
            eq = mt5.account_info().equity
            self.state.update(day=day, day_start_equity=eq, trades_today=0, halted=False)
            self.save_state()
            log.info("Nouvelle journee %s | equity de depart %.2f", day, eq)

    def count_new_trades(self):
        known = set(self.state["known_positions"])
        for p in self.my_positions():
            if p.ticket not in known:
                self.state["known_positions"].append(p.ticket)
                self.state["trades_today"] += 1
                log.info("Nouvelle position #%s %s %.2f @ %s | trades du jour : %d",
                         p.ticket, "BUY" if p.type == 0 else "SELL", p.volume, p.price_open,
                         self.state["trades_today"])
                self.save_state()

    def check_kill_switch(self):
        if self.state["halted"]:
            return True
        start = self.state["day_start_equity"]
        eq = mt5.account_info().equity
        if start > 0 and (eq - start) / start * 100.0 <= -DAILY_LOSS_PCT:
            log.warning("KILL SWITCH : perte journaliere %.2f %% (equity %.2f / depart %.2f). "
                        "Arret jusqu'a demain.", (eq - start) / start * 100.0, eq, start)
            self.flatten("kill switch")
            self.state["halted"] = True
            self.save_state()
            return True
        return False

    # ---- gestion des positions -------------------------------------------
    def manage_positions(self, m15):
        si = self.info()
        tick = mt5.symbol_info_tick(self.symbol)
        min_dist = self.stops_distance(si)
        for p in self.my_positions():
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            d = 1 if is_buy else -1
            price = tick.bid if is_buy else tick.ask
            be = self.norm_price(p.price_open + d * BE_OFFSET_USD, si)
            tp1_done = p.ticket in self.state["tp1_done"] or (
                p.sl > 0 and (p.sl - p.price_open) * d >= 0)

            # TP1 : 50 % + SL au BE
            if not tp1_done and (price - p.price_open) * d >= TP1_USD:
                half = math.floor(p.volume * TP1_CLOSE_FRACTION / si.volume_step) * si.volume_step
                half = round(half, 8)
                if half >= si.volume_min and p.volume - half >= si.volume_min - 1e-9:
                    if not self.close_position(p, volume=half, why="TP1"):
                        continue
                else:
                    log.warning("#%s : volume %.2f trop petit pour fermer 50 %%, SL au BE seul.",
                                p.ticket, p.volume)
                self.state["tp1_done"].append(p.ticket)
                self.save_state()
                tp1_done = True
                if not DRY_RUN:
                    time.sleep(0.5)
                    p = next((x for x in self.my_positions() if x.ticket == p.ticket), None)
                    if p is None:
                        continue

            if tp1_done and (p.sl - be) * d < 0:
                if abs(price - be) >= min_dist:
                    self.modify_sl(p, be, "BE + %.2f" % BE_OFFSET_USD)
                continue

            # Runner : trailing sur le dernier swing M15
            if tp1_done and m15 is not None:
                swing = last_swing(m15, d)
                if swing is None:
                    continue
                new_sl = self.norm_price(swing - d * TRAIL_BUFFER_USD, si)
                if (new_sl - p.sl) * d > si.point and (price - new_sl) * d >= min_dist:
                    self.modify_sl(p, new_sl, "trailing swing M15")

    # ---- ordres en attente -----------------------------------------------
    def manage_orders(self, bias):
        tick = mt5.symbol_info_tick(self.symbol)
        for o in self.my_orders():
            d = 1 if o.type == mt5.ORDER_TYPE_BUY_LIMIT else -1
            age_min = (tick.time - o.time_setup) / 60.0
            if bias != 0 and d != bias:
                self.cancel_order(o, "biais H1 inverse")
            elif age_min > PENDING_MAX_MINUTES:
                self.cancel_order(o, "expire apres %d min" % PENDING_MAX_MINUTES)

    # ---- recherche d'entree ----------------------------------------------
    def lot_size(self, si, entry, sl, is_buy):
        risk = mt5.account_info().equity * RISK_PCT / 100.0
        otype = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        loss = mt5.order_calc_profit(otype, self.symbol, 1.0, entry, sl)
        if loss is None or loss == 0:
            loss = -abs(entry - sl) / si.trade_tick_size * si.trade_tick_value
        lots = math.floor(risk / abs(loss) / si.volume_step) * si.volume_step
        lots = min(round(lots, 8), si.volume_max)
        return lots, risk

    def try_entry(self, bias, m15, d1):
        if bias == 0:
            return
        if self.my_positions() or self.my_orders():
            return
        if self.state["trades_today"] >= MAX_TRADES_PER_DAY:
            return
        si = self.info()
        tick = mt5.symbol_info_tick(self.symbol)
        spread = tick.ask - tick.bid
        if spread > MAX_SPREAD_USD:
            return
        a = adr(d1)
        if a is None:
            return
        used = set(self.state["used_fvgs"]) | self.dry_used
        min_dist = self.stops_distance(si)

        for fvg in find_fvgs(m15, bias):
            if fvg["id"] in used:
                continue
            size = fvg["top"] - fvg["bottom"]
            if size < a * FVG_MIN_ADR_PCT / 100.0:
                continue
            is_buy = fvg["dir"] > 0
            entry = self.norm_price(fvg["top"] if is_buy else fvg["bottom"], si)
            sl = self.norm_price(entry - SL_USD if is_buy else entry + SL_USD, si)
            market = tick.ask if is_buy else tick.bid
            if (market - entry) * fvg["dir"] < min_dist:
                continue  # prix deja dans la zone ou trop proche : pas de limit possible
            if SL_USD < min_dist:
                log.warning("stops_level %.2f $ > SL %.2f $ : trade ignore.", min_dist, SL_USD)
                return
            lots, risk = self.lot_size(si, entry, sl, is_buy)
            if lots < si.volume_min:
                log.warning("Lot calcule %.4f < minimum %.2f (risque %.2f) : trade ignore.",
                            lots, si.volume_min, risk)
                return
            req = {
                "action": mt5.TRADE_ACTION_PENDING, "symbol": self.symbol, "volume": lots,
                "type": mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT,
                "price": entry, "sl": sl, "tp": 0.0, "deviation": DEVIATION_POINTS,
                "magic": MAGIC, "comment": "%s %s" % (COMMENT_TAG, fvg["id"]),
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            what = "%s LIMIT %.2f lot @ %s SL %s | FVG %s [%.2f-%.2f] taille %.2f (ADR %.2f) spread %.2f" % (
                "BUY" if is_buy else "SELL", lots, entry, sl, fvg["id"], fvg["bottom"], fvg["top"],
                size, a, spread)
            if self.send(req, what):
                if DRY_RUN:
                    self.dry_used.add(fvg["id"])
                else:
                    self.state["used_fvgs"].append(fvg["id"])
                    self.save_state()
            return

    # ---- un tour de boucle -----------------------------------------------
    def step(self):
        now = datetime.now(PARIS)
        self.update_day(now)
        self.count_new_trades()

        if not in_session(now):
            if self.my_positions() or self.my_orders():
                self.flatten("hors session (cloture forcee %dh)" % SESSION_END_HOUR)
            return

        m15 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M15, 1, M15_BARS)
        self.manage_positions(m15)

        if self.check_kill_switch():
            return

        h1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 1, H1_BARS)
        d1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 1, ADR_PERIOD)
        if m15 is None or h1 is None or len(m15) < 10 or len(h1) < 10:
            log.warning("Historique indisponible (%s).", mt5.last_error())
            return
        bias = h1_bias(h1)
        self.manage_orders(bias)

        bar_time = int(m15[-1]["time"])
        if bar_time != self.last_bar_time:
            self.last_bar_time = bar_time
            a = adr(d1)
            log.info("Bougie M15 | biais H1 %s | ADR14 %s | FVG candidats %d | trades jour %d/%d",
                     {1: "HAUSSIER", -1: "BAISSIER", 0: "AUCUN"}[bias],
                     "%.2f" % a if a else "n/d", len(find_fvgs(m15, bias)),
                     self.state["trades_today"], MAX_TRADES_PER_DAY)

        self.try_entry(bias, m15, d1)

    def emergency_stop(self):
        log.critical("%d erreurs consecutives : fermeture des positions de l'EA et arret.",
                     MAX_CONSECUTIVE_ERRORS)
        try:
            if self.ensure_connection():
                self.flatten("arret d'urgence")
                left = len(self.my_positions()) + len(self.my_orders())
                if left and not DRY_RUN:
                    log.critical("%d position(s)/ordre(s) n'ont pas pu etre fermes : verifiez le terminal !", left)
            else:
                log.critical("Terminal injoignable : positions NON fermees, verifiez le terminal !")
        except Exception:
            log.exception("Echec de la fermeture d'urgence : verifiez le terminal !")

    def run(self):
        """Boucle incassable. Retourne un code de sortie."""
        log.info("Boucle demarree (toutes les %d s). Ctrl+C pour arreter.", LOOP_SECONDS)
        errors = 0
        next_heartbeat = 0.0
        while True:
            try:
                if time.time() >= next_heartbeat:
                    next_heartbeat = time.time() + HEARTBEAT_MINUTES * 60
                    self.heartbeat()
                # Une coupure de connexion n'est pas comptee comme une erreur :
                # l'EA attend le retour du terminal aussi longtemps qu'il le faut.
                if not self.ensure_connection():
                    time.sleep(RECONNECT_PAUSE_SECONDS)
                    continue
                self.step()
                errors = 0
                time.sleep(LOOP_SECONDS)
            except (KeyboardInterrupt, FatalError):
                raise
            except Exception:
                errors += 1
                log.exception("Erreur dans la boucle (%d/%d consecutives). Reprise dans %d s.",
                              errors, MAX_CONSECUTIVE_ERRORS, ERROR_PAUSE_SECONDS)
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    self.emergency_stop()
                    return 5
                time.sleep(ERROR_PAUSE_SECONDS)


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    if AUTO_DETACH and "--child" not in sys.argv and os.name == "nt":
        detach()
        return 0

    setup_logging()
    lock = acquire_lock()
    if lock is None:
        log.error("Un autre EA tourne deja (port %d occupe). Arret.", LOCK_PORT)
        return 1

    log.info("=" * 70)
    log.info("Demarrage XAU FVG EA | DRY_RUN=%s DEMO_ONLY=%s MAGIC=%s", DRY_RUN, DEMO_ONLY, MAGIC)
    try:
        load_libs()
    except ImportError as e:
        log.critical("Librairie manquante : %s (lancez setup_mt5_python.bat)", e)
        return 1

    if not connect():
        return 2
    try:
        if not check_account():
            return 3
        symbol = resolve_symbol()
        if symbol is None:
            log.critical("Symbole %s introuvable chez ce broker.", SYMBOL_BASE)
            return 4
        si = mt5.symbol_info(symbol)
        log.info("Symbole : %s | digits %d | stops_level %d pts | lot min %.2f pas %.2f",
                 symbol, si.digits, si.trade_stops_level, si.volume_min, si.volume_step)
        code = EA(symbol).run()
    except KeyboardInterrupt:
        log.info("Arret demande (Ctrl+C). Positions laissees avec leur SL.")
        code = 0
    except FatalError as e:
        log.critical("Arret definitif : %s", e)
        code = 3
    finally:
        mt5.shutdown()
        lock.close()
    log.info("EA arrete (code %s).", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
