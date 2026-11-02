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
    service=None if d.water=='desconocido' else 'recuperacion' if d.water.startswith('verde_') else 'limpieza_total' if d.water=='turbia' or d.algae else 'mantenimiento'
    q={'dimensions':dimensions,'service':service,'price':None,'unitPrice':None,'cleanings':None,'depthMultiplier':None,'currency':'ARS','tariffVersion':TARIFFS['version'],'classificationSource':'declarada_usuario','status':'revision','ranges':[],'priceRange':None,'approximate':approximate}
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
        if len(matches)!=1:
            result={**q,'ranges':matches,'reason':'La superficie coincide con dos tramos; requiere revisión.' if matches else 'La superficie no tiene un tramo cargado. Importe a confirmar.'}
        else:
            result=priced({**q,'ranges':matches},service,Decimal(str(matches[0]['price'])),depth,reason='Precotización sujeta a revisión del prestador.')
    return with_range(result,service,area,depth,approximate)


def unit_price(service,area):
    """Precio por limpieza del tramo que corresponde a `area` (sin recargo de profundidad); None si cae entre tramos o en un límite."""
    maximum=Decimal(str(TARIFFS['ranges'][-1][1]))
    if area>maximum:
        base=Decimal(str(TARIFFS['prices'][service][-1]))
        return base+(area-maximum)*(base/maximum)
    matches=[TARIFFS['prices'][service][i] for i,(lo,hi) in enumerate(TARIFFS['ranges']) if Decimal(lo)<=area<=Decimal(hi)]
    return Decimal(str(matches[0])) if len(matches)==1 else None


def _total(service,unit,factor):
    return float((((unit*factor).quantize(CENT,rounding=ROUND_HALF_UP))*TARIFFS['cleanings'][service]).quantize(CENT,rounding=ROUND_HALF_UP))


def with_range(q,service,area,depth,approximate):
    """Rango de precio por sensibilidad: ±error relativo de la superficie (más ancho si la forma es aproximada).
    Si la superficie cae entre dos tramos, el rango va del tramo inferior al superior, a confirmar."""
    factor=depth_multiplier(depth)
    if factor is None or q['status']=='sin_cobertura':
        return q
    if q['price'] is None:
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
