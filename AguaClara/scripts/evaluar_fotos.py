"""Mide qué tan bien decide el servicio (y lee el agua) el sistema, con fotos que el dueño etiquetó.

Dos formas de etiquetar:
  A) Por carpetas (la más simple):  CARPETA/mantenimiento/*.jpg, CARPETA/recuperacion/*.jpg, CARPETA/limpieza_total/*.jpg
       python scripts/evaluar_fotos.py CARPETA [--solo-cv] [--salida resultados.json]
  B) Con planilla CSV (encabezado): archivo, servicio, estado_agua, algas, forma  (solo `archivo` y una de
     `servicio` / `estado_agua` son obligatorias; estado_agua: cristalina | levemente_turbia | turbia |
     verde_leve | verde_intenso | verde_oscuro_opaco; algas: si/no)
       python scripts/evaluar_fotos.py CARPETA etiquetas.csv [--solo-cv] [--salida resultados.json]

Compara tres métodos sobre las mismas fotos: visión por color sola (baseline), una lectura de Gemini y la lectura
combinada del sistema (varias lecturas + visión por color). Con --solo-cv no se usa Gemini ni internet.
Imprime accuracy, F1 por clase, F1 macro, matriz de confusión y tiempos; --salida guarda todo en JSON.
El servicio se deduce con la misma regla que el presupuesto: agua verde = recuperación; turbia o con algas =
limpieza total; el resto = mantenimiento.
"""
import argparse
import csv
import json
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings  # noqa: E402
from app.services import cv_baseline, metrics as m, perception, vision_service  # noqa: E402
from app.services.analytics_service import service_of  # noqa: E402
from app.services.cv_baseline import SEVERITY, STATES  # noqa: E402

SERVICES = ['mantenimiento', 'limpieza_total', 'recuperacion']
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
MIME = {'.png': 'image/png', '.webp': 'image/webp'}


def load_photo(path):
    """Lee la foto por su contenido real (no por la extensión), la endereza y la reduce a JPEG."""
    from io import BytesIO
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        im.thumbnail((2048, 2048))
        buf = BytesIO()
        im.save(buf, format='JPEG', quality=90)
        return buf.getvalue()


