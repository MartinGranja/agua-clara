import datetime
import itertools
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.services import client_base, route_parser as rp, route_rules as rules, route_service as rs, routing_engine as eng
from app.services.route_geo import coords_from_link, normalize_phone

CLIENTS = client_base.demo()
DAY = datetime.date(2026, 10, 9)


def plan(text, **kw):
    return rs.plan(text, CLIENTS, kw.pop('start', '12:00'), kw.pop('service', None), DAY, **kw)


def lines(result, block=0):
    return result['equipos'][block]['mensaje'].splitlines()


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(_env_file=None, database_url='sqlite:///' + str(tmp_path / 'r.db'), gemini_api_key='', admin_token=''))
    with TestClient(app) as c:
        yield c
    app.state.store.engine.dispose()


# ---- Regla 2 y 4: prefijos, dosis y productos ----
@pytest.mark.parametrize('kind,limp,c,p,expected', [
    ('quincenal', 2, 2, None, 'Colocar 1 kg cloro'), ('quincenal', 2, 1, None, 'Colocar ½ kg cloro'), ('quincenal', 2, 2, 1, 'Colocar 1 kg cloro + 2 pastillas'),
    ('quincenal', 2, 1, 1, 'Colocar ½ kg cloro + 2 pastillas'), ('quincenal', 2, None, 1, 'Colocar 2 pastillas'),
    ('semanal', 2, 2, None, 'Colocar ½ kg cloro'), ('semanal', 2, 1, None, 'Colocar ¼ kg cloro'), ('semanal', 2, 2, 1, 'Colocar ½ kg cloro + 1 pastilla'),
    ('semanal', 2, 1, 1, 'Colocar ¼ kg cloro + 1 pastilla'), ('semanal', 2, None, 1, 'Colocar 1 pastilla'),
])
def test_dose_table_from_the_rules(kind, limp, c, p, expected):
    assert rules.treatment(kind, limp, c, p) == expected


def test_first_cleaning_of_the_month_leaves_and_places():
    assert rules.treatment('quincenal', 0, 2, 1) == 'Dejar 2 kg cloro + 1 kg pastillas, Colocar 1 kg cloro + 2 pastillas'
    assert rules.treatment('semanal', 0, 2, None) == 'Dejar 2 kg cloro, Colocar ½ kg cloro'


def test_owed_cleaning_still_places_and_owed_product_is_skipped():
    assert rules.treatment('quincenal', -1, 2, 1) == 'Colocar 1 kg cloro + 2 pastillas'
    assert rules.treatment('quincenal', 0, -1, 1) == 'Dejar 1 kg pastillas, Colocar 2 pastillas'
    assert rules.treatment('quincenal', 0, -1, -1) == ''


@pytest.mark.parametrize('kind', ['unica', 'mensual', 'no_toca'])
def test_no_products_for_single_monthly_or_skipped(kind):
    assert rules.treatment(kind, 0, 2, 1) == ''


def test_fraction_formatting():
    assert [rules.kg(x) for x in (0.25, 0.5, 0.75, 1, 1.5, 0.3)] == ['¼ kg', '½ kg', '¾ kg', '1 kg', '1 ½ kg', '0,3 kg']


def test_prefix_kinds_and_limp_not_in_message():
    r = plan('VIERNES\nALTA GRACIA\n//Ana Demo 0 limp 2c 1p\n/Beto Demo 2 limp 2c\n.Carla Demo\nDiego Demo 3 limp 2c\nElena Demo')
    text = r['equipos'][0]['mensaje']
    assert 'Beto Demo' not in text and 'limp' not in text.lower()
    assert 'Ana Demo (Dejar 2 kg cloro + 1 kg pastillas, Colocar 1 kg cloro + 2 pastillas)' in text
    assert 'Carla Demo\n' in text and 'Elena Demo\n' in text            # sin productos: sin paréntesis
    assert 'Diego Demo (Colocar ½ kg cloro)' in text                    # semanal
    assert r['resumen']['noTocan'] == 1 and '(4)' in lines(r)[1]


# ---- Regla 5: notas ----
def test_free_notes_parentheses_and_fixed_phrases():
    r = plan('ALTA GRACIA\nCLIO GRIS:\n//Ana Demo 2 limp 2c llevar sacahojas\nBeto Demo (llamar antes)\nCarla Demo llevar 1c')
    text = r['equipos'][0]['mensaje']
    assert 'Ana Demo (Colocar 1 kg cloro) (Llevar sacahojas)' in text
    assert 'Beto Demo (llamar antes)' in text                           # lo que ya venía entre paréntesis se copia tal cual
    assert 'Carla Demo (Llevar 1c)' in text                             # "1c" en una nota no es un producto


