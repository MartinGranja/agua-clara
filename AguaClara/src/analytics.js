'use strict';
/* Vista "Analíticas": métricas de los dos módulos calculadas por el servidor con los datos reales guardados.
   Sirve para el informe (accuracy, F1, matriz de confusión, error del presupuesto, ahorro de kilómetros). */
const Analytics = (() => {
  const {$, esc, api, toast, fetchFile} = UI;
  const f = (x, d = 1) => x == null ? '—' : new Intl.NumberFormat('es-AR', {maximumFractionDigits: d, minimumFractionDigits: 0}).format(x);
  const pct = (x, d = 1) => x == null ? '—' : f(x * 100, d) + ' %';
  const pc = (x, d = 1) => x == null ? '—' : f(x, d) + ' %';
  const money = n => n == null ? '—' : UI.money(n);
  const state = k => (AC_CONFIG.states && AC_CONFIG.states[k]) || k;
  const SERVICE = k => (AC_CONFIG.services && AC_CONFIG.services[k]) || k;

  const kpi = (value, label, hint = '') => '<div class="stat"><b>' + esc(value) + '</b><span>' + esc(label) + '</span>' + (hint ? '<small>' + esc(hint) + '</small>' : '') + '</div>';
  const block = (title, body, note = '') => '<section class="an-block"><h2>' + esc(title) + '</h2>' + (note ? '<p class="help">' + esc(note) + '</p>' : '') + body + '</section>';

  function bars(obj, label = k => k, max) {
    const entries = Object.entries(obj || {});
    if (!entries.length) return '<p class="help">Todavía no hay datos.</p>';
    const top = max || Math.max(...entries.map(([, v]) => v), 1);
    return '<div class="hbars">' + entries.map(([k, v]) => '<div class="hbar"><span>' + esc(label(k)) + '</span><div class="track"><i style="width:' + Math.max(2, v / top * 100).toFixed(1) + '%"></i></div><b>' + esc(f(v, 0)) + '</b></div>').join('') + '</div>';
  }

  function stats(rows, unit = '') {
    return '<div class="table-wrap"><table class="an-table"><thead><tr><th>Medida</th><th>n</th><th>Media</th><th>Mediana</th><th>Mín.</th><th>Máx.</th></tr></thead><tbody>' +
      rows.map(([name, d, scale = 1, dec = 2]) => '<tr><th scope="row">' + esc(name) + '</th><td>' + d.n + '</td>' + ['mean', 'median', 'min', 'max'].map(k => '<td>' + esc(d[k] == null ? '—' : f(d[k] * scale, dec)) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
  }

  function confusion(rep, name = state) {
    if (!rep || !rep.n) return '';
    const labels = rep.labels, max = Math.max(...rep.confusion.flat(), 1);
    const head = '<tr><th class="corner">Real ↓ / IA →</th>' + labels.map(l => '<th scope="col">' + esc(name(l)) + '</th>').join('') + '</tr>';
    const body = rep.confusion.map((row, i) => '<tr><th scope="row">' + esc(name(labels[i])) + '</th>' + row.map((v, j) => '<td class="' + (i === j ? 'diag' : '') + '" style="--a:' + (v / max).toFixed(2) + '">' + (v || '') + '</td>').join('') + '</tr>').join('');
    return '<div class="table-wrap"><table class="confusion"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
  }

  function perClass(rep, name = state) {
    if (!rep || !rep.n) return '';
    return '<div class="table-wrap"><table class="an-table"><thead><tr><th>Clase</th><th>Precisión</th><th>Sensibilidad</th><th>F1</th><th>Casos</th></tr></thead><tbody>' +
      Object.entries(rep.classes).map(([k, c]) => '<tr><th scope="row">' + esc(name(k)) + '</th><td>' + pct(c.precision) + '</td><td>' + pct(c.recall) + '</td><td>' + pct(c.f1) + '</td><td>' + c.support + '</td></tr>').join('') + '</tbody></table></div>';
  }

  function line(series, key, color) {
    const pts = series.filter(p => p[key] != null);
    if (pts.length < 2) return '<p class="help">Con dos o más recorridos calculados se dibuja la evolución.</p>';
    const W = 640, H = 200, L = 40, R = 12, T = 14, B = 26;
    const vals = pts.map(p => p[key]), lo = Math.min(0, ...vals), hi = Math.max(...vals, 1);
    const x = i => L + (W - L - R) * i / (pts.length - 1), y = v => H - B - (H - T - B) * (v - lo) / ((hi - lo) || 1);
    const path = pts.map((p, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p[key]).toFixed(1)).join(' ');
    const grid = [0, .5, 1].map(t => { const v = lo + (hi - lo) * t; return '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '" class="grid"/><text x="' + (L - 6) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end">' + f(v, 0) + '</text>'; }).join('');
    const last = pts[pts.length - 1];
    return '<figure class="chart"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Evolución del ahorro de kilómetros por recorrido calculado">' + grid +
      '<path d="' + path + ' L' + x(pts.length - 1).toFixed(1) + ' ' + y(lo).toFixed(1) + ' L' + L + ' ' + y(lo).toFixed(1) + ' Z" class="area"/><path d="' + path + '" class="ln"/>' +
      '<circle cx="' + x(pts.length - 1).toFixed(1) + '" cy="' + y(last[key]).toFixed(1) + '" r="4.5" class="dot"/><text x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end">recorridos más recientes →</text></svg>' +
      '<figcaption>Ahorro de kilómetros (%) de cada recorrido contra el orden en que se anotó. Último: ' + esc(f(last[key], 1)) + ' %.</figcaption></figure>';
  }

  function moduleA(c) {
    const e = c.embudo, v = c.vision, x = c.exactitud, p = c.presupuesto;
    let html = '<div class="stats">' + kpi(e.consultas, 'Consultas recibidas', e.analisis + (e.analisis === 1 ? ' foto analizada' : ' fotos analizadas')) + kpi(e.conversionPct == null ? '—' : f(e.conversionPct) + ' %', 'Conversión a cliente', e.agendadas + ' agendadas') +
      kpi(money(c.precio.mean), 'Precotización media', c.precio.n + ' con precio') + kpi(pct(v.confianza.mean, 0), 'Confianza media de la IA', 'revisión sugerida en ' + pc(v.revisionSugeridaPct, 0)) +
      kpi(pct(v.acuerdoModelo.mean, 0), 'Acuerdo entre lecturas', 'contraste con visión por color: ' + pct(v.acuerdoCV.mean, 0)) + kpi(v.latenciaMs.mean == null ? '—' : f(v.latenciaMs.mean / 1000) + ' s', 'Tiempo medio de análisis', 'n = ' + v.latenciaMs.n) + '</div>';
    html += block('Embudo de la consulta', bars({'Fotos analizadas': e.analisis, 'Fotos válidas': e.analisisValidos, 'Consultas guardadas': e.consultas, 'Con precio calculado': e.conPrecio, 'Revisadas por el dueño': e.revisadas, 'Contactadas o agendadas': e.contactadas, 'Agendadas': e.agendadas}),
      'Cuánta gente avanza en cada paso. Abandono entre foto válida y consulta guardada: ' + pc(e.abandonoPct, 0) + '.');
    html += '<div class="an-grid">' + block('Estado del agua detectado', bars(c.distribuciones.estadoAgua, state)) + block('Servicio sugerido', bars(c.distribuciones.servicio, SERVICE)) + block('Forma de la pileta', bars(c.distribuciones.forma, UI.SHAPE_LABEL)) +
      block('Localidad', bars(c.distribuciones.localidad)) + block('Certeza de la estimación', bars(c.distribuciones.certeza)) + block('Seguimiento', bars(c.distribuciones.resultado)) + '</div>';
    html += block('Calidad de la visión', stats([['Confianza final', v.confianza, 100, 1], ['Acuerdo entre lecturas (%)', v.acuerdoModelo, 100, 1], ['Acuerdo con visión por color (%)', v.acuerdoCV, 100, 1], ['Tiempo de análisis (ms)', v.latenciaMs, 1, 0], ['Índice de turbidez (0–100)', v.indiceTurbidez, 1, 1], ['Intensidad de verde (0–100)', v.intensidadVerde, 1, 1], ['Precio (ARS)', c.precio, 1, 0], ['Duración de la conversación (s)', c.conversacion.duracionSeg, 1, 0], ['Mensajes por conversación', c.conversacion.mensajes, 1, 0]]),
      'Medidas descriptivas sobre todas las fotos y consultas guardadas.');
    // Exactitud contra el estado real cargado por el dueño
    if (!x.etiquetadas) {
      html += block('Exactitud de la IA (accuracy, F1, matriz de confusión)', '<div class="empty small"><p>Todavía no hay consultas con el estado real cargado. Abrí una consulta en el panel, mirá la pileta en la visita y completá «Servicio real». Con ' + x.minimoRecomendado + ' o más (0 de ' + x.minimoRecomendado + ' hasta ahora) las métricas son confiables para el informe.</p></div>');
    } else {
      const sv = x.servicio, svc = x.servicioVisionClasica, w = x.estadoAgua, cvr = x.estadoAguaVisionClasica, o = x.estadoAguaOrdinal;
      html += block('Exactitud del servicio sugerido contra el servicio real', '<div class="stats">' + kpi(pct(sv.accuracy), 'Accuracy · servicio', 'n = ' + sv.n) + kpi(pct(sv.macroF1), 'F1 macro', 'ponderado ' + pct(sv.weightedF1)) +
        kpi(pct(svc.accuracy), 'Accuracy solo con visión por color', 'baseline · n = ' + svc.n) + kpi(pct(x.forma.accuracy), 'Accuracy · forma de la pileta', 'n = ' + x.forma.n) + kpi(pct(x.algas.f1), 'F1 · algas en paredes', 'n = ' + x.algas.n) + '</div>' +
        (x.etiquetadas < x.minimoRecomendado ? '<p class="review-error">Con ' + x.etiquetadas + (x.etiquetadas === 1 ? ' caso etiquetado' : ' casos etiquetados') + ' las cifras son orientativas; el mínimo recomendado es ' + x.minimoRecomendado + '.</p>' : '') +
        '<h3>Matriz de confusión · servicio</h3>' + confusion(sv, SERVICE) + '<h3>Por clase</h3>' + perClass(sv, SERVICE) +
        '<p>' + (svc.n ? 'La visión por color sola acierta el servicio en ' + pct(svc.accuracy) + ' (F1 macro ' + pct(svc.macroF1) + '), contra ' + pct(sv.accuracy) + ' del sistema combinado.' : 'La visión por color no pudo evaluar ninguna foto etiquetada.') + '</p>');
      if (w.n) html += block('Estado del agua (solo consultas donde se cargó el estado real)', '<div class="stats">' + kpi(pct(w.accuracy), 'Accuracy · estado del agua', 'n = ' + w.n) + kpi(pct(w.macroF1), 'F1 macro', 'ponderado ' + pct(w.weightedF1)) + kpi(pct(o.withinOne), 'Acierto con un escalón de margen', 'error medio ' + f(o.meanGap, 2)) + kpi(pct(cvr.accuracy), 'Visión por color sola', 'n = ' + cvr.n) + '</div>' + confusion(w) + perClass(w));
    }
    html += block('Error del presupuesto automático', p.conPrecioRevisado ? '<div class="stats">' + kpi(money(p.error.mae), 'Error absoluto medio (MAE)', 'n = ' + p.error.n) + kpi(pc(p.error.mape, 1), 'Error porcentual medio (MAPE)') + kpi(money(p.error.bias), 'Sesgo (estimado − revisado)') + kpi(money(p.error.rmse), 'RMSE') + kpi(pc(p.ajustadasPct, 0), 'Precios que el dueño corrigió') + '</div>' : '<div class="empty small"><p>Se calcula cuando el dueño guarda un importe revisado en una consulta: se compara el precio automático contra el que finalmente cobra.</p></div>',
      'Compara la precotización del sistema con el importe que el dueño confirmó después de la visita.');
    return html;
  }

  function moduleB(r) {
    if (!r.planes) return '<div class="empty small"><p>Todavía no se calculó ningún recorrido. Armá uno en «Recorrido del día» y vuelve acá.</p></div>';
    const real = r.errorReal;
    let html = '<div class="stats">' + kpi(r.planes, 'Recorridos calculados', r.paradasTotal + ' piletas en total') + kpi(f(r.ahorroKmTotal) + ' km', 'Kilómetros ahorrados', 'contra el orden anotado') + kpi(pc(r.ahorroPct.mean), 'Ahorro medio por recorrido', 'mín. ' + pc(r.ahorroPct.min) + ' · máx. ' + pc(r.ahorroPct.max)) +
      kpi(f(r.ahorroMinTotal, 0) + ' min', 'Tiempo de traslado ahorrado', 'a 38 km/h') + kpi(f(r.ahorroLitrosTotal) + ' L', 'Combustible ahorrado', money(r.ahorroPesosTotal) + ' con los supuestos editables') + kpi(pc(r.vsVecino.mean), 'Ahorro contra «vecino más cercano»', 'n = ' + r.vsVecino.n + ' recorridos comparables') + '</div>';
    html += block('Evolución del ahorro', line(r.serie, 'ahorroPct'));
    html += '<div class="an-grid">' + block('Kilómetros promedio por recorrido', bars({'Orden anotado': r.kmManual.mean, 'Optimizado': r.kmOptimizado.mean}, k => k, Math.max(r.kmManual.mean || 0, 1)), 'Media sobre todos los recorridos calculados.') +
      block('Cómo se resolvió cada bloque', bars({'Solución exacta (Held-Karp)': r.metodo.exactos, 'Heurística (inserción + 2-opt)': r.metodo.heuristicos})) +
      block('Calidad de los datos', '<div class="stats one">' + kpi(r.ubicacionExactaPct.mean == null ? '—' : f(r.ubicacionExactaPct.mean, 0) + ' %', 'Paradas con ubicación exacta', 'las demás usan el centro de la zona') + kpi(r.calculoMs.mean == null ? '—' : f(r.calculoMs.mean, 0) + ' ms', 'Tiempo de cálculo medio', 'máx. ' + f(r.calculoMs.max, 0) + ' ms') + '</div>') +
      block('Por día de la semana', Object.keys(r.porDia).length ? bars(Object.fromEntries(Object.entries(r.porDia).map(([d, v]) => [d + ' (' + v.planes + ')', v.ahorroPctMedio])), k => k) : '<p class="help">Sin datos.</p>', 'Ahorro medio (%) y cantidad de recorridos.') + '</div>';
    html += block('Estimado contra lo que pasó de verdad', real.km.n ? '<div class="stats">' + kpi(f(real.km.mae) + ' km', 'Error absoluto medio · kilómetros', 'n = ' + real.km.n) + kpi(pc(real.km.mape), 'Error porcentual medio · km') + kpi(f(real.km.bias) + ' km', 'Sesgo (estimado − real)') +
      kpi(real.finMin.n ? f(real.finMin.mae, 0) + ' min' : '—', 'Error medio · hora de fin', real.finMin.n ? 'n = ' + real.finMin.n : '') + '</div>' : '<div class="empty small"><p>Después de hacer un recorrido guardado, cargá los kilómetros reales y la hora en que terminaste (en «Recorridos guardados»). Con eso se mide cuánto se equivoca la estimación.</p></div>',
      'El ahorro de kilómetros y de tiempo es una estimación del modelo hasta que se carguen resultados reales.');
    return html;
  }

  async function load() {
    const out = $('analytics-body');
    $('analytics-error').textContent = '';
    out.setAttribute('aria-busy', 'true');
    try {
      const d = await api('/api/admin/analytics');
      out.innerHTML = '<h2 class="an-module">Módulo A · Precotizador con IA</h2>' + moduleA(d.consultas) + '<h2 class="an-module">Módulo B · Recorrido del día</h2>' + moduleB(d.rutas);
    } catch (e) {
      $('analytics-error').textContent = e.message;
      if (e.status === 401) { toast('Ingresá primero la clave en Panel de admin.'); UI.view('owner'); }
    } finally { out.removeAttribute('aria-busy'); }
  }

  $('analytics-refresh').onclick = load;
  $('analytics-export-a').onclick = () => fetchFile('/api/admin/export/analisis', 'aguaclara_analisis.csv');
  $('analytics-export-b').onclick = () => fetchFile('/api/admin/export/rutas', 'aguaclara_recorridos.csv');
  return {load};
})();
