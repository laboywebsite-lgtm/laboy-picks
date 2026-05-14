#!/usr/bin/env python3
"""
publish_dashboard.py — Publica el dashboard principal a GitHub Pages.

Uso:
    python3 publish_dashboard.py

Requiere:
    - Repo clonado localmente (ver GITHUB_PAGES_REPO abajo)
    - git push con acceso SSH/HTTPS configurado

Repo: https://github.com/laboywebsite-lgtm/laboy-picks
URL:  https://laboywebsite-lgtm.github.io/laboy-picks/dashboard-Lb9x3Kw.html
"""

import os, sys, shutil, subprocess
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Path al clon local del repo laboy-picks
GITHUB_PAGES_REPO = os.environ.get(
    "LABOY_DASHBOARD_REPO",
    os.path.join(os.path.expanduser("~"), "repos", "laboy-picks")
)

GITHUB_PAGES_URL  = "https://laboywebsite-lgtm.github.io/laboy-picks"
DASHBOARD_TOKEN   = "Lb9x3Kw"
DASHBOARD_FILE    = f"dashboard-{DASHBOARD_TOKEN}.html"
CLONE_URL         = "https://github.com/laboywebsite-lgtm/laboy-picks"


def _git(repo, args):
    r = subprocess.run(["git", "-C", repo] + args, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def publish():
    repo = GITHUB_PAGES_REPO

    if not os.path.isdir(repo):
        print(f"\n  ❌ Repo no encontrado: {repo}")
        print(f"     Clona el repo primero:")
        print(f"     git clone {CLONE_URL} {repo}")
        print(f"     O define: export LABOY_DASHBOARD_REPO=/tu/path/laboy-picks")
        sys.exit(1)

    # ── Copiar dashboard HTML al repo ──────────────────────────────────────
    src  = os.path.join(SCRIPT_DIR, DASHBOARD_FILE)
    dest = os.path.join(repo, DASHBOARD_FILE)

    if not os.path.isfile(src):
        print(f"  ❌ No se encontró: {src}")
        sys.exit(1)

    shutil.copy2(src, dest)
    print(f"  📋 Copiado: {DASHBOARD_FILE}")

    # ── .nojekyll — necesario para que GitHub Pages sirva manifest.json ─────
    with open(os.path.join(repo, ".nojekyll"), "w") as f:
        f.write("")

    # ── index.html en blanco ───────────────────────────────────────────────
    blank = (
        "<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
        "<title>Laboy Picks</title>"
        "<style>*{margin:0;padding:0}html,body{height:100%;background:#080c12}</style>"
        "</head><body></body></html>\n"
    )
    with open(os.path.join(repo, "index.html"), "w", encoding="utf-8") as f:
        f.write(blank)

    # ── git add / commit ──────────────────────────────────────────────────
    _git(repo, ["add", "--all"])
    msg = f"🎯 Dashboard actualizado {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    code, out, err = _git(repo, ["commit", "-m", msg])

    if code != 0 and "nothing to commit" in (out + err):
        print("\n  ℹ️  Sin cambios nuevos (dashboard idéntico).")
    elif code != 0:
        print(f"\n  ❌ git commit falló: {err or out}")
        sys.exit(1)

    # ── ¿El remoto ya tiene ramas? ────────────────────────────────────────
    _, remote_refs, _ = _git(repo, ["ls-remote", "--heads", "origin"])
    has_remote_branch  = bool(remote_refs.strip())

    if has_remote_branch:
        print("  🔄 git pull --rebase...")
        code, out, err = _git(repo, ["pull", "--rebase"])
        if code != 0:
            print(f"\n  ❌ git pull falló: {err or out}")
            sys.exit(1)

    # ── push ──────────────────────────────────────────────────────────────
    if has_remote_branch:
        code, out, err = _git(repo, ["push"])
    else:
        print("  🔄 git push (primer push)...")
        code, out, err = _git(repo, ["push", "--set-upstream", "origin", "main"])
        if code != 0:
            code, out, err = _git(repo, ["push", "--set-upstream", "origin", "master"])

    if code != 0:
        print(f"\n  ❌ git push falló: {err or out}")
        print(f"     Verifica acceso SSH/HTTPS.")
        sys.exit(1)

    print(f"\n  ✅ Dashboard publicado en GitHub Pages!")
    print(f"\n  📱 URL principal (guarda en iPhone):")
    print(f"     {GITHUB_PAGES_URL}/{DASHBOARD_FILE}")
    print()


if __name__ == "__main__":
    publish()
