#!/usr/bin/env python3
"""
record_card.py — Tarjeta combinada de récord para todas las ligas

Uso (all-time):
  python3 record_card.py

Uso (récord del día):
  python3 record_card.py 2026-05-02
  python3 record_card.py --today
  python3 record_card.py --force-export

Uso (playoffs NBA por ronda):
  python3 record_card.py --nba-r1       ← récord primera ronda (Apr 12 – May 5)
  python3 record_card.py --nba-r2       ← récord segunda ronda (May 6 – May 27)
"""

import os, sys, subprocess, re, hashlib, glob
from datetime import datetime, date, timedelta

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
FORCE_EXPORT = "--force-export" in sys.argv

# ── Mode flags ────────────────────────────────────────────────────────────────
NBA_R1_MODE = "--nba-r1" in sys.argv
NBA_R2_MODE = "--nba-r2" in sys.argv

# ── Date argument ─────────────────────────────────────────────────────────────
_DATE_ARG = None
for _a in sys.argv[1:]:
    if _a == "--today":
        _DATE_ARG = date.today().strftime("%Y-%m-%d")
        break
    if re.match(r'^\d{4}-\d{2}-\d{2}$', _a):
        _DATE_ARG = _a
        break

# ── Logo helpers ─────────────────────────────────────────────────────────────
def _load_logo_b64(path, strip_black=True):
    if not path or not os.path.exists(path):
        return ""
    try:
        from PIL import Image
        import io, base64
        img = Image.open(path).convert("RGBA")
        if strip_black:
            data = img.load()
            w, h = img.size
            for y in range(h):
                for x in range(w):
                    r, g, b, a = data[x, y]
                    if r < 35 and g < 35 and b < 35:
                        data[x, y] = (0, 0, 0, 0)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""

def _bsn_logo_b64():
    candidates = [
        os.path.join(SCRIPT_DIR, "bsn_logo.png"),
        os.path.join(SCRIPT_DIR, "BSN", "bsn_logo.png"),
        os.path.join(SCRIPT_DIR, "BSN", "laboy_logo.png"),
        os.path.join(SCRIPT_DIR, "MLB", "laboy_logo.png"),
    ]
    logo_path = next((p for p in candidates if os.path.exists(p)), None)
    return _load_logo_b64(logo_path, strip_black=True)

def _header_logo_b64():
    candidates = [
        os.path.join(SCRIPT_DIR, "MLB", "laboy_logo.png"),
        os.path.join(SCRIPT_DIR, "BSN", "laboy_logo.png"),
    ]
    logo_path = next((p for p in candidates if os.path.exists(p)), None)
    return _load_logo_b64(logo_path, strip_black=True)

def _bsn_logo_b64_legacy():
    candidates = [
        os.path.join(SCRIPT_DIR, "BSN", "laboy_logo.png"),
        os.path.join(SCRIPT_DIR, "MLB", "laboy_logo.png"),
    ]
    logo_path = next((p for p in candidates if os.path.exists(p)), None)
    if not logo_path:
        return ""
    try:
        from PIL import Image
        import io, base64
        img  = Image.open(logo_path).convert("RGBA")
        data = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = data[x, y]
                if r < 35 and g < 35 and b < 35:
                    data[x, y] = (0, 0, 0, 0)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""

# ── Liga definitions ──────────────────────────────────────────────────────────
LEAGUES = [
    {
        "name":   "MLB",
        "script": os.path.join(SCRIPT_DIR, "MLB", "mlb.py"),
        "accent": "#e05252",
        "glow":   "rgba(224,82,82,0.22)",
        "logo":   "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/mlb.png&w=120&h=120",
    },
    {
        "name":   "NBA",
        "script": os.path.join(SCRIPT_DIR, "NBA", "nba.py"),
        "accent": "#4f8ef7",
        "glow":   "rgba(79,142,247,0.22)",
        "logo":   "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/nba.png&w=120&h=120",
    },
    {
        "name":   "BSN",
        "script": os.path.join(SCRIPT_DIR, "BSN", "bsn.py"),
        "accent": "#f5a623",
        "glow":   "rgba(245,166,35,0.20)",
        "logo":   "",
    },
]

# ── Record parser ─────────────────────────────────────────────────────────────
def parse_record(out):
    r = {"w":0,"l":0,"p":0,"win_pct":0.0,"pl":0.0,"pending":0,"ok":False}
    m = re.search(r'R[eé]cord(?:\s+total)?:\s*(\d+)-(\d+)-(\d+)', out)
    if m:
        r["w"],r["l"],r["p"] = int(m.group(1)),int(m.group(2)),int(m.group(3))
        r["ok"] = True
    m2 = re.search(r'Win%:\s*([\d.]+)%', out)
    if m2: r["win_pct"] = float(m2.group(1))
    m3 = re.search(r'P&L:\s*([+-]?\$[\d,.]+)', out)
    if m3:
        try: r["pl"] = float(m3.group(1).replace('$','').replace(',',''))
        except: pass
    m4 = re.search(r'Pending:\s*(\d+)', out)
    if m4: r["pending"] = int(m4.group(1))
    return r