def test_manual_instruction_replaces_the_automatic_rule():
    text = plan('ALTA GRACIA\n//Ana Demo 0 limp 2c 1p esta vez solo dejar 1c')['equipos'][0]['mensaje']
    assert 'Ana Demo (Esta vez solo dejar 1c)' in text and 'Colocar' not in text and 'Dejar 2 kg' not in text


def test_line_without_own_client_becomes_an_item_with_phone_and_location():
    r = plan('ALTA GRACIA\nDejar 1c a Fabio Demo\nAna Demo')
    text = r['equipos'][0]['mensaje']
    assert 'Dejar 1c a Fabio Demo\n📞 3515550006' in text.replace('12:10 ', '').replace('12:00 ', '').replace('12:30 ', '')
    assert r['equipos'][0]['piletas'] == 1                               # una entrega no cuenta como pileta


def test_extra_delivery_adds_no_time():
    a = plan('ALTA GRACIA\nAna Demo\nDejar 1c a Fabio Demo')['equipos'][0]
    b = plan('ALTA GRACIA\nAna Demo')['equipos'][0]
    assert a['fin'] == b['fin']


# ---- Regla 6: formato de salida ----
def test_output_format_matches_the_spec():
    r = plan('VIERNES\nALTA GRACIA 1\nCLIO AZUL:\n//Ana Demo 0 limp 2c 1p 13:30', start='13:30')
    assert lines(r)[:4] == ['VIERNES', 'ALTA GRACIA – CLIO AZUL (1)', '', '13:30 Ana Demo (Dejar 2 kg cloro + 1 kg pastillas, Colocar 1 kg cloro + 2 pastillas)']
    assert lines(r)[4].startswith('📞 3515550001') and lines(r)[-1].startswith('📍 https://maps.google.com/?q=')


def test_address_only_when_the_base_has_one():
    text = plan('DESPEÑADEROS\nDaniela Demo')['equipos'][0]['mensaje']
    assert '🏠 Calle Falsa 123' in text and '📝 perro suelto' in text
    assert '🏠' not in plan('ALTA GRACIA\nBeto Demo')['equipos'][0]['mensaje']


def test_missing_client_shows_FALTA():
    text = plan('ALTA GRACIA\nPedro Perez 2 limp 2c')['equipos'][0]['mensaje']
    assert 'Pedro Perez (Colocar ½ kg cloro)' in text and '📞 FALTA' in text and '📍 FALTA' in text


def test_one_message_per_zone_and_team_with_counts():
    r = plan('VIERNES\nALTA GRACIA 2 y 1\nCLIO AZUL:\nAna Demo\nBeto Demo\nCLIO GRIS:\nCarla Demo')
    assert [e['nombre'] for e in r['equipos']] == ['ALTA GRACIA – CLIO AZUL', 'ALTA GRACIA – CLIO GRIS'] and [e['piletas'] for e in r['equipos']] == [2, 1]
    assert not any('se anotaron' in a for a in r['avisos'])


def test_declared_count_mismatch_warns_but_cancellation_does_not():
    assert any('se anotaron 3 piletas' in a for a in plan('ALTA GRACIA 3\nCLIO AZUL:\nAna Demo\nBeto Demo')['avisos'])
    r = plan('ALTA GRACIA 3\nCLIO AZUL:\nAna Demo\nBeto Demo\nCarla Demo\ncancela Beto Demo')
    assert r['equipos'][0]['piletas'] == 2 and '(2)' in lines(r)[1] and 'Beto' not in r['equipos'][0]['mensaje']


def test_declared_sizes_split_unassigned_stops_between_teams():
    clients = [{'name': f'C{i}', 'zone': 'Alta Gracia', 'lat': -31.64 + i * 0.01, 'lng': -64.43, 'link': '', 'phone': '', 'obs': ''} for i in range(5)]
    r = rs.plan('ALTA GRACIA 3 y 2\nC0\nC1\nC2\nC3\nC4', clients, '12:00', None, DAY)
    assert sorted(e['piletas'] for e in r['equipos']) == [2, 3]
    assert {p['cliente'] for p in r['equipos'][0]['paradas']} in ({'C0', 'C1', 'C2'}, {'C0', 'C1'}, {'C3', 'C4'}, {'C2', 'C3', 'C4'})


