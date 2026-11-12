import io
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.schemas import Consultation,Analysis
from app.services.pricing_engine import calculate
from app.services.vision_service import prepare_image,InvalidImage,VisionUnavailable,analyze

AID='00000000-0000-4000-8000-000000000001'
BASE=dict(measurementsConfirmed=True,analysisId=AID,shape='rectangular',length=7,width=4,depthType='uniforme',depthMin=1.4,water='verde_intenso',algae=True,zone='La Bolsa',name='Cliente Prueba',phone='0000000000',day='A coordinar')

@pytest.fixture
def client(tmp_path):
    app=create_app(Settings(_env_file=None,database_url='sqlite:///'+str(tmp_path/'test.db'),gemini_api_key='',admin_token=''))
    seed(app)
    with TestClient(app) as client:yield client
    app.state.store.engine.dispose()

def payload(**changes):return {'requestId':str(uuid4()),'data':{**BASE,**changes}}

def png():
    out=io.BytesIO();Image.new('RGB',(32,24),(20,140,100)).save(out,format='PNG');return out.getvalue()

@pytest.mark.parametrize('area,price',[(12,60000),(21,60000),(21.001,None),(24,None),(27.999,None),(28,72000),(39.999,72000),(40,None),(40.001,81000),(53.999,81000),(54,None),(54.001,90000),(60,90000),(60.001,90001.5),(11.999,None)])
def test_tariff_boundaries(area,price):
    assert calculate(Consultation(**{**BASE,'length':area/2,'width':2}))['price']==price

@pytest.mark.parametrize('state,algae,service,price', [('cristalina',False,'mantenimiento',24000),('cristalina',True,'limpieza_total',170000),('levemente_turbia',False,'mantenimiento',24000),('levemente_turbia',True,'limpieza_total',170000),('turbia',False,'limpieza_total',170000),('verde_leve',False,'recuperacion',72000),('verde_oscuro_opaco',True,'limpieza_total',170000)])
def test_classification(state,algae,service,price):
    result=calculate(Consultation(**{**BASE,'water':state,'algae':algae}))
    assert (result['service'],result['price'])==(service,price)

def test_variable_volume(client):
    result=client.post('/api/quotes',json={**BASE,'depthType':'variable','depthMin':1,'depthMax':1.8}).json()
    assert result['dimensions']['depth']==1.4
    assert result['dimensions']['volume']==39.2
    assert (result['price'],result['unitPrice'],result['cleanings'])==(72000,36000,2)

@pytest.mark.parametrize('changes',[{'length':-7},{'length':0},{'depthMin':0},{'depthType':'variable','depthMin':2,'depthMax':1},{'length':'foo'},{'phone':'123'},{'phone':'abc0000000000'},{'day':'inventado'},{'price':1},{'water':'fake'},{'name':' '}])
def test_invalid_server_inputs(client,changes):
    r=client.post('/api/quotes',json={**BASE,**changes});assert r.status_code==422
    assert all('input' not in error for error in r.json()['detail'])

@pytest.mark.parametrize('changes',[{'zone':'Villa La Merced'},{'zone':'Fuera de Alta Gracia'}])
def test_no_price_without_evidence(client,changes):assert client.post('/api/quotes',json={**BASE,**changes}).json()['price'] is None

@pytest.mark.parametrize('changes',[{'unknownDepth':True},{'unknown':True},{'measurementsConfirmed':False},{'shape':'otra','depthMin':None}])
def test_requires_confirmed_measurements(client,changes):
    assert client.post('/api/quotes',json={**BASE,**changes}).status_code==409
    assert client.post('/api/requests',json=payload(**changes)).status_code==409


def test_create_retry_and_review(client):
    body=payload();first=client.post('/api/requests',json=body);assert first.status_code==201
    record=first.json();assert record['id']==body['requestId'];assert record['quote']['price']==72000
    assert client.post('/api/requests',json=body).json()==record
    assert len(client.get('/api/admin/requests').json())==1
    changed={**body,'data':{**body['data'],'length':8}}
    assert client.post('/api/requests',json=changed).status_code==409
    review=client.patch('/api/admin/requests/'+record['id'],json={'price':37000,'note':'Ajuste revisado con el prestador.'})
    assert review.status_code==200;assert review.json()['review']['price']==37000
    assert client.get('/api/admin/requests').json()[0]['state']=='reviewed'

def test_concurrent_retries(client):
    body=payload()
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:client.post('/api/requests',json=body),range(4)))
    assert all(r.status_code==201 for r in results)
    assert len(client.get('/api/admin/requests').json())==1

