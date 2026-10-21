#!/usr/bin/env python3
"""Generador estático de la sección de Novedades de CAS'LEY.

Lee la API interna del DOF (o un snapshot local) y escribe páginas estáticas
en `v1/novedades/`. El sitio publicado NO llama a la API en tiempo de ejecución:
todo se compone aquí y se sirve como ficheros.

El explorador de `/novedades/` filtra en el navegador sobre `datos.json`
(fuente oficial, tema, tipo, emisor, rango de fechas y búsqueda de texto).
Las páginas por materia y las fichas se sirven completas en HTML para que
funcionen sin JavaScript y sean indexables.

Uso:
    python3 generador-novedades.py              # descarga de la API y regenera
    python3 generador-novedades.py --offline    # usa el snapshot guardado
    python3 generador-novedades.py --limite 60  # acota el número de notas

Determinismo: no se usa la hora actual. El `lastBuildDate` del RSS y el pie de
página usan la fecha de la nota más reciente, para que dos ejecuciones con los
mismos datos produzcan bytes idénticos.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
SALIDA = BASE / "v1" / "novedades"
SRC_UI = BASE / "v1" / "src" / "novedades"
SNAPSHOT = BASE / "v1" / "src" / "novedades-snapshot.json"
API = "https://dof.jc99.dev/v1/novedades"
SITIO = "https://despacho.jc99.dev"
MIN_RELEVANCIA = 80
TITULO_SITIO = "CAS'LEY — Asesoría Jurídica Profesional"
NOTAS_EN_HTML = 12  # las que se sirven sin JS; el explorador pagina de 12 en 12

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

# Fuentes oficiales previstas. El filtro se puebla solo con las que traigan
# notas; las demás se anuncian como pendientes de ingesta, sin inventar datos.
FUENTES = {
    "DOF": {"nombre": "Diario Oficial de la Federación", "corto": "DOF", "url": "https://www.dof.gob.mx/"},
    "POBC": {"nombre": "Periódico Oficial del Estado de Baja California", "corto": "POBC",
             "url": "https://www.bajacalifornia.gob.mx/periodicooficial"},
    "SAT": {"nombre": "Servicio de Administración Tributaria", "corto": "SAT", "url": "https://www.sat.gob.mx/"},
}
FUENTES_PREVISTAS = ("POBC", "SAT")

# Tipos tal como los publica el DOF, normalizados para lectura.
TIPO_LEGIBLE = {
    "RESOLUCION": "Resolución", "ACUERDO": "Acuerdo", "DECRETO": "Decreto",
    "LINEAMIENTOS": "Lineamientos", "CRITERIO": "Criterio", "NOM": "Norma oficial",
    "AVISO": "Aviso", "CIRCULAR": "Circular", "CONVOCATORIA": "Convocatoria",
}

ETIQUETAS_MATERIA = {
    "energia": "Energía",
    "amparo_constitucional": "Amparo constitucional",
    "telecom": "Telecomunicaciones",
    "fiscal": "Fiscal",
    "mercantil": "Mercantil",
    "administrativo": "Administrativo",
    "salud": "Salud",
    "general": "General",
}

# Palabras institucionales que el DOF publica sin acentos en mayúsculas.
LEGIBLE = {
    "SECRETARIA": "Secretaría", "CREDITO": "Crédito", "PUBLICO": "Público",
    "REPUBLICA": "República", "ECONOMIA": "Economía", "ORGANO": "Órgano",
    "ADMINISTRACION": "Administración", "COMISION": "Comisión", "FEDERACION": "Federación",
    "PROTECCION": "Protección", "ENERGIA": "Energía", "GANADERIA": "Ganadería",
    "AGRICULTURA": "Agricultura", "TELECOMUNICACIONES": "Telecomunicaciones",
    "EDUCACION": "Educación", "POBLACION": "Población", "MIGRACION": "Migración",
    "INFORMACION": "Información", "NUTRICION": "Nutrición", "PREVISION": "Previsión",
}
EDICION_LEGIBLE = {"MAT": "Matutina", "VES": "Vespertina", "EXT": "Extraordinaria", "ESP": "Especial"}
MENORES = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "E", "EN", "PARA", "POR", "CON", "A", "AL", "U"}


def plural(n: int, singular: str, plural_: str) -> str:
    return f"{n} {singular if n == 1 else plural_}"


def sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos(t).lower()).strip("-")


def fecha_larga(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return iso
    return f"{d.day} de {MESES[d.month]} de {d.year}"


def fecha_corta(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return iso
    return f"{d.day} {MESES[d.month][:3]} {d.year}"


def etiqueta_materia(m: str) -> str:
    return ETIQUETAS_MATERIA.get(m) or m.replace("_", " ").capitalize()


def emisor_legible(t: str) -> str:
    """'SECRETARIA DE HACIENDA Y CREDITO PUBLICO' → 'Secretaría de Hacienda y Crédito Público'."""
    palabras = (t or "").split()
    salida = []
    for i, p in enumerate(palabras):
        limpio = p.strip(".,;:()")
        if limpio in LEGIBLE:
            salida.append(LEGIBLE[limpio])
        elif limpio.upper() in MENORES and i > 0:
            salida.append(limpio.lower())
        elif len(limpio) <= 4 and limpio.isupper():
            salida.append(limpio)  # siglas: SAT, IMSS, SHCP, CNDH
        else:
            salida.append(limpio.capitalize())
    return " ".join(salida)


def fecha_rfc822(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return d.strftime("%a, %d %b %Y 08:00:00 +0000")


def descargar(limite: int | None) -> list[dict]:
    notas: list[dict] = []
    cursor = None
    for _ in range(10):
        q = {"min_relevancia": MIN_RELEVANCIA, "limit": 100}
        if cursor:
            q["cursor"] = cursor
        url = f"{API}?{urllib.parse.urlencode(q)}"
        peticion = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CASLEYWeb/1.0 (build estatico; contacto jc99.dev)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(peticion, timeout=30) as r:
            datos = json.loads(r.read().decode())
        items = datos.get("items", [])
        notas.extend(items)
        cursor = datos.get("next_cursor")
        if not cursor or not items:
            break
        if limite and len(notas) >= limite:
            break
    if limite:
        notas = notas[:limite]
    return notas


def cargar(limite: int | None, offline: bool) -> list[dict]:
    if offline:
        if not SNAPSHOT.exists():
            sys.exit(f"ERROR: no hay snapshot en {SNAPSHOT}")
        notas = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    else:
        notas = descargar(limite)
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(notas, ensure_ascii=False, indent=1), encoding="utf-8")
    for n in notas:
        n["fuente"] = (n.get("fuente") or "DOF").upper()
        n["emisor"] = n.get("emisor") or n.get("dependencia") or ""
        n["materias"] = n.get("materias") or ["general"]
        tipo = (n.get("tipo") or "").strip()
        n["tipo"] = TIPO_LEGIBLE.get(tipo.upper(), tipo)
    notas.sort(key=lambda n: (n.get("fecha", ""), n.get("codigo", 0)), reverse=True)
    return notas


def materias_de(notas: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for n in notas:
        for m in n.get("materias") or ["general"]:
            idx.setdefault(m, []).append(n)
    return dict(sorted(idx.items()))


# ── Plantilla base ───────────────────────────────────────────────────────────

def pagina(titulo: str, descripcion: str, cuerpo: str, extra_head: str = "",
           canonical: str = "", con_js: bool = False, clase: str = "") -> str:
    can = f'\n  <link rel="canonical" href="{html.escape(canonical)}">' if canonical else ""
    js = '\n  <script src="/novedades/novedades.js" defer></script>' if con_js else ""
    og = (
        f'\n  <meta property="og:type" content="website">'
        f'\n  <meta property="og:site_name" content="{html.escape(TITULO_SITIO)}">'
        f'\n  <meta property="og:title" content="{html.escape(titulo)}">'
        f'\n  <meta property="og:description" content="{html.escape(descripcion)}">'
        f'\n  <meta property="og:locale" content="es_MX">'
        + (f'\n  <meta property="og:url" content="{html.escape(canonical)}">' if canonical else "")
        + '\n  <meta name="twitter:card" content="summary">'
    )
    return f"""<!DOCTYPE html>
