"""Entrena y evalúa el clasificador propio (app/services/own_classifier.py) con fotos etiquetadas por carpetas:
  CARPETA/mantenimiento/*.jpg, CARPETA/recuperacion/*.jpg, CARPETA/limpieza_total/*.jpg   (el espacio en «limpieza total» también vale)

  python scripts/entrenar_clasificador.py CARPETA [--salida resultados_clasificador.json] [--guardar]

Necesita scikit-learn SOLO para entrenar (pip install scikit-learn); la app en producción no lo usa.
Evaluación: validación cruzada estratificada de 5 pliegues repetida 5 veces. El valor de C de la regresión logística se
elige DENTRO de cada pliegue de entrenamiento (validación cruzada anidada), así la métrica informada no usa las fotos de prueba
para ajustar nada. También se comparan SVM y bosque aleatorio. Con --guardar se entrena el modelo final con todas las fotos y se
escribe app/data/clasificador_propio.json. Importante: si hay varias fotos de una misma pileta, deben ir juntas en una sola
partición; este script asume que cada foto es de una pileta distinta (confirmado por el dueño para el banco de 2026).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import metrics as m, own_classifier as oc  # noqa: E402

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV, StratifiedKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
except ImportError:
    sys.exit('Falta scikit-learn para entrenar: pip install scikit-learn')

EXT = {'.jpg', '.jpeg', '.png', '.webp'}
GRID = {'logisticregression__C': [0.03, 0.1, 0.3, 1, 3]}


def slug(t):
    return t.strip().lower().replace(' ', '_').replace('ó', 'o')


def load(folder):
    X, y, names = [], [], []
    for sub in sorted(p for p in Path(folder).iterdir() if p.is_dir()):
        s = slug(sub.name)
        if s not in oc.SERVICES:
            print('Carpeta ignorada:', sub.name)
            continue
        for p in sorted(sub.iterdir()):
            if p.suffix.lower() not in EXT:
                continue
            f = oc.extract_features(p.read_bytes())
            if f is None:
                print('Foto omitida:', p.name)
                continue
            X.append(f); y.append(oc.SERVICES.index(s)); names.append(f'{sub.name}/{p.name}')
    return np.array(X), np.array(y), names


def logreg():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, class_weight='balanced'))


def tuned_logreg(seed):
    return GridSearchCV(logreg(), GRID, cv=StratifiedKFold(4, shuffle=True, random_state=seed), scoring='f1_macro')


def candidates(seed):
    return {'Regresión logística (C elegido por CV anidada)': tuned_logreg(seed),
            'SVM (núcleo RBF)': make_pipeline(StandardScaler(), SVC(C=3, class_weight='balanced')),
            'Bosque aleatorio': RandomForestClassifier(300, class_weight='balanced', random_state=0)}


def oof_predictions(X, y, make, repeats=5):
    """Predicciones fuera de muestra: lista de arreglos (uno por repetición)."""
    out = []
    for seed in range(repeats):
        pred = np.zeros_like(y)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            model = make(seed)
            model.fit(X[tr], y[tr])
            pred[te] = model.predict(X[te])
        out.append(pred)
    return out


def report(y, preds, labels):
    reps = [m.classification_report([(labels[a], labels[b]) for a, b in zip(y, p)], labels) for p in preds]
    avg = lambda k: float(np.mean([r[k] for r in reps]))
    cm = np.mean([np.array(r['confusion']) for r in reps], axis=0)
    return {'accuracy': avg('accuracy'), 'accuracy_sd': float(np.std([r['accuracy'] for r in reps])), 'macroF1': avg('macroF1'),
            'weightedF1': avg('weightedF1'), 'labels': reps[0]['labels'], 'confusion_promedio': cm.round(1).tolist(),
            'por_clase': {c: {k: float(np.mean([r['classes'][c][k] for r in reps])) for k in ('precision', 'recall', 'f1')} | {'support': reps[0]['classes'][c]['support']} for c in labels}}


def export_head(model, classes):
    scaler, clf = model.named_steps['standardscaler'], model.named_steps['logisticregression']
    return {'classes': classes, 'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
            'coef': clf.coef_.tolist(), 'intercept': clf.intercept_.tolist(), 'C': float(clf.C)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('carpeta')
    ap.add_argument('--salida')
    ap.add_argument('--guardar', action='store_true', help='entrenar el modelo final y guardarlo en app/data/')
    ap.add_argument('--repeticiones', type=int, default=5)
    args = ap.parse_args()
    X, y, names = load(args.carpeta)
    print(f'{len(y)} fotos · rasgos {X.shape[1]} · por servicio {dict(zip(oc.SERVICES, np.bincount(y).tolist()))}')
    yb = (y > 0).astype(int)
    results = {'n': int(len(y)), 'servicios': dict(zip(oc.SERVICES, np.bincount(y).tolist())), 'tres_servicios': {}, 'necesita_tratamiento': {}}
    for name, mk in ((n, (lambda s, n=n: candidates(s)[n])) for n in candidates(0)):
        r3 = report(y, oof_predictions(X, y, mk, args.repeticiones), oc.SERVICES)
        rb = report(yb, oof_predictions(X, yb, mk, args.repeticiones), ['mantenimiento', 'tratamiento'])
        results['tres_servicios'][name], results['necesita_tratamiento'][name] = r3, rb
        print(f"\n{name}\n  3 servicios: exactitud {r3['accuracy']:.3f} ± {r3['accuracy_sd']:.3f} · F1 macro {r3['macroF1']:.3f}"
              f"\n  mantenimiento vs tratamiento: exactitud {rb['accuracy']:.3f} ± {rb['accuracy_sd']:.3f} · F1 macro {rb['macroF1']:.3f}")
    main_name = next(iter(candidates(0)))
    # Cota con la pregunta de los 4 meses: el cliente responde bien, entonces la etapa 2 acierta entre recuperación y limpieza total.
    preds_b = oof_predictions(X, yb, lambda s: candidates(s)[main_name], args.repeticiones)
    preds_3 = oof_predictions(X, y, lambda s: candidates(s)[main_name], args.repeticiones)
    pq = []
    for pb, p3 in zip(preds_b, preds_3):
        q = np.where(pb == 0, 0, np.where(y > 0, y, p3))   # tratamiento predicho: con respuesta correcta se acierta el servicio real
        q = np.where((pb == 1) & (y == 0), np.where(p3 > 0, p3, 1), q)  # falso tratamiento sobre una pileta de mantenimiento: sigue mal
        pq.append(q)
    results['propio_mas_pregunta'] = report(y, pq, oc.SERVICES)
    r = results['propio_mas_pregunta']
    print(f"\nClasificador propio + pregunta (cota superior): exactitud {r['accuracy']:.3f} · F1 macro {r['macroF1']:.3f}")
    if args.salida:
        Path(args.salida).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Guardado en', args.salida)
    if args.guardar:
        bin_model = tuned_logreg(0).fit(X, yb).best_estimator_
        three_model = tuned_logreg(0).fit(X, y).best_estimator_
        model = {'version': 1, 'n_fotos': int(len(y)), 'rasgos': int(X.shape[1]),
                 'binario': export_head(bin_model, ['mantenimiento', 'tratamiento']),
                 'tres_servicios': export_head(three_model, oc.SERVICES),
                 'nota': 'Entrenado con scripts/entrenar_clasificador.py; reentrenar al sumar fotos.'}
        oc.MODEL_PATH.write_text(json.dumps(model), encoding='utf-8')
        print('Modelo guardado en', oc.MODEL_PATH)


if __name__ == '__main__':
    main()
