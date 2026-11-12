"""Módulo B · configuración y lectura de ubicaciones."""
import re
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
import yaml

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / 'data' / 'ruteo.yaml').read_text(encoding='utf-8'))
COORD = [re.compile(r'[?&](?:q|ll|query)=(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)'), re.compile(r'@(-?\d+\.\d+),(-?\d+\.\d+)'), re.compile(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)')]


def coords_from_link(link):
    for rx in COORD:
        m = rx.search(link or '')
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None


SHORT_HOSTS = ('maps.app.goo.gl', 'goo.gl', 'g.co')
MAPS_HOSTS = SHORT_HOSTS + ('maps.google.com', 'www.google.com', 'google.com')


def _host_ok(url, allowed):
    host = (urlparse(url).hostname or '').lower()
    return any(host == h or host.endswith('.' + h) for h in allowed)


def resolve_link(url, timeout=6):
    """Sigue un link corto de Google Maps (maps.app.goo.gl) y devuelve (lat, lng) o None. Sólo consulta hosts de Google."""
    if not url or not _host_ok(url, SHORT_HOSTS):
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (AguaClara)'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
            if not _host_ok(final, MAPS_HOSTS):
                return None
            found = coords_from_link(final)
            if found:
                return found
            return coords_from_link(resp.read(300000).decode('utf-8', 'ignore').replace('\\u003d', '=').replace('\\u0026', '&'))
    except Exception:
        return None


def normalize_phone(raw):
    """10 dígitos, sin +54 9, espacios ni guiones. Devuelve '' si no se puede dejar en ese formato."""
    digits = re.sub(r'\D', '', str(raw or ''))
    for prefix in ('549', '54'):
        if digits.startswith(prefix) and len(digits) > 10:
            digits = digits[len(prefix):]
            break
    digits = digits.lstrip('0') if len(digits) > 10 else digits
    if len(digits) == 12:  # código de área + 15 + número
        for i in (2, 3, 4):
            if digits[i:i + 2] == '15':
                digits = digits[:i] + digits[i + 2:]
                break
    return digits if len(digits) == 10 else ''
