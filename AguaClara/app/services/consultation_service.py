from app.services.pricing_engine import calculate
from app.repositories.store import Conflict

class ConsultationService:
    def __init__(self,store): self.store=store

    def quote(self,data):
        if (not data.measurementsConfirmed or data.unknown or data.unknownDepth
            or data.length is None or data.width is None or data.depthMin is None
            or data.depthType is None or (data.depthType=='variable' and
                (data.depthMax is None or data.depthMax<data.depthMin))):
            raise Conflict('Necesitamos largo, ancho y profundidad, y tu confirmación de esas medidas.')
        if not data.analysisId:
            raise Conflict('Necesitamos analizar una foto de la pileta antes de precotizar.')
        quote=calculate(data)
        if data.analysisId:
            analysis=self.store.get_analysis(data.analysisId)
            if not analysis: raise Conflict('El análisis asociado no existe. Volvé a adjuntar la foto.')
            result=analysis['result']
            detected_shape='rectangular' if result.get('tipo_pileta') in ('rectangular','cuadrada') else 'otra'
            if data.shape!=detected_shape:
                raise Conflict('La forma debe coincidir con la evaluación de la foto. Volvé a analizarla.')
            if result['es_pileta'] and result['confianza']>=0.65 and result['estado_agua']!='desconocido':
                if data.water==result['estado_agua'] and data.algae==result['presencia_algas_paredes']:
                    quote['classificationSource']='gemini'
                    quote['analysisModel']=analysis['model']
            if quote['classificationSource'] != 'gemini':
                raise Conflict('La evaluación de la foto no es válida o fue modificada. Volvé a analizar la foto.')
        return quote

    def create(self,request):
        return self.store.create(str(request.requestId),request.data.model_dump(mode='json'),self.quote(request.data),[m.model_dump() for m in request.conversation])
