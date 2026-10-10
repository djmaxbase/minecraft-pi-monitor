'use strict';
(async()=>{
const setup=document.getElementById('setup'),dashboard=document.getElementById('dashboard');
try{
const res=await fetch('/api/bootstrap');if(!res.ok)throw Error('Bootstrap mislukt');const state=await res.json();
if(!state.setup_required){for(const file of ['/app.js','/extended.js'])await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=file;script.onload=resolve;script.onerror=reject;document.head.append(script);});return;}
dashboard.hidden=true;setup.hidden=false;
const form=document.getElementById('setup-form');
async function send(path){const values=Object.fromEntries(new FormData(form));const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});const body=await response.json();if(!response.ok)throw Error(body.error);return body;}
document.getElementById('setup-test').onclick=async()=>{const out=document.getElementById('setup-test-result');out.textContent='Verbinding testen…';try{const r=await send('/api/setup/test');out.textContent=r.reachable?`Bereikbaar · ${r.version} · ${r.online} spelers · Query ${r.query_available?'beschikbaar':'niet beschikbaar'}. ${r.limitation}`:`Niet bereikbaar: ${r.error}`;}catch(e){out.textContent=e.message;}};
form.onsubmit=async e=>{e.preventDefault();try{await send('/api/setup');location.reload();}catch(err){document.getElementById('setup-result').textContent=err.message;}};
}catch(e){dashboard.hidden=true;setup.hidden=false;document.getElementById('setup-result').textContent='Installatiestatus ophalen mislukt: '+e.message;}
})();
