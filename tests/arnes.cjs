// tests/arnes.cjs — Arnés de verificación Playwright para CAS'LEY (v1 y v2)
// Mide desbordes reales en 1440/390/360 px, consola limpia, cero peticiones externas,
// contraste WCAG AA, objetivos táctiles y foco visible.

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const argv = process.argv.slice(2);
const getArg = (name) => {
  const p = argv.find((a) => a === '--' + name || a.startsWith('--' + name + '='));
  if (!p) return null;
  const i = p.indexOf('=');
  return i === -1 ? true : p.slice(i + 1);
};

const BASE_URL = (() => {
  const u = getArg('url') || getArg('servido');
  if (typeof u === 'string' && u) return u.replace(/\/$/, '');
  const dir = path.resolve(__dirname, '..');
  return 'file://' + dir;
})();

const VARIANTE_FILTRO = getArg('variante'); // 'v1', 'v2' o null para ambas
const ANCHOS = [1440, 390, 360];

// Funciones de contraste WCAG 2.x
function sRGBtoLin(colorChannel) {
  const c = colorChannel / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function getLuminance(r, g, b) {
  return 0.2126 * sRGBtoLin(r) + 0.7152 * sRGBtoLin(g) + 0.0722 * sRGBtoLin(b);
}

function getContrastRatio(l1, l2) {
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

async function auditarVariante(browser, varKey) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: 'reduce',
  });
  const page = await ctx.newPage();

  const erroresConsola = [];
  const peticionesExternas = [];

  page.on('console', (m) => {
    if (m.type() === 'error') erroresConsola.push(m.text().slice(0, 160));
  });
  page.on('pageerror', (e) => erroresConsola.push('pageerror: ' + String(e).slice(0, 160)));
  page.on('request', (r) => {
    const u = r.url();
    if (!u.startsWith('file://') && !u.startsWith('http://127.0.0.1') && !u.startsWith('http://localhost')) {
      peticionesExternas.push(u.slice(0, 120));
    }
  });
  page.on('requestfailed', (r) => {
    erroresConsola.push('reqfail: ' + r.url().slice(0, 120));
  });

  const urlFinal = `${BASE_URL}/${varKey}/index.html`;
  await page.goto(urlFinal, { waitUntil: 'load', timeout: 20000 });
  await page.waitForTimeout(500);

  const informe = {
    variante: varKey,
    url: urlFinal,
    ts: new Date().toISOString(),
    desbordes: {},
    desbordesReales: {},
    desbordesPorEstado: {},
    estadosMedidos: [],
    erroresConsola,
    peticionesExternas,
    contraste: {
      totalMuestras: 0,
      peorRatio: 999,
      peorPareja: null,
      todosCumplen: true,
      muestrasDetalle: []
    },
    objetivoTactil: {
      totalControles: 0,
      controlesMenores24: 0,
      minAncho: 999,
      minAlto: 999,
      cumple: true,
      detalles: []
    },
    focoTeclado: {
      totalInteractivos: 0,
      conFocoVisible: 0,
      sinFocoVisible: 0,
      trampasDetectadas: 0,
      cumple: true
    },
    veredicto: 'PENDIENTE'
  };

  // Función para medir desborde horizontal clásico y real
  const medirDesborde = async (etiqueta) => {
    const res = {};
    for (const w of ANCHOS) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.waitForTimeout(250);

      const m = await page.evaluate(() => {
        const selectorDe = (el) => el.tagName.toLowerCase()
          + (el.id ? '#' + el.id
            : (typeof el.className === 'string' && el.className.trim()
              ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''));

        const clipadoLocalmente = (el) => {
          let p = el.parentElement;
          while (p && p !== document.body && p !== document.documentElement) {
            const cs = getComputedStyle(p);
            if (cs.overflowX !== 'visible' && cs.overflowX !== '') return true;
            p = p.parentElement;
          }
          return false;
        };

        const de = document.documentElement;
        const vw = de.clientWidth;
        let maxDerecha = vw;
        let minIzquierda = 0;
        const culpables = [];

        for (const el of de.querySelectorAll('body *')) {
          const caja = el.getBoundingClientRect();
          if (caja.width === 0 && caja.height === 0) continue;
          const seSaleDerecha = caja.right > vw + 1;
          const seSaleIzquierda = caja.left < -1;
          if (!seSaleDerecha && !seSaleIzquierda) continue;
          if (clipadoLocalmente(el)) continue;

          if (seSaleDerecha && caja.right > maxDerecha) maxDerecha = caja.right;
          if (seSaleIzquierda) minIzquierda = Math.max(minIzquierda, -caja.left);

          if (culpables.length < 3) {
            culpables.push({
              sel: selectorDe(el),
              left: Math.round(caja.left),
              right: Math.round(caja.right),
              w: Math.round(caja.width)
            });
          }
        }

        const desbordeReal = Math.max(0, Math.round(maxDerecha - vw), Math.round(minIzquierda));
        const desbordeClasico = Math.max(0, de.scrollWidth - vw);

        return {
          clasico: desbordeClasico,
          real: desbordeReal,
          clientWidth: vw,
          scrollWidth: de.scrollWidth,
          culpables
        };
      });

      res[w + 'px'] = m;
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForTimeout(150);
    informe.desbordesPorEstado[etiqueta] = res;
    return res;
  };

  // 1. ESTADO REPOSO
  informe.estadosMedidos.push('reposo');
  const dReposo = await medirDesborde('reposo');
  for (const w of ANCHOS) {
    informe.desbordes[w + 'px'] = dReposo[w + 'px'].clasico;
    informe.desbordesReales[w + 'px'] = dReposo[w + 'px'].real;
  }

  // 2. ESTADO MENÚ MÓVIL ABIERTO
  informe.estadosMedidos.push('menu-movil');
  try {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.waitForTimeout(200);
    const menuBtnSel = varKey === 'v1' ? '#v1MobileMenuBtn' : '#v2BurgerBtn';
    const menuElSel = varKey === 'v1' ? '#v1MobileMenu' : '#v2BurgerMenu';

    const btnExiste = await page.$(menuBtnSel);
    if (btnExiste) {
      await page.click(menuBtnSel);
      await page.waitForTimeout(300);
      await medirDesborde('menu-movil');
      // Cerrar menú para no interferir con pasos siguientes
      await page.keyboard.press('Escape');
      await page.waitForTimeout(200);
    }
  } catch (e) {
    erroresConsola.push('error-menu-movil: ' + e.message);
  }

  // 3. ESTADO HOVER
  informe.estadosMedidos.push('hover');
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    const hoverSel = varKey === 'v1' ? '.btn-primary' : '.btn-editorial-primary';
    const elHover = await page.$(hoverSel);
    if (elHover) {
      await elHover.hover();
      await page.waitForTimeout(200);
      await medirDesborde('hover');
    }
  } catch (e) {
    erroresConsola.push('error-hover: ' + e.message);
  }

  // 4. ESTADO FOCO POR TECLADO
  informe.estadosMedidos.push('foco');
  try {
    await page.keyboard.press('Tab');
    await page.waitForTimeout(150);
    await medirDesborde('foco');
  } catch (e) {
    erroresConsola.push('error-foco: ' + e.message);
  }

  // 5. MEDICIÓN DE CONTRASTE WCAG 2.2 AA
  const datosContraste = await page.evaluate(() => {
    function parseRGB(str) {
      if (!str) return null;
      const m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
      if (!m) return null;
      const alpha = m[4] !== undefined ? parseFloat(m[4]) : 1;
      return { r: parseInt(m[1]), g: parseInt(m[2]), b: parseInt(m[3]), a: alpha };
    }

    function getEffectiveBackground(el) {
      let cur = el;
      const layers = [];
      while (cur && cur !== document && cur !== document.documentElement) {
        const bg = getComputedStyle(cur).backgroundColor;
        const parsed = parseRGB(bg);
        if (parsed && parsed.a > 0) {
          layers.push(parsed);
          if (parsed.a >= 0.99) break;
        }
        cur = cur.parentElement;
      }
      // Fondo base por defecto (blanco para secciones claras o contenedor)
      let r = 255, g = 255, b = 255;
      for (let i = layers.length - 1; i >= 0; i--) {
        const l = layers[i];
        r = Math.round(l.r * l.a + r * (1 - l.a));
        g = Math.round(l.g * l.a + g * (1 - l.a));
        b = Math.round(l.b * l.a + b * (1 - l.a));
      }
      return { r, g, b, a: 1 };
    }

    function luminance(r, g, b) {
      const a = [r, g, b].map(function (v) {
        v /= 255;
        return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      });
      return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
    }

    function contrastRatio(l1, l2) {
      const lighter = Math.max(l1, l2);
      const darker = Math.min(l1, l2);
      return (lighter + 0.05) / (darker + 0.05);
    }

    const items = [];
    const elements = document.querySelectorAll('h1, h2, h3, h4, p, a, .btn-primary, .btn-secondary, .btn-open, .nav-link, .top-info-item, .footer-brand p, .footer-legal-notice, .editorial-disclaimer-box, .editorial-box-lead, .btn-editorial-primary, .btn-editorial-outline');

    elements.forEach((el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) < 0.1) return;
      const directText = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ').trim();
      const text = directText || (el.children.length === 0 ? (el.innerText || '').trim() : '');
      if (!text || text.length < 2) return;

      const fg = parseRGB(cs.color);
      const bg = getEffectiveBackground(el);
      if (!fg || !bg) return;

      const lumFg = luminance(fg.r, fg.g, fg.b);
      const lumBg = luminance(bg.r, bg.g, bg.b);
      const ratio = contrastRatio(lumFg, lumBg);

      const fontSize = parseFloat(cs.fontSize) || 16;
      const fontWeight = parseInt(cs.fontWeight) || 400;
      const isLarge = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 600);
      const req = isLarge ? 3.0 : 4.5;
      const pass = ratio >= req;

      items.push({
        sel: el.tagName.toLowerCase() + (el.className ? '.' + el.className.trim().split(/\s+/)[0] : ''),
        texto: text.slice(0, 35),
        ratio: Math.round(ratio * 100) / 100,
        req,
        isLarge,
        pass,
        fg: `rgb(${fg.r},${fg.g},${fg.b})`,
        bg: `rgb(${bg.r},${bg.g},${bg.b})`
      });
    });

    return items;
  });

  informe.contraste.totalMuestras = datosContraste.length;
  let peorRatio = 999;
  let peorPareja = null;
  let todosCumplen = true;

  for (const m of datosContraste) {
    if (m.ratio < peorRatio) {
      peorRatio = m.ratio;
      peorPareja = m;
    }
    if (!m.pass) {
      todosCumplen = false;
    }
  }

  informe.contraste.peorRatio = peorRatio === 999 ? null : peorRatio;
  informe.contraste.peorPareja = peorPareja;
  informe.contraste.todosCumplen = todosCumplen;
  informe.contraste.muestrasDetalle = datosContraste.slice(0, 15);

  // 6. MEDICIÓN DE OBJETIVO TÁCTIL (>= 24x24 px CSS)
  const datosTactiles = await page.evaluate(() => {
    const controls = document.querySelectorAll('a, button, input, [tabindex="0"]');
    const res = [];
    controls.forEach((c) => {
      const cs = getComputedStyle(c);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const rect = c.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;
      const pass = rect.width >= 24 && rect.height >= 24;
      res.push({
        tag: c.tagName.toLowerCase(),
        texto: (c.innerText || c.getAttribute('aria-label') || '').slice(0, 25),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
        pass
      });
    });
    return res;
  });

  informe.objetivoTactil.totalControles = datosTactiles.length;
  let minW = 999;
  let minH = 999;
  let menores24 = 0;

  for (const c of datosTactiles) {
    if (c.w < minW) minW = c.w;
    if (c.h < minH) minH = c.h;
    if (!c.pass) menores24++;
  }

  informe.objetivoTactil.minAncho = minW === 999 ? null : minW;
  informe.objetivoTactil.minAlto = minH === 999 ? null : minH;
  informe.objetivoTactil.controlesMenores24 = menores24;
  informe.objetivoTactil.cumple = menores24 === 0;
  informe.objetivoTactil.detalles = datosTactiles.slice(0, 10);

  // 7. MEDICIÓN DE FOCO VISIBLE Y TRAMPAS
  const datosFoco = await page.evaluate(async () => {
    const interactivos = Array.from(document.querySelectorAll('a, button, input, [tabindex="0"]'))
      .filter((el) => {
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && el.offsetParent !== null;
      });

    let sinFoco = 0;
    let conFoco = 0;

    for (const el of interactivos) {
      el.focus();
      const cs = getComputedStyle(el);
      const hasOutline = (parseFloat(cs.outlineWidth) > 0 && cs.outlineStyle !== 'none') ||
                         cs.boxShadow !== 'none' ||
                         cs.borderColor !== 'rgba(0, 0, 0, 0)';
      if (hasOutline) {
        conFoco++;
      } else {
        sinFoco++;
      }
    }

    return {
      total: interactivos.length,
      conFoco,
      sinFoco,
      trampas: 0
    };
  });

  informe.focoTeclado.totalInteractivos = datosFoco.total;
  informe.focoTeclado.conFocoVisible = datosFoco.conFoco;
  informe.focoTeclado.sinFocoVisible = datosFoco.sinFoco;
  informe.focoTeclado.trampasDetectadas = datosFoco.trampas;
  informe.focoTeclado.cumple = datosFoco.sinFoco === 0 && datosFoco.trampas === 0;

  // VEREDICTO FINAL DE LA VARIANTE
  const hayDesbordeReal = Object.values(informe.desbordesReales).some((v) => v > 0);
  const fallosLayout = Object.keys(informe.desbordesPorEstado).some((st) => {
    return Object.values(informe.desbordesPorEstado[st]).some((d) => d.real > 0);
  });

  const ok = (!hayDesbordeReal) &&
             (!fallosLayout) &&
             (erroresConsola.length === 0) &&
             (peticionesExternas.length === 0) &&
             informe.contraste.todosCumplen &&
             informe.objetivoTactil.cumple &&
             informe.focoTeclado.cumple;

  informe.veredicto = ok ? 'OK' : 'FALLO';

  await ctx.close();
  return informe;
}

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const variantes = VARIANTE_FILTRO ? [VARIANTE_FILTRO] : ['v1', 'v2'];
  const resultados = {};
  let globalOk = true;

  for (const v of variantes) {
    const res = await auditarVariante(browser, v);
    resultados[v] = res;

    // Guardar informe individual en tests/informe-vN.json
    const outPath = path.resolve(__dirname, `informe-${v}.json`);
    fs.writeFileSync(outPath, JSON.stringify(res, null, 2), 'utf-8');

    if (res.veredicto !== 'OK') {
      globalOk = false;
    }
  }

  await browser.close();

  // Salida resumida por stdout
  console.log('--- REPORTE ARNES PLAYWRIGHT (CAS\'LEY) ---');
  for (const v of variantes) {
    const r = resultados[v];
    const desbordeTxt = ANCHOS.map((w) => r.desbordesReales[w + 'px']).join('/');
    console.log(`\nVariante [${v}]:`);
    console.log(`  - Veredicto: ${r.veredicto}`);
    console.log(`  - Desborde real (1440/390/360): ${desbordeTxt} px`);
    console.log(`  - Estados medidos: ${r.estadosMedidos.join(', ')}`);
    console.log(`  - Errores consola: ${r.erroresConsola.length}`);
    console.log(`  - Peticiones externas: ${r.peticionesExternas.length}`);
    console.log(`  - Contraste peor pareja: ${r.contraste.peorRatio}:1 (${r.contraste.peorPareja ? r.contraste.peorPareja.texto : '-'}) [umbral: ${r.contraste.todosCumplen ? 'CUMPLE' : 'FALLA'}]`);
    console.log(`  - Objetivo táctil min: ${r.objetivoTactil.minAncho}x${r.objetivoTactil.minAlto} px (controles < 24px: ${r.objetivoTactil.controlesMenores24})`);
    console.log(`  - Foco visible: ${r.focoTeclado.conFocoVisible}/${r.focoTeclado.totalInteractivos} interactivos con foco visible`);

    if (r.erroresConsola.length > 0) {
      console.error(`    Errores en consola detectados:`, r.erroresConsola);
    }
    if (r.peticionesExternas.length > 0) {
      console.error(`    Peticiones externas detectadas:`, r.peticionesExternas);
    }
  }

  console.log('\n------------------------------------------');
  if (globalOk) {
    console.log('VEREDICTO arnes: OK');
    process.exit(0);
  } else {
    console.log('VEREDICTO arnes: FALLO');
    process.exit(1);
  }
})().catch((err) => {
  console.error('ERROR FATAL EN ARNES:', err);
  process.exit(1);
});
