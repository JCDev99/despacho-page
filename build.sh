#!/usr/bin/env bash
# build.sh — Ensamblador determinista de plantillas web para CAS'LEY.
# Arquitectura modular bajo el ciclo de la casa Mentor (mentor-desarrollo-web-casa).
#
# Uso:
#   ./build.sh           Construye y actualiza los 3 destinos (portada, v1, v2)
#   ./build.sh --check   Verifica los 3 destinos contra su EXPECTED sin modificar ficheros
#   ./build.sh --update  Fuerza reconstrucción y re-sella src/EXPECTED de los 3 destinos
#   ./build.sh [root|v1|v2]  Construye un destino específico
#
# Exit codes:
#   0 ok (sin deriva en --check, o build completado)
#   1 falta una parte o error de lectura
#   2 deriva detectada respecto al sello EXPECTED

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(command -v python3 || echo "python3")"

exec "$PYTHON_BIN" - "$SCRIPT_DIR" "$@" <<'PY'
import sys
import os
import hashlib

BASE_DIR = sys.argv[1]
ARGS = sys.argv[2:]

CHECK_MODE = "--check" in ARGS
UPDATE_MODE = "--update" in ARGS or (len(ARGS) == 0)

TARGETS = {
    "root": {
        "name": "Portada (Índice)",
        "src_dir": os.path.join(BASE_DIR, "src"),
        "output": os.path.join(BASE_DIR, "index.html"),
        "sello": os.path.join(BASE_DIR, "src", "EXPECTED"),
        "manifest": [
            "html/00-head-open.html",
            "css/10-portada.css",
            "html/20-head-close-body.html",
            "html/30-header-hero.html",
            "html/40-plantillas-comparativa.html",
            "html/50-footer.html",
            "html/60-script-open.html",
            "js/10-portada.js",
            "html/99-body-close.html",
        ]
    },
    "v1": {
        "name": "Variante v1 (Institucional Sobria)",
        "src_dir": os.path.join(BASE_DIR, "v1", "src"),
        "output": os.path.join(BASE_DIR, "v1", "index.html"),
        "sello": os.path.join(BASE_DIR, "v1", "src", "EXPECTED"),
        "manifest": [
            "html/00-head-open.html",
            "css/10-variables.css",
            "css/20-reset-base.css",
            "css/30-layout-grid.css",
            "css/40-components.css",
            "css/50-responsive.css",
            "html/10-head-close-nav.html",
            "html/20-hero.html",
            "html/30-areas-practica.html",
            "html/40-confianza-valores.html",
            "html/50-abogados.html",
            "html/60-proceso.html",
            "html/70-contacto-horario.html",
            "html/80-footer-aviso.html",
            "html/90-script-open.html",
            "js/10-menu-movil.js",
            "js/20-a11y-focus.js",
            "html/99-body-close.html",
        ]
    },
    "v2": {
        "name": "Variante v2 (Editorial Contemporánea)",
        "src_dir": os.path.join(BASE_DIR, "v2", "src"),
        "output": os.path.join(BASE_DIR, "v2", "index.html"),
        "sello": os.path.join(BASE_DIR, "v2", "src", "EXPECTED"),
        "manifest": [
            "html/00-head-open.html",
            "css/10-variables.css",
            "css/20-reset-editorial.css",
            "css/30-asymmetric-layout.css",
            "css/40-editorial-typography.css",
            "css/50-responsive-editorial.css",
            "html/10-head-close-nav.html",
            "html/20-hero.html",
            "html/30-areas-practica.html",
            "html/40-confianza-valores.html",
            "html/50-abogados.html",
            "html/60-proceso.html",
            "html/70-contacto-horario.html",
            "html/80-footer-aviso.html",
            "html/90-script-open.html",
            "js/10-menu-movil.js",
            "js/20-interaccion-areas.js",
            "html/99-body-close.html",
        ]
    }
}

