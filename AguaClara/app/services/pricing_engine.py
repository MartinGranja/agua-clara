from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import yaml

from app.schemas import Consultation

DATA = Path(__file__).resolve().parents[1] / 'data'
TARIFFS = yaml.safe_load((DATA/'tarifas.yaml').read_text(encoding='utf-8'))
ZONES = yaml.safe_load((DATA/'zonas_cobertura.yaml').read_text(encoding='utf-8'))['zones']
SHAPES = TARIFFS['shapes']
CENT = Decimal('0.01')


def configuration():
    return {**TARIFFS,'zones':ZONES}


def _depth(dimensions,d,area):
    if d.unknownDepth: return
    depth_min=Decimal(str(d.depthMin))
    depth_max=Decimal(str(d.depthMax)) if d.depthType=='variable' else depth_min
    depth=(depth_min+depth_max)/2
    dimensions.update(depth=float(depth),min=float(depth_min),max=float(depth_max),volume=float(area*depth))


def needs_bottom(water, algae):
    """¿Corresponde preguntar si se ve el fondo? Solo cuando la foto dice «tratamiento» pero el agua es dudosa
    (cristalina con algas, levemente turbia o verde leve). Con verde intenso u oscuro o turbia no se pregunta."""
    return water in ('cristalina','levemente_turbia','verde_leve') and (algae or water in ('levemente_turbia','verde_leve'))


def service_for(water, algae, last_treatment=None, bottom_visible=None):
    """Servicio que corresponde. Regla de Agua Clara:
    - agua dudosa (ver needs_bottom) y el cliente dice que el fondo se ve claramente: mantenimiento.
    - agua verde: si pasaron más de 4 meses sin limpieza ni productos, limpieza total; si no, recuperación.
      Sin esa respuesta se decide por la foto: verde oscuro y opaco = limpieza total; el resto del verde = recuperación.
    - agua no verde: turbia o con algas = limpieza total; si no, mantenimiento.
    Devuelve (servicio, base) con base 'foto', 'foto+tiempo', 'foto+fondo' o 'foto_sin_confirmar' (verde sin respuesta confirmada)."""
    if water in (None,'desconocido'): return None,'foto'
    if bottom_visible=='si' and needs_bottom(water,algae): return 'mantenimiento','foto+fondo'
    if water.startswith('verde_'):
        if last_treatment=='mas_4': return 'limpieza_total','foto+tiempo'
        if last_treatment=='menos_4': return 'recuperacion','foto+tiempo'
        return ('limpieza_total' if water=='verde_oscuro_opaco' else 'recuperacion'),'foto_sin_confirmar'
    return ('limpieza_total' if water=='turbia' or algae else 'mantenimiento'),'foto'


def calculate(d: Consultation) -> dict:
    dimensions={'area':None,'volume':None,'depth':None,'source':'no_disponible'}
    if d.shape=='rectangular' and not d.unknown:
        length,width=Decimal(str(d.length)),Decimal(str(d.width))
        area=length*width
        dimensions.update(length=d.length,width=d.width,area=float(area),source='declarada_usuario')
        _depth(dimensions,d,area)
    elif d.shape=='otra' and d.poolShape in SHAPES and not d.unknown and d.length and d.width:
        # Forma no rectangular: superficie aproximada = largo × ancho máximos × factor de la forma.
        factor=Decimal(str(SHAPES[d.poolShape]['factor']))
        length,width=Decimal(str(d.length)),Decimal(str(d.width))
        area=length*width*factor
        dimensions.update(length=d.length,width=d.width,area=float(area),source='aproximada_por_forma',shape=d.poolShape,shapeFactor=float(factor))
        _depth(dimensions,d,area)
    approximate=dimensions['source']=='aproximada_por_forma'
    service,service_basis=service_for(d.water,d.algae,d.lastTreatment,d.bottomVisible)
    q={'dimensions':dimensions,'service':service,'price':None,'unitPrice':None,'cleanings':None,'depthMultiplier':None,'currency':'ARS','tariffVersion':TARIFFS['version'],'classificationSource':'declarada_usuario','status':'revision','ranges':[],'priceRange':None,'approximate':approximate,'serviceBasis':service_basis,'lastTreatment':d.lastTreatment,'bottomVisible':d.bottomVisible}
    if d.zone not in ZONES:
        return {**q,'status':'sin_cobertura','reason':'Localidad fuera de la cobertura confirmada. Se requiere revisión.'}
    if not service:
        return {**q,'reason':'El estado del agua requiere revisión.'}
    if dimensions['area'] is None:
        return {**q,'reason':'Se necesitan medidas y forma confirmadas para seleccionar un tramo.'}
    if dimensions['depth'] is None:
        return {**q,'reason':'Falta la profundidad promedio para calcular el importe.'}
    depth=Decimal(str(dimensions['depth']))
    maximum=Decimal(str(TARIFFS['ranges'][-1][1]))
    if area > maximum:
        base=Decimal(str(TARIFFS['prices'][service][-1]))
        extra=area-maximum
        result=priced(q,service,base+extra*(base/maximum),depth,
                calculation={'baseArea':float(maximum),'basePrice':float(base),'extraArea':float(extra),'pricePerExtraM2':float(base/maximum)},
                reason='Tarifa de 60 m² más los metros adicionales al valor proporcional por m².')
    else:
        # Decimal preserves exact boundaries; no rounding into an adjacent tariff.
        matches=[{'min':lo,'max':hi,'price':TARIFFS['prices'][service][i]} for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(lo)<=area<=Decimal(hi)]
        if len(matches)==2: matches=matches[1:]   # justo en el límite de dos tramos (40 o 54 m²): se usa el tramo de arriba
        gap=gap_unit(service,area) if not matches else None
        if gap is not None:
            result=priced({**q,'ranges':[],'gap':True},service,gap,depth,reason='Superficie entre dos tramos de la tabla: precio promedio de los tramos vecinos, a confirmar en la visita.')
        elif len(matches)!=1:
            result={**q,'ranges':matches,'reason':'La superficie coincide con dos tramos; requiere revisión.' if matches else 'La superficie no tiene un tramo cargado. Importe a confirmar.'}
        else:
            result=priced({**q,'ranges':matches},service,Decimal(str(matches[0]['price'])),depth,reason='Precotización sujeta a revisión del prestador.')
    return with_range(result,service,area,depth,approximate)


