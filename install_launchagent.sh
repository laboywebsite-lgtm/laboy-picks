#!/bin/bash
# ============================================================
#  install_launchagent.sh — Instala el LaunchAgent de macOS
#  Esto hace que start_laboy.sh arranque solo al iniciar sesión
#  y se reinicie automáticamente si falla.
#
#  Uso: bash install_launchagent.sh
# ============================================================

SERVE_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SERVE_DIR/start_laboy.sh"
PLIST="$HOME/Library/LaunchAgents/com.laboy.picks.plist"

# Hacer el script ejecutable
chmod +x "$SCRIPT"

# Crear el plist
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.laboy.picks</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT</string>
    </array>

    <!-- Reiniciar automáticamente si el proceso muere -->
    <key>KeepAlive</key>
    <true/>

    <!-- Arrancar al iniciar sesión -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Logs del sistema (adicionales a los de logs/) -->
    <key>StandardOutPath</key>
    <string>$SERVE_DIR/logs/launchd_out.log</string>
    <key>StandardErrorPath</key>
    <string>$SERVE_DIR/logs/launchd_err.log</string>

    <!-- Espera 5s antes de reiniciar si falla -->
    <key>ThrottleInterval</key>
    <integer>5</integer>
</dict>
</plist>
EOF

echo "✅ Plist creado en: $PLIST"

# Cargar el agente ahora mismo (sin reiniciar)
launchctl unload "$PLIST" 2>/dev/null
launchctl load -w "$PLIST"

echo ""
echo "✅ LaunchAgent instalado y activo."
echo ""
echo "   🟢 El server arranca solo cuando inicias sesión en la Mac."
echo "   🟢 Si serve.py o ngrok se caen, se reinician solos en ~30s."
echo "   🟢 La Mac no duerme mientras esté enchufada."
echo ""
echo "   Para ver logs:    tail -f \"$SERVE_DIR/logs/laboy.log\""
echo "   Para detenerlo:   launchctl unload \"$PLIST\""
echo "   Para reinstalar:  bash \"$0\""
echo ""
echo "─────────────────────────────────────────────────────────"
echo "  PRÓXIMO PASO: Configura un dominio estático en ngrok"
echo "  1. Ve a https://dashboard.ngrok.com/domains"
echo "  2. Crea un dominio gratis (ej: laboy-picks.ngrok-free.app)"
echo "  3. Abre start_laboy.sh y pon tu dominio en NGROK_DOMAIN="
echo "  Así la URL nunca cambia aunque ngrok se reinicie."
echo "─────────────────────────────────────────────────────────"