# ---- Horarios ----
def test_start_time_and_thirty_minutes_per_pool():
    r = plan('ALTA GRACIA\nAna Demo\nBeto Demo\nCarla Demo', start='08:30')
    assert [p['llegada'] for p in r['equipos'][0]['paradas']] == ['08:30', '09:00', '09:30']


def test_fixed_time_is_respected_and_others_flow_around_it():
    r = plan('ALTA GRACIA\nAna Demo\nBeto Demo 10:00\nCarla Demo\nDiego Demo', start='08:30')
    rows = r['equipos'][0]['paradas']
    assert next(p for p in rows if p['cliente'] == 'Beto Demo')['llegada'] == '10:00'
    assert [p['llegada'] for p in rows] == sorted(p['llegada'] for p in rows)


def test_a_fixed_time_nobody_can_reach_is_reported():
    r = plan('ALTA GRACIA\nAna Demo 08:30\nBeto Demo 08:30', start='08:30')
    assert any('no se llega a las 08:30' in a for a in r['avisos'])


def test_second_block_of_the_same_team_continues_the_clock():
    r = plan('VIERNES\nALTA GRACIA\nCLIO AZUL:\nAna Demo\nBeto Demo\nLA BOLSA\nCLIO AZUL:\nIrene Demo', start='08:00')
    assert r['equipos'][1]['paradas'][0]['llegada'] == '09:00'


def test_travel_time_is_optional():
    text = 'VIERNES\nDESPEÑADEROS\nCLIO AZUL:\nTomás Demo\nALTA GRACIA\nCLIO AZUL:\nAna Demo'
    far = plan(text, start='08:00')
    far_t = plan(text, start='08:00', travel=True)
    assert far['equipos'][1]['paradas'][0]['llegada'] == '08:30'
    assert far_t['equipos'][1]['paradas'][0]['llegada'] > '08:30'


# ---- Regla 8: cambios de último momento ----
def test_cancel_removes_client_and_recounts():
    r = plan('ALTA GRACIA\nAna Demo\nBeto Demo\nCancelar Ana Demo')
    assert [p['cliente'] for p in r['equipos'][0]['paradas']] == ['Beto Demo'] and any('Cancelado: Ana Demo' in a for a in r['avisos'])


def test_shift_only_affects_the_next_n_pools():
    r = plan('ALTA GRACIA\nAna Demo\nCorrer las siguientes 2 piletas\nBeto Demo\nCarla Demo\nDiego Demo', start='12:00')
    by = {p['cliente']: p for p in r['equipos'][0]['paradas']}
    assert by['Beto Demo']['corrida'] == 30 and by['Carla Demo']['corrida'] == 30
    assert by['Ana Demo']['corrida'] == 0 and by['Diego Demo']['corrida'] == 0
    assert any(p['llegada'] == '11:30' or p['llegada'] == '12:00' for p in by.values())


def test_shift_with_custom_minutes():
    r = plan('ALTA GRACIA\nCorrer las siguientes 1 piletas 15 min\nAna Demo\nBeto Demo')
    assert next(p for p in r['equipos'][0]['paradas'] if p['cliente'] == 'Ana Demo')['corrida'] == 15


# ---- Regla 7: base de clientes y búsqueda de nombres ----
@pytest.mark.parametrize('raw,expected', [('+54 9 351 345-3993', '3513453993'), ('3513453993', '3513453993'), ('0351 15 4453993', '3514453993'), ('123', ''), ('', '')])
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


def test_same_first_name_resolves_by_zone():
    pa = plan('ALTA GRACIA\nDaniela')['equipos'][0]['paradas'][0]
    pb = plan('DESPEÑADEROS\nDaniela')['equipos'][0]['paradas'][0]
    assert pa['telefono'] == '3515559001' and pb['telefono'] == '3515559002'


def test_same_name_different_people_is_told_apart_by_phone():
    both = [{'name': 'Fernando', 'zone': None, 'phone': '3547577212'}, {'name': 'Fernando Samma', 'zone': None, 'phone': '3512222222'}, {'name': 'Fernando', 'zone': None, 'phone': '3519999999'}]
    assert rp.match_client('Fernando', both)[0] == 'ambiguo'
    assert rp.match_client('Fernando', both, phone='3519999999')[1]['phone'] == '3519999999'
    assert rp.match_client('Fernando Samma', both)[1]['phone'] == '3512222222'


def test_alias_accents_and_partial_names():
    assert plan('ALTA GRACIA\nAnita')['equipos'][0]['paradas'][0]['cliente'] == 'Ana Demo'
    assert rp.match_client('ana', CLIENTS)[1]['name'] == 'Ana Demo'
    assert rp.match_client('tomas demo', CLIENTS)[1]['name'] == 'Tomás Demo'


