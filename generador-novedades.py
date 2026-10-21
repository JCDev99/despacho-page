#!/usr/bin/env python3
"""Generador estático de la sección de Novedades de CAS'LEY.

Lee la API interna del DOF (o un snapshot local) y escribe páginas estáticas
en `v1/novedades/`. El sitio publicado NO llama a la API en tiempo de ejecución:
todo se compone aquí y se sirve como ficheros.

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
SNAPSHOT = BASE / "v1" / "src" / "novedades-snapshot.json"
API = "https://dof.jc99.dev/v1/novedades"
SITIO = "https://despacho.jc99.dev"
MIN_RELEVANCIA = 80
TITULO_SITIO = "CAS'LEY — Asesoría Jurídica Profesional"

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

CSS = """\
:root{
  --navy-950:#070F18; --navy-900:#0B1B2B; --navy-800:#13273D; --navy-700:#1E3752;
  --stone-50:#F8FAFC; --stone-200:#E2E8F0; --stone-300:#CBD5E1; --stone-400:#94A3B8;
  --stone-700:#334155; --stone-900:#0F172A;
  --gold-light:#E6C280; --gold-base:#C5A059; --gold-dark:#85581A;
  --border-dark:rgba(226,232,240,0.12);
  --serif:"Georgia","Times New Roman","Cambria",serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --container:1180px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--navy-950);color:var(--stone-200);font-family:var(--sans);line-height:1.65}
