import asyncio
import base64
import secrets
import time
from collections import defaultdict,deque
from uuid import UUID,uuid4
from fastapi import APIRouter,Request,UploadFile,File,Header,Depends,HTTPException
from app.schemas import Consultation,CreateRequest,Review,DialogueRequest,Outcome
from app.services.notify_service import channels,send as send_notification
from app.services.dialogue_service import compose
from app.services.pricing_engine import configuration
from app.services.consultation_service import ConsultationService
from app.services.vision_service import prepare_image,analyze,MAX_BYTES,InvalidImage,VisionUnavailable
from app.repositories.store import Conflict
from app.schemas import ClientImport,RoutePlan
from app.services import route_service,client_base

router=APIRouter()

@router.post('/api/dialogue')
async def dialogue(data:DialogueRequest,request:Request):
    if not request.app.state.settings.gemini_api_key:
        raise HTTPException(503,'No pudimos redactar el mensaje.')
    key='dialogue:'+request.client.host;queue=request.app.state.vision_limiter[key];now=time.monotonic()
    while queue and queue[0]<now-3600:queue.popleft()
    if len(queue)>=180:raise HTTPException(429,'Intentá nuevamente más tarde.')
    queue.append(now)
    analysis=request.app.state.store.get_analysis(data.analysisId) if data.analysisId else None
    if data.analysisId and not analysis:raise HTTPException(404,'No se encontró la evaluación.')
    try:return await asyncio.wait_for(asyncio.to_thread(compose,data.step,analysis,request.app.state.settings),18)
    except Exception:raise HTTPException(503,'No pudimos redactar el mensaje.')

def owner(request:Request,authorization:str|None=Header(default=None)):
    settings=request.app.state.settings
    if settings.admin_token:
        if not secrets.compare_digest(authorization or '',f'Bearer {settings.admin_token}'):
            raise HTTPException(401,'Ingresá la clave de acceso al panel.')
    elif request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'El panel requiere autenticación.')

@router.get('/health')
def health(): return {'status':'ok'}

@router.get('/api/config')
def config(request:Request):
    return {**configuration(),'visionAvailable':bool(request.app.state.settings.gemini_api_key),'notifyChannels':channels(request.app.state.settings)}

@router.post('/api/quotes')
def quote(data:Consultation,request:Request):
    try:return ConsultationService(request.app.state.store).quote(data)
    except Conflict as e:raise HTTPException(409,str(e))

@router.post('/api/requests',status_code=201)
def create(data:CreateRequest,request:Request):
    try:record=ConsultationService(request.app.state.store).create(data)
    except Conflict as e:raise HTTPException(409,str(e))
    return notify_owner(request.app.state,record)

def notify_owner(state,record,force=False):
    """Avisa al dueño una sola vez por consulta; un fallo del aviso nunca invalida la consulta guardada."""
    if not channels(state.settings):return record
    claimed=state.store.claim_notification(record['id'],force)
    if not claimed:return state.store.get_request(record['id']) or record
    return state.store.set_notification(record['id'],send_notification(state.settings,claimed))

@router.get('/api/admin/requests',dependencies=[Depends(owner)])
def listing(request:Request): return request.app.state.store.list()

@router.get('/api/admin/requests/{request_id}/details',dependencies=[Depends(owner)])
def details(request_id:UUID,request:Request):
    record=request.app.state.store.get_request(request_id)
    if not record: raise HTTPException(404,'No se encontró la solicitud.')
    analysis=request.app.state.store.get_analysis(record['data'].get('analysisId'))
    return {'photo':analysis.get('photo') if analysis else None,'conversation':record.get('conversation',[])}

@router.patch('/api/admin/requests/{request_id}',dependencies=[Depends(owner)])
def review(request_id:UUID,data:Review,request:Request):
    try:return request.app.state.store.review(str(request_id),data.model_dump())
    except KeyError:raise HTTPException(404,'No se encontró la solicitud.')
    except Conflict as e:raise HTTPException(409,str(e))

@router.post('/api/admin/requests/{request_id}/notify',dependencies=[Depends(owner)])
def renotify(request_id:UUID,request:Request):
    state=request.app.state
    if not channels(state.settings):raise HTTPException(409,'No hay un canal de aviso configurado.')
    if not state.store.get_request(request_id):raise HTTPException(404,'No se encontró la solicitud.')
    return notify_owner(state,{'id':str(request_id)},True)

