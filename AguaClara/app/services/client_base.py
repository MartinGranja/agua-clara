"""Módulo B · base de clientes: lectura de CSV (exportado de la planilla) y base de demostración."""
import csv
import io
import re
from pathlib import Path
from app.services.route_parser import norm, ZONES
from app.services.route_geo import CFG, coords_from_link, normalize_phone
from app.services.route_rules import split_observations

DEMO = Path(__file__).resolve().parents[1] / 'data' / 'clientes_demo.csv'
ALIASES = {
    'name': ['nombre', 'cliente', 'clientes nombre', 'clientes'],
    'zone': ['zona', 'zona localidad', 'localidad'],
    'phone': ['telefono', 'tel', 'celular', 'whatsapp'],
    'link': ['link', 'maps', 'maps link', 'ubicacion', 'direccion o referencia'],
    'address': ['direccion', 'domicilio', 'calle'],
    'lat': ['lat', 'latitud'], 'lng': ['lng', 'lon', 'long', 'longitud'],
    'obs': ['observaciones', 'observaciones fijas', 'indicacion', 'indicacion fija', 'notas', 'nota'],
    'frequency': ['frecuencia'], 'day': ['dia habitual', 'dia'], 'vehicle': ['vehiculo asignado', 'vehiculo', 'equipo'],
    'minutes': ['minutos', 'minutos por visita', 'servicio min'],
    'alias': ['alias', 'apodo', 'apodos'],
}
ZONE_ALIAS = {norm(z): z for z in ZONES}
ZONE_ALIAS.update({'despenaderos': 'Despeñaderos', 'alta gracia': 'Alta Gracia'})


def slug(name):
    return norm(name).replace(' ', '-')[:60] or 'cliente'


def nearest_zone(lat, lng):
    from app.services.routing_engine import haversine_km
    return min(CFG['zonas'], key=lambda z: haversine_km((lat, lng), (CFG['zonas'][z]['lat'], CFG['zonas'][z]['lng'])))


def _num(value):
    try:
        return float(str(value).replace(',', '.').strip())
    except ValueError:
        return None


def read_csv(text):
    """Devuelve (clientes, avisos). Acepta coma, punto y coma o tabulador y nombres de columna flexibles."""
    text = text.lstrip('﻿')
    first = text.split('\n', 1)[0]
    delimiter = max(',;\t', key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return [], ['El archivo está vacío.']
    header = [norm(h) for h in rows[0]]
    col = {}
    for field, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in names and field not in col:
                col[field] = i
    if 'name' not in col:
        return [], ['No se encontró la columna con el nombre del cliente (Nombre o Cliente).']
    clients, warnings, seen, ids = [], [], set(), set()
    for line, r in enumerate(rows[1:], 2):
        get = lambda f: r[col[f]].strip() if f in col and col[f] < len(r) else ''
        name = get('name')
        if not name:
            continue
        raw_phone = get('phone')
        phone = normalize_phone(raw_phone)
        if raw_phone and not phone:
            warnings.append(f'Fila {line}: el teléfono de «{name}» no tiene 10 dígitos y se dejó vacío.')
        key = (norm(name), phone)
        if key in seen:
            warnings.append(f'Fila {line}: «{name}» está repetido con el mismo teléfono; se conservó la primera.')
            continue
        seen.add(key)
        link, lat, lng = get('link'), _num(get('lat')), _num(get('lng'))
        if lat is None or lng is None:
            c = coords_from_link(link)
            lat, lng = c if c else (None, None)
        zone = ZONE_ALIAS.get(norm(get('zone')))
        inferred = False
        if not zone and lat is not None:
            zone, inferred = nearest_zone(lat, lng), True
        if get('zone') and not ZONE_ALIAS.get(norm(get('zone'))) and not inferred:
            warnings.append(f'Fila {line}: la zona «{get("zone")}» no está en la cobertura.')
        minutes = _num(get('minutes'))
        address_obs, notes = split_observations(get('obs'))
        address = get('address') or (link if link and not link.startswith('http') else '') or address_obs
        client_id = slug(name)
        if client_id in ids:
            client_id = f'{client_id}-{phone[-4:] or line}'
        ids.add(client_id)
        aliases = [a.strip() for a in re.split(r'[;|,]', get('alias')) if a.strip()]
        clients.append({'id': client_id, 'name': name, 'alias': aliases, 'zone': zone, 'zoneInferred': inferred, 'phone': phone, 'link': link if link.startswith('http') else '',
                        'address': address, 'lat': lat, 'lng': lng, 'obs': get('obs'), 'notes': notes, 'frequency': get('frequency'),
                        'day': get('day'), 'vehicle': get('vehicle'), 'minutes': int(minutes) if minutes else None})
    return clients, warnings


def summary(clients):
    return {'total': len(clients), 'conCoordenadas': sum(c['lat'] is not None for c in clients), 'sinCoordenadas': sum(c['lat'] is None for c in clients),
            'sinTelefono': sum(not c['phone'] for c in clients), 'zonaInferida': sum(bool(c.get('zoneInferred')) for c in clients),
            'porZona': {z: sum(c['zone'] == z for c in clients) for z in ZONES}}


def demo():
    return read_csv(DEMO.read_text(encoding='utf-8'))[0]