a{color:var(--gold-light);text-decoration:none}
a:hover,a:focus-visible{text-decoration:underline}
.container{max-width:var(--container);margin:0 auto;padding:0 1.25rem}
.top{display:flex;align-items:center;justify-content:space-between;gap:1.5rem;padding:1.1rem 0;border-bottom:1px solid var(--border-dark);flex-wrap:wrap}
.brand{font-family:var(--serif);font-size:1.35rem;font-weight:700;color:#fff;letter-spacing:.04em}
.brand span{display:block;font-family:var(--sans);font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--gold-light);font-weight:600}
.back{font-size:.9rem}
header.hero{padding:3rem 0 1.5rem;border-bottom:1px solid var(--border-dark)}
h1{font-family:var(--serif);font-size:clamp(1.9rem,4vw,2.9rem);line-height:1.15;margin:0 0 .9rem;color:#fff}
.lede{max-width:62ch;color:var(--stone-300);margin:0 0 1.4rem}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;list-style:none;padding:0;margin:0}
.chips a,.chips span{display:inline-block;padding:.35rem .8rem;border:1px solid var(--border-dark);border-radius:999px;font-size:.82rem;color:var(--stone-300)}
.chips a:hover{border-color:var(--gold-base);color:var(--gold-light);text-decoration:none}
.chips .on{background:var(--gold-base);color:var(--navy-950);border-color:var(--gold-base);font-weight:600}
main{padding:2.5rem 0 4rem}
.fecha{display:flex;align-items:center;gap:.75rem;margin:2.4rem 0 1rem;color:var(--gold-light);font-size:.85rem;letter-spacing:.12em;text-transform:uppercase;font-weight:600}
.fecha::after{content:"";flex:1;height:1px;background:var(--border-dark)}
article.card{border:1px solid var(--border-dark);border-radius:6px;padding:1.35rem 1.5rem;margin:0 0 1rem;background:var(--navy-900)}
article.card h2{font-family:var(--serif);font-size:1.2rem;line-height:1.35;margin:0 0 .6rem;color:#fff;font-weight:700}
.meta{font-size:.78rem;color:var(--stone-400);margin:0 0 .7rem;text-transform:uppercase;letter-spacing:.06em}
.meta b{color:var(--gold-light);font-weight:600}
.resumen{margin:0 0 .9rem;color:var(--stone-300)}
.acciones{display:flex;flex-wrap:wrap;gap:1.1rem;font-size:.86rem}
.tag{font-size:.72rem;color:var(--stone-400)}
.pager{display:flex;justify-content:space-between;gap:1rem;margin-top:2.5rem}
footer{border-top:1px solid var(--border-dark);padding:2rem 0 3rem;color:var(--stone-400);font-size:.85rem}
footer p{margin:0 0 .6rem;max-width:75ch}
.nota{border-left:2px solid var(--gold-dark);padding:.8rem 1rem;margin:2rem 0 0;color:var(--stone-400);font-size:.85rem}
.ficha h1{font-size:clamp(1.5rem,3vw,2.2rem)}
.datos{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin:1.5rem 0;padding:1.2rem 0;border-top:1px solid var(--border-dark);border-bottom:1px solid var(--border-dark)}
.datos div span{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--stone-400);margin-bottom:.15rem}
.datos div strong{color:var(--stone-200);font-weight:600;font-size:.92rem}
@media(max-width:640px){header.hero{padding:2rem 0 1rem}article.card{padding:1.1rem 1rem}}
"""


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


def etiqueta_materia(m: str) -> str:
    if m in ETIQUETAS_MATERIA:
        return ETIQUETAS_MATERIA[m]
    return m.replace("_", " ").capitalize()


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
    notas.sort(key=lambda n: (n.get("fecha", ""), n.get("codigo", 0)), reverse=True)
    return notas


def materias_de(notas: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for n in notas:
        for m in n.get("materias") or ["general"]:
            idx.setdefault(m, []).append(n)
    return dict(sorted(idx.items()))


def pagina(titulo: str, descripcion: str, cuerpo: str, extra_head: str = "", canonical: str = "") -> str:
    can = f'\n  <link rel="canonical" href="{html.escape(canonical)}">' if canonical else ""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(titulo)}</title>
  <meta name="description" content="{html.escape(descripcion)}">
  <meta name="theme-color" content="#0F172A">{can}
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/novedades/novedades.css">
  <link rel="alternate" type="application/rss+xml" title="Novedades del DOF — CAS'LEY" href="/novedades/feed.xml">{extra_head}
</head>
<body>
  <div class="container">
    <div class="top">
      <a class="brand" href="/">CAS'LEY<span>Asesoría Jurídica Profesional</span></a>
      <a class="back" href="/">← Volver al sitio</a>
    </div>
  </div>
{cuerpo}
  <div class="container">
    <footer>
      <p><strong>Aviso:</strong> esta sección resume, con carácter informativo, publicaciones del Diario Oficial
      de la Federación. No constituye asesoría jurídica ni sustituye el texto oficial; cada ficha enlaza a su fuente.</p>
      <p>© 2026 CAS'LEY — Asesoría Jurídica Profesional · Calle Novena #252, Fracc. C.D. San Quintín, Baja California, México.</p>
    </footer>
  </div>
</body>
</html>
"""


def tarjeta(n: dict, con_materia: bool = True) -> str:
    cod = n.get("codigo") or n.get("clave")
    tipo = (n.get("tipo") or "").strip()
    emisor = n.get("emisor") or n.get("dependencia") or ""
    resumen = (n.get("resumen") or "").strip()
    mats = n.get("materias") or []
    tags = " · ".join(html.escape(etiqueta_materia(m).upper()) for m in mats[:3]) if con_materia else ""
    fuente = n.get("url") or ""
    enlace_fuente = (
        f'<a href="{html.escape(fuente)}" rel="noopener nofollow" target="_blank">Fuente oficial (DOF) ↗</a>'
        if fuente else ""
    )
    return f"""      <article class="card">
        <p class="meta"><b>{html.escape(tipo)}</b> · {html.escape(emisor)}{(' · ' + tags) if tags else ''}</p>
        <h2>{html.escape((n.get('titulo') or '').strip())}</h2>
        <p class="resumen">{html.escape(resumen)}</p>
        <div class="acciones">
          <a href="/novedades/{cod}.html">Leer ficha</a>
          {enlace_fuente}
          <span class="tag">Relevancia {n.get('relevancia', '')}</span>
        </div>
      </article>
"""


