#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Laboy Picks — Setup GitHub backup
#  Corre esto en tu Terminal desde la carpeta Data Analysis
#  Ejemplo: cd ~/ruta/a/"Data Analysis" && bash setup_github.sh
# ═══════════════════════════════════════════════════════════════
set -e

REPO_NAME="laboy-picks"
GITHUB_USER="laboywebsite-lgtm"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "═══════════════════════════════════════"
echo "  Laboy Picks — GitHub Backup Setup"
echo "═══════════════════════════════════════"
echo ""
echo "📁 Carpeta: $DIR"
echo ""

cd "$DIR"

# 1. Limpiar git anterior si estaba roto
if [ -d ".git" ]; then
  echo "🗑  Removiendo .git anterior..."
  rm -rf .git
fi

# 2. Init
echo "🔧 Inicializando repositorio..."
git init
git branch -M main
git config user.email "laboywebsite@gmail.com"
git config user.name "Jose Laboy"

# 3. Add + Commit
echo "📦 Agregando archivos..."
git add .
echo "💾 Creando commit inicial..."
git commit -m "🔒 Backup inicial — Laboy Picks $(date '+%Y-%m-%d')"

echo ""
echo "✅ Repositorio local listo."
echo ""

# 4. Crear repo en GitHub (necesitas gh CLI o hacerlo manualmente)
if command -v gh &> /dev/null; then
  echo "🐙 Creando repositorio privado en GitHub..."
  gh repo create "$GITHUB_USER/$REPO_NAME" --private --source=. --remote=origin --push
  echo ""
  echo "✅ ¡Listo! Tu proyecto está en:"
  echo "   https://github.com/$GITHUB_USER/$REPO_NAME"
else
  echo "─────────────────────────────────────────────"
  echo "  Paso manual: crear el repo en GitHub"
  echo "─────────────────────────────────────────────"
  echo ""
  echo "  1. Ve a: https://github.com/new"
  echo "  2. Repository name: $REPO_NAME"
  echo "  3. ✅ Private"
  echo "  4. ❌ NO marques 'Add README' (dejarlo vacío)"
  echo "  5. Click 'Create repository'"
  echo ""
  echo "  Luego corre estos comandos:"
  echo ""
  echo "  git remote add origin https://github.com/$GITHUB_USER/$REPO_NAME.git"
  echo "  git push -u origin main"
  echo ""
fi

echo "═══════════════════════════════════════"
echo "  Para futuros backups, solo corre:"
echo ""
echo "  cd \"$DIR\""
echo "  git add . && git commit -m \"backup \$(date '+%Y-%m-%d')\" && git push"
echo "═══════════════════════════════════════"