def test_csv_import_rules():
    text = 'Cliente;Teléfono;Ubicación;Observaciones fijas;Alias\nConstanza Lescano;+54 9 351 345-3993;https://maps.google.com/?q=-31.8142,-64.2966;\"Maipú 146; llamar antes\";Coty\nFernando;3547577212;;;\nFernando;3519999999;;;\nFernando;3519999999;;;\n'
    items, warnings = client_base.read_csv(text)
    assert [c['name'] for c in items] == ['Constanza Lescano', 'Fernando', 'Fernando'] and len({c['id'] for c in items}) == 3
    first = items[0]
    assert first['phone'] == '3513453993' and first['alias'] == ['Coty'] and first['address'] == 'Maipú 146' and first['zone'] == 'Despeñaderos' and 'llamar antes' in first['notes']
    assert len(warnings) == 1
    assert rp.match_client('Coty', items)[1]['name'] == 'Constanza Lescano'


def test_csv_without_name_column_is_rejected():
    assert client_base.read_csv('a,b\n1,2')[0] == []


@pytest.mark.parametrize('link,expected', [('https://maps.google.com/?q=-31.7,-64.4', (-31.7, -64.4)), ('https://www.google.com/maps/@-31.7,-64.4,15z', (-31.7, -64.4)), ('https://maps.app.goo.gl/abc', None), ('', None)])
def test_coords_from_link(link, expected):
    assert coords_from_link(link) == expected


# ---- Lista: interpretación ----
def test_header_and_item_parsing():
    parsed = rp.parse_day('VIERNES\nALTA GRACIA 11 y 11\nCLIO AZUL:\n//Vale Maizon 0 limp 2c 1p 13:30', CLIENTS)
    item = parsed['items'][0]
    assert parsed['day'] == 'viernes' and parsed['declared'] == {'Alta Gracia': [11, 11]}
    assert (item['prefix'], item['limp'], item['chlorine'], item['pills'], item['time'], item['zone'], item['vehicle']) == ('//', 0, 2.0, 1.0, 13 * 60 + 30, 'Alta Gracia', 'clio azul')


@pytest.mark.parametrize('text,minutes', [('Ana 9:30', 570), ('Ana 9.30', 570), ('Ana 10 hs', 600), ('08:05 Ana', 485), ('Ana 2 limp 2c 13:30', 810)])
def test_time_formats(text, minutes):
    assert rp.parse_day(text, CLIENTS)['items'][0]['time'] == minutes


def test_phone_digits_are_not_a_time():
    assert rp.parse_day('Ana 3515550001', CLIENTS)['items'][0]['time'] is None


def test_legacy_zone_line_with_commas_still_works():
    r = plan('La Bolsa: Irene Demo, Javier Demo (llamar antes)')
    assert r['equipos'][0]['piletas'] == 2


def test_unknown_or_ambiguous_names_are_not_dropped():
    r = plan('Pedro Perez\nDaniela\nAna Demo')
    assert r['resumen']['paradas'] == 3 and len(r['pendientes']) == 2
    assert any(p['texto'] == 'Pedro Perez' for p in r['pendientes'])


def test_productos_ignored_without_prefix_warn():
    r = plan('ALTA GRACIA\n.Ana Demo 0 limp 2c')
    assert any('por su prefijo no se calculan' in a for a in r['avisos'])


# ---- Motor ----
def test_exact_matches_bruteforce():
    import random
    random.seed(3)
    pts = [(-31.65 + random.uniform(-.05, .05), -64.43 + random.uniform(-.05, .05)) for _ in range(7)]
    m = eng.Matrix((-31.6533, -64.4283), pts, 1.35, 38)
    order, method = eng.solve([{} for _ in pts], m)
    brute = min(eng.path_cost(list(p), m.km) for p in itertools.permutations(range(1, 8)))
    assert method == 'exacto' and eng.path_cost([i + 1 for i in order], m.km) == pytest.approx(brute)


def test_heuristic_is_close_to_exact_and_not_worse_than_input_order():
    import random
    random.seed(11)
    pts = [(-31.65 + random.uniform(-.05, .05), -64.43 + random.uniform(-.05, .05)) for _ in range(11)]
    m = eng.Matrix((-31.6533, -64.4283), pts, 1.35, 38)
    exact = eng.path_cost(eng.held_karp(list(range(1, 12)), m.km), m.km)
    stops = [{'time': None} for _ in pts]
    heur = eng.local_search(list(range(11)), lambda o: eng.objective(o, stops, m, 0))
    assert eng.path_cost([i + 1 for i in heur], m.km) <= exact * 1.05
    assert eng.path_cost([i + 1 for i in heur], m.km) <= eng.path_cost(list(range(1, 12)), m.km)


