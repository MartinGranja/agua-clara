"""Visión clásica de referencia (baseline) para el estado del agua. Sin Gemini, sin red, solo numpy + Pillow.

Cumple tres funciones en el sistema:
1. Segunda opinión independiente: si no coincide con Gemini, baja la confianza y se sugiere revisión (perception.py).
2. Baseline de comparación para el informe (scripts/evaluar_fotos.py): ¿cuánto aporta la IA frente a reglas de color?
3. Modelo supervisado liviano: con fotos etiquetadas por el dueño, scripts/entrenar_baseline.py ajusta centroides por clase
   y guarda app/data/cv_modelo.json; si el archivo existe se usa en lugar de las reglas manuales.

Método: se achica la imagen, se pasa a HSV, se buscan bloques de 16×16 px lisos con tono de agua (verde-azulado a azul)
y se calculan 6 rasgos sobre esos bloques: saturación, brillo, proporción de tono verde, proporción de zonas oscuras,
energía de bordes (qué tan visible es el fondo) y tono medio. Las reglas manuales son un punto de partida
NO calibrado con fotos reales de Agua Clara: su exactitud se mide con las etiquetas del dueño.
"""
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

STATES = ['cristalina', 'levemente_turbia', 'turbia', 'verde_leve', 'verde_intenso', 'verde_oscuro_opaco']
SEVERITY = {s: i for i, s in enumerate(STATES)}          # escala ordinal usada también en la fusión
FEATURES = ['mean_s', 'mean_v', 'green_ratio', 'dark_ratio', 'edge', 'mean_h']
MODEL_PATH = Path(__file__).resolve().parents[1] / 'data' / 'cv_modelo.json'

BLOCK = 16
MAX_SIDE = 256
WATER_HUE = (95.0, 255.0)       # grados: del verde-amarillento (algas) al azul profundo
GREEN_HUE_MAX = 172.0           # por debajo de este tono se considera agua verde; por encima, azulada
MIN_SAT, MIN_VAL = 0.10, 0.12
SMOOTH_STD = 0.14               # un bloque con más textura que esto es follaje o reflejos, no agua
MIN_WATER_FRACTION = 0.06       # menos que esto de la imagen: no se ve una pileta


def _hsv(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn
    safe = np.where(d > 1e-6, d, 1.0)
    is_r = (mx == r) & (d > 1e-6)
    is_g = (mx == g) & ~is_r & (d > 1e-6)
    is_b = ~is_r & ~is_g & (d > 1e-6)
    h = np.where(is_r, ((g - b) / safe) % 6, np.where(is_g, (b - r) / safe + 2, np.where(is_b, (r - g) / safe + 4, 0.0))) * 60.0
    s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1.0), 0.0)
    return h, s, mx