def test_sqlite_survives_new_app(tmp_path):
    cfg=Settings(_env_file=None,database_url='sqlite:///'+str(tmp_path/'persist.db'),gemini_api_key='',admin_token='')
    a=create_app(cfg)
    seed(a)
    with TestClient(a) as c:record=c.post('/api/requests',json=payload()).json()
    a.state.store.engine.dispose()
    b=create_app(cfg)
    with TestClient(b) as c:assert c.get('/api/admin/requests').json()[0]['id']==record['id']
    b.state.store.engine.dispose()

def test_owner_auth(client):
    client.app.state.settings.admin_token='test-owner-secret'
    assert client.get('/api/admin/requests').status_code==401
    assert client.get('/api/admin/requests',headers={'Authorization':'Bearer test-owner-secret'}).status_code==200
    assert 'test-owner-secret' not in client.get('/api/config').text

def test_cross_origin(client):assert client.post('/api/quotes',json=BASE,headers={'Origin':'https://unrelated.example'}).status_code==403

def test_outside_review_cannot_quote(client):
    record=client.post('/api/requests',json=payload(zone='Villa La Merced')).json()
    assert client.patch('/api/admin/requests/'+record['id'],json={'price':30000,'note':'Revisar cobertura.'}).status_code==409

def test_missing_key_image_fallback(client):
    r=client.post('/api/analysis',files={'image':('test.png',png(),'image/png')});assert r.status_code==503
    assert 'Intentá' in r.json()['detail'];assert 'price' not in r.json()

def test_image_content_validation(client):
    assert client.post('/api/analysis',files={'image':('fake.png',b'not an image','image/png')}).status_code==422
    assert client.post('/api/analysis',files={'image':('fake.jpg',png(),'image/jpeg')}).status_code==422

def test_image_resize_and_metadata():
    out=io.BytesIO();image=Image.new('RGB',(1500,1000));exif=Image.Exif();exif[270]='private';image.save(out,format='JPEG',exif=exif)
    prepared=prepare_image(out.getvalue(),'image/jpeg')
    with Image.open(io.BytesIO(prepared)) as result:assert max(result.size)==768;assert not result.getexif()
    with pytest.raises(InvalidImage):prepare_image(b'x'*(10*1024*1024+1),'image/png')

def test_gemini_contract_and_provenance(client,monkeypatch):
    client.app.state.settings.gemini_api_key='test-only'
    import app.api.routes as routes
    monkeypatch.setattr(routes,'analyze',lambda *_:Analysis(es_pileta=True,estado_agua='verde_intenso',presencia_algas_paredes=True,tipo_pileta='rectangular',problemas_visibles=['algas'],observaciones='Agua verde visible.',confianza=0.9))
    result=client.post('/api/analysis',files={'image':('test.png',png(),'image/png')});assert result.status_code==200
    aid=result.json()['id']
    q=client.post('/api/quotes',json={**BASE,'analysisId':aid}).json();assert q['classificationSource']=='gemini'
    assert client.post('/api/quotes',json={**BASE,'water':'turbia','analysisId':aid}).status_code==409
    assert client.post('/api/quotes',json={**BASE,'analysisId':str(uuid4())}).status_code==409

def test_gemini_error_no_fabrication(client,monkeypatch):
    client.app.state.settings.gemini_api_key='test-only'
    import app.api.routes as routes
    def fail(*_):raise VisionUnavailable('Intentá nuevamente o describí el agua.')
    monkeypatch.setattr(routes,'analyze',fail)
    result=client.post('/api/analysis',files={'image':('test.png',png(),'image/png')});assert result.status_code==503;assert 'result' not in result.json()

def test_gemini_sdk_request_and_invalid_json(monkeypatch):
    import app.services.vision_service as vs
    observed={}
    class FakeClient:
        def __init__(self,**kwargs):self.models=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def generate_content(self,**kwargs):
            observed.update(kwargs)
            return type('Response',(),{'text':'not json'})()
    monkeypatch.setattr(vs.genai,'Client',FakeClient)
    with pytest.raises(VisionUnavailable):analyze(b'test',Settings(_env_file=None,gemini_api_key='test-only'))
    assert observed['model']=='gemini-3.6-flash'
    assert observed['config'].response_mime_type=='application/json'
    assert observed['config'].response_schema is None
    assert observed['config'].response_json_schema == vs.vision_schema()


def seed(app):
    app.state.store.save_analysis(AID,{'result':{'es_pileta':True,'tipo_pileta':'rectangular','confianza':0.9,'estado_agua':'verde_intenso','presencia_algas_paredes':True},'model':'test','photo':'data:image/jpeg;base64,cGhvdG8='})

