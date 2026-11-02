"""Analíticas de los dos módulos, listas para citar en el informe (todo se calcula con datos reales guardados).

Módulo A: embudo, calidad de la visión (confianza, acuerdo entre lecturas, acuerdo con visión clásica, latencia),
exactitud contra las etiquetas del dueño (accuracy, F1, matriz de confusión) y error del presupuesto automático.
Módulo B: ahorro de kilómetros / tiempo / combustible y, con el resultado real cargado, error de las estimaciones.
"""
import csv
import io
from datetime import datetime

from app.services import metrics as m
from app.services.cv_baseline import SEVERITY, STATES


def service_of(water, algae):
    """Misma regla del presupuesto: de estado del agua y algas a servicio."""
    if water in (None, 'desconocido'):
        return None
    return 'recuperacion' if water.startswith('verde_') else 'limpieza_total' if water == 'turbia' or algae else 'mantenimiento'


def _seconds(conversation):
    try:
        times = sorted(datetime.fromisoformat(c['at'].replace('Z', '+00:00')) for c in conversation if c.get('at'))
        return (times[-1] - times[0]).total_seconds() if len(times) > 1 else None
    except (ValueError, TypeError, KeyError):
        return None


def consultas(requests, analyses):
    by_id = {a['id']: a for a in analyses}
    valid = [a for a in analyses if a['result'].get('es_pileta') and a['result'].get('confianza', 0) >= 0.65 and a['result'].get('estado_agua') != 'desconocido']
    results = [a['result'] for a in analyses if a['result'].get('es_pileta')]
    metas = [a.get('meta') or {} for a in analyses]
    priced = [r['quote']['price'] for r in requests if r.get('quote', {}).get('price') is not None]
    booked = sum(1 for r in requests if r.get('outcome') == 'agendado')
    out = {
        'embudo': {'analisis': len(analyses), 'analisisValidos': len(valid), 'consultas': len(requests), 'conPrecio': len(priced), 'revisadas': sum(1 for r in requests if r.get('state') == 'reviewed'),
                   'contactadas': sum(1 for r in requests if r.get('outcome') in ('contactado', 'agendado')), 'agendadas': booked,
                   'conversionPct': round(100 * booked / len(requests), 1) if requests else None,
                   'abandonoPct': round(100 * (1 - len(requests) / len(valid)), 1) if valid else None},
        'distribuciones': {
            'estadoAgua': m.count_by(r['estado_agua'] for r in results), 'forma': m.count_by(r['tipo_pileta'] for r in results),
            'servicio': m.count_by(r['quote'].get('service') for r in requests), 'localidad': m.count_by(r['data'].get('zone') for r in requests),
            'certeza': m.count_by(r['quote'].get('certainty') for r in requests), 'resultado': m.count_by(r.get('outcome') or 'sin_gestion' for r in requests)},
        'precio': {**m.describe(priced), 'total': round(sum(priced))},
        'conversacion': {'duracionSeg': m.describe(_seconds(r.get('conversation', [])) for r in requests), 'mensajes': m.describe(len(r.get('conversation', [])) for r in requests)},
        'vision': {
            'confianza': m.describe(r['confianza'] for r in results), 'acuerdoModelo': m.describe(x.get('acuerdoModelo') for x in metas),
            'acuerdoCV': m.describe(x.get('acuerdoCV') for x in metas), 'latenciaMs': m.describe(x.get('latenciaMs') for x in metas),
            'revisionSugeridaPct': round(100 * sum(1 for x in metas if x.get('revisionSugerida')) / len(metas), 1) if metas else None,
            'indiceTurbidez': m.describe(r.get('indice_turbidez') for r in results), 'intensidadVerde': m.describe(r.get('intensidad_verde') for r in results)},
    }
    # --- Exactitud contra la verdad de terreno cargada por el dueño ---
    labeled = [(r, by_id.get(r['data'].get('analysisId'))) for r in requests if r.get('validation')]
    labeled = [(r, a) for r, a in labeled if a]
    water_pairs = [(r['validation']['water'], a['result']['estado_agua']) for r, a in labeled]
    cv_pairs = [(r['validation']['water'], (a.get('meta') or {}).get('cv', {}).get('estado_agua')) for r, a in labeled if (a.get('meta') or {}).get('cv', {}).get('es_pileta')]
    service_pairs = [(service_of(r['validation']['water'], r['validation']['algae']), r['quote'].get('service')) for r, a in labeled]
    shape_pairs = [(r['validation']['shape'], a['result']['tipo_pileta']) for r, a in labeled]
    water_labels = [s for s in STATES if any(s in p for p in water_pairs + cv_pairs)]
    reviewed = [(r['review']['price'], r['quote']['price']) for r in requests if r.get('review') and r['review'].get('price') is not None and r['quote'].get('price') is not None]
    out['exactitud'] = {
        'etiquetadas': len(labeled), 'sinEtiquetar': len(requests) - len(labeled),
        'estadoAgua': m.classification_report(water_pairs, water_labels), 'estadoAguaOrdinal': m.ordinal_report(water_pairs, SEVERITY),
        'estadoAguaVisionClasica': m.classification_report(cv_pairs, water_labels),
        'algas': m.binary_report([(r['validation']['algae'], a['result']['presencia_algas_paredes']) for r, a in labeled]),
        'forma': m.classification_report(shape_pairs), 'servicio': m.classification_report(service_pairs),
        'minimoRecomendado': 30,
    }
    out['presupuesto'] = {'conPrecioRevisado': len(reviewed), 'error': m.regression_report([(real, est) for real, est in reviewed]),
                          'ajustadasPct': round(100 * sum(1 for r, e in reviewed if abs(r - e) > 0.5) / len(reviewed), 1) if reviewed else None}
    return out