def bloque_lista(notas: list[dict], materia_activa: str | None = None) -> str:
    if not notas:
        return '<p class="lede">No hay publicaciones que mostrar.</p>\n'
    partes = []
    fecha_actual = None
    for n in notas:
        if n.get("fecha") != fecha_actual:
            fecha_actual = n.get("fecha")
            partes.append(f'      <div class="fecha">{html.escape(fecha_larga(fecha_actual))}</div>\n')
        partes.append(tarjeta(n))
    return "".join(partes)


def chips(idx: dict[str, list[dict]], activa: str | None, total: int) -> str:
    base = [
        f'<li><a href="/novedades/"{"" if activa is None else ""} class="{"on" if activa is None else ""}">'
        f'Todas ({total})</a></li>'
    ]
    for m, ns in idx.items():
        on = " on" if activa == m else ""
        base.append(
            f'<li><a href="/novedades/materia/{slug(m)}.html" class="{on.strip()}">'
            f'{html.escape(etiqueta_materia(m))} ({len(ns)})</a></li>'
        )
    return '<ul class="chips">' + "".join(base) + "</ul>"


def generar_listado(notas: list[dict], idx: dict[str, list[dict]], materia: str | None) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    if materia is None:
        destino = SALIDA / "index.html"
        url = f"{SITIO}/novedades/"
        titulo = "Novedades del DOF — CAS'LEY"
        desc = "Publicaciones del Diario Oficial de la Federación seleccionadas por relevancia jurídica."
        cuerpo_notas = bloque_lista(notas)
        activa = None
        subtitulo = "Publicaciones del Diario Oficial de la Federación con relevancia para despachos y empresas, resumidas en una frase útil."
    else:
        destino = SALIDA / "materia" / f"{slug(materia)}.html"
        destino.parent.mkdir(parents=True, exist_ok=True)
        url = f"{SITIO}/novedades/materia/{slug(materia)}.html"
        titulo = f"{etiqueta_materia(materia)} — Novedades del DOF — CAS'LEY"
        desc = f"Publicaciones del DOF en materia {etiqueta_materia(materia)} seleccionadas por relevancia jurídica."
        cuerpo_notas = bloque_lista(idx[materia])
        activa = materia
        subtitulo = f"Publicaciones del DOF en materia <strong>{html.escape(etiqueta_materia(materia))}</strong>."

    cuerpo = f"""  <header class="hero">
    <div class="container">
      <h1>Novedades del Diario Oficial</h1>
      <p class="lede">{subtitulo}</p>
      {chips(idx, activa, len(notas))}
    </div>
  </header>
  <main>
    <div class="container">
{cuerpo_notas}    </div>
  </main>
"""
    destino.write_text(pagina(titulo, desc, cuerpo, canonical=url), encoding="utf-8")


