/* Novedades · CAS'LEY — explorador de publicaciones
   Sin dependencias. Filtrado en cliente sobre /novedades/datos.json.
   Si el fetch falla, la página conserva el listado servido en HTML. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const POR_PAGINA = 12;
  let DATOS = null, MATERIAS = {}, FUENTES = {}, MAXFECHA = '';
  const estado = { fuente: new Set(), tema: new Set(), tipo: new Set(), emisor: '', desde: '', hasta: '', q: '', orden: 'reciente' };
  let filtradas = [], pagina = 1;

  const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  const fechaLarga = iso => { const [a, m, d] = iso.split('-').map(Number); return `${d} de ${MESES[m - 1]} de ${a}`; };
  const fechaCorta = iso => { const [a, m, d] = iso.split('-').map(Number); return `${d} ${MESES[m - 1].slice(0, 3)} ${a}`; };
  const hoyISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

  /* ── Patrón de resaltado tolerante a acentos ── */
  function patron(q) {
    const base = norm(q).split(/\s+/).filter(Boolean);
    if (!base.length) return null;
    const clases = { a: '[aáàäâ]', e: '[eéèëê]', i: '[iíìïî]', o: '[oóòöô]', u: '[uúùüû]', n: '[nñ]', c: '[cç]' };
    const fuente = base.map(t => Array.from(t).map(ch => clases[ch] || ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('')).join('|');
    try { return new RegExp('(' + fuente + ')', 'gi'); } catch (_) { return null; }
  }
  function resaltar(texto, q) {
    const limpio = esc(texto);
    const re = q ? patron(q) : null;
    return re ? limpio.replace(re, '<mark>$1</mark>') : limpio;
  }

  /* ── Datos de URL ── */
  function leerURL() {
    const p = new URLSearchParams(location.search);
    (p.get('fuente') || '').split(',').filter(Boolean).forEach(v => estado.fuente.add(v));
    (p.get('tema') || '').split(',').filter(Boolean).forEach(v => estado.tema.add(v));
    (p.get('tipo') || '').split(',').filter(Boolean).forEach(v => estado.tipo.add(v));
    estado.emisor = p.get('emisor') || '';
    estado.desde = p.get('desde') || '';
    estado.hasta = p.get('hasta') || '';
    estado.q = p.get('q') || '';
    estado.orden = p.get('orden') === 'relevancia' ? 'relevancia' : 'reciente';
  }
  function escribirURL() {
    const p = new URLSearchParams();
    if (estado.fuente.size) p.set('fuente', [...estado.fuente].join(','));
    if (estado.tema.size) p.set('tema', [...estado.tema].join(','));
    if (estado.tipo.size) p.set('tipo', [...estado.tipo].join(','));
    if (estado.emisor) p.set('emisor', estado.emisor);
    if (estado.desde) p.set('desde', estado.desde);
    if (estado.hasta) p.set('hasta', estado.hasta);
    if (estado.q) p.set('q', estado.q);
    if (estado.orden !== 'reciente') p.set('orden', estado.orden);
    const qs = p.toString();
    try { history.replaceState(null, '', qs ? '?' + qs : location.pathname); } catch (_) { /* file:// */ }
  }

  /* ── Predicado de filtrado ── */
  function coincide(n, omitir) {
    if (omitir !== 'fuente' && estado.fuente.size && !estado.fuente.has(n.fuente)) return false;
    if (omitir !== 'tema' && estado.tema.size && !(n.materias || []).some(m => estado.tema.has(m))) return false;
    if (omitir !== 'tipo' && estado.tipo.size && !estado.tipo.has(n.tipo)) return false;
    if (estado.emisor && n.emisor !== estado.emisor) return false;
    if (estado.desde && n.fecha < estado.desde) return false;
    if (estado.hasta && n.fecha > estado.hasta) return false;
    if (omitir !== 'q' && estado.q) {
      const texto = norm([n.titulo, n.resumen, n.emisor, n.tipo, (n.materias || []).map(m => MATERIAS[m] || m).join(' ')].join(' '));
      const terminos = norm(estado.q).split(/\s+/).filter(Boolean);
      if (!terminos.every(t => texto.includes(t))) return false;
    }
    return true;
  }

  function ordenar(lista) {
    const copia = lista.slice();
    if (estado.orden === 'relevancia') {
      copia.sort((a, b) => (b.relevancia - a.relevancia) || b.fecha.localeCompare(a.fecha) || b.codigo - a.codigo);
    } else {
      copia.sort((a, b) => b.fecha.localeCompare(a.fecha) || (b.relevancia - a.relevancia) || b.codigo - a.codigo);
    }
    return copia;
  }

  /* ── Render ── */
  function desgloseTexto(n) {
    const det = n.relevancia_detalle || {};
    return (det.factores || []).map(f => `${f.motivo} ${f.puntos >= 0 ? '+' : ''}${f.puntos}`).join(' · ');
  }

  function tarjeta(n, q) {
    const esNuevo = MAXFECHA && n.fecha >= restarDias(MAXFECHA, 2);
    const mats = (n.materias || []).slice(0, 3).map(m =>
      `<a href="/novedades/materia/${esc(m)}.html" data-tema="${esc(m)}">${esc(MATERIAS[m] || m)}</a>`).join('');
    const pdf = n.pdf_url && n.pdf_url !== n.url
      ? `<a class="fuente-ext" href="${esc(n.pdf_url)}" target="_blank" rel="noopener nofollow">PDF ↗</a>` : '';
    return `<article class="nota" data-codigo="${esc(n.codigo)}">
      <div class="nota__cab">
        <span class="b b--fuente">${esc(n.fuente)}</span>
        <span class="b">${esc(n.tipo)}</span>
        ${esNuevo ? '<span class="b b--nuevo">Nuevo</span>' : ''}
        ${mats ? `<div class="materias">${mats}</div>` : ''}
        <time class="nota__fecha" datetime="${esc(n.fecha)}">${esc(fechaCorta(n.fecha))}</time>
      </div>
      <h3><a href="/novedades/${esc(n.clave)}.html">${resaltar(n.titulo, q)}</a></h3>
      <p class="nota__emisor">${resaltar(n.emisor, q)}</p>
      <p class="nota__resumen">${resaltar(n.resumen, q)}</p>
      <div class="nota__pie">
        <a class="cta" href="/novedades/${esc(n.clave)}.html">Leer ficha <span aria-hidden="true">→</span></a>
        <a class="fuente-ext" href="${esc(n.url)}" target="_blank" rel="noopener nofollow">Texto oficial ↗</a>
        ${pdf}
        <span class="rel" title="Relevancia estimada ${esc(n.relevancia)} de 100${desgloseTexto(n) ? ': ' + esc(desgloseTexto(n)) : ''}"><span class="rel__lbl">Relevancia</span>${esc(n.relevancia)}<i style="--v:${Math.max(0, Math.min(100, Number(n.relevancia) || 0))}%"></i></span>
      </div>
    </article>`;
  }

  function restarDias(iso, dias) {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() - dias);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function pintarLista() {
    const cont = $('#lista');
    if (!cont) return;
    const visibles = filtradas.slice(0, pagina * POR_PAGINA);
    let html = '', fechaActual = '';
    visibles.forEach(n => {
      if (n.fecha !== fechaActual) {
        if (fechaActual) html += '</div>';
        const totalDia = filtradas.filter(x => x.fecha === n.fecha).length;
        html += `<div class="grupo-fecha"><h2>${esc(fechaLarga(n.fecha))}</h2><span class="n-dia">${totalDia} ${totalDia === 1 ? 'publicación' : 'publicaciones'}</span></div><div class="lista">`;
        fechaActual = n.fecha;
      }
      html += tarjeta(n, estado.q);
    });
    if (fechaActual) html += '</div>';
    cont.innerHTML = html;

    const vacio = $('#vacio');
    if (vacio) vacio.hidden = filtradas.length > 0;
    const mas = $('#mas');
    if (mas) {
      const resto = filtradas.length - visibles.length;
      mas.hidden = resto <= 0;
      mas.textContent = `Ver más publicaciones (${resto})`;
    }
    const cuenta = $('#cuenta');
    if (cuenta) cuenta.innerHTML = filtradas.length === 1
      ? '<b>1</b> publicación'
      : `<b>${filtradas.length}</b> publicaciones`;
  }

  function pintarFacetas() {
    $$('[data-faceta]').forEach(inp => {
      const faceta = inp.dataset.faceta, valor = inp.dataset.valor;
      const n = DATOS.filter(x => coincide(x, faceta) && (
        faceta === 'tema' ? (x.materias || []).includes(valor) : x[faceta] === valor)).length;
      const etiqueta = inp.closest('label');
      const cont = etiqueta && etiqueta.querySelector('.n');
      if (cont) cont.textContent = n;
      if (etiqueta) etiqueta.style.opacity = n === 0 ? '.45' : '';
    });
    const sel = $('#emisor');
    if (sel) {
      $$('option', sel).forEach(o => {
        if (!o.value) return;
        const n = DATOS.filter(x => coincide(x, 'emisor') && x.emisor === o.value).length;
        o.textContent = `${o.dataset.etiqueta || o.value} (${n})`;
        o.disabled = n === 0;
      });
    }
  }

  function pintarChips() {
    const cont = $('#chips');
    if (!cont) return;
    const piezas = [];
    estado.fuente.forEach(v => piezas.push(['fuente', v, v]));
    estado.tema.forEach(v => piezas.push(['tema', v, MATERIAS[v] || v]));
    estado.tipo.forEach(v => piezas.push(['tipo', v, v]));
    if (estado.emisor) piezas.push(['emisor', estado.emisor, estado.emisor]);
    if (estado.desde) piezas.push(['desde', estado.desde, 'Desde ' + fechaCorta(estado.desde)]);
    if (estado.hasta) piezas.push(['hasta', estado.hasta, 'Hasta ' + fechaCorta(estado.hasta)]);
    if (estado.q) piezas.push(['q', estado.q, `“${estado.q}”`]);
    cont.innerHTML = piezas.map(([f, v, t]) =>
      `<li><button class="chip-filtro" type="button" data-quitar="${f}" data-valor="${esc(v)}">${esc(t)} <span aria-hidden="true">×</span><span class="visualmente-oculto">Quitar filtro</span></button></li>`).join('');
    const limpiar = $('#limpiar');
    if (limpiar) limpiar.hidden = piezas.length === 0;
    const cuentaBtn = $('#cuenta-filtros');
    if (cuentaBtn) {
      const total = estado.fuente.size + estado.tema.size + estado.tipo.size + (estado.emisor ? 1 : 0) + (estado.desde ? 1 : 0) + (estado.hasta ? 1 : 0);
      cuentaBtn.textContent = total;
      cuentaBtn.hidden = total === 0;
    }
  }

  function sincronizarControles() {
    $$('[data-faceta]').forEach(inp => {
      const set = estado[inp.dataset.faceta];
      inp.checked = set instanceof Set && set.has(inp.dataset.valor);
    });
    const q = $('#q'); if (q) q.value = estado.q;
    const em = $('#emisor'); if (em) em.value = estado.emisor;
    const or = $('#orden'); if (or) or.value = estado.orden;
    const de = $('#desde'); if (de) de.value = estado.desde;
    const ha = $('#hasta'); if (ha) ha.value = estado.hasta;
    $$('.preset').forEach(b => {
      const d = Number(b.dataset.dias);
      b.setAttribute('aria-pressed', String(d === 0 ? (!estado.desde && !estado.hasta) : (estado.desde === restarDias(hoyISO(), d) && !estado.hasta)));
    });
    const borrar = $('.borrar-q');
    if (borrar) borrar.hidden = !estado.q;
  }

  function aplicar(opciones) {
    if (!DATOS) return;
    if (!opciones || !opciones.conservarPagina) pagina = 1;
    filtradas = ordenar(DATOS.filter(n => coincide(n, null)));
    pintarLista();
    pintarFacetas();
    pintarChips();
    sincronizarControles();
    escribirURL();
  }

  function limpiarTodo() {
    estado.fuente.clear(); estado.tema.clear(); estado.tipo.clear();
    estado.emisor = estado.desde = estado.hasta = estado.q = '';
    estado.orden = 'reciente';
    aplicar();
  }

  /* ── Interacción ── */
  function enlazar() {
    $$('[data-faceta]').forEach(inp => {
      inp.addEventListener('change', () => {
        const set = estado[inp.dataset.faceta];
        if (!(set instanceof Set)) return;
        if (inp.checked) set.add(inp.dataset.valor); else set.delete(inp.dataset.valor);
        aplicar();
      });
    });

    const q = $('#q');
    if (q) {
      let t = null;
      q.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(() => { estado.q = q.value.trim(); aplicar(); }, 180);
      });
      const borrar = $('.borrar-q');
      if (borrar) borrar.addEventListener('click', () => { q.value = ''; estado.q = ''; aplicar(); q.focus(); });
    }

    const em = $('#emisor');
    if (em) em.addEventListener('change', () => { estado.emisor = em.value; aplicar(); });

    const or = $('#orden');
    if (or) or.addEventListener('change', () => { estado.orden = or.value; aplicar(); });

    const de = $('#desde');
    if (de) de.addEventListener('change', () => { estado.desde = de.value; aplicar(); });
    const ha = $('#hasta');
    if (ha) ha.addEventListener('change', () => { estado.hasta = ha.value; aplicar(); });

    $$('.preset').forEach(b => b.addEventListener('click', () => {
      const d = Number(b.dataset.dias);
      if (d === 0) { estado.desde = ''; estado.hasta = ''; }
      else { estado.desde = restarDias(hoyISO(), d); estado.hasta = ''; }
      aplicar();
    }));

    const limpiar = $('#limpiar');
    if (limpiar) limpiar.addEventListener('click', limpiarTodo);
    const vacioLimpiar = $('#vacio-limpiar');
    if (vacioLimpiar) vacioLimpiar.addEventListener('click', limpiarTodo);

    const chips = $('#chips');
    if (chips) chips.addEventListener('click', e => {
      const b = e.target.closest('[data-quitar]');
      if (!b) return;
      const f = b.dataset.quitar, v = b.dataset.valor;
      if (f === 'fuente' || f === 'tema' || f === 'tipo') estado[f].delete(v);
      else estado[f] = '';
      aplicar();
    });

    const mas = $('#mas');
    if (mas) mas.addEventListener('click', () => { pagina += 1; pintarLista(); });

    /* Drawer móvil */
    const panel = $('#filtros'), telon = $('#telon');
    const abrir = () => {
      if (!panel) return;
      panel.classList.add('abierto'); if (telon) telon.classList.add('on');
      document.body.style.overflow = 'hidden';
      const primero = panel.querySelector('input, select, button'); if (primero) primero.focus();
    };
    const cerrar = () => {
      if (!panel) return;
      panel.classList.remove('abierto'); if (telon) telon.classList.remove('on');
      document.body.style.overflow = '';
      const btn = $('#abrir-filtros'); if (btn) btn.focus();
    };
    const btnAbrir = $('#abrir-filtros'); if (btnAbrir) btnAbrir.addEventListener('click', abrir);
    const btnCerrar = $('#cerrar-filtros'); if (btnCerrar) btnCerrar.addEventListener('click', cerrar);
    const btnAplicar = $('#aplicar-movil'); if (btnAplicar) btnAplicar.addEventListener('click', cerrar);
    if (telon) telon.addEventListener('click', cerrar);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && panel && panel.classList.contains('abierto')) cerrar(); });

    /* Volver arriba */
    const arriba = $('#arriba');
    if (arriba) {
      const ver = () => arriba.classList.toggle('on', window.scrollY > 700);
      window.addEventListener('scroll', ver, { passive: true }); ver();
      arriba.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    }
  }

  /* ── Ficha: compartir ── */
  function enlazarFicha() {
    const b = $('#compartir');
    if (!b) return;
    b.addEventListener('click', async () => {
      const datos = { title: document.title, url: location.href };
      try {
        if (navigator.share) await navigator.share(datos);
        else { await navigator.clipboard.writeText(location.href); b.textContent = 'Enlace copiado ✓'; setTimeout(() => { b.textContent = 'Compartir'; }, 2000); }
      } catch (_) { /* cancelado */ }
    });
  }

  async function init() {
    enlazarFicha();
    const cont = $('#lista');
    if (!cont) return;
    leerURL();
    try {
      const r = await fetch('/novedades/datos.json', { cache: 'no-cache' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      DATOS = j.notas || []; MATERIAS = j.materias || {}; FUENTES = j.fuentes || {};
      MAXFECHA = DATOS.reduce((m, n) => n.fecha > m ? n.fecha : m, '');
      sincronizarControles();
      enlazar();
      aplicar();
    } catch (e) {
      const aviso = $('#aviso-js');
      if (aviso) { aviso.hidden = false; aviso.textContent = 'No se pudo cargar el índice de filtros. Se muestra el listado de las publicaciones más recientes; recarga la página para intentarlo de nuevo.'; }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
