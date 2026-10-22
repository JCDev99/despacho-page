#!/usr/bin/env bash
# publicar-novedades.sh — regenera y publica /novedades solo si el catálogo cambió.
#
# Pensado para ejecutarse cada 15 minutos desde cron. Consulta la nota más
# reciente de cada fuente en el servicio editorial; si el sello coincide con el
# último publicado, termina sin generar ni copiar nada (coste: una petición HTTP).
#
# Si hay cambio: genera, pasa el arnés del explorador y publica en el CT103.
# Si el arnés falla, NO publica y avisa por Telegram: el sitio sigue sirviendo
# la versión anterior.
#
# Uso: ./publicar-novedades.sh [--forzar]

set -euo pipefail

REPO="/opt/mentor/workspace/despacho-page"
SELLO="/opt/mentor/state/sello-novedades.txt"
LOG="/opt/mentor/state/novedades-publicacion.log"
API="https://dof.jc99.dev/v1/novedades"
PVE="root@192.168.100.200"
CT="103"
DESTINO="/opt/despacho-page"
FORZAR=0
[ "${1:-}" = "--forzar" ] && FORZAR=1

export NODE_PATH="$(npm root -g)"
export PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
export TZ=America/Mexico_City

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

avisar() {
  local token chat
  token=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' /root/.hermes/.env 2>/dev/null | cut -d= -f2- || true)
  chat=$(grep -m1 '^TELEGRAM_CHAT_ID=' /root/.hermes/.env 2>/dev/null | cut -d= -f2- || true)
  chat="${chat:-730898122}"
  if [ -n "${token:-}" ]; then
    curl -s -m 10 "https://api.telegram.org/bot${token}/sendMessage" \
      --data-urlencode "chat_id=${chat}" --data-urlencode "text=$1" >/dev/null 2>&1 || true
  fi
}

# Una sola ejecución a la vez: dos builds simultáneos pisarían la salida.
exec 9>/var/lock/novedades-publicacion.lock
flock -n 9 || { log "otra ejecución en curso; se omite"; exit 0; }

# ── 1. Sello remoto ───────────────────────────────────────────────────────────
remoto=$(python3 - "$API" <<'PY'
import json, sys, urllib.request
api = sys.argv[1]
partes = []
for fuente in ("dof", "pobbc"):
    try:
        peticion = urllib.request.Request(
            f"{api}?fuente={fuente}&limit=1",
            headers={"User-Agent": "CASLEYWeb/1.0 (cron novedades)", "Accept": "application/json"},
        )
        with urllib.request.urlopen(peticion, timeout=25) as r:
            datos = json.loads(r.read().decode())
        it = (datos.get("items") or [{}])[0]
        partes.append(f"{fuente}:{it.get('fecha','')}:{it.get('clave','')}")
    except Exception as exc:  # noqa: BLE001
        codigo = getattr(exc, "code", "")
        partes.append(f"{fuente}:error:{type(exc).__name__}{(':' + str(codigo)) if codigo else ''}")
print("|".join(partes))
PY
)

if printf '%s' "$remoto" | grep -q ':error:'; then
  log "servicio no disponible ($remoto); se reintenta en la próxima pasada"
  exit 1
fi

if [ "$FORZAR" -eq 0 ] && [ -f "$SELLO" ] && [ "$(cat "$SELLO")" = "$remoto" ]; then
  # Heartbeat: deja constancia una vez cada 6 h de que el cron sigue vivo,
  # sin llenar el log con una línea cada 15 minutos.
  if [ -n "$(find "$SELLO" -mmin +360 2>/dev/null)" ]; then
    log "sin cambios; el sello sigue vigente ($remoto)"
    touch "$SELLO"
  fi
  exit 0
fi

log "cambio detectado: $remoto (anterior: $(cat "$SELLO" 2>/dev/null || echo 'ninguno'))"

# ── 2. Generar ────────────────────────────────────────────────────────────────
cd "$REPO"
if ! python3 generador-novedades.py >> "$LOG" 2>&1; then
  log "ERROR en la generación"
  avisar "Novedades: falló la generación. No se ha publicado nada."
  exit 1
fi

# ── 3. Verificar antes de publicar ────────────────────────────────────────────
puerto=$(python3 - <<'PY'
import socket
s = socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()
PY
)
python3 -m http.server "$puerto" --directory "$REPO/v1" >/dev/null 2>&1 &
servidor=$!
trap 'kill "$servidor" 2>/dev/null || true' EXIT

listo=0
for _ in $(seq 1 40); do
  if curl -sf -o /dev/null "http://127.0.0.1:${puerto}/novedades/"; then listo=1; break; fi
  sleep 0.2
done
if [ "$listo" -ne 1 ]; then
  log "ERROR: el servidor de verificación no respondió"
  avisar "Novedades: no arrancó el servidor de verificación. No se publica."
  exit 1
fi

if ! node "$REPO/tests/novedades.cjs" --servido="http://127.0.0.1:${puerto}" >> "$LOG" 2>&1; then
  log "ERROR: el arnés no pasó; se aborta la publicación"
  avisar "Novedades: el arnés detectó un problema. No se ha publicado; la web sigue con la versión anterior."
  exit 1
fi
kill "$servidor" 2>/dev/null || true
trap - EXIT

# ── 4. Publicar (copia atómica al CT103) ─────────────────────────────────────
rm -rf /tmp/pub-nov
mkdir -p /tmp/pub-nov
cp index.html 404.html robots.txt sitemap.xml /tmp/pub-nov/
cp v1/favicon.svg /tmp/pub-nov/
cp -a v1/novedades /tmp/pub-nov/novedades
rm -f /tmp/novedades-pub.tar.gz
tar -czf /tmp/novedades-pub.tar.gz -C /tmp/pub-nov .

if ! scp -q -o BatchMode=yes /tmp/novedades-pub.tar.gz "${PVE}:/tmp/"; then
  log "ERROR al copiar el paquete al PVE"
  avisar "Novedades: no se pudo copiar el paquete al PVE. No se ha publicado."
  exit 1
fi

hoy=$(date +%Y%m%d)
if ! ssh -o BatchMode=yes "$PVE" "pct push ${CT} /tmp/novedades-pub.tar.gz /tmp/novedades-pub.tar.gz && pct exec ${CT} -- bash -lc '[ -d ${DESTINO}.bak-${hoy} ] || cp -a ${DESTINO} ${DESTINO}.bak-${hoy}' && pct exec ${CT} -- tar -xzf /tmp/novedades-pub.tar.gz -C ${DESTINO}" >> "$LOG" 2>&1; then
  log "ERROR al desplegar en el CT${CT}"
  avisar "Novedades: falló el despliegue en el CT${CT}. Revisa el log."
  exit 1
fi

# ── 5. Sello y cierre ────────────────────────────────────────────────────────
printf '%s' "$remoto" > "$SELLO"
notas=$(python3 -c "import json;print(len(json.load(open('v1/novedades/datos.json'))['notas']))" 2>/dev/null || echo "?")
log "publicado: $notas notas · sello $remoto"