def _nba_logo_b64():
    candidates = [
        os.path.join(SCRIPT_DIR, "NBA", "laboy_logo.png"),
        os.path.join(SCRIPT_DIR, "MLB", "laboy_logo.png"),
        os.path.join(SCRIPT_DIR, "BSN", "laboy_logo.png"),
    ]
    logo_path = next((p for p in candidates if os.path.exists(p)), None)
    return _load_logo_b64(logo_path, strip_black=True)

def fetch_nba_playoff_record(round_key):
    script = os.path.join(SCRIPT_DIR, "NBA", "nba.py")
    if not os.path.exists(script):
        return {"w":0,"l":0,"p":0,"win_pct":0.0,"pl":0.0,"pending":0,"ok":False,"error":"nba.py not found"}
    try:
        res = subprocess.run(
            [sys.executable, script, "--record", round_key],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(script)
        )
        return parse_record(res.stdout)
    except Exception as e:
        return {"w":0,"l":0,"p":0,"win_pct":0.0,"pl":0.0,"pending":0,"ok":False,"error":str(e)}

def fetch_record(league, date_str=None):
    script = league["script"]
    if not os.path.exists(script):
        return {"w":0,"l":0,"p":0,"win_pct":0.0,"pl":0.0,"pending":0,"ok":False,"error":"script not found"}
    try:
        cmd = [sys.executable, script, "--record"]
        if date_str:
            cmd.append(date_str)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45,
                             cwd=os.path.dirname(script))
        return parse_record(res.stdout)
    except Exception as e:
        return {"w":0,"l":0,"p":0,"win_pct":0.0,"pl":0.0,"pending":0,"ok":False,"error":str(e)}

# ── Helpers ───────────────────────────────────────────────────────────────────
def win_color(pct):
    if pct >= 58: return "#22c55e"
    if pct >= 52: return "#86efac"
    if pct >= 46: return "#f59e0b"
    return "#ef4444"

def win_bg(pct):
    if pct >= 58: return "rgba(34,197,94,0.12)"
    if pct >= 52: return "rgba(134,239,172,0.10)"
    if pct >= 46: return "rgba(245,158,11,0.12)"
    return "rgba(239,68,68,0.12)"

def short_hash():
    return hashlib.md5(datetime.now().isoformat().encode()).hexdigest()[:7]

# ── JPG export (playwright) ───────────────────────────────────────────────────
def html_to_jpg(html_path, width=820, scale=2):
    jpg_path = html_path.replace(".html", ".jpg")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  💡 Para JPG: pip install playwright --break-system-packages && playwright install chromium")
        return None
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox","--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width":width,"height":600}, device_scale_factor=scale)
            page.set_content(html_content, wait_until="domcontentloaded")
            try: page.wait_for_load_state("networkidle", timeout=7000)
            except: pass
            h = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width":width,"height":max(h,300)})
            png_bytes = page.screenshot(full_page=True)
            browser.close()
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        img.save(jpg_path, "JPEG", quality=95, optimize=True)
        return jpg_path
    except Exception as e:
        print(f"  ⚠️  html_to_jpg error: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# SHARED AI CSS — injected into all three templates
# ══════════════════════════════════════════════════════════════════════════════
_AI_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800;900&display=swap');

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  background: #060a0f;
  font-family: 'Inter', system-ui, sans-serif;
  color: #e2e8f0;
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 28px 16px 36px;
  /* subtle dot-grid texture */
  background-image: radial-gradient(rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 24px 24px;
  background-color: #060a0f;
}}

.wrapper {{
  width: 100%;
  max-width: {max_w}px;
}}

/* ── Header ── */
.hdr {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255,255,255,.06);
}}
.hdr-brand {{
  display: flex; align-items: center; gap: 10px;
}}
.hdr-brand img {{
  height: 44px; object-fit: contain;
}}
.hdr-brand-text {{
  display: flex; align-items: center; gap: 8px;
}}
.hdr-dot {{
  width: 7px; height: 7px; border-radius: 50%;
  background: #f07820;
  box-shadow: 0 0 10px rgba(240,120,32,.7);
}}
.hdr-name {{
  font-size: .72rem; font-weight: 800;
  letter-spacing: .18em; text-transform: uppercase;
  color: #f07820;
}}
.hdr-badge {{
  display: flex; align-items: center; gap: 6px;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 99px;
  padding: 4px 12px;
}}
.hdr-badge-dot {{
  width: 5px; height: 5px; border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 6px rgba(34,197,94,.9);
  animation: blink 2s ease-in-out infinite;
}}
@keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
.hdr-badge-lbl {{
  font-size: .6rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase;
  color: #475569;
}}
.hdr-ts {{
  font-size: .65rem; color: #334155;
  letter-spacing: .08em; text-transform: uppercase;
}}

/* ── League cards (all-time & daily breakdown) ── */
.lg-list {{
  display: flex; flex-direction: column; gap: 10px;
}}

.lg-card {{
  position: relative;
  background: rgba(255,255,255,.03);
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 16px;
  padding: 18px 20px 16px;
  overflow: hidden;
}}

/* colored left bar */
.lg-card::before {{
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--accent);
  border-radius: 3px 0 0 3px;
}}

