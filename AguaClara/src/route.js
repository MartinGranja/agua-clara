'use strict';
// Módulo B · pantalla "Recorrido del día". Usa la sesión del panel de admin (misma clave).
(() => {
  const {$, esc, api, toast, download} = UI;
  const EXAMPLE = 'VIERNES\nALTA GRACIA 3 y 3\nCLIO AZUL:\n//Ana Demo 0 limp 2c 1p 13:30\n/Beto Demo 1 limp 2c\n.Carla Demo (llamar antes)\nDiego Demo 2 limp 2c 1p llevar sacahojas\nDejar 1c a Fabio Demo\nCLIO GRIS:\n//Gaby Demo -1 limp 2c\nHugo Demo\nPedro Perez 3 limp 2c';
  const DAYS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  let last = null;
  const today = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
  const fail = e => { $('route-error').textContent = e.message; if (e.status === 401) { toast('Ingresá primero la clave en Panel de admin.'); UI.view('owner'); } };
  const km = n => new Intl.NumberFormat('es-AR', {maximumFractionDigits: 1}).format(n);
  const hm = m => m >= 60 ? Math.floor(m / 60) + ' h ' + String(Math.round(m % 60)).padStart(2, '0') + ' min' : Math.round(m) + ' min';

  function analysisHtml(a) {
    if (!a) return '';
    const c = a.comparables, max = Math.max(a.kmManual, a.kmOptimizado, 1);
    const bar = (name, v, cls) => '<div class="hbar ' + cls + '"><span>' + esc(name) + '</span><div class="track"><i style="width:' + Math.max(2, v / max * 100).toFixed(1) + '%"></i></div><b>' + km(v) + ' km</b></div>';
    const vs = c.bloques ? 'En los ' + c.bloques + ' bloques sin hora fija, donde los tres criterios son comparables: orden anotado ' + km(c.kmManual) + ' km, vecino más cercano ' + km(c.kmVecino) + ' km y optimizado ' + km(c.kmOptimizado) + ' km (' + km(c.ahorroVsVecinoPct) + ' % menos que el vecino más cercano).' : 'Todos los bloques tienen horas fijas, por eso no se compara con el vecino más cercano (no respeta horarios).';
    return '<section class="route-analytics"><h2>Análisis del recorrido</h2><div class="hbars">' + bar('Orden en que lo anotaste', a.kmManual, 'bad') + (a.kmVecino ? bar('Vecino más cercano (ignora horas)', a.kmVecino, 'mid') : '') + bar('Optimizado', a.kmOptimizado, 'good') + '</div>' +
      '<div class="stats">' + [[a.ahorroVsManualPct + ' %', 'Menos kilómetros que tu orden'], ['≈ ' + a.ahorroMin + ' min', 'Menos traslado (a ' + 38 + ' km/h)'], [km(a.ahorroLitros) + ' L', 'Combustible ahorrado'], ['$ ' + new Intl.NumberFormat('es-AR').format(a.ahorroPesos), 'Ahorro estimado']].map(([n, l]) => '<div class="stat"><b>' + esc(n) + '</b><span>' + esc(l) + '</span></div>').join('') + '</div>' +
      '<p class="help">' + esc(vs) + ' Combustible calculado con ' + esc(a.supuestosCombustible) + ' (editable en ruteo.yaml).</p>' +
      '<p class="help">Calidad: ' + a.bloquesExactos + ' bloque(s) resueltos con solución exacta y ' + a.bloquesHeuristicos + ' con heurística · ' + (a.ubicacionExactaPct == null ? '—' : km(a.ubicacionExactaPct) + ' %') + ' de las paradas con ubicación exacta · calculado en ' + a.calculoMs + ' ms.</p></section>';
  }

  function render(r) {
    last = r;
    const s = r.resumen;
    const stats = [[s.paradas, 'Piletas en el recorrido'], [km(s.km) + ' km', 'Recorrido optimizado'], [km(s.kmManual) + ' km', 'Orden en que las anotaste'], [s.ahorroPct + '%', 'Menos kilómetros']];
    let html = '<div class="stats">' + stats.map(([n, l]) => '<div class="stat"><b>' + esc(n) + '</b><span>' + esc(l) + '</span></div>').join('') + '</div>';
    html += analysisHtml(r.analitica);
    if (r.pendientes.length) html += '<div class="route-notes pending" role="alert"><b>A confirmar antes de salir (' + r.pendientes.length + ')</b><ul>' + r.pendientes.map(p => '<li>«' + esc(p.texto) + '» — ' + esc(p.motivo) + (p.opciones.length ? '. ¿Será ' + p.opciones.map(esc).join(' o ') + '?' : '') + '</li>').join('') + '</ul></div>';
    if (r.avisos.length) html += '<div class="route-notes"><b>Avisos</b><ul>' + r.avisos.map(a => '<li>' + esc(a) + '</li>').join('') + '</ul></div>';
    if (r.baseDemo) html += '<div class="route-notes"><b>Estás usando la base de clientes de demostración.</b> Importá tus clientes abajo para trabajar con los reales.</div>';
    html += r.equipos.map((t, i) => {
      if (!t.paradas.length) return '<article class="team"><div class="team-head"><h2>' + esc(t.nombre) + '</h2><span>Sin paradas</span></div></article>';
      const rows = t.paradas.map(p => '<li class="' + (p.retraso ? 'late' : '') + '"><b class="n">' + p.orden + '</b><div><b>' + esc(p.texto || p.cliente) + '</b>' + (p.texto ? ' <small>' + esc(p.cliente) + '</small>' : '') + (!p.enBase ? '<span class="tag">FALTA en la base</span>' : p.ubicacion === 'aproximada' ? '<span class="tag">ubicación aproximada</span>' : '') + (p.detalle.length ? '<small>' + p.detalle.map(esc).join(' · ') + '</small>' : '') + (p.direccion ? '<small>' + esc(p.direccion) + '</small>' : '') + (p.mapa ? '<small><a href="' + esc(p.mapa) + '" target="_blank" rel="noopener noreferrer">Abrir en el mapa</a></small>' : '') + '</div><div class="time">' + esc(p.llegada) + (p.horaPedida ? '<small>pedida ' + esc(p.horaPedida) + '</small>' : '') + (p.corrida ? '<small>corrida −' + p.corrida + ' min</small>' : '') + '</div></li>').join('');
      return '<article class="team"><div class="team-head"><h2>' + esc(t.nombre) + '</h2><span>' + t.piletas + ' piletas · ' + km(t.km) + ' km · termina ~' + esc(t.fin) + ' (' + hm(t.minutos) + ') · método ' + esc(t.metodo) + '</span></div><ol>' + rows + '</ol><pre class="message-box">' + esc(t.mensaje) + '</pre><div class="route-buttons"><button type="button" data-copy="' + i + '">Copiar mensaje</button><a class="button" target="_blank" rel="noopener noreferrer" href="https://wa.me/?text=' + encodeURIComponent(t.mensaje) + '">Abrir en WhatsApp</a></div></article>';
    }).join('');
    html += '<p class="lead">' + esc(r.supuestos) + (r.id ? ' Recorrido guardado.' : '') + '</p><div class="route-buttons"><button type="button" id="route-export" class="quiet">Exportar resultado</button></div>';
    $('route-result').innerHTML = html;
    $('route-result').querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => { try { await navigator.clipboard.writeText(r.equipos[b.dataset.copy].mensaje); toast('Mensaje copiado.'); } catch { toast('No se pudo copiar. Seleccioná el texto y copialo.'); } });
    $('route-export').onclick = () => download('AguaClara-recorrido-' + r.fecha + '.json', JSON.stringify(r, null, 2));
  }

  async function plan(e) {
    e.preventDefault();
    $('route-error').textContent = '';
    const button = $('route-go');
    button.disabled = true; button.textContent = 'Armando…';
    try {
      const r = await api('/api/admin/route/plan', {method: 'POST', body: JSON.stringify({lista: $('route-list').value, fecha: $('route-date').value || null, inicio: $('route-start').value || '08:30', servicio: Number($('route-service').value) || 30, traslado: $('route-travel').checked, guardar: $('route-save').checked})});
      render(r);
      if (r.id) loadHistory();
    } catch (err) { fail(err); }
    finally { button.disabled = false; button.textContent = 'Armar recorrido'; }
  }

  async function loadClients() {
    try {
      const c = await api('/api/admin/clients');
      const z = Object.entries(c.summary.porZona).filter(([, n]) => n).map(([k, n]) => k + ': ' + n).join(' · ');
      $('route-clients-count').textContent = '(' + c.summary.total + (c.demo ? ', demostración' : '') + ')';
      $('route-clients-info').textContent = (c.demo ? 'Base de demostración con clientes ficticios. ' : '') + c.summary.total + ' clientes · ' + c.summary.conCoordenadas + ' con coordenadas exactas · ' + c.summary.sinCoordenadas + ' sin coordenadas (se usa el centro de la zona) · ' + c.summary.sinTelefono + ' sin teléfono. ' + z;
    } catch (err) { if (err.status !== 401) $('route-clients-info').textContent = err.message; }
  }

  async function loadHistory() {
    try {
      const list = await api('/api/admin/routes');
      $('route-history-body').innerHTML = list.length ? list.map(x => '<div class="saved-route"><span>' + esc(x.dia || '') + ' ' + esc(x.fecha || '') + ' · ' + (x.resumen?.paradas ?? 0) + ' paradas · ' + km(x.resumen?.km ?? 0) + ' km estimados' + (x.real ? ' · real ' + km(x.real.kmReal) + ' km, fin ' + esc(x.real.finReal) : '') + '</span><button type="button" class="quiet" data-route="' + esc(x.id) + '">Ver</button><details class="real"><summary>' + (x.real ? 'Editar resultado real' : 'Registrar resultado real') + '</summary><form data-real="' + esc(x.id) + '" class="real-form"><label>Kilómetros reales<input name="km" type="number" min="1" max="1000" step="0.1" required value="' + (x.real ? x.real.kmReal : '') + '"></label><label>Hora en que terminaste<input name="fin" type="time" required value="' + (x.real ? esc(x.real.finReal) : '') + '"></label><label>Nota (opcional)<input name="nota" maxlength="300" value="' + esc(x.real?.nota || '') + '"></label><button class="primary">Guardar</button><p class="help">Estimado: ' + km(x.resumen?.km ?? 0) + ' km, fin ~' + esc(x.fin || '—') + '. Sirve para medir el error de la estimación en Analíticas.</p></form></details></div>').join('') : '<p>Todavía no guardaste recorridos.</p>';
      $('route-history-body').querySelectorAll('[data-real]').forEach(form => form.onsubmit = async e => { e.preventDefault(); const b = form.querySelector('button'); b.disabled = true; try { await api('/api/admin/routes/' + form.dataset.real + '/real', {method: 'PATCH', body: JSON.stringify({kmReal: Number(form.elements.km.value), finReal: form.elements.fin.value, nota: form.elements.nota.value.trim()})}); toast('Resultado real guardado.'); loadHistory(); } catch (err) { fail(err); b.disabled = false; } });
      $('route-history-body').querySelectorAll('[data-route]').forEach(b => b.onclick = async () => { try { const r = await api('/api/admin/routes/' + b.dataset.route); $('route-list').value = r.lista || ''; render(r); window.scrollTo({top: 0, behavior: 'smooth'}); } catch (err) { fail(err); } });
    } catch (err) { if (err.status !== 401) $('route-history-body').textContent = err.message; }
  }

  async function importClients() {
    const msg = $('route-import-msg'); msg.textContent = '';
    try {
      const r = await api('/api/admin/clients', {method: 'PUT', body: JSON.stringify({csv: $('route-csv').value, replace: true})});
      msg.textContent = 'Se importaron ' + r.imported + ' clientes.' + (r.warnings.length ? ' Avisos: ' + r.warnings.slice(0, 5).join(' ') : '');
      $('route-csv').value = ''; loadClients();
    } catch (err) { msg.textContent = err.message; if (err.status === 401) fail(err); }
  }

  $('route-form').onsubmit = plan;
  $('route-date').value = today();
  $('route-example').onclick = () => { $('route-list').value = EXAMPLE; };
  $('route-suggest').onclick = async () => {
    const d = $('route-date').value ? new Date($('route-date').value + 'T12:00:00') : new Date();
    try { const r = await api('/api/admin/route/suggest?dia=' + encodeURIComponent(DAYS[d.getDay()])); if (!r.lista) toast('No hay clientes con ese día habitual.'); else $('route-list').value = DAYS[d.getDay()][0].toUpperCase() + DAYS[d.getDay()].slice(1) + '\n' + r.lista; } catch (err) { fail(err); }
  };
  $('route-csv-file').onchange = async e => { const f = e.target.files[0]; if (f) { if (f.size > 400000) { $('route-import-msg').textContent = 'El archivo es demasiado grande.'; return; } $('route-csv').value = await f.text(); } };
  $('route-import').onclick = importClients;
  $('route-demo').onclick = async () => { try { await api('/api/admin/clients', {method: 'DELETE'}); $('route-import-msg').textContent = 'Se volvió a la base de demostración.'; loadClients(); } catch (err) { fail(err); } };
  document.querySelector('[data-view="route"]').addEventListener('click', () => { loadClients(); loadHistory(); });
})();
