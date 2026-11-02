"""Percepción híbrida: varias lecturas independientes de Gemini + una segunda opinión de visión clásica.

Por qué no alcanza una sola lectura: un modelo generativo puede equivocarse con mala luz o reflejos y siempre contesta
con aplomo. Acá cada foto se lee `vision_samples` veces (en paralelo), se mide cuánto coinciden las lecturas entre sí
(acuerdo) y con el detector de color (cv_baseline). La confianza final baja cuando hay desacuerdo o la foto es mala;
si queda por debajo del umbral del servicio (0,65) el sistema pide otra foto en vez de inventar un precio.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import mean

from app.schemas import Analysis
from app.services import cv_baseline
from app.services.cv_baseline import SEVERITY
from app.services.vision_service import VisionUnavailable

logger = logging.getLogger('aguaclara.perception')
QUALITY = {'buena': 1.0, 'regular': 0.9, 'mala': 0.7}
REVIEW_BELOW = 0.75   # por debajo de esta confianza final se sugiere revisión del dueño


def _severity(state):
    return SEVERITY.get(state)


def _vote(values):
    """Valor más frecuente; con empate, el primero en aparecer."""
    best = None
    for v in values:
        if best is None or values.count(v) > values.count(best):
            best = v
    return best


def _pairwise_agreement(samples):
    """Coincidencia media entre pares de lecturas en los tres datos que deciden el presupuesto."""
    if len(samples) < 2:
        return 1.0
    pairs = [(a, b) for i, a in enumerate(samples) for b in samples[i + 1:]]
    score = []
    for a, b in pairs:
        gap = abs((_severity(a.estado_agua) or 0) - (_severity(b.estado_agua) or 0)) if 'desconocido' not in (a.estado_agua, b.estado_agua) else 5
        water = 1.0 if gap == 0 else 0.5 if gap == 1 else 0.0
        algae = 1.0 if a.presencia_algas_paredes == b.presencia_algas_paredes else 0.0
        shape = 1.0 if a.tipo_pileta == b.tipo_pileta else 0.0
        score.append(0.6 * water + 0.2 * algae + 0.2 * shape)
    return mean(score)


def _pick_water(samples, cv):
    """Estado del agua consensuado. Con dos lecturas distintas decide el detector de color; sin él, la más severa."""
    known = [s.estado_agua for s in samples if s.estado_agua != 'desconocido']
    if not known:
        return 'desconocido'
    counts = {k: known.count(k) for k in known}
    top = max(counts.values())
    leaders = [k for k, c in counts.items() if c == top]
    if len(leaders) == 1:
        return leaders[0]
    if cv and cv['es_pileta']:
        return min(leaders, key=lambda k: abs(SEVERITY[k] - SEVERITY[cv['estado_agua']]))
    return max(leaders, key=lambda k: SEVERITY[k])


def fuse(samples, cv, latency_ms=0):
    """Combina lecturas + detector de color. Devuelve (Analysis, meta)."""
    if not any(s.es_pileta for s in samples) or sum(s.es_pileta for s in samples) * 2 < len(samples):
        base = samples[0].model_copy(update={'es_pileta': False, 'estado_agua': 'desconocido', 'confianza': 0.0})
        return base, {'muestras': len(samples), 'acuerdoModelo': 1.0, 'acuerdoCV': None, 'cv': cv, 'latenciaMs': latency_ms, 'revisionSugerida': True, 'motivos': ['No se reconoce una pileta.']}
    live = [s for s in samples if s.es_pileta]
    water = _pick_water(live, cv)
    shape = _vote([s.tipo_pileta for s in live])
    yes = sum(s.presencia_algas_paredes for s in live)
    algae = water.startswith('verde') if yes * 2 == len(live) else yes * 2 > len(live)   # empate: con agua verde se asume que hay algas
    # Rasgos numéricos: promedio de las lecturas que coinciden con el estado elegido (o de todas si ninguna).
    agree = [s for s in live if s.estado_agua == water] or live
    leader = min(agree, key=lambda s: -s.confianza)
    quality = _vote([s.calidad_foto for s in live])
    problems = list(dict.fromkeys(p for s in agree for p in s.problemas_visibles))[:8]
    model_agreement = _pairwise_agreement(live)
    cv_agreement, cv_factor = None, 1.0
    if cv and cv['es_pileta'] and water != 'desconocido':
        gap = abs(SEVERITY[water] - SEVERITY[cv['estado_agua']])
        cv_agreement = 1.0 if gap <= 1 else 0.5 if gap == 2 else 0.0
        cv_factor = 1.0 if gap <= 1 else 0.85 if gap == 2 else 0.7
    elif cv and not cv['es_pileta']:
        cv_factor = 0.95   # el detector de color no encontró agua: poca señal en contra, pero no se ignora
    confidence = mean(s.confianza for s in live) * (0.55 + 0.45 * model_agreement) * cv_factor * QUALITY[quality]
    confidence = round(min(1.0, max(0.0, confidence)), 3)
    reasons = []
    if model_agreement < 0.8:
        reasons.append('Las lecturas de la foto no coinciden del todo.')
    if cv_agreement is not None and cv_agreement < 1.0:
        reasons.append('El detector de color ve el agua distinta a la lectura principal.')
    if quality != 'buena':
        reasons.append('La calidad de la foto no es buena.')
    if confidence < REVIEW_BELOW:
        reasons.append('La confianza final es baja.')
    fused = leader.model_copy(update={
        'estado_agua': water, 'tipo_pileta': shape, 'presencia_algas_paredes': bool(algae), 'confianza': confidence, 'calidad_foto': quality,
        'problemas_visibles': problems,
        'indice_turbidez': round(mean(s.indice_turbidez for s in agree)), 'intensidad_verde': round(mean(s.intensidad_verde for s in agree)),
        'superficie_visible_pct': round(mean(s.superficie_visible_pct for s in live)), 'hojas_o_residuos': sum(s.hojas_o_residuos for s in live) * 2 > len(live)})
    meta = {'muestras': len(samples), 'acuerdoModelo': round(model_agreement, 3), 'acuerdoCV': cv_agreement, 'cv': cv, 'latenciaMs': latency_ms,
            'revisionSugerida': bool(reasons), 'motivos': reasons}
    return fused, meta


def perceive(image, settings, analyze_fn):
    """Lee la foto `vision_samples` veces en paralelo y la contrasta con visión clásica. Devuelve (Analysis, meta)."""
    started = time.perf_counter()
    n = max(1, min(3, int(getattr(settings, 'vision_samples', 2) or 1)))
    cv = cv_baseline.predict(image) if getattr(settings, 'cv_enabled', True) else None
    samples, failure = [], None
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(analyze_fn, image, settings, i) for i in range(n)]
        for future in futures:
            try:
                samples.append(future.result())
            except VisionUnavailable as exc:
                failure = failure or exc
    if not samples:
        raise failure
    # Desempate: si hay dos lecturas con estados lejanos entre sí y todavía se puede, se pide una tercera.
    live = [s for s in samples if s.es_pileta and s.estado_agua != 'desconocido']
    budget = float(getattr(settings, 'llm_timeout_seconds', 30)) * 0.6   # no gastar el tiempo máximo de la función
    if time.perf_counter() - started < budget and n == 2 and len(samples) == 2 and len(live) == 2 and abs(SEVERITY[live[0].estado_agua] - SEVERITY[live[1].estado_agua]) >= 2:
        try:
            samples.append(analyze_fn(image, settings, 2))
        except VisionUnavailable as exc:
            logger.warning('tiebreak_failed kind=%s', type(exc).__name__)
    return fuse(samples, cv, round((time.perf_counter() - started) * 1000))
