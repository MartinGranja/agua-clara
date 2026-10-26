"""Módulo B · arma el recorrido del día: lista → clientes → bloques zona/equipo → orden → horarios → mensaje."""
from datetime import date
from app.services import routing_engine as eng
from app.services.route_geo import CFG, coords_from_link
from app.services.route_parser import parse_day, match_client, norm, to_minutes, DAYS, DAY_LABEL, capitalize_note, ZONES
from app.services.route_rules import treatment, capitalize

WEEK = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
ENTREGA_MIN = 0  # una entrega suelta ("Dejar 1c a …") no suma tiempo (regla del usuario)


def hhmm(minutes):
    minutes = int(round(minutes))
    return f'{minutes // 60 % 24:02d}:{minutes % 60:02d}'


def team_label(label, base_vehicle=None):
    """Nombre canónico del equipo ('Clio azul'); None si la lista no lo indica."""
    names = CFG['equipos']
    for raw in (label, base_vehicle):
        n = norm(raw or '')
        if not n:
            continue
        for i, name in enumerate(names):
            if norm(name) == n or n in (f'equipo {i + 1}', f'auto {i + 1}', f'vehiculo {i + 1}'):
                return name
        return capitalize(n)
    return None


def locate(client, zone):
    """Coordenadas: link con coordenadas > columnas lat/lng > centro de la zona (aproximada)."""
    if client:
        c = coords_from_link(client.get('link'))
        if c:
            return c, 'exacta'
        if client.get('lat') is not None and client.get('lng') is not None:
            return (client['lat'], client['lng']), 'exacta'
    z = (client or {}).get('zone') or zone
    if z in CFG['zonas']:
        return (CFG['zonas'][z]['lat'], CFG['zonas'][z]['lng']), 'aproximada'
    return (CFG['base']['lat'], CFG['base']['lng']), 'sin_ubicacion'


def maps_link(client):
    if not client:
        return ''
    if client.get('link'):
        return client['link']
    if client.get('lat') is not None and client.get('lng') is not None:
        return f"https://maps.google.com/?q={client['lat']:.6f},{client['lng']:.6f}"
    return ''


def split_by_declared(group, sizes):
    """'ALTA GRACIA 11 y 11' sin equipos escritos: reparte por cercanía respetando los tamaños declarados."""
    pts = [s['coord'] for s in group]
    far = max(((eng.haversine_km(a, b), i, j) for i, a in enumerate(pts) for j, b in enumerate(pts) if i < j), default=(0, 0, 0))
    i, j = far[1], far[2]
    ax, ay = pts[i]
    bx, by = pts[j]
    dx, dy = bx - ax, by - ay
    norm2 = dx * dx + dy * dy or 1
    ordered = sorted(range(len(group)), key=lambda k: ((pts[k][0] - ax) * dx + (pts[k][1] - ay) * dy) / norm2)
    names = CFG['equipos']
    for rank, k in enumerate(ordered):
        group[k]['team'] = names[0] if rank < sizes[0] else names[1]


def build_stop(item, clients, rules_service):
    client = item['client']
    coord, quality = locate(client, item['zone'])
    name = client['name'] if client else item['name']
    if item.get('extra'):
        detail = [item['raw_text']]
        count = False
        service = ENTREGA_MIN
    else:
        kind = item['kind']
        auto = treatment(kind, item['limp'], item['chlorine'], item['pills']) if not item['override'] else ''
        detail = [x for x in [auto] if x]
        count, service = True, rules_service
    parens = []
    if not item.get('extra'):
        if detail:
            parens.append(detail[0])
        if item['override']:
            parens.append(item['override'])
        if item['free']:
            parens.append(capitalize_note(item['free']))
        parens += item['paren']
    return {'name': name, 'item': item, 'client': client, 'zone': item['zone'] or (client or {}).get('zone'), 'time': item['time'], 'service': service, 'coord': coord, 'quality': quality,
            'team': team_label(item['vehicle'], None), 'written': item['order'], 'parens': parens, 'count': count, 'raw_text': item.get('raw_text')}


def apply_cancellations(items, cancels, clients, warnings):
    kept = list(items)
    for text in cancels:
        status, client, _ = match_client(text, clients)
        removed = [i for i in kept if (client and i['client'] is client) or (not client and norm(i['name']) == norm(text))]
        if not removed:
            warnings.append(f'No se encontró en la lista a «{text}» para cancelarlo.')
            continue
        kept = [i for i in kept if i not in removed]
        warnings.append(f"Cancelado: {removed[0]['client']['name'] if removed[0]['client'] else removed[0]['name']}.")
    return kept


