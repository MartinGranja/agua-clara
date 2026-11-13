"""Regla de servicio con agua verde: más de 4 meses sin limpieza ni productos = limpieza total."""
import pytest
from app.schemas import Consultation
from app.services.pricing_engine import calculate, service_for
from app.services.consultation_service import certainty_of
from app.services.analytics_service import service_of
from tests.test_backend import BASE


@pytest.mark.parametrize('water,algae,last,service,basis', [
    ('verde_leve', False, 'mas_4', 'limpieza_total', 'foto+tiempo'),
    ('verde_leve', False, 'menos_4', 'recuperacion', 'foto+tiempo'),
    ('verde_oscuro_opaco', True, 'menos_4', 'recuperacion', 'foto+tiempo'),
    ('verde_intenso', True, 'mas_4', 'limpieza_total', 'foto+tiempo'),
    ('verde_leve', False, None, 'recuperacion', 'foto_sin_confirmar'),
    ('verde_intenso', True, 'no_se', 'recuperacion', 'foto_sin_confirmar'),
    ('verde_oscuro_opaco', True, 'no_se', 'limpieza_total', 'foto_sin_confirmar'),
    ('cristalina', False, 'mas_4', 'mantenimiento', 'foto'),   # la respuesta solo importa con agua verde
    ('turbia', False, None, 'limpieza_total', 'foto'),
    ('cristalina', True, None, 'limpieza_total', 'foto'),
    ('desconocido', False, None, None, 'foto'),
])
def test_service_for(water, algae, last, service, basis):
    assert service_for(water, algae, last) == (service, basis)


def test_quote_uses_answer_and_prices_the_resulting_service():
    short = calculate(Consultation(**{**BASE, 'water': 'verde_intenso', 'algae': True, 'lastTreatment': 'menos_4'}))
    long = calculate(Consultation(**{**BASE, 'water': 'verde_intenso', 'algae': True, 'lastTreatment': 'mas_4'}))
    assert (short['service'], long['service']) == ('recuperacion', 'limpieza_total')
    assert long['price'] > short['price'] and long['lastTreatment'] == 'mas_4'


def test_photo_only_service_matches_budget_rule():
    assert service_of('verde_oscuro_opaco', True) == 'limpieza_total'
    assert service_of('verde_leve', False) == 'recuperacion'
    assert service_of('cristalina', False) == 'mantenimiento'


def test_certainty_drops_when_green_without_answer():
    analysis = {'result': {'confianza': 0.9, 'calidad_foto': 'buena'}, 'meta': {}}
    answered = certainty_of({'price': 1, 'serviceBasis': 'foto+tiempo'}, analysis)
    unanswered = certainty_of({'price': 1, 'serviceBasis': 'foto_sin_confirmar'}, analysis)
    assert answered['certainty'] == 'alta' and unanswered['certainty'] == 'media'
    assert any('hace cuánto' in r for r in unanswered['certaintyReasons'])


def test_invalid_answer_rejected():
    with pytest.raises(Exception):
        Consultation(**{**BASE, 'lastTreatment': 'ayer'})


def test_dialogue_accepts_treatment_step():
    from app.schemas import DialogueRequest
    assert DialogueRequest(step='treatment').step == 'treatment'