def gap_unit(service,area):
    """Superficie entre dos tramos cargados (p. ej. 21 a 28 m²): promedio de los precios de los tramos vecinos. None si no corresponde."""
    if any(Decimal(lo)<=area<=Decimal(hi) for lo,hi in TARIFFS['ranges']): return None
    lower=[i for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(hi)<area]
    upper=[i for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(lo)>area]
    if not lower or not upper: return None
    return (Decimal(str(TARIFFS['prices'][service][lower[-1]]))+Decimal(str(TARIFFS['prices'][service][upper[0]])))/2


def unit_price(service,area):
    """Precio por limpieza del tramo que corresponde a `area` (sin recargo de profundidad); None si cae entre tramos o en un límite."""
    maximum=Decimal(str(TARIFFS['ranges'][-1][1]))
    if area>maximum:
        base=Decimal(str(TARIFFS['prices'][service][-1]))
        return base+(area-maximum)*(base/maximum)
    matches=[TARIFFS['prices'][service][i] for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(lo)<=area<=Decimal(hi)]
    if not matches: return gap_unit(service,area)
    return Decimal(str(matches[-1]))   # en el límite de dos tramos se usa el de arriba


def _total(service,unit,factor):
    return float((((unit*factor).quantize(CENT,rounding=ROUND_HALF_UP))*TARIFFS['cleanings'][service]).quantize(CENT,rounding=ROUND_HALF_UP))


def with_range(q,service,area,depth,approximate):
    """Rango de precio por sensibilidad: ±error relativo de la superficie (más ancho si la forma es aproximada).
    Si la superficie cae entre dos tramos, el rango va del tramo inferior al superior, a confirmar."""
    factor=depth_multiplier(depth)
    if factor is None or q['status']=='sin_cobertura':
        return q
    if q['price'] is None or q.get('gap'):
        # Sin precio fijo (entre tramos o en el límite de dos): se orienta con los precios de los tramos vecinos.
        if len(q['ranges'])==2:
            units=[Decimal(str(m['price'])) for m in q['ranges']]
        else:
            lower=[i for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(hi)<area]
            upper=[i for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(lo)>area]
            if not lower or not upper: return q
            units=[Decimal(str(TARIFFS['prices'][service][lower[-1]])),Decimal(str(TARIFFS['prices'][service][upper[0]]))]
        totals=[_total(service,u,factor) for u in units]
        return {**q,'priceRange':{'min':min(totals),'max':max(totals),'basis':'tramos vecinos a la superficie calculada'}}
    error=Decimal(str(TARIFFS['sensitivity']['approximate' if approximate else 'exact']))
    prices=[]
    for a in (area*(1-error),area,area*(1+error)):
        u=unit_price(service,a)
        if u is not None: prices.append(_total(service,u,factor))
    if not prices:
        return q
    basis=f"±{int(error*100)} % de superficie"+(' (forma aproximada)' if approximate else '')
    return {**q,'priceRange':{'min':min(prices),'max':max(prices),'basis':basis}}


def depth_multiplier(depth: Decimal):
    """1,00 hasta la profundidad estándar; luego solo los multiplicadores cargados. None = a confirmar."""
    if depth<=Decimal(str(TARIFFS['depth']['standard_max'])): return Decimal('1')
    for value,factor in TARIFFS['depth']['multipliers']:
        if depth==Decimal(str(value)): return Decimal(str(factor))
    return None

def priced(q,service,unit,depth,reason,**extra):
    """price = total a informar al cliente = precio por limpieza x recargo de profundidad x cantidad de limpiezas."""
    factor=depth_multiplier(depth)
    if factor is None:
        return {**q,**extra,'reason':'La profundidad promedio no tiene un recargo cargado. Importe a confirmar.'}
    cleanings=TARIFFS['cleanings'][service]
    cents=Decimal('0.01')
    unit=(unit*factor).quantize(cents,rounding=ROUND_HALF_UP)
    total=(unit*cleanings).quantize(cents,rounding=ROUND_HALF_UP)
    if cleanings>1: reason=f'Total estimado de {cleanings} limpiezas. Sujeto a revisión del prestador.'
    if q.get('approximate'): reason='Superficie aproximada según la forma de la pileta (largo × ancho × '+str(q['dimensions']['shapeFactor']).replace('.',',')+'). '+reason+' La forma se confirma en la visita.'
    return {**q,**extra,'price':float(total),'unitPrice':float(unit),'cleanings':cleanings,'depthMultiplier':float(factor),'status':'estimada','reason':reason}
