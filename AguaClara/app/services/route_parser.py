"""Módulo B · interpreta la lista diaria de Martín (reglas en docs/MODULO_B_RECORRIDOS.md) y la cruza con la base de clientes.

Entrada típica:
    VIERNES
    ALTA GRACIA 11 y 11
    CLIO AZUL:
    //Vale Maizon 0 limp 2c 1p 13:30
"""
import re
import unicodedata
from difflib import SequenceMatcher

ZONES = ['Alta Gracia', 'La Bolsa', 'Los Aromos', 'Despeñaderos']
DAYS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
DAY_LABEL = {'lunes': 'LUNES', 'martes': 'MARTES', 'miercoles': 'MIÉRCOLES', 'jueves': 'JUEVES', 'viernes': 'VIERNES', 'sabado': 'SÁBADO', 'domingo': 'DOMINGO'}
NOTE_WORDS = re.compile(r'\b(colocar|dejar|llevar|llamar|avisar|cobrar|pedir|abrir|portón|porton|perro|kg|pastilla|pastillas|cloro|enrollador|manguera|reja|llave|si no)\b|\d')
VERBS = {'dejar', 'colocar', 'llevar', 'cobrar', 'entregar', 'retirar', 'traer'}
STOP = VERBS | {'a', 'al', 'de', 'la', 'el', 'los', 'las', 'para', 'con', 'kg', 'cloro', 'pastilla', 'pastillas', 'y', 'en'}
URL = re.compile(r'https?://\S+')
PHONE = re.compile(r'(?<![\d.,])\d{10}(?![\d])')
TIME_AT_END = re.compile(r'(?<![\d:.,])((?:[01]?\d|2[0-3])[:.][0-5]\d|(?:[01]?\d|2[0-3])\s*hs?)\s*$', re.I)
TIME_AT_START = re.compile(r'^\s*((?:[01]?\d|2[0-3])[:.][0-5]\d|(?:[01]?\d|2[0-3])\s*hs?)\s+', re.I)
LEAD = re.compile(r'^\s*(?:\d{1,2}\s*[).]\s+|[-•*·]+\s*)')
PREFIX = re.compile(r'^\s*(//|/|\.)\s*')
LIMP = re.compile(r'^(-?\d+)\s*limp\w*$', re.I)
PRODUCT = re.compile(r'^(-?\d+(?:[.,]\d+)?)([cp])$', re.I)
OVERRIDE = re.compile(r'\b(esta vez|solo|sólo|no\s+(?:dejar|colocar)|sin\s+(?:dejar|colocar))\b.*$', re.I)
CANCEL = re.compile(r'^\s*(?:se\s+)?cancel\w*\s*:?\s*(.*)$', re.I)
SHIFT = re.compile(r'^\s*correr\b.*?(\d+)\s*piletas?\b(.*)$', re.I)


def norm(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]+', ' ', text)).strip()


ZONE_KEYS = {norm(z): z for z in ZONES}


def to_minutes(text):
    m = re.match(r'^(\d{1,2})(?:[:.](\d{2}))?', text.strip())
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


def vehicle_key(text):
    n = norm(text)
    m = re.match(r'^(clio\s+(?:gris|azul)|equipo\s*[12]|auto\s*[12]|vehiculo\s*[12])$', n)
    return m.group(1).replace('  ', ' ') if m else None


# ---------- encabezados ----------
def _header_kind(part):
    n = norm(part)
    m = re.match(r'^(.*?)((?:\s\d+)(?:\sy\s\d+)*)?$', n)
    base, nums = m.group(1), m.group(2)
    if base in ZONE_KEYS:
        return 'zone', (ZONE_KEYS[base], [int(x) for x in re.findall(r'\d+', nums or '')])
    if vehicle_key(n):
        return 'vehicle', vehicle_key(n)
    if n in DAYS:
        return 'day', n
    return None


