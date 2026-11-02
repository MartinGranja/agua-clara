'use strict';
/* Simulador de WhatsApp de Agua Clara (no envía mensajes reales).
   Diálogo por estados + comprensión de texto libre (/api/understand: Gemini y reglas, siempre re-validado en el servidor).
   El backend analiza la foto (lecturas múltiples + visión clásica), valida y precotiza; el precio sale solo de la tabla de tarifas. */
(() => {
  const {$,num,money} = UI;
  const normalize = text => text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim();
  const days=['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','A coordinar'];
  let state='photo',data={},photoUrl='',savedId=null,epoch=0,uploading=false,busy=false,cachedQuote=null,requestId=crypto.randomUUID(),lastFile=null,lastOrigin='file',analysisResult=null;
  let conversation=[],pendingEvaluation=false;
  function typing(on){
    let t=$('typing');
    if(on&&!t){t=document.createElement('div');t.id='typing';t.className='bubble typing';t.setAttribute('aria-label','Agua Clara está escribiendo');t.append(document.createElement('i'),document.createElement('i'),document.createElement('i'));$('messages').append(t);$('messages').scrollTop=$('messages').scrollHeight;}
    else if(!on&&t)t.remove();
  }
  function draw(text,you=false,image='',result=false){
    typing(false);
    conversation.push({role:you?'user':'assistant',text,at:new Date().toISOString(),image:Boolean(image)});
    const bubble=document.createElement('div');bubble.className='bubble'+(you?' you':'')+(result?' result':'');
    if(image){const img=document.createElement('img');img.src=image;img.alt='Foto adjunta de la pileta';bubble.append(img);}
    const body=document.createElement('span');body.textContent=text;
    const time=document.createElement('small');time.textContent=new Date().toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'});if(you){const ticks=document.createElement('span');ticks.className='ticks';ticks.textContent=' ✓✓';ticks.setAttribute('aria-label','entregado');time.append(ticks);}bubble.append(body,time);$('messages').append(bubble);$('messages').scrollTop=$('messages').scrollHeight;
  }
  function reply(text,result=false){draw(text,false,'',result);}
  const label=(map,key)=>(map&&map[key]&&(map[key].label||map[key]))||key;
  function drawAnalysis(result,meta){
    const water=AC_CONFIG.states[result.estado_agua]||result.estado_agua,shape=label(AC_CONFIG.shapes,result.tipo_pileta),pct=Math.round(result.confianza*100);
    const text='Lo que vi en tu foto: agua '+water.toLowerCase()+', '+(result.presencia_algas_paredes?'con':'sin')+' algas en las paredes, pileta '+shape.toLowerCase()+'. Confianza '+pct+' %.';
    conversation.push({role:'assistant',text,at:new Date().toISOString(),image:false});
    const card=document.createElement('div');card.className='bubble result analysis';
    const title=document.createElement('b');title.textContent='Lo que vi en tu foto';card.append(title);
    const rows=[['Agua',water],['Algas en paredes',result.presencia_algas_paredes?'Sí':'No'],['Forma',shape],['Calidad de la foto',result.calidad_foto]];
    const list=document.createElement('dl');rows.forEach(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;list.append(dt,dd);});card.append(list);
    const meter=document.createElement('div');meter.className='meter';meter.setAttribute('role','img');meter.setAttribute('aria-label','Confianza '+pct+' por ciento');const bar=document.createElement('i');bar.style.width=pct+'%';meter.append(bar);
    const cap=document.createElement('small');cap.textContent='Confianza de la lectura: '+pct+' %'+(meta&&meta.muestras>1?' · '+meta.muestras+' lecturas contrastadas con visión por color':'');card.append(meter,cap);
    if(meta&&meta.revisionSugerida){const note=document.createElement('small');note.className='review-note';note.textContent='El equipo va a revisar esta foto antes de confirmar el precio.';card.append(note);}
    typing(false);$('messages').append(card);$('messages').scrollTop=$('messages').scrollHeight;
  }
  function missingState(){
    if(data.length==null||data.width==null)return 'size';
    if(!data.depthType)return 'depthType';
    if(data.depthMin==null)return data.depthType==='uniforme'?'depth':'depthMin';
    if(data.depthType==='variable'&&data.depthMax==null)return 'depthMax';
    if(!data.measurementsConfirmed)return 'measuresReview';
    if(!data.zone)return 'zone';
    if(!data.name)return 'name';
    if(!data.phone)return 'phone';
    if(!data.day)return 'day';
    return 'review';
  }
  function applyFields(f){
    const done=[];
    if(f.length!=null&&f.width!=null){data.length=f.length;data.width=f.width;data.unknown=false;data.measurementsConfirmed=false;done.push(num(f.length)+' × '+num(f.width)+' m');}
    if(state==='depthMax'&&f.depthMax==null&&f.depthMin!=null&&f.depthType!=='uniforme'){f.depthMax=f.depthMin;delete f.depthMin;}
    if(f.depthMin!=null||f.depthMax!=null||f.depthType){
      data.unknownDepth=false;data.measurementsConfirmed=false;
      if(f.depthType)data.depthType=f.depthType;
      if(f.depthMin!=null)data.depthMin=f.depthMin;
      if(f.depthMax!=null)data.depthMax=f.depthMax;
      if(!data.depthType&&data.depthMin!=null)data.depthType=data.depthMax!=null&&data.depthMax!==data.depthMin?'variable':'uniforme';
      if(data.depthType==='uniforme'&&data.depthMin!=null)data.depthMax=data.depthMin;
      if(data.depthType==='variable'&&f.depthType==='variable'&&f.depthMax==null&&f.depthMin==null)delete data.depthMax;
      if(data.depthType==='variable'&&data.depthMin!=null&&data.depthMax!=null&&data.depthMax<data.depthMin)[data.depthMin,data.depthMax]=[data.depthMax,data.depthMin];
      if(data.depthMin!=null)done.push('profundidad '+(data.depthType==='variable'&&data.depthMax!=null?num(data.depthMin)+' a '+num(data.depthMax):num(data.depthMin))+' m');
    }
    if(f.zone){data.zone=f.zone;done.push('localidad '+f.zone);if(!AC_CONFIG.zones.includes(f.zone))done.push('(fuera de la cobertura confirmada: queda para revisión)');}
    if(f.name){data.name=f.name;done.push('nombre '+f.name);}
    if(f.phone){try{PricingEngine.contact({name:data.name||'xx',phone:f.phone,day:'A coordinar'});data.phone=f.phone;done.push('teléfono');}catch{}}
    if(f.day){data.day=f.day;done.push('día '+f.day);}
    return done;
  }
  async function interpret(text,t){
    if(!['size','depthType','depth','depthMin','depthMax','zone','name','phone','day','measuresReview','review'].includes(state))return false;
    const quick=new Set(['uniforme','variable','a coordinar','confirmar consulta','confirmar datos','confirmo','si','dale','todo bien','esta bien','confirmar medidas','corregir medidas',...days.map(normalize),...AC_CONFIG.zones.map(normalize)]);
    if(quick.has(t))return false;
    const token=epoch;busy=true;buttons([]);typing(true);$('status').textContent='Escribiendo…';
    let u=null;
    try{u=await UI.api('/api/understand',{method:'POST',body:JSON.stringify({text,step:state,shape:data.shape==='otra'?(data.poolShape||null):(data.shape||null),analysisId:data.analysisId||null})});}catch{u=null;}
    if(token!==epoch)return true;
    typing(false);busy=false;$('status').textContent='en línea';
    if(!u)return false;
    const fields=u.fields||{};
    if(!Object.keys(fields).length){
      if(u.intent==='pregunta'&&u.reply){reply(u.reply);if(state!=='review')await prompt();else buttons(['Confirmar consulta','Cambiar medidas','Cambiar profundidad','Cambiar localidad','Cambiar foto','Cambiar contacto','Cambiar día','Descargar resumen']);return true;}
      return false;
    }
    if(state==='review')requestId=crypto.randomUUID();
    const done=applyFields({...fields});
    if(!done.length)return false;
    cachedQuote=null;reply('Anoté: '+done.join(' · ')+'.');
    advance(missingState());return true;
  }
  function buttons(labels){$('actions').replaceChildren();labels.forEach(label=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>submit(label);$('actions').append(b);});}
  async function quote(){return await UI.quote(data);}
  function summary(){return cachedQuote?UI.resultText(data,cachedQuote):'Todavía faltan datos para precotizar. Completá el recorrido para ver el resumen.';}
  async function prompt(){
    if(state==='review'){const token=epoch;busy=true;$('status').textContent='Calculando…';buttons([]);try{const result=await quote();if(token!==epoch)return;cachedQuote=result;}catch(e){if(token===epoch){reply(e.message);buttons(['Reintentar cálculo','Cambiar medidas','Cambiar localidad']);}return;}finally{if(token===epoch){busy=false;$('status').textContent='en línea';}}if(token!==epoch)return;}
    const prompts={
      photo:['Compartí una foto de la pileta para evaluar el estado del agua.',['Sacar foto ahora','Cargar foto']],
      size:[data.shape==='otra'&&data.poolShape?'Veo que es una pileta '+label(AC_CONFIG.shapes,data.poolShape).toLowerCase()+'. Pasame el largo y el ancho máximos, en metros (por ejemplo “7 por 4”), y calculo la superficie aproximada según la forma. Si querés, contame todo junto: medidas, profundidad y localidad.':'¿Cuánto mide de largo y de ancho, en metros? Por ejemplo: “7 por 4”, “7 × 4 m” o “tiene 7 de largo y 4 de ancho”. También podés escribir todo junto: medidas, profundidad y localidad.',[]],
      depthType:['¿La profundidad es uniforme o cambia de un extremo al otro?',['Uniforme','Variable']],
      depth:['¿Cuál es la profundidad, en metros? Acepto coma decimal: por ejemplo “1,4 m”.',[]],
      depthMin:['¿Cuál es la profundidad mínima, en metros?',[]],
      depthMax:['¿Y la profundidad máxima? Debe ser igual o mayor que la mínima ('+data.depthMin+' m).',[]],
      measuresReview:['Confirmame estos datos: '+num(data.length)+' m de largo × '+num(data.width)+' m de ancho. Profundidad '+(data.depthType==='variable'?'de '+num(data.depthMin)+' a '+num(data.depthMax)+' m':num(data.depthMin)+' m')+'. '+(data.shape==='otra'&&data.poolShape?'Es una forma '+label(AC_CONFIG.shapes,data.poolShape).toLowerCase()+': la superficie es aproximada y se confirma en la visita. ':'')+'¿Son correctos?',['Confirmar medidas','Corregir medidas']],
      zone:['¿En qué localidad está la pileta? Si es otra localidad, escribí su nombre.',AC_CONFIG.zones],
      name:['¿Cómo te llamás?',[]],
      phone:['¿Qué teléfono de contacto querés dejar? Incluí el código de área.',[]],
      day:['¿Qué día preferís? Es una preferencia, no una reserva.',days],
      review:[summary()+'\n\n¿Están bien los datos?',['Confirmar consulta','Cambiar medidas','Cambiar profundidad','Cambiar localidad','Cambiar foto','Cambiar contacto','Cambiar día','Descargar resumen']],
      done:['Recibimos tu consulta. Identificador: '+savedId+'. Ya le avisamos al equipo de Agua Clara: te van a escribir para confirmar el precio final y el día de la visita.',['Ver panel de admin','Descargar resumen','Imprimir resumen','Nueva consulta']]
    };
    const [text,choices]=prompts[state];
    if(['review','done','measuresReview'].includes(state)){reply(text,state==='review');buttons(choices);return;}
    const token=epoch,step=state,withEvaluation=pendingEvaluation;pendingEvaluation=false;
    busy=true;buttons([]);typing(true);$('status').textContent='Escribiendo…';
    let message=text;
    try{const result=await UI.api('/api/dialogue',{method:'POST',body:JSON.stringify({step,analysisId:withEvaluation?data.analysisId:null})});message=result.message;}
    catch{if(withEvaluation)message=analysisResult.observaciones+'\n\n'+text;}
    if(token!==epoch)return;
    reply(message);buttons(choices);busy=false;$('status').textContent='en línea';
  }
  function advance(next){cachedQuote=null;state=next;prompt();}
  function continueAfterEdit(){data.editing=false;advance(missingState());}
  function reset(){conversation=[];pendingEvaluation=false;epoch++;uploading=false;busy=false;cachedQuote=null;requestId=crypto.randomUUID();lastFile=null;analysisResult=null;$('status').textContent='en línea';if(photoUrl)URL.revokeObjectURL(photoUrl);photoUrl='';state='photo';data={shape:'rectangular',unknown:false,unknownDepth:false};savedId=null;$('messages').replaceChildren();$('text').value='';$('photo').value='';$('camera').value='';prompt();}
  function numericText(text,label,max){
    const raw=text.trim().replace(/\s*(?:m|metros?|mts?)\.?$/i,'').trim();
    return PricingEngine.number(raw,label,max);
  }
  function finishDepth(){data.measurementsConfirmed=false;advance('measuresReview');}
  function validateAll(){
    if(!data.zone||data.zone.trim().length<3)throw Error('Falta la localidad.');
    PricingEngine.contact(data);return cachedQuote;
  }
  async function submit(raw){
    const text=raw.trim();if(!text||busy)return;const t=normalize(text);$('text').value='';
    if(t==='cargar foto'||t==='sacar foto ahora'){if(uploading)return;$(t==='cargar foto'?'photo':'camera').click();return;}
    if(t==='reintentar calculo'){prompt();return;}
    if(t==='reintentar analisis'){if(lastFile)await analyzeFile(lastFile,lastOrigin);else reply('Primero adjuntá una foto.');return;}
    if(t==='ver panel de admin'){UI.view('owner');return;}
    if(t==='descargar resumen'){try{validateAll();const q=cachedQuote||await quote();UI.download('AguaClara-precotizacion.txt',(savedId?'Identificador: '+savedId+'\n':'CONSULTA SIN CONFIRMAR\n')+UI.resultText(data,q),'text/plain;charset=utf-8');}catch(e){reply(e.message);}return;}
    if(t==='imprimir resumen'){try{$('print-content').textContent=(savedId?'Identificador: '+savedId+'\n':'')+UI.resultText(data,cachedQuote||await quote());window.print();}catch(e){reply(e.message);}return;}
    draw(text,true);
    if(/^(nueva consulta|reiniciar|empezar de nuevo)$/.test(t)){reset();return;}
    if(uploading){reply('Esperá a que termine la validación de la foto antes de continuar.');return;}
    if(/^(hola|buenas|buen dia|buenos dias|buenas tardes|buenas noches|hey)[!.\s]*$/.test(t)){reply('¡Hola! Seguimos con tu pileta.');prompt();return;}
    if(/^(gracias|muchas gracias|genial|perfecto)[!.\s]*$/.test(t)){reply('¡De nada! Podés seguir con las opciones de abajo.');return;}
    if(/^(ver resumen|resumen|mis datos)$/.test(t)){reply(summary(),true);return;}
    if(state==='measuresReview'&&t==='corregir medidas'){data.measurementsConfirmed=false;advance('size');return;}
    if(state==='measuresReview'&&t==='confirmar medidas'){data.measurementsConfirmed=true;continueAfterEdit();return;}
    if(state==='measuresReview'&&/^(si|correcto|son correctos|son correctas|dale|ok|esta bien|todo bien)[!.\s]*$/.test(t)){data.measurementsConfirmed=true;continueAfterEdit();return;}
    if(/^(cambiar|corregir|modificar)/.test(t)){
      if(state==='done'){reply('La consulta ya fue guardada. Revisala desde el panel de admin o iniciá una nueva; conservamos el registro original.');return;}
      const target=/profundidad/.test(t)?'depthType':/forma/.test(t)?'photo':/medida|tamano/.test(t)?'size':/localidad|zona/.test(t)?'zone':/telefono/.test(t)?'phone':/nombre|contacto/.test(t)?'name':/dia|fecha/.test(t)?'day':/foto|servicio|agua|alga/.test(t)?'photo':null;
      if(!target){reply('Podés corregir medidas, profundidad, localidad, contacto, teléfono, día o estado del agua.');return;}
      if(!data.day){reply('Completá primero el recorrido; después podrás corregir cada dato desde el resumen.');return;}
      requestId=crypto.randomUUID();data.editing=true;if(['size','depthType','photo'].includes(target))data.measurementsConfirmed=false;if(target==='photo')delete data.analysisId;advance(target);return;
    }
    if(await interpret(text,t))return;
    if(/precio|cuanto (sale|cuesta|cobran)|presupuesto|tarifa/.test(t)&&!/^guardar/.test(t)){reply(data.zone?summary():'La precotización sale de la tabla de tramos, según superficie y servicio. Primero completamos los datos. El precio final queda a confirmar.',!!data.zone);return;}
    if(/que (hacen|servicios)|como funciona|que podes hacer|ayuda/.test(t)){reply('Mantenimiento, limpieza total y recuperación de agua verde. Reunimos foto, medidas, zona y contacto. No realizamos reparaciones de bombas, electricidad ni plomería.');prompt();return;}
    if(/horario|cuanto tarda|cuando vienen|disponibilidad/.test(t)){reply('El horario y la duración se coordinan con el prestador. El día preferido no representa una reserva.');return;}
    if(/son una ia|sos (una ia|un bot|humano)|inteligencia artificial/.test(t)){reply('Soy un asistente automático. Cuando el análisis de fotos está disponible, Gemini evalúa el agua; el precio se calcula con la tabla de tarifas de Agua Clara.');return;}
    try{
      if(state==='photo'){reply('Necesitamos una foto para que la IA evalúe el agua.');buttons(['Sacar foto ahora','Cargar foto']);return;}
      if(state==='size'){
        if(/no se|no tengo|ni idea/.test(t)){reply('Necesitamos que midas el largo y el ancho para continuar. Cuando los tengas, escribilos acá.');return;}
        // Accept the original natural phrase but never drop a negative sign.
        const cleaned=t.replaceAll(',','.');const numbers=cleaned.match(/[+-]?\d+(?:\.\d+)?/g);
        const allowed=cleaned.replace(/[+-]?\d+(?:\.\d+)?/g,'').replace(/tiene|de|largo|ancho|metros|metro|mts|por|[xy×m.\s]/g,'');
        if(!numbers||numbers.length!==2||allowed){throw Error('Ingresá largo y ancho en metros: “7 por 4” o “tiene 7 de largo y 4 de ancho”.');}
        const length=PricingEngine.number(numbers[0],'Largo',50),width=PricingEngine.number(numbers[1],'Ancho',50);
        data.measurementsConfirmed=false;data.length=length;data.width=width;data.unknown=false;delete data.depthMin;delete data.depthMax;data.unknownDepth=false;
        advance('depthType');return;
      }
      if(['depthType','depth','depthMin','depthMax'].includes(state)&&/no se|no tengo/.test(t)){reply('Necesitamos la profundidad para continuar. Cuando la sepas, escribila acá.');return;}
      if(state==='depthType'){
        if(!['uniforme','variable'].includes(t))throw Error('Elegí profundidad Uniforme o Variable.');data.depthType=t;data.unknownDepth=false;delete data.depthMin;delete data.depthMax;advance(t==='uniforme'?'depth':'depthMin');return;
      }
      if(state==='depth'||state==='depthMin'){
        const depth=numericText(text,'Profundidad',5);data.depthMin=depth;data.unknownDepth=false;if(state==='depthMin')advance('depthMax');else{data.depthMax=depth;finishDepth();}return;
      }
      if(state==='depthMax'){
        const max=numericText(text,'Profundidad máxima',5);if(max<data.depthMin)throw Error('La profundidad máxima no puede ser menor que '+num(data.depthMin)+' m.');data.depthMax=max;finishDepth();return;
      }
      if(state==='zone'){
        const location=text.replace(/^(vivo en|estoy en|en)\s+/i,'').trim();
        if(location.length<3||location.length>80||/\d|\?|no se|no tengo/.test(normalize(location)))throw Error('Escribí una localidad de 3 a 80 caracteres.');
        const z=AC_CONFIG.zones.find(z=>normalize(z)===normalize(location));data.zone=z||location;if(!z)reply('Esa localidad queda fuera de nuestra cobertura confirmada. Dejamos la consulta para revisar.');continueAfterEdit();return;
      }
      if(state==='name'){
        const name=text.replace(/^(me llamo|mi nombre es|soy)\s+/i,'').trim();if(name.length<2||name.length>80||/[\d?]/.test(name))throw Error('Ingresá un nombre de entre 2 y 80 caracteres, sin números.');data.name=name;continueAfterEdit();return;
      }
      if(state==='phone'){
        PricingEngine.contact({name:data.name,phone:text,day:'A coordinar'});data.phone=text;continueAfterEdit();return;
      }
      if(state==='day'){
        const day=days.find(x=>normalize(x)===t);if(!day)throw Error('Elegí uno de los días o “A coordinar”.');data.day=day;data.editing=false;advance('review');return;
      }
      if(state==='review'&&/^(confirmar consulta|confirmar datos|confirmo|si|dale|todo bien|esta bien)[!.\s]*$/.test(t)){
        validateAll();busy=true;$('status').textContent='Enviando consulta…';const token=epoch;try{const record=await UI.save({...data},requestId,conversation);if(token!==epoch)return;savedId=record.id;cachedQuote=record.quote;state='done';prompt();}finally{if(token===epoch){busy=false;$('status').textContent='en línea';}}return;
      }
      if(state==='done'){reply('La consulta ya está guardada. Podés abrir el panel de admin, descargar el resumen o iniciar otra.');return;}
      reply('Quiero asegurarme de entenderte bien.');prompt();
    }catch(err){reply(err.message);}
  }
  async function analyzeFile(file,origin){
    delete data.analysisId;delete data.water;delete data.algae;delete data.poolShape;const token=epoch;uploading=true;busy=true;$('status').textContent='Analizando foto…';buttons([]);typing(true);
    try{
      const form=new FormData();form.append('image',file);
      const response=await UI.api('/api/analysis',{method:'POST',body:form});
      if(token!==epoch)return;
      analysisResult=response.result;
      if(!analysisResult.es_pileta){delete data.analysisId;reply('No pudimos identificar una pileta en esa imagen. Probá con otra foto.');state='photo';buttons(['Cargar foto']);return;}
      if(analysisResult.confianza<0.65||analysisResult.estado_agua==='desconocido'){delete data.analysisId;reply('La imagen no permite una evaluación suficientemente clara. Probá con otra foto con mejor luz.');advance('photo');return;}
      data.analysisId=response.id;
      drawAnalysis(analysisResult,response.meta);
      pendingEvaluation=true;
      data.water=analysisResult.estado_agua;data.algae=analysisResult.presencia_algas_paredes;
      data.shape=['rectangular','cuadrada'].includes(analysisResult.tipo_pileta)?'rectangular':'otra';
      if(data.shape==='otra'&&AC_CONFIG.shapes&&AC_CONFIG.shapes[analysisResult.tipo_pileta])data.poolShape=analysisResult.tipo_pileta;else delete data.poolShape;
      data.unknown=false;data.unknownDepth=false;delete data.length;delete data.width;delete data.depthMin;delete data.depthMax;
      data.measurementsConfirmed=false;data.editing=false;state='size';cachedQuote=null;await prompt();
    }catch(e){if(token===epoch){delete data.analysisId;typing(false);reply(e.message);state='photo';buttons(['Reintentar análisis','Cargar foto']);}}
    finally{if(token===epoch){uploading=false;busy=false;$('status').textContent='en línea';}}
  }
  async function onPhoto(event){
    const file=event.target.files[0];event.target.value='';if(!file)return;
    if(state==='done'){reply('Iniciá una nueva consulta para adjuntar otra foto.');return;}
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10*1024*1024||!file.size){reply('Elegí un JPG, PNG o WebP de hasta 10 MB.');return;}
    const token=epoch;let url='';busy=true;
    try{
      url=URL.createObjectURL(file);const img=new Image();img.src=url;await img.decode();
      if(token!==epoch){URL.revokeObjectURL(url);return;}
      if(photoUrl)URL.revokeObjectURL(photoUrl);photoUrl=url;data.photoName=file.name;lastOrigin=event.target.id==='camera'?'camera_requested':'file';data.photoOrigin=lastOrigin;lastFile=file;
      // Reducir antes de subir para admitir fotos de celular dentro del límite de Vercel.
      const scale=Math.min(1,1280/Math.max(img.naturalWidth,img.naturalHeight));
      const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(img.naturalWidth*scale));canvas.height=Math.max(1,Math.round(img.naturalHeight*scale));
      canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);
      const upload=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.85));
      if(token!==epoch)return;
      if(!upload||upload.size>3*1024*1024)throw Error('No pudimos preparar la foto.');
      lastFile=new File([upload],'pileta.jpg',{type:'image/jpeg'});
      draw('Foto adjunta',true,url);await analyzeFile(lastFile,lastOrigin);
    }catch(e){if(url)URL.revokeObjectURL(url);if(token===epoch)reply('No pudimos leer la imagen. Probá otro archivo.');}
    finally{if(token===epoch)busy=false;}
  }
  $('photo').onchange=onPhoto;$('camera').onchange=onPhoto;
  $('composer').onsubmit=e=>{e.preventDefault();if(!$('text').disabled)submit($('text').value);};$('reset').disabled=true;
  $('text').disabled=true;
  UI.ready.then(()=>{$('text').disabled=false;$('reset').disabled=false;$('reset').onclick=reset;reset();}).catch(e=>{reply(e.message+' Recargá la página para volver a intentar.');$('status').textContent='Sin conexión';if(location.protocol==='file:'){const link=document.createElement('a');link.href='http://127.0.0.1:8766/';link.textContent='Abrir Agua Clara';$('actions').replaceChildren(link);}});
})();
