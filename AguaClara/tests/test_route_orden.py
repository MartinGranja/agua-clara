import datetime
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.services import route_service as rs

DAY = datetime.date(2026, 10, 9)
# En línea recta: A (norte, lejos), B (centro), C (norte, cerca de A). El orden anotado A-B-C no es el más corto.
CLIENTS = [{'name': n, 'zone': 'Alta Gracia', 'lat': la, 'lng': -64.43, 'link': '', 'phone': '', 'obs': ''} for n, la in (('Aa', -31.50), ('Bb', -31.70), ('Cc', -31.51))]
LISTA = 'ALTA GRACIA\nAa\nBb\nCc'


def names(r):
    return [p['cliente'] for p in r['equipos'][0]['paradas']]


def test_keep_order_respects_written_order_but_still_reports_optimized_comparison():
    r = rs.plan(LISTA, CLIENTS, '08:30', None, DAY, optimize=False)
    assert r['modo'] == 'mi_orden' and names(r) == ['Aa', 'Bb', 'Cc']
    b = r['equipos'][0]
    assert b['kmUsado'] == b['kmManual'] and b['km'] < b['kmManual']
    assert r['analitica']['kmOptimizado'] < r['analitica']['kmManual']


def test_default_optimizes_and_uses_optimized_km():
    r = rs.plan(LISTA, CLIENTS, '08:30', None, DAY)
    assert r['modo'] == 'optimizado' and names(r) != ['Aa', 'Bb', 'Cc']
    assert r['equipos'][0]['kmUsado'] == r['equipos'][0]['km']


def test_custom_start_point_changes_distance():
    base = rs.plan(LISTA, CLIENTS, '08:30', None, DAY, optimize=False)['equipos'][0]['kmUsado']
    far = rs.plan(LISTA, CLIENTS, '08:30', None, DAY, optimize=False, origin_point=(-31.9, -64.0))['equipos'][0]['kmUsado']
    assert far > base


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(_env_file=None, database_url='sqlite:///' + str(tmp_path / 'o.db'), gemini_api_key='', admin_token=''))
    with TestClient(app) as c:
        yield c
    app.state.store.engine.dispose()


def test_api_origin_validation(api):
    ok = api.post('/api/admin/route/plan', json={'lista': 'ALTA GRACIA\nAna Demo\nBeto Demo', 'origen': 'https://maps.google.com/?q=-31.65,-64.43'})
    assert ok.status_code == 200 and ok.json()['base'] == 'Punto de partida indicado'
    assert api.post('/api/admin/route/plan', json={'lista': 'ALTA GRACIA\nAna Demo', 'origen': '-31.65, -64.43'}).status_code == 200
    bad = api.post('/api/admin/route/plan', json={'lista': 'ALTA GRACIA\nAna Demo', 'origen': 'https://maps.app.goo.gl/abc'})
    assert bad.status_code == 422


def test_before_rule_overrides_distance_order_and_shows_note():
    # La base está más cerca de Bb, pero la regla pide a Aa antes de las 08:45: debe ir primero aunque alargue el recorrido.
    free = rs.plan(LISTA, CLIENTS, '08:30', None, DAY)
    ruled = rs.plan('ALTA GRACIA\nAa antes de las 8:45\nBb\nCc', CLIENTS, '08:30', None, DAY)
    assert names(ruled)[0] == 'Aa' and names(ruled) != names(free)
    stop = ruled['equipos'][0]['paradas'][0]
    assert 'Antes de las 08:45' in ruled['equipos'][0]['mensaje'] and not stop['retraso'] and ruled['equipos'][0]['horaFija']


def test_before_rule_hour_without_minutes_means_afternoon_and_warns_when_impossible():
    r = rs.plan('ALTA GRACIA\nAa\nBb\nCc antes de las 2', CLIENTS, '08:30', None, DAY)
    assert 'Antes de las 14:00' in r['equipos'][0]['mensaje']
    late = rs.plan('ALTA GRACIA\nAa\nBb\nCc antes de las 8:20', CLIENTS, '08:30', None, DAY)
    assert any('no se llega antes de las 08:20' in a for a in late['avisos'])


def test_after_rule_waits():
    r = rs.plan('ALTA GRACIA\nAa después de las 11\nBb', CLIENTS, '08:30', None, DAY)
    row = next(p for p in r['equipos'][0]['paradas'] if p['cliente'] == 'Aa')
    assert row['llegada'] >= '11:00'


def test_resolve_links_fills_coordinates_and_only_queries_google_hosts(api, monkeypatch):
    from app.services import route_geo
    csv = 'Nombre,Teléfono,Maps,Zona\nGuchy,3547526392,https://maps.app.goo.gl/abc,Alta Gracia\nEuge,3513144931,"https://maps.google.com/?q=-31.72,-64.43",La Bolsa\n'
    assert api.put('/api/admin/clients', json={'csv': csv, 'replace': True}).status_code == 200
    monkeypatch.setattr('app.api.routes.resolve_link', lambda url: (-31.65, -64.42))
    r = api.post('/api/admin/clients/resolve-links').json()
    assert r['resueltos'] == 1 and r['sinCoordenadas'] == [] and r['summary']['sinCoordenadas'] == 0
    assert route_geo.resolve_link('https://evil.example.com/x') is None
    assert route_geo.resolve_link('http://127.0.0.1:1/x') is None


def test_resolve_links_requires_clients(api):
    assert api.post('/api/admin/clients/resolve-links').status_code == 422