def generar_ficha(n: dict, idx: dict[str, list[dict]]) -> None:
    cod = n.get("codigo") or n.get("clave")
    mats = n.get("materias") or []
    chips_m = "".join(
        f'<a href="/novedades/materia/{slug(m)}.html">{html.escape(etiqueta_materia(m))}</a> ' for m in mats
    )
    fuente = n.get("url") or ""
    pdf = n.get("pdf_url") or ""
    enlaces = []
    if fuente:
        enlaces.append(f'<a href="{html.escape(fuente)}" rel="noopener nofollow" target="_blank">Texto oficial en el DOF ↗</a>')
    if pdf:
        enlaces.append(f'<a href="{html.escape(pdf)}" rel="noopener nofollow" target="_blank">PDF ↗</a>')

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

    cuerpo = f"""  <header class="hero ficha">
    <div class="container">
      <p class="meta"><b>{html.escape((n.get('tipo') or '').strip())}</b> · {html.escape(fecha_larga(n.get('fecha', '')))}</p>
      <h1>{html.escape((n.get('titulo') or '').strip())}</h1>
      <p class="lede">{html.escape((n.get('resumen') or '').strip())}</p>
      <p class="acciones">{' · '.join(enlaces) if enlaces else ''}</p>
    </div>
  </header>
  <main>
    <div class="container">
      <div class="datos">
        <div><span>Emisor</span><strong>{html.escape(n.get('emisor') or n.get('dependencia') or '—')}</strong></div>
        <div><span>Fecha</span><strong>{html.escape(fecha_larga(n.get('fecha', '')))}</strong></div>
        <div><span>Edición</span><strong>{html.escape(n.get('edicion') or '—')}</strong></div>
        <div><span>Materias</span><strong>{chips_m or '—'}</strong></div>
        <div><span>Relevancia</span><strong>{n.get('relevancia', '—')} / 100</strong></div>
      </div>
      <p class="nota">Resumen extractivo generado automáticamente a partir del texto publicado en el DOF.
        Consulte siempre el texto oficial antes de actuar: esta ficha es informativa y no constituye asesoría jurídica.</p>
      <p class="pager"><a href="/novedades/">← Todas las novedades</a><a href="/">Ir al sitio del despacho</a></p>
    </div>
  </main>
"""
    destino = SALIDA / f"{cod}.html"
    destino.write_text(
        pagina(f"{(n.get('titulo') or '').strip()} — CAS'LEY", (n.get("resumen") or "")[:180], cuerpo,
               extra_head=extra, canonical=f"{SITIO}/novedades/{cod}.html"),
        encoding="utf-8",
    )


def generar_rss(notas: list[dict]) -> None:
    ultimas = notas[:30]
    last = ultimas[0].get("fecha", "") if ultimas else ""
    items = []
    for n in ultimas:
        cod = n.get("codigo") or n.get("clave")
        link = f"{SITIO}/novedades/{cod}.html"
        items.append(
            "    <item>\n"
            f"      <title>{html.escape((n.get('titulo') or '').strip())}</title>\n"
            f"      <link>{link}</link>\n"
            f"      <guid isPermaLink=\"true\">{link}</guid>\n"
            f"      <pubDate>{fecha_rfc822(n.get('fecha', ''))}</pubDate>\n"
            f"      <category>{html.escape((n.get('tipo') or 'DOF'))}</category>\n"
            f"      <description>{html.escape((n.get('resumen') or '').strip())}</description>\n"
            "    </item>\n"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Novedades del DOF — CAS'LEY</title>\n"
        f"    <link>{SITIO}/novedades/</link>\n"
        "    <description>Publicaciones del Diario Oficial de la Federación seleccionadas por relevancia jurídica.</description>\n"
        "    <language>es-MX</language>\n"
        f"    <lastBuildDate>{fecha_rfc822(last)}</lastBuildDate>\n"
        f'    <atom:link href="{SITIO}/novedades/feed.xml" rel="self" type="application/rss+xml"/>\n'
        + "".join(items)
        + "  </channel>\n</rss>\n"
    )
    (SALIDA / "feed.xml").write_text(rss, encoding="utf-8")


def generar_sitemap(notas: list[dict], idx: dict[str, list[dict]]) -> None:
    """Sitemap completo del sitio: portada, índice de novedades, materias y fichas."""
    from xml.sax.saxutils import escape as xml_escape

    urls = [
        (f"{SITIO}/", "2026-10-21", "1.0"),
        (f"{SITIO}/novedades/", notas[0].get("fecha", "") if notas else "", "0.9"),
    ]
    for m in idx:
        urls.append((f"{SITIO}/novedades/materia/{slug(m)}.html", "", "0.6"))
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
    (SALIDA / "novedades.css").write_text(CSS, encoding="utf-8")

    generar_listado(notas, idx, None)
    for m in idx:
        generar_listado(notas, idx, m)
    for n in notas:
        generar_ficha(n, idx)
    generar_rss(notas)
    generar_sitemap(notas, idx)

    print(f"[novedades] {len(notas)} notas · {len(idx)} materias · salida {SALIDA}")
    print(f"[novedades] fechas: {notas[-1].get('fecha')} → {notas[0].get('fecha')}")


if __name__ == "__main__":
    main()
