"""Mide qué tan bien lee el estado del agua el sistema, con fotos que el dueño etiquetó.

Uso:
  python scripts/evaluar_fotos.py CARPETA etiquetas.csv [--solo-cv] [--salida resultados.json]

etiquetas.csv (con encabezado): archivo, estado_agua, algas (si/no, opcional), forma (opcional)
  estado_agua: cristalina | levemente_turbia | turbia | verde_leve | verde_intenso | verde_oscuro_opaco

Compara tres métodos sobre las mismas fotos: visión por color sola (baseline), una lectura de Gemini y la lectura
combinada del sistema (varias lecturas + visión por color). Con --solo-cv no se usa Gemini ni internet.
Imprime accuracy, F1 por clase, F1 macro, matriz de confusión y error ordinal; --salida guarda todo en JSON.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings  # noqa: E402
from app.services import cv_baseline, metrics as m, perception, vision_service  # noqa: E402
from app.services.cv_baseline import SEVERITY, STATES  # noqa: E402


def read_labels(path):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        r = {k.strip().lower(): (v or '').strip() for k, v in r.items()}
        if r.get('estado_agua') not in SEVERITY:
            print('Fila ignorada (estado_agua inválido):', r.get('archivo'))
            continue
        out.append(r)
    return out


def show(name, pairs):
    rep = m.classification_report(pairs, STATES)
    o = m.ordinal_report(pairs, SEVERITY)
    print(f"\n== {name} ==  n={rep['n']}")
    if not rep['n']:
        print('sin datos')
        return rep, o
    print(f"accuracy {rep['accuracy']:.3f} · F1 macro {rep['macroF1']:.3f} · F1 ponderado {rep['weightedF1']:.3f} · acierto ±1 escalón {o['withinOne']:.3f} · error medio {o['meanGap']:.2f} escalones")
    for k, c in rep['classes'].items():
        print(f"  {k:20s} P={c['precision']:.2f} R={c['recall']:.2f} F1={c['f1']:.2f} n={c['support']}")
    print('  matriz de confusión (filas = real, columnas = predicho):', rep['labels'])
    for label, row in zip(rep['labels'], rep['confusion']):
        print(f'  {label:20s}', row)
    return rep, o


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('carpeta')
    ap.add_argument('etiquetas')
    ap.add_argument('--solo-cv', action='store_true', help='no llamar a Gemini (solo visión por color)')
    ap.add_argument('--salida', help='archivo JSON donde guardar los resultados')
    args = ap.parse_args()
    labels = read_labels(args.etiquetas)
    settings = Settings()
    use_llm = not args.solo_cv
    if use_llm and not settings.gemini_api_key:
        sys.exit('Falta GEMINI_API_KEY en el entorno o en .env. Usá --solo-cv para evaluar solo la visión por color.')
    pairs = {'visión por color': [], 'Gemini (1 lectura)': [], 'sistema combinado': []}
    algae_pairs, times, details = [], [], []
    for row in labels:
        path = Path(args.carpeta) / row['archivo']
        if not path.exists():
            print('No existe:', path)
            continue
        raw = path.read_bytes()
        image = vision_service.prepare_image(raw, 'image/' + ('png' if path.suffix.lower() == '.png' else 'webp' if path.suffix.lower() == '.webp' else 'jpeg'))
        truth = row['estado_agua']
        cv = cv_baseline.predict(image)
        pairs['visión por color'].append((truth, cv['estado_agua'] if cv['es_pileta'] else None))
        entry = {'archivo': row['archivo'], 'real': truth, 'cv': cv['estado_agua']}
        if use_llm:
            started = time.perf_counter()
            try:
                single = vision_service.analyze(image, settings)
                fused, meta = perception.perceive(image, settings, vision_service.analyze)
            except vision_service.VisionUnavailable as exc:
                print('Falló', row['archivo'], exc)
                continue
            times.append(time.perf_counter() - started)
            pairs['Gemini (1 lectura)'].append((truth, single.estado_agua if single.es_pileta else None))
            pairs['sistema combinado'].append((truth, fused.estado_agua if fused.es_pileta else None))
            entry.update(gemini=single.estado_agua, combinado=fused.estado_agua, confianza=fused.confianza, acuerdo=meta['acuerdoModelo'])
            if row.get('algas'):
                algae_pairs.append((row['algas'].lower() in ('si', 'sí', '1', 'true'), fused.presencia_algas_paredes))
        details.append(entry)
    results = {}
    for name, p in pairs.items():
        if name != 'visión por color' and not use_llm:
            continue
        results[name] = dict(zip(('reporte', 'ordinal'), show(name, p)))
    if algae_pairs:
        b = m.binary_report(algae_pairs)
        results['algas'] = b
        print(f"\n== Algas en paredes ==  n={b['n']}  accuracy {b['accuracy']:.3f} · precisión {b['precision']:.3f} · sensibilidad {b['recall']:.3f} · F1 {b['f1']:.3f}")
    if times:
        print(f"\nTiempo de inferencia (2 lecturas + 1 individual + visión por color): media {sum(times) / len(times):.1f} s, máx. {max(times):.1f} s")
        results['tiempos'] = m.describe(times)
    if len(labels) < 30:
        print(f"\nAviso: {len(labels)} fotos etiquetadas; para métricas confiables conviene tener 30 o más, con varias por estado.")
    if args.salida:
        Path(args.salida).write_text(json.dumps({'detalle': details, 'resultados': results}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Guardado en', args.salida)


if __name__ == '__main__':
    main()
