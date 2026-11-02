"""Métricas de evaluación en Python puro (sin numpy), compartidas por la app y por scripts/evaluar_fotos.py.

Todas devuelven números simples para poder volcarlos tal cual al informe: exactitud (accuracy),
precisión / sensibilidad / F1 por clase, F1 macro y ponderado, matriz de confusión y errores de regresión.
"""
from statistics import mean, median


def _div(a, b):
    return a / b if b else 0.0


def classification_report(pairs, labels=None):
    """`pairs` = [(real, predicho), ...]. Devuelve accuracy, F1 por clase, F1 macro/ponderado y matriz de confusión."""
    pairs = [(r, p) for r, p in pairs if r is not None and p is not None]
    if not pairs:
        return {'n': 0, 'accuracy': None, 'macroF1': None, 'weightedF1': None, 'classes': {}, 'labels': list(labels or []), 'confusion': []}
    seen = {x for pair in pairs for x in pair}
    base = list(dict.fromkeys(labels or []))
    labels = [l for l in base if l in seen] + sorted(seen - set(base))
    index = {l: i for i, l in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for real, pred in pairs:
        matrix[index[real]][index[pred]] += 1
    classes = {}
    for l in labels:
        i = index[l]
        tp = matrix[i][i]
        fp = sum(matrix[r][i] for r in range(len(labels))) - tp
        fn = sum(matrix[i]) - tp
        precision, recall = _div(tp, tp + fp), _div(tp, tp + fn)
        classes[l] = {'precision': round(precision, 4), 'recall': round(recall, 4), 'f1': round(_div(2 * precision * recall, precision + recall), 4), 'support': sum(matrix[i])}
    total = len(pairs)
    correct = sum(matrix[i][i] for i in range(len(labels)))
    supported = [c for c in classes.values() if c['support']]
    return {'n': total, 'accuracy': round(correct / total, 4),
            'macroF1': round(mean(c['f1'] for c in supported), 4) if supported else None,
            'weightedF1': round(sum(c['f1'] * c['support'] for c in supported) / total, 4),
            'classes': classes, 'labels': labels, 'confusion': matrix}


def binary_report(pairs):
    """Para variables sí/no (ej. algas). La clase positiva es True."""
    pairs = [(bool(r), bool(p)) for r, p in pairs if r is not None and p is not None]
    if not pairs:
        return {'n': 0, 'accuracy': None, 'precision': None, 'recall': None, 'f1': None, 'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0}
    tp = sum(1 for r, p in pairs if r and p)
    fp = sum(1 for r, p in pairs if not r and p)
    fn = sum(1 for r, p in pairs if r and not p)
    tn = len(pairs) - tp - fp - fn
    precision, recall = _div(tp, tp + fp), _div(tp, tp + fn)
    return {'n': len(pairs), 'accuracy': round((tp + tn) / len(pairs), 4), 'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1': round(_div(2 * precision * recall, precision + recall), 4), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn}


def ordinal_report(pairs, scale):
    """Error ordinal (cuántos escalones se equivoca) para estados ordenados como el del agua."""
    gaps = [abs(scale[r] - scale[p]) for r, p in pairs if r in scale and p in scale]
    if not gaps:
        return {'n': 0, 'withinOne': None, 'meanGap': None}
    return {'n': len(gaps), 'withinOne': round(sum(1 for g in gaps if g <= 1) / len(gaps), 4), 'meanGap': round(mean(gaps), 3)}


def regression_report(pairs):
    """`pairs` = [(real, estimado)]. MAE, MAPE, sesgo (estimado - real) y RMSE."""
    pairs = [(float(r), float(p)) for r, p in pairs if r is not None and p is not None]
    if not pairs:
        return {'n': 0, 'mae': None, 'mape': None, 'bias': None, 'rmse': None}
    errors = [p - r for r, p in pairs]
    pct = [abs(p - r) / abs(r) for r, p in pairs if r]
    return {'n': len(pairs), 'mae': round(mean(abs(e) for e in errors), 3), 'mape': round(100 * mean(pct), 2) if pct else None,
            'bias': round(mean(errors), 3), 'rmse': round(mean(e * e for e in errors) ** 0.5, 3)}


def describe(values):
    """Resumen descriptivo de una lista de números."""
    values = [float(v) for v in values if v is not None]
    if not values:
        return {'n': 0, 'mean': None, 'median': None, 'min': None, 'max': None}
    return {'n': len(values), 'mean': round(mean(values), 3), 'median': round(median(values), 3), 'min': round(min(values), 3), 'max': round(max(values), 3)}


def count_by(items):
    out = {}
    for x in items:
        if x is not None:
            out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
