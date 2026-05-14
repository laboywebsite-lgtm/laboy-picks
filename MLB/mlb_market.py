"""
nba_market.py — Market Signals para Laboy Picks
================================================
Obtiene señales de dinero inteligente (sharp money) desde:
  • sportsbettingdime.com  → public bet % y money %
  • actionnetwork.com      → movimientos de línea (opening vs current)

Señales detectadas:
  1. Reverse Line Movement (RLM): público >70% en un lado, línea se mueve en su contra
  2. Money vs. Ticket Split: diferencia >12% entre money% y ticket% en el lado menos popular
  3. Steam Move: línea se movió ≥2.0 puntos desde apertura

Cada señal vale 1 punto. Signal strength:
  0 → NEUTRAL  (solo el modelo decide)
  1 → WEAK     (leve confirmación)
  2 → MODERATE (buena confirmación)
  3 → STRONG   (sharps y modelo alineados — pick sólido)

Uso:
    from nba_market import fetch_market_signals, sharp_confirm

    signals = fetch_market_signals(sport="nba")   # también "mlb"
    conf = sharp_confirm(signals, "TOR_CLE", "spread", side="AWAY")
    # → {"lean": "AWAY", "strength": 2, "signals": ["RLM", "MONEY_SPLIT"], "confirm": True}
"""

import re
import json
import time
import unicodedata
from datetime import date as _date

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ── Constantes ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

TIMEOUT = 10   # segundos

# Threshold para señales
RLM_PUBLIC_THRESHOLD  = 70.0   # % de tickets para considerar "público pesado"
MONEY_SPLIT_MIN_DIFF  = 12.0   # diferencia mínima money% vs ticket% para activar señal
STEAM_MOVE_MIN        = 2.0    # puntos de movimiento para considerar steam

# ── Normalización de nombres ───────────────────────────────────────────────────

# Mapa de nombres completos / nicknames → abreviatura ESPN
_NAME_TO_ABB = {
    # NBA
    "HAWKS": "ATL", "CELTICS": "BOS", "NETS": "BKN", "HORNETS": "CHA",
    "BULLS": "CHI", "CAVALIERS": "CLE", "MAVERICKS": "DAL", "NUGGETS": "DEN",
    "PISTONS": "DET", "WARRIORS": "GSW", "ROCKETS": "HOU", "PACERS": "IND",
    "CLIPPERS": "LAC", "LAKERS": "LAL", "GRIZZLIES": "MEM", "HEAT": "MIA",
    "BUCKS": "MIL", "TIMBERWOLVES": "MIN", "PELICANS": "NOP", "KNICKS": "NYK",
    "THUNDER": "OKC", "MAGIC": "ORL", "76ERS": "PHI", "SIXERS": "PHI",
    "SUNS": "PHX", "TRAILBLAZERS": "POR", "BLAZERS": "POR", "KINGS": "SAC",
    "SPURS": "SAS", "RAPTORS": "TOR", "JAZZ": "UTA", "WIZARDS": "WAS",
    "TWOLVES": "MIN",
    # MLB
    "DIAMONDBACKS": "ARI", "D-BACKS": "ARI", "BRAVES": "ATL", "ORIOLES": "BAL",
    "RED SOX": "BOS", "CUBS": "CHC", "WHITE SOX": "CWS", "REDS": "CIN",
    "GUARDIANS": "CLE", "ROCKIES": "COL", "TIGERS": "DET", "ASTROS": "HOU",
    "ROYALS": "KC", "ANGELS": "LAA", "DODGERS": "LAD", "MARLINS": "MIA",
    "BREWERS": "MIL", "TWINS": "MIN", "METS": "NYM", "YANKEES": "NYY",
    "ATHLETICS": "OAK", "PHILLIES": "PHI", "PIRATES": "PIT", "PADRES": "SD",
    "GIANTS": "SF", "MARINERS": "SEA", "CARDINALS": "STL", "RAYS": "TB",
    "RANGERS": "TEX", "BLUE JAYS": "TOR", "NATIONALS": "WAS",
}

