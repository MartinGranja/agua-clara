'use strict';

const UI = (() => {

  const $=id=>document.getElementById(id);

  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const money=n=>new Intl.NumberFormat('es-AR',{style:'currency',currency:'ARS',maximumFractionDigits:0}).format(n);

  const num=n=>new Intl.NumberFormat('es-AR',{maximumFractionDigits:2}).format(n);

  let records=[],adminToken='',knownIds=null,pollTimer=null;
  const OUTCOMES=[['contactado','Contactado'],['agendado','Agendado'],['descartado','Descartado']];
  const waLink=r=>{let n=String(r.data.phone).replace(/\D/g,'').replace(/^0+/,'');if(n.length===12){const i=[2,3,4].find(i=>n.slice(i,i+2)==='15');if(i!==undefined)n=n.slice(0,i)+n.slice(i+2);}if(!n.startsWith('54'))n='549'+n;else if(!n.startsWith('549'))n='549'+n.slice(2);const q=r.quote;const text='Hola '+r.data.name+', te escribimos de Agua Clara por tu consulta de la pileta.'+(q.price!=null?' La precotización es de '+money(q.price)+(q.cleanings>1?' en total ('+q.cleanings+' limpiezas de '+money(q.unitPrice)+')':'')+'.':'')+' ¿Coordinamos la visita?';return 'https://wa.me/'+n+'?text='+encodeURIComponent(text);};
  const notifyLine=r=>{const n=r.notification;if(!AC_CONFIG.notifyChannels?.length&&!n)return 'Aviso automático al dueño: sin canal configurado (se ve en este panel).';if(!n)return 'Aviso al dueño: sin enviar.';const names=(n.sent||[]).join(', ');return n.ok?'Aviso al dueño enviado por '+names+(n.failed?.length?' (falló: '+n.failed.join(', ')+')':'')+'.':'Aviso al dueño no enviado'+(n.failed?.length?' ('+n.failed.join(', ')+')':'')+'.';};

  async function api(path,options={}) {

    if(location.protocol==='file:')throw Error('Abrí Agua Clara desde http://127.0.0.1:8766/. Si no responde, ejecutá Iniciar_AguaClara.cmd. Este archivo necesita conectarse al servidor.');

    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),40000);

    try{

      const response=await fetch(path,{...options,signal:controller.signal,headers:{...(options.body&&!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(path.startsWith('/api/admin/')&&adminToken?{Authorization:'Bearer '+adminToken}:{}),...options.headers}});

      let body;try{body=await response.json();}catch{throw Error('El servidor devolvió una respuesta inesperada. Reintentá.');}

      if(!response.ok){const message=Array.isArray(body.detail)?body.detail.map(x=>x.loc.slice(1).join('.')+': '+x.msg).join('\n'):body.detail||'No pudimos completar la operación.';const error=new Error(message);error.status=response.status;throw error;}return body;

    }catch(e){if(e.name==='AbortError')throw Error('El servidor tardó demasiado. Podés reintentar.');if(e instanceof TypeError)throw Error('No pudimos conectar con el servidor. Revisá la conexión y reintentá.');throw e;}finally{clearTimeout(timeout);}

  }

  const ready=api('/api/config').then(config=>Object.assign(AC_CONFIG,config));

  function clean(d){return Object.fromEntries(['shape','unknown','unknownDepth','length','width','depthType','depthMin','depthMax','water','algae','zone','name','phone','day','photoName','photoOrigin','analysisId','measurementsConfirmed'].filter(k=>d[k]!==undefined).map(k=>[k,d[k]]));}

  function quote(d){return api('/api/quotes',{method:'POST',body:JSON.stringify(clean(d))});}

  function save(d,id,conversation){return api('/api/requests',{method:'POST',body:JSON.stringify({requestId:id,data:clean(d),conversation})});}

  function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,5000);}

  function download(name,content,type='application/json'){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}

  function priceDetail(q){if(q.price==null)return '';const p=[];if(q.cleanings>1)p.push(money(q.unitPrice)+' por limpieza × '+q.cleanings+' limpiezas (pueden ser hasta 3; se confirma antes de empezar)');if(q.depthMultiplier>1)p.push('incluye recargo por profundidad ×'+num(q.depthMultiplier));return p.join(' · ');}
  function resultText(d,q){const dims=q.dimensions;return 'AGUA CLARA · PRECOTIZACIÓN\n\n'+

    'Cliente: '+(d.name||'Pendiente')+'\nTeléfono: '+(d.phone||'Pendiente')+'\nLocalidad: '+(d.zone||'Pendiente')+'\nDía preferido: '+(d.day||'A coordinar')+'\n'+

    'Estado del agua: '+(AC_CONFIG.states[d.water]||'A confirmar')+'\nAlgas en paredes: '+(d.algae?'Sí':'No')+'\nServicio sugerido: '+(AC_CONFIG.services[q.service]||'A evaluar')+'\n'+

    'Superficie: '+(dims.area===null?'A confirmar':num(dims.area)+' m²')+'\nVolumen aproximado: '+(dims.volume===null?'A confirmar':num(dims.volume)+' m³ · '+num(dims.volume*1000)+' L')+'\n'+

    (dims.depth!==null?'Cálculo: '+num(dims.length)+' × '+num(dims.width)+' × '+num(dims.depth)+' m de profundidad promedio.\n':'')+

    '\nPrecotización: '+(q.price===null?'A confirmar':money(q.price)+' ARS'+(q.cleanings>1?' (total estimado)':''))+'\n'+(priceDetail(q)?priceDetail(q)+'\n':'')+q.reason+'\n\nEl precio final y el día de visita se confirman con el prestador.';}

  function exportOne(r){download('AguaClara-'+r.id+'.json',JSON.stringify(r,null,2));}

  function view(name){document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('.nav').forEach(e=>{e.classList.toggle('active',e.dataset.view===name);e.setAttribute('aria-pressed',String(e.dataset.view===name));});clearInterval(pollTimer);if(name==='owner'){refresh();pollTimer=setInterval(()=>{if(!document.hidden&&!document.querySelector('#owner-list details[open], #owner-list form :focus'))refresh();},20000);}}

  async function refresh(){

    $('owner-error').textContent='';$('refresh').disabled=true;

    try{records=await api('/api/admin/requests');$('owner-login').hidden=true;const fresh=knownIds?records.filter(r=>!knownIds.has(r.id)):[];knownIds=new Set(records.map(r=>r.id));renderOwner();if(fresh.length)toast('Llegó una consulta nueva: '+fresh.map(r=>r.data.name).join(', ')+'.');}

    catch(e){$('owner-error').textContent=e.message;if(e.status===401){$('owner-login').hidden=false;records=[];$('owner-list').replaceChildren();$('owner-stats').replaceChildren();}}

    finally{$('refresh').disabled=false;}

  }

  function renderOwner(){

    const pending=records.filter(r=>r.state==='pending').length,booked=records.filter(r=>r.outcome==='agendado').length;
    $('count').textContent=pending||'';
    $('owner-stats').innerHTML=[[records.length,'Consultas'],[pending,'Pendientes de revisión'],[booked,'Agendadas'],[records.length?Math.round(booked/records.length*100)+'%':'—','Conversión a cliente']].map(([n,label])=>'<div class="stat"><b>'+n+'</b><span>'+label+'</span></div>').join('');

    const selected=records.filter(r=>$('filter').value==='all'||r.state===$('filter').value).slice().reverse();

    $('owner-list').innerHTML=selected.length?selected.map(r=>{

      const d=r.data,q=r.quote,displayPrice=r.review?.price??q.price;return '<article class="request" data-id="'+esc(r.id)+'"><div><span class="pill">'+(r.state==='reviewed'?'Revisada':'Pendiente de revisión')+'</span>'+(r.outcome?' <span class="pill outcome-'+esc(r.outcome)+'">'+esc((OUTCOMES.find(o=>o[0]===r.outcome)||[,''])[1])+'</span>':'')+'<h2>'+esc(d.name)+'</h2><p>'+esc(d.zone)+' · '+esc(d.phone)+'<br>'+esc(AC_CONFIG.services[q.service]||'Servicio a evaluar')+' · '+(q.dimensions.area==null?'Medidas a confirmar':num(q.dimensions.area)+' m²')+'</p><small>'+esc(r.id)+'<br>'+esc(new Date(r.createdAt).toLocaleString('es-AR'))+'</small></div><div><span class="help">Precotización</span><div class="amount">'+(displayPrice===null?'A confirmar':money(displayPrice))+'</div><p>'+esc(r.review?.price!=null?'Precio revisado por el administrador.':q.reason)+'</p>'+(r.review?'<span class="pill">'+(r.review.price==null?'Importe a confirmar':money(r.review.price)+' · revisado')+'</span>':'')+(priceDetail(q)?'<p>'+esc(priceDetail(q))+'</p>':'')+'<div class="inline-actions"><a class="button primary" target="_blank" rel="noopener" href="'+esc(waLink(r))+'">Responder por WhatsApp</a><button data-export="'+esc(r.id)+'">Exportar JSON</button></div><p class="notify-status">'+esc(notifyLine(r))+(AC_CONFIG.notifyChannels?.length?' <button class="link" data-notify="'+esc(r.id)+'">'+(r.notification?.ok?'Reenviar':'Enviar aviso')+'</button>':'')+'</p><div class="outcomes" role="group" aria-label="Seguimiento"><span class="help">Seguimiento</span>'+OUTCOMES.map(([k,l])=>'<button data-outcome="'+k+'" data-id="'+esc(r.id)+'" aria-pressed="'+(r.outcome===k)+'" class="chip'+(r.outcome===k?' on':'')+'">'+l+'</button>').join('')+'</div></div><details><summary>Ver datos y registrar revisión</summary><pre class="request-summary">'+esc(resultText(d,q))+'</pre>'+(r.review?'<p><b>Nota:</b> '+esc(r.review.note)+'</p>':'')+'<form class="edit-area" data-review="'+esc(r.id)+'"><label>Importe revisado en ARS<input name="price" type="number" min="1" max="10000000" step="1" '+(q.status==='sin_cobertura'?'disabled':'')+' value="'+(r.review?.price??'')+'" placeholder="A confirmar"></label><label>Motivo o nota de revisión<textarea name="note" required minlength="5" maxlength="500" rows="2">'+esc(r.review?.note||'')+'</textarea></label><button class="primary approval">Guardar revisión</button><p class="review-error" role="alert"></p></form></details><details class="evidence" data-evidence="'+esc(r.id)+'"><summary>Ver foto y conversación</summary><div class="evidence-body"></div></details></article>';

    }).join(''):'<div class="empty"><h2>No hay consultas en esta vista</h2><p>Las nuevas solicitudes aparecerán acá para su revisión.</p></div>';

    $('owner-list').querySelectorAll('[data-evidence]').forEach(details=>details.ontoggle=async()=>{

      if(!details.open||details.dataset.loaded||details.dataset.loading)return;

      details.dataset.loading='true';const body=details.querySelector('.evidence-body');body.textContent='Cargando…';

      try{

        const evidence=await api('/api/admin/requests/'+details.dataset.evidence+'/details');body.replaceChildren();

        if(evidence.photo&&/^data:image\/jpeg;base64,/.test(evidence.photo)){const img=document.createElement('img');img.src=evidence.photo;img.alt='Foto de la pileta evaluada por la IA';img.className='request-photo';body.append(img);}

        else{const p=document.createElement('p');p.textContent='Esta consulta no tiene una foto guardada.';body.append(p);}

        const history=document.createElement('details');const title=document.createElement('summary');title.textContent='Ver conversación';history.append(title);

        const log=document.createElement('div');log.className='saved-chat';

        for(const message of evidence.conversation){const bubble=document.createElement('div');bubble.className='bubble'+(message.role==='user'?' you':'');const label=document.createElement('b');label.textContent=message.role==='user'?'Cliente':'Agua Clara';const text=document.createElement('div');text.textContent=message.text;const time=document.createElement('small');time.textContent=new Date(message.at).toLocaleString('es-AR');bubble.append(label,text,time);log.append(bubble);}

        if(!evidence.conversation.length)log.textContent='Esta consulta no tiene una conversación guardada.';

        history.append(log);body.append(history);details.dataset.loaded='true';

      }catch(e){body.textContent=e.message+' Cerrá y volvé a abrir para reintentar.';}

      finally{delete details.dataset.loading;}

    });

    $('owner-list').querySelectorAll('[data-outcome]').forEach(b=>b.onclick=async()=>{try{await api('/api/admin/requests/'+b.dataset.id+'/outcome',{method:'PATCH',body:JSON.stringify({outcome:b.getAttribute('aria-pressed')==='true'?'sin_gestion':b.dataset.outcome})});await refresh();}catch(err){toast(err.message);}});
    $('owner-list').querySelectorAll('[data-notify]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const r=await api('/api/admin/requests/'+b.dataset.notify+'/notify',{method:'POST'});toast(r.notification?.ok?'Aviso enviado.':'No se pudo enviar el aviso.');await refresh();}catch(err){toast(err.message);b.disabled=false;}});
    $('owner-list').querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>exportOne(records.find(r=>r.id===b.dataset.export)));

    $('owner-list').querySelectorAll('[data-review]').forEach(f=>f.onsubmit=async e=>{

      e.preventDefault();const r=records.find(r=>r.id===f.dataset.review);f.querySelector('button').disabled=true;

      try{const raw=f.elements.price.value;await api('/api/admin/requests/'+r.id,{method:'PATCH',body:JSON.stringify({price:raw===''?null:Number(raw),note:f.elements.note.value.trim()})});await refresh();toast('Revisión guardada.');}

      catch(err){f.querySelector('.review-error').textContent=err.message;f.querySelector('button').disabled=false;}

    });

  }

  document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>view(b.dataset.view));document.querySelector('.brand').onclick=e=>{e.preventDefault();view('client');};

  $('owner-login').onsubmit=e=>{e.preventDefault();adminToken=$('owner-token').value;$('owner-token').value='';refresh();};

  $('refresh').onclick=refresh;$('filter').onchange=renderOwner;

  $('export-all').onclick=async()=>{try{const latest=await api('/api/admin/requests');download('AguaClara-consultas.json',JSON.stringify({exportedAt:new Date().toISOString(),records:latest},null,2));}catch(e){toast(e.message);}};

  return {$,esc,money,num,toast,save,quote,api,ready,download,resultText,view,exportOne};

})();