<html lang="es" class="{clase}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script>document.documentElement.classList.add('js');</script>
  <title>{html.escape(titulo)}</title>
  <meta name="description" content="{html.escape(descripcion)}">
  <meta name="theme-color" content="#070F18">{can}{og}
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/novedades/novedades.css">
  <link rel="alternate" type="application/rss+xml" title="Novedades oficiales — CAS'LEY" href="/novedades/feed.xml">{extra_head}{js}
</head>
<body>
  <a class="salto" href="#contenido">Saltar al contenido</a>
  <div class="container">
    <div class="top">
      <a class="brand" href="/">CAS'LEY<span>Asesoría Jurídica Profesional</span></a>
      <a class="back" href="/"><span aria-hidden="true">←</span> Volver al sitio</a>
    </div>
  </div>
{cuerpo}
  <div class="container">
    <footer>
      <p><strong>Aviso:</strong> esta sección resume, con carácter informativo, publicaciones oficiales.
      No constituye asesoría jurídica ni sustituye el texto oficial; cada ficha enlaza a su fuente.</p>
      <p>© 2026 CAS'LEY — Asesoría Jurídica Profesional · Calle Novena #252, Fracc. C.D. San Quintín, Baja California, México.</p>
    </footer>
  </div>
</body>
</html>
"""


# ── Piezas del explorador ───────────────────────────────────────────────────

def tarjeta(n: dict, q: str = "") -> str:
    cod = n.get("codigo") or n.get("clave")
    tipo = (n.get("tipo") or "").strip()
    emisor = emisor_legible(n.get("emisor") or "")
    resumen = (n.get("resumen") or "").strip()
    mats = n.get("materias") or []
    etiquetas = "".join(
        f'<a href="/novedades/materia/{slug(m)}.html">{html.escape(etiqueta_materia(m))}</a>'
        for m in mats[:3]
    )
    fuente = n.get("url") or ""
    pdf = n.get("pdf_url") or ""
    fuente_txt = html.escape((n.get("fuente") or "DOF"))
    rel = int(n.get("relevancia") or 0)
    ext = f'<a class="fuente-ext" href="{html.escape(fuente)}" rel="noopener nofollow" target="_blank">Texto oficial ↗</a>' if fuente else ""
    ext_pdf = f'<a class="fuente-ext" href="{html.escape(pdf)}" rel="noopener nofollow" target="_blank">PDF ↗</a>' if pdf and pdf != fuente else ""
    return f"""        <article class="nota">
          <div class="nota__cab">
            <span class="b b--fuente">{fuente_txt}</span>
            <span class="b">{html.escape(tipo)}</span>
            {f'<div class="materias">{etiquetas}</div>' if etiquetas else ''}
            <time class="nota__fecha" datetime="{html.escape(n.get('fecha') or '')}">{html.escape(fecha_corta(n.get('fecha')))}</time>
          </div>
          <h3><a href="/novedades/{cod}.html">{html.escape((n.get('titulo') or '').strip())}</a></h3>
          <p class="nota__emisor">{html.escape(emisor)}</p>
          <p class="nota__resumen">{html.escape(resumen)}</p>
          <div class="nota__pie">
            <a class="cta" href="/novedades/{cod}.html">Leer ficha <span aria-hidden="true">→</span></a>
            {ext}
            {ext_pdf}
            <span class="rel" title="Relevancia estimada {rel} de 100"><span class="rel__lbl">Relevancia</span>{rel}<i style="--v:{max(0, min(100, rel))}%"></i></span>
          </div>
        </article>
