#!/usr/bin/env node
/* tests/novedades.cjs — Arnés del explorador de Novedades.
   Mide lo que el ojo no ve: desbordes, consola, red externa, contraste,
   foco visible y coherencia entre los filtros y datos.json.

   Uso: node tests/novedades.cjs --servido=http://127.0.0.1:PUERTO
   (el sitio se sirve desde la raíz del repo, así que /novedades/ es v1/novedades) */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const arg = process.argv.find(a => a.startsWith('--servido='));
const BASE = arg ? arg.split('=')[1].replace(/\/$/, '') : 'http://127.0.0.1:8123';
const RAIZ = path.resolve(__dirname, '..');
const ANCHOS = [1440, 1024, 768, 390, 360];

const lum = hex => {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
    .map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const rgbHex = s => {
  const m = s.match(/\d+/g); if (!m) return null;
  return '#' + m.slice(0, 3).map(v => Number(v).toString(16).padStart(2, '0')).join('');
};

(async () => {
  const datos = JSON.parse(fs.readFileSync(path.join(RAIZ, 'v1/novedades/datos.json'), 'utf8'));
  const total = datos.notas.length;
  const fallos = [];
  const b = await chromium.launch();

  // 1. Desborde, consola y red en todos los anchos
  for (const ancho of ANCHOS) {
    const p = await b.newPage({ viewport: { width: ancho, height: 900 } });
    const errores = [], externas = [];
    p.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
    p.on('pageerror', e => errores.push(e.message));
    p.on('request', r => { const u = new URL(r.url()); if (!/127\.0\.0\.1|localhost/.test(u.host)) externas.push(r.url()); });
    await p.goto(`${BASE}/novedades/`, { waitUntil: 'networkidle' });
    await p.waitForSelector('#lista .nota');
    const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 1) fallos.push(`desborde de ${over}px a ${ancho}px`);
    if (errores.length) fallos.push(`consola a ${ancho}px: ${errores[0]}`);
    if (externas.length) fallos.push(`petición externa a ${ancho}px: ${externas[0]}`);
    console.log(`  [${ancho}px] desborde ${over}px · consola ${errores.length} · externas ${externas.length}`);
    await p.close();
  }

  const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
  await p.goto(`${BASE}/novedades/`, { waitUntil: 'networkidle' });
  await p.waitForSelector('#lista .nota');

  // 2. Contraste de los textos de interfaz
  const pares = await p.evaluate(() => {
    const fondo = getComputedStyle(document.body).backgroundColor;
    const sel = ['.lede', '.nota__resumen', '.nota__emisor', '.nota__fecha', '.opciones label', '.nota-fuente', '.resultado-cuenta', '.grupo-fecha h2', '.rel'];
    return sel.map(s => {
      const el = document.querySelector(s);
      if (!el) return null;
      const cs = getComputedStyle(el);
      let bg = cs.backgroundColor, n = el;
      while (n && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) { n = n.parentElement; if (n) bg = getComputedStyle(n).backgroundColor; }
      return { s, color: cs.color, bg: bg === 'rgba(0, 0, 0, 0)' ? fondo : bg };
    }).filter(Boolean);
  });
  for (const { s, color, bg } of pares) {
    const a = rgbHex(color), c = rgbHex(bg);
    if (!a || !c) continue;
    const r = ratio(a, c);
    if (r < 4.5) fallos.push(`contraste ${r.toFixed(2)}:1 en ${s}`);
    console.log(`  contraste ${s}: ${r.toFixed(2)}:1`);
  }

  // 3. Foco visible en los controles del panel
  const foco = await p.evaluate(() => {
    const els = [...document.querySelectorAll('#filtros input, #filtros button, #filtros select, .barra input, .barra select, .barra button')]
      .filter(el => el.offsetParent !== null);
    let ok = 0, evaluables = 0;
    for (const el of els) {
      el.focus();
      // :focus-visible solo lo activa el navegador con interacción de teclado;
      // si no aplica, el control no es evaluable por script y no cuenta como fallo.
      if (!el.matches(':focus-visible')) continue;
      evaluables++;
      const cs = getComputedStyle(el);
      if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) ok++;
    }
    return { ok, total: evaluables };
  });
  console.log(`  foco visible (script): ${foco.ok}/${foco.total}`);
  if (foco.ok !== foco.total) fallos.push(`foco visible en ${foco.ok}/${foco.total} controles`);

  // Tabulación real: el foco de teclado sí debe pintar anillo en todos los controles
  await p.evaluate(() => document.querySelector('#q').focus());
  const sinAnillo = [];
  for (let i = 0; i < 10; i++) {
    await p.keyboard.press('Tab');
    const info = await p.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      return { id: el.id || el.name || el.tagName, anillo: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 };
    });
    if (info && !info.anillo) sinAnillo.push(info.id);
  }
  console.log(`  foco con Tab: ${sinAnillo.length ? 'sin anillo en ' + sinAnillo.join(', ') : 'anillo en los 10 saltos'}`);
  if (sinAnillo.length) fallos.push(`foco de teclado sin anillo en ${sinAnillo.join(', ')}`);

  // 4. Coherencia de filtros contra datos.json
  const casos = [
    ['tema', 'fiscal', n => (n.materias || []).includes('fiscal')],
    ['tipo', 'Decreto', n => n.tipo === 'Decreto'],
    ['fuente', 'DOF', n => n.fuente === 'DOF'],
  ];
  for (const [faceta, valor, pred] of casos) {
    const esperado = datos.notas.filter(pred).length;
    await p.check(`input[data-faceta="${faceta}"][data-valor="${valor}"]`);
    await p.waitForTimeout(150);
    const cuenta = Number((await p.textContent('#cuenta')).replace(/\D+/g, ''));
    if (cuenta !== esperado) fallos.push(`filtro ${faceta}=${valor}: ${cuenta} vs ${esperado} esperadas`);
    console.log(`  filtro ${faceta}=${valor}: ${cuenta} (esperado ${esperado})`);
    await p.uncheck(`input[data-faceta="${faceta}"][data-valor="${valor}"]`);
    await p.waitForTimeout(120);
  }

  // 5. Búsqueda combinada y estado en URL
  await p.fill('#q', 'hacienda');
  await p.waitForTimeout(300);
  const cuentaQ = Number((await p.textContent('#cuenta')).replace(/\D+/g, ''));
  const esperadoQ = datos.notas.filter(n => /hacienda/i.test([n.titulo, n.resumen, n.emisor, n.tipo].join(' '))).length;
  if (cuentaQ !== esperadoQ) fallos.push(`búsqueda "hacienda": ${cuentaQ} vs ${esperadoQ}`);
  if (!p.url().includes('q=hacienda')) fallos.push('la búsqueda no queda en la URL');
  console.log(`  búsqueda hacienda: ${cuentaQ} (esperado ${esperadoQ}) · url con estado: ${p.url().includes('q=hacienda')}`);

  // 6. Sin JavaScript se sirve contenido real
  const ctx = await b.newContext({ javaScriptEnabled: false, viewport: { width: 1280, height: 900 } });
  const sinJs = await ctx.newPage();
  await sinJs.goto(`${BASE}/novedades/`, { waitUntil: 'load' });
  const notasSinJs = await sinJs.locator('#lista .nota').count();
  console.log(`  sin JS: ${notasSinJs} notas servidas en HTML`);
  if (notasSinJs < 10) fallos.push(`sin JS solo se sirven ${notasSinJs} notas`);
  await ctx.close();

  // 7. Ficha
  const ficha = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errFicha = [];
  ficha.on('pageerror', e => errFicha.push(e.message));
  const una = datos.notas[0];
  await ficha.goto(`${BASE}/novedades/${una.clave}.html`, { waitUntil: 'networkidle' });
  const h1 = (await ficha.textContent('h1')).trim();
  if (!h1 || !h1.includes(una.titulo.slice(0, 30))) fallos.push('la ficha no muestra el título esperado');
  if (errFicha.length) fallos.push(`consola en ficha: ${errFicha[0]}`);
  const ld = await ficha.locator('script[type="application/ld+json"]').count();
  if (!ld) fallos.push('la ficha no incluye JSON-LD');
  console.log(`  ficha: h1 ok · JSON-LD ${ld} · errores ${errFicha.length}`);

  await b.close();
  console.log(`  total de notas en datos.json: ${total}`);
  if (fallos.length) {
    console.log('\nVEREDICTO novedades: FAIL');
    fallos.forEach(f => console.log('  - ' + f));
    process.exit(1);
  }
  console.log('\nVEREDICTO novedades: OK');
})();
