"""Clasificador propio de Agua Clara: decide el servicio a partir de la foto con un modelo entrenado con fotos etiquetadas
por el dueño. Sin Gemini y sin red; en producción usa solo numpy + Pillow (el entrenamiento, con scikit-learn, es offline).

Dos etapas, como razona el dueño:
1. ¿La pileta necesita tratamiento? (mantenimiento vs recuperación/limpieza total): modelo binario.
2. Si necesita tratamiento, la pregunta «¿hace más de 4 meses?» decide entre recuperación y limpieza total
   (misma regla que pricing_engine.service_for). Sin esa respuesta, decide el modelo de tres servicios.

Los rasgos son histogramas de matiz/saturación/valor, estadísticas de color y de bordes sobre tres regiones de la foto
(completa, mitad inferior, centro). Los pesos se guardan en app/data/clasificador_propio.json (scripts/entrenar_clasificador.py).
"""
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .cv_baseline import _hsv

MODEL_PATH = Path(__file__).resolve().parents[1] / 'data' / 'clasificador_propio.json'
SERVICES = ['mantenimiento', 'recuperacion', 'limpieza_total']
MAX_SIDE = 256
_cache = {}


def _region_features(a):
    h, s, v = _hsv(a)
    out = []
    for ch, bins, hi in ((h, 18, 360.0), (s, 8, 1.0), (v, 8, 1.0)):
        hist = np.histogram(ch, bins=bins, range=(0, hi))[0].astype(np.float64)
        out += list(hist / max(hist.sum(), 1.0))
    for ch in (a[..., 0], a[..., 1], a[..., 2], s, v):
        out += [float(ch.mean()), float(ch.std())]
    gray = a.mean(-1)
    gy, gx = np.gradient(gray)
    mag = np.hypot(gx, gy)
    out.append(float(mag.mean()))
    hist = np.histogram(np.minimum(mag, 0.4), bins=8, range=(0, 0.4))[0].astype(np.float64)
    out += list(hist / max(hist.sum(), 1.0))
    return out


def extract_features(image_bytes):
    """Vector de rasgos (159 valores) de una foto, o None si no se puede leer."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            a = np.asarray(im, dtype=np.float64) / 255.0
    except Exception:
        return None
    H, W = a.shape[:2]
    if H < 16 or W < 16:
        return None
    feats = []
    for region in (a, a[H // 2:, :], a[H // 4:3 * H // 4, W // 4:3 * W // 4]):
        feats += _region_features(region)
    return np.array(feats)


def load_model(path=MODEL_PATH):
    key = str(path)
    if key not in _cache:
        try:
            _cache[key] = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _cache[key] = None
    return _cache[key]


def _softmax_head(x, head):
    z = (x - np.array(head['mean'])) / np.array(head['scale'])
    logits = np.array(head['coef']) @ z + np.array(head['intercept'])
    if len(head['classes']) == 2 and logits.shape == (1,):
        p1 = 1.0 / (1.0 + np.exp(-logits[0]))
        return {head['classes'][0]: 1 - p1, head['classes'][1]: p1}
    e = np.exp(logits - logits.max())
    p = e / e.sum()
    return dict(zip(head['classes'], map(float, p)))


def predict(image_bytes, last_treatment=None, model=None):
    """Devuelve {'servicio','base','prob_tratamiento','prob_servicios','confianza'} o None si no hay modelo o foto legible."""
    model = model or load_model()
    if not model:
        return None
    x = extract_features(image_bytes)
    if x is None:
        return None
    return decide(x, model, last_treatment)


def decide(x, model, last_treatment=None):
    p_bin = _softmax_head(x, model['binario'])
    p_three = _softmax_head(x, model['tres_servicios'])
    p_treat = float(p_bin['tratamiento'])
    if p_treat < 0.5:
        service, base, conf = 'mantenimiento', 'foto', 1 - p_treat
    elif last_treatment == 'mas_4':
        service, base, conf = 'limpieza_total', 'foto+tiempo', p_treat
    elif last_treatment == 'menos_4':
        service, base, conf = 'recuperacion', 'foto+tiempo', p_treat
    else:
        service = 'limpieza_total' if p_three['limpieza_total'] >= p_three['recuperacion'] else 'recuperacion'
        base, conf = 'foto_sin_confirmar', p_treat
    return {'servicio': service, 'base': base, 'prob_tratamiento': round(p_treat, 4),
            'prob_servicios': {k: round(v, 4) for k, v in p_three.items()}, 'confianza': round(float(conf), 4)}