def _strip_headers(line, state):
    """Reconoce 'ALTA GRACIA 11 y 11', 'CLIO AZUL:', 'VIERNES', 'Clio gris - La Bolsa: …'. Devuelve el resto de la línea."""
    head, sep, rest = line.partition(':')
    if not sep:
        head, rest = line, ''
    kinds = [_header_kind(p) for p in re.split(r'\s[-–—/]\s', head.strip())]
    if not head.strip() or not all(kinds):
        return line, False
    for kind, value in kinds:
        if kind == 'zone':
            state['zone'], state['declared'] = value
            state['vehicle'] = None
        else:
            state[kind] = value
    return rest.strip(), True


# ---------- nombres ----------
def _names(client):
    return [client['name']] + list(client.get('alias') or [])


def _prefix_match(query, candidate):
    q, c = _tokens(query), _tokens(candidate)
    return bool(q) and all(any(ct.startswith(qt) for ct in c) for qt in q if len(qt) >= 3) and any(len(t) >= 3 for t in q)


def _tokens(name):
    return [t for t in norm(name).split() if t]


def match_client(name, clients, zone=None, phone=None):
    """Devuelve (estado, cliente, candidatos). Estados: ok, ambiguo, sin_match. Tolera tildes, mayúsculas, partes del nombre y apodos."""
    key = norm(name)
    if not key:
        return 'sin_match', None, []
    exact = [c for c in clients if any(norm(n) == key for n in _names(c))]
    pool = exact or [c for c in clients if any(_prefix_match(name, n) for n in _names(c))]
    if not pool:
        scored = sorted(((max(SequenceMatcher(None, key, norm(n)).ratio() for n in _names(c)), c) for c in clients), key=lambda x: -x[0])
        if scored and scored[0][0] >= 0.84 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.05):
            return 'ok', scored[0][1], []
        near = [c for s, c in scored[:3] if s >= 0.7]
        return ('ambiguo', None, near) if near else ('sin_match', None, [])
    if len(pool) > 1 and phone:
        pool = [c for c in pool if c.get('phone') == phone] or pool
    if len(pool) > 1 and zone:
        pool = [c for c in pool if c.get('zone') == zone] or pool
    if len(pool) > 1:
        pool = [c for c in pool if any(norm(n) == key for n in _names(c))] or pool
    return ('ok', pool[0], []) if len(pool) == 1 else ('ambiguo', None, pool[:4])


def _find_inside(words, clients, zone):
    """Busca un cliente dentro de una frase suelta ('Dejar 1c a Franco Soriano')."""
    for i in range(len(words)):
        if norm(words[i]) in STOP:
            continue
        for j in range(len(words), i, -1):
            span = ' '.join(words[i:j])
            status, client, _ = match_client(span, clients, zone)
            if status == 'ok':
                return client
    return None


# ---------- líneas ----------
def _product_values(words):
    c = p = None
    used = 0
    for w in words:
        m = PRODUCT.match(w)
        if not m:
            break
        value = float(m.group(1).replace(',', '.'))
        if m.group(2).lower() == 'c':
            c = value
        else:
            p = value
        used += 1
    return c, p, used


