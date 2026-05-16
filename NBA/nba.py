#!/usr/bin/env python3
"""
NBA Sports Betting Analytics Tool
Modeled after mlb.py, adapted for basketball
"""

import os
import sys
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import math

# Optional imports with graceful fallback
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Market signals (sharp money / line movement)
try:
    from nba_market import fetch_market_signals as _fetch_market_signals
    from nba_market import sharp_confirm as _sharp_confirm
    from nba_market import format_signal as _format_market_signal
    _HAS_MARKET = True
except ImportError:
    _HAS_MARKET = False
    def _fetch_market_signals(sport="nba"): return {}
    def _sharp_confirm(signals, key, bet_type, side):
        return {"lean":"NEUTRAL","strength":0,"signals":[],"confirm":True,"fade":False,"available":False}
    def _format_market_signal(conf): return "📊 nba_market.py no disponible"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE         = os.path.join(SCRIPT_DIR, "nba_picks_log.json")
MODEL_PICKS_FILE = os.path.join(SCRIPT_DIR, "nba_model_picks.json")
NBA_STATS_CACHE  = os.path.join(SCRIPT_DIR, "nba_stats_cache.json")
MANUAL_GAMES_FILE = os.path.join(SCRIPT_DIR, "nba_manual_games.json")
PLAYOFF_GAME_LOG_CACHE  = os.path.join(SCRIPT_DIR, "nba_playoff_game_log.json")
MANUAL_MARKET_FILE = os.path.join(SCRIPT_DIR, "nba_manual_market.json")

# ── GitHub Pages publish config ───────────────────────────────
GITHUB_PAGES_REPO = os.environ.get(
    "NBA_GITHUB_REPO",
    os.path.join(os.path.expanduser("~"), "repos", "nba-picks")
)
GITHUB_PAGES_URL  = "https://laboywebsite-lgtm.github.io/nba-picks"
DASHBOARD_TOKEN   = os.environ.get("NBA_DASHBOARD_TOKEN", "Lb9x3Kw")

# ── TARGET_DATE: primer arg con formato YYYY-MM-DD, si no → hoy ──────────────
_date_args = [a for a in sys.argv[1:] if re.match(r"^\d{4}-\d{2}-\d{2}$", a)]
TARGET_DATE = _date_args[0] if _date_args else datetime.now().strftime("%Y-%m-%d")

# ── Flags de modo (module-level para que todos los comandos los vean) ─────────
PUBLISH_MODE     = "--publish"     in sys.argv
EXPORT_LOG_MODE  = "--export-log"  in sys.argv
FORCE_EXPORT     = "--force-export" in sys.argv   # sobreescribir picks HTML aunque ya exista
PENDING_MODE     = "--pending"     in sys.argv    # solo picks sin gradear (útil para --grade)

# NBA Teams
TEAM_ABB = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

ESPN_ABB = {
    "ATL":"atl","BOS":"bos","BKN":"bkn","CHA":"cha","CHI":"chi","CLE":"cle",
    "DAL":"dal","DEN":"den","DET":"det","GSW":"gs","HOU":"hou","IND":"ind",
    "LAC":"lac","LAL":"lal","MEM":"mem","MIA":"mia","MIL":"mil","MIN":"min",
    "NOP":"no","NYK":"ny","OKC":"okc","ORL":"orl","PHI":"phi","PHX":"phx",
    "POR":"por","SAC":"sac","SAS":"sa","TOR":"tor","UTA":"utah","WAS":"wsh",
}

TEAM_COLORS = {
    "ATL":"#C8102E","BOS":"#007A33","BKN":"#94a3b8","CHA":"#1D1160",
    "CHI":"#CE1141","CLE":"#860038","DAL":"#00538C","DEN":"#4f7942",
    "DET":"#C8102E","GSW":"#1D428A","HOU":"#CE1141","IND":"#c8952a",
    "LAC":"#c0392b","LAL":"#552583","MEM":"#5D76A9","MIA":"#98002E",
    "MIL":"#00471B","MIN":"#0C2340","NOP":"#0C2340","NYK":"#c0602a",
    "OKC":"#007AC1","ORL":"#0077C0","PHI":"#006BB6","PHX":"#1D1160",
    "POR":"#c0393e","SAC":"#5A2D81","SAS":"#7a8fa0","TOR":"#CE1141",
    "UTA":"#002B5C","WAS":"#002B5C",
}

TEAM_NICKNAMES = {
    "ATL":"HAWKS",   "BOS":"CELTICS",  "BKN":"NETS",      "CHA":"HORNETS",
    "CHI":"BULLS",   "CLE":"CAVS",     "DAL":"MAVS",      "DEN":"NUGGETS",
    "DET":"PISTONS", "GSW":"WARRIORS", "HOU":"ROCKETS",   "IND":"PACERS",
    "LAC":"CLIPPERS","LAL":"LAKERS",   "MEM":"GRIZZLIES", "MIA":"HEAT",
    "MIL":"BUCKS",   "MIN":"WOLVES",   "NOP":"PELICANS",  "NYK":"KNICKS",
    "OKC":"THUNDER", "ORL":"MAGIC",    "PHI":"76ERS",     "PHX":"SUNS",
    "POR":"BLAZERS", "SAC":"KINGS",    "SAS":"SPURS",     "TOR":"RAPTORS",
    "UTA":"JAZZ",    "WAS":"WIZARDS",
}

def _fmt_pick(p):
    """'O 215.5' → 'Over 215.5', 'U 215' → 'Under 215', 'MIA +5.5' → 'Heat +5.5'"""
    import re as _re
    p = str(p).strip()
    if _re.match(r'^O\s+\d', p):  return "Over "  + p[1:].strip()
    if _re.match(r'^U\s+\d', p):  return "Under " + p[1:].strip()
    parts = p.split()
    if parts and parts[0].upper() in TEAM_NICKNAMES:
        return TEAM_NICKNAMES[parts[0].upper()] + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")
    return p

# League averages (2024-25 season)
LEAGUE_AVG_ORTG = 115.0
LEAGUE_AVG_DRTG = 115.0
LEAGUE_AVG_PACE = 99.0

# Odds API
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "524c2c3a534298ebbd212c6dc621a458")

# ESPN API returns short abbreviations for some teams (GS, NO, NY, SA, UTAH, WSH…)
# Map those back to our internal 3-letter codes.
ESPN_API_TO_INTERNAL = {
    "GS":   "GSW",
    "NO":   "NOP",
    "NY":   "NYK",
    "SA":   "SAS",
    "UTAH": "UTA",
    "WSH":  "WAS",
    "WST":  "WAS",
    "PHO":  "PHX",
    "BKN":  "BKN",
    "CHA":  "CHA",
    "NOR":  "NOP",
    "GGS":  "GSW",
}

# ============================================================================
# STATS FETCHING & CACHING
# ============================================================================

def fetch_nba_stats(season_year="2026", season_type="Regular Season"):
    """
    Fetch ORTG, DRTG y PACE por equipo.

    season_type: "Regular Season" | "Playoffs"

    Fuente primaria: NBA.com via nba_api (oficial, sin Cloudflare, gratis).
      Endpoint: LeagueDashTeamStats (Advanced) → OFF_RATING, DEF_RATING, PACE
    Fallback:  Basketball-Reference scraping (puede fallar por 403/Cloudflare).

    Retorna {ESPN_ABB: {"ortg": X, "drtg": Y, "pace": Z, "net": N, "gp": G}}
    """
    # NBA.com abreviaciones → ESPN abreviaciones (nba_api usa NBA.com style)
    NBACOM_TO_ESPN = {
        "ATL":"ATL","BOS":"BOS","BKN":"BKN","CHA":"CHA","CHI":"CHI","CLE":"CLE",
        "DAL":"DAL","DEN":"DEN","DET":"DET","GSW":"GSW","HOU":"HOU","IND":"IND",
        "LAC":"LAC","LAL":"LAL","MEM":"MEM","MIA":"MIA","MIL":"MIL","MIN":"MIN",
        "NOP":"NOP","NYK":"NYK","OKC":"OKC","ORL":"ORL","PHI":"PHI","PHX":"PHX",
        "POR":"POR","SAC":"SAC","SAS":"SAS","TOR":"TOR","UTA":"UTA","WAS":"WAS",
    }
    # BBRef → ESPN (fallback)
    BBR_TO_ESPN = {
        "ATL":"ATL","BOS":"BOS","BRK":"BKN","CHO":"CHA","CHI":"CHI","CLE":"CLE",
        "DAL":"DAL","DEN":"DEN","DET":"DET","GSW":"GSW","HOU":"HOU","IND":"IND",
        "LAC":"LAC","LAL":"LAL","MEM":"MEM","MIA":"MIA","MIL":"MIL","MIN":"MIN",
        "NOP":"NOP","NYK":"NYK","OKC":"OKC","ORL":"ORL","PHI":"PHI","PHO":"PHX",
        "POR":"POR","SAC":"SAC","SAS":"SAS","TOR":"TOR","UTA":"UTA","WAS":"WAS",
    }

    # ── Convert season_year to NBA API format: "2026" → "2025-26" ───────────
    yr = int(season_year)
    season_str = f"{yr - 1}-{str(yr)[2:]}"   # e.g. "2025-26"

    stats = {}

    # ══════════════════════════════════════════════════════════════════════════
    # PRIMARY: nba_api  (NBA.com official — no Cloudflare, no scraping)
    # ══════════════════════════════════════════════════════════════════════════
    _nba_api_ok = False
    try:
        from nba_api.stats.endpoints import LeagueDashTeamStats   # type: ignore
        print(f"  📡 NBA.com API — LeagueDashTeamStats (Advanced) temporada {season_str} …")

        # nba_api parameter names vary slightly by version; try both styles
        _endpoint = None
        _tried = []
        _st = season_type   # "Regular Season" | "Playoffs"
        for _kwargs in [
            # Style A: newer nba_api (measure_type_detailed_defense)
            {"season": season_str, "measure_type_detailed_defense": "Advanced",
             "season_type_all_star": _st, "timeout": 60},
            # Style B: older nba_api (measure_type_simple)
            {"season": season_str, "measure_type_simple": "Advanced",
             "season_type_all_star": _st, "timeout": 60},
            # Style C: no measure type kwarg — grab all result sets and find the right one
            {"season": season_str, "season_type_all_star": _st, "timeout": 60},
            # Style D: no season_type (fallback si la versión no lo soporta)
            {"season": season_str, "measure_type_detailed_defense": "Advanced", "timeout": 60},
        ]:
            try:
                _endpoint = LeagueDashTeamStats(**_kwargs)
                _tried.append("ok:" + str(list(_kwargs.keys())))
                break
            except TypeError as _te:
                _tried.append("fail:" + str(_te))
                _endpoint = None

        if _endpoint is None:
            raise RuntimeError(f"No se pudo instanciar LeagueDashTeamStats. Intentos: {_tried}")

        # nba_api returns multiple DataFrames per call.
        # Advanced DF has OFF_RATING/DEF_RATING/PACE but NOT TEAM_ABBREVIATION.
        # Base DF (or another DF) has TEAM_ABBREVIATION + TEAM_ID.
        # Strategy: build TEAM_ID→ABB map from any DF that has it, then join.
        _dfs = _endpoint.get_data_frames()

        # Normalise all DFs to uppercase column names
        _dfs_up = []
        for _d in _dfs:
            if len(_d) == 0:
                continue
            _dc = _d.copy()
            _dc.columns = [c.upper() for c in _dc.columns]
            _dfs_up.append(_dc)

        # ── Build TEAM_ID → abbreviation mapping ─────────────────────────────
        # Also build TEAM_NAME → abbreviation as fallback
        _id_to_abb  = {}   # {team_id_int: "BOS"}
        _name_to_abb = {}  # {"Boston Celtics": "BOS"}

        # Reverse-lookup from our own TEAM_ABB dict
        _full_name_to_abb = {v.upper(): k for k, v in TEAM_ABB.items()}

        for _d in _dfs_up:
            _cols = set(_d.columns)
            _has_id  = "TEAM_ID" in _cols
            _has_abb = "TEAM_ABBREVIATION" in _cols
            _has_nm  = "TEAM_NAME" in _cols
            if _has_id and _has_abb:
                for _, _r in _d.iterrows():
                    _id_to_abb[int(_r["TEAM_ID"])] = str(_r["TEAM_ABBREVIATION"]).upper().strip()
            if _has_nm:
                for _, _r in _d.iterrows():
                    _nm = str(_r["TEAM_NAME"]).upper().strip()
                    # Try abbreviation from same row first
                    if _has_abb:
                        _name_to_abb[_nm] = str(_r["TEAM_ABBREVIATION"]).upper().strip()
                    # Else map via our local dict
                    elif _nm in _full_name_to_abb:
                        _name_to_abb[_nm] = _full_name_to_abb[_nm]

        def _resolve_abb(row_d):
            """Return NBA.com abbreviation from a DataFrame row."""
            if "TEAM_ABBREVIATION" in row_d.index:
                return str(row_d["TEAM_ABBREVIATION"]).upper().strip()
            if "TEAM_ID" in row_d.index:
                _tid = int(row_d["TEAM_ID"])
                if _tid in _id_to_abb:
                    return _id_to_abb[_tid]
            if "TEAM_NAME" in row_d.index:
                _nm = str(row_d["TEAM_NAME"]).upper().strip()
                if _nm in _name_to_abb:
                    return _name_to_abb[_nm]
                if _nm in _full_name_to_abb:
                    return _full_name_to_abb[_nm]
            return None

        # ── Pick the best DF for each stat ───────────────────────────────────
        _ADV_COLS  = {"OFF_RATING", "E_OFF_RATING", "DEF_RATING", "E_DEF_RATING",
                      "NET_RATING", "E_NET_RATING", "PACE", "E_PACE"}

        df_adv  = None   # DataFrame with ratings
        for _d in _dfs_up:
            if _ADV_COLS & set(_d.columns):
                df_adv = _d
                break
        if df_adv is None:
            df_adv = _dfs_up[0] if _dfs_up else None

        if df_adv is None:
            raise ValueError("nba_api no retornó datos")

        # ── Column aliases ────────────────────────────────────────────────────
        def _first_col(df, *candidates):
            for c in candidates:
                if c in df.columns:
                    return c
            return None

        _c_ortg = _first_col(df_adv, "OFF_RATING", "E_OFF_RATING")
        _c_drtg = _first_col(df_adv, "DEF_RATING", "E_DEF_RATING")
        _c_net  = _first_col(df_adv, "NET_RATING",  "E_NET_RATING")
        _c_pace = _first_col(df_adv, "PACE",        "E_PACE", "PACE_PER40")
        # GP viene del df base o del mismo df_adv
        _c_gp   = _first_col(df_adv, "GP", "G", "GAMES_PLAYED")
        if _c_gp is None:
            # intentar en otro df si existe
            for _d2 in _dfs_up:
                _c_gp2 = _first_col(_d2, "GP", "G", "GAMES_PLAYED")
                if _c_gp2:
                    # merge GP por equipo
                    _gp_map = {}
                    for _, _r2 in _d2.iterrows():
                        _a2 = _resolve_abb(_r2)
                        if _a2:
                            _gp_map[NBACOM_TO_ESPN.get(_a2, _a2)] = int(_r2[_c_gp2])
                    break
            else:
                _gp_map = {}
        else:
            _gp_map = None   # lo leemos directo del df_adv

        for _, row in df_adv.iterrows():
            nba_abb = _resolve_abb(row)
            if not nba_abb:
                continue
            espn_abb = NBACOM_TO_ESPN.get(nba_abb, nba_abb)

            ortg = float(row[_c_ortg]) if _c_ortg else LEAGUE_AVG_ORTG
            drtg = float(row[_c_drtg]) if _c_drtg else LEAGUE_AVG_DRTG
            pace = float(row[_c_pace]) if _c_pace else LEAGUE_AVG_PACE
            net  = float(row[_c_net])  if _c_net  else round(ortg - drtg, 2)
            if _gp_map is not None:
                gp = _gp_map.get(espn_abb, 0)
            else:
                gp = int(row[_c_gp]) if _c_gp else 0

            stats[espn_abb] = {
                "ortg": round(ortg, 1),
                "drtg": round(drtg, 1),
                "pace": round(pace, 1),
                "net":  round(net,  2),
                "gp":   gp,
            }

        # Para playoffs solo hay 8-16 equipos; para regular season esperamos 30
        _min_expected = 8 if season_type == "Playoffs" else 20
        if len(stats) >= _min_expected:
            _nba_api_ok = True
            has_adv = bool(_c_ortg or _c_drtg)
            gp_ok   = any(v.get("gp", 0) > 0 for v in stats.values())
            print(f"  ✅ NBA.com API [{season_type}]: {len(stats)} equipos — "
                  f"{'ORtg/DRtg/Pace/Net' if has_adv else 'stats básicas'}"
                  f"{', GP ✅' if gp_ok else ''}")
        else:
            print(f"  ⚠️  NBA.com API retornó solo {len(stats)} equipos — intentando BBRef …")
            stats = {}

    except ImportError:
        print("  ⚠️  nba_api no instalado. Instala con: pip install nba_api")
        print("  🔄 Intentando Basketball-Reference como fallback …")
    except Exception as e:
        _err_str = str(e)
        if "timed out" in _err_str.lower() or "timeout" in _err_str.lower():
            print(f"  ⚠️  NBA.com API timeout — retrying once with longer timeout …")
            # Retry una vez con timeout más largo
            try:
                from nba_api.stats.endpoints import LeagueDashTeamStats  # type: ignore
                _endpoint2 = LeagueDashTeamStats(
                    season=season_str,
                    measure_type_detailed_defense="Advanced",
                    season_type_all_star=_st,
                    timeout=90
                )
                _dfs2 = _endpoint2.get_data_frames()
                if _dfs2 and len(_dfs2[0]) > 0:
                    # Re-run the full parsing — reuse existing logic via recursive call guard
                    print("  ✅ Retry NBA.com exitoso — procesando datos …")
                    # Use first df as df_adv proxy
                    import pandas as _pd
                    _df_r = _dfs2[0].copy()
                    _df_r.columns = [c.upper() for c in _df_r.columns]
                    for _, _row in _df_r.iterrows():
                        _nba_abb = None
                        if "TEAM_ABBREVIATION" in _df_r.columns:
                            _nba_abb = str(_row["TEAM_ABBREVIATION"]).upper().strip()
                        if not _nba_abb:
                            continue
                        _espn_abb = NBACOM_TO_ESPN.get(_nba_abb, _nba_abb)
                        def _fcol2(df, *cands):
                            for _c in cands:
                                if _c in df.columns:
                                    return _c
                            return None
                        _co = _fcol2(_df_r, "OFF_RATING", "E_OFF_RATING")
                        _cd = _fcol2(_df_r, "DEF_RATING", "E_DEF_RATING")
                        _cp = _fcol2(_df_r, "PACE", "E_PACE")
                        _cn = _fcol2(_df_r, "NET_RATING", "E_NET_RATING")
                        _cg = _fcol2(_df_r, "GP", "G", "GAMES_PLAYED")
                        _o = float(_row[_co]) if _co else LEAGUE_AVG_ORTG
                        _d = float(_row[_cd]) if _cd else LEAGUE_AVG_DRTG
                        _p = float(_row[_cp]) if _cp else LEAGUE_AVG_PACE
                        _n = float(_row[_cn]) if _cn else round(_o - _d, 2)
                        _g = int(_row[_cg]) if _cg else 0
                        stats[_espn_abb] = {"ortg": round(_o,1), "drtg": round(_d,1),
                                            "pace": round(_p,1), "net": round(_n,2), "gp": _g}
                    _min_e = 8 if season_type == "Playoffs" else 20
                    if len(stats) >= _min_e:
                        _nba_api_ok = True
                        print(f"  ✅ Retry NBA.com: {len(stats)} equipos cargados.")
                    else:
                        stats = {}
                        print(f"  ⚠️  Retry retornó solo {len(stats)} equipos → BBRef fallback …")
            except Exception as _e2:
                print(f"  ⚠️  Retry también falló: {_e2}")
                stats = {}
        else:
            print(f"  ⚠️  Error al obtener datos de NBA.com API: {e}")
        print("  🔄 Intentando Basketball-Reference como fallback …")
        if not _nba_api_ok:
            stats = {}

    # ══════════════════════════════════════════════════════════════════════════
    # FALLBACK: Basketball-Reference scraping
    # Aplica tanto a temporada regular como a playoffs.
    # Para playoffs: BBRef usa la URL /playoffs/NBA_{year}.html
    # ══════════════════════════════════════════════════════════════════════════
    if not _nba_api_ok:
        import bs4 as _bs4

        BBREF_HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.basketball-reference.com/",
            "Connection": "keep-alive",
        }

        def _get_soup(url):
            req = Request(url, headers=BBREF_HEADERS)
            with urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
            return BeautifulSoup(html, "html.parser"), html

        def _all_tables(soup, html_text):
            tables = list(soup.find_all("table"))
            for comment in soup.find_all(string=lambda t: isinstance(t, _bs4.Comment)):
                if "<table" in str(comment):
                    inner = BeautifulSoup(str(comment), "html.parser")
                    tables.extend(inner.find_all("table"))
            return tables

        def _parse_table(table, need_cols):
            thead = table.find("thead")
            if not thead:
                return None
            all_th = []
            for tr in thead.find_all("tr"):
                all_th.append([th.get_text(strip=True) for th in tr.find_all(["th","td"])])
            col_headers = all_th[-1] if all_th else []
            col_idx = {}
            for alias, candidates in need_cols.items():
                for i, h in enumerate(col_headers):
                    if any(c.lower() == h.lower() or c.lower() in h.lower() for c in candidates):
                        col_idx[alias] = i
                        break
            if not any(k in col_idx for k in ("ortg", "drtg", "pace")):
                return None
            team_idx = next(
                (i for i, h in enumerate(col_headers) if h.lower() in ("team","franchise")), 1
            )
            results = []
            tbody = table.find("tbody")
            for row in (tbody.find_all("tr") if tbody else []):
                cls = row.get("class", [])
                if "thead" in cls or "partial_table" in cls:
                    continue
                cells = row.find_all(["td","th"])
                if len(cells) < 3:
                    continue
                bbr_raw = cells[team_idx].get_text(strip=True)
                bbr_abb = bbr_raw.replace("*","").strip()
                if not bbr_abb or bbr_abb in ("Rk","Team","League Average",""):
                    continue
                espn_abb = BBR_TO_ESPN.get(bbr_abb, bbr_abb)
                row_data = {"espn_abb": espn_abb}
                for alias, idx in col_idx.items():
                    if idx < len(cells):
                        try:
                            row_data[alias] = float(cells[idx].get_text(strip=True))
                        except ValueError:
                            pass
                if "espn_abb" in row_data and len(row_data) > 1:
                    results.append(row_data)
            return results if results else None

        ORTG_NAMES = ["ORtg", "O-Rtg", "AdjO", "Adj ORtg", "Offensive Rating"]
        DRTG_NAMES = ["DRtg", "D-Rtg", "AdjD", "Adj DRtg", "Defensive Rating"]
        PACE_NAMES = ["Pace"]
        GP_NAMES   = ["G", "GP", "Games"]

        # URL base según season_type
        _is_po = (season_type == "Playoffs")
        _bbref_base = (f"https://www.basketball-reference.com/playoffs/NBA_{season_year}"
                       if _is_po else
                       f"https://www.basketball-reference.com/leagues/NBA_{season_year}")

        # Step 1: main page
        main_url = f"{_bbref_base}.html"
        print(f"  📡 BBRef {'Playoffs' if _is_po else 'Regular Season'} Stats: {main_url}")
        try:
            soup, html_text = _get_soup(main_url)
            tables = _all_tables(soup, html_text)
            found_main = False
            for tbl in tables:
                rows = _parse_table(tbl, {"ortg": ORTG_NAMES, "drtg": DRTG_NAMES,
                                          "pace": PACE_NAMES, "gp": GP_NAMES})
                if not rows:
                    continue
                has_ratings = any("ortg" in r and "drtg" in r for r in rows)
                has_pace    = any("pace" in r for r in rows)
                min_rows    = 8 if _is_po else 20   # playoffs: solo 8-16 equipos
                if len(rows) >= min_rows and (has_ratings or has_pace):
                    for r in rows:
                        ea = r["espn_abb"]
                        if ea not in stats:
                            stats[ea] = {"ortg": LEAGUE_AVG_ORTG, "drtg": LEAGUE_AVG_DRTG, "pace": LEAGUE_AVG_PACE}
                        if "ortg" in r: stats[ea]["ortg"] = r["ortg"]
                        if "drtg" in r: stats[ea]["drtg"] = r["drtg"]
                        if "pace" in r: stats[ea]["pace"]  = r["pace"]
                        if "gp"   in r: stats[ea]["gp"]    = int(r["gp"])
                    n_r = sum(1 for v in stats.values() if v["ortg"] != LEAGUE_AVG_ORTG)
                    n_p = sum(1 for v in stats.values() if v["pace"] != LEAGUE_AVG_PACE)
                    if n_r >= min_rows:
                        found_main = True
                        print(f"  ✅ BBRef main: {n_r} equipos ORtg/DRtg, {n_p} Pace")
                        if n_r >= min_rows and n_p >= min_rows:
                            break
            if not found_main:
                print("  ⚠️  Tabla completa no encontrada en BBRef main. Intentando sub-páginas …")
        except Exception as e:
            print(f"  ⚠️  Error BBRef main: {e}")

        # Step 2: ratings sub-page (solo regular season; playoffs tienen todo en la main page)
        n_ratings = sum(1 for v in stats.values() if v.get("ortg", LEAGUE_AVG_ORTG) != LEAGUE_AVG_ORTG)
        if not _is_po and n_ratings < 20:
            try:
                ratings_url = f"{_bbref_base}_ratings.html"
                print(f"  📡 Fallback ratings: {ratings_url}")
                soup_r, _ = _get_soup(ratings_url)
                for tbl in _all_tables(soup_r, ""):
                    rows = _parse_table(tbl, {"ortg": ORTG_NAMES, "drtg": DRTG_NAMES, "gp": GP_NAMES})
                    if rows and len(rows) >= 20:
                        for r in rows:
                            ea = r["espn_abb"]
                            if ea not in stats:
                                stats[ea] = {"ortg": LEAGUE_AVG_ORTG, "drtg": LEAGUE_AVG_DRTG, "pace": LEAGUE_AVG_PACE}
                            if "ortg" in r: stats[ea]["ortg"] = r["ortg"]
                            if "drtg" in r: stats[ea]["drtg"] = r["drtg"]
                            if "gp"   in r: stats[ea]["gp"]   = int(r["gp"])
                        print(f"  ✅ Ratings fallback: {len(rows)} equipos")
                        break
            except Exception as e:
                print(f"  ⚠️  Error ratings fallback: {e}")

        # Step 3: misc sub-page (Pace)
        n_pace = sum(1 for v in stats.values() if v.get("pace", LEAGUE_AVG_PACE) != LEAGUE_AVG_PACE)
        min_pace = 8 if _is_po else 20
        if n_pace < min_pace:
            try:
                misc_url = f"{_bbref_base}_misc.html"
                print(f"  📡 Fallback PACE: {misc_url}")
                soup_m, _ = _get_soup(misc_url)
                for tbl in _all_tables(soup_m, ""):
                    rows = _parse_table(tbl, {"pace": PACE_NAMES, "ortg": ORTG_NAMES,
                                              "drtg": DRTG_NAMES, "gp": GP_NAMES})
                    if rows and any("pace" in r for r in rows) and len(rows) >= min_pace:
                        pace_count = 0
                        for r in rows:
                            ea = r["espn_abb"]
                            if ea not in stats:
                                stats[ea] = {"ortg": LEAGUE_AVG_ORTG, "drtg": LEAGUE_AVG_DRTG, "pace": LEAGUE_AVG_PACE}
                            if "pace" in r:
                                stats[ea]["pace"] = r["pace"]
                                pace_count += 1
                            if "ortg" in r and stats[ea].get("ortg") == LEAGUE_AVG_ORTG:
                                stats[ea]["ortg"] = r["ortg"]
                            if "drtg" in r and stats[ea].get("drtg") == LEAGUE_AVG_DRTG:
                                stats[ea]["drtg"] = r["drtg"]
                            if "gp" in r and "gp" not in stats.get(ea, {}):
                                stats[ea]["gp"] = int(r["gp"])
                        print(f"  ✅ PACE fallback: {pace_count} equipos")
                        break
            except Exception as e:
                print(f"  ⚠️  Error PACE fallback: {e}")

        # Compute net for BBRef path
        for ea, v in stats.items():
            if "net" not in v:
                v["net"] = round(v.get("ortg", LEAGUE_AVG_ORTG) - v.get("drtg", LEAGUE_AVG_DRTG), 2)

    # ── Final check ──────────────────────────────────────────────────────────
    n_total = len(stats)
    if n_total == 0:
        print("  ❌ No se pudo obtener stats. Instala nba_api (pip install nba_api) o usa")
        print("     --set-stats TEAM ORTG DRTG PACE para entrada manual.")
        return None

    print(f"  ✅ {n_total} equipos cargados.")
    return stats

def blend_regular_playoff_stats(reg_stats, playoff_stats, max_playoff_weight=0.40):
    """
    Blend temporada regular + playoffs con peso dinámico por juegos jugados.

    Lógica (escalado dinámico por ronda):
      - 2 PO games  → ~12% playoff + 88% regular  (muestra muy chica)
      - 5 PO games  → ~31% playoff + 69% regular  (R2: datos de serie relevantes)
      - 10 PO games → ~50% playoff + 50% regular
      - 16+ PO games→ 55% playoff + 45% regular  (max en rondas avanzadas)

    En R2+ el techo sube a 0.55 porque hay 5-7 juegos de contexto head-to-head
    que es más predictivo que 82 juegos de temporada regular.

    Los stats blended se guardan en caché con metadata de playoff para que
    show_stats pueda mostrar de dónde vienen los números.
    """
    if not playoff_stats:
        return reg_stats

    # Calcular el total de GP en playoffs como proxy de la ronda actual
    total_po_gp = sum(po.get("gp", 0) for po in playoff_stats.values()) if playoff_stats else 0
    # R1: ≤80 total gp (4 series × máx 7 = 28 gp por equipo); R2+: más
    _is_r2_plus = total_po_gp > 0 and any(po.get("gp", 0) >= 4 for po in playoff_stats.values())
    _max_w = 0.55 if _is_r2_plus else max_playoff_weight   # R2+: techo más alto

    blended = {}
    for team, reg in reg_stats.items():
        po = playoff_stats.get(team)
        if not po:
            blended[team] = reg.copy()
            blended[team].setdefault("po_gp", 0)
            blended[team].setdefault("po_weight", 0.0)
            continue

        po_gp  = po.get("gp", 2)           # juegos jugados en playoffs
        po_w   = min(_max_w, po_gp / 16 * _max_w)
        reg_w  = 1 - po_w

        b_ortg = round(reg["ortg"] * reg_w + po["ortg"] * po_w, 1)
        b_drtg = round(reg["drtg"] * reg_w + po["drtg"] * po_w, 1)
        b_pace = round(reg["pace"] * reg_w + po.get("pace", reg["pace"]) * po_w, 1)

        blended[team] = {
            "ortg":      b_ortg,
            "drtg":      b_drtg,
            "pace":      b_pace,
            "net":       round(b_ortg - b_drtg, 2),
            # metadata de playoffs para display
            "po_ortg":   po["ortg"],
            "po_drtg":   po["drtg"],
            "po_gp":     po_gp,
            "po_weight": round(po_w * 100, 1),
            # base regular season (para referencia)
            "reg_ortg":  reg["ortg"],
            "reg_drtg":  reg["drtg"],
        }

    # Equipos en playoffs que no estaban en reg_stats (edge case)
    for team, po in playoff_stats.items():
        if team not in blended:
            blended[team] = po.copy()
            blended[team]["po_gp"]     = po.get("gp", 0)
            blended[team]["po_weight"] = max_playoff_weight * 100

    return blended


def load_nba_stats():
    """
    Load stats from cache, return dict by team ABB.
    En playoffs: si el caché no es de HOY, auto-refresca antes de continuar.
    Los stats de playoffs cambian partido a partido — un caché de ayer ya
    puede estar desalineado con el mercado (equipos que ganaron/perdieron
    dramáticamente no están reflejados).
    """
    if os.path.exists(NBA_STATS_CACHE):
        try:
            # Verificar fecha del caché
            import datetime as _dt_mod
            mtime = os.path.getmtime(NBA_STATS_CACHE)
            cache_date = _dt_mod.datetime.fromtimestamp(mtime).date()
            today_date = _dt_mod.date.today()
            days_stale = (today_date - cache_date).days

            with open(NBA_STATS_CACHE, 'r') as f:
                cached = json.load(f)

            if days_stale == 0:
                return cached

            # Caché desactualizado
            if _is_nba_playoffs() and days_stale >= 1:
                print(f"\n  ⚠️  NBA STATS CACHE DESACTUALIZADO ({days_stale}d) — los últimos")
                print(f"     juegos de playoffs no están reflejados en el modelo.")
                print(f"     → Auto-refreshing stats antes de correr picks...")
                try:
                    cmd_refresh_stats()
                    # Recargar después del refresh
                    with open(NBA_STATS_CACHE, 'r') as f:
                        return json.load(f)
                except Exception as _re:
                    print(f"  ⚠️  Auto-refresh falló ({_re}) — usando caché de {cache_date}")
                    return cached
            elif days_stale >= 1:
                print(f"  ℹ️  NBA stats cache tiene {days_stale}d — corre --refresh para actualizar")
            return cached
        except Exception:
            pass
    return {}

def save_nba_stats(stats):
    """Save stats to cache."""
    with open(NBA_STATS_CACHE, 'w') as f:
        json.dump(stats, f, indent=2)

def _get_playoff_gp_from_series(season_year):
    """
    Cuenta juegos jugados (GP) por equipo en playoffs via LeagueGameLog.
    LeagueGameLog lista cada juego individual → conteo exacto y real-time.
    SeriesStandings falla frecuentemente; usamos LeagueGameLog como alternativa.

    Retorna dict {espn_abb: games_played} o {} si falla.
    """
    try:
        from nba_api.stats.endpoints import LeagueGameLog  # type: ignore
        yr         = int(season_year)
        season_str = f"{yr-1}-{str(yr)[2:]}"   # "2025-26"
        gl  = LeagueGameLog(
            season=season_str,
            season_type_all_star="Playoffs",
            timeout=30
        )
        df = gl.get_data_frames()[0]
        if df.empty:
            return {}

        # Cada fila = 1 equipo en 1 juego → contar filas por equipo
        gp_map = {}
        for _, row in df.iterrows():
            abb = str(row.get("TEAM_ABBREVIATION", "")).strip()
            if not abb:
                continue
            espn = NBACOM_TO_ESPN.get(abb, abb)
            gp_map[espn] = gp_map.get(espn, 0) + 1

        return gp_map

    except Exception as _e:
        # Fallback: SeriesStandings (puede fallar con season_id)
        try:
            from nba_api.stats.endpoints import SeriesStandings  # type: ignore
            _NBA2ESPN = NBACOM_TO_ESPN
            yr2       = int(season_year)
            season_id = f"4{yr2 - 1}"
            ss  = SeriesStandings(league_id="00", season_id=season_id, timeout=20)
            df2 = ss.get_data_frames()[0]
            if df2.empty:
                return {}
            gp_map2 = {}
            for col in df2.columns:
                pass   # inspección silenciosa
            # Intentar con UPPER_CASE y CamelCase
            for _, row in df2.iterrows():
                h_wins = int(row.get("HOME_TEAM_WINS") or row.get("HomeTeamWins") or 0)
                a_wins = int(row.get("VISITOR_TEAM_WINS") or row.get("VisitorTeamWins") or 0)
                h_abb  = str(row.get("HOME_TEAM_ABBREVIATION") or row.get("HomeTeamAbbreviation") or "")
                a_abb  = str(row.get("VISITOR_TEAM_ABBREVIATION") or row.get("VisitorTeamAbbreviation") or "")
                h_e    = _NBA2ESPN.get(h_abb, h_abb)
                a_e    = _NBA2ESPN.get(a_abb, a_abb)
                total  = h_wins + a_wins
                gp_map2[h_e] = gp_map2.get(h_e, 0) + total
                gp_map2[a_e] = gp_map2.get(a_e, 0) + total
            return gp_map2
        except Exception:
            return {}


def cmd_refresh_stats():
    """Fetch fresh NBA.com stats and save to cache. Blends playoffs when detected."""
    season_year = TARGET_DATE[:4]
    in_playoffs = _is_nba_playoffs()

    # ── Temporada regular ─────────────────────────────────────────────────────
    print(f"\n📡 Fetching temporada regular {season_year} …")
    reg_stats = fetch_nba_stats(season_year, season_type="Regular Season")
    if not reg_stats:
        print("❌ No se pudo obtener stats de temporada regular.")
        print("   Configura manualmente con --set-stats TEAM ORTG DRTG PACE")
        return

    stats = reg_stats

    # ── Playoffs blend (si estamos en playoffs) ───────────────────────────────
    if in_playoffs:
        print(f"\n🏆 Playoffs detectados — fetching stats de playoffs {season_year} …")
        po_stats = fetch_nba_stats(season_year, season_type="Playoffs")
        if po_stats:
            n_po = len([t for t in po_stats if po_stats[t].get("gp", 0) > 0])
            print(f"  ✅ Playoffs: {n_po} equipos con datos")
            stats = blend_regular_playoff_stats(reg_stats, po_stats)
            n_blended = len([t for t in stats if stats[t].get("po_gp", 0) > 0])
            print(f"  🔀 Blend aplicado: {n_blended} equipos con datos de playoffs mezclados")
        else:
            print("  ⚠️  No se pudo obtener stats de playoffs — usando solo temporada regular.")

        # ── Parchar GP con LeagueGameLog (real-time, sin lag) ────────────────
        print(f"  📡 Verificando GP real-time via LeagueGameLog …", end=" ", flush=True)
        series_gp = _get_playoff_gp_from_series(season_year)
        if series_gp:
            updated = 0
            changes = []
            for team, real_gp in series_gp.items():
                if team in stats:
                    old_gp = stats[team].get("po_gp", 0)
                    if real_gp != old_gp:
                        stats[team]["po_gp"] = real_gp
                        # Re-calcular po_weight con GP actualizado
                        stats[team]["po_weight"] = round(
                            min(0.40, real_gp / 16 * 0.40) * 100, 1)
                        changes.append(f"{team}: {old_gp}→{real_gp}G")
                        updated += 1
            print(f"{len(series_gp)} equipos — {updated} GP corregidos")
            if changes:
                print(f"     Cambios: {', '.join(changes)}")
        else:
            print("⚠️  no disponible (usando GP de LeagueDashTeamStats — puede lagear)")

    save_nba_stats(stats)
    show_stats(stats)

