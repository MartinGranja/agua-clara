import logging
import os
from collections import defaultdict,deque
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings,Settings,ROOT
from app.repositories.store import Store
from app.api.routes import router

logger=logging.getLogger('aguaclara')

def create_app(config:Settings|None=None):
    config=config or settings
    if config.allow_remote and not config.admin_token:
        raise RuntimeError('ADMIN_TOKEN es obligatorio para acceso remoto.')
    url=config.database_url
    if os.environ.get('VERCEL')=='1':
        if not config.admin_token or not config.allow_remote:
            raise RuntimeError('Vercel requiere ADMIN_TOKEN y ALLOW_REMOTE=true.')
        if not url.startswith(('postgres://','postgresql://','postgresql+psycopg://')):
            raise RuntimeError('Vercel requiere DATABASE_URL de PostgreSQL persistente.')
    if url.startswith('sqlite:///./'):
        url='sqlite:///'+str(ROOT/url.removeprefix('sqlite:///./'))
    app=FastAPI(title='Agua Clara',version='0.2.0')
    app.state.settings=config;app.state.store=Store(url);app.state.vision_limiter=defaultdict(deque)

    @app.middleware('http')
    async def boundaries(request:Request,call_next):
        if not config.allow_remote and request.client.host not in ('127.0.0.1','::1','testclient'):
            return JSONResponse({'detail':'Acceso restringido a esta computadora.'},403)
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'Origen no permitido.'},403)
        if request.headers.get('content-length','').isdigit() and int(request.headers['content-length'])>11*1024*1024:
            return JSONResponse({'detail':'El archivo supera el tamaño permitido.'},413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        # Exclude rejected raw input, which may contain customer data.
        return JSONResponse({'detail':[{'loc':list(e['loc']),'msg':e['msg']} for e in exc.errors()]},422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request,exc):
        logger.error('database_failed kind=%s',type(exc).__name__)
        return JSONResponse({'detail':'No pudimos guardar los datos. Reintentá en un momento.'},503)

    app.include_router(router)
    app.mount('/',StaticFiles(directory=ROOT/'src',html=True),name='frontend')
    return app

app=create_app()