"""


def bloque_lista(notas: list[dict]) -> str:
    if not notas:
        return '<p class="lede">No hay publicaciones que mostrar.</p>\n'
    partes = ["        <div class=\"lista\">"]
    fecha_actual = None
    for n in notas:
        if n.get("fecha") != fecha_actual:
            if fecha_actual is not None:
                partes.append("        </div>\n")
                partes.append("        <div class=\"lista\">")
            fecha_actual = n.get("fecha")
            total = sum(1 for x in notas if x.get("fecha") == fecha_actual)
            partes.append(
                f'          <div class="grupo-fecha"><h2>{html.escape(fecha_larga(fecha_actual))}</h2>'
                f'<span class="n-dia">{plural(total, "publicación", "publicaciones")}</span></div>\n'
            )
        partes.append(tarjeta(n))
    partes.append("        </div>\n")
    return "".join(partes)


def panel_filtros(notas: list[dict], idx: dict[str, list[dict]]) -> str:
    fuentes = sorted({n.get("fuente") or "DOF" for n in notas})
    tipos = sorted({(n.get("tipo") or "").strip() for n in notas if (n.get("tipo") or "").strip()})
    emisores = sorted({emisor_legible(n.get("emisor") or "") for n in notas if n.get("emisor")})
    previstas = [f for f in FUENTES_PREVISTAS if f not in fuentes]

    def grupo(titulo: str, faceta: str, valores: list[tuple[str, str, int]]) -> str:
        items = "".join(
            f'<li><label><input type="checkbox" data-faceta="{faceta}" data-valor="{html.escape(v)}">'
            f'<span>{html.escape(e)}</span><span class="n">{c}</span></label></li>'
            for v, e, c in valores
        )
        return f"""        <fieldset class="grupo">
          <legend>{html.escape(titulo)}</legend>
          <ul class="opciones">{items}</ul>
        </fieldset>
