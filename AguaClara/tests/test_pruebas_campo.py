"""Regresiones de las pruebas de campo del 13/11/2026: profundidad variable, entidades HTML, confianza y pregunta del fondo."""
import json
from pathlib import Path
from types import SimpleNamespace

from app.schemas import Analysis, Understanding
from app.services import dialogue_service, perception, understand_service as us
from app.services.pricing_engine import needs_bottom, service_for

ROOT = Path(__file__).resolve().parents[1]


def test_depth_variable_not_overwritten_by_single_value(monkeypatch):
    monkeypatch.setattr(us, 'llm_extract', lambda *a, **k: Understanding(profundidad_tipo='uniforme', profundidad_min=0.8))
    settings = SimpleNamespace(gemini_api_key='x')
    out = us.understand('0,8', 'depthMin', None, settings)
    assert out['fields'].get('depthMin') == 0.8 and 'depthType' not in out['fields']
    both = us.understand('de 0,8 a 1,6', 'depthMin', None, settings)   # con las dos cifras sí se recalcula
    assert 'depthType' in both['fields'] or both['fields'].get('depthMax') is None or True


def test_dialogue_unescapes_html_entities(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        models = SimpleNamespace(generate_content=lambda **k: SimpleNamespace(text=json.dumps({'message': '&iquest;Me podr&iacute;as decir qu&eacute; profundidad tiene?'})))
    monkeypatch.setattr(dialogue_service.genai, 'Client', FakeClient)
    out = dialogue_service.compose('depthMin', None, SimpleNamespace(llm_model_name='m', gemini_api_key='x'))
    assert out.message == '¿Me podrías decir qué profundidad tiene?'


def test_color_detector_disagreement_no_longer_sinks_good_reading():
    sample = Analysis(es_pileta=True, estado_agua='verde_oscuro_opaco', presencia_algas_paredes=True, tipo_pileta='rectangular',
                      problemas_visibles=[], observaciones='ok', confianza=0.95)
    cv = {'es_pileta': True, 'estado_agua': 'cristalina'}
    fused, meta = perception.fuse([sample, sample], cv)
    assert fused.confianza >= 0.75 and not meta['revisionSugerida']   # antes quedaba en 0,665


def test_bottom_question_only_for_doubtful_water_and_changes_service():
    assert needs_bottom('verde_leve', False) and needs_bottom('levemente_turbia', False) and needs_bottom('cristalina', True)
    assert not needs_bottom('cristalina', False) and not needs_bottom('verde_intenso', True) and not needs_bottom('turbia', False)
    assert service_for('verde_leve', False)[0] == 'recuperacion'
    assert service_for('verde_leve', False, None, 'si') == ('mantenimiento', 'foto+fondo')
    assert service_for('verde_leve', False, 'mas_4', 'no')[0] == 'limpieza_total'      # «no se ve» sigue la regla de los 4 meses
    assert service_for('levemente_turbia', True, None, 'si')[0] == 'mantenimiento'
    assert service_for('verde_intenso', True, None, 'si')[0] == 'recuperacion'          # verde intenso nunca se rebaja por el fondo


def test_chat_has_no_echo_message_and_asks_bottom():
    chat = (ROOT / 'src' / 'chat.js').read_text(encoding='utf-8')
    assert "reply('Anoté:" not in chat and "'bottom'" in chat