def cmd_set_stats(team, ortg, drtg, pace):
    """Manually set stats for a team."""
    stats = load_nba_stats()
    stats[team] = {
        'ortg': float(ortg),
        'drtg': float(drtg),
        'pace': float(pace),
        'net': float(ortg) - float(drtg)
    }
    save_nba_stats(stats)
    print(f"Updated {team}: ORTG={ortg}, DRTG={drtg}, PACE={pace}")

# ============================================================================
# SCHEDULE & ODDS
# ============================================================================

# ── Manual games helpers ─────────────────────────────────────────────────────

def _load_manual_games_nba():
    if not os.path.exists(MANUAL_GAMES_FILE):
        return []
    try:
        with open(MANUAL_GAMES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _save_manual_games_nba(entries):
    with open(MANUAL_GAMES_FILE, "w") as f:
        json.dump(entries, f, indent=2, default=str)

def _get_manual_games_nba(target_date):
    return [g for g in _load_manual_games_nba() if g.get("date") == target_date]

def cmd_add_game_nba():
    """
    --add-game AWAY HOME [HORA]
    Agrega un juego manual para TARGET_DATE.
    Ej: python3 nba.py --add-game BOS NYK '7:30 PM'
    """
    try:
        idx = sys.argv.index("--add-game")
        raw_away = sys.argv[idx+1].upper()
        raw_home = sys.argv[idx+2].upper()
        raw_time = sys.argv[idx+3] if idx+3 < len(sys.argv) and not sys.argv[idx+3].startswith("-") else ""
    except (ValueError, IndexError):
        print("  Uso: python3 nba.py --add-game AWAY HOME 'HORA'")
        print("  Ej:  python3 nba.py --add-game BOS NYK '7:30 PM ET'")
        return

    # Normalize abbreviations
    away = ESPN_API_TO_INTERNAL.get(raw_away, raw_away)
    home = ESPN_API_TO_INTERNAL.get(raw_home, raw_home)

    if away not in TEAM_ABB:
        print(f"  ⚠️  Equipo visitante no reconocido: {away}")
        print(f"  Equipos válidos: {', '.join(sorted(TEAM_ABB.keys()))}")
        return
    if home not in TEAM_ABB:
        print(f"  ⚠️  Equipo local no reconocido: {home}")
        return

    entry = {
        "date": TARGET_DATE,
        "away_abb": away,
        "home_abb": home,
        "away_name": TEAM_ABB[away],
        "home_name": TEAM_ABB[home],
        "game_time_utc": raw_time,
        "game_id": f"manual_{TARGET_DATE}_{away}_{home}",
    }
    existing = _load_manual_games_nba()
    # Dedup by team pair + date
    existing = [g for g in existing
                if not (g["date"] == TARGET_DATE
                        and {g["away_abb"], g["home_abb"]} == {away, home})]
    existing.append(entry)
    _save_manual_games_nba(existing)
    print(f"  ✅ Juego agregado: {away} @ {home}  ({TARGET_DATE}  {raw_time})")
    print(f"  Corre:  python3 nba.py --lines  para ver proyecciones.")

def cmd_list_games_nba():
    """--list-games : lista juegos manuales para TARGET_DATE."""
    games = _get_manual_games_nba(TARGET_DATE)
    if not games:
        print(f"  No hay juegos manuales para {TARGET_DATE}.")
    else:
        print(f"\n  Juegos manuales — {TARGET_DATE}:")
        for g in games:
            t = g.get("game_time_utc","")
            print(f"    {g['away_abb']} @ {g['home_abb']}  {t}")
    print()

def cmd_remove_game_nba():
    """--remove-game AWAY HOME : elimina un juego manual."""
    try:
        idx = sys.argv.index("--remove-game")
        away = sys.argv[idx+1].upper()
        home = sys.argv[idx+2].upper()
    except (ValueError, IndexError):
        print("  Uso: python3 nba.py --remove-game AWAY HOME")
        return
    existing = _load_manual_games_nba()
    kept = [g for g in existing
            if not (g["date"] == TARGET_DATE
                    and {g["away_abb"], g["home_abb"]} == {away, home})]
    if len(kept) == len(existing):
        print(f"  No se encontró {away} @ {home} en {TARGET_DATE}.")
    else:
        _save_manual_games_nba(kept)
        print(f"  ✅ Juego removido: {away} @ {home}")

# ── Schedule fetching ─────────────────────────────────────────────────────────

def _normalize_abb(abb):
    """Normalize ESPN API abbreviation to internal 3-letter code."""
    u = abb.upper()
    return ESPN_API_TO_INTERNAL.get(u, u)

def get_nba_schedule(target_date, silent=False):
    """
    Fetch NBA schedule from ESPN for a given date.
    Falls back to manual games (nba_manual_games.json) if ESPN returns nothing.
    Normalizes ESPN abbreviations (e.g. 'GS' → 'GSW') to match stats cache keys.
    """
    espn_games = []
    try:
        ymd = target_date.replace("-", "")
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        for event in data.get('events', []):
            # Per-game try/except — a bad event should not drop the rest
            try:
                comp = event['competitions'][0]
                away_comp, home_comp = None, None
                for c in comp['competitors']:
                    if c.get('homeAway') == 'home':
                        home_comp = c
                    elif c.get('homeAway') == 'away':
                        away_comp = c
                # Fallback to index if homeAway not present
                if away_comp is None or home_comp is None:
                    if len(comp['competitors']) >= 2:
                        away_comp = comp['competitors'][1]
                        home_comp = comp['competitors'][0]
                    else:
                        continue   # skip malformed event

                away_raw = away_comp['team']['abbreviation']
                home_raw = home_comp['team']['abbreviation']
                away_abb = _normalize_abb(away_raw)
                home_abb = _normalize_abb(home_raw)
                espn_games.append({
                    'away_abb':      away_abb,
                    'home_abb':      home_abb,
                    'away_name':     away_comp['team'].get('displayName', away_raw),
                    'home_name':     home_comp['team'].get('displayName', home_raw),
                    'game_time_utc': comp.get('startDate', ''),
                    'game_id':       event['id'],
                })
            except Exception as eg:
                if not silent:
                    try:
                        _eid = event.get('id','?')
                        _teams = [c.get('team',{}).get('abbreviation','?') for c in event.get('competitions',[{}])[0].get('competitors',[])]
                        print(f"  ⚠️  ESPN: juego {_eid} ({_teams}) ignorado — {eg}")
                    except Exception:
                        print(f"  ⚠️  ESPN: evento ignorado — {eg}")

    except Exception as e:
        if not silent:
            print(f"  ⚠️  ESPN API: {e}")

    # Merge with manual games (manual ones not already in ESPN)
    manual = _get_manual_games_nba(target_date)
    if manual:
        espn_keys = {(g['away_abb'], g['home_abb']) for g in espn_games}
        for m in manual:
            if (m['away_abb'], m['home_abb']) not in espn_keys:
                espn_games.append(m)

    if not silent:
        if espn_games:
            game_strs = [f"{g['away_abb']}@{g['home_abb']}" for g in espn_games]
            print(f"  📅 Schedule {target_date}: {len(espn_games)} juego(s) — {', '.join(game_strs)}")
        else:
            print(f"  ⚠️  No hay juegos NBA para {target_date}.")
            print(f"  💡 Agrégalos manualmente:  python3 nba.py --add-game AWAY HOME 'HORA'")

    return espn_games

def _load_manual_market():
    """Carga líneas de mercado ingresadas manualmente vía --set-market.
    Retorna dict keyed by '{away_abb}_{home_abb}'.
    Solo devuelve entradas del día de hoy para evitar contaminar con datos viejos.
    """
    import json as _j
    if not os.path.exists(MANUAL_MARKET_FILE):
        return {}
    try:
        with open(MANUAL_MARKET_FILE) as _f:
            data = _j.load(_f)
        today = TARGET_DATE
        result = {}
        for key, entry in data.items():
            if entry.get("date") == today:
                result[key] = entry.get("markets", {})
        return result
    except Exception:
        return {}


def cmd_set_market():
    """
    --set-market AWAY HOME SPREAD [TOTAL] [ML_AWAY]
    Ingresa manualmente las líneas de mercado para un juego cuando el API no tiene datos.

    Ejemplos:
      python3 nba.py --set-market SAS MIN -5.5
      python3 nba.py --set-market SAS MIN -5.5 215.5 +110
    Luego corre: python3 nba.py --picks
    """
    import json as _j
    try:
        idx  = sys.argv.index("--set-market")
        away = _normalize_abb(sys.argv[idx+1].upper())
        home = _normalize_abb(sys.argv[idx+2].upper())
        spread_raw = float(sys.argv[idx+3])  # spread en perspectiva del away (neg = away fav)
    except (ValueError, IndexError):
        print("  ❌ Uso: python3 nba.py --set-market AWAY HOME SPREAD [TOTAL] [ML_AWAY]")
        print("     Ejemplo: python3 nba.py --set-market SAS MIN -5.5")
        return

    total_raw = None
    ml_away   = None
    if idx+4 < len(sys.argv) and not sys.argv[idx+4].startswith("--"):
        try: total_raw = float(sys.argv[idx+4])
        except ValueError: pass
    if idx+5 < len(sys.argv) and not sys.argv[idx+5].startswith("--"):
        try: ml_away = int(sys.argv[idx+5])
        except ValueError: pass

    # Convertir spread a formato interno: spread_line = abs(spread), favorito = quien tiene neg
    spread_abs   = abs(spread_raw)
    fav_is_away  = spread_raw < 0
    dog_odds     = -110  # default
    # Si ml_away dada, el favorito tiene juice negativo
    if ml_away is not None:
        dog_odds = ml_away if not fav_is_away else -ml_away  # odds del underdog

    # Construir estructura compatible con get_market_odds()
    key = f"{away}_{home}"
    markets_list = []
    # Spreads
    markets_list.append({
        "key": "spreads",
        "outcomes": [
            {"name": away, "price": (-110 if fav_is_away else dog_odds), "point": spread_raw},
            {"name": home, "price": (-110 if not fav_is_away else dog_odds), "point": -spread_raw},
        ]
    })
    # ML (estimated if not provided)
    if ml_away is not None:
        away_ml = ml_away
        home_ml = -ml_away if ml_away > 0 else abs(ml_away)
    else:
        # estimate from spread
        away_ml = round(-110 + spread_raw * 12) if fav_is_away else round(110 + spread_raw * 12)
        home_ml = round(-110 - spread_raw * 12) if not fav_is_away else round(110 - spread_raw * 12)
    markets_list.append({
        "key": "h2h",
        "outcomes": [
            {"name": away, "price": away_ml},
            {"name": home, "price": home_ml},
        ]
    })
    # Totals
    if total_raw:
        markets_list.append({
            "key": "totals",
            "outcomes": [
                {"name": "Over",  "price": -110, "point": total_raw},
                {"name": "Under", "price": -110, "point": total_raw},
            ]
        })

    # Save
    existing = {}
    if os.path.exists(MANUAL_MARKET_FILE):
        try:
            with open(MANUAL_MARKET_FILE) as _f:
                existing = _j.load(_f)
        except Exception:
            existing = {}
    existing[key] = {
        "date":    TARGET_DATE,
        "away":    away,
        "home":    home,
        "spread":  spread_raw,
        "total":   total_raw,
        "ml_away": ml_away,
        "markets": markets_list,
    }
    with open(MANUAL_MARKET_FILE, 'w') as _f:
        _j.dump(existing, _f, indent=2)

    fav_s = f"{away} {spread_raw}" if fav_is_away else f"{home} +{spread_abs}"
    print(f"  ✅ Línea guardada: {away} @ {home} | Spread: {spread_raw} | Total: {total_raw or '—'}")
    print(f"  Regenera picks: python3 nba.py --picks")


def get_market_odds(sport_key='basketball_nba'):
    """Fetch market odds from The Odds API.
    Returns odds_map keyed by '{away_abb}_{home_abb}' or empty dict if unavailable.
    """
    if not ODDS_API_KEY:
        return {}
    try:
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'us',
            'markets': 'h2h,spreads,totals',
            'oddsFormat': 'american',
            'dateFormat': 'iso',
        }
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode('utf-8')
            data = json.loads(raw)

        # v4 API returns a list directly (not wrapped in {"data": [...]})
        if isinstance(data, dict):
            games_list = data.get('data', [])
        else:
            games_list = data  # it IS the list

        odds_map = {}
        for game in games_list:
            away_full = game.get('away_team', '')
            home_full = game.get('home_team', '')
            bookmakers = game.get('bookmakers', [])
            if not bookmakers:
                continue
            # Map full team names → abbreviations (best effort)
            away_abb = _full_name_to_abb(away_full)
            home_abb = _full_name_to_abb(home_full)
            key = f"{away_abb}_{home_abb}"
            odds_map[key] = {
                'away_team': away_full,
                'home_team': home_full,
                'away_abb':  away_abb,
                'home_abb':  home_abb,
                'bookmakers': bookmakers,
            }

        # Merge manual market lines (override API for games not covered)
        manual = _load_manual_market()
        for mkey, mmarkets in manual.items():
            if mkey not in odds_map:
                # Build minimal bookmaker-style entry from manual data
                away_m, home_m = mkey.split("_", 1)
                odds_map[mkey] = {
                    'away_team': away_m, 'home_team': home_m,
                    'away_abb':  away_m, 'home_abb':  home_m,
                    'bookmakers': [{'key': 'manual', 'title': 'Manual', 'markets': mmarkets}],
                }
        return odds_map
    except Exception as e:
        # On API failure, still return any manual lines
        manual = _load_manual_market()
        result = {}
        for mkey, mmarkets in manual.items():
            away_m, home_m = mkey.split("_", 1)
            result[mkey] = {
                'away_team': away_m, 'home_team': home_m,
                'away_abb':  away_m, 'home_abb':  home_m,
                'bookmakers': [{'key': 'manual', 'title': 'Manual', 'markets': mmarkets}],
            }
        return result


# Reverse map: full name → abbreviation
_NAME_TO_ABB = {v.lower(): k for k, v in TEAM_ABB.items()}
# Extra aliases
_NAME_TO_ABB.update({
    "golden state warriors": "GSW",
    "los angeles lakers": "LAL",
    "los angeles clippers": "LAC",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "portland trail blazers": "POR",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
})


def _full_name_to_abb(full_name):
    """Convert full NBA team name → internal 3-letter abbreviation."""
    key = full_name.strip().lower()
    if key in _NAME_TO_ABB:
        return _NAME_TO_ABB[key]
    # Fallback: match last word (e.g. "Warriors" → "GSW")
    last_word = key.split()[-1] if key else ""
    for name, abb in _NAME_TO_ABB.items():
        if name.endswith(last_word):
            return abb
    return full_name[:3].upper()

def _fetch_nba_scores(date_str):
    """Fetch scores from ESPN for grading."""
    try:
        ymd = date_str.replace("-", "")
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        scores = []
        for event in data.get('events', []):
            away = event['competitions'][0]['competitors'][1]['team']['abbreviation']
            home = event['competitions'][0]['competitors'][0]['team']['abbreviation']
            away_score = event['competitions'][0]['competitors'][1].get('score')
            home_score = event['competitions'][0]['competitors'][0].get('score')
            status = event['status']['type'].get('description', 'unknown')

            if away_score is not None and home_score is not None:
                scores.append({
                    'away_abb': away,
                    'home_abb': home,
                    'away_score': int(away_score),
                    'home_score': int(home_score),
                    'status': status
                })

        return scores
    except Exception as e:
        print(f"Error fetching scores: {e}")
        return []

# ============================================================================
# INJURY REPORT — NBA
# ============================================================================

NBA_INJURIES_FILE = os.path.join(SCRIPT_DIR, "nba_injuries.json")

# Cuánto se descuenta del total de puntos según el rol del jugador (temporada regular)
# rf representa la fracción de ppg*usg que se traduce en pérdida neta de puntos.
# (el reemplazo absorbe una parte, pero nunca toda la producción)
INJURY_RATE_FACTOR  = {1: 0.70, 2: 0.75, 3: 0.80}

# ── Playoffs: superstars y stars duelen MÁS porque:
#   · Rotación corta (7-8 hombres) → el reemplazo juega más minutos y es menos eficiente
#   · El equipo reorganiza el ataque entero alrededor de los que quedan
#   · La defensa rival gameplans específicamente para aislar la ausencia
#   · En clutch/late-game no hay plan B comparable
# Multiplier vs temporada regular:  Rate 1 → +40%   Rate 2 → +20%   Rate 3 → +5%
PLAYOFF_INJURY_RATE_FACTOR = {1: 0.98, 2: 0.90, 3: 0.84}

# Cuánto del impacto aplica según el estatus
INJURY_STATUS_FACTOR = {
    "out":          1.00,
    "doubtful":     0.80,
    "gtd":          0.50,   # Game Time Decision
    "questionable": 0.50,
    "probable":     0.00,   # Se espera que juegue → impacto 0 en el modelo
}

# En playoffs, "questionable" casi siempre juega (los jugadores aguantan las lesiones).
# Usar factor más bajo para no sobrepenalizar equipos cuando el jugador probablemente cancha.
#   questionable → 0.20 (juega ~80% de las veces en playoffs)
#   gtd          → 0.30 (juega ~70% de las veces)
#   doubtful     → 0.65 (más serio, pero el playoff pressure lo empuja a intentarlo)
PLAYOFF_INJURY_STATUS_FACTOR = {
    "out":          1.00,
    "doubtful":     0.65,
    "gtd":          0.30,
    "questionable": 0.20,   # Playoffs: el jugador casi siempre sale a cancha
    "probable":     0.00,
}

# ESPN team abbreviation → NBA abbreviation
_ESPN_TO_NBA = {v: k for k, v in ESPN_ABB.items()}   # construido desde ESPN_ABB
# Aliases adicionales que ESPN usa en su API/HTML
_ESPN_TO_NBA.update({
    "gs":"GSW","sa":"SAS","ny":"NYK","no":"NOP","utah":"UTA","wsh":"WAS",
    "wsn":"WAS","okc":"OKC","mem":"MEM","phi":"PHI","phx":"PHX",
    "nop":"NOP","bkn":"BKN","cha":"CHA",
})

BREF_SEASON = "2026"   # cambiar cada temporada


def _load_nba_injuries():
    if not os.path.exists(NBA_INJURIES_FILE):
        return []
    try:
        with open(NBA_INJURIES_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_nba_injuries(entries):
    with open(NBA_INJURIES_FILE, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    _gh_push_injuries()


def _gh_push_injuries():
    """Push nba_injuries.json to the laboy-picks repo so it survives Render redeploys."""
    import base64 as _b64, urllib.request as _ur, urllib.error as _ue
    _token = os.environ.get("GITHUB_TOKEN", "")
    _repo  = os.environ.get("GITHUB_USER", "laboywebsite-lgtm") + "/" + os.environ.get("GITHUB_REPO", "laboy-picks")
    _path  = "NBA/nba_injuries.json"
    _api   = f"https://api.github.com/repos/{_repo}/contents/{_path}"
    _hdrs  = {
        "Authorization": f"token {_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "nba-injuries-autopush",
    }
    try:
        with open(NBA_INJURIES_FILE, "rb") as _f:
            _raw = _f.read()
        _b64c = _b64.b64encode(_raw).decode()
        # Get current SHA from GitHub
        _req = _ur.Request(_api, headers=_hdrs)
        with _ur.urlopen(_req) as _r:
            _cur = json.loads(_r.read())
        _sha = _cur.get("sha", "")
        _payload = json.dumps({
            "message": f"data: nba_injuries.json — {TARGET_DATE}",
            "content": _b64c,
            "sha": _sha,
        }).encode()
        _req2 = _ur.Request(_api, data=_payload, headers=_hdrs, method="PUT")
        with _ur.urlopen(_req2) as _r2:
            _res = json.loads(_r2.read())
        print(f"  📤 nba_injuries.json → GitHub ({_res['commit']['sha'][:8]})")
    except Exception as _e:
        print(f"  ⚠️  GitHub push injuries falló: {_e}")



def _classify_rate_nba(ppg, usg_pct):
    """Clasifica al jugador: 1=Superstar, 2=Star, 3=Role player."""
    if ppg >= 24 or usg_pct >= 0.30:   return 1
    if ppg >= 15 or usg_pct >= 0.22:   return 2
    return 3


def _bref_fetch_html(url):
    """Descarga HTML desde basketball-reference con headers apropiados."""
    import time
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.basketball-reference.com/",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️  bref fetch error: {e}")
        return ""


def _bref_player_stats_nba():
    """
    Obtiene PPG y USG% de basketball-reference.com para la temporada actual.
    Retorna dict: {nombre_normalizado: {'ppg': float, 'usg': float, 'team': str}}
    Cachea en memoria durante la sesión para no golpear el sitio múltiples veces.
    """
    if hasattr(_bref_player_stats_nba, '_cache'):
        return _bref_player_stats_nba._cache

    result = {}

    # ── Per-game (PPG) ────────────────────────────────────────────────────────
    url_pg = f"https://www.basketball-reference.com/leagues/NBA_{BREF_SEASON}_per_game.html"
    html_pg = _bref_fetch_html(url_pg)

    if html_pg:
        # BBRef esconde algunas tablas en comentarios HTML
        import html as _html_mod
        sources = [html_pg]
        # extraer tablas de comentarios
        for cm in re.findall(r'<!--(.*?)-->', html_pg, re.DOTALL):
            if '<table' in cm:
                sources.append(_html_mod.unescape(cm))

        for src in sources:
            rows = re.findall(
                r'<tr[^>]*>.*?</tr>', src, re.DOTALL
            )
            for row in rows:
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
                cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if len(cells) < 8: continue
                try:
                    name = cells[1].strip()
                    team = cells[4].strip().upper()
                    ppg  = float(cells[29]) if len(cells) > 29 else float(cells[-1])
                    if name and ppg > 0:
                        key = name.upper()
                        if key not in result:
                            result[key] = {'ppg': ppg, 'usg': 0.0, 'team': team}
                except (ValueError, IndexError):
                    pass

    # ── Advanced (USG%) ───────────────────────────────────────────────────────
    url_adv = f"https://www.basketball-reference.com/leagues/NBA_{BREF_SEASON}_advanced.html"
    html_adv = _bref_fetch_html(url_adv)

    if html_adv:
        sources_adv = [html_adv]
        for cm in re.findall(r'<!--(.*?)-->', html_adv, re.DOTALL):
            if '<table' in cm:
                import html as _html_mod2
                sources_adv.append(_html_mod2.unescape(cm))

        for src in sources_adv:
            rows = re.findall(r'<tr[^>]*>.*?</tr>', src, re.DOTALL)
            for row in rows:
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
                cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if len(cells) < 20: continue
                try:
                    name = cells[1].strip()
                    # USG% es la col ~20 en advanced; buscar por posición relativa
                    # Columnas: Rk, Player, Age, Tm, Pos, G, MP, PER, TS%, 3PAr, FTr,
                    #           ORB%, DRB%, TRB%, AST%, STL%, BLK%, TOV%, USG%, ...
                    usg_str = cells[19] if len(cells) > 19 else ""
                    usg = float(usg_str.replace('%','')) / 100 if usg_str else 0.0
                    key = name.upper()
                    if key in result:
                        result[key]['usg'] = usg
                    elif name and usg > 0:
                        result[key] = {'ppg': 0.0, 'usg': usg, 'team': ''}
                except (ValueError, IndexError):
                    pass

    _bref_player_stats_nba._cache = result
    print(f"  📊 bref stats cargadas: {len(result)} jugadores")
    return result


def _nba_strip_accents(s):
    """Normaliza caracteres acentuados → ASCII. Ej: Dončić → DONCIC."""
    import unicodedata
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(s).upper())
        if unicodedata.category(c) != 'Mn'
    )

def _bref_lookup(player_keyword, player_stats):
    """
    Busca un jugador en el dict de stats por keyword parcial.
    Normaliza acentos para manejar nombres como Dončić, Jokić, Šarić, etc.
    Retorna (ppg, usg) o (None, None) si no se encuentra.
    """
    pk = _nba_strip_accents(player_keyword)

    # Construir índice normalizado (solo una vez por sesión)
    if not hasattr(_bref_lookup, '_normalized_cache') or \
       id(player_stats) != getattr(_bref_lookup, '_cache_id', None):
        _bref_lookup._normalized_cache = {
            _nba_strip_accents(k): v for k, v in player_stats.items()
        }
        _bref_lookup._cache_id = id(player_stats)

    norm = _bref_lookup._normalized_cache

    # Coincidencia exacta (normalizada)
    if pk in norm:
        s = norm[pk]
        return s['ppg'], s['usg']
    # Coincidencia por apellido (última palabra)
    last = pk.split()[-1] if pk.split() else pk
    matches = [(k, v) for k, v in norm.items() if last in k.split()]
    if not matches:
        matches = [(k, v) for k, v in norm.items() if last in k]
    if len(matches) == 1:
        return matches[0][1]['ppg'], matches[0][1]['usg']
    if len(matches) > 1:
        best = max(matches, key=lambda x: len(set(pk) & set(x[0])))
        return best[1]['ppg'], best[1]['usg']
    return None, None


def _normalize_injury_status(note):
    """
    Parsea el campo 'note' de bref o ESPN y retorna un status normalizado.
    Ej: 'Out (knee) - Day-To-Day' → 'gtd'
        'Out (back)'              → 'out'
        'Probable (ankle)'        → 'probable'
    """
    n = note.lower()
    if 'day-to-day' in n or 'dtd' in n:    return 'gtd'
    if 'questionable' in n:                 return 'questionable'
    if 'doubtful' in n:                     return 'doubtful'
    if 'probable' in n:                     return 'probable'
    if 'out' in n:                          return 'out'
    return 'gtd'   # default conservador si no se reconoce


# bref usa abreviaciones distintas en algunos equipos
_BREF_TO_NBA = {
    "BRK": "BKN",   # Brooklyn
    "PHO": "PHX",   # Phoenix
    "CHO": "CHA",   # Charlotte
    "NOP": "NOP",   # New Orleans (bref ya usa NOP)
    "UTA": "UTA",
    "GSW": "GSW",
    "SAS": "SAS",
    "LAC": "LAC",
    "LAL": "LAL",
    "MEM": "MEM",
    "OKC": "OKC",
    "WSH": "WAS",   # Washington
    "WAS": "WAS",
}


# Nombre completo del equipo (en el PDF de la NBA) → abreviación
_NBA_FULLNAME_TO_ABB = {v.upper(): k for k, v in TEAM_ABB.items()}
_NBA_FULLNAME_TO_ABB.update({
    "LA CLIPPERS":              "LAC",
    "GOLDEN STATE WARRIORS":    "GSW",
    "NEW YORK KNICKS":          "NYK",
    "NEW ORLEANS PELICANS":     "NOP",
    "OKLAHOMA CITY THUNDER":    "OKC",
    "SAN ANTONIO SPURS":        "SAS",
    "UTAH JAZZ":                "UTA",
    "WASHINGTON WIZARDS":       "WAS",
})


def _nba_pdf_urls(date_str):
    """
    Genera URLs del PDF oficial de la NBA en orden más-reciente → más-antiguo.
    Formato: https://ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{HH}_{MM}{AM/PM}.pdf

    Los slots se generan dinámicamente desde la hora actual ET hacia atrás en
    pasos de 30 min. Así a las 10:08 PM intenta 10:00PM → 9:30PM → 9:00PM → ...
    en lugar de quedarse pegado en el 8:00PM hardcodeado.
    """
    from datetime import datetime as _dt, timedelta as _td

    base = "https://ak-static.cms.nba.com/referee/injury/Injury-Report"

    # NBA opera en Eastern Time. Abril = EDT (UTC-4).
    # Puerto Rico (AST) también es UTC-4 en abril — no hay diferencia.
    now_et    = _dt.utcnow() - _td(hours=4)
    today_et  = now_et.strftime("%Y-%m-%d")

    if date_str == today_et:
        # Arrancar desde el slot de 15 min más cercano ≤ ahora
        # NBA publica nuevo PDF cada 15 minutos
        total_min = now_et.hour * 60 + now_et.minute
        start_min = (total_min // 15) * 15
    else:
        # Fechas pasadas: arrancar desde las 11:45 PM hacia atrás
        start_min = 23 * 60 + 45

    def _slot_str(total_minutes):
        h24  = total_minutes // 60
        m    = total_minutes % 60
        ampm = "PM" if h24 >= 12 else "AM"
        h12  = h24 % 12 or 12
        return f"{h12:02d}_{m:02d}{ampm}"

    urls = []
    slot = start_min
    while slot >= 5 * 60:          # hasta las 5:00 AM mínimo
        urls.append(f"{base}_{date_str}_{_slot_str(slot)}.pdf")
        slot -= 15                 # NBA: nuevo PDF cada 15 minutos
    return urls


def _parse_nba_pdf(pdf_bytes, debug=False):
    """
    Parsea el PDF oficial de la NBA.

    Formato real del PDF (descubierto en prod):
      Fila con juego nuevo:
        04/14/2026 07:30(ET) MIA@CHA MiamiHeat LastName,FirstName Status Reason
      Filas siguientes del mismo equipo (sin prefijo de juego):
        LastName,FirstName Status Reason
      Fila con nuevo equipo dentro del mismo juego:
        04/14/2026 07:30(ET) MIA@CHA CharlotteHornets LastName,FirstName Status Reason
        -- o solo: --
        CharlotteHornets LastName,FirstName Status Reason

    Estrategia:
    - Detectar matchup "ABC@DEF" → extraer away/home abbs directamente
    - Detectar team concatenado (ej "MiamiHeat") → mapear a abreviación
    - "LastName,FirstName" → invertir a "FIRSTNAME LASTNAME"
    - Saltar jugadores con status "Available"
    """
    import io as _io

    # Mapa de nombre-concatenado → abreviación NBA
    # Generado desde TEAM_ABB eliminando espacios
    _CONCAT_TO_ABB = {}
    for abb, full in TEAM_ABB.items():
        _CONCAT_TO_ABB[full.replace(" ", "").upper()] = abb  # "MIAMIHEAT" → "MIA"

    # Alias especiales para equipos con nombres compuestos o irregulares
    _CONCAT_TO_ABB.update({
        "LACLIPPERS":            "LAC",
        "LOSANGELESCLIPPERS":    "LAC",
        "LOSANGELESLAKERS":      "LAL",
        "GOLDENSTATEWARRIORS":   "GSW",
        "NEWYORKKNICKS":         "NYK",
        "NEWORLEANSPELICANSS":   "NOP",   # typo guard
        "NEWORLDEANSPELICANSS":  "NOP",
        "OKLAHOMACITYTHUNDER":   "OKC",
        "SANANTONIOSPURS":       "SAS",
        "MEMPHISGRIZZLIES":      "MEM",
        "MINNESOTATI MBERWOLVES":"MIN",
    })

    # Status que nos importan (saltar "Available")
    KEEP_STATUSES = {"out", "questionable", "doubtful", "probable", "day-to-day", "dtd",
                     "game time decision", "gtd"}

    injuries = []

    try:
        import pdfplumber
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

        if debug:
            print("\n--- FULL PDF TEXT (first 1500 chars) ---")
            print(full_text[:1500])

        current_team = None   # abreviación del equipo en contexto

        for raw_line in full_text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            # ── Saltar encabezado del reporte ──────────────────────────────
            if line.startswith("Injury Report:") or line.startswith("GameDate"):
                continue
            if line.lower().startswith("game date") or line.lower().startswith("gametime"):
                continue

            # ── Detectar si la línea tiene matchup "ABC@DEF" ───────────────
            matchup_m = re.search(r'\b([A-Z]{2,4})@([A-Z]{2,4})\b', line)
            if matchup_m:
                away_raw = matchup_m.group(1)
                home_raw = matchup_m.group(2)
                # Normalizar abreviaciones usando ESPN_API_TO_INTERNAL si aplica
                away_abb = ESPN_API_TO_INTERNAL.get(away_raw, away_raw)
                home_abb = ESPN_API_TO_INTERNAL.get(home_raw, home_raw)
                # Resto de la línea después del matchup
                after_matchup = line[matchup_m.end():].strip()

                # Intentar extraer equipo concatenado al inicio de after_matchup
                team_found = None
                for concat, abb in sorted(_CONCAT_TO_ABB.items(), key=lambda x: -len(x[0])):
                    if after_matchup.upper().startswith(concat):
                        team_found = abb
                        after_matchup = after_matchup[len(concat):].strip()
                        break

                if team_found:
                    current_team = team_found
                else:
                    # Si no podemos identificar el equipo por nombre concatenado,
                    # usamos el home_abb como fallback (el equipo local va último en el PDF)
                    current_team = home_abb

                if debug:
                    print(f"  MATCHUP {away_abb}@{home_abb} → team={current_team}  rest='{after_matchup}'")

                # La línea puede tener también el primer jugador del equipo
                line = after_matchup
                if not line:
                    continue

            # ── Intentar detectar cambio de equipo (nombre concatenado sin matchup) ──
            # Ej: "CharlotteHornets Bridges,Miles Day-To-Day ..."
            else:
                team_found = None
                for concat, abb in sorted(_CONCAT_TO_ABB.items(), key=lambda x: -len(x[0])):
                    if line.upper().startswith(concat):
                        team_found = abb
                        line = line[len(concat):].strip()
                        break
                if team_found:
                    current_team = team_found
                    if debug:
                        print(f"  NEW TEAM (no matchup): {current_team}  rest='{line}'")
                    if not line:
                        continue

            # ── Intentar parsear "LastName,FirstName Status Reason" ────────
            # Patrón: una palabra (o apellido con caracteres especiales), coma, otra palabra
            player_m = re.match(r"^([A-Za-z''\-\.]+),([A-Za-z''\-\.]+)\s+(.+)$", line)
            if not player_m:
                # Algunos apellidos truncados o líneas de continuación (reason overflow)
                if debug:
                    print(f"  SKIP (no player pattern): '{line}'")
                continue

            if current_team is None:
                if debug:
                    print(f"  SKIP (no team context): '{line}'")
                continue

            last_name  = player_m.group(1).strip()
            first_name = player_m.group(2).strip()
            rest       = player_m.group(3).strip()

            # El primer token de 'rest' es el status
            rest_parts = rest.split()
            status_raw = rest_parts[0] if rest_parts else ""
            reason     = " ".join(rest_parts[1:]) if len(rest_parts) > 1 else ""

            # Saltar Available
            if status_raw.lower() == "available":
                if debug:
                    print(f"  SKIP Available: {first_name} {last_name}")
                continue

            # Solo guardar estados conocidos de lesión
            if status_raw.lower() not in KEEP_STATUSES:
                if debug:
                    print(f"  SKIP unknown status '{status_raw}': {first_name} {last_name}")
                continue

            full_player = f"{first_name} {last_name}".strip().upper()

            if debug:
                print(f"  → TEAM={current_team}  PLAYER={full_player}  STATUS={status_raw}")

            injuries.append({
                "team_abb": current_team,
                "player":   full_player,
                "status":   _normalize_injury_status(status_raw),
                "note":     f"{status_raw} – {reason}".strip(" –"),
            })

        return injuries

    except ImportError:
        print("  ⚠️  Instala pdfplumber: pip3 install pdfplumber")
        return []


def fetch_nba_injuries(date_str=None):
    """
    Fuente primaria: PDF oficial de la NBA (ak-static.cms.nba.com)
    Retorna lista de dicts: {team_abb, player, status, note}
    """
    if date_str is None:
        date_str = TARGET_DATE

    injuries = []

    # ── Estrategia 1: NBA official PDF ────────────────────────────────────────
    pdf_data   = None
    found_url  = None
    for url in _nba_pdf_urls(date_str):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=8) as r:
                pdf_data = r.read()
            found_url = url
            break
        except Exception:
            continue

    if pdf_data:
        print(f"  📄 PDF encontrado: {found_url.split('/')[-1]}")
        debug_mode = 'debug' in sys.argv
        injuries = _parse_nba_pdf(pdf_data, debug=debug_mode)
        if injuries:
            print(f"  ✅ NBA PDF: {len(injuries)} jugadores")
            return injuries
        else:
            print("  ⚠️  PDF descargado pero parse retornó 0 jugadores.")
            print("       Corre:  python3 nba.py --ir refresh debug  para ver el contenido del PDF")
    else:
        print(f"  ⚠️  No se encontró PDF para {date_str}")

    # ── Estrategia 2: basketball-reference injuries (fallback) ─────────────────
    print("  🔄 Intentando basketball-reference.com...")
    try:
        html = _bref_fetch_html("https://www.basketball-reference.com/friv/injuries.fcgi")
        if html:
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            for row in rows:
                pm = re.search(r'data-stat="player"[^>]*>(.*?)</td>', row, re.DOTALL)
                tm = re.search(r'data-stat="team_id"[^>]*>(.*?)</td>', row, re.DOTALL)
                nm = re.search(r'data-stat="note"[^>]*>(.*?)</td>', row, re.DOTALL)
                if not (pm and tm and nm): continue
                name      = re.sub(r'<[^>]+>', '', pm.group(1)).strip()
                bref_team = re.sub(r'<[^>]+>', '', tm.group(1)).strip().upper()
                note      = re.sub(r'<[^>]+>', '', nm.group(1)).strip()
                if not name or name.upper() in ('PLAYER', ''): continue
                nba_abb = _BREF_TO_NBA.get(bref_team, bref_team)
                injuries.append({"team_abb": nba_abb, "player": name.upper(),
                                  "status": _normalize_injury_status(note), "note": note})
            if injuries:
                print(f"  ✅ bref: {len(injuries)} jugadores")
                return injuries
    except Exception as e:
        print(f"  ⚠️  bref error: {e}")

    return injuries


