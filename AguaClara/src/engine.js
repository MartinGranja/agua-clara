/* Validaciones de entrada. El precio se calcula exclusivamente en Python. */
const PricingEngine = (() => {
  const config = typeof AC_CONFIG !== 'undefined' ? AC_CONFIG : require('./tarifas.js');
  function number(value, label, max) {
    const text = String(value ?? '').trim();
    if (!/^\d+(?:[.,]\d+)?$/.test(text)) throw new Error(`${label}: ingresá un número válido en metros.`);
    const n = Number(text.replace(',', '.'));
    if (!Number.isFinite(n) || n <= 0 || n > max) throw new Error(`${label}: debe ser mayor que 0 y hasta ${max} m.`);
    return n;
  }
  function dimensions(d) {
    if (!['rectangular','otra'].includes(d.shape)) throw new Error('Elegí la forma de la pileta.');
    if (d.shape === 'otra') return {area:null,volume:null,depth:null,source:'no_disponible'};
    if (d.unknown) return {area:null,volume:null,depth:null,source:'no_disponible'};
    const length = number(d.length,'Largo',50), width = number(d.width,'Ancho',50);
    if (d.unknownDepth) return {length,width,area:length*width,volume:null,depth:null,source:'declarada_usuario'};
    if (!['uniforme','variable'].includes(d.depthType)) throw new Error('Elegí el tipo de profundidad.');
    const min = number(d.depthMin,'Profundidad',5);
    const max = d.depthType === 'variable' ? number(d.depthMax,'Profundidad máxima',5) : min;
    if (min > max) throw new Error('La profundidad mínima no puede superar la máxima.');
    const depth = (min+max)/2;
    // No redondear la superficie antes del lookup: un redondeo puede cruzar un límite.
    return {length,width,min,max,depth,area:length*width,volume:length*width*depth,source:'declarada_usuario'};
  }
  function classify(state, algae) {
    if (!Object.hasOwn(config.states,state)) throw new Error('Elegí un estado de agua válido.');
    if (typeof algae !== 'boolean') throw new Error('Indicá si hay algas en las paredes.');
    if (state === 'desconocido') return null;
    if (state.startsWith('verde_')) return 'recuperacion';
    return state === 'turbia' || algae ? 'limpieza_total' : 'mantenimiento';
  }
  function contact(d) {
    if (!d.name || d.name.trim().length<2 || d.name.trim().length>80) throw new Error('Ingresá un nombre de entre 2 y 80 caracteres.');
    if (!/^\+?[\d\s()-]+$/.test(d.phone || '') || !/^\d{10,15}$/.test(d.phone.replace(/\D/g,''))) throw new Error('Ingresá un teléfono de 10 a 15 dígitos, con código de área.');
    if (!['A coordinar','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'].includes(d.day)) throw new Error('Elegí una preferencia de día.');
    return true;
  }
  return {number,dimensions,classify,contact};
})();
if (typeof module !== 'undefined') module.exports = PricingEngine;
