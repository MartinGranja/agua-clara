"""Aviso automático al dueño cuando un cliente confirma una consulta (Fase 1: sin Meta Business)."""
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from app.services.pricing_engine import TARIFFS

logger=logging.getLogger('aguaclara.notify')

def channels(settings):
    names=[]
    if settings.owner_whatsapp_phone and settings.callmebot_api_key:names.append('whatsapp')
    if settings.telegram_bot_token and settings.telegram_chat_id:names.append('telegram')
    if settings.notify_webhook_url:names.append('webhook')
    return names

def money(n):return '$'+f'{n:,.0f}'.replace(',','.')

def compose(record):
    d,q=record['data'],record['quote'];dims=q['dimensions']
    lines=['Nueva consulta · Agua Clara','',
        f"Cliente: {d['name']}",f"Teléfono: {d['phone']}",
        f"Localidad: {d['zone']}"+('' if q['status']!='sin_cobertura' else ' (FUERA DE COBERTURA)'),
        f"Día preferido: {d['day']}",'']
    size=f"{dims['length']:g} × {dims['width']:g} m = {dims['area']:g} m²" if dims.get('area') else 'a confirmar'
    if dims.get('depth'):size+=f", prof. {dims['depth']:g} m"
    lines+=[f"Pileta: {size}",
        f"Agua: {TARIFFS['states'].get(d['water'],d['water'])}"+(' con algas en paredes' if d['algae'] else ''),
        f"Servicio: {TARIFFS['services'].get(q['service'],'a evaluar')}"]
    if q['price'] is None:lines.append('Precotización: a confirmar ('+q['reason']+')')
    elif q.get('cleanings',1)>1:lines.append(f"Precotización: {money(q['price'])} total estimado ({q['cleanings']} limpiezas de {money(q['unitPrice'])})")
    else:lines.append('Precotización: '+money(q['price']))
    lines+=['',f"ID: {record['id']}",'Revisá fotos y conversación en el panel de admin.']
    return '\n'.join(lines)

def _http(url,body=None):
    request=urllib.request.Request(url,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'} if body is not None else {})
    with urllib.request.urlopen(request,timeout=8):pass

def send(settings,record):
    text=compose(record);jobs={}
    if 'whatsapp' in channels(settings):
        jobs['whatsapp']=lambda:_http('https://api.callmebot.com/whatsapp.php?'+urllib.parse.urlencode({'phone':settings.owner_whatsapp_phone,'text':text,'apikey':settings.callmebot_api_key}))
    if 'telegram' in channels(settings):
        jobs['telegram']=lambda:_http(f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage',{'chat_id':settings.telegram_chat_id,'text':text})
    if 'webhook' in channels(settings):
        jobs['webhook']=lambda:_http(settings.notify_webhook_url,{'text':text,'request':{k:v for k,v in record.items() if k!='conversation'}})
    sent,failed=[],[]
    for name,job in jobs.items():
        try:job();sent.append(name)
        except Exception as exc:
            # Solo el tipo de error: las URLs contienen claves y el texto, datos del cliente.
            logger.warning('notify_failed channel=%s kind=%s',name,type(exc).__name__);failed.append(name)
    return {'ok':bool(sent),'sent':sent,'failed':failed,'at':datetime.now(timezone.utc).isoformat()}