def parse_client_line(line, clients, zone):
    prefix_match = PREFIX.match(line)
    prefix = prefix_match.group(1) if prefix_match else ''
    text = line[prefix_match.end():] if prefix_match else line
    link = (URL.findall(text) or [None])[0]
    text = URL.sub(' ', text)
    paren = [n.strip() for n in re.findall(r'\(([^)]*)\)', text) if n.strip()]
    text = re.sub(r'\([^)]*\)', ' ', text)
    time = None
    m = TIME_AT_START.match(text) or None
    if m:
        time, text = to_minutes(m.group(1)), text[m.end():]
    m = TIME_AT_END.search(text)
    if m:
        time, text = to_minutes(m.group(1)), text[:m.start()]
    override = None
    m = OVERRIDE.search(text)
    if m:
        override, text = capitalize_note(m.group(0)), text[:m.start()]
    phone_hint = (PHONE.findall(text) or [None])[0]
    text = PHONE.sub(' ', text)
    words = text.split()
    verb_line = bool(words) and norm(words[0]) in VERBS
    item = {'prefix': prefix, 'time': time, 'link': link, 'paren': paren, 'override': override, 'free': '', 'limp': None, 'chlorine': None, 'pills': None, 'extra': False, 'phone_hint': phone_hint}
    if verb_line:
        client = _find_inside(words, clients, zone)
        item.update(extra=True, name=' '.join(words), raw_text=capitalize_note(' '.join(words) + (' ' + ' '.join('(' + p + ')' for p in paren) if paren else '')), client=client, status='ok' if client else 'sin_match', candidates=[])
        item['paren'] = []
        return item
    first_struct = len(words)
    for i, w in enumerate(words):
        if PRODUCT.match(w) or (re.match(r'^-?\d+$', w) and i + 1 < len(words) and re.match(r'^limp', words[i + 1], re.I)) or LIMP.match(w):
            first_struct = i
            break
    chosen = None
    for k in range(first_struct, 0, -1):
        status, client, cands = match_client(' '.join(words[:k]), clients, zone, phone_hint)
        if status == 'ok':
            chosen = (k, status, client, cands)
            break
    if chosen is None:
        k = next((i for i, w in enumerate(words[:first_struct]) if i > 0 and NOTE_WORDS.search(w.lower())), first_struct) or first_struct
        k = max(k, 1) if words else 0
        status, client, cands = match_client(' '.join(words[:k]), clients, zone, phone_hint)
        chosen = (k, status, client, cands)
    k, status, client, cands = chosen
    rest = words[k:]
    if rest and LIMP.match(rest[0]):
        item['limp'] = int(LIMP.match(rest[0]).group(1))
        rest = rest[1:]
    elif len(rest) >= 2 and re.match(r'^-?\d+$', rest[0]) and re.match(r'^limp', rest[1], re.I):
        item['limp'] = int(rest[0])
        rest = rest[2:]
    c, p, used = _product_values(rest)
    item.update(chlorine=c, pills=p)
    rest = rest[used:]
    item.update(name=' '.join(words[:k]), free=' '.join(rest).strip(' ,;-'), client=client, status=status, candidates=[x['name'] for x in cands])
    return item


def capitalize_note(text):
    text = text.strip()
    return text[:1].upper() + text[1:]


def kind_of(item):
    """Frecuencia según el prefijo: // quincenal que toca, / no toca, . única, 'N limp' sin prefijo = semanal, resto mensual/eventual."""
    if item['prefix'] == '//':
        return 'quincenal'
    if item['prefix'] == '/':
        return 'no_toca'
    if item['prefix'] == '.':
        return 'unica'
    return 'semanal' if item['limp'] is not None else 'mensual'


def parse_day(text, clients):
    """Interpreta la lista completa. Devuelve items en el orden escrito más datos de contexto."""
    state = {'zone': None, 'vehicle': None, 'day': None, 'declared': []}
    items, cancels, shifts, declared = [], [], [], {}
    for raw in str(text or '').splitlines():
        line = LEAD.sub('', raw.strip())
        if not line:
            continue
        rest, was_header = _strip_headers(line, state)
        if was_header:
            if state['zone'] and state['declared']:
                declared[state['zone']] = state['declared']
            if not rest:
                continue
            line = rest
        m = CANCEL.match(line)
        if m and m.group(1):
            cancels.append(m.group(1).strip())
            continue
        m = SHIFT.match(line)
        if m:
            minutes = re.search(r'(\d+)\s*(?:min|minutos)', m.group(2))
            shifts.append({'after': len(items), 'count': int(m.group(1)), 'minutes': int(minutes.group(1)) if minutes else 30})
            continue
        pieces = [x.strip() for x in re.split(r',(?![^()]*\))', line)] if was_header else [line]
        for piece in filter(None, pieces):
            item = parse_client_line(piece, clients, state['zone'])
            if not re.search(r'\w', item['name']) and not item['link'] and not item.get('extra'):
                continue
            item.update(raw=piece, zone=state['zone'], vehicle=state['vehicle'], order=len(items))
            item['kind'] = kind_of(item)
            items.append(item)
    return {'items': items, 'day': state['day'], 'cancels': cancels, 'shifts': shifts, 'declared': declared}