def _strip(s):
    s = ''.join(c for c in unicodedata.normalize('NFD', str(s).upper())
                if unicodedata.category(c) != 'Mn')
    return s.strip()

def _name_to_abb(name):
    s = _strip(name)
    if s in _NAME_TO_ABB:
        return _NAME_TO_ABB[s]
    for k, v in _NAME_TO_ABB.items():
        if k in s or s in k:
            return v
    return s[:3]  # fallback: primeras 3 letras


# ── sportsbettingdime.com ─────────────────────────────────────────────────────

_SBD_ENDPOINTS = [
    # Endpoint API conocido (puede cambiar con actualizaciones del sitio)
    "https://www.sportsbettingdime.com/wp-json/public-betting/v1/odds?sport={sport}",
    # Fallback HTML
    "https://www.sportsbettingdime.com/{sport}/public-betting-action/",
]

def _fetch_sbd(sport="nba"):
    """
    Intenta obtener datos de SBD. Retorna lista de juegos con bet/money %.
    Formato raw de SBD (aproximado — puede variar con actualizaciones del sitio):
    [
      {
        "away_team": "Toronto Raptors",
        "home_team": "Cleveland Cavaliers",
        "spread": {"away_bets": 35, "home_bets": 65, "away_money": 52, "home_money": 48},
        "ml":     {"away_bets": 30, "home_bets": 70, "away_money": 44, "home_money": 56},
        "total":  {"over_bets": 48, "under_bets": 52, "over_money": 55, "under_money": 45},
      }, ...
    ]
    """
    if not _HAS_REQUESTS:
        return []

    sport_slug = sport.lower()
    games = []

    # 1. Intentar API JSON
    api_url = f"https://www.sportsbettingdime.com/wp-json/public-betting/v1/odds?sport={sport_slug}"
    try:
        r = _requests.get(api_url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and r.headers.get('content-type','').startswith('application/json'):
            data = r.json()
            games = _parse_sbd_json(data)
            if games:
                return games
    except Exception:
        pass

    # 2. Buscar JSON embebido en el HTML
    html_url = f"https://www.sportsbettingdime.com/{sport_slug}/public-betting-action/"
    try:
        r = _requests.get(html_url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            # Buscar window.__INITIAL_STATE__ o similar
            patterns = [
                r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                r'window\.__NEXT_DATA__\s*=\s*({.*?});',
                r'"publicBetting"\s*:\s*(\[.*?\])',
                r'"games"\s*:\s*(\[.*?\])',
            ]
            for pat in patterns:
                m = re.search(pat, r.text, re.DOTALL)
                if m:
                    try:
                        obj = json.loads(m.group(1))
                        games = _parse_sbd_json(obj)
                        if games:
                            return games
                    except Exception:
                        pass
    except Exception:
        pass

    return []


def _parse_sbd_json(data):
    """Intenta parsear la respuesta de SBD en distintos formatos."""
    games = []
    if not data:
        return games

    # Si es lista directa de juegos
    if isinstance(data, list):
        items = data
    # Si es dict con key 'games', 'data', 'events', etc.
    elif isinstance(data, dict):
        for key in ('games', 'data', 'events', 'matchups', 'results'):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        else:
            return games
    else:
        return games

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            # Intentar extraer nombres de equipos
            away = (item.get('away_team') or item.get('awayTeam') or
                    item.get('away') or item.get('visitor', ''))
            home = (item.get('home_team') or item.get('homeTeam') or
                    item.get('home', ''))
            if not away or not home:
                continue

            away_abb = _name_to_abb(str(away))
            home_abb = _name_to_abb(str(home))
            key = f"{away_abb}_{home_abb}"

            # Spread
            spread = item.get('spread', item.get('ats', {})) or {}
            # ML
            ml = item.get('ml', item.get('moneyline', item.get('h2h', {}))) or {}
            # Total
            total = item.get('total', item.get('ou', {})) or {}

            def _pct(obj, *keys):
                for k in keys:
                    v = obj.get(k)
                    if v is not None:
                        try:
                            return float(str(v).replace('%', ''))
                        except Exception:
                            pass
                return None

            games.append({
                "key": key,
                "away_abb": away_abb,
                "home_abb": home_abb,
                "spread": {
                    "tickets_away":  _pct(spread, 'away_bets', 'awayBets', 'away_tickets', 'away'),
                    "tickets_home":  _pct(spread, 'home_bets', 'homeBets', 'home_tickets', 'home'),
                    "money_away":    _pct(spread, 'away_money', 'awayMoney'),
                    "money_home":    _pct(spread, 'home_money', 'homeMoney'),
                },
                "ml": {
                    "tickets_away":  _pct(ml, 'away_bets', 'awayBets', 'away'),
                    "tickets_home":  _pct(ml, 'home_bets', 'homeBets', 'home'),
                    "money_away":    _pct(ml, 'away_money', 'awayMoney'),
                    "money_home":    _pct(ml, 'home_money', 'homeMoney'),
                },
                "total": {
                    "tickets_over":  _pct(total, 'over_bets', 'overBets', 'over'),
                    "tickets_under": _pct(total, 'under_bets', 'underBets', 'under'),
                    "money_over":    _pct(total, 'over_money', 'overMoney'),
                    "money_under":   _pct(total, 'under_money', 'underMoney'),
                },
            })
        except Exception:
            continue

    return games


# ── actionnetwork.com ─────────────────────────────────────────────────────────

_AN_SPORT_IDS = {"nba": 4, "mlb": 3, "nfl": 1, "nhl": 6}

def _fetch_action_network(sport="nba"):
    """
    Obtiene movimientos de línea desde actionnetwork.com
    Retorna lista de juegos con opening/current lines.
    """
    if not _HAS_REQUESTS:
        return []

    sport_id = _AN_SPORT_IDS.get(sport.lower(), 4)
    games = []

    endpoints = [
        f"https://api.actionnetwork.com/web/v1/nba/matchups?period_type=full",
        f"https://api.actionnetwork.com/web/v1/nba/odds?sport_id={sport_id}&market=spread",
        f"https://api.actionnetwork.com/web/v1/nba/games",
    ]

    for url in endpoints:
        try:
            r = _requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                parsed = _parse_action_json(data)
                if parsed:
                    return parsed
        except Exception:
            continue

    # Fallback: HTML scraping de actionnetwork.com
    try:
        url = f"https://www.actionnetwork.com/{sport}/public-betting-percentages"
        r = _requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            patterns = [
                r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                r'window\.__NEXT_DATA__\s*=\s*({.*?});',
                r'"games"\s*:\s*(\[.*?\])',
                r'"matchups"\s*:\s*(\[.*?\])',
            ]
            for pat in patterns:
                m = re.search(pat, r.text, re.DOTALL)
                if m:
                    try:
                        obj = json.loads(m.group(1))
                        parsed = _parse_action_json(obj)
                        if parsed:
                            return parsed
                    except Exception:
                        pass
    except Exception:
        pass

    return []


def _parse_action_json(data):
    """Parsea respuesta de ActionNetwork para extraer movimientos de línea."""
    games = []
    if not data:
        return games

    # Buscar lista de juegos/matchups
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ('games', 'matchups', 'data', 'events', 'results'):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    if not items:
        return games

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            # Nombres de equipos
            away = (item.get('away_team', {}) or {})
            home = (item.get('home_team', {}) or {})

            if isinstance(away, dict):
                away_name = away.get('name', away.get('full_name', away.get('abbr', '')))
            else:
                away_name = str(away)
            if isinstance(home, dict):
                home_name = home.get('name', home.get('full_name', home.get('abbr', '')))
            else:
                home_name = str(home)

            if not away_name or not home_name:
                continue

            away_abb = _name_to_abb(away_name)
            home_abb = _name_to_abb(home_name)
            key = f"{away_abb}_{home_abb}"

            # Líneas (spread)
            odds = item.get('odds', item.get('lines', item.get('books', [])))
            spread_open = spread_cur = total_open = total_cur = None

            # Intentar extraer opening/current del consenso
            consensus = item.get('consensus', {}) or {}
            if consensus:
                spread_open = _safe_float(consensus.get('spread_open', consensus.get('open_spread')))
                spread_cur  = _safe_float(consensus.get('spread',      consensus.get('current_spread')))
                total_open  = _safe_float(consensus.get('total_open',  consensus.get('open_total')))
                total_cur   = _safe_float(consensus.get('total',       consensus.get('current_total')))

            # Buscar en books si consensus no tiene datos
            if spread_open is None and isinstance(odds, list):
                for book in odds:
                    if not isinstance(book, dict):
                        continue
                    so = _safe_float(book.get('spread_open', book.get('open_spread')))
                    sc = _safe_float(book.get('spread',      book.get('spread_current')))
                    if so is not None and sc is not None:
                        spread_open, spread_cur = so, sc
                    to = _safe_float(book.get('total_open', book.get('open_total')))
                    tc = _safe_float(book.get('total',      book.get('total_current')))
                    if to is not None and tc is not None:
                        total_open, total_cur = to, tc
                    if spread_open is not None and total_open is not None:
                        break

            games.append({
                "key":          key,
                "away_abb":     away_abb,
                "home_abb":     home_abb,
                "spread_open":  spread_open,
                "spread_cur":   spread_cur,
                "total_open":   total_open,
                "total_cur":    total_cur,
            })
        except Exception:
            continue

    return games


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(str(v).replace('%', ''))
    except Exception:
        return None


# ── Caché en memoria (evita refetches múltiples por ejecución) ────────────────

_CACHE = {}
_CACHE_TS = {}
_CACHE_TTL = 300   # 5 minutos


def _cached(key, fn, *args, **kwargs):
    now = time.time()
    if key in _CACHE and now - _CACHE_TS.get(key, 0) < _CACHE_TTL:
        return _CACHE[key]
    result = fn(*args, **kwargs)
    _CACHE[key] = result
    _CACHE_TS[key] = now
    return result


# ── API Pública ───────────────────────────────────────────────────────────────

def fetch_market_signals(sport="nba"):
    """
    Fetch y unifica señales de SBD + ActionNetwork.

    Retorna dict:  {game_key: {"sbd": {...}, "an": {...}}}
    game_key = "AWAY_ABB_HOME_ABB"  (ej: "TOR_CLE")
    """
    sbd_raw = _cached(f"sbd_{sport}", _fetch_sbd, sport)
    an_raw  = _cached(f"an_{sport}",  _fetch_action_network, sport)

    # Indexar por game_key
    sbd_map = {g["key"]: g for g in sbd_raw}
    an_map  = {g["key"]: g for g in an_raw}

    all_keys = set(sbd_map) | set(an_map)
    result = {}
    for k in all_keys:
        result[k] = {
            "sbd": sbd_map.get(k),
            "an":  an_map.get(k),
        }
    return result


def sharp_confirm(signals, game_key, bet_type, side):
    """
    Evalúa si hay señal de sharp money que CONFIRMA o CONTRADICE el pick del modelo.

    Parámetros:
        signals  : dict devuelto por fetch_market_signals()
        game_key : "AWAY_ABB_HOME_ABB"  (ej: "TOR_CLE")
        bet_type : "spread" | "ml" | "over" | "under"
        side     : "AWAY" | "HOME" | "OVER" | "UNDER"

    Retorna dict:
        {
          "lean":     "AWAY"|"HOME"|"OVER"|"UNDER"|"NEUTRAL",
          "strength": 0-3,           # cuántas señales confirmaron
          "signals":  ["RLM", ...],  # señales que dispararon
          "confirm":  True/False,    # ¿el mercado CONFIRMA el pick del modelo?
          "fade":     True/False,    # ¿el mercado va EN CONTRA del pick?
          "available": True/False,   # ¿había datos de mercado?
        }
    """
    game_data = signals.get(game_key) or signals.get(_flip_key(game_key))
    if not game_data:
        return _no_data()

    sbd = game_data.get("sbd") or {}
    an  = game_data.get("an")  or {}

    fired_signals = []
    lean_scores = {"AWAY": 0, "HOME": 0, "OVER": 0, "UNDER": 0}

    # ── Señal 1: Money vs Ticket Split ─────────────────────────────────────
    bet_key = bet_type if bet_type in ("spread", "ml") else "total"
    bets = sbd.get(bet_key, {}) or {}

    if bet_type in ("spread", "ml"):
        ta = bets.get("tickets_away")
        th = bets.get("tickets_home")
        ma = bets.get("money_away")
        mh = bets.get("money_home")

        if all(x is not None for x in (ta, th, ma, mh)):
            # Diferencia: si el money% supera al ticket% en un lado → sharps ahí
            diff_a = (ma - ta)   # positivo = más dinero que tickets en away
            diff_h = (mh - th)

            if diff_a >= MONEY_SPLIT_MIN_DIFF:
                lean_scores["AWAY"] += 1
                fired_signals.append("MONEY_SPLIT")
            elif diff_h >= MONEY_SPLIT_MIN_DIFF:
                lean_scores["HOME"] += 1
                if "MONEY_SPLIT" not in fired_signals:
                    fired_signals.append("MONEY_SPLIT")

    elif bet_type in ("over", "under"):
        to_ = bets.get("tickets_over")
        tu  = bets.get("tickets_under")
        mo  = bets.get("money_over")
        mu  = bets.get("money_under")

        if all(x is not None for x in (to_, tu, mo, mu)):
            diff_o = (mo - to_)
            diff_u = (mu - tu)

            if diff_o >= MONEY_SPLIT_MIN_DIFF:
                lean_scores["OVER"] += 1
                fired_signals.append("MONEY_SPLIT")
            elif diff_u >= MONEY_SPLIT_MIN_DIFF:
                lean_scores["UNDER"] += 1
                if "MONEY_SPLIT" not in fired_signals:
                    fired_signals.append("MONEY_SPLIT")

    # ── Señal 2: Reverse Line Movement (RLM) ────────────────────────────────
    spread_open = an.get("spread_open")
    spread_cur  = an.get("spread_cur")
    total_open  = an.get("total_open")
    total_cur   = an.get("total_cur")

    if bet_type in ("spread", "ml") and spread_open is not None and spread_cur is not None:
        # spread_open/cur = línea del HOME (positivo = home es favorito)
        line_moved = spread_cur - spread_open   # positivo = home más favorito
        ta = bets.get("tickets_home") or 50.0

        if ta >= RLM_PUBLIC_THRESHOLD and line_moved < -0.5:
            # Público en home pero línea cayó → sharps en AWAY
            lean_scores["AWAY"] += 1
            fired_signals.append("RLM")
        elif (100 - ta) >= RLM_PUBLIC_THRESHOLD and line_moved > 0.5:
            # Público en away pero línea subió → sharps en HOME
            lean_scores["HOME"] += 1
            if "RLM" not in fired_signals:
                fired_signals.append("RLM")

    if bet_type in ("over", "under") and total_open is not None and total_cur is not None:
        total_moved = total_cur - total_open   # negativo = línea bajó → sharps en UNDER
        to_ = bets.get("tickets_over") or 50.0

        if to_ >= RLM_PUBLIC_THRESHOLD and total_moved < -0.5:
            lean_scores["UNDER"] += 1
            fired_signals.append("RLM")
        elif (100 - to_) >= RLM_PUBLIC_THRESHOLD and total_moved > 0.5:
            lean_scores["OVER"] += 1
            if "RLM" not in fired_signals:
                fired_signals.append("RLM")

    # ── Señal 3: Steam Move ──────────────────────────────────────────────────
    if bet_type in ("spread", "ml") and spread_open is not None and spread_cur is not None:
        move = spread_cur - spread_open
        if abs(move) >= STEAM_MOVE_MIN:
            if move > 0:   # línea subió → sharps en HOME (home más favorito)
                lean_scores["HOME"] += 1
            else:          # línea bajó → sharps en AWAY
                lean_scores["AWAY"] += 1
            if "STEAM" not in fired_signals:
                fired_signals.append("STEAM")

    if bet_type in ("over", "under") and total_open is not None and total_cur is not None:
        move = total_cur - total_open
        if abs(move) >= STEAM_MOVE_MIN:
            if move > 0:
                lean_scores["OVER"] += 1
            else:
                lean_scores["UNDER"] += 1
            if "STEAM" not in fired_signals:
                fired_signals.append("STEAM")

    # ── Lean dominante ──────────────────────────────────────────────────────
    max_score = max(lean_scores.values())
    if max_score == 0:
        lean = "NEUTRAL"
        strength = 0
    else:
        candidates = [k for k, v in lean_scores.items() if v == max_score]
        lean = candidates[0]
        strength = max_score

    confirm = (lean == side or lean == "NEUTRAL")
    fade    = (lean != side and lean != "NEUTRAL")

    return {
        "lean":      lean,
        "strength":  strength,
        "signals":   fired_signals,
        "confirm":   confirm,
        "fade":      fade,
        "available": bool(sbd or an),
        # Data raw para debug
        "_scores":   lean_scores,
    }


def _flip_key(key):
    """TOR_CLE → CLE_TOR — por si el juego está indexado al revés."""
    parts = key.split("_")
    if len(parts) == 2:
        return f"{parts[1]}_{parts[0]}"
    return key


def _no_data():
    return {
        "lean":      "NEUTRAL",
        "strength":  0,
        "signals":   [],
        "confirm":   True,    # sin datos = no fades
        "fade":      False,
        "available": False,
        "_scores":   {},
    }


# ── Utilidad de display ───────────────────────────────────────────────────────

def format_signal(conf):
    """
    Devuelve string corto para mostrar en el pick card.
    Ej: "🔥 SHARP (RLM+MONEY)" | "⚠️ FADE RISK" | "— sin datos"
    """
    if not conf.get("available"):
        return "📊 sin datos mercado"
    if conf["fade"]:
        sigs = "+".join(conf["signals"])
        return f"⚠️  FADE RISK ({conf['lean']} {sigs})"
    if conf["strength"] >= 2:
        sigs = "+".join(conf["signals"])
        return f"🔥 SHARP CONFIRMED ({sigs})"
    if conf["strength"] == 1:
        sigs = "+".join(conf["signals"])
        return f"✅ leve confirmación ({sigs})"
    return "➖ mercado neutral"


# ── CLI de prueba ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sport = sys.argv[1] if len(sys.argv) > 1 else "nba"
    print(f"\n🔍 Fetching market signals para {sport.upper()}...\n")

    sigs = fetch_market_signals(sport=sport)
    if not sigs:
        print("  ⚠️  No se pudo obtener datos de mercado.")
        print("  Verifica conexión y que los sitios estén disponibles.\n")
        sys.exit(0)

    print(f"  ✅ {len(sigs)} juegos encontrados\n")
    for key, data in list(sigs.items())[:5]:
        sbd = data.get("sbd") or {}
        an  = data.get("an") or {}
        print(f"  {key}:")
        if sbd:
            sp = sbd.get("spread", {})
            print(f"    Spread tickets: AWAY {sp.get('tickets_away')}% / HOME {sp.get('tickets_home')}%")
            print(f"    Spread money:   AWAY {sp.get('money_away')}%  / HOME {sp.get('money_home')}%")
        if an:
            print(f"    Spread open: {an.get('spread_open')} → current: {an.get('spread_cur')}")
            print(f"    Total  open: {an.get('total_open')} → current: {an.get('total_cur')}")
        print()
