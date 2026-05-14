# MLB Model — To-Do List (Mejoras Pendientes)

> Basado en el documento de ChatGPT + análisis propio.
> Última actualización: Abril 2026

---

## ✅ YA IMPLEMENTADO

- wRC+ platoon (vs LHP / vs RHP)
- xFIP + TTO (platoon vs bullpen)
- Park Factor
- Clima / ADI (temperatura, viento, humedad, altitud)
- Umpire factor (K% histórico)
- Form L10 (racha últimas 10)
- Rest factor (días de descanso)
- Standings factor (win% temporada)
- SP recent ERA (últimas 5 salidas, blend 60/40 con xFIP)
- Bullpen fatigue (IP últimos 3 días)
- Thresholds subidos (ML 5.5%, EV 5%, máx 6 picks/día)

---

## 🔴 ALTA PRIORIDAD

### 1. Lineups confirmados
- Usar lineup real del día (BaseballPress / RotoWire API)
- Recalcular wRC+ ponderado por el orden real de bateo
- **Impacto:** el mayor gap actual. El modelo usa promedio del equipo completo.

### 2. Rolling 14-day wRC+ ofensivo
- Forma ofensiva reciente del equipo (no solo W/L de L10)
- Complementa el win% y el L10 con producción real de carreras
- Fuente: MLB Stats API gamelog por equipo

### 3. Home/Away wRC+ splits
- Los equipos visita rinden ~5-8% menos que en casa
- FanGraphs tiene splits home/away
- Aplicar factor separado para away team

### 4. Fractional Kelly Bet Sizing
- Fórmula: `f = (edge) / (odds - 1)` → usar 25-33% del Kelly completo
- No requiere datos externos, solo matemática
- **Output:** campo `kelly_pct` en cada pick → recomendación de tamaño de apuesta

---

## 🟡 PRIORIDAD MEDIA

### 5. K% y BB% del SP
- Mejor diagnóstico de calidad del pitcher que xFIP solo
- SP con K% alto = más dominante aunque xFIP sea similar
- Fuente: statsapi (season stats por pitcher)

### 6. GB/FB profile del SP
- GB pitchers suprimen HRs en parks HR-friendly
- Interacción con Park Factor
- Fuente: FanGraphs o Baseball Savant

### 7. Disponibilidad del closer
- ¿Está disponible el mejor relevista en juego cerrado?
- IP últimas 48-72h del closer titular
- Fuente: statsapi boxscores (ya tenemos la estructura de bullpen)

### 8. Presión barométrica
- Completa el modelo ADI (actualmente faltan datos de presión)
- Afecta la densidad del aire y la trayectoria de la pelota
- Fuente: Open-Meteo API (ya usada para temperatura/viento)

### 9. Estado del techo (retractable roof)
- `DOME_TEAMS` existe pero no detecta si el techo está abierto o cerrado
- Un estadio con techo abierto tiene clima real; cerrado = neutral
- Fuente: scraping de RotoBaller / beat writers (complejo)

### 10. Fatiga por viaje
- Viaje costa-este/oeste (cambio de zona horaria ≥3 horas)
- Equipo viajando el mismo día = penalidad
- Fuente: schedule de statsapi (ya disponible)

### 11. Monte Carlo simulation
- 10,000 simulaciones por juego en vez de fórmula directa
- Distribución de probabilidades más robusta
- Mayor impacto en juegos con incertidumbre alta (SP desconocido, clima extremo)

---

## 🟢 PRIORIDAD BAJA (requieren nuevas fuentes de datos)

### 12. xwOBA / Exit Velocity (Baseball Savant)
- Mejor métrica de contacto que wRC+ solo
- Detecta "batters de suerte" vs batters legítimos
- Fuente: baseballsavant.mlb.com (Statcast API)

### 13. OAA / DRS — Métricas de defensa
- La defensa afecta runs permitidos ~0.2-0.4 por juego en extremos
- Fuente: Baseball Savant (OAA) / FanGraphs (DRS)

### 14. Pitch mix matchup modeling
- Cómo le va al tipo de bateador vs el tipo de pitcher específico
- (ej. pull hitters vs sinkers, fly ball hitters vs curveball pitchers)
- Requiere modelo de categorización de bateadores

### 15. Velocity trend analysis
- Caída de velocidad del SP en últimas salidas = indicador de fatiga o lesión
- Fuente: Baseball Savant Statcast

### 16. CLV Tracking (Closing Line Value)
- Comparar nuestros picks vs la línea de cierre
- Si el modelo consistentemente "bate" la línea de cierre = edge real
- Implementar en record-tracking actual

### 17. Market resistance / Sharp money detection
- Detectar cuando la línea se mueve contra el consenso público
- Señal de dinero sharp (profesional) en el otro lado
- Fuente: Action Network API o similar

### 18. Catcher framing impact
- Catcher elite en framing puede valer +0.2 a +0.3 carreras por juego
- Fuente: Baseball Savant framing metrics

---

## 📊 RESUMEN

| Prioridad | Items | Dificultad |
|-----------|-------|------------|
| 🔴 Alta   | 4     | Media      |
| 🟡 Media  | 7     | Media-Alta |
| 🟢 Baja   | 7     | Alta       |

**Próximo paso recomendado:** Lineups confirmados (#1) — mayor impacto inmediato.
