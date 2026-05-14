"""
fix_parlay_publish.py
Copia todos los PNGs de parlay al repo bsn-picks,
actualiza manifest.json y hace git push.
Corre: python3 fix_parlay_publish.py
"""
import json, os, shutil, subprocess, glob as _glob, re
from datetime import date

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
REPO             = os.environ.get("BSN_GITHUB_REPO",
                   os.path.join(os.path.expanduser("~"), "repos", "bsn-picks"))
PAGES_URL        = "https://laboywebsite-lgtm.github.io/bsn-picks"
MANIFEST_PATH    = os.path.join(REPO, "manifest.json")

print(f"\n{'═'*60}")
print(f"  FIX PARLAY PUBLISH")
print(f"{'═'*60}\n")

if not os.path.isdir(REPO):
    print(f"  ❌ Repo no encontrado: {REPO}")
    print(f"     Verifica que tienes clonado el repo bsn-picks.")
    raise SystemExit(1)

# ── 1. Encontrar PNGs de parlay en carpeta BSN ────────────────────────────
parlay_pngs = sorted(_glob.glob(os.path.join(SCRIPT_DIR, "Laboy BSN Parlay*.png")))
if not parlay_pngs:
    print(f"  ❌ No se encontró ningún Laboy BSN Parlay*.png en:\n     {SCRIPT_DIR}")
    raise SystemExit(1)

print(f"  📸 {len(parlay_pngs)} parlay PNG(s) encontrado(s):")
for p in parlay_pngs:
    print(f"     {os.path.basename(p)}")

# ── 2. Copiar al repo ────────────────────────────────────────────────────
for png in parlay_pngs:
    dest = os.path.join(REPO, os.path.basename(png))
    shutil.copy2(png, dest)
print(f"\n  ✅ Copiado(s) a: {REPO}")

# ── 3. Leer / crear manifest.json ───────────────────────────────────────
if os.path.exists(MANIFEST_PATH):
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
else:
    manifest = {"sport": "BSN", "base_url": PAGES_URL, "files": []}

existing_names = {fi["name"] for fi in manifest.get("files", [])}
today_s = date.today().strftime("%Y-%m-%d")

added = 0
for png in parlay_pngs:
    base = os.path.basename(png)
    enc  = base.replace(" ", "%20").replace("#", "%23")
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", base)
    img_date = date_m.group(1) if date_m else today_s
    subtype  = "today" if img_date == today_s else "archive"

    if base in existing_names:
        # Actualizar subtype y url por si acaso
        for fi in manifest["files"]:
            if fi["name"] == base:
                fi["url"]     = f"{PAGES_URL}/{enc}"
                fi["subtype"] = subtype
        print(f"  🔄 Actualizado en manifest: {base}")
    else:
        manifest["files"].insert(0, {
            "name":    base,
            "url":     f"{PAGES_URL}/{enc}",
            "type":    "mypick_img",
            "subtype": subtype,
            "date":    img_date,
            "game":    "",
        })
        existing_names.add(base)
        added += 1
        print(f"  ➕ Agregado al manifest: {base}")

# ── 4. Guardar manifest ──────────────────────────────────────────────────
with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
print(f"\n  💾 manifest.json actualizado ({len(manifest['files'])} archivos)")

# ── 5. Git add / commit / push ───────────────────────────────────────────
def git(args):
    r = subprocess.run(["git", "-C", REPO] + args, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if out: print(f"     {out}")
    return r.returncode

print(f"\n  📤 Publicando en GitHub Pages...")
git(["add", "--all"])

code, _, _ = (lambda r: (r.returncode, r.stdout, r.stderr))(
    subprocess.run(["git", "-C", REPO, "commit", "-m",
                    f"parlay card + manifest fix"],
                   capture_output=True, text=True))

# Re-run to get output
r = subprocess.run(["git", "-C", REPO, "commit", "-m", "parlay card + manifest fix"],
                   capture_output=True, text=True)
out = (r.stdout + r.stderr).strip()
if "nothing to commit" in out:
    print("  ℹ️  Sin cambios nuevos — forzando push igual...")
elif r.returncode != 0:
    print(f"  ⚠️  commit: {out}")

push_r = subprocess.run(["git", "-C", REPO, "push"], capture_output=True, text=True)
push_out = (push_r.stdout + push_r.stderr).strip()
if push_r.returncode == 0:
    print(f"\n  ✅ PUBLICADO!")
    for png in parlay_pngs:
        base = os.path.basename(png)
        enc  = base.replace(" ", "%20").replace("#", "%23")
        print(f"     {PAGES_URL}/{enc}")
else:
    print(f"\n  ❌ git push falló: {push_out}")
    print(f"     Verifica tu conexión SSH/HTTPS con GitHub.")

print()
