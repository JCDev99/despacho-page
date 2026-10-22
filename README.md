# Despacho Jurídico CAS'LEY — Plantillas Web Estáticas

Sitio web estático para el despacho jurídico **CAS'LEY** (Ensenada, Baja California). Desarrollado bajo la metodología del ciclo de desarrollo web estático de la casa Mentor (`mentor-desarrollo-web-casa`).

---

## 1. Arquitectura del Repositorio

El proyecto no utiliza frameworks, preprocesadores ni dependencias de red externas (cero peticiones CDN). La fuente está organizada de manera modular en fragmentos numerados por orden de ensamblado:

```
.
├── build.sh                   # Ensamblador determinista y verificador de sello
├── index.html                 # Portada raíz (generada desde src/)
├── src/                       # Fuente modular de la portada
│   ├── css/10-portada.css
│   ├── html/*.html
│   ├── js/10-portada.js
│   └── EXPECTED               # Sello de integridad de la portada
├── v1/                        # Variante 01: Institucional Sobria
│   ├── index.html             # Artefacto autocontenido (HTML + CSS + JS inline)
│   └── src/
│       ├── css/*.css          # 5 partes CSS
│       ├── html/*.html        # 11 partes HTML
│       ├── js/*.js            # 2 partes JS
│       └── EXPECTED           # Sello de integridad de v1
├── v2/                        # Variante 02: Editorial Contemporánea
│   ├── index.html             # Artefacto autocontenido (HTML + CSS + JS inline)
│   └── src/
│       ├── css/*.css          # 5 partes CSS
│       ├── html/*.html        # 11 partes HTML
│       ├── js/*.js            # 2 partes JS
│       └── EXPECTED           # Sello de integridad de v2
├── tests/
│   ├── arnes.cjs              # Arnés Playwright (mide desborde real, consola, red, a11y)
│   ├── verificar.sh           # Orquestador de verificación (build, paridad, 404, arnés)
│   ├── informe-v1.json        # Métricas de ejecución Playwright sobre v1
│   └── informe-v2.json        # Métricas de ejecución Playwright sobre v2
├── referencia/
│   └── v0-index.html          # Copia íntegra de la versión previa original
├── contenido.md               # Inventario de contenido factual y huecos declarados
├── INFORME.md                 # Informe técnico de entrega con mediciones reproducibles
└── README.md                  # Este documento
```

---

## 2. Cómo Construir el Sitio

Los ficheros `index.html` **no se editan directamente a mano**. Se ensamblan determinísticamente a partir de sus partes en `src/`:

```bash
# Construir y sellar todos los destinos (portada, v1 y v2):
./build.sh

# Construir un destino específico:
./build.sh root   # Solo la portada raíz
./build.sh v1     # Solo la Variante v1
./build.sh v2     # Solo la Variante v2

# Forzar reconstrucción limpia y re-sellado:
./build.sh --update
```

### Verificación de Integridad sin Deriva (`--check`)
Para validar que los artefactos generados en disco corresponden exactamente con la concatenación de sus partes y con sus respectivos sellos `EXPECTED`:

```bash
./build.sh --check
```
*Salida exitosa (`rc=0`):*
```
[OK] sin deriva: sello, src/ e index.html son el mismo contenido.
```

---

## 3. Cómo Verificar (Arnés y Servidor Estático)

El script `tests/verificar.sh` automatiza el ciclo completo de auditoría:
1. Comprueba la integridad con `./build.sh --check`.
2. Levanta un servidor HTTP estático propio (`python3 -m http.server`) en un puerto libre.
3. Comprueba la **paridad MD5 servido vs disco** para la portada, `v1` y `v2`.
4. Ejecuta un **control negativo** para garantizar que los respaldos (`.bak`, `.old`) devuelven código HTTP `404`.
5. Corre el arnés de Playwright (`tests/arnes.cjs`) midiendo layout (1440, 390, 360 px), peticiones externas, errores de consola, contraste WCAG y accesibilidad.
6. Corre el arnés del explorador de Novedades (`tests/novedades.cjs`) sirviendo `v1/` como raíz, igual que en producción: desbordes a 1440/1024/768/390/360, contraste, foco, red externa, coherencia de los filtros con `datos.json`, búsqueda con estado en URL y render sin JavaScript.

```bash
./tests/verificar.sh
```

Para correr únicamente el arnés de pruebas Playwright:
```bash
export NODE_PATH="$(npm root -g)"
export PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
node tests/arnes.cjs
```

---

## 4. Publicación en GitHub Pages

El repositorio está concebido para desplegarse de manera directa y sin pasos de compilación en el servidor remoto:
- **Destino:** GitHub Pages alojado en la rama principal (`main`) desde la raíz `/`.
- **Portabilidad de dominio:** Todas las rutas son estrictamente relativas (ej. `./v1/index.html`), lo que permite que el sitio funcione indistintamente en servidores locales, subdirectorios de GitHub Pages o dominios personalizados sin alterar el código fuente.
- **Regla de Gerencia:** La publicación, commits y firmas los realiza Gerencia.

---

## 5. Sección de Novedades (`/novedades/`)

Generada por `generador-novedades.py` a partir de la API interna del DOF; el sitio publicado no consulta la API en tiempo de ejecución.

```bash
python3 generador-novedades.py            # descarga de la API y regenera
python3 generador-novedades.py --offline  # usa v1/src/novedades-snapshot.json
python3 generador-novedades.py --limite 60
```

Produce, en `v1/novedades/`:

- `index.html`: explorador con filtros de **fuente oficial**, **tema** (multiselección), **tipo de documento**, **emisor**, **banda de relevancia**, **rango de fechas** con atajos y **búsqueda de texto** con resaltado. El estado vive en la URL (`?tema=fiscal&bandas=alta&desde=…`), de modo que cualquier combinación se puede compartir o recuperar con el botón Atrás.
- `datos.json`: índice que consume el filtrado en cliente (`v1/src/novedades/app.js`).
- `novedades.css` y `novedades.js`: copias de `v1/src/novedades/` (esa carpeta es la fuente editable; no se tocan los ficheros publicados a mano).
- `<clave>.html`: ficha de cada publicación, con datos, materias, aviso legal, JSON-LD y navegación anterior/siguiente.
- `materia/<tema>.html`: listado completo por tema, sin JavaScript e indexable.
- `feed.xml` y `materia/<tema>.xml`: RSS general y por tema.
- `sitemap.xml` en la raíz del repo, regenerado con las fichas y las páginas de tema.

**Fuentes:** el filtro se construye con las fuentes presentes en los datos (`campo fuente`). Hoy publica `DOF` y `POBBC` (Periódico Oficial de Baja California); `SAT` está declarada y aparecerá sola cuando la API entregue notas con ese campo.

**Relevancia:** se publica todo el catálogo, sin umbral de entrada. La puntuación se presenta en tres bandas —**Alta** (80+), **Media** (50-79) e **Informativa** (menos de 50)— con tres segmentos, y el número solo aparece en la ficha, dentro del desglose. Por defecto el explorador muestra Alta y Media; la banda Informativa se activa desde el panel. El orden por defecto es cronológico, y sigue existiendo el orden por relevancia.

**Determinismo:** no se usa la hora actual. El `lastBuildDate` del RSS, el pie y los contadores usan la fecha de la nota más reciente, de modo que dos ejecuciones con los mismos datos producen bytes idénticos.