/* accent glow */
.lg-card::after {{
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at -5% 50%, var(--glow) 0%, transparent 55%);
  pointer-events: none;
}}

.lg-top {{
  display: flex; align-items: center; gap: 14px;
  position: relative; z-index: 1;
  margin-bottom: 14px;
}}

.lg-icon {{
  flex-shrink: 0;
  width: 42px; height: 42px;
  border-radius: 10px;
  background: rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.08);
  display: flex; align-items: center; justify-content: center;
  overflow: hidden;
}}
.lg-icon img {{
  width: 30px; height: 30px; object-fit: contain;
}}
.lg-icon-txt {{
  font-size: .85rem; font-weight: 900;
  color: var(--accent);
}}

.lg-meta {{ flex: 1; }}
.lg-league-name {{
  font-size: .65rem; font-weight: 800;
  letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); margin-bottom: 1px;
}}
.lg-sub {{
  font-size: .6rem; color: #334155;
  letter-spacing: .06em;
}}

.lg-pl-tag {{
  flex-shrink: 0;
  font-size: .72rem; font-weight: 800;
  padding: 4px 10px;
  border-radius: 8px;
  letter-spacing: .02em;
}}
.pl-pos {{ background: rgba(34,197,94,.12); color: #22c55e; border: 1px solid rgba(34,197,94,.22); }}
.pl-neg {{ background: rgba(239,68,68,.10); color: #ef4444; border: 1px solid rgba(239,68,68,.18); }}
.pl-neu {{ background: rgba(255,255,255,.05); color: #475569; border: 1px solid rgba(255,255,255,.08); }}

/* big W-L */
.lg-record {{
  display: flex; align-items: baseline; gap: 2px;
  position: relative; z-index: 1;
  margin-bottom: 12px;
}}
.r-big {{
  font-size: 3.4rem; font-weight: 900;
  line-height: 1; letter-spacing: -.04em;
}}
.r-w  {{ color: #22c55e; text-shadow: 0 0 28px rgba(34,197,94,.35); }}
.r-l  {{ color: #ef4444; text-shadow: 0 0 28px rgba(239,68,68,.30); }}
.r-push {{ font-size: 1.8rem; font-weight: 700; color: #475569; line-height: 1; }}
.r-sep {{
  font-size: 2rem; font-weight: 200; color: rgba(255,255,255,.1);
  line-height: 1; margin: 0 6px;
}}

/* stats row */
.lg-stats {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  position: relative; z-index: 1;
  margin-bottom: 12px;
}}
.lg-stat {{
  background: rgba(255,255,255,.03);
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 9px;
  padding: 7px 10px;
}}
.ls-lbl {{
  font-size: .58rem; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase;
  color: #475569; margin-bottom: 3px;
}}
.ls-val {{
  font-size: 1rem; font-weight: 800; line-height: 1;
}}

/* progress bar */
.lg-bar-wrap {{ position: relative; z-index: 1; }}
.lg-bar-bg {{
  height: 3px; background: rgba(255,255,255,.06);
  border-radius: 99px; overflow: hidden;
}}
.lg-bar-fill {{
  height: 100%; border-radius: 99px;
  background: var(--bar-clr);
  box-shadow: 0 0 8px var(--bar-clr);
}}

.no-picks-note {{
  font-size: .68rem; color: #334155;
  font-style: italic;
  position: relative; z-index: 1;
}}

/* ── Hero (daily combined) ── */
.hero {{
  position: relative;
  background: rgba(255,255,255,.03);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 18px;
  padding: 24px 24px 20px;
  overflow: hidden;
  margin-bottom: 12px;
}}
.hero::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, rgba(240,120,32,.6), rgba(255,78,0,.5), rgba(240,120,32,.6), transparent);
}}
.hero::after {{
  content: '';
  position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% -20%, rgba(240,120,32,.06) 0%, transparent 60%);
  pointer-events: none;
}}

.hero-top {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 16px;
  position: relative; z-index: 1;
}}
.hero-label {{
  font-size: .62rem; font-weight: 800;
  letter-spacing: .2em; text-transform: uppercase;
  color: #f07820;
}}
.hero-date {{
  font-size: .62rem; color: #334155;
  letter-spacing: .1em; text-transform: uppercase;
}}

.hero-record {{
  display: flex; align-items: baseline; gap: 2px;
  position: relative; z-index: 1;
  margin-bottom: 16px;
}}
.hr-big {{
  font-size: 5.5rem; font-weight: 900;
  line-height: 1; letter-spacing: -.05em;
}}
.hr-w {{ color: #22c55e; text-shadow: 0 0 40px rgba(34,197,94,.4); }}
.hr-l {{ color: #ef4444; text-shadow: 0 0 40px rgba(239,68,68,.35); }}
.hr-p {{ font-size: 3rem; font-weight: 700; color: #475569; }}
.hr-sep {{
  font-size: 3.5rem; font-weight: 200;
  color: rgba(255,255,255,.08);
  line-height: 1; margin: 0 10px;
}}

.hero-pills {{
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  position: relative; z-index: 1; margin-bottom: 16px;
}}
.h-pill {{
  display: flex; flex-direction: column; gap: 2px;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 9px; padding: 6px 12px;
}}
.hp-lbl {{
  font-size: .52rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase;
  color: #475569;
}}
.hp-val {{
  font-size: .92rem; font-weight: 800; line-height: 1;
}}

.hero-bar-wrap {{
  position: relative; z-index: 1;
}}
.hero-bar-lbl {{
  font-size: .52rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase;
  color: #1e293b; margin-bottom: 5px;
}}
.hero-bar-bg {{
  height: 3px; background: rgba(255,255,255,.06);
  border-radius: 99px; overflow: hidden;
}}
.hero-bar-fill {{
  height: 100%; border-radius: 99px;
}}

/* ── Playoffs (NBA round card) ── */
.po-round-badge {{
  text-align: center; margin-bottom: 20px;
}}
.po-pill {{
  display: inline-flex; align-items: center; gap: 8px;
  background: rgba(79,142,247,.06);
  border: 1px solid rgba(79,142,247,.2);
  border-radius: 99px; padding: 7px 20px;
  font-size: .68rem; font-weight: 800;
  letter-spacing: .16em; text-transform: uppercase;
  color: #4f8ef7;
  box-shadow: 0 0 20px rgba(79,142,247,.08);
}}
.po-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: #4f8ef7;
  box-shadow: 0 0 8px rgba(79,142,247,.8);
}}

.po-card {{
  position: relative;
  background: rgba(255,255,255,.03);
  border: 1px solid rgba(79,142,247,.15);
  border-radius: 18px;
  padding: 24px 24px 20px;
  overflow: hidden;
  margin-bottom: 12px;
}}
.po-card::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, rgba(79,142,247,.5), rgba(100,160,255,.4), rgba(79,142,247,.5), transparent);
}}
.po-card::after {{
  content: '';
  position: absolute; inset: 0;
  background: radial-gradient(ellipse at 50% -20%, rgba(79,142,247,.07) 0%, transparent 60%);
  pointer-events: none;
}}

.po-top {{
  display: flex; align-items: center; gap: 14px;
  margin-bottom: 18px;
  position: relative; z-index: 1;
}}
.po-icon {{
  width: 52px; height: 52px; border-radius: 12px;
  background: rgba(79,142,247,.08);
  border: 1px solid rgba(79,142,247,.2);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}}
.po-icon img {{
  width: 36px; height: 36px; object-fit: contain;
}}
.po-league {{
  font-size: .65rem; font-weight: 800;
  letter-spacing: .18em; text-transform: uppercase;
  color: #4f8ef7; margin-bottom: 3px;
}}
.po-round-lbl {{
  font-size: .68rem; font-weight: 500;
  color: #334155; letter-spacing: .04em;
}}

.po-record {{
  display: flex; align-items: baseline; gap: 2px;
  position: relative; z-index: 1;
  margin-bottom: 16px;
}}

.po-pills {{
  display: flex; gap: 8px; flex-wrap: wrap;
  position: relative; z-index: 1; margin-bottom: 16px;
}}

.po-bar-wrap {{ position: relative; z-index: 1; }}
.po-bar-lbl {{
  font-size: .5rem; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase;
  color: #1e293b; margin-bottom: 5px;
}}
.po-bar-bg {{
  height: 4px; background: rgba(255,255,255,.06);
  border-radius: 99px; overflow: hidden;
}}
.po-bar-fill {{ height: 100%; border-radius: 99px; }}

.po-date-range {{
  text-align: center; margin-top: 12px;
  font-size: .58rem; font-weight: 600;
  letter-spacing: .1em; text-transform: uppercase;
  color: #1e293b;
}}

/* ── Footer ── */
.footer {{
  margin-top: 16px; text-align: center;
  font-size: .58rem; color: #1e293b;
  letter-spacing: .08em;
}}
"""

# ── HTML – ALL-TIME ───────────────────────────────────────────────────────────
HTML_ALLTIME = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Laboy Picks · Record General</title>
<style>{css}</style>
</head>
<body>
<div class="wrapper">

  <div class="hdr">
    {brand_html}
    <div style="display:flex;align-items:center;gap:8px;">
      <div class="hdr-badge">
        <div class="hdr-badge-dot"></div>
        <span class="hdr-badge-lbl">All-Time</span>
      </div>
      <span class="hdr-ts">{date_str}</span>
    </div>
  </div>

  <div class="lg-list">
{cards}
  </div>

  <div class="footer">Laboy Picks · Updated {ts}</div>

</div>
</body>
</html>
"""

CARD_TPL = """\
    <div class="lg-card" style="--accent:{accent};--glow:{glow};--bar-clr:{wc};">
      <div class="lg-top">
        <div class="lg-icon">
          <img src="{logo}" alt="{name}"
               onerror="this.style.display='none';this.nextElementSibling.style.display='block';">
          <span class="lg-icon-txt" style="display:none;">{name}</span>
        </div>
        <div class="lg-meta">
          <div class="lg-league-name">{name}</div>
          <div class="lg-sub">ALL-TIME RECORD</div>
        </div>
        {pl_tag}
      </div>

      <div class="lg-record">
        <span class="r-big r-w">{w}</span>
        <span class="r-sep">-</span>
        <span class="r-big r-l">{l}</span>
        {push_frag}
      </div>

      <div class="lg-stats">
        <div class="lg-stat">
          <div class="ls-lbl">Win Rate</div>
          <div class="ls-val" style="color:{wc};">{pct:.1f}%</div>
        </div>
        <div class="lg-stat">
          <div class="ls-lbl">Picks</div>
          <div class="ls-val" style="color:#94a3b8;">{total_picks}</div>
        </div>
        {pending_stat}
      </div>

      <div class="lg-bar-wrap">
        <div class="lg-bar-bg">
          <div class="lg-bar-fill" style="width:{bar_w}%;"></div>
        </div>
      </div>

      {error_frag}
    </div>"""

def build_html_alltime(data, logo_b64=""):
    now      = datetime.now()
    date_str = now.strftime("%b %d, %Y").upper()
    ts       = now.strftime("%H:%M")

    if logo_b64:
        brand_html = (f'<div class="hdr-brand">'
                      f'<img src="{logo_b64}" alt="Laboy Picks" style="height:44px;object-fit:contain;">'
                      f'</div>')
    else:
        brand_html = ('<div class="hdr-brand-text">'
                      '<div class="hdr-dot"></div>'
                      '<span class="hdr-name">Laboy Picks</span>'
                      '</div>')

    cards = []
    for league, rec in data:
        wc    = win_color(rec["win_pct"])
        bar_w = max(0, min(100, (rec["win_pct"] - 30) / 45 * 100))
        total_picks = rec["w"] + rec["l"] + rec["p"]

        pl_tag = ""
        if rec.get("pl", 0) > 0:
            pl_tag = f'<span class="lg-pl-tag pl-pos">+${rec["pl"]:,.2f}</span>'
        elif rec.get("pl", 0) < 0:
            pl_tag = f'<span class="lg-pl-tag pl-neg">-${abs(rec["pl"]):,.2f}</span>'

        push_frag = ""
        if rec["p"] > 0:
            push_frag = f'<span class="r-sep" style="font-size:1.4rem;">·</span><span class="r-push">{rec["p"]}</span>'

        pending_stat = ""
        if rec["pending"] > 0:
            pending_stat = (f'<div class="lg-stat">'
                            f'<div class="ls-lbl">Pending</div>'
                            f'<div class="ls-val" style="color:#f59e0b;">{rec["pending"]}</div>'
                            f'</div>')
        else:
            pending_stat = (f'<div class="lg-stat">'
                            f'<div class="ls-lbl">P&amp;L</div>'
                            f'<div class="ls-val" style="color:{wc};">'
                            + (f'+${rec["pl"]:,.2f}' if rec.get("pl",0) >= 0 else f'-${abs(rec.get("pl",0)):,.2f}') +
                            f'</div></div>')

        error_frag = (f'<div style="font-size:.62rem;color:#ef4444;margin-top:8px;position:relative;z-index:1;">'
                      f'⚠ {rec.get("error","")}</div>') if "error" in rec else ""

        cards.append(CARD_TPL.format(
            name         = league["name"],
            logo         = league["logo"],
            accent       = league["accent"],
            glow         = league["glow"],
            w            = rec["w"],
            l            = rec["l"],
            push_frag    = push_frag,
            pl_tag       = pl_tag,
            pending_stat = pending_stat,
            error_frag   = error_frag,
            wc           = wc,
            pct          = rec["win_pct"],
            bar_w        = round(bar_w, 1),
            total_picks  = total_picks,
        ))

    css  = _AI_CSS.format(max_w=420)
    html = HTML_ALLTIME.format(
        css        = css,
        brand_html = brand_html,
        date_str   = date_str,
        cards      = "\n".join(cards),
        ts         = ts,
    )
    return html

# ── HTML – RÉCORD DEL DÍA ────────────────────────────────────────────────────
HTML_DIA = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Laboy Picks · Récord del Día</title>
<style>{css}</style>
</head>
<body>
<div class="wrapper">

  <div class="hdr">
    <div class="hdr-brand-text">
      <div class="hdr-dot"></div>
      <span class="hdr-name">Laboy Picks</span>
    </div>
    <span class="hdr-ts">{ts}</span>
  </div>

  <!-- Hero combined -->
  <div class="hero">
    <div class="hero-top">
      <span class="hero-label">Récord del Día</span>
      <span class="hero-date">{display_date}</span>
    </div>

    <div class="hero-record">
      <span class="hr-big hr-w">{total_w}</span>
      <span class="hr-sep">-</span>
      <span class="hr-big hr-l">{total_l}</span>
      {total_push_frag}
    </div>

    <div class="hero-pills">
      <div class="h-pill">
        <span class="hp-lbl">Win Rate</span>
        <span class="hp-val" style="color:{total_wc};">{total_pct:.1f}%</span>
      </div>
      {total_pl_pill}
      {total_picks_pill}
      {total_pending_pill}
    </div>

    <div class="hero-bar-wrap">
      <div class="hero-bar-lbl">Performance</div>
      <div class="hero-bar-bg">
        <div class="hero-bar-fill" style="width:{total_bar_w}%;background:{total_wc};box-shadow:0 0 10px {total_wc}66;"></div>
      </div>
    </div>
  </div>

  <!-- Per-league breakdown -->
  <div class="lg-list">
{league_cards}
  </div>

  <div class="footer">Laboy Picks · {display_date} · Generated {ts}</div>

</div>
</body>
</html>
"""

LG_CARD_TPL = """\
    <div class="lg-card" style="--accent:{accent};--glow:{glow};--bar-clr:{wc};">
      <div class="lg-top">
        <div class="lg-icon">
          <img src="{logo}" alt="{name}"
               onerror="this.style.display='none';this.nextElementSibling.style.display='block';">
          <span class="lg-icon-txt" style="display:none;">{name}</span>
        </div>
        <div class="lg-meta">
          <div class="lg-league-name">{name}</div>
          <div class="lg-sub">Récord del Día</div>
        </div>
        {pl_frag}
      </div>

      {record_or_empty}

      {bar_frag}
    </div>"""

def build_html_dia(data, date_str):
    now = datetime.now()
    ts  = now.strftime("%H:%M")

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        display_date = dt.strftime("%B %d, %Y").upper()
    except Exception:
        display_date = date_str.upper()

    total_w = sum(rec["w"] for _, rec in data if rec["ok"])
    total_l = sum(rec["l"] for _, rec in data if rec["ok"])
    total_p = sum(rec["p"] for _, rec in data if rec["ok"])
    total_pl = sum(rec["pl"] for _, rec in data if rec["ok"])
    total_pending = sum(rec["pending"] for _, rec in data)
    total_decided = total_w + total_l
    total_pct = (total_w / total_decided * 100) if total_decided > 0 else 0.0
    total_wc  = win_color(total_pct)
    total_bar_w = max(0, min(100, (total_pct - 30) / 45 * 100))

    total_push_frag = ""
    if total_p > 0:
        total_push_frag = (f'<span class="hr-sep" style="font-size:2.5rem;margin:0 8px;">·</span>'
                           f'<span class="hr-p">{total_p}</span>')

    if total_pl > 0:
        total_pl_pill = (f'<div class="h-pill"><span class="hp-lbl">P&amp;L</span>'
                         f'<span class="hp-val" style="color:#22c55e;">+${total_pl:,.2f}</span></div>')
    elif total_pl < 0:
        total_pl_pill = (f'<div class="h-pill"><span class="hp-lbl">P&amp;L</span>'
                         f'<span class="hp-val" style="color:#ef4444;">-${abs(total_pl):,.2f}</span></div>')
    else:
        total_pl_pill = ""

    total_picks = total_w + total_l + total_p
    total_picks_pill = (f'<div class="h-pill"><span class="hp-lbl">Picks</span>'
                        f'<span class="hp-val" style="color:#94a3b8;">{total_picks}</span></div>')
    total_pending_pill = (f'<div class="h-pill"><span class="hp-lbl">Pending</span>'
                          f'<span class="hp-val" style="color:#f59e0b;">{total_pending}</span></div>'
                          ) if total_pending > 0 else ""

    lg_cards = []
    for league, rec in data:
        wc    = win_color(rec["win_pct"])
        bar_w = max(0, min(100, (rec["win_pct"] - 30) / 45 * 100))

        if rec.get("pl", 0) > 0:
            pl_frag = f'<span class="lg-pl-tag pl-pos">+${rec["pl"]:,.2f}</span>'
        elif rec.get("pl", 0) < 0:
            pl_frag = f'<span class="lg-pl-tag pl-neg">-${abs(rec["pl"]):,.2f}</span>'
        else:
            pl_frag = ""

        no_picks = (not rec["ok"]) or (rec["w"] == 0 and rec["l"] == 0 and rec["p"] == 0 and rec["pending"] == 0)

        if no_picks:
            record_or_empty = '<div class="no-picks-note">sin picks este día</div>'
            bar_frag = ""
        else:
            push_frag = ""
            if rec["p"] > 0:
                push_frag = f'<span class="r-sep" style="font-size:1.2rem;">·</span><span class="r-push" style="font-size:1.6rem;">{rec["p"]}</span>'

            pending_stat = ""
            if rec["pending"] > 0:
                pending_stat = (f'<div class="lg-stat">'
                                f'<div class="ls-lbl">Pending</div>'
                                f'<div class="ls-val" style="color:#f59e0b;">{rec["pending"]}</div>'
                                f'</div>')

            record_or_empty = (
                f'<div class="lg-record">'
                f'<span class="r-big r-w">{rec["w"]}</span>'
                f'<span class="r-sep">-</span>'
                f'<span class="r-big r-l">{rec["l"]}</span>'
                f'{push_frag}</div>'
                f'<div class="lg-stats">'
                f'<div class="lg-stat"><div class="ls-lbl">Win Rate</div>'
                f'<div class="ls-val" style="color:{wc};">{rec["win_pct"]:.1f}%</div></div>'
                f'<div class="lg-stat"><div class="ls-lbl">Picks</div>'
                f'<div class="ls-val" style="color:#94a3b8;">{rec["w"]+rec["l"]+rec["p"]}</div></div>'
                + pending_stat +
                f'</div>'
            )
            bar_frag = (f'<div class="lg-bar-wrap">'
                        f'<div class="lg-bar-bg">'
                        f'<div class="lg-bar-fill" style="width:{round(bar_w,1)}%;"></div>'
                        f'</div></div>')

        lg_cards.append(LG_CARD_TPL.format(
            accent         = league["accent"],
            glow           = league["glow"],
            logo           = league["logo"],
            name           = league["name"],
            wc             = wc,
            pl_frag        = pl_frag,
            record_or_empty= record_or_empty,
            bar_frag       = bar_frag,
        ))

    css = _AI_CSS.format(max_w=480)
    return HTML_DIA.format(
        css              = css,
        ts               = ts,
        display_date     = display_date,
        total_w          = total_w,
        total_l          = total_l,
        total_push_frag  = total_push_frag,
        total_pct        = total_pct,
        total_wc         = total_wc,
        total_bar_w      = round(total_bar_w, 1),
        total_pl_pill    = total_pl_pill,
        total_picks_pill = total_picks_pill,
        total_pending_pill = total_pending_pill,
        league_cards     = "\n".join(lg_cards),
    )

# ── HTML – NBA PLAYOFFS ROUND RECORD ─────────────────────────────────────────
HTML_PO = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Laboy Picks · NBA Playoffs {round_name}</title>
<style>{css}</style>
</head>
<body>
<div class="wrapper">

  <div class="hdr">
    {brand_html}
    <span class="hdr-ts">{date_label}</span>
  </div>

  <div class="po-round-badge">
    <div class="po-pill">
      <div class="po-dot"></div>
      {round_name} · NBA PLAYOFFS 2026
      <div class="po-dot"></div>
    </div>
  </div>

  <div class="po-card">
    <div class="po-top">
      <div class="po-icon">
        <img src="https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/nba.png&w=80&h=80"
             alt="NBA" onerror="this.style.display='none'">
      </div>
      <div>
        <div class="po-league">NBA</div>
        <div class="po-round-lbl">{round_label}</div>
      </div>
    </div>

    <div class="po-record">
      <span class="r-big r-w" style="font-size:5rem;">{w}</span>
      <span class="r-sep" style="font-size:3rem;margin:0 10px;">-</span>
      <span class="r-big r-l" style="font-size:5rem;">{l}</span>
    </div>

    <div class="po-pills">
      <div class="h-pill">
        <span class="hp-lbl">Win Rate</span>
        <span class="hp-val" style="color:{wc};">{pct:.1f}%</span>
      </div>
      <div class="h-pill">
        <span class="hp-lbl">Picks</span>
        <span class="hp-val" style="color:#94a3b8;">{total_picks}</span>
      </div>
      {pending_pill}
    </div>

    <div class="po-bar-wrap">
      <div class="po-bar-lbl">Performance</div>
      <div class="po-bar-bg">
        <div class="po-bar-fill" style="width:{bar_w}%;background:{wc};box-shadow:0 0 10px {wc}66;"></div>
      </div>
    </div>
  </div>

  <div class="po-date-range">{date_range_str}</div>
  <div class="footer">Laboy Picks · Generated {ts}</div>

</div>
</body>
</html>
"""

def build_html_playoffs(rec, round_key, logo_b64=""):
    now        = datetime.now()
    ts         = now.strftime("%H:%M")
    date_label = now.strftime("%b %d, %Y").upper()

    if round_key == "r1":
        round_name  = "PRIMERA RONDA"
        round_label = "Primera Ronda · Apr 12 – May 5"
        date_range_str = "Apr 12, 2026 – May 5, 2026"
    else:
        round_name  = "SEGUNDA RONDA"
        round_label = "Segunda Ronda · May 6 – May 27"
        date_range_str = "May 6, 2026 – May 27, 2026"

    if logo_b64:
        brand_html = (f'<div class="hdr-brand">'
                      f'<img src="{logo_b64}" alt="Laboy Picks" style="height:44px;object-fit:contain;">'
                      f'</div>')
    else:
        brand_html = ('<div class="hdr-brand-text">'
                      '<div class="hdr-dot"></div>'
                      '<span class="hdr-name">Laboy Picks</span>'
                      '</div>')

    w   = rec.get("w", 0)
    l   = rec.get("l", 0)
    p   = rec.get("p", 0)
    pct = rec.get("win_pct", 0.0)
    pend = rec.get("pending", 0)

    wc    = win_color(pct)
    bar_w = max(0, min(100, (pct - 30) / 45 * 100))
    total_picks = w + l + p

    pending_pill = (f'<div class="h-pill"><span class="hp-lbl">Pending</span>'
                    f'<span class="hp-val" style="color:#f59e0b;">{pend}</span></div>'
                    ) if pend > 0 else ""

    css = _AI_CSS.format(max_w=420)
    return HTML_PO.format(
        css            = css,
        round_name     = round_name,
        round_label    = round_label,
        date_range_str = date_range_str,
        brand_html     = brand_html,
        date_label     = date_label,
        ts             = ts,
        w              = w,
        l              = l,
        pct            = pct,
        wc             = wc,
        bar_w          = round(bar_w, 1),
        total_picks    = total_picks,
        pending_pill   = pending_pill,
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # ── NBA Playoffs round mode ───────────────────────────────────────────────
    if NBA_R1_MODE or NBA_R2_MODE:
        round_key  = "r1" if NBA_R1_MODE else "r2"
        round_disp = "Primera Ronda" if round_key == "r1" else "Segunda Ronda"
        print(f"\n🏆 NBA Playoffs — {round_disp}\n")
        print(f"  ⏳ Fetching récord {round_key.upper()}...", end=" ", flush=True)
        rec = fetch_nba_playoff_record(round_key)
        if rec["ok"] or rec["w"] > 0 or rec["l"] > 0:
            push_str = f"-{rec['p']}" if rec.get("p",0) > 0 else ""
            print(f"✅  {rec['w']}-{rec['l']}{push_str}  Win%: {rec['win_pct']:.1f}%")
        else:
            print(f"⚠️  {rec.get('error','sin picks')}")

        header_b64 = _header_logo_b64()
        html  = build_html_playoffs(rec, round_key, logo_b64=header_b64)
        today = datetime.now().strftime("%Y-%m-%d")
        h     = short_hash()
        fname = f"Laboy NBA Playoffs {round_key.upper()} {today}-{h}.html"
        pat   = f"Laboy NBA Playoffs {round_key.upper()} {today}-*.html"

        fpath    = os.path.join(SCRIPT_DIR, fname)
        existing = glob.glob(os.path.join(SCRIPT_DIR, pat))
        if existing and not FORCE_EXPORT:
            print(f"\n  🔒 Ya existe — usa --force-export para regenerar.")
            fpath = existing[0]
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)
        if not (existing and not FORCE_EXPORT):
            print(f"\n  ✅ HTML: {os.path.basename(fpath)}")

        print("  🖼️  Generando JPG...", end=" ", flush=True)
        jpg = html_to_jpg(fpath, width=420, scale=3)
        if jpg:
            print(f"✅  {os.path.basename(jpg)}")
        else:
            print("⚠️  playwright no disponible")
        print(f"\n  📂 {fpath}\n")
        return jpg or fpath

    # Logos
    bsn_b64    = _bsn_logo_b64()
    header_b64 = _header_logo_b64()
    for lg in LEAGUES:
        if lg["name"] == "BSN" and bsn_b64:
            lg["logo"] = bsn_b64

    is_daily = bool(_DATE_ARG)

    if is_daily:
        print(f"\n📅 Récord del día: {_DATE_ARG}\n")
    else:
        print("\n📊 Recopilando récords (all-time)...\n")

    data = []
    for league in LEAGUES:
        print(f"  ⏳ {league['name']}...", end=" ", flush=True)
        rec = fetch_record(league, _DATE_ARG if is_daily else None)
        if rec["ok"]:
            push_str = f"-{rec['p']}" if rec["p"] > 0 else ""
            print(f"✅  {rec['w']}-{rec['l']}{push_str}  Win%: {rec['win_pct']:.1f}%")
        elif "error" in rec:
            print(f"⚠️  {rec['error']}")
        else:
            print("—  sin picks")
        data.append((league, rec))

    if is_daily:
        tw = sum(r["w"] for _, r in data if r["ok"])
        tl = sum(r["l"] for _, r in data if r["ok"])
        tp = sum(r["p"] for _, r in data if r["ok"])
        push_str = f"-{tp}" if tp > 0 else ""
        print(f"\n  📌 Total del día: {tw}-{tl}{push_str}")

        html  = build_html_dia(data, _DATE_ARG)
        h     = short_hash()
        fname = f"Laboy Record Dia {_DATE_ARG}-{h}.html"
        prefix_pat = f"Laboy Record Dia {_DATE_ARG}-*.html"
    else:
        html  = build_html_alltime(data, logo_b64=header_b64)
        h     = short_hash()
        today = datetime.now().strftime("%Y-%m-%d")
        fname = f"Laboy Record General {today}-{h}.html"
        prefix_pat = f"Laboy Record General {today}-*.html"

    fpath = os.path.join(SCRIPT_DIR, fname)

    existing = glob.glob(os.path.join(SCRIPT_DIR, prefix_pat))
    if existing and not FORCE_EXPORT:
        print(f"\n  🔒 Ya existe ({os.path.basename(existing[0])}) — usa --force-export para regenerar.")
        fpath = existing[0]
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)
    if not (existing and not FORCE_EXPORT):
        print(f"\n  ✅ HTML: {os.path.basename(fpath)}")

    print("  🖼️  Generando JPG...", end=" ", flush=True)
    jpg = html_to_jpg(fpath, width=420, scale=3)
    if jpg:
        print(f"✅  {os.path.basename(jpg)}")
    else:
        print("⚠️  playwright no disponible")

    print(f"\n  📂 {fpath}\n")
    return jpg or fpath

if __name__ == "__main__":
    main()