def test_optimized_never_longer_than_written_order():
    r = plan('ALTA GRACIA\n' + '\n'.join(c['name'] for c in CLIENTS if c['zone'] == 'Alta Gracia' and c['name'] != 'Daniela Demo'))
    assert r['resumen']['km'] <= r['resumen']['kmManual'] + 1e-6


# ---- API ----
LISTA = 'VIERNES\nALTA GRACIA 3\nCLIO AZUL:\n//Ana Demo 0 limp 2c 1p 13:30\nBeto Demo\nCarla Demo'


def test_api_plan_save_and_read(api):
    assert api.get('/api/admin/clients').json()['demo'] is True
    r = api.post('/api/admin/route/plan', json={'lista': LISTA, 'fecha': '2026-10-09', 'inicio': '12:00', 'guardar': True})
    assert r.status_code == 200 and r.json()['baseDemo'] and r.json()['id']
    assert '13:30 Ana Demo (Dejar' in r.json()['equipos'][0]['mensaje']
    assert api.get('/api/admin/routes').json()[0]['id'] == r.json()['id']
    saved = api.get('/api/admin/routes/' + r.json()['id']).json()
    assert saved['lista'] == LISTA and saved['resumen'] == r.json()['resumen']


def test_api_import_replaces_demo_and_persists(api):
    csv = 'Nombre,Zona,Teléfono,Maps\nCliente Uno,La Bolsa,3510000001,"https://maps.google.com/?q=-31.72,-64.43"\nCliente Dos,La Bolsa,,"https://maps.google.com/?q=-31.73,-64.42"\n'
    done = api.put('/api/admin/clients', json={'csv': csv}).json()
    assert done['summary']['total'] == 2 and done['demo'] is False
    plan_ = api.post('/api/admin/route/plan', json={'lista': 'LA BOLSA\nCliente Uno\nCliente Dos\nIrene'}).json()
    assert plan_['resumen']['paradas'] == 3 and plan_['pendientes'][0]['texto'] == 'Irene' and not plan_['baseDemo']
    assert api.delete('/api/admin/clients').json()['demo'] is True


def test_api_suggest_uses_usual_day(api):
    text = api.get('/api/admin/route/suggest', params={'dia': 'Miércoles'}).json()['lista']
    assert text.startswith('MIÉRCOLES\nLA BOLSA\nCLIO GRIS:') and 'Irene Demo' in text and 'Tomás Demo' not in text


@pytest.mark.parametrize('body', [{'lista': ''}, {'lista': '   '}, {'lista': 'x' * 8001}, {'lista': 'Ana', 'inicio': '25:00'}, {'lista': 'Ana', 'equipos': 3}, {'lista': ',,;'}])
def test_api_rejects_bad_plans(api, body):
    assert api.post('/api/admin/route/plan', json=body).status_code == 422


def test_api_import_errors(api):
    assert api.put('/api/admin/clients', json={'csv': 'a,b\n1,2'}).status_code == 422


def test_route_endpoints_require_the_admin_token(tmp_path):
    app = create_app(Settings(_env_file=None, database_url='sqlite:///' + str(tmp_path / 'a.db'), admin_token='secreto-largo', allow_remote=True))
    with TestClient(app) as c:
        for method, path in [('get', '/api/admin/clients'), ('post', '/api/admin/route/plan'), ('get', '/api/admin/routes')]:
            assert getattr(c, method)(path).status_code == 401
        ok = c.post('/api/admin/route/plan', json={'lista': 'ALTA GRACIA\nAna Demo'}, headers={'Authorization': 'Bearer secreto-largo'})
        assert ok.status_code == 200
    app.state.store.engine.dispose()


def test_stops_without_zone_join_the_teams_known_zone():
    csv = 'Nombre,Zona,Teléfono,Maps,Observaciones\nAna Demo,Alta Gracia,3515550001,,\nBeto Demo,,3515550002,,\n'
    from app.services.client_base import read_csv
    clients = read_csv(csv)[0]
    r = rs.plan('CLIO GRIS:\n//Ana Demo 1 limp 2c\n//Beto Demo 1 limp 2c', clients, '12:00', None, DAY)
    assert len(r['equipos']) == 1 and r['equipos'][0]['piletas'] == 2