def _end_minutes(route):
    ends = [b.get('fin') for b in route.get('equipos', []) if b.get('paradas') and b.get('fin')]
    if not ends:
        return None
    h, mi = max(ends).split(':')
    return int(h) * 60 + int(mi)


def plan_metrics(result):
    """Números de un recorrido calculado (sin nombres ni teléfonos), para guardar como evento de analítica."""
    a, r = result['analitica'], result['resumen']
    c = a['comparables']
    return {'fecha': result.get('fecha'), 'dia': result.get('dia'), 'paradas': r['paradas'], 'bloques': r['bloques'], 'km': a['kmOptimizado'], 'kmManual': a['kmManual'],
            'kmVecino': a['kmVecino'], 'ahorroKm': round(a['kmManual'] - a['kmOptimizado'], 1), 'ahorroPct': a['ahorroVsManualPct'], 'ahorroMin': a['ahorroMin'],
            'ahorroLitros': a['ahorroLitros'], 'ahorroPesos': a['ahorroPesos'], 'bloquesComparables': c['bloques'], 'kmVecinoComparable': c['kmVecino'],
            'ahorroVsVecinoPct': c['ahorroVsVecinoPct'], 'bloquesExactos': a['bloquesExactos'], 'bloquesHeuristicos': a['bloquesHeuristicos'],
            'ubicacionExactaPct': a['ubicacionExactaPct'], 'calculoMs': a['calculoMs'], 'pendientes': r['pendientes']}


def rutas(plans, saved):
    """`plans` = métricas de cada recorrido calculado; `saved` = recorridos guardados completos (con 'real' si se cargó)."""
    km_saved = sum(p.get('ahorroKm', 0) for p in plans)
    real_pairs_km, real_pairs_min, rows = [], [], []
    for r in saved:
        real = r.get('real')
        if not real:
            continue
        est_km, est_end = (r.get('resumen') or {}).get('km'), _end_minutes(r)
        real_h, real_m = real['finReal'].split(':')
        real_pairs_km.append((real['kmReal'], est_km))
        if est_end is not None:
            real_pairs_min.append((int(real_h) * 60 + int(real_m), est_end))
        rows.append({'fecha': r.get('fecha'), 'kmEstimado': est_km, 'kmReal': real['kmReal'], 'finEstimado': est_end, 'finReal': real['finReal']})
    weekday = {}
    for p in plans:
        weekday.setdefault(p.get('dia') or '—', []).append(p.get('ahorroPct', 0))
    return {
        'planes': len(plans), 'guardados': len(saved), 'conResultadoReal': len(rows),
        'paradas': m.describe(p.get('paradas') for p in plans), 'paradasTotal': sum(p.get('paradas', 0) for p in plans),
        'kmOptimizado': m.describe(p.get('km') for p in plans), 'kmManual': m.describe(p.get('kmManual') for p in plans),
        'ahorroPct': m.describe(p.get('ahorroPct') for p in plans), 'ahorroKmTotal': round(km_saved, 1),
        'ahorroMinTotal': sum(p.get('ahorroMin', 0) for p in plans), 'ahorroLitrosTotal': round(sum(p.get('ahorroLitros', 0) for p in plans), 1),
        'ahorroPesosTotal': sum(p.get('ahorroPesos', 0) for p in plans),
        'vsVecino': m.describe(p.get('ahorroVsVecinoPct') for p in plans if p.get('bloquesComparables')),
        'calculoMs': m.describe(p.get('calculoMs') for p in plans),
        'metodo': {'exactos': sum(p.get('bloquesExactos', 0) for p in plans), 'heuristicos': sum(p.get('bloquesHeuristicos', 0) for p in plans)},
        'ubicacionExactaPct': m.describe(p.get('ubicacionExactaPct') for p in plans),
        'porDia': {d: {'planes': len(v), 'ahorroPctMedio': round(sum(v) / len(v), 1)} for d, v in weekday.items()},
        'serie': [{'fecha': p.get('fecha'), 'ahorroPct': p.get('ahorroPct'), 'km': p.get('km'), 'kmManual': p.get('kmManual'), 'paradas': p.get('paradas')} for p in plans[-30:]],
        'errorReal': {'km': m.regression_report(real_pairs_km), 'finMin': m.regression_report(real_pairs_min), 'detalle': rows},
    }