def test_dialogue_uses_stored_analysis_and_validates_steps(client,monkeypatch):
    from app.schemas import DialogueReply
    import app.api.routes as routes
    client.app.state.settings.gemini_api_key='test-only'
    observed={}
    def compose(step,analysis,settings):
        observed.update(step=step,analysis=analysis)
        return DialogueReply(message='Veo el agua verde. ¿Cuánto mide de largo y ancho?')
    monkeypatch.setattr(routes,'compose',compose)
    r=client.post('/api/dialogue',json={'step':'size','analysisId':AID})
    assert r.status_code==200
    assert observed['analysis']['result']['tipo_pileta']=='rectangular'
    assert client.post('/api/dialogue',json={'step':'inventar_precio'}).status_code==422
    assert client.post('/api/dialogue',json={'step':'size','analysisId':str(uuid4())}).status_code==404

@pytest.mark.parametrize('shape',['circular','ovalada','en_l','rinon','irregular','cuadrada'])
def test_named_shapes(shape):
    result=Analysis(es_pileta=True,estado_agua='verde_intenso',presencia_algas_paredes=True,tipo_pileta=shape,problemas_visibles=[],observaciones='Agua verde.',confianza=0.9)
    assert result.tipo_pileta==shape

@pytest.mark.parametrize('code,expected_calls',[(503,2),(429,2),(400,1)])
def test_vision_retries_only_transient_errors(monkeypatch,code,expected_calls):
    import app.services.vision_service as vs
    calls=[]
    expected=Analysis(es_pileta=True,estado_agua='verde_intenso',presencia_algas_paredes=True,tipo_pileta='rectangular',problemas_visibles=[],observaciones='Agua verde.',confianza=0.9)
    def once(*args):
        calls.append(1)
        if len(calls)==1:
            cause=Exception('provider error');cause.code=code
            raise VisionUnavailable('No disponible') from cause
        return expected
    monkeypatch.setattr(vs,'_analyze_once',once)
    monkeypatch.setattr(vs.time,'sleep',lambda *_:None)
    if code==400:
        with pytest.raises(VisionUnavailable):vs.analyze(b'x',None)
    else:assert vs.analyze(b'x',None)==expected
    assert len(calls)==expected_calls

def test_daily_quota_message_does_not_retry(monkeypatch):
    import app.services.vision_service as vs
    calls=[]
    class FakeClient:
        def __init__(self,**kwargs):self.models=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def generate_content(self,**kwargs):
            calls.append(1)
            error=Exception('GenerateRequestsPerDayPerProjectPerModel-FreeTier');error.code=429
            raise error
    monkeypatch.setattr(vs.genai,'Client',FakeClient)
    with pytest.raises(VisionUnavailable,match='cuota diaria'):
        vs.analyze(b'x',Settings(_env_file=None,gemini_api_key='test-only'))
    assert len(calls)==1

def test_requires_ai_and_rejects_modified_evaluation(client):
    for changes in [{'analysisId':None},{'water':'turbia'},{'algae':False}]:
        assert client.post('/api/quotes',json={**BASE,**changes}).status_code==409
        assert client.post('/api/requests',json=payload(**changes)).status_code==409

def test_admin_photo_and_conversation_persist_and_are_private(client):
    body=payload();body['conversation']=[{'role':'user','text':'<script>not executable</script>','at':'2026-10-03T12:00:00Z','image':False}]
    r=client.post('/api/requests',json=body);assert r.status_code==201
    url='/api/admin/requests/'+r.json()['id']+'/details'
    details=client.get(url).json()
    assert details['photo']=='data:image/jpeg;base64,cGhvdG8='
    assert details['conversation']==body['conversation']
    client.app.state.settings.admin_token='secret'
    assert client.get(url).status_code==401
    assert client.get(url,headers={'Authorization':'Bearer secret'}).json()==details

def test_legacy_request_details(client):
    rid=str(uuid4());client.app.state.store.create(rid,{**BASE,'analysisId':None},{})
    assert client.get('/api/admin/requests/'+rid+'/details').json()=={'photo':None,'conversation':[],'analysis':None,'validation':None}

@pytest.mark.parametrize('shape',['otra','indeterminado'])
def test_ai_shape_without_rectangular_calculation(client,shape):
    aid=str(uuid4())
    client.app.state.store.save_analysis(aid,{'result':{'es_pileta':True,'tipo_pileta':shape,'confianza':0.9,'estado_agua':'verde_intenso','presencia_algas_paredes':True},'model':'test'})
    data={**BASE,'analysisId':aid,'shape':'otra'}
    result=client.post('/api/quotes',json=data)
    assert result.status_code==200
    assert result.json()['dimensions']['area'] is None
    assert result.json()['price'] is None
    assert client.post('/api/quotes',json={**data,'shape':'rectangular'}).status_code==409

@pytest.mark.parametrize('water,algae,expected',[('cristalina',False,40000),('verde_intenso',True,120000),('turbia',True,306666.67)])
def test_proportional_above_sixty(water,algae,expected):
    q=calculate(Consultation(**{**BASE,'length':10,'width':8,'water':water,'algae':algae}))
    assert q['price']==expected
    assert q['calculation']['extraArea']==20
    assert q['status']=='estimada'


