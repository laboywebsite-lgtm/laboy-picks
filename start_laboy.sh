#!/bin/bash
# ============================================================
#  start_laboy.sh — Laboy Picks · Auto-restart server
#  Levanta serve.py + ngrok y los reinicia si se caen.
#  También evita que la Mac duerma mientras esté enchufada.
# ============================================================

# ── Configuración ────────────────────────────────────────────
SERVE_DIR="$(cd "$(dirname "$0")" && pwd)"   # carpeta donde está este script
PORT=5001
LOG_DIR="$SERVE_DIR/logs"

# Dominio estático de ngrok (ngrok.com → Domains → New Domain → copia el tuyo)
# Si lo dejas vacío usa ngrok sin dominio fijo (URL cambia cada reinicio)
NGROK_DOMAIN=""

# Ruta al binario de ngrok (ajusta si es diferente)
NGROK_BIN="$(which ngrok 2>/dev/null || echo '/usr/local/bin/ngrok')"

# Python
PYTHON_BIN="$(which python3)"
# ─────────────────────────────────────────────────────────────

mkdir -p "$LOG_DIR"

echo "[$(date)] ▶ Laboy Picks server iniciando..." | tee -a "$LOG_DIR/laboy.log"

# ── Evitar que la Mac duerma mientras esté enchufada ─────────
# -s = solo previene sleep cuando está en power adapter
caffeinate -s &
CAFF_PID=$!
echo "[$(date)] ☕ caffeinate PID $CAFF_PID" >> "$LOG_DIR/laboy.log"

# ── Función: iniciar serve.py ────────────────────────────────
start_serve() {
    echo "[$(date)] 🚀 Iniciando serve.py (puerto $PORT)..." >> "$LOG_DIR/laboy.log"
    cd "$SERVE_DIR"
    "$PYTHON_BIN" serve.py --port "$PORT" >> "$LOG_DIR/serve.log" 2>&1 &
    SERVE_PID=$!
    echo "[$(date)] serve.py PID $SERVE_PID" >> "$LOG_DIR/laboy.log"
}

# ── Función: iniciar ngrok ───────────────────────────────────
start_ngrok() {
    # Espera a que serve.py esté listo
    sleep 3

    if [ -n "$NGROK_DOMAIN" ]; then
        echo "[$(date)] 🌐 Iniciando ngrok con dominio fijo: $NGROK_DOMAIN" >> "$LOG_DIR/laboy.log"
        "$NGROK_BIN" http --domain="$NGROK_DOMAIN" "$PORT" >> "$LOG_DIR/ngrok.log" 2>&1 &
    else
        echo "[$(date)] 🌐 Iniciando ngrok (URL dinámica)..." >> "$LOG_DIR/laboy.log"
        "$NGROK_BIN" http "$PORT" >> "$LOG_DIR/ngrok.log" 2>&1 &
    fi
    NGROK_PID=$!
    echo "[$(date)] ngrok PID $NGROK_PID" >> "$LOG_DIR/laboy.log"
}

# ── Cleanup al salir ─────────────────────────────────────────
cleanup() {
    echo "[$(date)] 🛑 Deteniendo todo..." >> "$LOG_DIR/laboy.log"
    kill $CAFF_PID $SERVE_PID $NGROK_PID 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

# ── Loop principal: verifica cada 30s y reinicia si mueren ───
start_serve
start_ngrok

while true; do
    sleep 30

    # ¿Sigue vivo serve.py?
    if ! kill -0 "$SERVE_PID" 2>/dev/null; then
        echo "[$(date)] ⚠️  serve.py muerto — reiniciando..." >> "$LOG_DIR/laboy.log"
        start_serve
    fi

    # ¿Sigue vivo ngrok?
    if ! kill -0 "$NGROK_PID" 2>/dev/null; then
        echo "[$(date)] ⚠️  ngrok muerto — reiniciando..." >> "$LOG_DIR/laboy.log"
        start_ngrok
    fi
done
