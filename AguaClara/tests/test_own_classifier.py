import io

import numpy as np
from PIL import Image

from app.services import own_classifier as oc


def jpeg(color, size=(160, 120), noise=0):
    arr = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    if noise:
        arr = np.clip(arr + np.random.default_rng(1).integers(-noise, noise, arr.shape), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format='JPEG')
    return buf.getvalue()


def toy_model(n):
    head = lambda classes, coef, b: {'classes': classes, 'mean': [0.0] * n, 'scale': [1.0] * n, 'coef': coef, 'intercept': b}
    zeros = [0.0] * n
    return {'binario': head(['mantenimiento', 'tratamiento'], [zeros], [2.0]),          # siempre «tratamiento» (p≈0,88)
            'tres_servicios': head(oc.SERVICES, [zeros, zeros, zeros], [0.0, 0.0, 1.0])}  # prefiere limpieza total


def test_features_fixed_length_and_unreadable():
    f = oc.extract_features(jpeg((20, 120, 160)))
    assert f.shape == (159,) and np.isfinite(f).all()
    assert oc.extract_features(b'no es una imagen') is None


def test_two_stage_rule_with_question():
    x = oc.extract_features(jpeg((20, 120, 160), noise=20)); model = toy_model(len(x))
    assert oc.decide(x, model, 'mas_4')['servicio'] == 'limpieza_total'
    assert oc.decide(x, model, 'menos_4')['servicio'] == 'recuperacion'
    sin = oc.decide(x, model)
    assert sin['base'] == 'foto_sin_confirmar' and sin['servicio'] == 'limpieza_total'
    model['binario']['intercept'] = [-2.0]
    assert oc.decide(x, model, 'mas_4')['servicio'] == 'mantenimiento'   # sin tratamiento, la pregunta no cambia nada


def test_predict_without_model_or_photo(tmp_path):
    assert oc.predict(jpeg((0, 0, 0)), model=None) in (None, oc.predict(jpeg((0, 0, 0))))
    assert oc.load_model(tmp_path / 'no_existe.json') is None


def test_shipped_model_runs_and_perception_records_it():
    model = oc.load_model()
    assert model and model['rasgos'] == 159
    out = oc.predict(jpeg((10, 110, 150), noise=15))
    assert out['servicio'] in oc.SERVICES and 0 <= out['prob_tratamiento'] <= 1


def test_perceive_records_own_classifier_without_changing_result():
    from types import SimpleNamespace
    from app.schemas import Analysis
    from app.services import perception
    one = lambda image, settings, i: Analysis(es_pileta=True, estado_agua='cristalina', presencia_algas_paredes=False, tipo_pileta='rectangular',
                                              problemas_visibles=[], observaciones='ok', confianza=0.9)
    photo = jpeg((10, 110, 150), noise=15)
    on, off = SimpleNamespace(vision_samples=1, cv_enabled=False, own_classifier_enabled=True), SimpleNamespace(vision_samples=1, cv_enabled=False, own_classifier_enabled=False)
    f1, m1 = perception.perceive(photo, on, one)
    f2, m2 = perception.perceive(photo, off, one)
    assert m1['propio']['servicio'] in oc.SERVICES and 'propio' not in m2
    assert f1.confianza == f2.confianza and f1.estado_agua == f2.estado_agua