@pytest.mark.parametrize('depth,factor',[(1,1),(1.5,1),(1.75,1.25),(2,1.5)])
def test_depth_multiplier_applies_to_total(depth,factor):
    # Mantenimiento 7x4 = $24.000 (hoja Profundidad y volumen: 1,75 m -> x1,25 = $30.000).
    q=calculate(Consultation(**{**BASE,'water':'cristalina','algae':False,'length':7,'width':4,'depthMin':depth}))
    assert q['depthMultiplier']==factor and q['price']==24000*factor
    r=calculate(Consultation(**{**BASE,'length':7,'width':4,'depthMin':depth}))  # recuperación: recargo sobre el total
    assert (r['unitPrice'],r['price'])==(36000*factor,72000*factor)

@pytest.mark.parametrize('depth',[1.6,1.9,2.5])
def test_unloaded_depth_is_not_invented(depth):
    q=calculate(Consultation(**{**BASE,'depthMin':depth}))
    assert q['price'] is None and 'profundidad' in q['reason'].lower() and q['status']=='revision'

def test_average_depth_is_used_for_variable_depth():
    q=calculate(Consultation(**{**BASE,'depthType':'variable','depthMin':1.5,'depthMax':2}))  # promedio 1,75
    assert q['depthMultiplier']==1.25

# --- Aviso al dueño y seguimiento -------------------------------------------------
def configure_notify(client,monkeypatch,ok=True):
    import app.api.routes as routes
    calls=[]
    client.app.state.settings.telegram_bot_token='t';client.app.state.settings.telegram_chat_id='1'
    monkeypatch.setattr(routes,'send_notification',lambda settings,record:calls.append(record) or {'ok':ok,'sent':['telegram'] if ok else [],'failed':[] if ok else ['telegram'],'at':'2026-10-04T12:00:00+00:00'})
    return calls

def test_owner_is_notified_once_even_with_retries(client,monkeypatch):
    calls=configure_notify(client,monkeypatch)
    body=payload()
    first=client.post('/api/requests',json=body).json();again=client.post('/api/requests',json=body).json()
    assert len(calls)==1 and first['notificationSent'] is True and again['notification']['sent']==['telegram']

def test_notification_failure_keeps_request_and_can_be_resent(client,monkeypatch):
    calls=configure_notify(client,monkeypatch,ok=False)
    r=client.post('/api/requests',json=payload());assert r.status_code==201
    assert r.json()['notificationSent'] is False and r.json()['notification']['failed']==['telegram']
    configure_notify(client,monkeypatch,ok=True)
    resent=client.post('/api/admin/requests/'+r.json()['id']+'/notify');assert resent.status_code==200
    assert resent.json()['notificationSent'] is True

def test_no_channel_means_no_notification_and_resend_conflict(client):
    r=client.post('/api/requests',json=payload()).json();assert r['notification'] is None
    assert client.post('/api/admin/requests/'+r['id']+'/notify').status_code==409
    assert client.get('/api/config').json()['notifyChannels']==[]

def test_notification_text_has_what_the_owner_needs():
    from app.services.notify_service import compose
    q=calculate(Consultation(**BASE))
    text=compose({'id':'abc','data':BASE,'quote':q})
    for expected in ['Cliente Prueba','0000000000','La Bolsa','A coordinar','Verde intenso','Recuperación','$72.000','2 limpiezas de $36.000','28 m²']:
        assert expected in text

def test_notify_send_isolates_channel_failures(monkeypatch):
    import app.services.notify_service as ns
    def fake(url,body=None):
        if 'telegram' in url:raise OSError('down')
    monkeypatch.setattr(ns,'_http',fake)
    cfg=Settings(_env_file=None,telegram_bot_token='t',telegram_chat_id='1',notify_webhook_url='https://hook.example/x')
    q=calculate(Consultation(**BASE))
    result=ns.send(cfg,{'id':'abc','data':BASE,'quote':q})
    assert result['ok'] and result['sent']==['webhook'] and result['failed']==['telegram']

def test_outcome_tracking_requires_owner_and_valid_value(client):
    r=client.post('/api/requests',json=payload()).json();url='/api/admin/requests/'+r['id']+'/outcome'
    assert client.patch(url,json={'outcome':'agendado'}).json()['outcome']=='agendado'
    assert client.patch(url,json={'outcome':'sin_gestion'}).json()['outcome'] is None
    assert client.patch(url,json={'outcome':'inventado'}).status_code==422
    assert client.patch('/api/admin/requests/'+str(uuid4())+'/outcome',json={'outcome':'agendado'}).status_code==404
    client.app.state.settings.admin_token='secret'
    assert client.patch(url,json={'outcome':'agendado'}).status_code==401