def plan(text, clients, start='08:30', service=None, plan_date=None, travel=False, teams=2):
    start_min = to_minutes(start)
    service = service or CFG['servicio_min']
    tol = CFG['tolerancia_hora_min']
    parsed = parse_day(text, clients)
    warnings, pending = [], []
    items = apply_cancellations(parsed['items'], parsed['cancels'], clients, warnings)
    skipped = [i for i in items if i['kind'] == 'no_toca']
    items = [i for i in items if i['kind'] != 'no_toca']
    # Indicaciones "correr las siguientes N piletas": se aplican a las N siguientes anotadas después de esa línea.
    shift_for = {}
    for sh in parsed['shifts']:
        following = [i for i in parsed['items'] if i['order'] >= sh['after'] and i['kind'] != 'no_toca' and not i.get('extra')][:sh['count']]
        for i in following:
            shift_for[i['order']] = shift_for.get(i['order'], 0) + sh['minutes']
    stops = []
    for item in items:
        if not item['name'].strip() and not item.get('extra'):
            pending.append({'texto': item['raw'].strip(), 'motivo': 'No se pudo leer el nombre del cliente', 'opciones': [], 'zona': item['zone']})
            continue
        if item['kind'] != 'quincenal' and item['kind'] != 'semanal' and (item['chlorine'] or item['pills']) and not item.get('extra'):
            warnings.append(f"{item['client']['name'] if item['client'] else item['name']}: tiene productos anotados pero por su prefijo no se calculan (solo // o semanal con «N limp»).")
        stop = build_stop(item, clients, service)
        if item['status'] != 'ok':
            reason = 'Hay más de un cliente posible' if item['status'] == 'ambiguo' else 'No está en la base de clientes'
            pending.append({'texto': item['raw'].strip(), 'motivo': reason, 'opciones': item['candidates'], 'zona': item['zone']})
        stops.append(stop)
    seen = {}
    for s in stops:
        if s['count']:
            seen[s['name']] = seen.get(s['name'], 0) + 1
    warnings += [f'{n} aparece {c} veces en la lista.' for n, c in seen.items() if c > 1]
    approx = sorted({s['name'] for s in stops if s['quality'] == 'aproximada' and s['count']})
    if approx:
        warnings.append('Sin coordenadas exactas (se usó el centro de la zona): ' + ', '.join(approx) + '.')
    approx_assumed = []
    # Equipo de cada parada: el encabezado de la lista manda; si no hay, el vehículo de la base; si no, se reparte según los números declarados.
    for s in stops:
        if s['team'] is None and s['client'] and s['client'].get('vehicle'):
            s['team'] = team_label(s['client']['vehicle'])
    # Paradas sin zona (ni en la lista ni en la base): se suman a la única zona conocida de su equipo (o de toda la lista).
    for s in stops:
        if s['zone']:
            continue
        zones = {x['zone'] for x in stops if x['zone'] and x['team'] == s['team']} or {x['zone'] for x in stops if x['zone']}
        if len(zones) == 1:
            s['zone'] = next(iter(zones))
            if s['quality'] == 'sin_ubicacion' and s['zone'] in CFG['zonas']:
                s['coord'], s['quality'] = (CFG['zonas'][s['zone']]['lat'], CFG['zonas'][s['zone']]['lng']), 'aproximada'
                approx_assumed.append(s['name'])
    if approx_assumed:
        warnings.append('Sin zona en la base (se asumió la de las demás paradas del equipo): ' + ', '.join(sorted(set(approx_assumed))) + '.')
    declared = parsed['declared']
    for zone in {s['zone'] for s in stops}:
        group = [s for s in stops if s['zone'] == zone and s['team'] is None and s['count']]
        sizes = declared.get(zone, [])
        if len(group) > 1 and len(sizes) == 2 and teams == 2 and sum(sizes) == len(group):
            split_by_declared(group, sizes)
    # Bloques (zona, equipo) en el orden escrito.
    blocks = {}
    for s in stops:
        blocks.setdefault((s['zone'], s['team']), []).append(s)
    if not parsed['cancels']:
        for zone, sizes in declared.items():
            have = [len([s for s in v if s['count']]) for (z, _), v in blocks.items() if z == zone]
            if sizes and have and sorted(sizes) != sorted(have) and len(sizes) == len(have):
                warnings.append(f"{zone.upper()}: se anotaron {' y '.join(map(str, sizes))} piletas y en la lista hay {' y '.join(map(str, have))}.")
    label_date = plan_date or date.today()
    day_word = parsed['day'] or WEEK[label_date.weekday()]
    day_title = DAY_LABEL.get(day_word, day_word.upper())
    depot = (CFG['base']['lat'], CFG['base']['lng'])
    cursor, origin = {}, {}
    result = {'equipos': [], 'pendientes': pending, 'dia': day_title.capitalize(), 'fecha': label_date.isoformat(), 'salida': start, 'base': CFG['base']['nombre']}
    totals = {'km': 0.0, 'kmManual': 0.0}
    skip_note = [i['client']['name'] if i['client'] else i['name'] for i in skipped]
    for (zone, team), group in blocks.items():
        t0 = cursor.get(team, start_min)
        matrix = eng.Matrix(origin.get(team, depot), [s['coord'] for s in group], CFG['factor_ruta'], CFG['velocidad_kmh'], clock_travel=travel)
        order, method = eng.solve(group, matrix, t0)
        opt = eng.evaluate(order, group, matrix, t0, tol)
        manual = eng.evaluate(sorted(range(len(group)), key=lambda i: group[i]['written']), group, matrix, t0, tol)
        cursor[team] = opt['end']
        origin[team] = group[order[-1]]['coord']
        rows = []
        for pos, row in enumerate(opt['rows'], 1):
            s = group[row['index']]
            shift = shift_for.get(s['written'], 0)
            c = s['client'] or {}
            rows.append({'orden': pos, 'cliente': s['name'], 'zona': s['zone'], 'llegada': hhmm(row['arrive'] - shift), 'horaPedida': hhmm(s['time']) if s['time'] is not None else None, 'retraso': row['late'],
                         'detalle': s['parens'], 'texto': s['raw_text'], 'telefono': c.get('phone') or '', 'direccion': c.get('address') or '', 'notasFijas': c.get('notes') or [], 'mapa': maps_link(s['client']),
                         'ubicacion': s['quality'], 'cuenta': s['count'], 'enBase': bool(s['client']), 'corrida': shift})
            if row['late']:
                warnings.append(f"{s['name']}: no se llega a las {hhmm(s['time'])} (llegaría a las {hhmm(row['arrive'])}).")
        pools = sum(1 for r in rows if r['cuenta'])
        block = {'nombre': f"{zone.upper()} – {team.upper()}" if zone and team else (zone or team or 'SIN ZONA').upper(), 'zona': zone, 'equipo': team, 'metodo': method, 'paradas': rows, 'piletas': pools,
                 'km': round(opt['km'], 1), 'minutos': round(opt['end'] - t0), 'fin': hhmm(opt['end']), 'kmManual': round(manual['km'], 1)}
        block['mensaje'] = message(block, day_title)
        result['equipos'].append(block)
        totals['km'] += opt['km']
        totals['kmManual'] += manual['km']
    saved = totals['kmManual'] - totals['km']
    result['resumen'] = {'paradas': sum(b['piletas'] for b in result['equipos']), 'bloques': len(result['equipos']), 'pendientes': len(pending), 'noTocan': len(skipped), 'km': round(totals['km'], 1), 'kmManual': round(totals['kmManual'], 1),
                         'ahorroKm': round(saved, 1), 'ahorroPct': round(100 * saved / totals['kmManual'], 1) if totals['kmManual'] > 0.05 else 0.0}
    if skip_note:
        warnings.append('No les toca esta semana (prefijo /): ' + ', '.join(skip_note) + '.')
    mode = 'sumando el traslado estimado' if travel else 'sin sumar traslado'
    result['supuestos'] = f"{service} min por pileta, {mode}, salida a las {start}. Las distancias son línea recta × {CFG['factor_ruta']} (no usan calles ni tráfico reales); sirven para ordenar y comparar, no son una promesa de horario."
    result['avisos'] = warnings
    result['mensajePendientes'] = pending_message(pending)
    return result


