import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Text, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

class Base(DeclarativeBase):
    pass

class RequestRow(Base):
    __tablename__='requests'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)

class AnalysisRow(Base):
    __tablename__='analyses'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    body: Mapped[str] = mapped_column(Text)

class ClientRow(Base):
    __tablename__='clients'
    id: Mapped[str] = mapped_column(String(80),primary_key=True)
    body: Mapped[str] = mapped_column(Text)

class RouteRow(Base):
    __tablename__='routes'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    body: Mapped[str] = mapped_column(Text)

class Conflict(Exception):
    pass

class Store:
    def __init__(self,url):
        if url.startswith('postgres://'):
            url=url.replace('postgres://','postgresql+psycopg://',1)
        elif url.startswith('postgresql://'):
            url=url.replace('postgresql://','postgresql+psycopg://',1)
        if url.startswith('sqlite:///') and ':memory:' not in url:
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True,exist_ok=True)
        options={'connect_args':{'check_same_thread':False}} if url.startswith('sqlite:') else {'poolclass':NullPool,'connect_args':{'connect_timeout':10}}
        self.engine=create_engine(url,**options)
        Base.metadata.create_all(self.engine)

    def create(self,request_id,data,quote,conversation=None):
        raw=json.dumps(data,sort_keys=True,ensure_ascii=False)
        digest=hashlib.sha256(raw.encode()).hexdigest()
        record={'id':request_id,'createdAt':datetime.now(timezone.utc).isoformat(),'state':'pending','data':data,'quote':quote,'conversation':conversation or [],'review':None,'outcome':None,'notification':None,'notificationSent':False,'appointmentConfirmed':False}
        with Session(self.engine) as db:
            old=db.get(RequestRow,request_id)
            if old:
                if old.digest!=digest: raise Conflict('El identificador corresponde a otra consulta. Iniciá una nueva.')
                return json.loads(old.body)
            db.add(RequestRow(id=request_id,digest=digest,body=json.dumps(record,ensure_ascii=False)))
            try: db.commit()
            except IntegrityError:
                db.rollback()
                old=db.get(RequestRow,request_id)
                if not old or old.digest!=digest: raise Conflict('El identificador corresponde a otra consulta.')
                return json.loads(old.body)
        return record

    def list(self):
        with Session(self.engine) as db:
            return sorted([json.loads(r.body) for r in db.scalars(select(RequestRow))],key=lambda r:r['createdAt'])

    def get_request(self,request_id):
        with Session(self.engine) as db:
            row=db.get(RequestRow,str(request_id))
            return json.loads(row.body) if row else None

    def review(self,request_id,review):
        with Session(self.engine) as db:
            row=db.get(RequestRow,request_id)
            if not row: raise KeyError(request_id)
            record=json.loads(row.body)
            if record['quote']['status']=='sin_cobertura' and review['price'] is not None:
                raise Conflict('No se admite un importe fuera de cobertura.')
            record.update(state='reviewed',review={**review,'at':datetime.now(timezone.utc).isoformat()})
            row.body=json.dumps(record,ensure_ascii=False); db.commit()
            return record

    def save_analysis(self,analysis_id,body):
        with Session(self.engine) as db:
            db.add(AnalysisRow(id=analysis_id,body=json.dumps(body,ensure_ascii=False)));db.commit()

    def get_analysis(self,analysis_id):
        with Session(self.engine) as db:
            row=db.get(AnalysisRow,str(analysis_id))
            return json.loads(row.body) if row else None

    def _save(self,db,request_id,record):
        row=db.get(RequestRow,request_id);row.body=json.dumps(record,ensure_ascii=False);db.commit();return record

    def claim_notification(self,request_id,force=False):
        """Reserva el envío del aviso de forma atómica para no avisar dos veces por reintentos concurrentes."""
        with Session(self.engine) as db:
            row=db.get(RequestRow,str(request_id))
            if not row: return None
            record=json.loads(row.body)
            if record.get('notification') and not force: return None
            old=row.body
            record['notification']={'ok':False,'status':'enviando','at':datetime.now(timezone.utc).isoformat()}
            claimed=db.execute(update(RequestRow).where(RequestRow.id==str(request_id),RequestRow.body==old).values(body=json.dumps(record,ensure_ascii=False))).rowcount==1
            db.commit()
            return record if claimed else None

    def set_notification(self,request_id,result):
        with Session(self.engine) as db:
            row=db.get(RequestRow,str(request_id))
            if not row: raise KeyError(request_id)
            record=json.loads(row.body);record.update(notification=result,notificationSent=bool(result.get('ok')))
            return self._save(db,str(request_id),record)

    def set_outcome(self,request_id,outcome):
        with Session(self.engine) as db:
            row=db.get(RequestRow,str(request_id))
            if not row: raise KeyError(request_id)
            record=json.loads(row.body);record['outcome']=None if outcome=='sin_gestion' else outcome
            return self._save(db,str(request_id),record)

    # --- Módulo B: base de clientes y recorridos guardados ---
    def replace_clients(self,clients,replace=True):
        with Session(self.engine) as db:
            if replace:
                for row in db.scalars(select(ClientRow)):db.delete(row)
                db.flush()
            for c in clients:
                row=db.get(ClientRow,c['id'])
                if row:row.body=json.dumps(c,ensure_ascii=False)
                else:db.add(ClientRow(id=c['id'],body=json.dumps(c,ensure_ascii=False)))
            db.commit()
        return len(clients)

    def list_clients(self):
        with Session(self.engine) as db:
            return sorted([json.loads(r.body) for r in db.scalars(select(ClientRow))],key=lambda c:c['name'].lower())

    def save_route(self,route_id,body):
        record={'id':route_id,'createdAt':datetime.now(timezone.utc).isoformat(),**body}
        with Session(self.engine) as db:
            db.add(RouteRow(id=route_id,body=json.dumps(record,ensure_ascii=False)));db.commit()
        return record

    def list_routes(self):
        with Session(self.engine) as db:
            rows=sorted([json.loads(r.body) for r in db.scalars(select(RouteRow))],key=lambda r:r['createdAt'],reverse=True)
        return [{'id':r['id'],'createdAt':r['createdAt'],'dia':r.get('dia'),'fecha':r.get('fecha'),'resumen':r.get('resumen')} for r in rows]

    def get_route(self,route_id):
        with Session(self.engine) as db:
            row=db.get(RouteRow,str(route_id))
            return json.loads(row.body) if row else None