def slug(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')
    return text.strip().replace(' ', '_').replace('-', '_')


def yes(value):
    return slug(value or '') in ('si', '1', 'true', 'x')


def read_folders(folder):
    rows = []
    for sub in sorted(p for p in Path(folder).iterdir() if p.is_dir()):
        service = slug(sub.name)
        if service not in SERVICES:
            print('Carpeta ignorada (nombre no reconocido):', sub.name)
            continue
        rows += [{'archivo': str(p.relative_to(folder)), 'servicio': service} for p in sorted(sub.iterdir()) if p.suffix.lower() in IMAGE_EXT]
    return rows


def read_labels(path):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        r = {k.strip().lower(): (v or '').strip() for k, v in r.items()}
        r['servicio'] = slug(r.get('servicio', ''))
        if r['servicio'] and r['servicio'] not in SERVICES:
            print('Fila ignorada (servicio inválido):', r.get('archivo'))
            continue
        if r.get('estado_agua') and r['estado_agua'] not in SEVERITY:
            print('Fila ignorada (estado_agua inválido):', r.get('archivo'))
            continue
        if not r['servicio'] and r.get('estado_agua'):
            r['servicio'] = service_of(r['estado_agua'], yes(r.get('algas')))
        if not r['servicio']:
            print('Fila ignorada (sin servicio ni estado_agua):', r.get('archivo'))
            continue
        out.append(r)
    return out


def show(name, pairs, labels):
    rep = m.classification_report(pairs, labels)
    print(f"\n== {name} ==  n={rep['n']}")
    if not rep['n']:
        print('sin datos')
        return rep
    print(f"accuracy {rep['accuracy']:.3f} · F1 macro {rep['macroF1']:.3f} · F1 ponderado {rep['weightedF1']:.3f}")
    for k, c in rep['classes'].items():
        print(f"  {k:20s} P={c['precision']:.2f} R={c['recall']:.2f} F1={c['f1']:.2f} n={c['support']}")
    print('  matriz de confusión (filas = real, columnas = predicho):', rep['labels'])
    for label, row in zip(rep['labels'], rep['confusion']):
        print(f'  {label:20s}', row)
    return rep


def read_progress(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('carpeta')
    ap.add_argument('etiquetas', nargs='?', help='CSV de etiquetas (si se omite, se usan las subcarpetas)')
    ap.add_argument('--solo-cv', action='store_true', help='no llamar a Gemini (solo visión por color)')
    ap.add_argument('--salida', help='archivo JSON donde guardar los resultados')
    ap.add_argument('--propio', help='JSON de scripts/entrenar_clasificador.py (--salida): suma el clasificador propio a la comparación')
    ap.add_argument('--progreso', default='evaluacion_progreso.json', help='archivo donde se guarda lo ya analizado para poder continuar otro día')
    ap.add_argument('--pausa', type=float, default=4.0, help='segundos de espera entre fotos para no pasar el límite por minuto (por defecto 4)')
    args = ap.parse_args()
    labels = read_labels(args.etiquetas) if args.etiquetas else read_folders(args.carpeta)
    if not labels:
        sys.exit('No se encontraron fotos etiquetadas.')
    settings = Settings()
    use_llm = not args.solo_cv
    if use_llm and not settings.gemini_api_key:
        sys.exit('Falta GEMINI_API_KEY en el entorno o en .env. Usá --solo-cv para evaluar solo la visión por color.')
    ORACLE = 'sistema + pregunta (si el cliente responde bien)'
    methods = ['visión por color', 'Gemini (1 lectura)', 'sistema combinado', ORACLE]
    progress = read_progress(args.progreso) if use_llm else {}
    if progress:
        print(f'Se retoma lo ya analizado: {len(progress)} fotos en {args.progreso}.')
    skipped, pending, quota_hit = [], [], False
    for row in labels:
        name = row['archivo']
        path = Path(args.carpeta) / name
        if not path.exists():
            print('No existe:', path)
            continue
        if use_llm and name in progress:
            continue
        if quota_hit:
            pending.append(name)
            continue
        try:
            image = vision_service.prepare_image(load_photo(path), 'image/jpeg')
        except Exception as exc:  # foto dañada, formato no soportado (p. ej. HEIC) u otro problema
            print('Foto omitida:', name, '-', exc)
            skipped.append(name)
            continue
        cv = cv_baseline.predict(image)
        rec = {'cv': cv['estado_agua'] if cv['es_pileta'] else None}
        if use_llm:
            first = []

            def analyze_first(img, cfg, variant=0):
                result = vision_service.analyze(img, cfg, variant)
                if variant == 0:
                    first.append(result)   # la primera lectura es la «lectura única» de Gemini: no se paga otra llamada
                return result
            started = time.perf_counter()
            try:
                fused, meta = perception.perceive(image, settings, analyze_first)
            except vision_service.VisionUnavailable as exc:
                print('Falló', name, '-', exc)
                if 'cuota diaria' in str(exc):
                    quota_hit = True
                pending.append(name)
                continue
            rec['tiempo'] = time.perf_counter() - started
            one = first[0] if first else None
            rec['gemini'] = {'es_pileta': one.es_pileta, 'agua': one.estado_agua, 'algas': one.presencia_algas_paredes} if one else None
            rec['combinado'] = {'es_pileta': fused.es_pileta, 'agua': fused.estado_agua, 'algas': fused.presencia_algas_paredes,
                                'confianza': fused.confianza, 'acuerdo': meta['acuerdoModelo'], 'lecturas': meta['muestras']}
            progress[name] = rec
            Path(args.progreso).write_text(json.dumps(progress, ensure_ascii=False, indent=1), encoding='utf-8')
            if args.pausa > 0:
                time.sleep(args.pausa)
        else:
            progress[name] = rec
    service_pairs = {k: [] for k in methods}
    water_pairs = {k: [] for k in methods}
    algae_pairs, times, details = [], [], []
    for row in labels:
        rec = progress.get(row['archivo'])
        if rec is None:
            continue
        truth = row['servicio']
        cv_water = rec['cv']
        service_pairs['visión por color'].append((truth, service_of(cv_water, False) if cv_water else None))
        entry = {'archivo': row['archivo'], 'servicio_real': truth, 'cv': cv_water}
        if row.get('estado_agua'):
            water_pairs['visión por color'].append((row['estado_agua'], cv_water))
        if use_llm and rec.get('combinado'):
            fused, one = rec['combinado'], rec.get('gemini')
            # Con agua verde el chat pregunta hace cuánto no se limpia (más de 4 meses = limpieza total). Cota superior:
            # se supone que el cliente responde bien, así que entre recuperación y limpieza total acierta.
            photo_service = service_of(fused['agua'], fused['algas']) if fused['es_pileta'] else None
            asked = fused['es_pileta'] and fused['agua'].startswith('verde_') and truth in ('recuperacion', 'limpieza_total')
            service_pairs[ORACLE].append((truth, truth if asked else photo_service))
            for method, a in (('Gemini (1 lectura)', one), ('sistema combinado', fused)):
                if not a:
                    continue
                service_pairs[method].append((truth, service_of(a['agua'], a['algas']) if a['es_pileta'] else None))
                if row.get('estado_agua'):
                    water_pairs[method].append((row['estado_agua'], a['agua'] if a['es_pileta'] else None))
            entry.update(gemini=one['agua'] if one else None, combinado=fused['agua'], algas=fused['algas'], confianza=fused['confianza'], acuerdo=fused['acuerdo'])
            if row.get('algas'):
                algae_pairs.append((yes(row['algas']), fused['algas']))
            times.append(rec['tiempo'])
        details.append(entry)
    results = {'servicio': {}, 'estado_agua': {}, 'omitidas': skipped, 'pendientes': pending}
    if skipped:
        print(f'\nSe omitieron {len(skipped)} fotos que no se pudieron leer (ver mensajes arriba).')
    for name in methods:
        if name != 'visión por color' and not use_llm:
            continue
        results['servicio'][name] = show('SERVICIO · ' + name, service_pairs[name], SERVICES)
        if water_pairs[name]:
            results['estado_agua'][name] = show('ESTADO DEL AGUA · ' + name, water_pairs[name], STATES)
    # Primera etapa: ¿la pileta necesita tratamiento (recuperación o limpieza total) o solo mantenimiento?
    two = lambda v: None if v is None else ('mantenimiento' if v == 'mantenimiento' else 'tratamiento')
    results['necesita_tratamiento'] = {}
    for name in methods[:3]:
        if name != 'visión por color' and not use_llm:
            continue
        pairs = [(two(a), two(b)) for a, b in service_pairs[name]]
        results['necesita_tratamiento'][name] = show('¿NECESITA TRATAMIENTO? (mantenimiento vs recuperación/limpieza total) · ' + name, pairs, ['mantenimiento', 'tratamiento'])
    if args.propio:   # métricas fuera de muestra del clasificador propio, calculadas sobre las mismas fotos con entrenar_clasificador.py
        own = json.loads(Path(args.propio).read_text(encoding='utf-8'))
        main_name = next(iter(own['tres_servicios']))
        results['servicio']['clasificador propio (validación cruzada)'] = own['tres_servicios'][main_name]
        results['servicio']['clasificador propio + pregunta (cota superior)'] = own['propio_mas_pregunta']
        results['necesita_tratamiento']['clasificador propio (validación cruzada)'] = own['necesita_tratamiento'][main_name]
        for k in ('clasificador propio (validación cruzada)', 'clasificador propio + pregunta (cota superior)'):
            r = results['servicio'][k]
            print(f"\n== SERVICIO · {k} ==  exactitud {r['accuracy']:.3f} · F1 macro {r['macroF1']:.3f}")
    if algae_pairs:
        b = m.binary_report(algae_pairs)
        results['algas'] = b
        print(f"\n== Algas en paredes ==  n={b['n']}  accuracy {b['accuracy']:.3f} · precisión {b['precision']:.3f} · sensibilidad {b['recall']:.3f} · F1 {b['f1']:.3f}")
    if times:
        print(f"\nTiempo de inferencia por foto (sistema combinado, con sus lecturas de Gemini): media {sum(times) / len(times):.1f} s, máx. {max(times):.1f} s")
        results['tiempos'] = m.describe(times)
    if len(details) < 30:
        print(f"\nAviso: {len(details)} fotos evaluadas; para métricas confiables conviene tener 30 o más, con varias por servicio.")
    if pending:
        print(f"\nFaltan {len(pending)} fotos por analizar{' (se agotó la cuota diaria de Gemini)' if quota_hit else ''}. Volvé a correr el MISMO comando más tarde o mañana: continúa desde donde quedó, usando {args.progreso}.")
    if args.salida:
        Path(args.salida).write_text(json.dumps({'detalle': details, 'resultados': results}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Guardado en', args.salida)


if __name__ == '__main__':
    main()