@router.patch('/api/admin/requests/{request_id}/outcome',dependencies=[Depends(owner)])
def outcome(request_id:UUID,data:Outcome,request:Request):
    try:return request.app.state.store.set_outcome(str(request_id),data.outcome)
    except KeyError:raise HTTPException(404,'No se encontró la solicitud.')

@router.post('/api/analysis')
async def analysis(request:Request,image:UploadFile=File(...)):
    host=request.client.host;now=time.monotonic();limiter=request.app.state.vision_limiter
    queue=limiter[host]
    while queue and queue[0]<now-3600:queue.popleft()
    if len(queue)>=10:raise HTTPException(429,'Se alcanzó el límite de análisis. Intentá nuevamente más tarde.')
    raw=await image.read(MAX_BYTES+1);await image.close()
    try:prepared=await asyncio.to_thread(prepare_image,raw,image.content_type or '')
    except InvalidImage as e:raise HTTPException(422,str(e))
    if not request.app.state.settings.gemini_api_key:
        raise HTTPException(503,'El análisis de fotos no está disponible. Intentá nuevamente más tarde.')
    queue.append(now)
    try:result=await asyncio.wait_for(asyncio.to_thread(analyze,prepared,request.app.state.settings),request.app.state.settings.llm_timeout_seconds+5)
    except (VisionUnavailable,TimeoutError) as e:
        raise HTTPException(503,str(e) or 'El análisis tardó demasiado. Probá nuevamente o cargá otra foto.')
    analysis_id=str(uuid4());body={'id':analysis_id,'result':result.model_dump(),'model':request.app.state.settings.llm_model_name}
    stored={**body,'photo':'data:image/jpeg;base64,'+base64.b64encode(prepared).decode('ascii')}
    await asyncio.to_thread(request.app.state.store.save_analysis,analysis_id,stored)
    return body

# --- Módulo B: recorridos ---
def base_clients(store):
    """Clientes cargados por el dueño; si todavía no cargó ninguno se usa la base de demostración."""
    saved=store.list_clients()
    return (saved,False) if saved else (client_base.demo(),True)

@router.get('/api/admin/clients',dependencies=[Depends(owner)])
def clients(request:Request):
    items,demo=base_clients(request.app.state.store)
    return {'demo':demo,'summary':client_base.summary(items),'clients':items}

@router.put('/api/admin/clients',dependencies=[Depends(owner)])
def import_clients(data:ClientImport,request:Request):
    items,warnings=client_base.read_csv(data.csv)
    if not items:raise HTTPException(422,warnings[0] if warnings else 'No se encontraron clientes en el archivo.')
    request.app.state.store.replace_clients(items,data.replace)
    return {'demo':False,'summary':client_base.summary(request.app.state.store.list_clients()),'imported':len(items),'warnings':warnings}

@router.delete('/api/admin/clients',dependencies=[Depends(owner)])
def reset_clients(request:Request):
    request.app.state.store.replace_clients([],True)
    return {'demo':True}

@router.get('/api/admin/route/suggest',dependencies=[Depends(owner)])
def suggest(request:Request,dia:str):
    items,_=base_clients(request.app.state.store)
    return {'lista':route_service.suggest(items,dia)}

@router.post('/api/admin/route/plan',dependencies=[Depends(owner)])
def plan_route(data:RoutePlan,request:Request):
    if not data.lista.strip():raise HTTPException(422,'Pegá la lista del día.')
    items,demo=base_clients(request.app.state.store)
    result=route_service.plan(data.lista,items,data.inicio,data.servicio,data.fecha,data.traslado,data.equipos)
    result['baseDemo']=demo
    if not result['resumen']['paradas'] and not result['pendientes']:raise HTTPException(422,'No se reconoció ninguna parada en la lista.')
    if data.guardar:
        saved=request.app.state.store.save_route(str(uuid4()),{**result,'lista':data.lista})
        result['id']=saved['id']
    return result

@router.get('/api/admin/routes',dependencies=[Depends(owner)])
def routes_listing(request:Request):return request.app.state.store.list_routes()

@router.get('/api/admin/routes/{route_id}',dependencies=[Depends(owner)])
def route_detail(route_id:UUID,request:Request):
    record=request.app.state.store.get_route(route_id)
    if not record:raise HTTPException(404,'No se encontró el recorrido.')
    return record
