"""Ajusta el detector de color (baseline) con fotos etiquetadas por el dueño y mide su exactitud.

Uso:
  python scripts/entrenar_baseline.py CARPETA etiquetas.csv [--guardar]

Compara las reglas manuales contra el modelo de centroides con validación cruzada dejando uno afuera (leave-one-out),
así la exactitud no se mide con las mismas fotos con las que se ajustó. Con --guardar escribe app/data/cv_modelo.json,
que el sistema usa automáticamente en lugar de las reglas manuales. Necesita al menos 2 estados con 2 fotos cada uno.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import cv_baseline, metrics as m, vision_service  # noqa: E402
from app.services.cv_baseline import STATES  # noqa: E402
from evaluar_fotos import read_labels as _read  # noqa: E402


def read_labels(path):
    return [r for r in _read(path) if r.get("estado_agua")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('carpeta')
    ap.add_argument('etiquetas')
    ap.add_argument('--guardar', action='store_true')
    args = ap.parse_args()
    samples = []
    for row in read_labels(args.etiquetas):
        path = Path(args.carpeta) / row['archivo']
        if not path.exists():
            print('No existe:', path)
            continue
        image = vision_service.prepare_image(path.read_bytes(), 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/png')
        features, _ = cv_baseline.extract_features(image)
        if features is None:
            print('No se detectó agua en', row['archivo'])
            continue
        samples.append((features, row['estado_agua'], row['archivo']))
    counts = {s: sum(1 for _, y, _ in samples if y == s) for s in STATES}
    usable = [s for s, n in counts.items() if n >= 2]
    if len(usable) < 2:
        sys.exit('Hacen falta al menos 2 estados con 2 fotos cada uno. Hay: ' + json.dumps({k: v for k, v in counts.items() if v}))
    samples = [s for s in samples if s[1] in usable]
    rules = [(y, cv_baseline._rules(f)[0]) for f, y, _ in samples]
    loo = []
    for i, (f, y, _) in enumerate(samples):
        train = [(g, z) for j, (g, z, _) in enumerate(samples) if j != i]
        if len({z for _, z in train}) < 2:
            continue
        model = cv_baseline.fit(train)
        loo.append((y, cv_baseline._centroid_predict(f, model)[0]))
    for name, pairs in (('reglas manuales', rules), ('centroides (leave-one-out)', loo)):
        rep = m.classification_report(pairs, STATES)
        print(f"{name}: n={rep['n']} accuracy {rep['accuracy']:.3f} · F1 macro {rep['macroF1']:.3f}")
    if args.guardar:
        model = cv_baseline.fit([(f, y) for f, y, _ in samples])
        cv_baseline.MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False), encoding='utf-8')
        print('Modelo guardado en', cv_baseline.MODEL_PATH)


if __name__ == '__main__':
    main()