"""

    html_fuentes = grupo("Fuente oficial", "fuente", [
        (f, FUENTES.get(f, {}).get("corto", f), sum(1 for n in notas if (n.get("fuente") or "DOF") == f))
        for f in fuentes
    ])
    html_temas = grupo("Tema", "tema", [
        (m, etiqueta_materia(m), len(ns)) for m, ns in idx.items()
    ])
    html_tipos = grupo("Tipo de documento", "tipo", [
        (t, t, sum(1 for n in notas if (n.get("tipo") or "").strip() == t)) for t in tipos
    ])
    opciones_emisor = "".join(
        f'<option value="{html.escape(e)}" data-etiqueta="{html.escape(e)}">{html.escape(e)}</option>'
        for e in emisores
    )
    nota_previstas = (
        '<p class="nota-fuente">Aún sin ingesta: ' + ", ".join(
            f'<abbr title="{html.escape(FUENTES[f]["nombre"])}">{html.escape(f)}</abbr>' for f in previstas
        ) + '. Aparecerán solas cuando la API entregue sus publicaciones.</p>' if previstas else ""
    )
    return f"""      <aside class="filtros solo-js" id="filtros" aria-label="Filtros de publicaciones">
        <div class="panel-cab">
          <h2>Filtros</h2>
          <button type="button" class="limpiar" id="limpiar" hidden>Limpiar todo</button>
        </div>
{html_fuentes}{nota_previstas}
{html_temas}
{html_tipos}
        <fieldset class="grupo">
          <legend>Fecha de publicación</legend>
          <div class="presets" role="group" aria-label="Atajos de fecha">
            <button type="button" class="preset" data-dias="0" aria-pressed="true">Todo</button>
            <button type="button" class="preset" data-dias="7" aria-pressed="false">7 días</button>
            <button type="button" class="preset" data-dias="30" aria-pressed="false">30 días</button>
          </div>
          <div class="campo-fecha">
            <label>Desde <input type="date" id="desde" name="desde"></label>
            <label>Hasta <input type="date" id="hasta" name="hasta"></label>
          </div>
        </fieldset>
        <fieldset class="grupo">
          <legend>Emisor</legend>
          <select id="emisor" aria-label="Filtrar por emisor">
            <option value="">Todos los emisores</option>
            {opciones_emisor}
          </select>
        </fieldset>
        <button type="button" class="btn btn--oro" id="aplicar-movil">Ver resultados</button>
      </aside>