def analysis_csv(requests, analyses):
    by_req = {r['data'].get('analysisId'): r for r in requests if r['data'].get('analysisId')}
    out = io.StringIO()
    w = csv.writer(out)
    cols = ['analisis_id', 'consulta_id', 'fecha', 'es_pileta', 'estado_agua_ia', 'algas_ia', 'forma_ia', 'confianza', 'acuerdo_modelo', 'estado_agua_cv', 'acuerdo_cv', 'muestras', 'calidad_foto',
            'indice_turbidez', 'intensidad_verde', 'latencia_ms', 'revision_sugerida', 'estado_agua_real', 'algas_real', 'forma_real', 'servicio_ia', 'servicio_real', 'precio_estimado', 'precio_revisado', 'certeza']
    w.writerow(cols)
    for a in analyses:
        r, res, meta = by_req.get(a['id']), a['result'], a.get('meta') or {}
        val = (r or {}).get('validation') or {}
        w.writerow([a['id'], (r or {}).get('id', ''), (r or {}).get('createdAt', ''), res.get('es_pileta'), res.get('estado_agua'), res.get('presencia_algas_paredes'), res.get('tipo_pileta'), res.get('confianza'),
                    meta.get('acuerdoModelo'), (meta.get('cv') or {}).get('estado_agua'), meta.get('acuerdoCV'), meta.get('muestras'), res.get('calidad_foto'), res.get('indice_turbidez'), res.get('intensidad_verde'),
                    meta.get('latenciaMs'), meta.get('revisionSugerida'), val.get('water', ''), val.get('algae', ''), val.get('shape', ''), ((r or {}).get('quote') or {}).get('service', ''),
                    service_of(val.get('water'), val.get('algae')) or '', ((r or {}).get('quote') or {}).get('price', ''), ((r or {}).get('review') or {}).get('price', ''), ((r or {}).get('quote') or {}).get('certainty', '')])
    return out.getvalue()


def routes_csv(plans, saved):
    real = {r['id']: r.get('real') for r in saved if r.get('real')}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['fecha', 'dia', 'paradas', 'bloques', 'km_manual', 'km_vecino_comparable', 'km_optimizado', 'ahorro_km', 'ahorro_pct', 'ahorro_min', 'ahorro_litros', 'ahorro_pesos', 'bloques_exactos',
                'bloques_heuristicos', 'ubicacion_exacta_pct', 'calculo_ms', 'ruta_guardada', 'km_real', 'fin_real'])
    for p in plans:
        rl = real.get(p.get('rutaId')) or {}
        w.writerow([p.get('fecha'), p.get('dia'), p.get('paradas'), p.get('bloques'), p.get('kmManual'), p.get('kmVecinoComparable'), p.get('km'), p.get('ahorroKm'), p.get('ahorroPct'), p.get('ahorroMin'),
                    p.get('ahorroLitros'), p.get('ahorroPesos'), p.get('bloquesExactos'), p.get('bloquesHeuristicos'), p.get('ubicacionExactaPct'), p.get('calculoMs'), p.get('rutaId', ''), rl.get('kmReal', ''), rl.get('finReal', '')])
    return out.getvalue()