def extract_features(image_bytes):
    """Devuelve (rasgos, agua_pct) o (None, 0.0) si no se ve agua."""
    with Image.open(io.BytesIO(image_bytes)) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        arr = np.asarray(im, dtype=np.float32) / 255.0
    height, width = (arr.shape[0] // BLOCK) * BLOCK, (arr.shape[1] // BLOCK) * BLOCK
    if height < BLOCK or width < BLOCK:
        return None, 0.0
    arr = arr[:height, :width]
    h, s, v = _hsv(arr)
    mask = (h >= WATER_HUE[0]) & (h <= WATER_HUE[1]) & (s >= MIN_SAT) & (v >= MIN_VAL)

    def blocks(x):
        return x.reshape(height // BLOCK, BLOCK, width // BLOCK, BLOCK).transpose(0, 2, 1, 3).reshape(height // BLOCK, width // BLOCK, -1)

    frac = blocks(mask.astype(np.float32)).mean(-1)
    texture = blocks(v).std(-1)
    water_blocks = (frac >= 0.70) & (texture < SMOOTH_STD)
    water_pct = float(water_blocks.mean())
    if water_pct < MIN_WATER_FRACTION:
        return None, water_pct
    pixel_mask = np.repeat(np.repeat(water_blocks, BLOCK, 0), BLOCK, 1) & mask
    if pixel_mask.sum() < 50:
        return None, water_pct
    gy, gx = np.gradient(v)
    edge = np.hypot(gx, gy)
    hue = h[pixel_mask]
    features = {
        'mean_s': float(s[pixel_mask].mean()), 'mean_v': float(v[pixel_mask].mean()),
        'green_ratio': float((hue < GREEN_HUE_MAX).mean()), 'dark_ratio': float((v[pixel_mask] < 0.28).mean()),
        'edge': float(edge[pixel_mask].mean()), 'mean_h': float(hue.mean()),
    }
    return features, water_pct


def _rules(f):
    """Reglas manuales. Devuelve (estado, confianza 0..1)."""
    if f['green_ratio'] >= 0.60:
        if f['mean_v'] < 0.30 or f['dark_ratio'] > 0.50:
            return 'verde_oscuro_opaco', 0.45 + min(0.35, abs(0.30 - f['mean_v']) * 2)
        if f['mean_s'] >= 0.45:
            return 'verde_intenso', 0.45 + min(0.35, abs(f['mean_s'] - 0.45) * 2)
        return 'verde_leve', 0.45 + min(0.35, abs(0.45 - f['mean_s']) * 2)
    if f['mean_s'] < 0.18:
        return 'turbia', 0.45 + min(0.35, (0.18 - f['mean_s']) * 3)
    if f['edge'] < 0.02 and f['mean_s'] < 0.35:
        return 'levemente_turbia', 0.45 + min(0.3, (0.02 - f['edge']) * 10)
    return 'cristalina', 0.5 + min(0.3, f['mean_s'] * 0.4)


def load_model(path=MODEL_PATH):
    try:
        model = json.loads(Path(path).read_text(encoding='utf-8'))
        return model if model.get('classes') and model.get('centroids') else None
    except (OSError, ValueError):
        return None


def _centroid_predict(f, model):
    x = (np.array([f[k] for k in FEATURES]) - np.array(model['mean'])) / np.array(model['std'])
    dist = np.linalg.norm(np.array(model['centroids']) - x, axis=1)
    order = np.argsort(dist)
    best, second = dist[order[0]], dist[order[1]] if len(dist) > 1 else dist[order[0]] + 1
    confidence = 0.4 + 0.5 * float(1 - best / (best + second + 1e-9))
    return model['classes'][int(order[0])], min(0.9, confidence)


def predict(image_bytes, model=None):
    """Clasifica el estado del agua de una imagen. Nunca lanza por una imagen rara: devuelve es_pileta=False."""
    try:
        features, water_pct = extract_features(image_bytes)
    except Exception:
        return {'es_pileta': False, 'estado_agua': 'desconocido', 'confianza': 0.0, 'aguaPct': 0.0, 'rasgos': None, 'metodo': 'reglas'}
    if features is None:
        return {'es_pileta': False, 'estado_agua': 'desconocido', 'confianza': 0.0, 'aguaPct': round(water_pct * 100, 1), 'rasgos': None, 'metodo': 'reglas'}
    model = model if model is not None else load_model()
    if model:
        state, confidence = _centroid_predict(features, model)
        method = 'centroides'
    else:
        state, confidence = _rules(features)
        method = 'reglas'
    return {'es_pileta': True, 'estado_agua': state, 'confianza': round(confidence, 3), 'aguaPct': round(water_pct * 100, 1),
            'rasgos': {k: round(v, 4) for k, v in features.items()}, 'metodo': method}


def fit(samples):
    """Ajusta el modelo de centroides. `samples` = [(rasgos_dict, estado), ...]. Devuelve el modelo (dict serializable)."""
    classes = sorted({s for _, s in samples}, key=lambda s: SEVERITY.get(s, 99))
    x = np.array([[f[k] for k in FEATURES] for f, _ in samples])
    mean, std = x.mean(0), x.std(0)
    std = np.where(std < 1e-6, 1.0, std)
    z = (x - mean) / std
    labels = np.array([s for _, s in samples])
    centroids = [z[labels == c].mean(0).tolist() for c in classes]
    return {'classes': classes, 'centroids': centroids, 'mean': mean.tolist(), 'std': std.tolist(), 'features': FEATURES, 'n': len(samples)}