def compute_nba_injury_impact(entries):
    """
    Calcula el impacto total en puntos por equipo.
    Retorna dict: {team_abb: total_pts_impact}

    Fórmula: impact = ppg * usg * rf * sf
      ppg  = puntos por juego del jugador
      usg  = uso fraction (0.28 = 28% de possessions cuando está en cancha)
      rf   = rate factor (cuánta de la producción NO puede reemplazarse):
             playoffs usa PLAYOFF_INJURY_RATE_FACTOR (más alto — rotación corta,
             reemplazo peor, superstars más críticos en late-game)
      sf   = status factor (out=1.0, dtd=0.50, probable=0.0)
    """
    in_po  = _is_nba_playoffs()
    impact = {}
    for e in entries:
        if not e.get('team_abb') or not e.get('ppg'): continue
        rate   = e.get('rate', 3)
        ppg    = e.get('ppg', 0.0)
        usg    = e.get('usg', 0.0)
        status = (e.get('status') or 'out').lower()
        # Normalizar status aliases
        for key in INJURY_STATUS_FACTOR:
            if key in status:
                status = key
                break
        rf_table = PLAYOFF_INJURY_RATE_FACTOR if in_po else INJURY_RATE_FACTOR
        rf = rf_table.get(rate, 0.84 if in_po else 0.80)
        sf_table = PLAYOFF_INJURY_STATUS_FACTOR if in_po else INJURY_STATUS_FACTOR
        sf = sf_table.get(status, 1.00)
        pts = round(ppg * usg * rf * sf, 3)
        t   = e['team_abb']
        impact[t] = round(impact.get(t, 0.0) + pts, 3)
    return impact


def cmd_ir_nba(refresh=False):
    """
    --ir          → muestra injuries de los equipos que juegan HOY
    --ir refresh  → refresca desde basketball-reference antes de mostrar
    --ir all      → muestra todos los equipos (no solo los de hoy)
    """
    show_all = 'all' in sys.argv

    entries = _load_nba_injuries()

    if refresh or not entries:
        print("\n  🏥 Refrescando injury report desde basketball-reference.com...\n")
        live = fetch_nba_injuries()
        print(f"  Encontrados: {len(live)} jugadores lesionados en toda la liga")

        # Cargar stats desde bref para calcular impacto
        print("  📊 Cargando stats de basketball-reference...")
        player_stats = _bref_player_stats_nba()

        # Merge: preservar rates manuales, actualizar status
        existing = {f"{e['team_abb']}|{e['player']}": e for e in entries}
        new_entries = []
        for inj in live:
            key = f"{inj['team_abb']}|{inj['player']}"
            if key in existing:
                e = existing[key].copy()
                e['status'] = inj['status']
                e['note']   = inj.get('note', '')
                # Re-lookup if stats were corrupted (0.0/0.0 from a bad prior fetch)
                if e.get('ppg', 0.0) == 0.0 and e.get('usg', 0.0) == 0.0:
                    ppg2, usg2 = _bref_lookup(inj['player'], player_stats)
                    if ppg2 is not None and usg2 is not None and (ppg2 > 0 or usg2 > 0):
                        e['ppg']    = round(ppg2, 2)
                        e['usg']    = round(usg2, 4)
                        e['rate']   = _classify_rate_nba(ppg2, usg2)
                        rf2 = INJURY_RATE_FACTOR[e['rate']]
                        sf2 = INJURY_STATUS_FACTOR.get(e['status'], 1.00)
                        e['impact'] = round(ppg2 * usg2 * rf2 * sf2, 3)
                new_entries.append(e)
            else:
                ppg, usg = _bref_lookup(inj['player'], player_stats)
                if ppg is None: ppg = 0.0
                if usg is None: usg = 0.0
                rate   = _classify_rate_nba(ppg, usg)
                rf     = INJURY_RATE_FACTOR[rate]
                sf     = INJURY_STATUS_FACTOR.get(inj['status'], 1.00)
                impact = round(ppg * usg * rf * sf, 3)
                new_entries.append({
                    "team_abb": inj['team_abb'],
                    "player":   inj['player'],
                    "status":   inj['status'],
                    "note":     inj.get('note', ''),
                    "ppg":      round(ppg, 2),
                    "usg":      round(usg, 4),
                    "rate":     rate,
                    "impact":   impact,
                })
        entries = new_entries
        _save_nba_injuries(entries)
        print(f"  ✅ {len(entries)} entradas guardadas en nba_injuries.json\n")

    if not entries:
        print("\n  Sin datos. Corre: python3 nba.py --ir refresh\n")
        return

    # ── Filtrar por equipos que juegan hoy (a menos que --ir all) ─────────────
    today_games = get_nba_schedule(TARGET_DATE)
    today_teams = set()
    game_map    = {}   # team_abb → "OPP (hora)"
    for g in today_games:
        a, h = g['away_abb'], g['home_abb']
        t    = _to_pr_time(g.get('game_time_utc', ''))
        today_teams.add(a); today_teams.add(h)
        game_map[a] = f"vs {TEAM_NICKNAMES.get(h,h)} · {t}"
        game_map[h] = f"vs {TEAM_NICKNAMES.get(a,a)} · {t}"

    # Excluir "probable" del display — se espera que jueguen, no son lesionados reales
    entries = [e for e in entries if e.get('status', 'out').lower() != 'probable']

    if today_teams and not show_all:
        display_entries = [e for e in entries if e.get('team_abb') in today_teams]
        filter_note = f"equipos jugando hoy ({len(today_teams)//2} juegos)"
    else:
        display_entries = entries
        filter_note = "toda la liga"

    if not display_entries:
        if today_teams:
            print(f"\n  ✅ Sin lesionados relevantes para los juegos de hoy.")
        else:
            print(f"\n  Sin juegos encontrados para {TARGET_DATE}. Usa --ir all para ver toda la liga.")
        return

    # ── Display ───────────────────────────────────────────────────────────────
    impact_total = compute_nba_injury_impact(display_entries)
    in_po        = _is_nba_playoffs()

    # Construir impacto por jugador con el mismo factor que compute_nba_injury_impact
    # (para que el display individual sea consistente con el total de equipo)
    def _player_impact_display(e):
        rate   = e.get('rate', 3)
        ppg    = e.get('ppg', 0.0)
        usg    = e.get('usg', 0.0)
        status = (e.get('status') or 'out').lower()
        for key in INJURY_STATUS_FACTOR:
            if key in status:
                status = key; break
        rf_table = PLAYOFF_INJURY_RATE_FACTOR if in_po else INJURY_RATE_FACTOR
        rf = rf_table.get(rate, 0.84 if in_po else 0.80)
        sf_table = PLAYOFF_INJURY_STATUS_FACTOR if in_po else INJURY_STATUS_FACTOR
        sf = sf_table.get(status, 1.00)
        return round(ppg * usg * rf * sf, 3)

    by_team = {}
    for e in display_entries:
        by_team.setdefault(e.get('team_abb', '???'), []).append(e)

    rate_lbl    = {1: "🌟 Superstar", 2: "⭐ Star", 3: "   Role"}
    status_icon = {
        "out":          "🔴 OUT",
        "doubtful":     "🟠 DOUBTFUL",
        "gtd":          "🟡 DTD",
        "questionable": "🟡 QUEST.",
        "probable":     "🟢 PROBABLE",
    }
    po_note = "  [PLAYOFFS — factor ajustado]" if in_po else ""

    print("\n" + "═"*72)
    print(f"  🏥 NBA INJURY REPORT  ·  {TARGET_DATE}  ·  {filter_note}{po_note}")
    print("═"*72)

    for team in sorted(by_team.keys()):
        players     = by_team[team]
        team_impact = impact_total.get(team, 0.0)
        nick        = TEAM_NICKNAMES.get(team, team)
        matchup     = f"  ⚔️  {game_map[team]}" if team in game_map else ""
        print(f"\n  {team} — {nick}{matchup}")
        print(f"  Impact total: -{team_impact:.2f} pts")
        print(f"  {'Jugador':<26} {'Status':<12} {'Rate':<14} {'PPG':>5} {'USG%':>6} {'Pts-':>6}")
        print(f"  {'-'*26} {'-'*12} {'-'*14} {'-'*5} {'-'*6} {'-'*6}")
        for e in sorted(players, key=lambda x: -_player_impact_display(x)):
            st    = status_icon.get(e.get('status','out'), e.get('status','').upper())
            rl    = rate_lbl.get(e.get('rate',3), '   Role')
            pts_d = _player_impact_display(e)
            print(f"  {e['player']:<26} {st:<12} {rl:<14} "
                  f"{e.get('ppg',0):>5.1f} {e.get('usg',0)*100:>5.1f}% {pts_d:>6.3f}")

    print("\n" + "═"*72)
    total_pts = sum(impact_total.values())
    print(f"  Equipos: {len(by_team)}   Jugadores: {len(display_entries)}   "
          f"Impact combinado: -{total_pts:.2f} pts")
    print("═"*72 + "\n")


def cmd_add_injury_nba():
    """
    --add-injury TEAM PLAYER RATE [STATUS]
    Agrega o actualiza jugador en nba_injuries.json.
    """
    try:
        fi     = sys.argv.index("--add-injury")
        team_a = sys.argv[fi+1].upper().strip()
        player = sys.argv[fi+2].upper().strip()
        rate   = int(sys.argv[fi+3])
        status = sys.argv[fi+4].lower() if len(sys.argv) > fi+4 else "out"
        assert rate in (1, 2, 3)
    except (ValueError, IndexError, AssertionError):
        print("  Uso: python3 nba.py --add-injury TEAM PLAYER RATE [STATUS]")
        print("     Ej: python3 nba.py --add-injury MIA BUTLER 1 out")
        print("     RATE: 1=Superstar  2=Star  3=Role player")
        print("     STATUS: out | doubtful | gtd | questionable | probable  (default: out)")
        return

    rate_lbl = {1: "SUPERSTAR", 2: "STAR", 3: "ROLE PLAYER"}
    rf = INJURY_RATE_FACTOR[rate]

    print(f"\n  🏥 Injury: {team_a} — {player} — Rate {rate} ({rate_lbl[rate]})  [{status.upper()}]")
    print("  📊 Buscando stats en basketball-reference...\n")

    player_stats = _bref_player_stats_nba()
    ppg, usg = _bref_lookup(player, player_stats)

    if ppg is not None:
        print(f"  ✅ PPG: {ppg:.1f}   USG%: {usg*100:.1f}%")
    else:
        print(f"  ⚠️  No encontrado en bref para '{player}'")
        try:
            ppg = float(input("     Ingresa PPG manualmente: ").strip())
            usg = float(input("     Ingresa USG% (ej: 24.5): ").strip()) / 100
        except (ValueError, EOFError):
            print("  ❌ Cancelado."); return

    for sk in INJURY_STATUS_FACTOR:
        if sk in status:
            status = sk; break
    sf     = INJURY_STATUS_FACTOR.get(status, 1.00)
    impact = round(ppg * usg * rf * sf, 3)
    print(f"\n  📊 Impact = {ppg:.1f} × {usg*100:.1f}% × {rf} × {sf} = {impact:.3f} pts")

    entries = _load_nba_injuries()
    found   = False
    for e in entries:
        if e['team_abb'] == team_a and player in e['player']:
            e.update({"status": status, "ppg": round(ppg,2),
                      "usg": round(usg,4), "rate": rate, "impact": impact})
            found = True
            print(f"  ✏️  Actualizado: {e['player']}")
            break
    if not found:
        entries.append({"team_abb": team_a, "player": player, "status": status,
                        "ppg": round(ppg,2), "usg": round(usg,4),
                        "rate": rate, "impact": impact})
        print(f"  ➕ Agregado: {player}")

    _save_nba_injuries(entries)
    print("  ✅ nba_injuries.json actualizado.\n")


def cmd_remove_injury_nba():
    """--remove-injury TEAM PLAYER"""
    try:
        fi     = sys.argv.index("--remove-injury")
        team_a = sys.argv[fi+1].upper().strip()
        player = sys.argv[fi+2].upper().strip()
    except (ValueError, IndexError):
        print("  Uso: python3 nba.py --remove-injury TEAM PLAYER")
        return

    entries = _load_nba_injuries()
    before  = len(entries)
    entries = [e for e in entries
               if not (e['team_abb'] == team_a and player in e['player'])]
    if len(entries) < before:
        _save_nba_injuries(entries)
        print(f"  ✅ Removido {player} de {team_a}.")
    else:
        print(f"  ⚠️  No se encontró {player} / {team_a} en el injury report.")


# ============================================================================
# MODEL COMPUTATION
# ============================================================================

def compute_game(away_abb, home_abb, stats, injury_impact=None):
    """
    Compute expected score using ORTG/DRTG/PACE model.
    Expected Score = (ORTG_team + DRTG_opponent) / 2 × PACE_avg / 100
    Win prob: Pythagorean with exp=13.91
    injury_impact: dict {team_abb: pts_to_subtract} — opcional
    """
    if injury_impact is None:
        injury_impact = {}

    a = stats.get(away_abb, {})
    h = stats.get(home_abb, {})

    ortg_a = a.get('ortg', LEAGUE_AVG_ORTG)
    drtg_a = a.get('drtg', LEAGUE_AVG_DRTG)
    ortg_h = h.get('ortg', LEAGUE_AVG_ORTG)
    drtg_h = h.get('drtg', LEAGUE_AVG_DRTG)
    pace = (a.get('pace', LEAGUE_AVG_PACE) + h.get('pace', LEAGUE_AVG_PACE)) / 2

    # Expected points base
    raw_pts_a = (ortg_a + drtg_h) / 2 * pace / 100
    raw_pts_h = (ortg_h + drtg_a) / 2 * pace / 100

    # Home court advantage: +2.5 pts regular season, +4.0 en playoffs
    # En playoffs la defensa es más intensa y el local tiene mayor ventaja
    in_playoffs = _is_nba_playoffs()
    HCA = PLAYOFF_HCA if in_playoffs else 2.5
    raw_pts_h += HCA / 2
    raw_pts_a -= HCA / 2

    # Playoffs: el scoring cae ~3.5% respecto a la temporada regular.
    # El factor es DINÁMICO — se reduce a medida que el blend de pace/ortg/drtg
    # ya absorbe la caída de playoffs. Evita double-counting:
    #
    #   po_weight=0%  → blend sin data playoff → factor completo (0.965)
    #   po_weight=40% → blend absorbe pace+ortg/drtg → factor residual (0.992)
    #                   el residual captura intensidad defensiva que el blend
    #                   no alcanza a incorporar completamente aún.
    #
    # Fórmula: factor = BASE + (RESIDUAL - BASE) * (po_w_avg / MAX_PO_W)
    if in_playoffs:
        _po_w_a   = a.get("po_weight", 0.0) / 100.0   # stored as % → fraction
        _po_w_h   = h.get("po_weight", 0.0) / 100.0
        _po_w_avg = (_po_w_a + _po_w_h) / 2.0
        _MAX_PO_W = 0.40   # max_playoff_weight en blend_regular_playoff_stats
        _FACTOR_BASE     = PLAYOFF_SCORING_FACTOR   # 0.965 — cuando po_w=0
        _FACTOR_RESIDUAL = 0.992                    # pequeño residual al máximo blend
        _dynamic_factor  = _FACTOR_BASE + (_FACTOR_RESIDUAL - _FACTOR_BASE) * min(1.0, _po_w_avg / _MAX_PO_W)
        raw_pts_a *= _dynamic_factor
        raw_pts_h *= _dynamic_factor

    # Injury adjustment
    inj_a = injury_impact.get(away_abb, 0.0)
    inj_h = injury_impact.get(home_abb, 0.0)
    pts_a = max(raw_pts_a - inj_a, 50.0)
    pts_h = max(raw_pts_h - inj_h, 50.0)

    # ── Series-specific scoring blend (playoffs only) ─────────────────────────
    # El modelo blendea stats de temporada regular + playoffs globales.
    # Pero lo que REALMENTE manda en una serie es cómo están anotando
    # estos dos equipos ENTRE SÍ — eso captura el scheme defensivo específico,
    # el pace ajustado, el matchup de rotaciones, etc.
    #
    # Ejemplo: PHX promedió 113 ORTG en la temporada, pero si en 3 juegos contra
    # OKC anotó 98/100/102, su ORTG efectivo en este matchup es ~100.
    # El mercado ve esto; el modelo sin esta info proyecta empate cuando hay +11.
    #
    # Blend: n=2→50%  n=3→60%  n=4+→70% (con momentum: últimos 2 juegos pesan 2x)
    # pts finales = pts_season * (1-w) + pts_series * w
    _series_adj_log = None
    _series_missing = False
    if in_playoffs:
        sm = _get_series_matchup_stats(away_abb, home_abb)
        if sm:
            sw = sm["series_weight"]   # 0.50 – 0.70
            tw = 1.0 - sw
            # Serie avg de puntos anotados por cada equipo (ponderado por momentum).
            # Los valores de la serie son NEUTRALES (sin HCA). Pero los valores de
            # temporada (pts_a, pts_h) ya tienen HCA aplicado (away -HCA/2, home +HCA/2).
            # Para que el blend sea consistente, aplicamos el contexto de venue de HOY
            # a los valores neutros de la serie antes de mezclar.
            # Sin esto, el HCA se diluye proporcionalmente al peso de la serie — error de ~2 pts.
            pts_a_series = sm["away_avg"] - HCA / 2   # aplica penalización de visitante
            pts_h_series = sm["home_avg"] + HCA / 2   # aplica bonificación de local
            pts_a = pts_a * tw + pts_a_series * sw
            pts_h = pts_h * tw + pts_h_series * sw
            mom_note = " [momentum]" if sm.get("momentum") else ""
            _series_adj_log = (f"serie {sm['n_games']}G{mom_note}: {away_abb} avg {sm['away_avg']:.1f} "
                               f"/ {home_abb} avg {sm['home_avg']:.1f} "
                               f"(peso serie {sw*100:.0f}%)")
        else:
            # Sin datos de serie — proyección basada SOLO en stats de temporada/playoffs acumulados.
            # Esto significa que el modelo ignora completamente cómo están jugando estos equipos
            # entre sí. El mercado SÍ tiene esta información. Esta es la mayor fuente de
            # discrepancia modelo vs mercado en playoffs.
            _series_missing = True

    # ── Rest days & R1 fatigue (segunda ronda y más allá) ────────────────────
    _rest_note    = None
    _fatigue_note = None
    _r2_note      = None
    po_round = _get_playoff_round() if in_playoffs else 0

    if in_playoffs:
        # — Rest days —
        rest_a = _get_rest_days(away_abb)
        rest_h = _get_rest_days(home_abb)
        rest_diff = rest_a - rest_h   # positivo = away más descansado
        # Cap a 2 días de diferencia para no sobre-ajustar
        rest_diff_capped = max(-2, min(2, rest_diff))
        if rest_diff_capped != 0:
            rest_adj = rest_diff_capped * REST_ADJ_PER_DAY
            pts_a += rest_adj / 2
            pts_h -= rest_adj / 2
            rested = away_abb if rest_diff_capped > 0 else home_abb
            tired  = home_abb if rest_diff_capped > 0 else away_abb
            _rest_note = (f"descanso: {rested} {abs(rest_diff)}d más que {tired} "
                          f"(adj {rest_adj:+.1f}pts)")

        # — R1 Fatigue (solo aplica en R2) —
        if po_round == 2:
            r1_a = _get_r1_games_played(away_abb, current_r2_opponent=home_abb)
            r1_h = _get_r1_games_played(home_abb, current_r2_opponent=away_abb)
            fat_a = FATIGUE_R1_TABLE.get(r1_a, 0.0)
            fat_h = FATIGUE_R1_TABLE.get(r1_h, 0.0)
            if fat_a > 0 or fat_h > 0:
                pts_a = max(pts_a - fat_a, 50.0)
                pts_h = max(pts_h - fat_h, 50.0)
                _fatigue_note = (f"fatiga R1: {away_abb} {r1_a}G (-{fat_a:.1f}pts) | "
                                 f"{home_abb} {r1_h}G (-{fat_h:.1f}pts)")

        # — Factor adicional R2+ (defensas más organizadas, rotaciones mínimas) —
        if po_round >= 2:
            pts_a *= R2_SCORING_FACTOR
            pts_h *= R2_SCORING_FACTOR
            _r2_note = f"factor R{po_round} ({R2_SCORING_FACTOR:.3f})"

    total = pts_a + pts_h
    spread = pts_h - pts_a  # positive = home favored

    # Pythagorean win prob
    exp = 13.91
    wp_h = pts_h**exp / (pts_h**exp + pts_a**exp)
    wp_a = 1 - wp_h

    def prob_to_american(p):
        if p >= 0.5:
            return int(round(-p / (1 - p) * 100))
        else:
            return int(round((1 - p) / p * 100))

    return {
        'pts_a':        round(pts_a, 1),
        'pts_h':        round(pts_h, 1),
        'total':        round(total, 1),
        'spread':       round(spread, 1),
        'wp_a':         round(wp_a * 100, 1),
        'wp_h':         round(wp_h * 100, 1),
        'ml_a':         prob_to_american(wp_a),
        'ml_h':         prob_to_american(wp_h),
        'series_note':    _series_adj_log,   # str o None — para display/debug
        'series_missing': _series_missing,  # True = sin datos de serie (mayor fuente de error en playoffs)
        'rest_note':      _rest_note,
        'fatigue_note':   _fatigue_note,
        'r2_note':        _r2_note,
        'po_round':     po_round,
        'rest_away':    _get_rest_days(away_abb) if in_playoffs else None,
        'rest_home':    _get_rest_days(home_abb) if in_playoffs else None,
    }

# ============================================================================
# MODEL-ONLY PICKS HELPERS
# ============================================================================

SIGMA_SPREAD_NBA = 11.0   # desviación estándar del margen victoria NBA (regular season)
SIGMA_TOTAL_NBA  = 16.0   # desviación estándar del total NBA (regular season)

# ── Playoffs detection ────────────────────────────────────────────────────────
def _get_playoff_series_game_log():
    """
    Jala TODOS los juegos de playoffs jugados hasta hoy desde ESPN scoreboard.
    Itera desde el primer día de playoffs (Apr 12) hasta TARGET_DATE inclusive.
    Retorna lista de:
      { "away": abb, "home": abb, "away_pts": int, "home_pts": int, "date": "YYYY-MM-DD",
        "manual": bool (True si fue ingresado a mano) }

    Estrategia de caché en 3 capas:
      1. Memoria (por sesión)
      2. Disco: nba_playoff_game_log.json — persiste entre runs
      3. ESPN API: re-fetcha si el caché de disco está desactualizado
    Los juegos ingresados manualmente con --add-series-game SIEMPRE se incluyen.
    """
    from datetime import date as _dt, timedelta as _td
    import json as _json

    # ── 1. Caché en memoria ──────────────────────────────────────
    if hasattr(_get_playoff_series_game_log, "_cache"):
        return _get_playoff_series_game_log._cache

    # ── 2. Caché en disco ────────────────────────────────────────
    disk_games = []
    disk_fetch_date = None
    if os.path.exists(PLAYOFF_GAME_LOG_CACHE):
        try:
            with open(PLAYOFF_GAME_LOG_CACHE, 'r') as _f:
                _d = _json.load(_f)
            disk_games      = _d.get("games", [])
            disk_fetch_date = _d.get("fetch_date", "")
        except Exception:
            disk_games = []

    # Separar juegos manuales (éstos SIEMPRE se conservan)
    manual_games = [g for g in disk_games if g.get("manual")]

    # Si el caché de disco es de hoy, usar directamente (+ manuales ya incluidos)
    today_str = _dt.fromisoformat(TARGET_DATE).isoformat()
    if disk_fetch_date == today_str and disk_games:
        _get_playoff_series_game_log._cache = disk_games
        return disk_games

    # ── 3. Fetch desde ESPN ──────────────────────────────────────
    espn_games = []
    try:
        start = _dt(int(TARGET_DATE[:4]), 4, 12)
        end   = _dt.fromisoformat(TARGET_DATE)
        cur   = start

        while cur <= end:
            ymd = cur.strftime("%Y%m%d")
            url = (f"https://site.api.espn.com/apis/site/v2/sports/basketball"
                   f"/nba/scoreboard?dates={ymd}")
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urlopen(req, timeout=10) as r:
                    data = _json.loads(r.read().decode())
            except Exception:
                cur += _td(days=1); continue

            for event in data.get("events", []):
                comp = event.get("competitions", [{}])[0]
                status = comp.get("status", {}).get("type", {}).get("name", "")
                if "final" not in status.lower() and "complete" not in status.lower():
                    continue
                season_type = event.get("season", {}).get("type", 0)
                if season_type != 3:
                    continue

                away_c, home_c = None, None
                for c in comp.get("competitors", []):
                    if c.get("homeAway") == "home":
                        home_c = c
                    elif c.get("homeAway") == "away":
                        away_c = c
                if not away_c or not home_c:
                    cs = comp.get("competitors", [])
                    if len(cs) >= 2:
                        away_c, home_c = cs[1], cs[0]
                    else:
                        continue

                try:
                    away_pts = int(away_c.get("score", 0))
                    home_pts = int(home_c.get("score", 0))
                except (ValueError, TypeError):
                    continue
                if away_pts == 0 and home_pts == 0:
                    continue

                away_abb = _normalize_abb(away_c.get("team", {}).get("abbreviation", ""))
                home_abb = _normalize_abb(home_c.get("team", {}).get("abbreviation", ""))
                espn_games.append({
                    "away": away_abb, "home": home_abb,
                    "away_pts": away_pts, "home_pts": home_pts,
                    "date": cur.isoformat(),
                    "manual": False,
                })
            cur += _td(days=1)

    except Exception:
        pass

    # Combinar: ESPN + manuales (sin duplicar manuales en ESPN)
    espn_keys = {(g["away"], g["home"], g["date"]) for g in espn_games}
    unique_manual = [
        g for g in manual_games
        if (g["away"], g["home"], g["date"]) not in espn_keys
    ]
    results = espn_games + unique_manual

    # Si ESPN devolvió datos, guardar en disco; si no, usar los que había en disco
    if espn_games:
        try:
            with open(PLAYOFF_GAME_LOG_CACHE, 'w') as _f:
                _json.dump({"fetch_date": today_str, "games": results}, _f, indent=2)
        except Exception:
            pass
    elif disk_games:
        # ESPN falló — usar disco aunque esté algo desactualizado
        results = disk_games
        print(f"  ⚠️  ESPN API no disponible — usando game log de disco ({disk_fetch_date or 'fecha desconocida'})")
        print(f"       Para ingresar resultados manualmente: python3 nba.py --add-series-game AWAY HOME A_PTS H_PTS DATE")

    _get_playoff_series_game_log._cache = results
    return results


def cmd_add_series_game():
    """
    --add-series-game AWAY HOME AWAY_PTS HOME_PTS [DATE]
    Ingresa manualmente el resultado de un juego de playoffs a nba_playoff_game_log.json.
    Útil cuando la API de ESPN no está disponible.

    Ejemplo: python3 nba.py --add-series-game NYK PHI 108 112 2026-05-07
    """
    import json as _json
    try:
        idx = sys.argv.index("--add-series-game")
        away     = _normalize_abb(sys.argv[idx+1].upper())
        home     = _normalize_abb(sys.argv[idx+2].upper())
        away_pts = int(sys.argv[idx+3])
        home_pts = int(sys.argv[idx+4])
        if idx+5 < len(sys.argv) and re.match(r"^\d{4}-\d{2}-\d{2}$", sys.argv[idx+5]):
            date_str = sys.argv[idx+5]
        else:
            date_str = TARGET_DATE
    except (ValueError, IndexError):
        print("  ❌ Uso: python3 nba.py --add-series-game AWAY HOME AWAY_PTS HOME_PTS [FECHA]")
        print("     Ejemplo: python3 nba.py --add-series-game NYK PHI 108 112 2026-05-07")
        return

    # Cargar log existente
    existing = []
    fetch_date = ""
    if os.path.exists(PLAYOFF_GAME_LOG_CACHE):
        try:
            with open(PLAYOFF_GAME_LOG_CACHE, 'r') as _f:
                _d = _json.load(_f)
            existing   = _d.get("games", [])
            fetch_date = _d.get("fetch_date", "")
        except Exception:
            existing = []

    # Evitar duplicados (mismo partido mismo día)
    dup = any(
        g["away"] == away and g["home"] == home and g["date"] == date_str
        for g in existing
    )
    if dup:
        print(f"  ⚠️  Ya existe un juego {away} @ {home} el {date_str} en el log.")
        print(f"       Usa --list-series-games para verlos.")
        return

    new_game = {
        "away": away, "home": home,
        "away_pts": away_pts, "home_pts": home_pts,
        "date": date_str,
        "manual": True,
    }
    existing.append(new_game)

    with open(PLAYOFF_GAME_LOG_CACHE, 'w') as _f:
        _json.dump({"fetch_date": fetch_date, "games": existing}, _f, indent=2)

    winner = away if away_pts > home_pts else home
    margin = abs(away_pts - home_pts)
    print(f"  ✅ Juego agregado: {away} {away_pts} @ {home} {home_pts}  ({date_str})")
    print(f"     Ganador: {winner}  |  Margen: {margin} pts  |  [manual]")
    print(f"\n  Regenera picks: python3 nba.py --picks")


def cmd_list_series_games():
    """
    --list-series-games [TEAM]
    Lista los juegos de playoffs en el caché (ESPN + manuales).
    """
    import json as _json
    if not os.path.exists(PLAYOFF_GAME_LOG_CACHE):
        print("  No hay game log de playoffs. Corre --picks para poblar.")
        return

    try:
        with open(PLAYOFF_GAME_LOG_CACHE, 'r') as _f:
            data = _json.load(_f)
    except Exception as _e:
        print(f"  ❌ Error leyendo game log: {_e}")
        return

    games      = data.get("games", [])
    fetch_date = data.get("fetch_date", "?")
    filter_team = sys.argv[sys.argv.index("--list-series-games")+1].upper() \
        if "--list-series-games" in sys.argv and \
           sys.argv.index("--list-series-games")+1 < len(sys.argv) and \
           not sys.argv[sys.argv.index("--list-series-games")+1].startswith("-") else None

    if filter_team:
        filter_team = _normalize_abb(filter_team)
        games = [g for g in games if g["away"] == filter_team or g["home"] == filter_team]

    print(f"\n  🏀 NBA Playoff Game Log  (fetch: {fetch_date})")
    print(f"  {'AWAY':6}  {'PTS':>4}  {'HOME':6}  {'PTS':>4}  {'DATE':12}  {'SRC'}")
    print(f"  {'-'*55}")
    for g in sorted(games, key=lambda x: x.get("date","")):
        src = "✏️  manual" if g.get("manual") else "ESPN"
        print(f"  {g['away']:6}  {g['away_pts']:>4}  {g['home']:6}  {g['home_pts']:>4}"
              f"  {g['date']:12}  {src}")
    print(f"\n  Total: {len(games)} juegos")


def _get_series_matchup_stats(away_abb, home_abb):
    """
    Calcula ORTG/DRTG/total específicos de la serie para este matchup, basado en
    los scores reales de los juegos jugados.

    Lógica:
      - Fetcha game log de playoffs (ESPN, cacheado)
      - Filtra juegos entre estos dos equipos
      - Calcula pts/juego de cada equipo EN ESTA SERIE
      - Estima pace de la serie (si avg total es diferente al season avg)
      - Retorna dict con los stats de la serie (o None si <2 juegos)

    El blend final (en compute_game) pesa:
      n=2 juegos → 40% serie
      n=3 juegos → 55% serie
      n=4 juegos → 65% serie
      n=5+       → 70% serie (máximo — la serie tiene info, pero lesiones/ajustes cambian)
    """
    games = _get_playoff_series_game_log()
    if not games:
        return None

    # Juegos entre estos dos equipos (independiente de quién es local)
    series_games = [
        g for g in games
        if (g["away"] == away_abb and g["home"] == home_abb) or
           (g["away"] == home_abb and g["home"] == away_abb)
    ]
    n = len(series_games)
    if n < 2:   # necesitamos al menos 2 juegos para tener señal real
        return None

    # Ordenar por fecha para momentum (juegos más recientes pesan más)
    series_games_sorted = sorted(series_games, key=lambda x: x.get("date", ""))

    # ── Normalización de venue ────────────────────────────────────────────────
    # PROBLEMA: si todos los juegos de la serie fueron en el mismo estadio,
    # los promedios embeben esa ventaja de local. Cuando hoy los roles se invierten
    # (los que eran home ahora son away y viceversa), hay double-counting con el
    # HCA que compute_game ya aplica por separado.
    #
    # SOLUCIÓN: convertir cada juego a puntuación "neutral" quitando la ventaja de
    # local (HCA/2) al home team y sumándosela al away team. Así compute_game puede
    # aplicar el HCA de hoy correctamente sin duplicar.
    #
    # Fórmula: pts_home_neutral = pts_home - HCA/2
    #          pts_away_neutral = pts_away + HCA/2
    _hca = PLAYOFF_HCA / 2   # la mitad de la ventaja (compute_game aplica ±HCA/2)

    away_pts_weighted = 0.0
    home_pts_weighted = 0.0
    total_weight      = 0.0
    for i, g in enumerate(series_games_sorted):
        w = 2.0 if i >= n - 2 else 1.0   # último 2 juegos: doble peso (momentum)

        if g["away"] == away_abb:
            # away_abb jugó como AWAY en este juego → puntuación de away
            pts_away_raw = g["away_pts"]
            pts_home_raw = g["home_pts"]
            # Neutralizar: away recibió penalización -HCA/2, darle de vuelta
            pts_away_neutral = pts_away_raw + _hca
            # home recibió bonificación +HCA/2, quitarla
            pts_home_neutral = pts_home_raw - _hca
            away_pts_weighted += pts_away_neutral * w
            home_pts_weighted += pts_home_neutral * w
        else:
            # away_abb jugó como HOME en este juego → sus pts están en g["home_pts"]
            pts_away_neutral = g["home_pts"] - _hca   # era home, quitar bonificación
            pts_home_neutral = g["away_pts"] + _hca   # era away, darle la penalización de vuelta
            away_pts_weighted += pts_away_neutral * w
            home_pts_weighted += pts_home_neutral * w
        total_weight += w

    away_avg = away_pts_weighted / total_weight
    home_avg = home_pts_weighted / total_weight
    series_total_avg = (away_pts_weighted + home_pts_weighted) / total_weight

    # Peso de la serie vs temporada: subido de 45% → 70% máx
    # El mercado pesa la actuación reciente en la serie al 60-70%.
    # La preocupación original (injurias temporales que distorsionan la serie)
    # se maneja con el momentum (últimos 2 juegos pesan 2x), no reduciendo el cap.
    #
    # Fórmula: n=2 → 50%  n=3 → 60%  n=4+ → 70%
    series_weight = min(0.70, 0.50 + (n - 2) * 0.10)

    return {
        "n_games":       n,
        "away_avg":      round(away_avg, 1),
        "home_avg":      round(home_avg, 1),
        "total_avg":     round(series_total_avg, 1),
        "series_weight": round(series_weight, 3),
        "momentum":      True,   # flag para que el log muestre que se usó momentum
    }


def _get_playoff_series_scores():
    """
    Jala el score actual de cada serie de playoffs desde ESPN API.
    Retorna dict: { frozenset({abb1, abb2}): {"leader": abb, "leader_wins": N, "trailer_wins": M} }
    o {} si falla.

    ESPN endpoint: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
    y el bracket: https://site.api.espn.com/apis/v2/sports/basketball/nba/playoffs
    """
    import json as _json
    _ESPN2ESPN = {  # normalizar abreviaciones ESPN → nuestras abreviaciones
        "GS": "GSW", "SA": "SAS", "NY": "NYK", "NO": "NOP", "WSH": "WAS",
        "UTAH": "UTA", "PHO": "PHX",
    }
    def _norm(a):
        a = str(a).upper().strip()
        return _ESPN2ESPN.get(a, a)

    try:
        url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/playoffs"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=12) as r:
            data = _json.loads(r.read().decode())

        series_map = {}
        # Navegar estructura ESPN: data["rounds"][*]["series"][*]
        for rnd in data.get("rounds", []):
            for ser in rnd.get("series", []):
                competitors = ser.get("competitors", [])
                if len(competitors) < 2:
                    continue
                wins = {}
                abbs = []
                for comp in competitors:
                    abb = _norm(comp.get("abbreviation") or comp.get("team", {}).get("abbreviation", ""))
                    w   = int(comp.get("wins", 0))
                    wins[abb] = w
                    abbs.append(abb)
                if len(abbs) < 2:
                    continue
                a1, a2 = abbs[0], abbs[1]
                w1, w2 = wins.get(a1, 0), wins.get(a2, 0)
                if w1 >= w2:
                    leader, l_wins, t_wins = a1, w1, w2
                else:
                    leader, l_wins, t_wins = a2, w2, w1
                key = frozenset({a1, a2})
                series_map[key] = {
                    "leader":       leader,
                    "leader_wins":  l_wins,
                    "trailer_wins": t_wins,
                    "total_games":  l_wins + t_wins,
                }
        return series_map

    except Exception:
        return {}