def message(block, day_title):
    lines = [day_title, f"{block['nombre']} ({block['piletas']})", '']
    for p in block['paradas']:
        title = p['texto'] if p['texto'] else p['cliente'] + (' (' + ') ('.join(p['detalle']) + ')' if p['detalle'] else '')
        if p['texto'] is None and p['detalle']:
            title = f"{p['cliente']} ({p['detalle'][0]})" + ''.join(f' ({d})' for d in p['detalle'][1:])
        lines.append(f"{p['llegada']} {title}")
        lines.append(f"📞 {p['telefono'] or 'FALTA'}")
        if p['direccion']:
            lines.append(f"🏠 {p['direccion']}")
        if p['notasFijas']:
            lines.append('📝 ' + '; '.join(p['notasFijas']))
        lines.append(f"📍 {p['mapa'] or 'FALTA'}")
        lines.append('')
    return '\n'.join(lines).strip()


def pending_message(pending):
    if not pending:
        return ''
    return 'A confirmar antes de salir (figuran con FALTA):\n' + '\n'.join(f"- {p['texto']} → {p['motivo']}" + (f" ({', '.join(p['opciones'])})" if p['opciones'] else '') for p in pending)


def suggest(clients, weekday_word):
    """Lista sugerida del día según el 'día habitual' de la base, en el formato de entrada."""
    w = norm(weekday_word)
    rows = [c for c in clients if norm(c.get('day')) == w]
    out = [DAY_LABEL.get(w, w.upper())] if rows else []
    for zone in ZONES:
        zone_rows = [c for c in rows if c.get('zone') == zone]
        for vehicle in dict.fromkeys(c.get('vehicle') or '' for c in zone_rows):
            members = [c for c in zone_rows if (c.get('vehicle') or '') == vehicle]
            out.append(zone.upper())
            if vehicle:
                out.append(vehicle.upper() + ':')
            out += [c['name'] for c in members]
    return '\n'.join(out)
