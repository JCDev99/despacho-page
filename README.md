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