# Cache de series scores (se refresca una vez por sesión)
_SERIES_SCORES_CACHE: dict = {}
_SERIES_SCORES_FETCHED: bool = False

def _series_scores():
    """Devuelve series scores cacheados (fetch una sola vez por sesión)."""
    global _SERIES_SCORES_CACHE, _SERIES_SCORES_FETCHED
    if not _SERIES_SCORES_FETCHED:
        _SERIES_SCORES_CACHE   = _get_playoff_series_scores()
        _SERIES_SCORES_FETCHED = True
    return _SERIES_SCORES_CACHE


def _get_series_context(away_abb, home_abb):
    """
    Retorna info de la serie para este matchup, o None si no está en playoffs / no se encuentra.
    {
      "leader":        "OKC",   # equipo que va ganando la serie
      "leader_wins":   3,
      "trailer_wins":  1,
      "total_games":   4,
      "series_str":    "OKC 3-1",
      "dominance":     2.0,     # diferencia de wins → cuánto domina el líder
    }
    """
    scores = _series_scores()
    if not scores:
        return None
    key = frozenset({away_abb, home_abb})
    s   = scores.get(key)
    if not s:
        return None
    return {
        **s,
        "series_str": f"{s['leader']} {s['leader_wins']}-{s['trailer_wins']}",
        "dominance":  s["leader_wins"] - s["trailer_wins"],
    }


def _get_active_playoff_teams(season_year):
    """
    Retorna un set de ESPN abbreviations de equipos AÚN VIVOS en playoffs.
    Deriva la info del game log de ESPN (mismo que ya usamos en compute_game).
    Lógica: agrupar juegos por par de equipos (serie), contar wins.
    Si alguien llega a 4 wins → serie terminada, solo el ganador sigue vivo.
    Si nadie llega a 4 wins → serie en curso, ambos vivos.
    Retorna None si no se puede determinar.
    """
    try:
        game_log = _get_playoff_series_game_log()
        if not game_log:
            return None

        # Agrupar juegos por serie (par canónico: frozenset de los dos equipos)
        from collections import defaultdict
        series_wins = defaultdict(lambda: defaultdict(int))  # {frozenset: {team: wins}}

        for g in game_log:
            away, home = g["away"], g["home"]
            key = frozenset([away, home])
            winner = away if g["away_pts"] > g["home_pts"] else home
            series_wins[key][winner] += 1

        WINS_TO_ADVANCE = 4
        active = set()

        for key, wins in series_wins.items():
            teams = list(key)
            t1, t2 = teams[0], teams[1]
            w1 = wins.get(t1, 0)
            w2 = wins.get(t2, 0)

            if max(w1, w2) >= WINS_TO_ADVANCE:
                # Serie terminada — solo el ganador
                winner = t1 if w1 >= WINS_TO_ADVANCE else t2
                active.add(winner)
            else:
                # Serie en curso — ambos vivos
                active.add(t1)
                active.add(t2)

        return active if active else None

    except Exception:
        return None   # no se puede determinar → mostrar todos los playoff teams


def _is_nba_playoffs(date_str=None):
    """
    Retorna True si la fecha corresponde a primera ronda / playoffs NBA.
    Playoffs: típicamente del 12 de abril al 20 de junio.
    """
    from datetime import date as _date
    try:
        if date_str:
            d = _date.fromisoformat(str(date_str)[:10])
        else:
            d = _date.today()
    except Exception:
        return False
    return (d.month == 4 and d.day >= 12) or d.month == 5 or \
           (d.month == 6 and d.day <= 20)

# Constantes ajustadas para playoffs
# Calibración 2026-05-10: OVERs R1 6W-1L → barra de OVER era demasiado alta.
# UNDERs R2 perdiendo consistencia → barra subió. Spreads: ajuste Spurs -5.5 (1.8pt edge, hit).
PLAYOFF_SCORING_FACTOR  = 0.965  # el marcador cae ~3.5% en playoffs vs regular season
PLAYOFF_HCA             = 3.5    # ↓ calibrado 4.0→3.5: en R2+ los equipos están más parejos,
                                  # la ventaja de local se comprime vs regular season.
                                  # Investigación FiveThirtyEight NBA 2016-2024: playoffs HCA ≈ 3.0-3.5
SIGMA_SPREAD_PLAYOFF    = 13.5   # más incertidumbre = más difícil cubrir → menos picks de spread
SIGMA_TOTAL_PLAYOFF     = 22.0   # totales en playoffs son MUY difíciles de proyectar
MIN_SPREAD_EDGE_PLAYOFF = 1.5    # ↓ bajado de 3.0 → en playoffs incluso 1.5pt de edge = valor real
MIN_DIFF_OVR_PLAYOFF    = 4.5    # ↓ bajado de 6.5 → OVERs R1 fueron 6W-1L, la barra era excesiva
MIN_DIFF_UND_PLAYOFF    = 5.5    # ↑ subido de 3.0 → UNDERs R2 perdiendo fuerza, más selectivo
MIN_EDGE_ML_PLAYOFF     = 6.0    # mínimo de edge % para picks ML en playoffs

# ── Constantes segunda ronda / rondas avanzadas ──────────────────────────────
R2_SCORING_FACTOR       = 0.992  # R2+ es más defensivo: ~0.8% adicional al playoff factor
REST_ADJ_PER_DAY        = 0.45   # pts por cada día de ventaja en descanso (cap 2 días)
FATIGUE_R1_TABLE        = {4: 0.0, 5: 0.4, 6: 0.9, 7: 1.6}  # penalización por juegos R1
MIN_DIFF_OVR_R2         = 5.5    # ↓ bajado de 8.5 → alineado con calibración de OVERs

# ── Market shrinkage para ML en playoffs ─────────────────────────────────────
# Cuando el mercado pone a un equipo como underdog significativo en playoffs
# (+120 o más), el mercado sabe algo que el modelo de ratings no captura:
# contexto de serie, matchup defense, rotación, momentum. Blendear con mercado.
_NBA_MODEL_W  = 0.65   # peso del modelo (65%)
_NBA_MARKET_W = 0.35   # peso del mercado (35%)
_NBA_DOG_MODEL_W  = 0.50  # peso modelo cuando el equipo es underdog (+120 a +180)
_NBA_DOG_MARKET_W = 0.50  # peso mercado cuando el equipo es underdog
_NBA_BIG_DOG_MODEL_W  = 0.40  # peso modelo cuando es gran underdog (+180+)
_NBA_BIG_DOG_MARKET_W = 0.60  # peso mercado cuando es gran underdog


def _get_playoff_round(date_str=None):
    """
    Detecta la ronda de playoffs por fecha.
    R1: Apr 12 – May 5
    R2: May 6 – May 28
    Conf Finals: May 19 – Jun 8  (overlap intencional — detección por fechas aproximadas)
    Finals: Jun 1+
    Retorna 1, 2, 3 o 4.
    """
    from datetime import date as _d
    try:
        d = _d.fromisoformat((date_str or TARGET_DATE)[:10])
    except Exception:
        return 1
    if d.month == 4 or (d.month == 5 and d.day <= 5):
        return 1
    elif d.month == 5 and d.day <= 27:
        return 2
    elif (d.month == 5 and d.day > 27) or (d.month == 6 and d.day <= 12):
        return 3   # Conference Finals
    else:
        return 4   # NBA Finals


def _get_rest_days(team_abb):
    """
    Días de descanso antes del juego de TARGET_DATE.
    0 = back-to-back, 1 = un día de descanso, 2+ = bien descansado.
    Retorna 2 si no hay historial (asume descanso normal).
    """
    from datetime import date as _d
    games   = _get_playoff_series_game_log()
    played  = sorted(
        g["date"] for g in games
        if (g["away"] == team_abb or g["home"] == team_abb)
    )
    if not played:
        return 2
    last = _d.fromisoformat(played[-1])
    today = _d.fromisoformat(TARGET_DATE)
    return max(0, (today - last).days - 1)


def _get_r1_games_played(team_abb, current_r2_opponent=None):
    """
    Juegos totales jugados en primera ronda (antes del inicio de R2).
    Si current_r2_opponent se especifica, excluye los juegos de la serie actual de R2.
    Usado para calcular fatiga acumulada al entrar a segunda ronda.
    """
    games = _get_playoff_series_game_log()
    if not games:
        return 4  # asume sweep si no hay datos (neutral)

    team_games = [g for g in games
                  if g["away"] == team_abb or g["home"] == team_abb]

    if current_r2_opponent:
        # Excluir juegos de la serie actual (R2)
        team_games = [
            g for g in team_games
            if g["away"] != current_r2_opponent and g["home"] != current_r2_opponent
        ]

    r1_count = len(team_games)
    # Sanitize: R1 es entre 4 y 7 juegos
    return max(4, min(7, r1_count)) if r1_count > 0 else 4