"""


def barra_resultados(total: int) -> str:
    return f"""        <div class="barra">
          <button type="button" class="btn-filtros" id="abrir-filtros" aria-controls="filtros" aria-expanded="false">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18M6 12h12M10 18h4"/></svg>
            Filtros <span class="cuenta" id="cuenta-filtros" hidden>0</span>
          </button>
          <div class="buscador">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
            <input type="search" id="q" placeholder="Buscar por título, emisor o tema" aria-label="Buscar publicaciones" autocomplete="off">
            <button type="button" class="borrar-q" aria-label="Borrar búsqueda" hidden>×</button>
          </div>
          <p class="resultado-cuenta" id="cuenta" aria-live="polite"><b>{total}</b> publicaciones</p>
          <div class="orden">
            <label for="orden">Orden</label>
            <select id="orden">
              <option value="reciente">Más recientes</option>
              <option value="relevancia">Más relevantes</option>
            </select>
          </div>
        </div>
"""


def enlaces_tema(idx: dict[str, list[dict]]) -> str:
    enlaces = "".join(
        f'<li><a href="/novedades/materia/{slug(m)}.html">{html.escape(etiqueta_materia(m))} ({len(ns)})</a></li>'
        for m, ns in idx.items()
    )
    return f"""        <div class="no-js-solo temas-estaticos">
          <h2>Explorar por tema</h2>
          <ul>{enlaces}</ul>
          <p class="nota-fuente">El explorador con filtros de fuente, fecha y búsqueda necesita JavaScript.
          El listado de abajo incluye las publicaciones más recientes.</p>
        </div>
"""


# ── Páginas ─────────────────────────────────────────────────────────────────

def generar_listado(notas: list[dict], idx: dict[str, list[dict]], materia: str | None) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    if materia is None:
        destino = SALIDA / "index.html"
        url = f"{SITIO}/novedades/"
        titulo = "Novedades oficiales — CAS'LEY"
        desc = ("Publicaciones del Diario Oficial de la Federación seleccionadas por relevancia jurídica, "
                "con filtros por fuente, tema, tipo, emisor y fecha.")
        visibles = notas[:NOTAS_EN_HTML]
        cabecera = f"""  <header class="hero">
    <div class="container">
      <p class="kicker">Observatorio normativo</p>
      <h1>Novedades oficiales</h1>
      <p class="lede">Publicaciones del Diario Oficial de la Federación con relevancia para despachos y
        empresas, resumidas en una frase útil y enlazadas a su texto oficial.</p>
      <p class="hero-datos">
        <span><b>{len(idx)}</b> temas</span>
        <span>Última publicación: <b>{html.escape(fecha_corta(notas[0].get('fecha')))}</b></span>
        <span><a href="/novedades/feed.xml">Seguir por RSS</a></span>
      </p>
    </div>
  </header>
"""
        cuerpo = cabecera + f"""  <main id="contenido">
    <div class="container">
      <div class="explorador">
{panel_filtros(notas, idx)}        <div class="columna-resultados">
{enlaces_tema(idx)}{barra_resultados(len(notas))}          <div id="aviso-js" class="aviso-js" hidden></div>
          <ul class="chips-activos" id="chips" aria-label="Filtros activos"></ul>
          <div id="lista">
{bloque_lista(visibles)}          </div>
          <div class="mas"><button type="button" class="btn btn--linea" id="mas" hidden>Ver más publicaciones</button></div>
          <div class="vacio" id="vacio" hidden>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
            <h2>Sin resultados con esos filtros</h2>
            <p>Prueba con otro tema, amplía el rango de fechas o borra la búsqueda.</p>
            <button type="button" class="btn btn--oro" id="vacio-limpiar">Limpiar filtros</button>
          </div>
        </div>
      </div>
    </div>
  </main>
  <div class="telon" id="telon"></div>
  <button type="button" class="arriba" id="arriba" aria-label="Volver arriba">↑</button>
