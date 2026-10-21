#!/usr/bin/env bash
# tests/verificar.sh — Verificación completa bajo el ciclo de la casa Mentor.
# Orquesta:
#   1. ./build.sh --check (integridad de sello y piezas)
#   2. Servidor estático HTTP en puerto libre
#   3. Paridad md5 servido vs disco (portada, v1, v2)
#   4. Control negativo del docroot (404 en respaldos .bak)
#   5. Ejecución del arnés Playwright sobre lo servido
#   6. Salida final: VEREDICTO verificar: OK

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== 1. VERIFICACIÓN DE ENSAMBLADO Y SELLO SIN DERIVA ==="
cd "$REPO_ROOT"
./build.sh --check

echo ""
echo "=== 2. LEVANTANDO SERVIDOR ESTÁTICO HTTP EN PUERTO LIBRE ==="
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')"
echo "Puerto asignado: $PORT"

python3 -m http.server "$PORT" --directory "$REPO_ROOT" > /dev/null 2>&1 &
SERVER_PID=$!

cleanup() {
  for pid in "${SERVER_PID:-}" "${SERVER_NOV_PID:-}"; do
    if [ -n "$pid" ]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

# Esperar a que el servidor responda
python3 - "$PORT" <<'PY'
import sys, time, urllib.request
port = sys.argv[1]
url = f"http://127.0.0.1:{port}/index.html"
for _ in range(30):
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            if resp.status == 200:
                sys.exit(0)
    except Exception:
        time.sleep(0.1)
sys.exit(1)
PY
echo "Servidor HTTP activo en http://127.0.0.1:$PORT"

echo ""
echo "=== 3. PARIDAD SERVIDO VS DISCO (MD5) ==="
python3 - "$PORT" "$REPO_ROOT" <<'PY'
import sys, os, urllib.request, hashlib

port = sys.argv[1]
root = sys.argv[2]

destinos = [
    ("Portada", "index.html"),
    ("Variante v1", "v1/index.html"),
    ("Variante v2", "v2/index.html")
]

fallos = 0
for nombre, rel_path in destinos:
    url = f"http://127.0.0.1:{port}/{rel_path}"
    file_path = os.path.join(root, rel_path)

    # MD5 disco
    with open(file_path, "rb") as fh:
        disco_bytes = fh.read()
    disco_md5 = hashlib.md5(disco_bytes).hexdigest()
    disco_tam = len(disco_bytes)

    # MD5 servido
    req = urllib.request.Request(url, headers={"User-Agent": "Mentor-Verificar/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        servido_bytes = resp.read()
    servido_md5 = hashlib.md5(servido_bytes).hexdigest()
    servido_tam = len(servido_bytes)

    if disco_md5 == servido_md5 and disco_tam == servido_tam:
        print(f"  [PARIDAD OK] {nombre} ({rel_path}):")
        print(f"    - Disco   : {disco_md5} ({disco_tam} B)")
        print(f"    - Servido : {servido_md5} ({servido_tam} B)")
    else:
        print(f"  [PARIDAD FALLO] {nombre} ({rel_path}):")
        print(f"    - Disco   : {disco_md5} ({disco_tam} B)")
        print(f"    - Servido : {servido_md5} ({servido_tam} B)")
        fallos += 1

if fallos > 0:
    sys.exit(1)
sys.exit(0)
PY

echo ""
echo "=== 4. CONTROL NEGATIVO DEL DOCROOT (RESPALDOS .BAK) ==="
CONTROL_NEGATIVO_RES="$(python3 - "$PORT" <<'PY'
import sys, urllib.request, urllib.error

port = sys.argv[1]
urls_negativas = [
    f"http://127.0.0.1:{port}/index.html.bak",
    f"http://127.0.0.1:{port}/v1/index.html.bak",
    f"http://127.0.0.1:{port}/v2/index.html.old"
]

fallos = 0
statuses = []
for u in urls_negativas:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mentor-Verificar/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  [FAIL] URL de respaldo expuesta con HTTP {resp.status}: {u}", file=sys.stderr)
            fallos += 1
            statuses.append(resp.status)
    except urllib.error.HTTPError as e:
        statuses.append(e.code)
        if e.code == 404:
            print(f"  [CONTROL NEGATIVO OK] {u} -> HTTP 404 (No expuesto)", file=sys.stderr)
        else:
            print(f"  [CONTROL NEGATIVO AVISO] {u} -> HTTP {e.code}", file=sys.stderr)
    except Exception as e:
        print(f"  [CONTROL NEGATIVO ERROR] {u} -> {e}", file=sys.stderr)
        fallos += 1

if fallos > 0 or not statuses or any(s != 404 for s in statuses):
    sys.exit(1)

sys.stdout.write("HTTP 404")
sys.exit(0)
PY
)"
echo "  Veredicto derivado control negativo: $CONTROL_NEGATIVO_RES"

echo ""
echo "=== 5. MEDICIÓN FUNCIONAL CON ARNÉS PLAYWRIGHT SOBRE LO SERVIDO ==="
export NODE_PATH="$(npm root -g)"
export PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
node "$REPO_ROOT/tests/arnes.cjs" --servido="http://127.0.0.1:$PORT"
ARNES_RC=$?

if [ "$ARNES_RC" -ne 0 ]; then
  echo "ERROR: El arnés Playwright falló con código $ARNES_RC" >&2
  exit "$ARNES_RC"
fi

echo ""
echo "=== 5b. ARNÉS DEL EXPLORADOR DE NOVEDADES (RAÍZ = v1, COMO EN PRODUCCIÓN) ==="
PORT_NOV="$(python3 -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')"
python3 -m http.server "$PORT_NOV" --directory "$REPO_ROOT/v1" > /dev/null 2>&1 &
SERVER_NOV_PID=$!

python3 - "$PORT_NOV" <<'PY'
import sys, time, urllib.request
url = f"http://127.0.0.1:{sys.argv[1]}/novedades/"
for _ in range(40):
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            if r.status == 200:
                sys.exit(0)
    except Exception:
        time.sleep(0.1)
sys.exit(1)
PY

node "$REPO_ROOT/tests/novedades.cjs" --servido="http://127.0.0.1:$PORT_NOV"

echo ""
echo "=== 6. BALANCE Y VEREDICTO FINAL ==="
PORTADA_MD5="$(md5sum "$REPO_ROOT/index.html" | cut -d' ' -f1)"
PORTADA_BYTES="$(stat -c %s "$REPO_ROOT/index.html")"
V1_MD5="$(md5sum "$REPO_ROOT/v1/index.html" | cut -d' ' -f1)"
V1_BYTES="$(stat -c %s "$REPO_ROOT/v1/index.html")"
V2_MD5="$(md5sum "$REPO_ROOT/v2/index.html" | cut -d' ' -f1)"
V2_BYTES="$(stat -c %s "$REPO_ROOT/v2/index.html")"

echo "Cifras de entrega verificadas (disco):"
echo "  - Portada : $PORTADA_MD5 ($PORTADA_BYTES B)"
echo "  - v1      : $V1_MD5 ($V1_BYTES B)"
echo "  - v2      : $V2_MD5 ($V2_BYTES B)"

python3 - "$REPO_ROOT" "$CONTROL_NEGATIVO_RES" <<'PY'
import sys, os, json

repo_root = sys.argv[1]
control_negativo = sys.argv[2]

path_v1 = os.path.join(repo_root, "tests", "informe-v1.json")
path_v2 = os.path.join(repo_root, "tests", "informe-v2.json")

if not os.path.exists(path_v1):
    print(f"ERROR: No existe {path_v1}", file=sys.stderr)
    sys.exit(1)
if not os.path.exists(path_v2):
    print(f"ERROR: No existe {path_v2}", file=sys.stderr)
    sys.exit(1)

with open(path_v1, "r", encoding="utf-8") as f:
    inv1 = json.load(f)
with open(path_v2, "r", encoding="utf-8") as f:
    inv2 = json.load(f)

# 1. Desbordes reales derivados
d_v1 = inv1.get("desbordesReales", {})
d_v2 = inv2.get("desbordesReales", {})
desb_v1_str = f"{d_v1.get('1440px')}/{d_v1.get('390px')}/{d_v1.get('360px')} px"
desb_v2_str = f"{d_v2.get('1440px')}/{d_v2.get('390px')}/{d_v2.get('360px')} px"

# 2. Errores consola derivados
err_v1 = len(inv1.get("erroresConsola", []))
err_v2 = len(inv2.get("erroresConsola", []))

# 3. Peticiones externas derivadas
pet_v1 = len(inv1.get("peticionesExternas", []))
pet_v2 = len(inv2.get("peticionesExternas", []))

# 4. Contraste derivado
ratio_v1 = inv1.get("contraste", {}).get("peorRatio")
ratio_v2 = inv2.get("contraste", {}).get("peorRatio")

# 5. Veredicto del arnés derivado
ver_v1 = inv1.get("veredicto")
ver_v2 = inv2.get("veredicto")

print(f"  - Control negativo .bak: {control_negativo}")
print(f"  - Desbordes reales v1 (1440/390/360): {desb_v1_str}")
print(f"  - Desbordes reales v2 (1440/390/360): {desb_v2_str}")
print(f"  - Errores consola (v1 / v2): {err_v1} / {err_v2}")
print(f"  - Peticiones externas (v1 / v2): {pet_v1} / {pet_v2}")
print(f"  - Contraste peor ratio (v1 / v2): {ratio_v1}:1 / {ratio_v2}:1 (umbral >= 4.5:1)")
print(f"  - Veredicto arnés (v1 / v2): {ver_v1} / {ver_v2}")

# Validación de cifras contra lo esperado
errores = []
if control_negativo != "HTTP 404":
    errores.append(f"Control negativo no devolvió HTTP 404: '{control_negativo}'")
if desb_v1_str != "0/0/0 px":
    errores.append(f"Desbordes reales v1 no son 0/0/0 px: {desb_v1_str}")
if desb_v2_str != "0/0/0 px":
    errores.append(f"Desbordes reales v2 no son 0/0/0 px: {desb_v2_str}")
if err_v1 != 0 or err_v2 != 0:
    errores.append(f"Errores en consola no vacíos (v1={err_v1}, v2={err_v2})")
if pet_v1 != 0 or pet_v2 != 0:
    errores.append(f"Peticiones externas no vacías (v1={pet_v1}, v2={pet_v2})")
if ratio_v1 is None or ratio_v1 < 4.5:
    errores.append(f"Peor contraste v1 ({ratio_v1}) por debajo de 4.5:1")
if ratio_v2 is None or ratio_v2 < 4.5:
    errores.append(f"Peor contraste v2 ({ratio_v2}) por debajo de 4.5:1")
if ver_v1 != "OK" or ver_v2 != "OK":
    errores.append(f"Veredicto arnés no es OK (v1={ver_v1}, v2={ver_v2})")

if errores:
    print("\n[FAIL] Comprobación de evidencia derivada fallida:", file=sys.stderr)
    for e in errores:
        print(f"  - {e}", file=sys.stderr)
    sys.exit(1)

print("\nVEREDICTO verificar: OK")
sys.exit(0)
PY