def _normal_cdf_nba(z):
    """Aproximación CDF normal estándar."""
    sign = 1 if z >= 0 else -1
    z = abs(z)
    t = 1.0 / (1.0 + 0.2316419 * z)
    p = t * (0.319381530 + t * (-0.356563782
               + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    base = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z) * p
    return (1.0 - base) if sign > 0 else base


def _american_to_prob(odds_val):
    """Implied prob from American odds (including vig)."""
    if odds_val > 0:
        return 100.0 / (100.0 + odds_val)
    else:
        return abs(odds_val) / (100.0 + abs(odds_val))


def _ev_from_prob(win_prob, market_odds):
    """EV% given win probability and market American odds.
    For negative odds (favorites): EV = win_prob*(100/|odds|) - (1-win_prob)
    For positive odds (underdogs): EV = win_prob*(odds/100) - (1-win_prob)
    Result is a fraction (0.10 = 10% EV).
    """
    if market_odds > 0:
        return win_prob * (market_odds / 100.0) - (1.0 - win_prob)
    else:
        return win_prob * (100.0 / abs(market_odds)) - (1.0 - win_prob)


def _compute_nba_picks_model(games, stats, market_odds=None, injury_impact=None,
                              market_signals=None):
    """
    Calcula los mejores picks para cada partido comparando ML, Spread y Total
    contra las odds del mercado (o -110 estándar si no hay odds disponibles).
    Si market_signals está disponible, añade confirmación de sharp money:
      - FADE: señales van en contra del pick → se omite
      - CONFIRM (strength ≥ 1): señal de sharps en mismo lado → pick sólido
    Retorna lista de picks ordenados por EV descendente.
    """
    if market_signals is None:
        market_signals = {}
    if market_odds is None:
        market_odds = {}
    if injury_impact is None:
        injury_impact = {}

    # Filtro de juegos ya iniciados — igual que MLB
    _now_utc = None
    try:
        from datetime import timezone as _tz
        _now_utc = __import__('datetime').datetime.now(_tz.utc).replace(tzinfo=None)
    except Exception:
        pass

    picks = []
    _skipped_started = 0
    for game in games:
        # Omitir juegos que ya comenzaron (odds en vivo no válidos para picks pre-game)
        _gut = game.get("game_time_utc", "")
        if _gut and _now_utc is not None:
            try:
                import datetime as _dtm
                _clean = _gut.replace("Z", "").split("+")[0]
                _gdt   = None
                for _fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
                    try:
                        _gdt = _dtm.datetime.strptime(_clean, _fmt)
                        break
                    except ValueError:
                        continue
                if _gdt is not None and _now_utc > _gdt:
                    _skipped_started += 1
                    continue
            except Exception:
                pass

        away = game['away_abb']
        home = game['home_abb']
        model = compute_game(away, home, stats, injury_impact=injury_impact)

        # Intentar obtener odds del mercado para este juego
        mkt = market_odds.get(f"{away}_{home}", {})
        bookmakers = mkt.get('bookmakers', [])

        # Extraer odds ML del primer book disponible
        mkt_ml_away, mkt_ml_home = None, None
        mkt_spread_line, mkt_spread_dog_odds = None, None
        mkt_spread_fav_abb = None   # abreviación del equipo favorito según el mercado
        mkt_total, mkt_total_over_odds, mkt_total_under_odds = None, None, None

        # Scan ALL bookmakers — take first that has each market type.
        # Don't stop at bookmakers[:1]; some books omit spreads while others have them.
        for bk in bookmakers:
            for mkt_obj in bk.get('markets', []):
                if mkt_obj['key'] in ('h2h', 'moneyline') and mkt_ml_away is None:
                    for oc in mkt_obj.get('outcomes', []):
                        name_abb = _full_name_to_abb(oc['name'])
                        if name_abb == away:
                            mkt_ml_away = oc['price']
                        elif name_abb == home:
                            mkt_ml_home = oc['price']
                elif mkt_obj['key'] == 'spreads' and mkt_spread_line is None:
                    for oc in mkt_obj.get('outcomes', []):
                        pt = oc.get('point')
                        if pt is not None and pt < 0:
                            mkt_spread_line = abs(pt)
                            mkt_spread_dog_odds = oc.get('price', -110)
                            # Guardar quién es el favorito del mercado (team con pt < 0)
                            mkt_spread_fav_abb = _full_name_to_abb(oc.get('name', ''))
                elif mkt_obj['key'] == 'totals' and mkt_total is None:
                    for oc in mkt_obj.get('outcomes', []):
                        if oc['name'].upper() == 'OVER':
                            mkt_total = oc.get('point')
                            mkt_total_over_odds = oc['price']
                        elif oc['name'].upper() == 'UNDER':
                            mkt_total_under_odds = oc['price']
            # Stop early once all three markets found
            if all(x is not None for x in [mkt_ml_away, mkt_spread_line, mkt_total]):
                break

        # Defaults si no hay odds de mercado
        _no_market_data = mkt_ml_away is None  # flag para marcar picks sin datos reales
        if mkt_ml_away is None:
            mkt_ml_away = model['ml_a']
        if mkt_ml_home is None:
            mkt_ml_home = model['ml_h']
        if mkt_spread_line is None:
            # El mercado typically tiene el spread ~30% más conservador que el modelo.
            # Usar modelo * 0.70 como estimación conservadora para no generar falsos picks,
            # pero sí capturar casos donde el modelo tiene ventaja real.
            # Ejemplo: modelo -9.2 → mercado estimado -6.5 → edge ~2.7 pts
            mkt_spread_line = round(abs(model['spread']) * 0.70 / 0.5) * 0.5
            # Asumir favorito del modelo como favorito estimado del mercado
            mkt_spread_fav_abb = away if model['spread'] < 0 else home
        if mkt_total is None:
            # Use a "standard" total that's 2 pts higher (market typically +2 over model)
            mkt_total = round(model['total'] + 2.0)
        if mkt_total_over_odds is None:
            mkt_total_over_odds = -110
        if mkt_total_under_odds is None:
            mkt_total_under_odds = -110

        candidates = []
        away_nick = TEAM_NICKNAMES.get(away, away)
        home_nick = TEAM_NICKNAMES.get(home, home)

        # Score de la serie para display
        _sc = _get_series_context(away, home) if _is_nba_playoffs() else None
        _series_suffix = f" [{_sc['series_str']}]" if _sc else ""
        game_label = f"{away_nick} @ {home_nick}{_series_suffix}"

        def _nba_fmt_odds(o):
            o = int(o)
            return f"+{o}" if o > 0 else str(o)

        _mkt_tag = " [mkt~est]" if _no_market_data else ""  # marcar si mercado fue estimado

        def _nba_shrink_wp(wp_raw, mkt_odds):
            """Shrinkage asimétrico: underdogs reciben más peso del mercado.
            En playoffs el mercado sabe del contexto de serie, momentum,
            rotación — el modelo de ratings no captura esto.
            """
            mkt_p = _american_to_prob(mkt_odds)
            is_dog = mkt_odds > 0   # underdog si odds positivas
            if mkt_odds >= 180:      # gran underdog +180+
                mw, mkw = _NBA_BIG_DOG_MODEL_W, _NBA_BIG_DOG_MARKET_W
            elif mkt_odds >= 120:    # underdog moderado +120-+179
                mw, mkw = _NBA_DOG_MODEL_W, _NBA_DOG_MARKET_W
            else:                    # favorito o underdog leve
                mw, mkw = _NBA_MODEL_W, _NBA_MARKET_W
            return wp_raw * mw + mkt_p * mkw

        # ── ML AWAY ──
        wp_a_raw = model['wp_a'] / 100.0
        wp_a = _nba_shrink_wp(wp_a_raw, mkt_ml_away)
        ev_ml_a = _ev_from_prob(wp_a, mkt_ml_away)
        mkt_prob_ml_a = _american_to_prob(mkt_ml_away)
        edge_ml_a = (wp_a - mkt_prob_ml_a) * 100
        candidates.append({
            "game": game_label,
            "pick": f"{away_nick} ML{_mkt_tag}",
            "type": "ML",
            "team_abb": away,
            "odds": mkt_ml_away,
            "modelo":  _nba_fmt_odds(model['ml_a']),
            "mercado": _nba_fmt_odds(mkt_ml_away) + ("~" if _no_market_data else ""),
            "edge":    f"{edge_ml_a:+.1f}%",
            "ev":      f"{ev_ml_a*100:+.1f}%",
            "_ev":     ev_ml_a,
            "_no_market": _no_market_data,
            "_wp_raw": round(wp_a_raw * 100, 1),  # modelo puro (sin shrinkage)
        })

        # ── ML HOME ──
        wp_h_raw = model['wp_h'] / 100.0
        wp_h = _nba_shrink_wp(wp_h_raw, mkt_ml_home)
        ev_ml_h = _ev_from_prob(wp_h, mkt_ml_home)
        mkt_prob_ml_h = _american_to_prob(mkt_ml_home)
        edge_ml_h = (wp_h - mkt_prob_ml_h) * 100
        candidates.append({
            "game": game_label,
            "pick": f"{home_nick} ML{_mkt_tag}",
            "type": "ML",
            "team_abb": home,
            "odds": mkt_ml_home,
            "modelo":  _nba_fmt_odds(model['ml_h']),
            "mercado": _nba_fmt_odds(mkt_ml_home) + ("~" if _no_market_data else ""),
            "edge":    f"{edge_ml_h:+.1f}%",
            "ev":      f"{ev_ml_h*100:+.1f}%",
            "_ev":     ev_ml_h,
            "_no_market": _no_market_data,
            "_wp_raw": round(wp_h_raw * 100, 1),
        })

        # ── SPREAD (market underdog +spread) ──
        model_spread = model['spread']
        # model_spread > 0 → home is model-favored; negative → away is model-favored
        model_spread_abs = abs(model_spread)
        model_spread_str = f"-{model_spread_abs:.1f}" if model_spread_abs >= 0.5 else "PICK"

        # El spread siempre se recomienda en el UNDERDOG del MERCADO (quien recibe puntos).
        # Casos:
        #   A) Mercado y modelo de acuerdo en favorito:
        #      edge = mkt_spread_line - model_spread_abs  (cuánto "cushion" de más da el mercado)
        #   B) Mercado y modelo en DESACUERDO (mercado fav ≠ modelo fav):
        #      el underdog del mercado es el favorito del modelo → edge = mkt_spread + model_spread_abs
        mkt_fav_is_away = (mkt_spread_fav_abb == away) if mkt_spread_fav_abb else (model_spread < 0)
        if mkt_fav_is_away:
            # Mercado: AWAY es favorito
            mkt_agrees_with_model = (model_spread <= 0)  # modelo también fav away
            if mkt_agrees_with_model:
                raw_edge = mkt_spread_line - model_spread_abs
                if raw_edge >= 0:
                    # Mercado da más puntos de ventaja de los que proyecta el modelo
                    # → valor en el HOME underdog (recibe demasiados puntos)
                    spread_edge      = raw_edge
                    spread_pick_nick = home_nick
                    spread_pick_abb  = home
                    spread_pick_str  = f"{home_nick} +{mkt_spread_line:.1f}{_mkt_tag}"
                    spread_odds_disp = f"+{mkt_spread_line:.1f}"
                else:
                    # Modelo proyecta favorito ganando por MÁS que el mercado
                    # → valor en el AWAY favorito (lay the spread)
                    spread_edge      = abs(raw_edge)
                    spread_pick_nick = away_nick
                    spread_pick_abb  = away
                    spread_pick_str  = f"{away_nick} -{mkt_spread_line:.1f}{_mkt_tag}"
                    spread_odds_disp = f"-{mkt_spread_line:.1f}"
            else:
                # Modelo fav HOME pero mercado da HOME +spread → desacuerdo total
                # ⚠️  En playoffs esto suele ser FALSO — marcado para filtro.
                spread_edge      = mkt_spread_line + model_spread_abs
                spread_pick_nick = home_nick
                spread_pick_abb  = home
                spread_pick_str  = f"{home_nick} +{mkt_spread_line:.1f}{_mkt_tag}"
                spread_odds_disp = f"+{mkt_spread_line:.1f}"
        else:
            # Mercado: HOME es favorito
            mkt_agrees_with_model = (model_spread >= 0)  # modelo también fav home
            if mkt_agrees_with_model:
                raw_edge = mkt_spread_line - model_spread_abs
                if raw_edge >= 0:
                    # Mercado da más puntos de los que proyecta el modelo
                    # → valor en el AWAY underdog
                    spread_edge      = raw_edge
                    spread_pick_nick = away_nick
                    spread_pick_abb  = away
                    spread_pick_str  = f"{away_nick} +{mkt_spread_line:.1f}{_mkt_tag}"
                    spread_odds_disp = f"+{mkt_spread_line:.1f}"
                else:
                    # Modelo proyecta favorito ganando por MÁS que el mercado
                    # → valor en el HOME favorito (lay the spread)
                    spread_edge      = abs(raw_edge)
                    spread_pick_nick = home_nick
                    spread_pick_abb  = home
                    spread_pick_str  = f"{home_nick} -{mkt_spread_line:.1f}{_mkt_tag}"
                    spread_odds_disp = f"-{mkt_spread_line:.1f}"
            else:
                # Modelo fav AWAY pero mercado da AWAY +spread → desacuerdo total
                # ⚠️  En playoffs esto suele ser FALSO — marcado para filtro.
                spread_edge      = mkt_spread_line + model_spread_abs
                spread_pick_nick = away_nick
                spread_pick_abb  = away
                spread_pick_str  = f"{away_nick} +{mkt_spread_line:.1f}{_mkt_tag}"
                spread_odds_disp = f"+{mkt_spread_line:.1f}"

        cover_prob = _normal_cdf_nba(spread_edge / SIGMA_SPREAD_NBA)
        ev_spread  = _ev_from_prob(cover_prob, -110)
        candidates.append({
            "game":          game_label,
            "pick":          spread_pick_str,
            "type":          "SPREAD",
            "team_abb":      spread_pick_abb,
            "odds":          -110,
            "modelo":        model_spread_str,
            "mercado":       spread_odds_disp + ("~" if _no_market_data else ""),
            "edge":          f"{spread_edge:+.1f} pts",
            "ev":            f"{ev_spread*100:+.1f}%",
            "_ev":           ev_spread,
            "_mkt_agrees":   mkt_agrees_with_model,
            "_mkt_spread":   mkt_spread_line,
            "_no_market":    _no_market_data,
        })

        # ── TOTAL OVER/UNDER ──
        total_diff = model['total'] - mkt_total
        # OVER
        over_prob = _normal_cdf_nba(total_diff / SIGMA_TOTAL_NBA)
        ev_over   = _ev_from_prob(over_prob, mkt_total_over_odds)
        candidates.append({
            "game":     game_label,
            "pick":     f"OVER {mkt_total:.1f}",
            "type":     "OVER",
            "team_abb": None,
            "odds":     mkt_total_over_odds,
            "modelo":   f"Proj {model['total']:.1f}",
            "mercado":  f"Line {mkt_total:.1f}",
            "edge":     f"{total_diff:+.1f} pts",
            "ev":       f"{ev_over*100:+.1f}%",
            "_ev":      ev_over,
        })
        # UNDER
        under_prob = 1.0 - over_prob
        ev_under   = _ev_from_prob(under_prob, mkt_total_under_odds)
        candidates.append({
            "game":     game_label,
            "pick":     f"UNDER {mkt_total:.1f}",
            "type":     "UNDER",
            "team_abb": None,
            "odds":     mkt_total_under_odds,
            "modelo":   f"Proj {model['total']:.1f}",
            "mercado":  f"Line {mkt_total:.1f}",
            "edge":     f"{-total_diff:+.1f} pts",
            "ev":       f"{ev_under*100:+.1f}%",
            "_ev":      ev_under,
        })

        # Inyectar away_abb / home_abb / game_time_utc en todos los candidates
        # (necesario para que _game_header pueda renderizar logos y nombre del matchup)
        for c in candidates:
            c.setdefault("away_abb", away)
            c.setdefault("home_abb", home)
            c.setdefault("game_time_utc", game.get("game_time_utc", ""))

        # Selección: un pick por juego, mayor EV con filtros de sensatez
        # En playoffs los thresholds son más estrictos — mercados más eficientes,
        # defensas más intensas, totales más bajos y menos predecibles.
        _playoffs = _is_nba_playoffs()
        MIN_EV          = 0.04
        MIN_EDGE_ML     = MIN_EDGE_ML_PLAYOFF    if _playoffs else 4.0
        MIN_SPREAD_EDGE = MIN_SPREAD_EDGE_PLAYOFF if _playoffs else 2.5
        _sigma_spread   = SIGMA_SPREAD_PLAYOFF    if _playoffs else SIGMA_SPREAD_NBA
        _sigma_total    = SIGMA_TOTAL_PLAYOFF     if _playoffs else SIGMA_TOTAL_NBA

        # Recalcular cover/over probs con sigma ajustado de playoffs
        if _playoffs:
            # Rebuild spread candidate with playoff sigma — usar el spread_edge
            # ya calculado correctamente (que ya maneja modelo/mercado en desacuerdo)
            sp_cprob = _normal_cdf_nba(spread_edge / _sigma_spread)
            sp_ev    = _ev_from_prob(sp_cprob, -110)
            for c in candidates:
                if c["type"] == "SPREAD":
                    c["_ev"] = sp_ev
            # Rebuild total candidates with playoff sigma
            total_diff = model['total'] - mkt_total
            over_p  = _normal_cdf_nba(total_diff / _sigma_total)
            under_p = 1.0 - over_p
            for c in candidates:
                if c["type"] == "OVER":
                    c["_ev"] = _ev_from_prob(over_p,  mkt_total_over_odds  or -110)
                elif c["type"] == "UNDER":
                    c["_ev"] = _ev_from_prob(under_p, mkt_total_under_odds or -110)
            candidates.sort(key=lambda x: -x["_ev"])

        def _edge_float_nba(c):
            try:
                return float(str(c.get("edge", "0")).replace("%","").replace("+","").split()[0])
            except:
                return 0.0

        # Juice cap SIEMPRE (regular season y playoffs): ML peor que -150 se descarta.
        # Más de -150 de juice destruye el valor — spread/total lo captura mejor a -110.
        ML_MAX_JUICE = -150

        def _ml_valid(c):
            """ML pick es válido SOLO si:
            1. El modelo proyecta que ese equipo gana (wp ≥ 50%).
            2. Edge ≥ MIN_EDGE_ML.
            3. Odds no peores que -150 (aplica siempre, playoffs incluidos).
            4. En playoffs: si el mercado tiene al equipo como gran underdog (spread ≥7)
               pero el modelo lo ve ganando, es blind spot de contexto de serie → suprimir."""
            if c["type"] != "ML":
                return True
            team = c.get("team_abb")
            if team == away:
                team_wp = model['wp_a']
            else:
                team_wp = model['wp_h']
            if team_wp < 50.0:
                return False
            if _edge_float_nba(c) < MIN_EDGE_ML:
                return False
            if c.get("odds", 0) < ML_MAX_JUICE:
                return False
            # Filtro playoff: modelo dice que el underdog masivo del mercado gana
            # → probablemente el modelo ignora el score de la serie
            if _playoffs and mkt_spread_line is not None and mkt_spread_line >= PLAYOFF_BLIND_SPOT_THRESHOLD:
                # ¿Este equipo es el underdog del mercado?
                team_is_mkt_dog = (mkt_fav_is_away and team == home) or \
                                  (not mkt_fav_is_away and team == away)
                if team_is_mkt_dog:
                    return False   # edge artificial — mercado sabe del score de la serie
            return True

        # Umbral: si mercado spread >= esto en playoffs Y modelo no concuerda en favorito
        # → suprimir pick (mercado tiene contexto de serie que el modelo no tiene)
        PLAYOFF_BLIND_SPOT_THRESHOLD = 7.0

        def _spread_valid(c):
            """Spread pick válido solo si hay edge real de al menos MIN_SPREAD_EDGE pts.
            En playoffs: si el mercado tiene al favorito con ≥7 pts de ventaja pero
            el modelo dice lo contrario, es un blind spot de contexto de serie → suprimir."""
            if c["type"] != "SPREAD":
                return True
            if _edge_float_nba(c) < MIN_SPREAD_EDGE:
                return False
            # Filtro playoff: modelo contradice al mercado en favorito + spread grande
            if _playoffs and not c.get("_mkt_agrees", True):
                mkt_sp = c.get("_mkt_spread", 0)
                if mkt_sp >= PLAYOFF_BLIND_SPOT_THRESHOLD:
                    return False   # edge artificial — mercado sabe del score de la serie
            return True

        def _total_valid(c):
            """En playoffs, OVER requiere barra muy alta. UNDER sigue siendo viable."""
            if c["type"] not in ("OVER", "UNDER"):
                return True
            edge = _edge_float_nba(c)
            if not _playoffs:
                return True  # regular season usa MIN_DIFF_OVR en la capa de preferencia
            if c["type"] == "OVER":
                _po_round = _get_playoff_round()
                _ovr_bar  = MIN_DIFF_OVR_R2 if _po_round >= 2 else MIN_DIFF_OVR_PLAYOFF
                return edge >= _ovr_bar
            else:  # UNDER
                return edge >= MIN_DIFF_UND_PLAYOFF

        candidates.sort(key=lambda x: -x["_ev"])
        strong = [
            c for c in candidates
            if c["_ev"] >= MIN_EV
            and _ml_valid(c)
            and _spread_valid(c)
            and _total_valid(c)
        ]

        # ── Near-miss: picks que casi clasificaron (para que el usuario decida) ──
        # Un near-miss es cualquier candidato que:
        #  - Tiene EV ≥ 2% (tiene algo de valor)
        #  - No está ya en strong (no clasificó por los filtros)
        #  - En playoffs: spread edge entre 0.5 y MIN_SPREAD_EDGE, o total edge cercano
        _near_misses_game = []
        _po_round = _get_playoff_round() if _playoffs else 1  # needed for near-miss OVER threshold
        if _playoffs:
            for c in candidates:
                if c in strong:
                    continue
                if c["_ev"] < 0.02:
                    continue
                edge_v = _edge_float_nba(c)
                is_near = False
                if c["type"] == "SPREAD" and 0.5 <= edge_v < MIN_SPREAD_EDGE:
                    is_near = True
                elif c["type"] == "OVER" and 1.5 <= edge_v < (MIN_DIFF_OVR_R2 if _po_round >= 2 else MIN_DIFF_OVR_PLAYOFF):
                    is_near = True
                elif c["type"] == "UNDER" and 2.0 <= edge_v < MIN_DIFF_UND_PLAYOFF:
                    is_near = True
                if is_near:
                    c["_near_miss"] = True
                    _near_misses_game.append(c)

        if not strong:
            # Si no hay picks fuertes pero hay near-misses, mostrar el mejor near-miss
            if _near_misses_game:
                best_nm = max(_near_misses_game, key=lambda x: x["_ev"])
                best_nm["_near_miss_only"] = True
                picks.append(best_nm)
            continue

        # ── Emitir TODOS los picks válidos del juego ──────────────────────────
        # Cada candidato que pasó los filtros es un pick independiente.
        # Esto permite que un mismo partido genere ML + UNDER, o SPREAD + UNDER,
        # cuando ambos tienen edge real — no enterrar uno como "alternativa".
        game_key = f"{away}_{home}"
        for c in strong:
            pick_type = c["type"]
            if pick_type == "ML":
                mkt_side = "HOME" if c["team_abb"] == home else "AWAY"
                mkt_bet  = "ml"
            elif pick_type == "SPREAD":
                mkt_side = "HOME" if c["team_abb"] == home else "AWAY"
                mkt_bet  = "spread"
            elif pick_type == "OVER":
                mkt_side = "OVER"
                mkt_bet  = "over"
            else:  # UNDER
                mkt_side = "UNDER"
                mkt_bet  = "under"

            mkt_conf = _sharp_confirm(market_signals, game_key, mkt_bet, mkt_side)
            c["market_signal"] = mkt_conf
            c["market_label"]  = _format_market_signal(mkt_conf)

            # En playoffs con señal FADE activa (≥2 señales) → omitir este pick
            if _playoffs and mkt_conf.get("fade") and mkt_conf.get("strength", 0) >= 2:
                continue

            # ── Detectar conflicto modelo vs mercado ──────────────────────────
            # Cuando modelo y mercado apuntan en lados OPUESTOS en el favorito,
            # el mercado probablemente sabe algo (lesiones, score de serie, forma
            # reciente) que el modelo no tiene todavía. Flag visible para el usuario.
            _conflict = False
            _conflict_disc = 0.0
            if pick_type in ("ML", "SPREAD"):
                team_is_mkt_dog_c = (mkt_fav_is_away and c["team_abb"] == home) or \
                                    (not mkt_fav_is_away and c["team_abb"] == away)
                if team_is_mkt_dog_c:
                    _conflict_disc = (mkt_spread_line or 0) + model_spread_abs
                    _conflict = _conflict_disc >= 6.0  # discrepancia total ≥6 pts = conflicto real
            c["_market_conflict"]      = _conflict
            c["_market_conflict_disc"] = round(_conflict_disc, 1)

            c["alt_picks"]     = []   # ya no hay "alternativas" — todos son principales
            c["model"]         = model
            c["away_abb"]      = away
            c["home_abb"]      = home
            c["game_time_utc"] = game.get("game_time_utc", "")
            picks.append(c)

    if _skipped_started:
        print(f"  ⏭️  {_skipped_started} juego(s) ya iniciado(s) — omitidos (odds en vivo no válidos)")

    picks.sort(key=lambda x: -x["_ev"])
    return picks


# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================

def show_stats(stats):
    """Display team stats table.

    Playoff mode (has_playoff_blend=True):
      - Solo muestra equipos que participaron/participan en playoffs (po_gp > 0)
      - Detecta equipos eliminados via SeriesStandings y los descarta de la tabla
      - Ordena por Net rating descendente (mejor equipo primero)
      - Columnas: Team | ORTG | DRTG | Net | PO-ORtg | PO-DRtg | PO-GP | PO-Wt

    Regular season:
      - Muestra los 30 equipos, orden alfabético
      - Columnas: Team | ORTG | DRTG | PACE | Net
    """
    if not tabulate:
        print("tabulate not installed. Install: pip install tabulate")
        return

    # Detectar si los stats son blended (tienen metadata de playoffs)
    has_playoff_blend = any(s.get("po_gp", 0) > 0 for s in stats.values())

    if has_playoff_blend:
        # ── MODO PLAYOFFS ──────────────────────────────────────────────────
        season_year = TARGET_DATE[:4]

        # 1. Filtrar solo equipos con datos de playoffs
        po_teams_all  = {t: s for t, s in stats.items() if s.get("po_gp", 0) > 0}

        # 2. Detectar equipos aún activos
        print("  🔎 Consultando bracket de playoffs …", end=" ", flush=True)
        active_teams = _get_active_playoff_teams(season_year)
        if active_teams:
            print(f"{len(active_teams)} equipos activos")
            # Solo equipos activos
            display_teams = {t: s for t, s in po_teams_all.items() if t in active_teams}
            eliminated    = {t: s for t, s in po_teams_all.items() if t not in active_teams}
        else:
            print("no se pudo determinar — mostrando todos")
            display_teams = po_teams_all
            eliminated    = {}

        # 3. Ordenar por Net rating descendente (mejor primero)
        sorted_teams = sorted(display_teams.items(),
                              key=lambda x: x[1].get("net", 0), reverse=True)

        rows = []
        for team, s in sorted_teams:
            po_gp = s.get("po_gp", 0)
            po_w  = s.get("po_weight", 0.0)
            rows.append([
                team,
                f"{s.get('ortg', 0):.1f}",
                f"{s.get('drtg', 0):.1f}",
                f"{s.get('net', 0):+.1f}",
                f"{s.get('po_ortg', 0):.1f}",
                f"{s.get('po_drtg', 0):.1f}",
                f"{po_gp}G",
                f"{po_w:.0f}%",
            ])

        n_active = len(display_teams)
        n_elim   = len(eliminated)
        elim_str = f"  ❌ Eliminados: {', '.join(sorted(eliminated))}" if eliminated else ""

        print("\n" + "═"*72)
        print(f"  🏆 NBA PLAYOFFS {season_year}  —  {n_active} equipos activos"
              + (f"  ({n_elim} eliminados)" if n_elim else ""))
        print(f"  ORTG/DRTG/Net = blended (temporada reg + PO). PO-ORtg/DRtg = playoffs puros.")
        print("═"*72)
        if rows:
            print(tabulate(rows,
                           headers=['Team', 'ORTG', 'DRTG', 'Net',
                                     'PO-ORtg', 'PO-DRtg', 'PO-GP', 'PO-Wt%'],
                           tablefmt='simple'))
        else:
            print("  (sin datos de playoffs disponibles)")
        if elim_str:
            print(elim_str)
        print()

    else:
        # ── MODO REGULAR SEASON ────────────────────────────────────────────
        rows = []
        for team in sorted(stats.keys()):
            s = stats[team]
            rows.append([
                team,
                f"{s.get('ortg', 0):.1f}",
                f"{s.get('drtg', 0):.1f}",
                f"{s.get('pace', 0):.1f}",
                f"{s.get('net', 0):+.1f}",
            ])

        print("\n" + "═"*60)
        print("NBA TEAM STATS  (Temporada Regular)")
        print("═"*60)
        print(tabulate(rows, headers=['Team', 'ORTG', 'DRTG', 'PACE', 'Net'],
                       tablefmt='simple'))
        print()

def _game_time_str(game):
    """Extract readable time string from game dict."""
    raw = game.get('game_time_utc') or game.get('time') or ''
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return dt.strftime('%I:%M %p ET')
    except Exception:
        return raw or 'TBD'


def _write_lines_json(games, stats, date_str, injury_impact=None):
    """
    Escribe nba_model_lines.json con las proyecciones de TODOS los juegos del día.
    Formato: { "YYYY-MM-DD": [ { game, away_abb, home_abb, model: {...} }, ... ] }
    Permite que serve.py muestre líneas de todos los juegos (no solo edge picks).
    """
    if injury_impact is None:
        injury_impact = {}
    entries = []
    for g in games:
        away = g['away_abb']
        home = g['home_abb']
        mdl = compute_game(away, home, stats, injury_impact=injury_impact)
        entries.append({
            "game":     f"{TEAM_NICKNAMES.get(away, away)} @ {TEAM_NICKNAMES.get(home, home)}".upper(),
            "away_abb": away,
            "home_abb": home,
            "model":    mdl,
        })
    out_path = os.path.join(os.path.dirname(__file__), "nba_model_lines.json")
    try:
        existing = {}
        if os.path.exists(out_path):
            with open(out_path) as f:
                existing = json.load(f)
    except Exception:
        existing = {}
    existing[date_str] = entries
    # Conserva solo los últimos 14 días
    cutoff = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    existing = {k: v for k, v in existing.items() if k >= cutoff}
    with open(out_path, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    return out_path


def display_lines(games, odds, stats, injury_impact=None):
    """Display model lines for each game (terminal format)."""
    if injury_impact is None:
        injury_impact = {}
    from datetime import datetime as _dt
    dt = _dt.strptime(TARGET_DATE, "%Y-%m-%d")
    print(f"\n{'═'*70}")
    print(f"  LABOY PICKS — NBA   {dt.strftime('%A, %B %d %Y').upper()}")
    print(f"{'═'*70}")

    for game in games:
        away = game['away_abb']
        home = game['home_abb']
        model = compute_game(away, home, stats, injury_impact=injury_impact)
        time_str = _game_time_str(game)

        print(f"\n  {'─'*66}")
        print(f"  {away:<6} @ {home}   ·  {time_str}")
        print(f"  {'─'*66}")
        # Spread: mostrar como "FAV -X.X / DOG +X.X" (convención estándar)
        m_sp = model['spread']
        if abs(m_sp) >= 0.5:
            sp_fav = home if m_sp >= 0 else away
            sp_dog = away if m_sp >= 0 else home
            spread_str = f"{sp_fav} -{abs(m_sp):.1f} / {sp_dog} +{abs(m_sp):.1f}"
        else:
            spread_str = "PICK"
        print(f"  🎯 MODELO  │  {away}: {model['pts_a']} pts  │  {home}: {model['pts_h']} pts")
        print(f"             │  Total: {model['total']}   Spread: {spread_str}")
        print(f"             │  Win%: {away} {model['wp_a']}%  /  {home} {model['wp_h']}%")
        print(f"             │  ML: {away} {model['ml_a']:+d}  /  {home} {model['ml_h']:+d}")
        if model.get("series_note"):
            print(f"             │  📊 {model['series_note']}")

    print(f"\n{'═'*70}\n")


def show_picks(games, odds, stats, threshold=0.0, injury_impact=None):
    """Show EV+ picks — usa odds del mercado si disponibles, si no modelo solo."""
    if injury_impact is None:
        injury_impact = {}
    # Fetch market signals — silencioso si no hay datos disponibles
    try:
        mkt_sigs = _fetch_market_signals(sport="nba")
        if mkt_sigs:
            print(f"  📡 Market signals: {len(mkt_sigs)} juegos")
    except Exception:
        mkt_sigs = {}
    picks = _compute_nba_picks_model(
        games, stats, market_odds=odds,
        injury_impact=injury_impact, market_signals=mkt_sigs
    )

    print(f"\n{'═'*70}")
    print(f"  LABOY PICKS — NBA EV+   {TARGET_DATE}")
    has_live = any(odds.values())
    src = "MERCADO + MODELO" if has_live else "MODELO SOLO (sin odds en vivo)"
    print(f"  Fuente: {src}")
    print(f"{'═'*70}\n")

    strong_picks = [p for p in picks if not p.get('_near_miss_only')]
    near_picks   = [p for p in picks if p.get('_near_miss_only')]

    if not strong_picks and not near_picks:
        print("  Sin picks EV+ para hoy.\n")
        return []

    def _fmt_pick_row(p):
        nm_tag = "  📍 WATCH" if p.get('_near_miss_only') else ""
        return [
            p['game'],
            p['pick'] + nm_tag,
            f"{p['odds']:+d}",
            p.get('modelo', '—'),
            p.get('mercado', '—'),
            p.get('edge', '—'),
            p.get('ev', '—'),
            p.get('market_label', '—'),
        ]

    if tabulate:
        rows = [_fmt_pick_row(p) for p in strong_picks]
        if rows:
            print(tabulate(rows,
                  headers=['Juego', 'Pick', 'Odds', 'Modelo', 'Mercado', 'Edge', 'EV', 'Sharp Signal'],
                  tablefmt='grid'))
        if near_picks:
            print("\n  📍 WATCH — cerca del umbral, no clasificó pero tiene valor:")
            nm_rows = [_fmt_pick_row(p) for p in near_picks]
            print(tabulate(nm_rows,
                  headers=['Juego', 'Pick', 'Odds', 'Modelo', 'Mercado', 'Edge', 'EV', 'Sharp Signal'],
                  tablefmt='simple'))
    else:
        for p in strong_picks:
            mkt = p.get('market_label', '')
            print(f"  {p['game']} → {p['pick']} ({p['odds']:+d})  "
                  f"Modelo:{p.get('modelo','—')}  EV:{p.get('ev','—')}  {mkt}")
        if near_picks:
            print("\n  📍 WATCH — cerca del umbral:")
            for p in near_picks:
                print(f"  {p['game']} → {p['pick']} ({p['odds']:+d})  "
                      f"Modelo:{p.get('modelo','—')}  Edge:{p.get('edge','—')}  EV:{p.get('ev','—')}")
    print()
    return picks

# ============================================================================
# HTML EXPORT — mismo diseño que mlb.py / bsn.py
# ============================================================================

def logo_url(team_abb):
    """Get ESPN logo URL for NBA team."""
    esp = ESPN_ABB.get(team_abb, team_abb.lower())
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{esp}.png"


def _nba_logo_b64():
    """
    Carga laboy_logo.png desde SCRIPT_DIR (NBA folder).
    Si no existe aquí busca en ../MLB/ (logo compartido).
    Retorna data-URI base64 o None.
    """
    for candidate in [
        os.path.join(SCRIPT_DIR, "laboy_logo.png"),
        os.path.join(SCRIPT_DIR, "..", "MLB", "laboy_logo.png"),
    ]:
        if os.path.exists(candidate):
            try:
                from PIL import Image
                import io, base64
                img = Image.open(candidate).convert("RGBA")
                data = img.load()
                w, h = img.size
                for y in range(h):
                    for x in range(w):
                        r, g, b, a = data[x, y]
                        if r < 35 and g < 35 and b < 35:
                            data[x, y] = (0, 0, 0, 0)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                return f"data:image/png;base64,{b64}"
            except Exception:
                try:
                    import base64
                    with open(candidate, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    return f"data:image/png;base64,{b64}"
                except Exception:
                    pass
    return None


def _nba_html_css():
    return """
  :root{--bg:#050508;--card:#0d0d10;--accent:#f07820;--green:#22c55e;--red:#ef4444;
        --text:#e8eef4;--muted:#4a6272;--border:#151520;--cyan:#00dcff;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);
    background-image:linear-gradient(rgba(0,220,255,.018) 1px,transparent 1px),
                     linear-gradient(90deg,rgba(0,220,255,.018) 1px,transparent 1px);
    background-size:32px 32px;
    color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:0 0 40px}
  .section{max-width:700px;margin:0 auto;padding:32px 16px 0}
  .section-title{font-size:0.75rem;font-weight:800;letter-spacing:3px;text-transform:uppercase;
    background:linear-gradient(90deg,#00dcff,#7a8fa0);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin:28px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--border)}
  .pick-card{background:linear-gradient(160deg,#0d0d10 0%,#0a0a0d 100%);border-radius:14px;
    padding:18px;margin-bottom:14px;border-left:4px solid var(--accent);
    border-top:1px solid rgba(0,220,255,.08);
    box-shadow:0 0 0 1px rgba(0,220,255,.04),0 4px 32px rgba(0,0,0,.8),
               inset 0 1px 0 rgba(255,255,255,.03)}
  .pick-time{font-size:0.7rem;color:var(--muted);margin-bottom:8px;font-family:monospace}
  .teams-row{display:flex;align-items:center;gap:12px;margin-bottom:14px}
  .teams-row img{width:52px;height:52px;object-fit:contain}
  .game-label{font-size:0.8rem;color:var(--muted);margin-bottom:4px}
  .pick-label{font-size:1.3rem;font-weight:800}
  @keyframes nba-odds-glow{0%,100%{box-shadow:0 0 4px rgba(240,120,32,.3)}50%{box-shadow:0 0 10px rgba(240,120,32,.6)}}
  .odds-badge{background:#f0782022;color:var(--accent);border-radius:6px;padding:2px 8px;font-size:1rem;
    animation:nba-odds-glow 2.5s ease-in-out infinite}
  .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
  .stat{background:rgba(0,220,255,.025);border:1px solid rgba(0,220,255,.08);
    border-radius:8px;padding:8px;text-align:center}
  .stat-label{font-size:0.6rem;text-transform:uppercase;letter-spacing:1px;color:#4a6272;margin-bottom:3px}
  .stat-val{font-size:0.88rem;font-weight:700;
    font-family:'JetBrains Mono','SF Mono','Fira Code','Courier New',monospace;letter-spacing:-.5px}
  .no-picks{color:var(--muted);text-align:center;padding:24px}
  .po-notes{margin-top:10px;padding:7px 10px;background:rgba(0,220,255,.03);
    border:1px solid rgba(0,220,255,.06);border-radius:8px;
    font-size:0.68rem;color:#7a8fa0;letter-spacing:0.5px;line-height:1.6}
  .po-note{color:#c8a84b}
  .line-card{background:linear-gradient(160deg,#0d0d10 0%,#0a0a0d 100%);border-radius:12px;
    padding:14px 16px;margin-bottom:10px;
    border:1px solid rgba(0,220,255,.07);
    box-shadow:0 0 0 1px rgba(0,220,255,.03),0 4px 24px rgba(0,0,0,.7)}
  .line-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
  .team-logo{display:flex;align-items:center;gap:6px;font-size:0.8rem;font-weight:700}
  .team-logo img{width:36px;height:36px;object-fit:contain}
  .line-time{font-size:0.75rem;color:var(--muted);font-family:monospace}
  .line-stats{display:flex;gap:12px;flex-wrap:wrap;font-size:0.8rem;margin-bottom:4px}
  .footer{text-align:center;padding:32px 16px 0;color:#1a2530;font-size:0.8rem;
    border-top:1px solid rgba(0,220,255,.06);margin-top:20px;padding-top:16px}
  .footer a{color:rgba(0,220,255,.35);text-decoration:none}
  ::-webkit-scrollbar{width:5px}
  ::-webkit-scrollbar-track{background:#050508}
  ::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#00dcff40,#f0782040);border-radius:3px}"""


def _nba_html_wrap(title, header_sub, dstr, yr, body_html):
    """Envuelve body_html en shell HTML completo — AI style (NBA)."""
    logo_src = _nba_logo_b64()
    logo_html = (f'<img class="dbg-logo" src="{logo_src}" alt="Laboy Picks">'
                 if logo_src else '<span class="dbg-wordmark">LABOY</span>')
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>{_nba_html_css()}
  /* ── AI Header ── */
  .dbg-header{{background:linear-gradient(180deg,#000 0%,#06060a 100%);
    padding:22px 24px 18px;text-align:center;border-bottom:1px solid rgba(0,220,255,.13);
    position:relative;overflow:hidden}}
  @keyframes nba-scan{{0%{{transform:translateY(-120%)}}100%{{transform:translateY(1200%)}}}}
  .dbg-header::before{{content:'';position:absolute;top:0;left:0;right:0;height:60px;
    background:linear-gradient(180deg,transparent,rgba(0,220,255,.09),transparent);
    animation:nba-scan 4s linear infinite;pointer-events:none}}
  .dbg-header::after{{content:'';position:absolute;bottom:-1px;left:10%;right:10%;height:1px;
    background:linear-gradient(90deg,transparent,rgba(0,220,255,.5),rgba(240,120,32,.5),transparent)}}
  .dbg-logo{{height:80px;width:auto;display:block;margin:0 auto 10px;
    filter:drop-shadow(0 0 12px rgba(240,120,32,.45))}}
  .dbg-wordmark{{font-size:2rem;font-weight:900;letter-spacing:6px;
    background:linear-gradient(90deg,#f07820,#00dcff);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    display:block;margin-bottom:8px}}
  @keyframes nba-gradient{{0%{{background-position:0% center}}100%{{background-position:200% center}}}}
  .dbg-title{{font-size:0.6rem;font-weight:800;letter-spacing:4px;text-transform:uppercase;
    margin-bottom:4px;background:linear-gradient(90deg,#00dcff,#7c3aed,#00dcff);
    background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;
    animation:nba-gradient 4s linear infinite}}
  .dbg-date{{color:#475569;font-size:0.65rem;letter-spacing:2.5px;text-transform:uppercase;margin-top:2px}}
  @keyframes nba-pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.4;transform:scale(.7)}}}}
  .dbg-badge{{display:inline-flex;align-items:center;gap:5px;
    background:rgba(0,220,255,.07);border:1px solid rgba(0,220,255,.2);
    border-radius:20px;padding:2px 10px;margin-top:8px;
    font-size:0.58rem;font-weight:700;letter-spacing:2px;color:rgba(0,220,255,.6);
    text-transform:uppercase}}
  .dbg-badge-dot{{width:5px;height:5px;border-radius:50%;background:#00dcff;
    box-shadow:0 0 6px #00dcff;animation:nba-pulse 1.8s ease-in-out infinite}}
  .fa-icon{{font-size:0.85em;opacity:0.75;margin-right:4px}}
  .section-title .fa-icon{{font-size:0.9em;opacity:1;margin-right:6px}}
</style>
</head>
<body>
<div class="dbg-header">
  {logo_html}
  <div class="dbg-title">&#9632;&nbsp;Model Report&nbsp;&#9632;</div>
  <div class="dbg-date">NBA &nbsp;·&nbsp; {dstr}</div>
  <div><span class="dbg-badge"><span class="dbg-badge-dot"></span>AI Analysis Engine · Active</span></div>
</div>
<div class="section">
{body_html}
</div>
<div class="footer">
  <p>Data Model by <a href="https://instagram.com/laboypicks">Laboy Picks</a> &nbsp;·&nbsp; {yr}</p>
</div>
</body>
</html>"""


def _to_pr_time(utc_str):
    """Convierte timestamp UTC a hora de Puerto Rico (AST = UTC-4, sin DST).
    Acepta: '2026-04-15T01:10:00Z', '2026-04-15T01:10:00+00:00', o '7:05 PM ET' (pass-through).
    """
    if not utc_str:
        return ""
    # Si ya viene como '7:05 PM ...' lo devolvemos tal cual
    if re.match(r'^\d+:\d+\s*(AM|PM)', utc_str.strip(), re.IGNORECASE):
        return utc_str
    try:
        from datetime import timezone, timedelta
        PR_OFFSET = timedelta(hours=-4)
        # Normalizar formato
        s = utc_str.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(s)
        dt_pr  = dt_utc + PR_OFFSET
        return dt_pr.strftime("%-I:%M %p AST")   # "7:10 PM AST" (Puerto Rico Time)
    except Exception:
        return utc_str


def _parse_time_sort_nba(t):
    """Convierte '7:05 PM PT' a int para ordenar cronológicamente."""
    if not t: return 9999
    try:
        parts = t.split()
        h, m  = map(int, parts[0].split(':'))
        ap    = parts[1].upper() if len(parts) > 1 else 'PM'
        if ap == 'PM' and h != 12: h += 12
        if ap == 'AM' and h == 12: h  = 0
        return h * 100 + m
    except Exception:
        return 9999


def _nba_over_under_logo(size=52):
    """Retorna <img> tag en base64 de over_under.png (de SCRIPT_DIR) o '' si no existe."""
    for p in [os.path.join(SCRIPT_DIR, "over_under.png"),
              os.path.join(SCRIPT_DIR, "..", "MLB", "over_under.png"),
              os.path.join(SCRIPT_DIR, "..", "BSN", "over_under.png")]:
        if os.path.exists(p):
            try:
                import base64 as _b64
                with open(p, "rb") as f:
                    d = _b64.b64encode(f.read()).decode()
                return (f'<img src="data:image/png;base64,{d}" alt="O/U" '
                        f'width="{size}" height="{size}" style="object-fit:contain">')
            except Exception:
                pass
    return ""


def _html_wrap(title, content, accent_color="#F7A826"):
    """Legacy wrapper — redirect to new _nba_html_wrap."""
    return _nba_html_wrap(title, "NBA", title, "2026", content)




def export_picks_html(games, odds, stats, date_str, injury_impact=None):
    """Genera 'Laboy NBA Picks YYYY-MM-DD.html' — mismo diseño que mlb.py / bsn.py."""
    if injury_impact is None:
        injury_impact = {}
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    dt   = datetime.strptime(date_str, "%Y-%m-%d")
    dstr = dt.strftime("%A, %B %d · %Y").upper()
    yr   = dt.strftime("%Y")

    # Intentar obtener market signals
    mkt_sigs = {}
    try:
        mkt_sigs = _fetch_market_signals(sport="nba")
    except Exception:
        pass

    picks = _compute_nba_picks_model(
        games, stats, market_odds=odds,
        injury_impact=injury_impact, market_signals=mkt_sigs
    )
    # Ordenar por hora AST cronológicamente
    picks.sort(key=lambda p: _parse_time_sort_nba(_to_pr_time(p.get('game_time_utc', ''))))

    # ── Helper: stat badge (igual que MLB) ──────────────────────────────────
    def _stat_badge(label, value, color="#f1f5f9"):
        return (f'<div style="background:rgba(0,0,0,0.4);border:1px solid rgba(0,220,255,0.1);'
                f'border-radius:8px;padding:6px 10px;min-width:52px;text-align:center">'
                f'<div style="font-size:0.55rem;font-weight:800;letter-spacing:0.1em;'
                f'color:rgba(0,220,255,0.5);margin-bottom:3px;text-transform:uppercase">{label}</div>'
                f'<div style="font-size:0.85rem;font-weight:800;color:{color}">{value}</div>'
                f'</div>')

    # ── Helper: game header row (logo | time + matchup | logo | badge) ──────
    def _game_header(away_abb, home_abb, game_time_utc, badge_label, badge_color="#f07820"):
        away_url = logo_url(away_abb)
        home_url = logo_url(home_abb)
        time_str = esc(_to_pr_time(game_time_utc)) if game_time_utc else "—"
        return f"""<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:12px;flex-wrap:wrap">
          <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0">
            <img src="{away_url}" alt="{esc(away_abb)}" width="38" height="38" style="object-fit:contain;flex-shrink:0" onerror="this.style.display='none'">
            <div style="min-width:0;flex:1">
              <div class="pick-time">{time_str}</div>
              <div style="font-size:0.88rem;font-weight:700;color:#f1f5f9;white-space:normal;line-height:1.3">{esc(TEAM_NICKNAMES.get(away_abb, away_abb))} @ {esc(TEAM_NICKNAMES.get(home_abb, home_abb))}</div>
            </div>
            <img src="{home_url}" alt="{esc(home_abb)}" width="38" height="38" style="object-fit:contain;flex-shrink:0" onerror="this.style.display='none'">
          </div>
          <span style="background:{badge_color}18;color:{badge_color};border-radius:6px;padding:3px 10px;font-size:0.72rem;font-weight:700;letter-spacing:0.05em;white-space:nowrap;flex-shrink:0;align-self:flex-start">{esc(badge_label)}</span>
        </div>"""

    if not picks:
        body = '<div class="no-picks">No hay picks con valor claro hoy — mercado bien alineado con el modelo.</div>'
    else:
        body = '<div class="section-title"><i class="fa-solid fa-bullseye fa-icon"></i>Picks EV+ del Modelo</div>\n'
        # Group picks by game so each card shows one game (multiple picks get stacked inside)
        from collections import OrderedDict
        games_order = OrderedDict()
        for p in picks:
            key = (p.get("away_abb",""), p.get("home_abb",""))
            if key not in games_order:
                games_order[key] = []
            games_order[key].append(p)

        for (away_abb, home_abb), game_picks in games_order.items():
            # Card border color = team color of first pick's team
            first = game_picks[0]
            pick_type_first = first.get('type','ML')
            if pick_type_first in ('OVER','UNDER'):
                card_color = "#f97316" if pick_type_first == "OVER" else "#a78bfa"
            else:
                team_abb = first.get('team_abb') or away_abb
                card_color = TEAM_COLORS.get(team_abb, "#4f8ef7")

            # Badge: type label(s)
            type_labels = list(dict.fromkeys(p.get('type','ML') for p in game_picks))
            badge_label = " · ".join(type_labels)

            # Playoff notes from first pick
            _mdl_first   = first.get('model', {}) or {}
            _notes_raw   = [_mdl_first.get('series_note'), _mdl_first.get('rest_note'),
                            _mdl_first.get('fatigue_note'), _mdl_first.get('r2_note')]
            _notes       = [n for n in _notes_raw if n]
            notes_html   = ""
            if _notes:
                notes_html = ('<div class="po-notes" style="margin-top:12px">'
                              + " &nbsp;|&nbsp; ".join(f'<span class="po-note">{esc(n)}</span>' for n in _notes)
                              + "</div>")

            body += f'\n<div class="pick-card" style="border-left:4px solid {card_color}">'
            body += _game_header(away_abb, home_abb, first.get('game_time_utc',''), badge_label, card_color)

            # One sub-row per pick in this game
            for p in game_picks:
                pick_type = p.get('type','ML')
                ev_s      = str(p.get('ev','—'))
                edge_s    = str(p.get('edge','—'))
                modelo_s  = str(p.get('modelo','—'))
                ev_col    = "#22c55e" if not ev_s.startswith('-') else "#ef4444"
                edge_col  = "#22c55e" if not edge_s.startswith('-') else "#ef4444"
                odds_s    = f"{p['odds']:+d}" if p.get('odds') is not None else "—"

                body += f"""
              <div style="background:linear-gradient(135deg,#0c0c14 0%,#080810 100%);
                          border-left:3px solid {card_color};border-radius:10px;
                          padding:12px 15px;margin-bottom:8px;
                          border:1px solid rgba(0,220,255,0.08);
                          box-shadow:0 2px 12px rgba(0,0,0,0.7) inset,0 0 0 1px rgba(0,220,255,0.03)">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
                  <div style="flex:1;min-width:0">
                    <div style="font-size:0.58rem;color:rgba(0,220,255,0.5);letter-spacing:0.14em;
                                font-weight:800;margin-bottom:4px;text-transform:uppercase">{esc(pick_type)}</div>
                    <div style="font-size:1.18rem;font-weight:900;color:#f1f5f9;
                                display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                      <span>{esc(_fmt_pick(p['pick']))}</span>
                      <span style="font-size:0.9rem;font-weight:800;
                                   background:rgba(0,220,255,0.08);border:1px solid rgba(0,220,255,0.2);
                                   color:#00dcff;border-radius:6px;padding:1px 9px;
                                   text-shadow:0 0 10px rgba(0,220,255,0.5)">{esc(odds_s)}</span>
                    </div>
                  </div>
                  <div style="display:flex;gap:8px;flex-shrink:0">
                    {_stat_badge("EDGE", esc(edge_s), edge_col)}
                    {_stat_badge("EV", esc(ev_s), ev_col)}
                    {_stat_badge("MODELO", esc(modelo_s))}
                  </div>
                </div>
              </div>"""

            body += '\n</div>'

    # ── Otros juegos sin pick — leer desde nba_model_lines.json ──────────────
    _lines_path = os.path.join(SCRIPT_DIR, "nba_model_lines.json")
    try:
        with open(_lines_path) as _lf:
            _lines_data = json.load(_lf)
        _lines_today = _lines_data.get(date_str, [])
        _picked_pairs = {(p.get("away_abb",""), p.get("home_abb","")) for p in picks}
        _no_pick_games = [
            g for g in _lines_today
            if (g.get("away_abb",""), g.get("home_abb","")) not in _picked_pairs
            and g.get("model")
        ]
        # Deduplicate by away+home pair
        _seen_np = set()
        _no_pick_deduped = []
        for _g in _no_pick_games:
            _k = (_g.get("away_abb",""), _g.get("home_abb",""))
            if _k not in _seen_np:
                _seen_np.add(_k)
                _no_pick_deduped.append(_g)
        _no_pick_games = _no_pick_deduped
    except Exception:
        _no_pick_games = []

    if _no_pick_games:
        body += '\n<div style="margin-top:24px;border-top:1px solid rgba(0,220,255,.08);padding-top:16px">'
        body += (
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">'
            '<div style="flex:1;height:1px;background:linear-gradient(90deg,rgba(79,142,247,.3),transparent)"></div>'
            '<span style="font-size:.46rem;font-weight:900;letter-spacing:.22em;text-transform:uppercase;color:#475569;white-space:nowrap">OTROS JUEGOS · NO PICK</span>'
            '<div style="flex:1;height:1px;background:linear-gradient(270deg,rgba(79,142,247,.3),transparent)"></div>'
            '</div>'
        )
        for _g in _no_pick_games:
            _ga  = _g.get("away_abb","")
            _gh  = _g.get("home_abb","")
            _mdl = _g.get("model", {})
            _sp  = _mdl.get("spread", 0)
            _tot = _mdl.get("total", 0)
            _mla = _mdl.get("ml_a", 0)
            _mlh = _mdl.get("ml_h", 0)
            _wpa = _mdl.get("wp_a", 50)
            _wph = _mdl.get("wp_h", 50)
            _sn  = _mdl.get("series_note") or ""
            _gt  = _g.get("game_time_utc","")
            _fav_a    = _wpa >= _wph
            _fav_abb  = _ga if _fav_a else _gh
            _fav_wp   = max(_wpa, _wph)
            _fav_color = TEAM_COLORS.get(_fav_abb, "#4f8ef7")
            _sp_s  = f'{_sp:+.1f}'
            _tot_s = f'{_tot:.1f}'
            _mla_s = f'+{int(_mla)}' if _mla > 0 else str(int(_mla))
            _mlh_s = f'+{int(_mlh)}' if _mlh > 0 else str(int(_mlh))
            _a_col = '#22c55e' if _fav_a else '#64748b'
            _h_col = '#22c55e' if not _fav_a else '#64748b'
            _sn_html = ""  # series note hidden in dashboard view
            _away_url = logo_url(_ga)
            _home_url = logo_url(_gh)
            _time_str = esc(_to_pr_time(_gt)) if _gt else ""

            body += f"""
<div style="margin-bottom:8px;background:rgba(255,255,255,.02);
  border:1px solid rgba(255,255,255,.06);border-left:3px solid {_fav_color}40;
  border-radius:12px;overflow:hidden">
  <div style="display:flex;align-items:center;justify-content:space-between;padding:9px 14px 0">
    <div style="display:flex;align-items:center;gap:8px">
      <img src="{_away_url}" alt="{esc(_ga)}" width="28" height="28" style="object-fit:contain" onerror="this.style.display='none'">
      <div>
        {"<div style='font-size:.44rem;color:#334155;font-weight:700'>"+_time_str+"</div>" if _time_str else ""}
        <div style="font-size:.78rem;font-weight:800;color:#e2e8f0">{esc(TEAM_NICKNAMES.get(_ga,_ga))} @ {esc(TEAM_NICKNAMES.get(_gh,_gh))}</div>
      </div>
      <img src="{_home_url}" alt="{esc(_gh)}" width="28" height="28" style="object-fit:contain" onerror="this.style.display='none'">
    </div>
    <div style="display:flex;align-items:center;gap:6px">
      <span style="font-size:.68rem;font-weight:900;color:{_fav_color}">{_fav_wp:.0f}%</span>
      <span style="font-size:.42rem;color:#334155;font-weight:700">{esc(_fav_abb)}</span>
      <span style="font-size:.4rem;font-weight:900;letter-spacing:.06em;padding:2px 7px;
        background:rgba(30,41,59,.7);border:1px solid rgba(255,255,255,.07);
        border-radius:5px;color:#334155">NO PICK</span>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:4px;padding:5px 14px 7px">
    <span style="font-size:.5rem;font-weight:700;color:{_a_col};width:24px;text-align:right">{_wpa:.0f}%</span>
    <div style="flex:1;height:4px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden">
      <div style="height:100%;width:{_wpa:.1f}%;background:linear-gradient(90deg,#3b82f6,#6366f1);border-radius:2px"></div>
    </div>
    <span style="font-size:.5rem;font-weight:700;color:{_h_col};width:24px">{_wph:.0f}%</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;border-top:1px solid rgba(255,255,255,.05)">
    <div style="text-align:center;padding:7px 4px;border-right:1px solid rgba(255,255,255,.04)">
      <div style="font-size:.36rem;color:#334155;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:2px">Spread</div>
      <div style="font-size:.78rem;font-weight:900;color:#60a5fa">{esc(_sp_s)}</div>
    </div>
    <div style="text-align:center;padding:7px 4px;border-right:1px solid rgba(255,255,255,.04)">
      <div style="font-size:.36rem;color:#334155;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:2px">Total</div>
      <div style="font-size:.78rem;font-weight:900;color:#a78bfa">{esc(_tot_s)}</div>
    </div>
    <div style="text-align:center;padding:7px 4px;border-right:1px solid rgba(255,255,255,.04)">
      <div style="font-size:.36rem;color:#334155;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:2px">{esc(_ga)} ML</div>
      <div style="font-size:.78rem;font-weight:900;color:{_a_col}">{esc(_mla_s)}</div>
    </div>
    <div style="text-align:center;padding:7px 4px">
      <div style="font-size:.36rem;color:#334155;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:2px">{esc(_gh)} ML</div>
      <div style="font-size:.78rem;font-weight:900;color:{_h_col}">{esc(_mlh_s)}</div>
    </div>
  </div>
  {_sn_html}
</div>"""
        body += '</div>'

    # ── Injury Report section (dashboard fragment only) ─────────────────────
    try:
        import json as _json_ir
        with open(NBA_INJURIES_FILE) as _irf:
            _all_ir = _json_ir.load(_irf)
        _active_statuses = {"out", "doubtful", "questionable"}
        _ir_entries = [e for e in _all_ir if e.get("status","").lower() in _active_statuses]
        # Collect all teams playing today from picks + no-pick games
        _today_teams_ir = set()
        for _p in picks:
            if _p.get("away_abb"): _today_teams_ir.add(_p["away_abb"])
            if _p.get("home_abb"): _today_teams_ir.add(_p["home_abb"])
        try:
            with open(_lines_path) as _lf2:
                _ld2 = _json_ir.load(_lf2)
            for _gl2 in _ld2.get(date_str, []):
                if _gl2.get("away_abb"): _today_teams_ir.add(_gl2["away_abb"])
                if _gl2.get("home_abb"): _today_teams_ir.add(_gl2["home_abb"])
        except Exception:
            pass
        _ir_show = [e for e in _ir_entries if not _today_teams_ir or e.get("team_abb","") in _today_teams_ir]
        if not _ir_show:
            _ir_show = _ir_entries
        if _ir_show:
            _ir_rows = ""
            for _e in sorted(_ir_show, key=lambda x: (x.get("team_abb",""), -float(x.get("ppg",0) or 0))):
                _st = (_e.get("status") or "").lower()
                if _st == "out":
                    _sc, _sl = "#ef4444", "OUT"
                elif _st == "doubtful":
                    _sc, _sl = "#f97316", "DBT"
                else:
                    _sc, _sl = "#eab308", "QST"
                _abb      = _e.get("team_abb","")
                _pname    = _e.get("player","")
                _ppg      = _e.get("ppg","")
                _ppg_s    = f"{_ppg} PPG" if _ppg else ""
                _imp      = _e.get("impact","")
                _imp_s    = f" · {_imp} pts impact" if _imp else ""
                _tc       = TEAM_COLORS.get(_abb, "#4f8ef7")
                _logo_url = logo_url(_abb)
                _ir_rows += f"""<div style="display:flex;align-items:center;gap:10px;
  padding:8px 14px;
  background:linear-gradient(90deg,{_tc}18 0%,{_tc}06 60%,transparent 100%);
  border:1px solid {_tc}25;
  border-radius:11px;margin-bottom:5px">
  <img src="{_logo_url}" alt="{_abb}" width="28" height="28" style="object-fit:contain;flex-shrink:0" onerror="this.style.display='none'">
  <div style="flex:1;min-width:0">
    <div style="font-size:.72rem;font-weight:800;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{_pname}</div>
    <div style="font-size:.54rem;color:#475569;font-weight:600">{_ppg_s}{_imp_s}</div>
  </div>
  <span style="font-size:.58rem;font-weight:900;padding:2px 9px;
    background:{_sc}18;border-radius:6px;color:{_sc};
    border:1px solid {_sc}50">{_sl}</span>
</div>"""
            body += f"""
<div style="margin-top:22px;border-top:1px solid rgba(255,255,255,.06);padding-top:14px">
  <div style="font-size:.44rem;font-weight:900;letter-spacing:.2em;text-transform:uppercase;
    color:#334155;margin-bottom:10px">🏥 INJURY REPORT</div>
  {_ir_rows}
</div>"""
    except Exception:
        pass  # IR is non-critical

    # ── Guardar fragmento del body para el dashboard (siempre sobreescribe) ──
    # nba_picks_body_current.html: body + CSS mínimo, sin full-page wrap.
    # serve.py lo inyecta directamente en el panel del dashboard.
    _FRAG_CSS = """
<style>
/* ── NBA picks fragment — inyectado en el dashboard (igual que MLB) ── */
.nba-frag-wrap {
  font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  color: #f1f5f9;
}
.nba-frag-wrap .section-title {
  font-size: .62rem;
  font-weight: 900;
  letter-spacing: .15em;
  text-transform: uppercase;
  background: linear-gradient(90deg,#00dcff,#7c3aed,#00dcff);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: nba-frag-grad 5s linear infinite;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
@keyframes nba-frag-grad {
  0%   { background-position: 0% center }
  100% { background-position: 200% center }
}
.nba-frag-wrap .pick-card {
  background: linear-gradient(160deg,#0d0d12 0%,#090910 100%);
  border: 1px solid rgba(0,220,255,.13);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 20px;
  box-shadow: 0 0 0 1px rgba(0,220,255,.04),0 6px 40px rgba(0,0,0,.85),inset 0 1px 0 rgba(255,255,255,.04);
  position: relative;
  overflow: hidden;
}
.nba-frag-wrap .pick-card::before {
  content: '';
  position: absolute;
  top: 0; left: 10%; right: 10%;
  height: 1px;
  background: linear-gradient(90deg,transparent,rgba(0,220,255,.35),rgba(240,120,32,.25),transparent);
}
.nba-frag-wrap .pick-time {
  font-size: .65rem;
  color: rgba(0,220,255,.55);
  letter-spacing: .08em;
  font-weight: 700;
  margin-bottom: 2px;
  text-transform: uppercase;
}
.nba-frag-wrap .po-notes {
  padding: 7px 10px;
  background: rgba(0,220,255,.03);
  border: 1px solid rgba(0,220,255,.07);
  border-radius: 8px;
  font-size: .66rem;
  color: #64748b;
  line-height: 1.6;
}
.nba-frag-wrap .po-note { color: #c8a84b; }
.nba-frag-wrap .no-picks {
  color: #475569;
  text-align: center;
  padding: 24px 16px;
  font-size: .85rem;
}
</style>"""

    # Guardar fragmento → siempre sobreescribe (sin importar si el HTML completo está protegido)
    _frag_content = f'{_FRAG_CSS}<div class="nba-frag-wrap">{body}</div>'
    _frag_path = os.path.join(SCRIPT_DIR, "nba_picks_body_current.html")
    try:
        with open(_frag_path, "w", encoding="utf-8") as _ff:
            _ff.write(_frag_content)
    except Exception:
        pass  # non-critical

    html  = _nba_html_wrap(f"Laboy NBA Picks · {dstr}", "NBA", dstr, yr, body)
    fname = f"Laboy NBA Picks {date_str}.html"
    fpath = os.path.join(SCRIPT_DIR, fname)
    if os.path.exists(fpath) and not FORCE_EXPORT:
        print(f"  🔒 NBA Picks HTML ya existe para {date_str} — protegido de sobreescritura.")
        print(f"     → {fname}")
        print(f"     Usa --force-export para regenerar.")
        return fpath
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  🎯 NBA Picks HTML: {fname}")
    return fpath


def export_lines_html(games, odds, stats, date_str, injury_impact=None):
    """Genera 'Laboy NBA Lines YYYY-MM-DD.html' — mismo diseño que mlb.py / bsn.py."""
    if injury_impact is None:
        injury_impact = {}
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    dt   = datetime.strptime(date_str, "%Y-%m-%d")
    dstr = dt.strftime("%A, %B %d · %Y").upper()
    yr   = dt.strftime("%Y")

    # Ordenar por hora PR
    sorted_games = sorted(games, key=lambda g: _parse_time_sort_nba(
        _to_pr_time(g.get('game_time_utc', ''))))

    body = '<div class="section-title"><i class="fa-solid fa-chart-simple fa-icon"></i>Data Model Lines — Todos los Juegos</div>\n'

    for game in sorted_games:
        away  = game['away_abb']
        home  = game['home_abb']
        model = compute_game(away, home, stats, injury_impact=injury_impact)
        time_str = esc(_to_pr_time(game.get('game_time_utc', '')))

        fav_abb   = home if model['spread'] >= 0 else away
        fav_color = TEAM_COLORS.get(fav_abb, "#f07820")

        away_logo = (f'<img src="{logo_url(away)}" alt="{esc(away)}" '
                     f'width="36" height="36" style="object-fit:contain" '
                     f'onerror="this.style.display=\'none\'">')
        home_logo = (f'<img src="{logo_url(home)}" alt="{esc(home)}" '
                     f'width="36" height="36" style="object-fit:contain" '
                     f'onerror="this.style.display=\'none\'">')

        model_spread_str = (f"{fav_abb} -{abs(model['spread']):.1f}"
                            if abs(model['spread']) >= 0.5 else "PICK")

        # Pull market odds for this game (for comparison display)
        mkt = odds.get(f"{away}_{home}", {}) if odds else {}
        bks = mkt.get('bookmakers', [])
        m_spread, m_total, m_ml_a, m_ml_h = None, None, None, None
        m_spread_fav_name = ""   # nombre del equipo favorito según el mercado (spread)
        for bk in bks:
            for mo in bk.get('markets', []):
                if mo['key'] in ('h2h','moneyline') and m_ml_a is None:
                    for oc in mo.get('outcomes', []):
                        n = _full_name_to_abb(oc['name'])
                        if n == away: m_ml_a = oc['price']
                        elif n == home: m_ml_h = oc['price']
                elif mo['key'] == 'spreads' and m_spread is None:
                    for oc in mo.get('outcomes', []):
                        if oc.get('point') is not None and oc['point'] < 0:
                            m_spread = abs(oc['point'])
                            m_spread_fav_name = oc.get('name', '')  # nombre del equipo favorito en el mercado
                elif mo['key'] == 'totals' and m_total is None:
                    for oc in mo.get('outcomes', []):
                        if oc['name'].upper() == 'OVER':
                            m_total = oc.get('point')
            if all(x is not None for x in [m_ml_a, m_spread, m_total]):
                break

        # Build market comparison row
        mkt_parts = []
        if m_spread is not None:
            # Determinar favorito/underdog según el MERCADO (no el modelo)
            mkt_fav_abb = _full_name_to_abb(m_spread_fav_name) if m_spread_fav_name else None
            if mkt_fav_abb not in (away, home):
                # Fallback: si no se pudo resolver el nombre, usar el modelo
                mkt_fav_abb = fav_abb
            mkt_dog_abb = home if mkt_fav_abb == away else away
            spread_edge = m_spread - abs(model['spread'])
            edge_col = "#22c55e" if spread_edge >= 2.5 else "#94a3b8"
            mkt_parts.append(
                f'<span style="color:{edge_col}"><i class="fa-solid fa-arrows-left-right fa-icon"></i>'
                f'Mkt Spread: {esc(mkt_fav_abb)} -{m_spread:.1f} · {esc(mkt_dog_abb)} +{m_spread:.1f} '
                f'<b>(edge {spread_edge:+.1f})</b></span>'
            )
        if m_total is not None:
            total_edge = model['total'] - m_total
            edge_col = "#22c55e" if abs(total_edge) >= 3.0 else "#94a3b8"
            side = "OVER" if total_edge > 0 else "UNDER"
            mkt_parts.append(
                f'<span style="color:{edge_col}"><i class="fa-solid fa-basketball fa-icon"></i>'
                f'Mkt Total: {m_total:.1f} · {side} <b>(edge {total_edge:+.1f})</b></span>'
            )
        if m_ml_a is not None and m_ml_h is not None:
            def _fmt(o): return f"+{o}" if o > 0 else str(o)
            mkt_parts.append(
                f'<span><i class="fa-solid fa-coins fa-icon"></i>'
                f'Mkt ML: {esc(away)} {_fmt(m_ml_a)} / {esc(home)} {_fmt(m_ml_h)}</span>'
            )
        mkt_row = (
            f'<div class="line-stats" style="margin-top:4px;border-top:1px solid #1e1e1e;padding-top:6px">'
            + " ".join(mkt_parts) +
            f'</div>'
        ) if mkt_parts else ""

        body += f"""
        <div class="line-card" style="border-left:3px solid {fav_color}">
          <div class="line-header">
            <div class="team-logo">{away_logo}<span>{esc(away)}</span></div>
            <div class="line-time">{time_str if time_str else "—"}</div>
            <div class="team-logo">{home_logo}<span>{esc(home)}</span></div>
          </div>
          <div class="line-stats">
            <span style="color:#64748b;font-size:0.7rem;font-weight:700;letter-spacing:1px">MODELO</span>
            <span><i class="fa-solid fa-basketball fa-icon"></i>Total: {model['total']:.1f}</span>
            <span><i class="fa-solid fa-arrows-left-right fa-icon"></i>{esc(model_spread_str)}</span>
            <span><i class="fa-solid fa-percent fa-icon"></i>{esc(away)} {model['wp_a']}% / {esc(home)} {model['wp_h']}%</span>
          </div>
          <div class="line-stats" style="margin-top:2px">
            <span><i class="fa-solid fa-coins fa-icon"></i>ML: {esc(away)} {model['ml_a']:+d} / {esc(home)} {model['ml_h']:+d}</span>
            <span><i class="fa-solid fa-chart-line fa-icon"></i>Pts: {model['pts_a']} – {model['pts_h']}</span>
          </div>
          {mkt_row}
        </div>"""

    html  = _nba_html_wrap(f"Laboy NBA Lines · {dstr}", "NBA", dstr, yr, body)
    fname = f"Laboy NBA Lines {date_str}.html"
    fpath = os.path.join(SCRIPT_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📊 NBA Lines HTML: {fname}")
    return fpath

# ============================================================================
# PICK LOGGING & TRACKING
# ============================================================================

def _load_picks():
    """Load picks log. IDs are normalized to match 0-based array indices."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                picks = json.load(f)
            # Normalize IDs to 0-based array indices (one-time migration)
            changed = False
            for i, p in enumerate(picks):
                if p.get('id') != i:
                    p['id'] = i
                    changed = True
            if changed:
                with open(LOG_FILE, 'w') as f:
                    json.dump(picks, f, indent=2)
            return picks
        except Exception:
            return []
    return []

def _save_picks(picks):
    """Save picks log."""
    with open(LOG_FILE, 'w') as f:
        json.dump(picks, f, indent=2)

def _load_model_picks():
    """Load model picks history."""
    if os.path.exists(MODEL_PICKS_FILE):
        try:
            with open(MODEL_PICKS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def _save_model_picks(picks):
    """Save model picks history."""
    with open(MODEL_PICKS_FILE, 'w') as f:
        json.dump(picks, f, indent=2)

def _model_picks_save_today(picks, date_str=None):
    """Auto-save model picks for today."""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    model_picks = _load_model_picks()
    model_picks[date_str] = picks
    _save_model_picks(model_picks)

def _fmt_odds_nba(o):
    o = int(o)
    return f"+{o}" if o > 0 else str(o)

def _parse_odds_input_nba(s):
    s = s.strip().replace(" ", "")
    if not s: raise ValueError("Odds vacíos")
    return int(s) if s.lstrip("+-").isdigit() else int(float(s))

def export_log_pick_html(entry):
    """
    Genera 'Laboy NBA Pick YYYY-MM-DD #N.html' con pick card + análisis.
    Retorna path o None si falla.
    """
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    try:
        pick_date = entry.get("date", TARGET_DATE)
        pick_id   = entry.get("id", 0)
        game      = entry.get("game", "")
        pick      = entry.get("pick", "")
        odds_v    = entry.get("odds", 0)
        analysis  = entry.get("analysis", "")
        result    = entry.get("result")
        pnl       = entry.get("pnl")
        book      = entry.get("book", "BetMGM")
        stake     = entry.get("stake", 0)
        stake_disp = f"${stake:.2f}"

        odds_fmt  = _fmt_odds_nba(odds_v)
        dt        = datetime.strptime(pick_date, "%Y-%m-%d")
        dstr      = dt.strftime("%A, %B %d · %Y").upper()
        yr        = dt.strftime("%Y")

        # Detectar equipos para logo
        parts = re.split(r'\s+@\s+|\s+VS\.?\s+', game.upper())
        away_abb = parts[0].strip() if parts else ""
        home_abb = parts[1].strip() if len(parts) > 1 else ""
        pick_upper = pick.upper()
        is_total = any(kw in pick_upper for kw in ("OVER","UNDER")) or bool(re.match(r'^[OU][\s]?[\d.]', pick_upper))

        # Format game: "POR @ PHX" → "Blazers @ Suns"
        def _fmt_game_display(g):
            gp = re.split(r'\s+(@)\s+', g)
            if len(gp) == 3:
                a = TEAM_NICKNAMES.get(gp[0].strip().upper(), gp[0].strip())
                h = TEAM_NICKNAMES.get(gp[2].strip().upper(), gp[2].strip())
                return f"{a} @ {h}"
            return g

        pick_disp = _fmt_pick(pick)
        game_disp = _fmt_game_display(game)

        def _logo_img(abb, size=52):
            esp = ESPN_API_TO_INTERNAL.get(abb, abb).lower()
            return f'<img src="https://a.espncdn.com/i/teamlogos/nba/500/{esp}.png" alt="{abb}" width="{size}" height="{size}" style="object-fit:contain" onerror="this.style.display=\'none\'">'

        if is_total:
            logo_html = _nba_over_under_logo(60)
            color     = "#f97316"
        elif away_abb in TEAM_ABB or home_abb in TEAM_ABB:
            pick_team = away_abb if away_abb in pick_upper else (home_abb if home_abb in pick_upper else away_abb)
            logo_html = _logo_img(pick_team, 60)
            # use accent color
            color = "#3b82f6"
        else:
            logo_html = ""
            color = "#f97316"

        if result == "W":
            result_html = '<span style="background:#22c55e22;color:#22c55e;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">✓ WIN</span>'
            card_border = "#22c55e"
            card_bg = "background:linear-gradient(140deg,#061410 0%,#07080d 60%)"
            _glow_col  = "#22c55e"
        elif result == "L":
            result_html = '<span style="background:#ef444422;color:#ef4444;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">✗ LOSS</span>'
            card_border = "#ef4444"
            card_bg = "background:linear-gradient(140deg,#14060a 0%,#07080d 60%)"
            _glow_col  = "#ef4444"
        elif result == "P":
            result_html = '<span style="background:#94a3b822;color:#94a3b8;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">— PUSH</span>'
            card_border = "#94a3b8"
            card_bg = "background:linear-gradient(140deg,#090a10 0%,#07080d 60%)"
            _glow_col  = "#94a3b8"
        else:
            result_html = '<span style="background:#f0782022;color:#f07820;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">⏳ PENDING</span>'
            card_border = color
            card_bg = "background:linear-gradient(140deg,#090910 0%,#07080d 100%)"
            _glow_col  = color

        pnl_html = ""
        if pnl is not None:
            pnl_col  = "#22c55e" if pnl >= 0 else "#ef4444"
            pnl_sign = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            pnl_html = f'<div class="stat"><div class="stat-label">P&L</div><div class="stat-val" style="color:{pnl_col}">{pnl_sign}</div></div>'

        card1 = f"""
        <div class="pick-card" style="border-left:4px solid {card_border};{card_bg};
             border-top:1px solid {_glow_col}22;
             box-shadow:0 0 0 1px {_glow_col}10,0 0 28px {_glow_col}0a,0 6px 32px rgba(0,0,0,.85)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div style="font-size:0.62rem;color:#4a6272;font-family:monospace;letter-spacing:0.08em">
              <i class="fa-solid fa-ticket fa-icon"></i>PICK&nbsp;#{pick_id}&nbsp;&nbsp;·&nbsp;&nbsp;{esc(pick_date)}
            </div>
            {result_html}
          </div>
          <div class="teams-row">
            {logo_html}
            <div>
              <div class="game-label"><i class="fa-solid fa-basketball fa-icon"></i>{esc(game_disp)}</div>
              <div class="pick-label">{esc(pick_disp)} <span class="odds-badge">{esc(odds_fmt)}</span></div>
            </div>
          </div>
          <div class="stats-grid">
            <div class="stat"><div class="stat-label">{esc(book)}</div><div class="stat-val" style="color:#f07820">{esc(odds_fmt)}</div></div>
            <div class="stat"><div class="stat-label">Apostado</div><div class="stat-val">{esc(stake_disp)}</div></div>
            <div class="stat"><div class="stat-label">Fecha</div><div class="stat-val" style="font-size:0.75rem">{esc(pick_date)}</div></div>
            {pnl_html if pnl_html else '<div class="stat"><div class="stat-label">Resultado</div><div class="stat-val">—</div></div>'}
          </div>
        </div>"""

        card2 = ""
        if analysis and analysis.strip():
            analysis_html = esc(analysis).replace("\n", "<br>")
            card2 = f"""
        <div class="pick-card" style="border-left:4px solid {card_border};
             background:linear-gradient(150deg,#070812 0%,#06060a 100%);
             box-shadow:0 0 0 1px rgba(0,220,255,.05),0 4px 24px rgba(0,0,0,.8)">
          <div class="section-title" style="margin-top:0;margin-bottom:12px">
            <i class="fa-solid fa-magnifying-glass-chart fa-icon"></i>Análisis
          </div>
          <div style="font-size:0.88rem;line-height:1.85;color:#c8d4e0;
                      letter-spacing:0.015em;white-space:pre-wrap">{analysis_html}</div>
        </div>"""

        body = card1 + card2
        _safe_game_nba = re.sub(r'[<>:"/\\|?*]', '', game).replace('.','').strip()
        _safe_game_nba = re.sub(r'\s+', ' ', _safe_game_nba)[:40].strip()
        html = _nba_html_wrap(f"Laboy NBA Pick #{pick_id} · {dstr}", "NBA", dstr, yr, body)
        fname = f"Laboy NBA Pick {pick_date} #{pick_id} {_safe_game_nba}.html" if _safe_game_nba else f"Laboy NBA Pick {pick_date} #{pick_id}.html"
        fpath = os.path.join(SCRIPT_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)

        # Auto-generar JPG: wkhtmltoimage (Render) o Playwright (local)
        try:
            jpg_path = html_to_jpg(fpath)
            if jpg_path:
                print(f"  🖼️  JPG: {os.path.basename(jpg_path)}")
            else:
                _pil_jpg = _nba_pick_card_jpg(entry)
                if _pil_jpg:
                    print(f"  🖼️  JPG (PIL fallback): {os.path.basename(_pil_jpg)}")
        except Exception as _je:
            print(f"  ⚠️  JPG PIL export: {_je}")

        return fpath
    except Exception as e:
        print(f"  ⚠️  export_log_pick_html error: {e}")
        return None


def cmd_log_pick():
    """Registra pick personal — muestra juegos del día y auto-llena odds."""
    print(f"\n{'═'*62}")
    print(f"  LABOY PICKS — REGISTRAR JUGADA  NBA")
    print(f"{'═'*62}\n")

    # ── Cargar juegos + odds de hoy ──────────────────────────────────────
    print("  ⏳ Cargando juegos y odds de hoy...")
    games_today = get_nba_schedule(TARGET_DATE, silent=True)
    odds_map    = get_market_odds()

    if not games_today:
        print("  ⚠️  No se encontraron juegos NBA para hoy.")
        print("  💡 Agrega un juego: python3 nba.py --add-game AWAY HOME 'HORA'\n")

    # ── Menú de juegos ───────────────────────────────────────────────────
    game_str = ""
    if games_today:
        print("  JUEGOS DE HOY:\n")
        for i, g in enumerate(games_today, 1):
            away, home = g['away_abb'], g['home_abb']
            mkt = odds_map.get(f"{away}_{home}", {})
            # Extraer ML del primer book disponible
            ml_a, ml_h = None, None
            for bk in mkt.get('bookmakers', [])[:1]:
                for mo in bk.get('markets', []):
                    if mo['key'] in ('h2h', 'moneyline'):
                        for oc in mo.get('outcomes', []):
                            n = _full_name_to_abb(oc['name'])
                            if n == away: ml_a = oc['price']
                            elif n == home: ml_h = oc['price']
            ml_str = ""
            if ml_a and ml_h:
                ml_str = f"   ML: {away} {_fmt_odds_nba(ml_a)} / {home} {_fmt_odds_nba(ml_h)}"
            time_str = _to_pr_time(g.get('game_time_utc',''))
            print(f"  [{i}] {away} @ {home}  {time_str}{ml_str}")
        print()
        try:
            sel = input("  Selecciona juego (número) o Enter para escribir manualmente: ").strip()
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(games_today):
                    g    = games_today[idx]
                    away, home = g['away_abb'], g['home_abb']
                    game_str   = f"{away} @ {home}"
                    print(f"  ✓ Juego: {game_str}\n")
        except (ValueError, EOFError):
            pass

    # ── Si no seleccionó de menú, entrada manual ─────────────────────────
    if not game_str:
        game_str = input("  Juego (ej: BOS @ MIL): ").strip().upper()

    # ── Pick y tipo ───────────────────────────────────────────────────────
    try:
        pick = input("  Pick (ej: BOS ML / BOS -3.5 / O 224.5): ").strip().upper()

        # ── Auto-buscar odds del pick en mkt ─────────────────────────────
        parts = re.split(r'\s+@\s+|\s+VS\.?\s+', game_str.upper())
        away_abb = parts[0].strip() if parts else ""
        home_abb = parts[1].strip() if len(parts) > 1 else ""
        mkt = odds_map.get(f"{away_abb}_{home_abb}", {})

        auto_odds = None
        pick_upper = pick.upper()
        is_total = any(kw in pick_upper for kw in ("OVER","UNDER","O ","U "))
        is_spread = bool(re.search(r'[-+]\d+(\.\d+)?$', pick_upper.split()[-1] if pick_upper.split() else ""))

        for bk in mkt.get('bookmakers', [])[:1]:
            for mo in bk.get('markets', []):
                if mo['key'] in ('h2h','moneyline') and not is_total and not is_spread:
                    for oc in mo.get('outcomes', []):
                        n = _full_name_to_abb(oc['name'])
                        if n in pick_upper or (away_abb in pick_upper and n == away_abb) or (home_abb in pick_upper and n == home_abb):
                            auto_odds = oc['price']
                elif mo['key'] == 'spreads' and is_spread:
                    for oc in mo.get('outcomes', []):
                        n = _full_name_to_abb(oc['name'])
                        if n in pick_upper:
                            auto_odds = oc.get('price', -110)
                elif mo['key'] == 'totals' and is_total:
                    for oc in mo.get('outcomes', []):
                        if ('OVER' in pick_upper and oc['name'].upper() == 'OVER') or \
                           ('UNDER' in pick_upper and oc['name'].upper() == 'UNDER'):
                            auto_odds = oc['price']

        book_raw = input("  Sportsbook [BetMGM]: ").strip()
        book     = book_raw if book_raw else "BetMGM"

        if auto_odds is not None:
            print(f"  💰 Odds encontrados: {_fmt_odds_nba(auto_odds)}  (Enter para usar, o escribe otro)")
            override = input("  Odds: ").strip()
            odds_v   = _parse_odds_input_nba(override) if override else auto_odds
        else:
            odds_s = input("  Odds (ej: +130 o -110): ").strip()
            odds_v = _parse_odds_input_nba(odds_s)

        stake_s     = input("  Apostado (ej: 15 para $15.00): ").strip()
        stake_clean = re.sub(r"[^\d.]", "", stake_s.split()[0])
        stake       = float(stake_clean)
        analysis    = input("  Análisis (opcional — razón del pick, Enter para omitir):\n  > ").strip()
    except (ValueError, EOFError) as e:
        print(f"\n  ❌ Entrada inválida ({e}). Intenta de nuevo.\n"); return

    picks   = _load_picks()
    pick_id = len(picks)   # 0-based: new pick gets index = current length
    entry   = {
        'id': pick_id, 'date': TARGET_DATE,
        'game': game_str, 'pick': pick,
        'odds': odds_v, 'book': book,
        'stake': stake, 'result': None, 'pnl': None,
        'analysis': analysis or "",
    }
    picks.append(entry)
    _save_picks(picks)

    if odds_v > 0:
        pot = round(stake * (odds_v / 100), 2)
    else:
        pot = round(stake * (100 / abs(odds_v)), 2)
    print(f"\n  ✅ Pick #{pick_id}: {game_str} │ {pick} │ {_fmt_odds_nba(odds_v)} │ ${stake:.2f} → potencial +${pot:.2f}")

    # Auto-generar HTML + JPG card
    try:
        html_path = export_log_pick_html(entry)
        if html_path:
            print(f"  📄 Card: {os.path.basename(html_path)}")
    except Exception as e:
        print(f"  ⚠️  Export falló: {e}")
    print()


def cmd_export_log_nba():
    """
    --export-log [IDX]
    Re-exporta un pick NBA logueado como HTML + JPG.
    Si no se da IDX, exporta el último pick.
    """
    picks = _load_picks()
    if not picks:
        print("  ❌ No hay picks. Usa --log primero.\n"); return
    try:
        ei  = sys.argv.index("--export-log")
        idx_str = sys.argv[ei+1] if ei+1 < len(sys.argv) and not sys.argv[ei+1].startswith("--") else None
        idx = int(idx_str) if idx_str else len(picks) - 1
    except (ValueError, IndexError):
        idx = len(picks) - 1
    if not (0 <= idx < len(picks)):
        print(f"  ❌ Índice {idx} inválido. Hay {len(picks)} picks (0–{len(picks)-1}).\n"); return
    entry = picks[idx]
    print(f"\n  📄 Exportando Pick #{entry['id']}: {entry['game']} │ {entry['pick']} │ {_fmt_odds_nba(entry['odds'])}")
    html_path = export_log_pick_html(entry)
    if html_path:
        print(f"  ✅ Guardado: {os.path.basename(html_path)}\n")
        if PUBLISH_MODE:
            cmd_publish([html_path])
    else:
        print("  ❌ Error al exportar.\n")

def cmd_grade_pick(idx, result):
    """
    Califica pick por índice (0-based, como aparece en --record).
    Uso: python3 nba.py --grade IDX W|L|P
    """
    picks = _load_picks()
    if not (0 <= idx < len(picks)):
        print(f"  ❌ Índice {idx} no válido. Hay {len(picks)} picks (0–{len(picks)-1}).")
        print(f"     Corre: python3 nba.py --record  para ver los índices.\n")
        return None
    p = picks[idx]
    p['result'] = result
    sv = float(p.get('stake', 0))
    odds_v = int(p.get('odds', -110))
    if result == 'W':
        p['pnl'] = round(sv * (odds_v / 100) if odds_v > 0 else sv * (100 / abs(odds_v)), 2)
    elif result == 'L':
        p['pnl'] = round(-sv, 2)
    else:
        p['pnl'] = 0.0
    _save_picks(picks)
    emoji = {"W": "✅", "L": "❌", "P": "🔄"}[result]
    pnl_str = (f"+${p['pnl']:.2f}" if p['pnl'] >= 0 else f"-${abs(p['pnl']):.2f}")
    print(f"\n  {emoji} Pick #{idx} → {result} | {p['game']} {p['pick']} {_fmt_odds_nba(odds_v)} | P&L: {pnl_str}")
    return p


def cmd_remove_pick(idx):
    """
    Elimina pick por índice (0-based). Pide confirmación y renumera.
    """
    picks = _load_picks()
    if not picks:
        print("  ❌ No hay picks en el log.\n"); return
    if not (0 <= idx < len(picks)):
        print(f"  ❌ Índice {idx} no válido. Hay {len(picks)} picks (0–{len(picks)-1}).\n"); return

    e = picks[idx]
    print(f"\n{'═'*52}")
    print(f"  ⚠️  ELIMINAR PICK")
    print(f"{'═'*52}")
    print(f"  #{idx} — {e['date']} | {e['game']} | {e['pick']} {_fmt_odds_nba(e['odds'])}")
    print()
    confirm = input("  ¿Confirmar eliminación? (s/N): ").strip().lower()
    if confirm not in ("s", "si", "sí", "y", "yes"):
        print("  ↩️  Cancelado.\n"); return

    new_picks = [p for i, p in enumerate(picks) if i != idx]
    for new_id, p in enumerate(new_picks):
        p["id"] = new_id
    _save_picks(new_picks)
    print(f"\n  ✅ Pick #{idx} eliminado. Quedan {len(new_picks)} en el log.\n")

def cmd_record():
    """
    --record              → últimos 30 picks (más recientes primero)
    --record all          → todos los picks
    --record 2026-04-18   → solo picks de esa fecha
    --record --pending    → solo picks sin gradear
    """
    picks = _load_picks()
    print(f"\n{'═'*80}")
    print(f"  LABOY PICKS — NBA · REGISTRO")
    print(f"{'═'*80}")
    if not picks:
        print("\n  No hay jugadas. Usa: python3 nba.py --log\n"); return

    # ── Parse argument after --record ────────────────────────────────────────
    date_filter   = None
    date_range    = None   # (start, end) para filtrar por rango de fechas
    show_all      = False
    pending_only  = PENDING_MODE
    try:
        ri  = sys.argv.index("--record")
        arg = sys.argv[ri + 1] if ri + 1 < len(sys.argv) and not sys.argv[ri + 1].startswith("--") else None
        if arg:
            if arg.lower() == "all":
                show_all = True
            elif arg.lower() == "r1":
                date_range = ("2026-04-12", "2026-05-05")
            elif arg.lower() == "r2":
                date_range = ("2026-05-06", "2026-05-27")
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", arg):
                date_filter = arg
    except (ValueError, IndexError):
        pass

    # ── Build running balance over ALL picks ─────────────────────────────────
    running_balance = 0.0
    bal_by_idx = {}
    for i, p in enumerate(picks):
        res = p.get("result") or "—"
        sv  = float(p.get("stake", 0))
        pnl = p.get("pnl")
        if res == "W":
            running_balance += pnl if pnl is not None else sv
        elif res == "L":
            running_balance -= sv
        bal_by_idx[i] = running_balance

    # ── Filter ───────────────────────────────────────────────────────────────
    indexed = list(enumerate(picks))
    if pending_only:
        display = [(i, p) for i, p in indexed if not p.get("result")]
        filter_label = f"  ⏳ {len(display)} picks PENDIENTES de {len(picks)} totales"
        if not display:
            print("\n  ✅ Todos los picks están calificados.\n"); return
    elif date_range:
        r_start, r_end = date_range
        display = [(i, p) for i, p in indexed if r_start <= p.get("date","") <= r_end]
        round_name = "R1" if date_range[0].endswith("04-12") else "R2"
        filter_label = f"  🏆 Playoffs {round_name} ({r_start} → {r_end})  |  {len(display)} picks"
        if not display:
            print(f"\n  Sin picks para playoffs {round_name}.\n"); return
    elif date_filter:
        display = [(i, p) for i, p in indexed if p.get("date","") == date_filter]
        filter_label = f"  📅 Filtrado: {date_filter}  ({len(display)} picks)"
        if not display:
            print(f"\n  Sin picks para {date_filter}.\n"); return
    elif show_all:
        display = indexed
        filter_label = f"  📋 Todos los picks ({len(picks)})"
    else:
        display = indexed[-30:]
        filter_label = f"  📋 Últimos {len(display)} picks  (usa --record all para ver todos)"

    # ── Newest first ─────────────────────────────────────────────────────────
    display = list(reversed(display))

    rows = []
    for idx, p in display:
        res     = p.get("result") or "—"
        sv      = float(p.get("stake", 0))
        pnl     = p.get("pnl")
        odds_v  = int(p.get("odds", 0))
        bal_val = bal_by_idx.get(idx, 0.0)
        bal_fmt = f"+${bal_val:.2f}" if bal_val >= 0 else f"-${abs(bal_val):.2f}"
        pnl_fmt = (f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}") if pnl is not None else "—"
        rows.append([idx, p.get("date",""), p.get("game","")[:22], p.get("pick","")[:14],
                     _fmt_odds_nba(odds_v), f"${sv:.2f}", res, pnl_fmt, bal_fmt])

    headers = ["#","Fecha","Juego","Pick","Odds","Apostado","Res","P&L","Ganancia"]
    print(f"\n{filter_label}")
    if tabulate:
        from tabulate import tabulate as _tab
        print("\n" + _tab(rows, headers=headers, tablefmt="simple"))
    else:
        hdr = f"  {'#':>3}  {'Fecha':<12}  {'Juego':<22}  {'Pick':<14}  {'Odds':>6}  {'Apost':>7}  {'Res':>4}  {'P&L':>8}  {'Ganancia':>9}"
        print("\n" + hdr)
        print("  " + "─"*86)
        for r in rows:
            print(f"  {r[0]:>3}  {r[1]:<12}  {r[2]:<22}  {r[3]:<14}  {r[4]:>6}  {r[5]:>7}  {r[6]:>4}  {r[7]:>8}  {r[8]:>9}")

    # ── Stats: over filtered set when range mode, otherwise full log ─────────
    stat_picks = [p for _, p in display] if date_range else picks
    graded  = [p for p in stat_picks if p.get("result") in ("W","L","P")]
    wins    = [p for p in graded if p["result"]=="W"]
    pnl_t   = sum(p.get("pnl",0) for p in graded if p.get("pnl") is not None)
    wag     = sum(float(p.get("stake",0)) for p in graded)
    roi     = (pnl_t / wag * 100) if wag > 0 else 0
    pending = len(stat_picks) - len(graded)
    pnl_str = f"+${pnl_t:.2f}" if pnl_t >= 0 else f"-${abs(pnl_t):.2f}"
    bal_final = f"+${running_balance:.2f}" if running_balance >= 0 else f"-${abs(running_balance):.2f}"

    n_w = len(wins)
    n_l = len([p for p in graded if p['result']=='L'])
    n_p = len([p for p in graded if p['result']=='P'])
    win_pct = n_w / len(graded) * 100 if graded else 0.0

    print(f"\n  📊 Récord total: {n_w}-{n_l}-{n_p}  "
          f"Pending: {pending}")
    if graded:
        print(f"     Win%: {win_pct:.1f}%  │  P&L: {pnl_str}  │  Jugado: ${wag:.2f}  │  ROI: {roi:+.1f}%")
    if not date_range:
        print(f"  💰 Ganancia actual: {bal_final}")
    print(f"\n  Tips:")
    print(f"    python3 nba.py --record all              ← ver todos los picks")
    print(f"    python3 nba.py --record 2026-04-18       ← picks de una fecha")
    print(f"    python3 nba.py --record --pending        ← solo picks sin gradear")
    print(f"    python3 nba.py --grade N W|L|P           ← califica pick #N")
    print(f"    python3 nba.py --remove N                ← elimina pick #N del log")
    print(f"    python3 nba.py --export-record           ← exporta card como HTML+JPG\n")

def cmd_feedback():
    """Performance analysis + AI feedback."""
    picks = _load_picks()

    if not picks:
        print("No picks to analyze.\n")
        return

    # Basic stats
    wins = sum(1 for p in picks if p.get('result') == 'W')
    losses = sum(1 for p in picks if p.get('result') == 'L')
    total_pnl = sum(p.get('pnl', 0) for p in picks if p.get('pnl') is not None)

    print("\n" + "="*60)
    print("PERFORMANCE FEEDBACK")
    print("="*60)
    print(f"Record: {wins}-{losses}")
    print(f"Total P&L: {total_pnl:+.2f}\n")

    # AI feedback if API key available
    if os.environ.get("ANTHROPIC_API_KEY") and Anthropic:
        try:
            client = Anthropic()

            # Get recent losses
            recent_losses = [p for p in sorted(picks, key=lambda x: x['date'], reverse=True)
                            if p.get('result') == 'L'][:10]

            if recent_losses:
                context = "Recent losses:\n" + "\n".join([
                    f"- {p['game']}: {p['pick']} @ {p['odds']} ({p.get('analysis', 'N/A')})"
                    for p in recent_losses
                ])

                response = client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=500,
                    messages=[{
                        'role': 'user',
                        'content': f"{context}\n\nAnalyze these loss patterns. Responde en español."
                    }]
                )
                print(response.content[0].text)
        except Exception as e:
            print(f"AI analysis unavailable: {e}")
    print()

# ============================================================================
# GRADE PICKS FROM HTML
# ============================================================================

def cmd_grade_picks(source):
    """
    Parsea HTML de picks NBA, califica con scores de ESPN,
    actualiza el HTML con badges estilo MLB/BSN y genera + publica el Model Card.
    Maneja ML, Spread (+/-N.N) y Totals (Over/Under).
    """
    # ── 1. Cargar HTML ────────────────────────────────────────────────────────
    if source.startswith('http'):
        try:
            req = Request(source, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as resp:
                html_content = resp.read().decode('utf-8')
        except Exception as e:
            print(f"  ❌ Error fetching URL: {e}"); return
    else:
        try:
            with open(source, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except Exception as e:
            print(f"  ❌ Error loading file: {e}"); return

    if not BeautifulSoup:
        print("  ❌ beautifulsoup4 no instalado: pip install beautifulsoup4"); return

    soup = BeautifulSoup(html_content, 'html.parser')

    # ── 2. Extraer fecha del <title> ──────────────────────────────────────────
    _MONTHS = {
        "JANUARY":"01","FEBRUARY":"02","MARCH":"03","APRIL":"04",
        "MAY":"05","JUNE":"06","JULY":"07","AUGUST":"08",
        "SEPTEMBER":"09","OCTOBER":"10","NOVEMBER":"11","DECEMBER":"12",
    }
    date_str = None
    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True).upper() if title_tag else ""
    iso_m = re.search(r'(\d{4}-\d{2}-\d{2})', title_text)
    if iso_m:
        date_str = iso_m.group(1)
    else:
        m = re.search(r'([A-Z]+)\s+(\d{1,2})\s*[·•\-]\s*(\d{4})', title_text)
        if m and m.group(1) in _MONTHS:
            date_str = f"{m.group(3)}-{_MONTHS[m.group(1)]}-{int(m.group(2)):02d}"
    if not date_str:
        date_str = TARGET_DATE
        print(f"  ⚠️  Fecha no encontrada en título, usando: {date_str}")
    print(f"  📅 Fecha: {date_str}")

    # ── 3. Mapa nickname → abreviación interna ────────────────────────────────
    _nick_to_abb = {v.upper(): k for k, v in TEAM_NICKNAMES.items()}
    _nick_to_abb.update({
        "BLAZERS":"POR","CAVALIERS":"CLE","WARRIORS":"GSW","CLIPPERS":"LAC",
        "TIMBERWOLVES":"MIN","TWOLVES":"MIN","76ERS":"PHI","SIXERS":"PHI",
    })

    # ── 4. Obtener scores de ESPN ─────────────────────────────────────────────
    print(f"  📡 Fetching scores …")
    raw_scores = _fetch_nba_scores(date_str)
    score_map = {}
    for s in raw_scores:
        a = ESPN_API_TO_INTERNAL.get(s['away_abb'].upper(), s['away_abb'].upper())
        h = ESPN_API_TO_INTERNAL.get(s['home_abb'].upper(), s['home_abb'].upper())
        score_map[f"{a}_{h}"] = s
        score_map[f"{s['away_abb'].upper()}_{s['home_abb'].upper()}"] = s
    if not raw_scores:
        print(f"  ⚠️  Sin scores para {date_str}. ¿Juegos finalizados?")

    # ── 5. Limpiar badges previos ─────────────────────────────────────────────
    pick_cards = soup.find_all('div', class_='pick-card')
    if not pick_cards:
        print("  ❌ No se encontraron pick cards en el HTML."); return
    for card in pick_cards:
        for el in card.find_all("div", style=lambda s: s and "justify-content:flex-end" in (s or "")):
            el.decompose()
        for el in card.find_all("div", style=lambda s: s and "font-size:0.75rem" in (s or "") and s and "color:#94a3b8" in (s or "")):
            el.decompose()

    # ── 6. Calificar cada pick card ───────────────────────────────────────────
    n_graded = n_skipped = 0
    picks_with_results = []

    for card in pick_cards:
        game_label_div = card.find('div', class_='game-label')
        if not game_label_div:
            continue
        gm = re.search(r'(\w+)\s+@\s+(\w+)', game_label_div.get_text(strip=True).upper())
        if not gm:
            continue
        away_nick, home_nick = gm.group(1), gm.group(2)
        away_abb = _nick_to_abb.get(away_nick, away_nick)
        home_abb = _nick_to_abb.get(home_nick, home_nick)
        game_label_str = game_label_div.get_text(strip=True)

        score = score_map.get(f"{away_abb}_{home_abb}") or score_map.get(f"{away_nick}_{home_nick}")
        if score is None:
            print(f"  ⚠️  Sin score: {away_nick} @ {home_nick}")
            n_skipped += 1
            continue
        status = score.get('status', '')
        if 'final' not in status.lower():
            print(f"  ⏳ No finalizado ({status}): {away_nick} @ {home_nick}")
            n_skipped += 1
            continue

        away_score  = score['away_score']
        home_score  = score['home_score']
        actual_total = away_score + home_score
        sc_str = f"{away_score}–{home_score}"

        # pick-label: extraer texto sin odds badge
        pick_label_div = card.find('div', class_='pick-label')
        if not pick_label_div:
            continue
        odds_span = pick_label_div.find('span', class_='odds-badge')
        odds_str = odds_span.get_text(strip=True) if odds_span else "—"
        if odds_span:
            odds_span.extract()
        pick_text = pick_label_div.get_text(strip=True).upper()
        if odds_span:
            pick_label_div.append(odds_span)

        result = None
        ml_m = re.match(r'^(\w+)\s+ML$', pick_text)
        sp_m = re.match(r'^(\w+)\s+([+-][\d.]+)$', pick_text)
        ov_m = re.match(r'^(?:OVER|O)\s+([\d.]+)$', pick_text)
        un_m = re.match(r'^(?:UNDER|U)\s+([\d.]+)$', pick_text)

        if ml_m:
            t = _nick_to_abb.get(ml_m.group(1), ml_m.group(1))
            if t in (away_abb, away_nick):
                result = 'W' if away_score > home_score else ('P' if away_score == home_score else 'L')
            elif t in (home_abb, home_nick):
                result = 'W' if home_score > away_score else ('P' if home_score == away_score else 'L')
        elif sp_m:
            t = _nick_to_abb.get(sp_m.group(1), sp_m.group(1))
            spread_val = float(sp_m.group(2))
            margin = (away_score - home_score) if t in (away_abb, away_nick) \
                else (home_score - away_score) if t in (home_abb, home_nick) else None
            if margin is not None:
                cover = margin + spread_val
                result = 'W' if cover > 0 else ('P' if cover == 0 else 'L')
        elif ov_m:
            line   = float(ov_m.group(1))
            result = 'W' if actual_total > line else ('P' if actual_total == line else 'L')
        elif un_m:
            line   = float(un_m.group(1))
            result = 'W' if actual_total < line else ('P' if actual_total == line else 'L')

        if result is None:
            print(f"  ⚠️  Pick no reconocido: '{pick_text}'")
            n_skipped += 1
            continue

        # ── Badges estilo MLB/BSN ─────────────────────────────────────────────
        color = "#22c55e" if result == "W" else ("#ef4444" if result == "L" else "#94a3b8")
        if result == "W":
            badge_html = '<span style="background:#22c55e22;color:#22c55e;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">✅ WIN</span>'
            card_bg    = "background:linear-gradient(135deg,#0d1f14 0%,#222222 60%)"
        elif result == "L":
            badge_html = '<span style="background:#ef444422;color:#ef4444;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">❌ LOSS</span>'
            card_bg    = "background:linear-gradient(135deg,#1f0d0d 0%,#222222 60%)"
        else:
            badge_html = '<span style="background:#94a3b822;color:#94a3b8;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">— PUSH</span>'
            card_bg    = "background:linear-gradient(135deg,#14161a 0%,#222222 60%)"

        # Badge row al tope de la card (flex, right-aligned)
        badge_div = soup.new_tag("div", style="display:flex;justify-content:flex-end;margin-bottom:10px")
        badge_div.append(BeautifulSoup(badge_html, "html.parser"))
        card.insert(0, badge_div)

        # Score bajo pick-label
        score_div = soup.new_tag("div", style="font-size:0.75rem;color:#94a3b8;margin-top:4px")
        score_div.string = f"Score: {sc_str}"
        pick_label_div.insert_after(score_div)

        # Card: border + background
        card["style"] = f"border-left:4px solid {color};{card_bg}"

        res_sym = {"W":"✅","L":"❌","P":"—"}.get(result, "⏳")
        print(f"  {res_sym} {result}  {away_nick} @ {home_nick}  [{pick_text}]  ({sc_str})")
        n_graded += 1

        picks_with_results.append({
            "game":   game_label_str,
            "pick":   pick_text,
            "odds":   odds_str,
            "result": result,
            "score":  sc_str,
            "color":  color,
        })

    print(f"\n  ✅ {n_graded} picks calificados, {n_skipped} omitidos.")

    # ── 7. Guardar picks HTML actualizado ─────────────────────────────────────
    if source.startswith('http'):
        out_path = os.path.join(SCRIPT_DIR, f"Laboy NBA Picks {date_str}.html")
    elif os.path.dirname(os.path.abspath(source)) != os.path.abspath(SCRIPT_DIR):
        out_path = os.path.join(SCRIPT_DIR, os.path.basename(source))
    else:
        out_path = source
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(str(soup))
    print(f"  💾 Picks HTML: {os.path.basename(out_path)}")

    # ── 8. Generar Model Card (RECORD-MODELO) con resultados ─────────────────
    model_card_path = export_daily_picks_card(date_str, picks_with_results)

    # ── 9. Publicar AMBOS: Picks HTML (con badges) + Model Card ──────────────
    if PUBLISH_MODE:
        to_publish = []
        if out_path and os.path.isfile(out_path):
            to_publish.append(out_path)           # Laboy NBA Picks {date}.html
        if model_card_path and os.path.isfile(model_card_path):
            to_publish.append(model_card_path)    # Laboy NBA Model Card {date}.html
        if to_publish:
            cmd_publish(to_publish)
        else:
            print("  ⚠️  No hay HTMLs para publicar.")

    return out_path

# ============================================================================
# RECORD CARD EXPORT
# ============================================================================

def export_record_card(date_str=None):
    """
    Genera 'Laboy NBA Record Card {DATE}.html' con picks del log personal
    (equivalente a MLB/BSN export_record_card).
    Retorna path del HTML generado.
    """
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    log = _load_picks()
    if not log:
        print("  ⚠️  No hay picks en el log."); return None

    if date_str:
        entries = [e for e in log if e.get("date") == date_str]
    else:
        entries = log

    label_date = date_str or "All-Time"
    try:
        if label_date != "All-Time":
            dt   = datetime.strptime(label_date, "%Y-%m-%d")
            dstr = dt.strftime("%A, %B %d").upper()
            yr   = dt.strftime("%Y")
        else:
            dstr = "ALL-TIME"
            yr   = datetime.now().strftime("%Y")
    except Exception:
        dstr = "ALL-TIME"
        yr   = datetime.now().strftime("%Y")

    def _rc_logo(abb, size=52):
        """ESPN CDN logo for record card."""
        esp = ESPN_ABB.get(abb, abb.lower())
        return (f'<img src="https://a.espncdn.com/i/teamlogos/nba/500/{esp}.png" '
                f'alt="{abb}" width="{size}" height="{size}" '
                f'style="object-fit:contain;border-radius:6px" '
                f'onerror="this.style.display=\'none\'">')

    # Mapa extendido nickname → abreviación interna (para logos en record card)
    _rc_nick_map = {v.upper(): k for k, v in TEAM_NICKNAMES.items()}
    _rc_nick_map.update({
        # Variantes cortas / populares que no están en TEAM_NICKNAMES
        "WOLVES":"MIN",  "TIMBERWOLVES":"MIN", "TWOLVES":"MIN",
        "BLAZERS":"POR", "CAVALIERS":"CLE",    "WARRIORS":"GSW",
        "CLIPPERS":"LAC","SIXERS":"PHI",       "76ERS":"PHI",
        "NETS":"BKN",    "MAVS":"DAL",         "SUNS":"PHX",
        "SPURS":"SAS",   "ROCKETS":"HOU",      "MAGIC":"ORL",
        "BULLS":"CHI",   "PISTONS":"DET",      "PACERS":"IND",
        "HAWKS":"ATL",   "HEAT":"MIA",         "BUCKS":"MIL",
        "KNICKS":"NYK",  "RAPTORS":"TOR",      "CELTICS":"BOS",
        "76ERS":"PHI",   "JAZZ":"UTA",         "NUGGETS":"DEN",
        "THUNDER":"OKC", "TRAILBLAZERS":"POR", "KINGS":"SAC",
        "LAKERS":"LAL",  "CLIPPERS":"LAC",     "GRIZZLIES":"MEM",
        "PELICANS":"NOP","HORNETS":"CHA",       "WIZARDS":"WAS",
    })

    def _rc_pick_team(pick_raw, game_str):
        """Extract primary team abbreviation from pick string.
        Handles both 3-letter codes (MIN, DEN) and nicknames (WOLVES, NUGGETS, KNICKS, etc.)
        """
        parts = pick_raw.strip().upper().split()
        # 1. Directo: primera palabra es abreviación interna (MIN, DEN, etc.)
        if parts and parts[0] in TEAM_ABB:
            return parts[0]
        # 2. Nickname map: buscar la primera palabra que sea un apodo conocido
        for word in parts:
            if word in _rc_nick_map:
                return _rc_nick_map[word]
        # 3. Compuesto: buscar frases de dos palabras ("TRAIL BLAZERS", etc.)
        for i in range(len(parts) - 1):
            two = f"{parts[i]} {parts[i+1]}"
            if two in _rc_nick_map:
                return _rc_nick_map[two]
        # 4. Fallback: tomar equipo visitante del game_label (solo para totals Over/Under)
        is_total = bool(re.match(r'^[OU]\s', pick_raw.strip().upper()))
        if is_total:
            g_parts = re.split(r'\s+[@vs\.]+\s+', game_str, flags=re.IGNORECASE)
            if g_parts:
                return g_parts[0].strip()
        return ""

    def _rc_fmt_game(game_str):
        """'POR @ PHX' → 'Blazers @ Suns'"""
        g_parts = re.split(r'\s+(@)\s+', game_str)
        if len(g_parts) == 3:
            a = g_parts[0].strip().upper(); h = g_parts[2].strip().upper()
            a_nick = TEAM_NICKNAMES.get(a, a); h_nick = TEAM_NICKNAMES.get(h, h)
            return f"{a_nick} @ {h_nick}"
        return game_str

    running_balance = 0.0
    picks_html = ""
    w = l = pu = 0

    for e in entries:
        sv     = float(e.get("stake", 0))
        pnl    = e.get("pnl")
        result = e.get("result") or "⏳"
        odds_v = int(e.get("odds", 0))
        raw_pick = e.get("pick", "")
        game_str = e.get("game", "")

        if result == "W":
            running_balance += pnl if pnl is not None else sv
            w += 1
        elif result == "L":
            running_balance -= sv
            l += 1
        elif result == "P":
            pu += 1

        _epnl = pnl
        if _epnl is not None:
            bal_fmt = f"+${_epnl:.2f}" if _epnl >= 0 else f"-${abs(_epnl):.2f}"
        elif result == "W":
            bal_fmt = f"+${sv:.2f}"
        elif result == "L":
            bal_fmt = f"-${sv:.2f}"
        else:
            bal_fmt = "—"

        # Logo: totals → over_under; else pick team
        is_total = re.match(r'^[OU]\s+\d', raw_pick.strip())
        if is_total:
            logo_h = _nba_over_under_logo(52)
        else:
            tm = _rc_pick_team(raw_pick, game_str)
            logo_h = _rc_logo(tm, 52) if tm else ""

        pick_display = esc(_fmt_pick(raw_pick))
        game_display = esc(_rc_fmt_game(game_str))
        _rc_cls  = {"W":"win","L":"loss","P":"push"}.get(result,"pending")
        _rc_bt   = {"W":"WIN","L":"LOSS","P":"PUSH"}.get(result,"PENDING")
        _book_e  = e.get("book","")
        _meta_e  = " · ".join(x for x in [_book_e, f"Stake: ${sv:.2f}"] if x)

        picks_html += f"""
<div class="rc-pick {_rc_cls}">
  <div class="rc-row">
    {logo_h}
    <div class="rc-main">
      <div class="rc-pick-name">{pick_display}<span class="rc-odds">{esc(_fmt_odds_nba(odds_v))}</span></div>
      <div class="rc-game">{game_display}</div>
      <div class="rc-meta">{esc(_meta_e)}</div>
    </div>
    <div class="rc-result-col">
      <span class="rc-badge {_rc_cls}">{_rc_bt}</span>
      <div class="rc-pnl {_rc_cls}">{esc(bal_fmt)}</div>
    </div>
  </div>
</div>"""

    total   = w + l + pu
    pnl_t   = sum(e.get("pnl",0) for e in entries if e.get("result") in ("W","L","P") and e.get("pnl") is not None)
    wag     = sum(float(e.get("stake",0)) for e in entries if e.get("result") in ("W","L","P"))
    roi     = (pnl_t / wag * 100) if wag > 0 else 0
    win_pct = f"{w/total*100:.0f}%" if total else "—"
    pnl_str = f"+${pnl_t:.2f}" if pnl_t >= 0 else f"-${abs(pnl_t):.2f}"
    bal_str = f"+${running_balance:.2f}" if running_balance >= 0 else f"-${abs(running_balance):.2f}"
    win_col = "#22c55e" if w >= l else "#ef4444"
    pnl_col = "#22c55e" if pnl_t >= 0 else "#ef4444"
    _DIAS_EN  = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    _MESES_EN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    if date_str:
        try:
            from datetime import date as _date
            _dobj = _date.fromisoformat(date_str)
            _rc_date_lbl = f"{_DIAS_EN[_dobj.weekday()]}, {_MESES_EN[_dobj.month-1]} {_dobj.day}"
        except Exception:
            _rc_date_lbl = date_str
    else:
        _rc_date_lbl = "All-Time"
    _roi_str = f"{roi:+.1f}%"

    _RC_CSS = """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:#080c12;color:#e2e8f0}
.rc-title{text-align:center;padding:12px 0 24px}
.rc-sport-lbl{font-size:1.6rem;font-weight:800;letter-spacing:.03em;color:#fff;margin-bottom:5px}
.rc-date-full{font-size:.78rem;color:#64748b;letter-spacing:.08em;text-transform:uppercase}
.rc-pick{border-radius:14px;padding:14px 16px;margin-bottom:10px;position:relative;
  overflow:hidden;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07)}
.rc-pick.win{border-left:4px solid #22c55e;background:linear-gradient(135deg,rgba(34,197,94,.08) 0%,rgba(255,255,255,.03) 60%)}
.rc-pick.loss{border-left:4px solid #ef4444;background:linear-gradient(135deg,rgba(239,68,68,.08) 0%,rgba(255,255,255,.03) 60%)}
.rc-pick.push{border-left:4px solid #94a3b8;background:rgba(255,255,255,.04)}
.rc-pick.pending{border-left:4px solid #f59e0b;background:rgba(255,255,255,.04)}
.rc-row{display:flex;align-items:center;gap:12px}
.rc-logo{flex-shrink:0}
.rc-main{flex:1;min-width:0}
.rc-pick-name{font-size:.95rem;font-weight:600;color:#f1f5f9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rc-odds{font-size:.78rem;color:#64748b;margin-left:6px;font-weight:400}
.rc-game{font-size:.78rem;color:#64748b;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rc-meta{font-size:.72rem;color:#475569;margin-top:4px;letter-spacing:.02em}
.rc-result-col{display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex-shrink:0}
.rc-badge{font-size:.68rem;font-weight:700;letter-spacing:.1em;padding:3px 9px;border-radius:20px}
.rc-badge.win{background:rgba(34,197,94,.18);color:#22c55e}
.rc-badge.loss{background:rgba(239,68,68,.18);color:#ef4444}
.rc-badge.push{background:rgba(148,163,184,.12);color:#94a3b8}
.rc-badge.pending{background:rgba(245,158,11,.12);color:#f59e0b}
.rc-pnl{font-size:.9rem;font-weight:700}
.rc-pnl.win{color:#22c55e}
.rc-pnl.loss{color:#ef4444}
.rc-pnl.push{color:#94a3b8}
.rc-summary{margin-top:18px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
  border-radius:14px;padding:18px}
.rc-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;text-align:center}
.rc-stat-lbl{font-size:.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}
.rc-stat-val{font-size:1.15rem;font-weight:700;line-height:1}
</style>"""
    body = f"""{_RC_CSS}
<div class="rc-title"><div class="rc-sport-lbl">🏀 NBA</div><div class="rc-date-full">{_rc_date_lbl}</div></div>
{picks_html}
<div class="rc-summary">
  <div class="rc-stats">
    <div class="rc-stat">
      <div class="rc-stat-lbl">Record</div>
      <div class="rc-stat-val" style="color:{win_col}">{w}-{l}-{pu}</div>
    </div>
    <div class="rc-stat">
      <div class="rc-stat-lbl">Win Rate</div>
      <div class="rc-stat-val" style="color:{win_col}">{win_pct}</div>
    </div>
    <div class="rc-stat">
      <div class="rc-stat-lbl">Profit/Loss</div>
      <div class="rc-stat-val" style="color:{pnl_col}">{pnl_str}</div>
    </div>
    <div class="rc-stat">
      <div class="rc-stat-lbl">ROI</div>
      <div class="rc-stat-val" style="color:{pnl_col}">{_roi_str}</div>
    </div>
  </div>
</div>
"""

    if not label_date or label_date == "All-Time":
        fname = f"Laboy NBA Record Card All-Time.html"
    else:
        fname = f"Laboy NBA Record Card {label_date}.html"

    html_path = os.path.join(SCRIPT_DIR, fname)
    html = _nba_html_wrap(f"Laboy NBA Record {label_date}", "NBA", dstr, yr, body)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📄 Record Card: {fname}")

    # Auto-generar JPG
    try:
        jpg = html_to_jpg(html_path)
        if jpg:
            print(f"  🖼️  JPG: {os.path.basename(jpg)}")
    except Exception as _e:
        pass

    return html_path

# ============================================================================
# SCREENSHOT EXPORT / PIL PICK CARD
# ============================================================================

_NBA_FONTS_DIR = os.path.join(SCRIPT_DIR, "..", ".claude", "skills", "canvas-design", "canvas-fonts")

try:
    from PIL import Image as _PIL_Image, ImageDraw as _PIL_Draw, ImageFont as _PIL_Font
    _NBA_HAS_PIL = True
except ImportError:
    _NBA_HAS_PIL = False

def _nba_pick_card_jpg(entry):
    """Genera JPG del pick card NBA usando PIL. Directo, sin Playwright."""
    if not _NBA_HAS_PIL: return None
    try:
        import textwrap as _tw, re as _re, io as _io
        import urllib.request as _ur
        C_BG=(10,10,10); C_CARD=(34,34,34); C_ACCENT=(59,130,246)  # NBA blue
        C_TEXT=(241,245,249); C_MUTED=(148,163,184); C_BORDER=(42,42,42)
        C_GREEN=(34,197,94); C_RED=(239,68,68); C_STAT=(24,24,24)
        pick_date=entry.get("date",""); pick_id=entry.get("id",0)
        game=entry.get("game","").upper(); pick_str=entry.get("pick","")
        odds_v=entry.get("odds",0); analysis=entry.get("analysis","").strip()
        book=entry.get("book",""); result=entry.get("result")
        odds_s=_fmt_odds_nba(odds_v); is_pos=odds_v>=0
        try:
            dstr=__import__("datetime").datetime.strptime(pick_date,"%Y-%m-%d").strftime("%A, %B %d · %Y").upper()
        except: dstr=pick_date.upper()
        # Team color from pick/game
        parts=_re.split(r'\s+(?:@|VS\.?)\s+',game,flags=_re.IGNORECASE)
        away_abb=parts[0].strip() if parts else ""; home_abb=parts[1].strip() if len(parts)>1 else ""
        def h2r(h):
            h=h.lstrip('#'); return tuple(int(h[i:i+2],16) for i in (0,2,4))
        C_TEAM=h2r(TEAM_COLORS.get(away_abb,"#3b82f6"))
        RES_C={"W":C_GREEN,"L":C_RED,"P":(148,163,184)}.get(result,C_TEAM)
        pick_disp=_fmt_pick(pick_str)
        # Fonts
        def fnt(size,bold=False):
            sfx="-Bold" if bold else ""
            for p in [os.path.join(_NBA_FONTS_DIR,f"BigShoulders{'Bold' if bold else 'Regular'}.ttf"),
                      f"/usr/share/fonts/truetype/dejavu/DejaVuSans{sfx}.ttf",
                      f"/usr/share/fonts/truetype/liberation/LiberationSans{sfx}.ttf",
                      "/System/Library/Fonts/Helvetica.ttc"]:
                if os.path.exists(p):
                    try: return _PIL_Font.truetype(p,size)
                    except: pass
            try: return _PIL_Font.load_default(size=size)
            except: return _PIL_Font.load_default()
        F_TITLE=fnt(44,True); F_PICK=fnt(60,True); F_ODDS=fnt(34,True)
        F_LBL=fnt(20); F_STAT=fnt(26,True); F_DATE=fnt(22); F_GAME=fnt(24,True)
        F_BODY=fnt(22); F_ANHEAD=fnt(34,True)
        W=1080; PAD=52; CR=18
        alines=_tw.wrap(analysis,42) if analysis else []
        AH=60+len(alines)*34+40 if alines else 0
        C2H=max(AH,120) if alines else 0
        H=max(140+30+380+(30+C2H if C2H else 0)+80,1080)
        img=_PIL_Image.new("RGB",(W,H),C_BG); d=_PIL_Draw.Draw(img)
        def tw(t,f):
            bb=d.textbbox((0,0),t,font=f); return bb[2]-bb[0]
        def cx(t,f,y,c): d.text(((W-tw(t,f))//2,y),t,font=f,fill=c)
        def rr(xy,r,fill=None,ol=None,w=1):
            d.rounded_rectangle([xy[:2],xy[2:]],radius=r,fill=fill,outline=ol,width=w)
        # Try to download NBA logo from ESPN CDN
        def get_nba_logo(abb,size=72):
            esp=ESPN_ABB.get(abb.upper(),"")
            if not esp: return None
            try:
                req=_ur.Request(f"https://a.espncdn.com/i/teamlogos/nba/500/{esp}.png",
                                headers={"User-Agent":"Mozilla/5.0"})
                with _ur.urlopen(req,timeout=6) as r:
                    return _PIL_Image.open(_io.BytesIO(r.read())).convert("RGBA").resize((size,size),_PIL_Image.LANCZOS)
            except: return None
        # Top stripe + header
        d.rectangle([(0,0),(W,6)],fill=C_ACCENT)
        y=18; cx("LABOY PICKS",F_TITLE,y,C_ACCENT); y+=54
        cx("NBA",fnt(26),y,C_MUTED); y+=30
        cx(dstr,F_DATE,y,C_MUTED); y+=32
        d.rectangle([(0,y+8),(W,y+10)],fill=C_ACCENT); y+=26
        # Card 1
        C1X,C1Y=PAD,y; C1W=W-PAD*2; C1H=370
        rr((C1X,C1Y,C1X+C1W,C1Y+C1H),CR,fill=C_CARD,ol=RES_C,w=2)
        d.rounded_rectangle((C1X,C1Y,C1X+5,C1Y+C1H),radius=CR,fill=C_TEAM)
        iy=C1Y+22; cx(game,F_GAME,iy,C_MUTED); iy+=42
        # Team logos or colored circles
        for ii,(lx,abb) in enumerate([(W//2-160,away_abb),(W//2+88,home_abb)]):
            logo=get_nba_logo(abb)
            if logo:
                img.paste(logo,(lx,iy),logo)
            else:
                tc=h2r(TEAM_COLORS.get(abb,"#3b82f6"))
                d.ellipse([(lx,iy),(lx+72,iy+72)],fill=tc)
                ini=(TEAM_NICKNAMES.get(abb,abb)[:2]).upper()
                iw=tw(ini,F_LBL); d.text((lx+36-iw//2,iy+26),ini,font=F_LBL,fill=(255,255,255))
        cx("VS",fnt(22),iy+26,C_MUTED); iy+=86
        cx(pick_disp.upper(),F_PICK,iy,C_TEXT); iy+=72
        ob_w=tw(odds_s,F_ODDS); bx=(W-ob_w-48)//2
        rr((bx,iy,bx+ob_w+48,iy+46),10,fill=(8,40,22) if is_pos else (30,20,20),ol=C_GREEN if is_pos else C_RED,w=2)
        d.text((bx+24,iy+6),odds_s,font=F_ODDS,fill=C_GREEN if is_pos else C_RED); iy+=56
        # Stats grid
        SLBLS=["JUEGO","PICK","ODDS","BOOK"]
        SVALS=[game[:12] if game else "—",pick_disp[:12] if pick_disp else "—",odds_s,book[:8] if book else "—"]
        sgw=(C1W-32)//4; sx0=C1X+16; sy=C1Y+C1H-86
        for i,(lb,vl) in enumerate(zip(SLBLS,SVALS)):
            sx=sx0+i*sgw; rr((sx+2,sy,sx+sgw-4,sy+76),8,fill=C_STAT)
            lw=tw(lb,F_LBL); d.text((sx+(sgw-lw)//2,sy+6),lb,font=F_LBL,fill=C_MUTED)
            vw=tw(vl,F_STAT); d.text((sx+(sgw-vw)//2,sy+32),vl,font=F_STAT,
                fill=C_GREEN if (i==2 and is_pos) else C_TEXT)
        y=C1Y+C1H+22
        # Card 2 analysis
        if alines:
            C2X,C2Y=PAD,y; C2W=C1W
            rr((C2X,C2Y,C2X+C2W,C2Y+C2H),CR,fill=C_CARD,ol=C_BORDER,w=1)
            d.rounded_rectangle((C2X,C2Y,C2X+5,C2Y+C2H),radius=CR,fill=C_MUTED)
            ay=C2Y+18; cx("ANÁLISIS",F_ANHEAD,ay,C_ACCENT); ay+=48
            d.line([(C2X+16,ay),(C2X+C2W-16,ay)],fill=C_BORDER,width=1); ay+=12
            for line in alines:
                lw=tw(line,F_BODY); d.text(((W-lw)//2,ay),line,font=F_BODY,fill=C_TEXT); ay+=34
            y=C2Y+C2H+22
        # Footer
        d.rectangle([(0,H-6),(W,H)],fill=C_ACCENT)
        cx("Laboy Picks · NBA · dubclub.win",F_DATE,H-44,C_MUTED)
        fname=f"Laboy NBA Pick {pick_date} #{pick_id}.jpg"
        fpath=os.path.join(SCRIPT_DIR,fname)
        img.convert("RGB").save(fpath,"JPEG",quality=92)
        print(f"  🖼️  NBA Pick JPG: {fname}"); return fpath
    except Exception as _e:
        print(f"  ⚠️  _nba_pick_card_jpg: {_e}"); return None

def html_to_jpg(html_path, width=800, scale=4):
    """
    Convierte un HTML file a JPG.
    Intenta en orden:
      1. wkhtmltoimage  (disponible en Render/Linux con apt-get install wkhtmltopdf)
      2. Playwright     (disponible en desarrollo local)
    Retorna el path del JPG o None si ambos fallan.
    """
    import subprocess as _sp
    jpg_path = html_path.replace(".html", ".jpg")

    # ── 1. wkhtmltoimage ────────────────────────────────────────────
    try:
        _wk = _sp.run(["which", "wkhtmltoimage"], capture_output=True)
        if _wk.returncode == 0:
            _result = _sp.run([
                "wkhtmltoimage",
                "--width",  str(width),
                "--quality", "92",
                "--format",  "jpg",
                "--enable-local-file-access",
                "--javascript-delay", "500",
                "--no-stop-slow-scripts",
                "--quiet",
                html_path,
                jpg_path,
            ], capture_output=True, timeout=90)
            if _result.returncode == 0 and os.path.exists(jpg_path) and os.path.getsize(jpg_path) > 1000:
                print("  🖼️  JPG via wkhtmltoimage ✅")
                return jpg_path
            else:
                _err = _result.stderr.decode(errors="replace")
                print(f"  ⚠️  wkhtmltoimage exit={_result.returncode}: {_err[:200]}")
    except Exception as _we:
        print(f"  ⚠️  wkhtmltoimage error: {_we}")

    # ── 2. Playwright (fallback local) ──────────────────────────────
    try:
        from playwright.sync_api import sync_playwright as _pw_sp
    except ImportError:
        print("  💡 Para generar JPG instala: wkhtmltopdf  o  playwright")
        return None
    try:
        with open(html_path, "r", encoding="utf-8") as _f:
            html_content = _f.read()
        with _pw_sp() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(
                viewport={"width": width, "height": 900},
                device_scale_factor=scale
            )
            page.set_content(html_content, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            full_h = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": width, "height": max(900, full_h + 40)})
            page.screenshot(path=jpg_path, full_page=True, type="jpeg", quality=95)
            browser.close()
        print(f"  🖼️  JPG via Playwright ✅")
        return jpg_path
    except Exception as e:
        print(f"  ⚠️  html_to_jpg falló: {e}")
        return None

# ============================================================================
# PUBLISH TO GITHUB
# ============================================================================

def _publish_update_index(repo):
    """
    Regenera index.html (en blanco) y dashboard-{DASHBOARD_TOKEN}.html en el repo.
    """
    import glob as _glob

    # ── 1. .nojekyll — desactiva Jekyll para que GitHub Pages sirva manifest.json ─
    with open(os.path.join(repo, ".nojekyll"), "w") as f:
        f.write("")

    # ── 2. index.html — completamente en blanco ──────────────────────────────
    blank = (
        "<!DOCTYPE html>\n"
        '<html lang="es"><head><meta charset="UTF-8">'
        "<title>NBA Picks</title></head><body></body></html>\n"
    )
    with open(os.path.join(repo, "index.html"), "w", encoding="utf-8") as f:
        f.write(blank)

    # ── 2. dashboard privado ─────────────────────────────────────────────────
    files = sorted(
        _glob.glob(os.path.join(repo, "Laboy*.html")),
        key=os.path.getmtime, reverse=True
    )

    picks_files = [f for f in files if "Picks" in os.path.basename(f)]
    lines_files = [f for f in files if "Lines" in os.path.basename(f)]
    rec_files   = [f for f in files if "Record" in os.path.basename(f) or "Model" in os.path.basename(f)]

    def _file_links(flist, label):
        if not flist:
            return ""
        items = ""
        for fp in flist[:12]:
            name = os.path.basename(fp)
            enc  = name.replace(" ", "%20")
            date_m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
            dstr = date_m.group(1) if date_m else name
            items += f'<li><a href="{GITHUB_PAGES_URL}/{enc}" target="_blank">{dstr}</a></li>\n'
        return f"<h3>{label}</h3><ul>{items}</ul>"

    dash_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NBA Picks — Dashboard</title>
  <style>
    body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;max-width:600px;margin:0 auto}}
    h1{{color:#f8fafc;font-size:1.4rem;border-bottom:1px solid #334155;padding-bottom:10px}}
    h3{{color:#94a3b8;font-size:0.85rem;text-transform:uppercase;letter-spacing:.08em;margin-top:20px}}
    a{{color:#60a5fa;text-decoration:none}} a:hover{{text-decoration:underline}}
    ul{{list-style:none;padding:0;margin:0}}
    li{{padding:6px 0;border-bottom:1px solid #1e293b}}
    .ts{{font-size:0.75rem;color:#475569;margin-top:20px}}
  </style>
</head>
<body>
  <h1>🏀 NBA Picks — Dashboard</h1>
  {_file_links(picks_files, "Picks del Modelo")}
  {_file_links(lines_files, "Lines del Modelo")}
  {_file_links(rec_files,   "Model Record")}
  <p class="ts">Actualizado: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
</body>
</html>"""

    dash_path = os.path.join(repo, f"dashboard-{DASHBOARD_TOKEN}.html")
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(dash_html)
    print(f"  📋 Dashboard actualizado: dashboard-{DASHBOARD_TOKEN}.html")

    # ── manifest.json — para el dashboard principal laboy-picks ────────────
    manifest = {"sport": "NBA", "base_url": GITHUB_PAGES_URL, "files": []}
    for fp in files[:20]:
        base = os.path.basename(fp)
        enc  = base.replace(" ", "%20")
        ftype = "picks" if "Picks" in base else ("lines" if "Lines" in base else "record")
        fsubtype = ("model_record" if ("Model Card" in base or "Model Record" in base) else "my_record") if ftype == "record" else ""
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
        manifest["files"].append({
            "name": base, "url": f"{GITHUB_PAGES_URL}/{enc}",
            "type": ftype,
            "subtype": fsubtype,
            "date": date_m.group(1) if date_m else "",
        })
    # Imágenes de picks personales (NO incluir Record/Model Card JPGs)
    all_imgs = sorted(
        _glob.glob(os.path.join(repo, "Laboy Pick *.jpg")) +
        _glob.glob(os.path.join(repo, "Laboy Pick *.png")) +
        _glob.glob(os.path.join(repo, "Laboy NBA Pick *.jpg")),
        key=os.path.getmtime, reverse=True,
    )
    # Load NBA picks log for game names
    _nba_pick_game = {}
    try:
        with open(LOG_FILE, encoding="utf-8") as _lf:
            _nba_log_data = json.load(_lf)
        _nba_entries = _nba_log_data if isinstance(_nba_log_data, list) else _nba_log_data.get("picks", [])
        for _e in _nba_entries:
            _nba_pick_game[int(_e["id"])] = _e.get("game", "")
    except Exception:
        pass
    for ip in all_imgs[:30]:
        base     = os.path.basename(ip)
        enc      = base.replace(" ", "%20").replace("#", "%23")
        date_m   = re.search(r"(\d{4}-\d{2}-\d{2})", base)
        img_date = date_m.group(1) if date_m else ""
        _real_today_nba = datetime.now().strftime("%Y-%m-%d")
        img_subtype = "today" if img_date == _real_today_nba else ("archive" if img_date else "")
        id_m     = re.search(r"#(\d+)", base)
        img_game = _nba_pick_game.get(int(id_m.group(1)), "") if id_m else ""
        manifest["files"].append({
            "name": base, "url": f"{GITHUB_PAGES_URL}/{enc}",
            "type": "mypick_img", "subtype": img_subtype,
            "date": img_date, "game": img_game,
        })

    with open(os.path.join(repo, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def cmd_publish(html_paths):
    """
    Copia los HTMLs generados al repo local de GitHub Pages y hace push.
    Uso: python3 nba.py --picks --publish
         python3 nba.py --export-picks --publish

    Requiere:
      - Repo clonado localmente en GITHUB_PAGES_REPO (o env NBA_GITHUB_REPO)
      - git configurado con acceso push al repo
    """
    import shutil, glob as _glob, subprocess as _sp

    repo      = GITHUB_PAGES_REPO
    _gh_token = os.environ.get("LABOY_GITHUB_TOKEN", "")
    _clone_base = "https://github.com/laboywebsite-lgtm/nba-picks"
    _clone_url  = (f"https://{_gh_token}@github.com/laboywebsite-lgtm/nba-picks"
                   if _gh_token else _clone_base)

    if not os.path.isdir(repo):
        print(f"\n  📥 Repo nba-picks no encontrado. Clonando...")
        os.makedirs(os.path.dirname(repo), exist_ok=True)
        _r = _sp.run(["git", "clone", _clone_url, repo], capture_output=True, text=True)
        if _r.returncode != 0:
            print(f"\n  ❌ Error al clonar: {_r.stderr.strip()}")
            return
        print(f"  ✅ Repo clonado.\n")

    copied = []
    for hp in (html_paths or []):
        if hp and os.path.isfile(hp):
            dest = os.path.join(repo, os.path.basename(hp))
            shutil.copy2(hp, dest)
            copied.append(os.path.basename(hp))

    # Copiar imágenes de picks personales (JPG/PNG) — NO Record/Model Card JPGs
    for img_pat in ["Laboy Pick *.jpg", "Laboy Pick *.png", "Laboy NBA Pick *.jpg"]:
        for img in _glob.glob(os.path.join(SCRIPT_DIR, img_pat)):
            dest = os.path.join(repo, os.path.basename(img))
            shutil.copy2(img, dest)

    if not copied:
        print("\n  ⚠️  No hay HTMLs para publicar.")
        return

    # ── Regenerar index + dashboard ─────────────────────────────
    _publish_update_index(repo)

    # ── git add / commit / push ─────────────────────────────────
    def _git(args):
        r = subprocess.run(["git", "-C", repo] + args,
                           capture_output=True, text=True)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    _git(["add", "--all"])
    msg = f"🏀 NBA {TARGET_DATE} — {', '.join(copied)}"
    code, out, err = _git(["commit", "-m", msg])
    if code != 0 and "nothing to commit" in (out + err):
        print("\n  ℹ️  Sin cambios nuevos en el repo (archivos idénticos).")
    elif code != 0:
        print(f"\n  ❌ git commit falló: {err or out}")
        return

    # ── ¿El remoto ya tiene ramas? (repo podría estar vacío) ───────────────
    _, remote_refs, _ = _git(["ls-remote", "--heads", "origin"])
    has_remote_branch  = bool(remote_refs.strip())

    if has_remote_branch:
        print("  🔄 git pull --rebase...")
        code, out, err = _git(["pull", "--rebase"])
        if code != 0:
            print(f"\n  ❌ git pull falló: {err or out}")
            return

    # ── push (primer push necesita --set-upstream) ──────────────────────
    if has_remote_branch:
        code, out, err = _git(["push"])
    else:
        print("  🔄 git push (primer push al repo vacío)...")
        code, out, err = _git(["push", "--set-upstream", "origin", "main"])
        if code != 0:
            code, out, err = _git(["push", "--set-upstream", "origin", "master"])

    if code != 0:
        print(f"\n  ❌ git push falló: {err or out}")
        print(f"     Verifica que tienes acceso SSH/HTTPS configurado.")
        return

    print(f"\n  ✅ Publicado en GitHub Pages!")
    for fname in copied:
        encoded = fname.replace(" ", "%20")
        print(f"  🌐 {GITHUB_PAGES_URL}/{encoded}")
    print(f"\n  📱 Dashboard privado:")
    print(f"     {GITHUB_PAGES_URL}/dashboard-{DASHBOARD_TOKEN}.html")
    print(f"     (Guarda este enlace en Safari / iPhone)")
    print()

# ============================================================================
# EXTENDED ANALYTICS
# ============================================================================

def analyze_team_trends(team_abb, num_picks=20):
    """Analyze win/loss trends for a specific team."""
    picks = _load_picks()

    team_picks = [p for p in picks if team_abb in p.get('game', '')]
    recent = sorted(team_picks, key=lambda x: x['date'], reverse=True)[:num_picks]

    if not recent:
        print(f"No picks found for {team_abb}.")
        return

    wins = sum(1 for p in recent if p.get('result') == 'W')
    losses = sum(1 for p in recent if p.get('result') == 'L')
    pnl = sum(p.get('pnl', 0) for p in recent if p.get('result'))

    print(f"\n{TEAM_ABB.get(team_abb, team_abb)} Trends (last {len(recent)} picks)")
    print(f"Record: {wins}-{losses}")
    print(f"P&L: {pnl:+.2f}\n")

    if tabulate:
        rows = []
        for p in reversed(recent):
            status = p.get('result', '?')
            pnl_val = p.get('pnl', 0) if p.get('result') else 0
            rows.append([
                p['date'],
                p['pick'],
                f"{p['odds']:+d}",
                status,
                f"{pnl_val:+.2f}" if pnl_val else "-"
            ])
        print(tabulate(rows, headers=['Date', 'Pick', 'Odds', 'Result', 'P&L'], tablefmt='grid'))
    print()

def compare_model_to_market(games, odds, stats):
    """Compare model predictions vs market consensus."""
    print("\n" + "="*80)
    print("MODEL VS MARKET COMPARISON")
    print("="*80 + "\n")

    comparisons = []
    for game in games:
        away = game['away_abb']
        home = game['home_abb']
        model = compute_game(away, home, stats)

        # Get market consensus
        market_odds = odds.get(f"{away}_{home}", {})
        if not market_odds.get('bookmakers'):
            continue

        # Extract average moneyline from bookmakers
        ml_spreads = []
        for bookie in market_odds.get('bookmakers', []):
            for market in bookie.get('markets', []):
                if market['key'] == 'moneyline':
                    for outcome in market['outcomes']:
                        ml_spreads.append(outcome['price'])

        if ml_spreads:
            avg_ml = sum(ml_spreads) / len(ml_spreads)
            comparisons.append({
                'game': f"{away}@{home}",
                'model_spread': model['spread'],
                'market_ml': avg_ml,
                'model_wp_home': model['wp_h'],
                'agreement': "Yes" if (model['spread'] > 0 and avg_ml < 0) or (model['spread'] < 0 and avg_ml > 0) else "No"
            })

    if comparisons and tabulate:
        rows = []
        for c in comparisons:
            rows.append([
                c['game'],
                f"{c['model_spread']:+.1f}",
                f"{c['market_ml']:+d}",
                f"{c['model_wp_home']:.1f}%",
                c['agreement']
            ])
        print(tabulate(rows, headers=['Game', 'Model Spread', 'Market ML', 'Model WP', 'Agreement'], tablefmt='grid'))
    print()

def export_daily_picks_card(date_str, picks):
    """
    Genera 'Laboy NBA Model Card {DATE}.html' con los picks del modelo del día,
    incluyendo badges de resultado (W/L/P/PENDING) en estilo MLB/BSN.
    picks: lista de dicts {game, pick, odds, result, score, color}
    """
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    if not picks:
        picks = []

    # Stats summary
    w  = sum(1 for p in picks if p.get("result") == "W")
    l  = sum(1 for p in picks if p.get("result") == "L")
    pu = sum(1 for p in picks if p.get("result") == "P")
    pend = sum(1 for p in picks if p.get("result") not in ("W","L","P"))
    total = w + l + pu
    win_pct = f"{w/total*100:.0f}%" if total else "—"
    win_col = "#22c55e" if w >= l else "#ef4444"

    cards_html = ""
    for p in picks:
        result  = p.get("result") or "⏳"
        color   = p.get("color", "#f07820")
        game    = esc(p.get("game", ""))
        pick_tx = esc(p.get("pick", ""))
        odds_tx = esc(str(p.get("odds", "—")))
        sc_str  = esc(p.get("score", "—"))

        if result == "W":
            badge   = '<span style="background:#22c55e22;color:#22c55e;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">✅ WIN</span>'
            card_bg = "background:linear-gradient(135deg,#0d1f14 0%,#222222 60%)"
        elif result == "L":
            badge   = '<span style="background:#ef444422;color:#ef4444;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">❌ LOSS</span>'
            card_bg = "background:linear-gradient(135deg,#1f0d0d 0%,#222222 60%)"
        elif result == "P":
            badge   = '<span style="background:#94a3b822;color:#94a3b8;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">— PUSH</span>'
            card_bg = "background:linear-gradient(135deg,#14161a 0%,#222222 60%)"
        else:
            badge   = '<span style="background:#f0782022;color:#f07820;border-radius:6px;padding:3px 10px;font-size:0.85rem;font-weight:700">⏳ PENDING</span>'
            card_bg = ""
            color   = "#f07820"

        # Logo: total vs equipo
        is_total = re.match(r'^(?:OVER|UNDER|O|U)\s+[\d.]+', pick_tx, re.I)
        if is_total:
            logo_h = _nba_over_under_logo(52)
        else:
            team_nick = pick_tx.split()[0].upper()
            team_abb  = {v.upper(): k for k, v in TEAM_NICKNAMES.items()}.get(team_nick, team_nick)
            esp       = ESPN_ABB.get(team_abb, team_abb.lower())
            logo_h    = (f'<img src="https://a.espncdn.com/i/teamlogos/nba/500/{esp}.png" '
                         f'alt="{team_abb}" width="52" height="52" style="object-fit:contain" '
                         f'onerror="this.style.display=\'none\'">')

        cards_html += f"""
        <div class="pick-card" style="border-left:4px solid {color};{card_bg}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <div style="font-size:0.72rem;color:var(--muted);font-weight:500">{game}</div>
            {badge}
          </div>
          <div class="teams-row" style="margin-bottom:8px">
            {logo_h}
            <div class="pick-main">
              <div class="pick-label" style="font-size:1.1rem">
                {pick_tx}
                <span class="odds-badge">{odds_tx}</span>
              </div>
              <div style="font-size:0.75rem;color:#94a3b8;margin-top:4px">Score: {sc_str}</div>
            </div>
          </div>
        </div>
"""

    pend_s = f" · {pend} pending" if pend else ""
    summary_html = f"""
    <div style="background:#1a1a1a;border-radius:12px;padding:16px;margin-top:24px;text-align:center">
      <div style="font-size:0.7rem;color:var(--muted);letter-spacing:1px;margin-bottom:6px">RESUMEN DEL DÍA</div>
      <div style="font-size:1.5rem;font-weight:900;color:{win_col}">{w}W · {l}L · {pu}P{pend_s}</div>
      <div style="font-size:1rem;color:var(--muted);margin-top:4px">Win% {win_pct}</div>
    </div>
"""

    try:
        dt   = datetime.strptime(date_str, "%Y-%m-%d")
        dstr = dt.strftime("%A, %B %d").upper()
        yr   = dt.strftime("%Y")
    except Exception:
        dstr = date_str.upper()
        yr   = date_str[:4]

    body = f'<div class="section-title">🏀 MODELO — NBA</div>\n{cards_html}\n{summary_html}'
    html = _nba_html_wrap(f"Laboy NBA Model Card {date_str}", "NBA", dstr, yr, body)

    filename = os.path.join(SCRIPT_DIR, f"Laboy NBA Model Card {date_str}.html")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  📄 Model Card: {os.path.basename(filename)}")

    try:
        jpg = html_to_jpg(filename)
        if jpg:
            print(f"  🖼️  JPG: {os.path.basename(jpg)}")
    except Exception:
        pass

    return filename

def get_odds_movement(game_id, market_type='moneyline'):
    """Track odds movement for a specific game (would require historical data)."""
    # This is a placeholder for real odds movement tracking
    # In production, would connect to historical odds database
    pass

def calculate_implied_probability(american_odds):
    """Convert American odds to implied probability."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)

def calculate_ev(model_prob, market_odds):
    """Calculate expected value of a bet."""
    market_prob = calculate_implied_probability(market_odds)

    if market_odds > 0:
        ev = (model_prob * (market_odds + 100)) - 100
    else:
        ev = (model_prob * 100) + abs(market_odds) - 100

    return ev / 100

def generate_matchup_report(away_abb, home_abb, stats):
    """Generate detailed matchup report."""
    a_stats = stats.get(away_abb, {})
    h_stats = stats.get(home_abb, {})
    model = compute_game(away_abb, home_abb, stats)

    print("\n" + "="*70)
    print(f"MATCHUP REPORT: {away_abb} @ {home_abb}")
    print("="*70)

    print(f"\n{TEAM_ABB.get(away_abb, away_abb)} (Away)")
    print(f"  ORTG: {a_stats.get('ortg', LEAGUE_AVG_ORTG):.1f} | DRTG: {a_stats.get('drtg', LEAGUE_AVG_DRTG):.1f}")
    print(f"  PACE: {a_stats.get('pace', LEAGUE_AVG_PACE):.1f} | Net: {a_stats.get('net', 0):.1f}")

    print(f"\n{TEAM_ABB.get(home_abb, home_abb)} (Home)")
    print(f"  ORTG: {h_stats.get('ortg', LEAGUE_AVG_ORTG):.1f} | DRTG: {h_stats.get('drtg', LEAGUE_AVG_DRTG):.1f}")
    print(f"  PACE: {h_stats.get('pace', LEAGUE_AVG_PACE):.1f} | Net: {h_stats.get('net', 0):.1f}")

    print("\nMODEL PROJECTIONS:")
    print(f"  {away_abb}: {model['pts_a']} pts | Win%: {model['wp_a']}%")
    print(f"  {home_abb}: {model['pts_h']} pts | Win%: {model['wp_h']}%")
    print(f"  Total: {model['total']} | Spread: {home_abb} {model['spread']:+.1f}")
    print()

def cmd_matchup(away_abb, home_abb):
    """Show detailed matchup report."""
    stats = load_nba_stats()
    if not stats:
        print("No stats cached. Run: python3 nba.py --refresh")
        return
    generate_matchup_report(away_abb, home_abb, stats)

def cmd_trends(team_abb):
    """Show team trends."""
    analyze_team_trends(team_abb)

def export_season_summary():
    """Export season summary with all picks and stats."""
    picks = _load_picks()

    if not picks:
        print("No picks to summarize.")
        return

    # Group by month
    monthly = {}
    for p in picks:
        date = p.get('date', '2026-01-01')
        month = date[:7]  # YYYY-MM
        if month not in monthly:
            monthly[month] = {'wins': 0, 'losses': 0, 'pushes': 0, 'pnl': 0, 'picks': []}
        monthly[month]['picks'].append(p)
        if p.get('result') == 'W':
            monthly[month]['wins'] += 1
        elif p.get('result') == 'L':
            monthly[month]['losses'] += 1
        else:
            monthly[month]['pushes'] += 1
        monthly[month]['pnl'] += p.get('pnl', 0)

    print("\n" + "="*80)
    print("SEASON SUMMARY BY MONTH")
    print("="*80)

    if tabulate:
        rows = []
        for month in sorted(monthly.keys()):
            m = monthly[month]
            total = m['wins'] + m['losses'] + m['pushes']
            win_rate = (m['wins'] / (m['wins'] + m['losses']) * 100) if (m['wins'] + m['losses']) > 0 else 0
            rows.append([
                month,
                f"{m['wins']}-{m['losses']}-{m['pushes']}",
                f"{win_rate:.1f}%",
                f"{m['pnl']:+.2f}",
                total
            ])
        print(tabulate(rows, headers=['Month', 'Record', 'Win%', 'P&L', 'Picks'], tablefmt='grid'))
    print()

def validate_game_outcome(game_id, away_score, home_score):
    """Validate and update a game outcome if scores differ."""
    picks = _load_picks()

    for p in picks:
        if game_id in p.get('game', ''):
            # Update result based on scores
            pick_team = p.get('pick')
            away_abb = game_id.split()[0]
            home_abb = game_id.split('@')[-1] if '@' in game_id else ""

            if pick_team == away_abb:
                result = 'W' if away_score > home_score else ('L' if away_score < home_score else 'P')
            elif pick_team == home_abb:
                result = 'W' if home_score > away_score else ('L' if home_score < away_score else 'P')
            else:
                continue

            p['result'] = result

            # Calculate PNL
            if result == 'W':
                if p['odds'] > 0:
                    p['pnl'] = p['stake'] * (p['odds'] / 100)
                else:
                    p['pnl'] = p['stake'] * (100 / abs(p['odds']))
            elif result == 'L':
                p['pnl'] = -p['stake']
            else:  # Push
                p['pnl'] = 0

    _save_picks(picks)
    print(f"Updated outcomes for {game_id}")

def get_season():
    """Detect current NBA season."""
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[2:]}"
    else:
        return f"{now.year - 1}-{str(now.year)[2:]}"

def export_picks_to_csv():
    """Export picks log to CSV."""
    picks = _load_picks()

    if not picks:
        print("No picks to export.")
        return

    csv_path = os.path.join(SCRIPT_DIR, "nba_picks_export.csv")

    import csv
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Date', 'Game', 'Pick', 'Odds', 'Book', 'Stake', 'Result', 'P&L', 'Analysis'])
        writer.writeheader()
        for p in sorted(picks, key=lambda x: x['date']):
            writer.writerow({
                'Date': p['date'],
                'Game': p['game'],
                'Pick': p['pick'],
                'Odds': p['odds'],
                'Book': p['book'],
                'Stake': p['stake'],
                'Result': p.get('result', ''),
                'P&L': p.get('pnl', ''),
                'Analysis': p.get('analysis', '')
            })

    print(f"Exported: {csv_path}")

def import_picks_from_csv(csv_path):
    """Import picks from CSV file."""
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return

    import csv
    picks = _load_picks()
    max_id = max([p.get('id', 0) for p in picks] + [0])

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            max_id += 1
            picks.append({
                'id': max_id,
                'date': row['Date'],
                'game': row['Game'],
                'pick': row['Pick'],
                'odds': int(row['Odds']),
                'book': row['Book'],
                'stake': float(row['Stake']),
                'result': row.get('Result') or None,
                'pnl': float(row['P&L']) if row.get('P&L') else None,
                'analysis': row.get('Analysis', '')
            })

    _save_picks(picks)
    print(f"Imported picks from {csv_path}")

def validate_stats_integrity(stats):
    """Check for unusual or invalid stats."""
    issues = []

    for team, s in stats.items():
        ortg = s.get('ortg', 0)
        drtg = s.get('drtg', 0)
        pace = s.get('pace', 0)

        if ortg > 130 or ortg < 100:
            issues.append(f"{team}: Unusual ORTG ({ortg})")
        if drtg > 130 or drtg < 100:
            issues.append(f"{team}: Unusual DRTG ({drtg})")
        if pace > 105 or pace < 93:
            issues.append(f"{team}: Unusual PACE ({pace})")

    if issues:
        print("\nData Integrity Warnings:")
        for issue in issues:
            print(f"  ⚠ {issue}")
    else:
        print("\nStats look valid.")

def cmd_validate():
    """Validate cached stats."""
    stats = load_nba_stats()
    if not stats:
        print("No stats cached.")
        return
    validate_stats_integrity(stats)

# ============================================================================
# HELP
# ============================================================================

def show_help():
    """Show help text."""
    print("""
╔════════════════════════════════════════════════════════════════╗
║           LABOY NBA SPORTS BETTING ANALYTICS TOOL              ║
╚════════════════════════════════════════════════════════════════╝

USAGE:
  python3 nba.py                            Show today's games with model lines
  python3 nba.py 2026-04-12                 Show games for specific date
  python3 nba.py --refresh                  Fetch fresh BBRef stats (ORTG/DRTG/PACE)
  python3 nba.py --stats                    Show all team stats
  python3 nba.py --lines                    Model lines for today
  python3 nba.py 2026-04-15 --lines         Model lines for a specific date
  python3 nba.py --picks                    EV+ picks vs market odds
  python3 nba.py --export-html              Generate Laboy NBA Picks HTML
  python3 nba.py --grade-picks [FILE|URL]   Grade picks from HTML or URL
  python3 nba.py --set-stats TEAM ORTG DRTG PACE  Set team stats manually

SCHEDULE (cuando ESPN no tiene los juegos):
  python3 nba.py --add-game AWAY HOME 'HORA'   Agrega juego manual
  python3 nba.py --list-games                   Lista juegos manuales de hoy
  python3 nba.py --remove-game AWAY HOME        Elimina juego manual
  Ej: python3 nba.py --add-game BOS NYK '7:30 PM ET'

PICK TRACKING:
  python3 nba.py --log                 Log a personal pick
  python3 nba.py --grade N W|L|P       Grade a logged pick
  python3 nba.py --remove N            Remove a logged pick
  python3 nba.py --record              Show record with running balance
  python3 nba.py --feedback            Performance analysis + AI
  python3 nba.py --export-record       Export personal record card

ANALYSIS & REPORTS:
  python3 nba.py --matchup AWAY HOME   Show detailed matchup report
  python3 nba.py --trends TEAM         Show team win/loss trends
  python3 nba.py --compare             Compare model vs market odds
  python3 nba.py --summary             Season summary by month
  python3 nba.py --validate            Validate stats integrity
  python3 nba.py --export-csv          Export picks to CSV
  python3 nba.py --import-csv FILE     Import picks from CSV

PUBLISHING:
  python3 nba.py --publish [FILE ...]  Publish to GitHub Pages

INFO:
  python3 nba.py --help                Show this help text

ENVIRONMENT:
  ODDS_API_KEY                         The Odds API key (optional)
  ANTHROPIC_API_KEY                    Claude API key for AI feedback (optional)
""")

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point."""
    stats = load_nba_stats()

    # Warn if stats not cached (doesn't block, just informational)
    if not stats and "--refresh" not in sys.argv and "--set-stats" not in sys.argv:
        print(f"  ⚠️  Stats no cacheadas. Corre:  python3 nba.py --refresh")

    # Filter out the date arg so we can parse the command flag cleanly
    non_date_args = [a for a in sys.argv[1:] if not re.match(r"^\d{4}-\d{2}-\d{2}$", a)]
    PUBLISH_MODE  = "--publish" in non_date_args

    if not non_date_args or non_date_args == ["--publish"]:
        # Only a date was passed (or nothing) — show lines + export HTML
        games = get_nba_schedule(TARGET_DATE)
        if games:
            display_lines(games, {}, stats)
            html_file = export_lines_html(games, {}, stats, TARGET_DATE)
            print(f"  📄 Lines HTML: {os.path.basename(html_file)}")
            if PUBLISH_MODE:
                cmd_publish([html_file])
        return

    cmd = non_date_args[0]

    if cmd == '--help':
        show_help()

    elif cmd == '--refresh':
        cmd_refresh_stats()

    elif cmd == '--stats':
        show_stats(stats)

    elif cmd in ('--lines', '--default'):
        games         = get_nba_schedule(TARGET_DATE)
        inj_entries   = _load_nba_injuries()
        inj_impact    = compute_nba_injury_impact(inj_entries)
        if inj_impact:
            print(f"  🏥 Injury impact activo: {len(inj_impact)} equipos afectados")
        if games:
            display_lines(games, {}, stats, injury_impact=inj_impact)
            html_file = export_lines_html(games, {}, stats, TARGET_DATE, injury_impact=inj_impact)
            _write_lines_json(games, stats, TARGET_DATE, injury_impact=inj_impact)
            print(f"  📄 Lines HTML: {os.path.basename(html_file)}")
            if PUBLISH_MODE:
                cmd_publish([html_file])

    elif cmd == '--picks':
        games       = get_nba_schedule(TARGET_DATE)
        odds        = get_market_odds()
        # Siempre buscar el PDF más reciente de la NBA al correr --picks
        print("  🏥 Actualizando injury report...")
        _fresh_inj = fetch_nba_injuries(TARGET_DATE)
        if _fresh_inj:
            _save_nba_injuries(_fresh_inj)
            inj_entries = _fresh_inj
        else:
            inj_entries = _load_nba_injuries()  # fallback al cache
        inj_impact  = compute_nba_injury_impact(inj_entries)
        if inj_impact:
            print(f"  🏥 Injury impact activo: {len(inj_impact)} equipos afectados")
        if games:
            picks = show_picks(games, odds, stats, injury_impact=inj_impact)
            if picks:
                _model_picks_save_today(picks, TARGET_DATE)
            _write_lines_json(games, stats, TARGET_DATE, injury_impact=inj_impact)
            html_file = export_picks_html(games, odds, stats, TARGET_DATE, injury_impact=inj_impact)
            print(f"  📄 Picks HTML: {os.path.basename(html_file)}")
            if PUBLISH_MODE:
                cmd_publish([html_file])

    elif cmd == '--export-html':
        games       = get_nba_schedule(TARGET_DATE)
        odds        = get_market_odds()
        inj_entries = _load_nba_injuries()
        inj_impact  = compute_nba_injury_impact(inj_entries)
        if games:
            lines_html = export_lines_html(games, odds, stats, TARGET_DATE, injury_impact=inj_impact)
            picks_html = export_picks_html(games, odds, stats, TARGET_DATE, injury_impact=inj_impact)
            print(f"  📄 Lines HTML: {os.path.basename(lines_html)}")
            print(f"  📄 Picks HTML: {os.path.basename(picks_html)}")
            if PUBLISH_MODE:
                cmd_publish([lines_html, picks_html])

    elif cmd == '--ir':
        refresh = 'refresh' in non_date_args[1:]
        cmd_ir_nba(refresh=refresh)

    elif cmd == '--grade-picks':
        # Accept explicit source after flag, but skip date args
        remaining = [a for a in non_date_args[1:] if not a.startswith("-")]
        source = remaining[0] if remaining else f"Laboy NBA Picks {TARGET_DATE}.html"
        cmd_grade_picks(source)

    elif cmd == '--set-stats':
        rest = non_date_args[1:]
        if len(rest) < 4:
            print("  Uso: python3 nba.py --set-stats TEAM ORTG DRTG PACE")
            return
        cmd_set_stats(rest[0], rest[1], rest[2], rest[3])

    # ── Manual game management ──────────────────────────────────────────────
    elif cmd == '--add-game':
        cmd_add_game_nba()

    elif cmd == '--remove-game':
        cmd_remove_game_nba()

    elif cmd == '--list-games':
        cmd_list_games_nba()

    # ── Playoff series game log (manual injection cuando ESPN no responde) ──
    elif cmd == '--add-series-game':
        cmd_add_series_game()

    elif cmd == '--list-series-games':
        cmd_list_series_games()

    # ── Manual market lines (cuando el API no tiene el juego) ──────────────
    elif cmd == '--set-market':
        cmd_set_market()

    # ── Pick tracking ───────────────────────────────────────────────────────
    elif cmd == '--log':
        cmd_log_pick()

    elif cmd == '--export-log':
        cmd_export_log_nba()

    elif cmd == '--grade':
        rest = non_date_args[1:]
        if len(rest) < 2:
            print("  ❌ Uso: python3 nba.py --grade IDX W|L|P")
            print("     Ejemplo: python3 nba.py --grade 0 W")
            print("\n  IDX = número del pick (ver python3 nba.py --record)")
            print("  W=Win  L=Loss  P=Push")
            return
        try:
            idx = int(rest[0])
            res = rest[1].upper()
            assert res in ("W","L","P")
        except (ValueError, AssertionError):
            print("  ❌ Uso: python3 nba.py --grade IDX W|L|P")
            return
        # Calificar y regenerar card
        entry = cmd_grade_pick(idx, res)
        if entry:
            try:
                export_log_pick_html(entry)
            except Exception as _ge:
                print(f"  ⚠️  No se pudo regenerar card: {_ge}")

    elif cmd == '--remove':
        rest = non_date_args[1:]
        if not rest:
            print("  Uso: python3 nba.py --remove N")
            return
        cmd_remove_pick(int(rest[0]))

    elif cmd == '--record':
        cmd_record()

    elif cmd == '--feedback':
        cmd_feedback()

    elif cmd == '--export-record':
        rec_html = export_record_card(TARGET_DATE)
        if PUBLISH_MODE and rec_html:
            cmd_publish([rec_html])

    elif cmd == '--matchup':
        rest = non_date_args[1:]
        if len(rest) < 2:
            print("  Uso: python3 nba.py --matchup AWAY HOME")
            return
        cmd_matchup(rest[0], rest[1])

    elif cmd == '--trends':
        rest = non_date_args[1:]
        if not rest:
            print("  Uso: python3 nba.py --trends TEAM")
            return
        cmd_trends(rest[0])

    elif cmd == '--compare':
        games = get_nba_schedule(TARGET_DATE)
        odds  = get_market_odds()
        if games:
            compare_model_to_market(games, odds, stats)

    elif cmd == '--summary':
        export_season_summary()

    elif cmd == '--validate':
        cmd_validate()

    elif cmd == '--export-csv':
        export_picks_to_csv()

    elif cmd == '--import-csv':
        rest = non_date_args[1:]
        if not rest:
            print("  Uso: python3 nba.py --import-csv FILE")
            return
        import_picks_from_csv(rest[0])

    elif cmd == '--publish':
        rest = non_date_args[1:]
        cmd_publish(rest)

    elif cmd == '--add-injury':
        cmd_add_injury_nba()

    elif cmd == '--remove-injury':
        cmd_remove_injury_nba()

    else:
        print(f"  Comando desconocido: {cmd}")
        print("  Corre:  python3 nba.py --help")

# ============================================================================
# UTILITY FUNCTIONS & HELPERS
# ============================================================================

def normalize_team_name(name):
    """Normalize team name to 3-letter abbreviation."""
    name = name.upper().strip()
    if name in TEAM_ABB:
        return name
    for abb, full_name in TEAM_ABB.items():
        if name in full_name.upper():
            return abb
    return name

def get_team_full_name(abb):
    """Get full team name from abbreviation."""
    return TEAM_ABB.get(abb, abb)

def format_odds(odds):
    """Format odds with +/- sign."""
    if odds > 0:
        return f"+{odds}"
    else:
        return str(odds)

def format_percentage(value):
    """Format percentage with 1 decimal."""
    return f"{value:.1f}%"

def format_money(value):
    """Format dollar amount."""
    return f"${value:,.2f}"

def get_team_color(team_abb):
    """Get brand color for team."""
    return TEAM_COLORS.get(team_abb, '#94a3b8')

def validate_date_format(date_str):
    """Check if date is in YYYY-MM-DD format."""
    return bool(re.match(r'\d{4}-\d{2}-\d{2}', date_str))

def date_is_valid(date_str):
    """Validate that date exists."""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def days_ago(n):
    """Get date string from n days ago."""
    return (datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d')

def upcoming_dates(n):
    """Get list of next n dates."""
    dates = []
    for i in range(n):
        dates.append((datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d'))
    return dates

def calculate_kelly_criterion(win_prob, avg_odds):
    """Calculate Kelly criterion bet sizing."""
    # Kelly % = (bp - q) / b, where p=win prob, q=loss prob, b=odds ratio
    if avg_odds > 0:
        b = avg_odds / 100
    else:
        b = 100 / abs(avg_odds)

    p = win_prob / 100
    q = 1 - p

    kelly = (b * p - q) / b if b > 0 else 0
    return max(0, kelly)  # Never negative

def calculate_roi_per_unit(pnl, risk):
    """Calculate ROI percentage per unit risked."""
    if risk == 0:
        return 0
    return (pnl / risk) * 100

def find_best_odds(game_key, market_type='moneyline'):
    """Find best available odds from all bookmakers (requires historical data)."""
    # This would integrate with odds comparison APIs
    pass

def get_game_status(game_id):
    """Get current status of a game."""
    games = get_nba_schedule(datetime.now().strftime('%Y-%m-%d'), silent=True)
    for g in games:
        if g['game_id'] == game_id:
            return 'Scheduled'
    return 'Unknown'

def calculate_closing_line_value(model_line, closing_odds):
    """Calculate closing line value vs model prediction."""
    # CLV shows if we consistently get favorable odds
    pass

def track_off_season():
    """Determine if we're in off-season."""
    now = datetime.now()
    # NBA season is Oct-Jun
    if now.month >= 7 and now.month <= 9:
        return True
    return False

def get_recent_picks(days=7):
    """Get picks from last N days."""
    picks = _load_picks()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return [p for p in picks if p['date'] >= cutoff]

def get_favorite_picks():
    """Get all picks on favorites (negative spread)."""
    picks = _load_picks()
    return [p for p in picks if p.get('odds', 0) < 0]

def get_underdog_picks():
    """Get all picks on underdogs (positive spread)."""
    picks = _load_picks()
    return [p for p in picks if p.get('odds', 0) > 0]

def picks_by_book():
    """Group picks by sportsbook."""
    picks = _load_picks()
    by_book = {}
    for p in picks:
        book = p.get('book', 'Unknown')
        if book not in by_book:
            by_book[book] = []
        by_book[book].append(p)
    return by_book

def best_performing_book():
    """Find which book has best ROI."""
    by_book = picks_by_book()
    results = {}

    for book, picks in by_book.items():
        total_pnl = sum(p.get('pnl', 0) for p in picks if p.get('result'))
        total_risk = sum(p['stake'] for p in picks if p.get('result'))
        roi = (total_pnl / total_risk * 100) if total_risk > 0 else 0
        results[book] = {'pnl': total_pnl, 'roi': roi, 'picks': len(picks)}

    return results

def streak_analysis():
    """Analyze winning/losing streaks."""
    picks = sorted(_load_picks(), key=lambda x: x['date'])

    if not picks:
        return None

    current_streak = 0
    max_streak = 0
    streak_type = None

    for p in picks:
        result = p.get('result')
        if result in ['W', 'L']:
            if streak_type is None:
                streak_type = result
                current_streak = 1
            elif result == streak_type:
                current_streak += 1
            else:
                max_streak = max(max_streak, current_streak)
                streak_type = result
                current_streak = 1

    max_streak = max(max_streak, current_streak)

    return {
        'current_streak': current_streak,
        'max_streak': max_streak,
        'current_type': streak_type
    }

def variance_by_odds_range():
    """Analyze performance by odds brackets."""
    picks = _load_picks()

    ranges = {
        'heavy_fav': {'min': -400, 'max': -200, 'picks': [], 'wr': 0},
        'slight_fav': {'min': -200, 'max': -101, 'picks': [], 'wr': 0},
        'slight_dog': {'min': 100, 'max': 200, 'picks': [], 'wr': 0},
        'heavy_dog': {'min': 201, 'max': 600, 'picks': [], 'wr': 0},
    }

    for p in picks:
        odds = p.get('odds', 0)
        for key, r in ranges.items():
            if r['min'] <= odds <= r['max']:
                r['picks'].append(p)

    for key, r in ranges.items():
        if r['picks']:
            wins = sum(1 for p in r['picks'] if p.get('result') == 'W')
            total = sum(1 for p in r['picks'] if p.get('result') in ['W', 'L'])
            r['wr'] = (wins / total * 100) if total > 0 else 0

    return ranges

def cmd_streak_analysis():
    """Show streak information."""
    streak = streak_analysis()
    if not streak:
        print("No picks to analyze.")
        return

    print("\n" + "="*60)
    print("STREAK ANALYSIS")
    print("="*60)
    print(f"Current Streak: {streak['current_streak']} {streak['current_type']}'s")
    print(f"Max Streak: {streak['max_streak']}")
    print()

def cmd_variance_analysis():
    """Show performance by odds range."""
    ranges = variance_by_odds_range()

    print("\n" + "="*60)
    print("PERFORMANCE BY ODDS RANGE")
    print("="*60 + "\n")

    if tabulate:
        rows = []
        for key, data in ranges.items():
            if data['picks']:
                rows.append([
                    key.replace('_', ' ').title(),
                    f"{data['min']} to {data['max']}",
                    len(data['picks']),
                    f"{data['wr']:.1f}%"
                ])
        if rows:
            print(tabulate(rows, headers=['Range', 'Odds', 'Picks', 'Win%'], tablefmt='grid'))
    print()

def cmd_book_analysis():
    """Show performance by sportsbook."""
    results = best_performing_book()

    print("\n" + "="*60)
    print("PERFORMANCE BY SPORTSBOOK")
    print("="*60 + "\n")

    if tabulate:
        rows = []
        for book, stats in results.items():
            rows.append([
                book,
                stats['picks'],
                f"{stats['pnl']:+.2f}",
                f"{stats['roi']:+.1f}%"
            ])
        print(tabulate(rows, headers=['Book', 'Picks', 'P&L', 'ROI'], tablefmt='grid'))
    print()

def cmd_recent_picks(days=7):
    """Show recent picks from last N days."""
    picks = get_recent_picks(days)

    print(f"\nPicks from last {days} days: {len(picks)}\n")

    if picks and tabulate:
        rows = []
        for p in sorted(picks, key=lambda x: x['date'], reverse=True):
            result = p.get('result', '?')
            rows.append([
                p['date'],
                p['game'],
                p['pick'],
                f"{p['odds']:+d}",
                result,
                f"{p.get('pnl', 0):+.2f}" if result != '?' else "-"
            ])
        print(tabulate(rows, headers=['Date', 'Game', 'Pick', 'Odds', 'Result', 'P&L'], tablefmt='grid'))
    print()

def export_detailed_report():
    """Export comprehensive analysis report."""
    picks = _load_picks()

    if not picks:
        print("No picks to report on.")
        return

    report = []
    report.append("="*80)
    report.append("DETAILED PICK ANALYSIS REPORT")
    report.append("="*80)
    report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Total Picks: {len(picks)}")

    # Basic stats
    graded = [p for p in picks if p.get('result')]
    wins = sum(1 for p in graded if p.get('result') == 'W')
    losses = sum(1 for p in graded if p.get('result') == 'L')
    pushes = sum(1 for p in graded if p.get('result') == 'P')
    total_pnl = sum(p.get('pnl', 0) for p in graded)
    total_risk = sum(p['stake'] for p in graded)

    report.append(f"\nRECORD: {wins}-{losses}-{pushes}")
    report.append(f"P&L: {total_pnl:+.2f}")
    report.append(f"ROI: {(total_pnl/total_risk*100) if total_risk > 0 else 0:+.2f}%")

    # Streaks
    streak = streak_analysis()
    if streak:
        report.append(f"\nStreaks:")
        report.append(f"  Current: {streak['current_streak']} {streak['current_type']}'s")
        report.append(f"  Best: {streak['max_streak']}")

    # By book
    report.append(f"\n\nBy Sportsbook:")
    results = best_performing_book()
    for book, stats in results.items():
        report.append(f"  {book}: {stats['picks']} picks, {stats['pnl']:+.2f} P&L, {stats['roi']:+.1f}% ROI")

    # By odds range
    report.append(f"\n\nBy Odds Range:")
    ranges = variance_by_odds_range()
    for key, data in ranges.items():
        if data['picks']:
            report.append(f"  {key}: {data['wr']:.1f}% WR on {len(data['picks'])} picks")

    report_text = '\n'.join(report)
    print(report_text)

    # Save to file
    report_path = os.path.join(SCRIPT_DIR, "detailed_report.txt")
    with open(report_path, 'w') as f:
        f.write(report_text)
    print(f"\nSaved: {report_path}")

# ============================================================================
# ADVANCED COMMANDS
# ============================================================================

def cmd_advanced_menu():
    """Interactive menu for advanced analysis."""
    while True:
        print("\n" + "="*60)
        print("ADVANCED ANALYSIS MENU")
        print("="*60)
        print("1. Streak Analysis")
        print("2. Variance by Odds Range")
        print("3. Performance by Sportsbook")
        print("4. Recent Picks (7 days)")
        print("5. Detailed Report")
        print("6. Export Detailed Report")
        print("0. Back")
        print()

        choice = input("Select: ").strip()

        if choice == '1':
            cmd_streak_analysis()
        elif choice == '2':
            cmd_variance_analysis()
        elif choice == '3':
            cmd_book_analysis()
        elif choice == '4':
            cmd_recent_picks(7)
        elif choice == '5':
            export_detailed_report()
        elif choice == '6':
            export_detailed_report()
        elif choice == '0':
            break
        else:
            print("Invalid selection.")

# ============================================================================
# DEVELOPMENT & DEBUG
# ============================================================================

def debug_fetch_schedule(date_str):
    """Debug schedule fetching."""
    print(f"Fetching schedule for {date_str}...")
    games = get_nba_schedule(date_str, silent=False)
    print(f"Found {len(games)} games:")
    for g in games:
        print(f"  {g['away_abb']} @ {g['home_abb']}")

def debug_compute_game(away, home):
    """Debug game computation."""
    stats = load_nba_stats()
    if not stats:
        print("No stats. Run --refresh")
        return

    model = compute_game(away, home, stats)
    m_sp = model['spread']
    if abs(m_sp) >= 0.5:
        sp_fav = home if m_sp >= 0 else away
        sp_dog = away if m_sp >= 0 else home
        spread_str = f"{sp_fav} -{abs(m_sp):.1f} / {sp_dog} +{abs(m_sp):.1f}"
    else:
        spread_str = "PICK"
    print(f"\nGame: {away} @ {home}")
    print(f"Model: {away} {model['pts_a']} vs {home} {model['pts_h']}")
    print(f"Spread: {spread_str}")
    print(f"Total: {model['total']}")
    print(f"Win%: {away} {model['wp_a']}% / {home} {model['wp_h']}%")

if __name__ == '__main__':
    main()