"""
        extra = ""
        con_js = True
    else:
        destino = SALIDA / "materia" / f"{slug(materia)}.html"
        destino.parent.mkdir(parents=True, exist_ok=True)
        url = f"{SITIO}/novedades/materia/{slug(materia)}.html"
        etiqueta = etiqueta_materia(materia)
        titulo = f"Novedades · {etiqueta} — CAS'LEY"
        desc = f"Publicaciones del DOF en materia {etiqueta} seleccionadas por relevancia jurídica."
        visibles = idx[materia]
        cuerpo = f"""  <header class="hero">
    <div class="container">
      <ul class="migas"><li><a href="/novedades/">Novedades</a></li><li>{html.escape(etiqueta)}</li></ul>
      <p class="kicker">Tema</p>
      <h1>{html.escape(etiqueta)}</h1>
      <p class="lede">{plural(len(visibles), "publicación", "publicaciones")} del Diario Oficial de la Federación
        clasificadas en este tema. Ordenadas de la más reciente a la más antigua.</p>
      <p class="hero-datos">
        <span><a href="/novedades/">Ver el explorador con filtros</a></span>
        <span><a href="/novedades/materia/{slug(materia)}.xml">Suscribirse por RSS</a></span>
      </p>
    </div>
  </header>
  <main id="contenido">
    <div class="container">
{bloque_lista(visibles)}    </div>
  </main>
"""
        extra = f'\n  <link rel="alternate" type="application/rss+xml" title="{html.escape(etiqueta)} — CAS\'LEY" href="/novedades/materia/{slug(materia)}.xml">'
        con_js = False
    destino.write_text(pagina(titulo, desc, cuerpo, extra_head=extra, canonical=url, con_js=con_js),
                       encoding="utf-8")


def generar_ficha(n: dict, notas: list[dict]) -> None:
    cod = n.get("codigo") or n.get("clave")
    mats = n.get("materias") or []
    chips_m = "".join(
        f'<a href="/novedades/materia/{slug(m)}.html">{html.escape(etiqueta_materia(m))}</a>' for m in mats
    )
    fuente = n.get("url") or ""
    pdf = n.get("pdf_url") or ""
    fuente_nombre = FUENTES.get(n.get("fuente") or "DOF", {}).get("nombre", "la fuente oficial")
    enlaces = []
    if fuente:
        enlaces.append(f'<a class="btn btn--oro" href="{html.escape(fuente)}" rel="noopener nofollow" target="_blank">Texto oficial ↗</a>')
    if pdf and pdf != fuente:
        enlaces.append(f'<a class="btn btn--linea" href="{html.escape(pdf)}" rel="noopener nofollow" target="_blank">PDF ↗</a>')
    enlaces.append('<button type="button" class="btn btn--linea" id="compartir">Compartir</button>')

    i = next((k for k, x in enumerate(notas) if (x.get("codigo") or x.get("clave")) == cod), None)
    previo = notas[i + 1] if i is not None and i + 1 < len(notas) else None
    siguiente = notas[i - 1] if i is not None and i > 0 else None
    pager = '<div class="pager">'
    pager += (f'<a class="prev" href="/novedades/{previo.get("codigo") or previo.get("clave")}.html">'
              f'<span aria-hidden="true">←</span> <span><span class="pager-lbl">Anterior</span>'
              f'{html.escape((previo.get("titulo") or "")[:70])}…</span></a>') if previo else "<span></span>"
    pager += (f'<a class="sig" href="/novedades/{siguiente.get("codigo") or siguiente.get("clave")}.html">'
              f'<span><span class="pager-lbl">Siguiente</span>'
              f'{html.escape((siguiente.get("titulo") or "")[:70])}…</span> <span aria-hidden="true">→</span></a>') if siguiente else "<span></span>"
    pager += "</div>"

    ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": (n.get("titulo") or "").strip(),
        "description": (n.get("resumen") or "").strip(),
        "datePublished": n.get("fecha"),
        "inLanguage": "es-MX",
        "articleSection": n.get("tipo"),
        "author": {"@type": "Organization", "name": n.get("emisor") or n.get("dependencia") or "DOF"},
        "publisher": {"@type": "Organization", "name": TITULO_SITIO},
        "url": f"{SITIO}/novedades/{cod}.html",
        "isBasedOn": fuente or f"{SITIO}/novedades/{cod}.html",
        "keywords": ", ".join(mats),
    }
    extra = '\n  <script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>"

    cuerpo = f"""  <header class="hero">
    <div class="container ficha">
      <ul class="migas"><li><a href="/novedades/">Novedades</a></li><li>{html.escape((n.get('tipo') or '').strip())}</li></ul>
      <div class="nota__cab">
        <span class="b b--fuente">{html.escape(n.get('fuente') or 'DOF')}</span>
        <span class="b">{html.escape((n.get('tipo') or '').strip())}</span>
        <span class="b">Resumen automático</span>
        <time class="nota__fecha" datetime="{html.escape(n.get('fecha') or '')}">{html.escape(fecha_larga(n.get('fecha')))}</time>
      </div>
      <h1>{html.escape((n.get('titulo') or '').strip())}</h1>
      <p class="lede">{html.escape((n.get('resumen') or '').strip())}</p>
      <div class="acciones-ficha">{''.join(enlaces)}</div>
    </div>
  </header>
  <main id="contenido">
    <div class="container ficha">
      <div class="datos">
        <div><span>Emisor</span><strong>{html.escape(emisor_legible(n.get('emisor') or '') or '—')}</strong></div>
        <div><span>Fecha</span><strong>{html.escape(fecha_larga(n.get('fecha', '')))}</strong></div>
        <div><span>Edición</span><strong>{html.escape(EDICION_LEGIBLE.get((n.get('edicion') or '').upper(), n.get('edicion') or '—'))}</strong></div>
        <div><span>Relevancia</span><strong>{n.get('relevancia', '—')} / 100</strong></div>
        <div><span>Materias</span><div class="materias">{chips_m or '—'}</div></div>
      </div>
      <p class="cuerpo-ficha">Esta ficha resume de forma extractiva el contenido publicado en {html.escape(fuente_nombre)}.
        El texto íntegro, sus anexos y cualquier fe de erratas están en la fuente oficial enlazada arriba.</p>
      <p class="nota-legal">Resumen generado automáticamente. Consulte siempre el texto oficial antes de actuar:
        esta ficha es informativa y no constituye asesoría jurídica.</p>
      {pager}
    </div>
  </main>
