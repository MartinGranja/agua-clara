from app.services.pricing_engine import calculate,SHAPES
from app.repositories.store import Conflict

class ConsultationService:
    def __init__(self,store): self.store=store

    def resolve(self,data):
        """Completa la forma concreta (circular, ovalada…) con la que detectó el análisis de la foto."""
        if data.shape!='otra' or data.poolShape or not data.analysisId: return data
        analysis=self.store.get_analysis(data.analysisId)
        shape=(analysis or {}).get('result',{}).get('tipo_pileta')
        return data.model_copy(update={'poolShape':shape}) if shape in SHAPES else data

    def quote(self,data):
        if (not data.measurementsConfirmed or data.unknown or data.unknownDepth
            or data.length is None or data.width is None or data.depthMin is None
            or data.depthType is None or (data.depthType=='variable' and
                (data.depthMax is None or data.depthMax<data.depthMin))):
            raise Conflict('Necesitamos largo, ancho y profundidad, y tu confirmación de esas medidas.')
        if not data.analysisId:
            raise Conflict('Necesitamos analizar una foto de la pileta antes de precotizar.')
        data=self.resolve(data)
        quote=calculate(data)
        analysis=self.store.get_analysis(data.analysisId)
        if not analysis: raise Conflict('El análisis asociado no existe. Volvé a adjuntar la foto.')
        result=analysis['result']
        detected_shape='rectangular' if result.get('tipo_pileta') in ('rectangular','cuadrada') else 'otra'
        if data.shape!=detected_shape or (data.poolShape and data.poolShape!=result.get('tipo_pileta')):
            raise Conflict('La forma debe coincidir con la evaluación de la foto. Volvé a analizarla.')
        if result['es_pileta'] and result['confianza']>=0.65 and result['estado_agua']!='desconocido':
            if data.water==result['estado_agua'] and data.algae==result['presencia_algas_paredes']:
                quote['classificationSource']='gemini'
                quote['analysisModel']=analysis['model']
        if quote['classificationSource'] != 'gemini':
            raise Conflict('La evaluación de la foto no es válida o fue modificada. Volvé a analizar la foto.')
        quote.update(certainty_of(quote,analysis))
        return quote

    def create(self,request):
        data=self.resolve(request.data)
        return self.store.create(str(request.requestId),data.model_dump(mode='json'),self.quote(data),[m.model_dump() for m in request.conversation])

def certainty_of(quote,analysis):
    """Nivel de certeza del importe (alta / media / baja) según la confianza del análisis, el acuerdo entre lecturas y la forma."""
    result,meta=analysis['result'],analysis.get('meta') or {}
    summary={'confianza':result['confianza'],'calidadFoto':result.get('calidad_foto'),'indiceTurbidez':result.get('indice_turbidez'),'intensidadVerde':result.get('intensidad_verde'),
             'acuerdoModelo':meta.get('acuerdoModelo'),'acuerdoCV':meta.get('acuerdoCV'),'muestras':meta.get('muestras'),'estadoCV':(meta.get('cv') or {}).get('estado_agua')}
    if quote['price'] is None: return {'certainty':None,'certaintyReasons':meta.get('motivos',[]),'analysisSummary':summary}
    score=result['confianza']*(0.9 if quote.get('approximate') else 1)*(0.85 if meta.get('revisionSugerida') else 1)
    reasons=list(meta.get('motivos',[]))
    if quote.get('approximate'): reasons.append('La superficie se aproximó por la forma de la pileta.')
    return {'certainty':'alta' if score>=0.8 else 'media' if score>=0.6 else 'baja','certaintyReasons':reasons,'analysisSummary':summary}
