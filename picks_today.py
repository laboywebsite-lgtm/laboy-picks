#!/usr/bin/env python3
"""
picks_today.py  — Runner unificado MLB + NBA
─────────────────────────────────────────────
Corre MLB y NBA con los flags del día, en orden.
Uso:
  python3 picks_today.py                 → picks del día completo (ambas ligas)
  python3 picks_today.py --day           → solo sesión day de MLB  +  NBA
  python3 picks_today.py --night         → solo sesión night de MLB  +  NBA
  python3 picks_today.py --mlb           → solo MLB (sesión full)
  python3 picks_today.py --nba           → solo NBA
  python3 picks_today.py --force-repick  → sobreescribir picks guardados (rompe calibración)
  python3 picks_today.py --publish       → publica ambas ligas al terminar
  python3 picks_today.py --debug         → genera debug HTML de ambas ligas
  python3 picks_today.py --confirmed     → MLB solo con lineups confirmados
"""

import subprocess
import sys
import os
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MLB_PY     = os.path.join(SCRIPT_DIR, "MLB", "mlb.py")
NBA_PY     = os.path.join(SCRIPT_DIR, "NBA", "nba.py")
PYTHON     = sys.executable   # mismo intérprete que lanzó este script

# ── Leer flags del usuario ────────────────────────────────────────────────────
args        = sys.argv[1:]
only_mlb    = "--mlb"           in args
only_nba    = "--nba"           in args
day_mode    = "--day"           in args
night_mode  = "--night"         in args
force       = "--force-repick"  in args
publish     = "--publish"       in args
debug       = "--debug"         in args
confirmed   = "--confirmed"     in args

# Flags que se reenvían a los scripts
mlb_extra   = []
nba_extra   = []

if day_mode:    mlb_extra.append("--day")
if night_mode:  mlb_extra.append("--night")
if force:
    mlb_extra.append("--force-repick")
    nba_extra.append("--force-repick")
if publish:
    mlb_extra.append("--publish")
    nba_extra.append("--publish")
if debug:
    mlb_extra.append("--debug")
    nba_extra.append("--debug")
if confirmed:
    mlb_extra.append("--confirmed")

# ── Helpers ───────────────────────────────────────────────────────────────────
SEP = "─" * 64

def run_league(name, script, extra_flags):
    cmd = [PYTHON, script, "--picks"] + extra_flags
    print(f"\n{SEP}")
    print(f"  🏟  {name}  →  {' '.join(['picks'] + extra_flags)}")
    print(SEP)
    t0 = time.time()
    result = subprocess.run(cmd, cwd=os.path.dirname(script))
    elapsed = time.time() - t0
    status  = "✅" if result.returncode == 0 else "❌"
    print(f"\n  {status} {name} terminó en {elapsed:.1f}s (rc={result.returncode})")
    return result.returncode

# ── Ejecución ─────────────────────────────────────────────────────────────────
print(f"\n{'═'*64}")
print(f"  LABOY PICKS HOY — Runner Unificado")
print(f"{'═'*64}")

errors = []

if not only_nba:
    rc = run_league("MLB ⚾", MLB_PY, mlb_extra)
    if rc != 0:
        errors.append("MLB")

if not only_mlb:
    rc = run_league("NBA 🏀", NBA_PY, nba_extra)
    if rc != 0:
        errors.append("NBA")

print(f"\n{'═'*64}")
if errors:
    print(f"  ⚠️  Terminó con errores en: {', '.join(errors)}")
else:
    print(f"  ✅  Picks del día listos — MLB {'⏭' if only_nba else '⚾'}  NBA {'⏭' if only_mlb else '🏀'}")
print(f"{'═'*64}\n")

sys.exit(1 if errors else 0)
