from datetime import date
from typing import Literal
import re
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Water = Literal['cristalina','levemente_turbia','turbia','verde_leve','verde_intenso','verde_oscuro_opaco','desconocido']

class Consultation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    shape: Literal['rectangular','otra'] = 'rectangular'
    poolShape: Literal['rectangular','cuadrada','circular','ovalada','en_l','rinon','irregular'] | None = None
    unknown: bool = False
    unknownDepth: bool = False
    length: float | None = Field(default=None, gt=0, le=50, allow_inf_nan=False)
    width: float | None = Field(default=None, gt=0, le=50, allow_inf_nan=False)
    depthType: Literal['uniforme','variable'] | None = None
    depthMin: float | None = Field(default=None, gt=0, le=5, allow_inf_nan=False)
    depthMax: float | None = Field(default=None, gt=0, le=5, allow_inf_nan=False)
    water: Water
    algae: bool
    zone: str = Field(min_length=3,max_length=80)
    name: str = Field(min_length=2,max_length=80)
    phone: str = Field(min_length=10,max_length=30)
    day: Literal['A coordinar','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado']
    photoName: str | None = Field(default=None,max_length=255)
    photoOrigin: Literal['camera_requested','file','example'] | None = None
    analysisId: UUID | None = None
    measurementsConfirmed: bool = False
    lastTreatment: Literal['menos_4','mas_4','no_se'] | None = None   # tiempo sin limpieza ni productos (solo se pregunta con agua verde)

    @field_validator('name','zone','phone',mode='before')
    @classmethod
    def trim(cls,v):
        return v.strip() if isinstance(v,str) else v

    @field_validator('phone')
    @classmethod
    def phone_format(cls,v):
        if not re.fullmatch(r'\+?[\d\s()-]+',v) or not 10<=len(re.sub(r'\D','',v))<=15:
            raise ValueError('Ingresá un teléfono de 10 a 15 dígitos.')
        return v

    @model_validator(mode='after')
    def measures(self):
        if self.shape=='rectangular' and not self.unknown:
            if self.length is None or self.width is None:
                raise ValueError('Faltan largo y ancho.')
            if not self.unknownDepth:
                if self.depthType is None or self.depthMin is None:
                    raise ValueError('Falta la profundidad.')
                if self.depthType=='variable' and (self.depthMax is None or self.depthMax<self.depthMin):
                    raise ValueError('Profundidad máxima debe ser mayor o igual a la mínima.')
        return self

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user','assistant']
    text: str = Field(max_length=12000)
    at: str = Field(max_length=40)
    image: bool = False

class CreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: UUID
    data: Consultation
    conversation: list[ChatMessage] = Field(default_factory=list,max_length=500)

class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    price: int | None = Field(default=None,gt=0,le=10000000)
    note: str = Field(min_length=5,max_length=500)

    @field_validator('note',mode='before')
    @classmethod
    def strip_note(cls,v):
        return v.strip() if isinstance(v,str) else v

class Outcome(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: Literal['sin_gestion','contactado','agendado','descartado']

class Analysis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    es_pileta: bool
    estado_agua: Water
    presencia_algas_paredes: bool
    tipo_pileta: Literal['rectangular','cuadrada','circular','ovalada','en_l','rinon','irregular','otra','indeterminado']
    problemas_visibles: list[str] = Field(max_length=8)
    observaciones: str = Field(min_length=1,max_length=500)
    confianza: float = Field(ge=0,le=1,allow_inf_nan=False)
    # Rasgos adicionales (análisis de datos): permiten graduar el servicio y explicar la decisión.
    indice_turbidez: int = Field(default=0,ge=0,le=100)       # 0 = fondo nítido, 100 = totalmente opaca
    intensidad_verde: int = Field(default=0,ge=0,le=100)      # 0 = sin tinte verde, 100 = verde oscuro
    calidad_foto: Literal['buena','regular','mala'] = 'buena'
    superficie_visible_pct: int = Field(default=100,ge=0,le=100)  # cuánta superficie de la pileta se ve
    hojas_o_residuos: bool = False
    evidencia: str = Field(default='',max_length=300)          # qué se ve que sustenta el estado del agua

class DialogueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    step: Literal['photo','size','depthType','depth','depthMin','depthMax','treatment','zone','name','phone','day']
    analysisId: UUID | None = None

class DialogueReply(BaseModel):
    message: str = Field(min_length=1,max_length=700)

class ClientImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    csv: str = Field(min_length=1,max_length=400000)
    replace: bool = True

class RoutePlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lista: str = Field(max_length=8000)
    fecha: date | None = None
    equipos: int = Field(2,ge=1,le=2)
    inicio: str = Field('08:30',pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    servicio: int = Field(30,ge=5,le=120)
    traslado: bool = False
    guardar: bool = False
    optimizar: bool = True
    origen: str = Field('',max_length=300)


class Understanding(BaseModel):
    """Lo que el modelo entiende de un mensaje libre del cliente. Todo se valida de nuevo en el servidor."""
    model_config = ConfigDict(extra='ignore')
    intencion: Literal['datos','pregunta','correccion','saludo','otro'] = 'datos'
    largo: float | None = None
    ancho: float | None = None
    profundidad_tipo: Literal['uniforme','variable'] | None = None
    profundidad_min: float | None = None
    profundidad_max: float | None = None
    localidad: str | None = Field(default=None,max_length=80)
    nombre: str | None = Field(default=None,max_length=80)
    telefono: str | None = Field(default=None,max_length=40)
    dia: str | None = Field(default=None,max_length=20)
    respuesta: str | None = Field(default=None,max_length=600)

class UnderstandRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=500)
    step: Literal['photo','size','depthType','depth','depthMin','depthMax','zone','name','phone','day','measuresReview','review','done']
    shape: str | None = Field(default=None,max_length=20)
    analysisId: UUID | None = None

class ValidationLabel(BaseModel):
    """Verdad de terreno cargada por el dueño: sirve para medir el acierto real de la IA."""
    model_config = ConfigDict(extra='forbid')
    service: Literal['mantenimiento','recuperacion','limpieza_total'] | None = None
    water: Water | None = None
    algae: bool | None = None
    shape: Literal['rectangular','cuadrada','circular','ovalada','en_l','rinon','irregular','indeterminado'] = 'indeterminado'
    note: str = Field(default='',max_length=300)

    @model_validator(mode='after')
    def needs_label(self):
        if self.service is None and self.water is None: raise ValueError('Indicá el servicio real o el estado real del agua.')
        return self

class RouteReal(BaseModel):
    """Resultado real de un recorrido ya hecho: se compara contra lo estimado."""
    model_config = ConfigDict(extra='forbid')
    kmReal: float = Field(gt=0,le=1000,allow_inf_nan=False)
    finReal: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    nota: str = Field(default='',max_length=300)
