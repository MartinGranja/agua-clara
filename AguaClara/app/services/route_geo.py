"""Módulo B · configuración y lectura de ubicaciones."""
import re
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