def leer_sello(ruta_sello):
    if not os.path.exists(ruta_sello):
        return None, None, None
    datos = {}
    with open(ruta_sello, "r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            datos[k.strip().lower()] = v.strip()
    partes = int(datos["partes"]) if "partes" in datos and datos["partes"].isdigit() else None
    nbytes = int(datos["bytes"]) if "bytes" in datos and datos["bytes"].isdigit() else None
    md5 = datos.get("md5")
    return partes, nbytes, md5

def escribir_sello(ruta_sello, partes, nbytes, md5_val, nombre_destino):
    os.makedirs(os.path.dirname(ruta_sello), exist_ok=True)
    contenido = [
        f"# Sello de integridad de {nombre_destino}\n",
        f"# Generado automáticamente por build.sh. No editar a mano.\n",
        f"partes={partes}\n",
        f"bytes={nbytes}\n",
        f"md5={md5_val}\n"
    ]
    with open(ruta_sello, "w", encoding="utf-8") as fh:
        fh.writelines(contenido)

def componer(cfg):
    src_dir = cfg["src_dir"]
    manifest = cfg["manifest"]
    buf = bytearray()
    for rel_p in manifest:
        full_p = os.path.join(src_dir, rel_p)
        if not os.path.exists(full_p):
            print(f"ERROR: Falta parte requerida: {full_p}", file=sys.stderr)
            return None
        with open(full_p, "rb") as fh:
            buf.extend(fh.read())
    return bytes(buf)

def md5_fichero(ruta):
    if not os.path.exists(ruta):
        return None
    with open(ruta, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()

def procesar_destino(clave, cfg, check_only, update_seal):
    buffer = componer(cfg)
    if buffer is None:
        return 1
    total_bytes = len(buffer)
    calc_md5 = hashlib.md5(buffer).hexdigest()
    num_partes = len(cfg["manifest"])

    sello_partes, sello_bytes, sello_md5 = leer_sello(cfg["sello"])
    output_path = cfg["output"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if check_only:
        if sello_md5 is None or sello_bytes is None:
            print(f"[FAIL] {cfg['name']}: Falta sello {cfg['sello']}", file=sys.stderr)
            return 1
        disco_md5 = md5_fichero(output_path)
        disco_bytes = os.path.getsize(output_path) if disco_md5 else None

        src_ok = (calc_md5 == sello_md5 and total_bytes == sello_bytes)
        disco_ok = (disco_md5 == sello_md5 and disco_bytes == sello_bytes)

        if not (src_ok and disco_ok):
            print(f"[FAIL] Deriva detectada en {cfg['name']}:", file=sys.stderr)
            print(f"  Sello EXPECTED : {sello_md5} · {sello_bytes} B", file=sys.stderr)
            print(f"  src/ ensamblado: {calc_md5} · {total_bytes} B ({'OK' if src_ok else 'DERIVA'})", file=sys.stderr)
            print(f"  index.html     : {disco_md5 or 'ausente'} · {disco_bytes or '-'} B ({'OK' if disco_ok else 'DERIVA'})", file=sys.stderr)
            return 2
        return 0

    # Modo construcción / update
    tmp_out = output_path + ".tmp"
    with open(tmp_out, "wb") as fh:
        fh.write(buffer)
    os.replace(tmp_out, output_path)

    escribir_sello(cfg["sello"], num_partes, total_bytes, calc_md5, cfg["name"])
    print(f"[BUILD] {cfg['name']}: {num_partes} partes -> {output_path} ({total_bytes} B, md5={calc_md5})")
    return 0

# Determinar qué destinos procesar
seleccion = [a for a in ARGS if a in TARGETS]
if not seleccion:
    seleccion = ["root", "v1", "v2"]

codigos = []
for k in seleccion:
    rc = procesar_destino(k, TARGETS[k], CHECK_MODE, UPDATE_MODE)
    codigos.append(rc)

max_rc = max(codigos) if codigos else 0
if CHECK_MODE:
    if max_rc == 0:
        print("[OK] sin deriva: sello, src/ e index.html son el mismo contenido.")
    sys.exit(max_rc)

sys.exit(max_rc)
PY