"""
    destino = SALIDA / f"{cod}.html"
    destino.write_text(
        pagina(f"{(n.get('titulo') or '').strip()} — CAS'LEY", (n.get("resumen") or "")[:180], cuerpo,
               extra_head=extra, canonical=f"{SITIO}/novedades/{cod}.html", con_js=True),
        encoding="utf-8",
    )


# ── Datos, RSS, sitemap ─────────────────────────────────────────────────────

def generar_datos(notas: list[dict], idx: dict[str, list[dict]]) -> None:
    fuentes = {}
    for f in sorted({n.get("fuente") or "DOF" for n in notas}):
        fuentes[f] = FUENTES.get(f, {"nombre": f, "corto": f, "url": ""})
    datos = {
        "generado": notas[0].get("fecha", "") if notas else "",
        "fuentes": fuentes,
        "materias": {m: etiqueta_materia(m) for m in idx},
        "notas": [
            {
                "clave": str(n.get("clave") or n.get("codigo")),
                "codigo": n.get("codigo"),
                "fuente": n.get("fuente") or "DOF",
                "fecha": n.get("fecha", ""),
                "tipo": (n.get("tipo") or "").strip(),
                "emisor": emisor_legible(n.get("emisor") or ""),
                "titulo": (n.get("titulo") or "").strip(),
                "resumen": (n.get("resumen") or "").strip(),
                "materias": n.get("materias") or [],
                "relevancia": n.get("relevancia", 0),
                "url": n.get("url") or "",
                "pdf_url": n.get("pdf_url") or "",
            }
            for n in notas
        ],
    }
    (SALIDA / "datos.json").write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def generar_rss(notas: list[dict], materia: str | None = None) -> None:
    if materia:
        notas = [n for n in notas if materia in (n.get("materias") or [])]
    ultimas = notas[:30]
    last = ultimas[0].get("fecha", "") if ultimas else ""
    etiqueta = etiqueta_materia(materia) if materia else "Novedades oficiales"
    enlace_canal = f"{SITIO}/novedades/materia/{slug(materia)}.html" if materia else f"{SITIO}/novedades/"
    ruta_self = f"{SITIO}/novedades/materia/{slug(materia)}.xml" if materia else f"{SITIO}/novedades/feed.xml"
    items = []
    for n in ultimas:
        cod = n.get("codigo") or n.get("clave")
        link = f"{SITIO}/novedades/{cod}.html"
        items.append(
            "    <item>\n"
            f"      <title>{html.escape((n.get('titulo') or '').strip())}</title>\n"
            f"      <link>{link}</link>\n"
            f'      <guid isPermaLink="true">{link}</guid>\n'
            f"      <pubDate>{fecha_rfc822(n.get('fecha', ''))}</pubDate>\n"
            f"      <category>{html.escape((n.get('tipo') or 'DOF'))}</category>\n"
            f"      <description>{html.escape((n.get('resumen') or '').strip())}</description>\n"
            "    </item>\n"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{html.escape(etiqueta)} — CAS'LEY</title>\n"
        f"    <link>{enlace_canal}</link>\n"
        "    <description>Publicaciones oficiales seleccionadas por relevancia jurídica.</description>\n"
        "    <language>es-MX</language>\n"
        f"    <lastBuildDate>{fecha_rfc822(last)}</lastBuildDate>\n"
        f'    <atom:link href="{ruta_self}" rel="self" type="application/rss+xml"/>\n'
        + "".join(items)
        + "  </channel>\n</rss>\n"
    )
    destino = (SALIDA / "materia" / f"{slug(materia)}.xml") if materia else (SALIDA / "feed.xml")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(rss, encoding="utf-8")


def generar_sitemap(notas: list[dict], idx: dict[str, list[dict]]) -> None:
    """Sitemap completo del sitio: portada, índice de novedades, materias y fichas."""
    from xml.sax.saxutils import escape as xml_escape

    urls = [
        (f"{SITIO}/", "2026-10-21", "1.0"),
        (f"{SITIO}/novedades/", notas[0].get("fecha", "") if notas else "", "0.9"),
    ]
    for m in idx:
        urls.append((f"{SITIO}/novedades/materia/{slug(m)}.html", notas[0].get("fecha", "") if notas else "", "0.6"))
    for n in notas:
        cod = n.get("codigo") or n.get("clave")
        urls.append((f"{SITIO}/novedades/{cod}.html", n.get("fecha", ""), "0.7"))

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n',
    ]
    for loc, lastmod, prio in urls:
        partes.append("  <url>\n")
        partes.append(f"    <loc>{xml_escape(loc)}</loc>\n")
        if lastmod:
            partes.append(f"    <lastmod>{xml_escape(lastmod)}</lastmod>\n")
        partes.append(f"    <priority>{prio}</priority>\n")
        partes.append("  </url>\n")
    partes.append("</urlset>\n")
    (BASE / "sitemap.xml").write_text("".join(partes), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="usa el snapshot en lugar de la API")
    ap.add_argument("--limite", type=int, default=None, help="máximo de notas")
    args = ap.parse_args()

    notas = cargar(args.limite, args.offline)
    if not notas:
        sys.exit("ERROR: no hay notas que publicar")

    idx = materias_de(notas)
    SALIDA.mkdir(parents=True, exist_ok=True)

    css = SRC_UI / "app.css"
    js = SRC_UI / "app.js"
    for f in (css, js):
        if not f.exists():
            sys.exit(f"ERROR: falta el asset {f}")
    (SALIDA / "novedades.css").write_text(css.read_text(encoding="utf-8"), encoding="utf-8")
    (SALIDA / "novedades.js").write_text(js.read_text(encoding="utf-8"), encoding="utf-8")

    generar_listado(notas, idx, None)
    for m in idx:
        generar_listado(notas, idx, m)
    for n in notas:
        generar_ficha(n, notas)
    generar_datos(notas, idx)
    generar_rss(notas)
    for m in idx:
        generar_rss(notas, m)
    generar_sitemap(notas, idx)

    print(f"[novedades] {len(notas)} notas · {len(idx)} materias · {len({n.get('fuente') or 'DOF' for n in notas})} fuentes · salida {SALIDA}")
    print(f"[novedades] fechas: {notas[-1].get('fecha')} → {notas[0].get('fecha')}")


if __name__ == "__main__":
    main()
