"""Módulo B · reglas de Agua Clara para productos, dosis y texto del mensaje (ver docs/MODULO_B_RECORRIDOS.md)."""
import re

DIVISORS = {'quincenal': 2, 'semanal': 4}   # // → quincenal que toca; sin prefijo + "N limp" → semanal
FRACTIONS = {0.25: '¼', 0.5: '½', 0.75: '¾'}


def _num(value):
    text = f'{value:.2f}'.rstrip('0').rstrip('.')
    return text.replace('.', ',')


def kg(value):
    """1 → '1 kg', 0.5 → '½ kg', 1.5 → '1 ½ kg', 0.3 → '0,3 kg'."""
    whole = int(value)
    frac = round(value - whole, 4)
    if abs(frac) < 1e-9:
        return f'{whole} kg'
    sym = FRACTIONS.get(round(frac * 4) / 4) if abs(frac * 4 - round(frac * 4)) < 1e-6 else None
    if sym:
        return f'{whole} {sym} kg' if whole else f'{sym} kg'
    return f'{_num(value)} kg'


def tablets(count):
    if abs(count - round(count)) < 1e-9:
        count = int(round(count))
        return f'{count} pastilla' + ('' if count == 1 else 's')
    return f'{_num(count)} pastillas'


def treatment(kind, limp, chlorine, pills):
    """Texto de productos: 'Dejar …, Colocar …' o 'Colocar …' (vacío si no corresponde).

    - Sólo hay productos con prefijo // (÷2) o semanal (÷4); con '.' o sin 'N limp' no se calculan.
    - Cantidad negativa = el cliente debe ese producto: no se deja ni se coloca.
    - 0 limp = primera limpieza del mes: se deja el total del mes y además se coloca la dosis del día.
    """
    divisor = DIVISORS.get(kind)
    if not divisor:
        return ''
    leave, place = [], []
    if chlorine is not None and chlorine > 0:
        leave.append(kg(chlorine) + ' cloro')
        place.append(kg(chlorine / divisor) + ' cloro')
    if pills is not None and pills > 0:
        leave.append(kg(pills) + ' pastillas')
        place.append(tablets(pills * 4 / divisor))
    parts = []
    if limp == 0 and leave:
        parts.append('Dejar ' + ' + '.join(leave))
    if place:
        parts.append('Colocar ' + ' + '.join(place))
    return ', '.join(parts)


def capitalize(text):
    text = text.strip()
    return text[:1].upper() + text[1:]


ADDRESS = re.compile(r'^[^\d]{3,40}\s\d{1,5}(?:\s*(?:bis|esq\.?.*|y\s+\w.*))?$', re.I)
NOTE_HINT = re.compile(r'\b(colocar|dejar|llevar|llamar|avisar|cobrar|pedir|abrir|port[oó]n|perro|kg|pastillas?|cloro|enrollador|manguera|reja|llave)\b', re.I)


def split_observations(text):
    """Separa la dirección (si se reconoce) de las notas fijas del cliente."""
    address, notes = '', []
    for piece in re.split(r'[;\n]|\s[-–—]\s', text or ''):
        piece = piece.strip(' .')
        if not piece:
            continue
        if not address and ADDRESS.match(piece) and not NOTE_HINT.search(piece):
            address = piece
        else:
            notes.append(piece)
    return address, notes
