const canvas=document.getElementById('screen'),ctx=canvas.getContext('2d');
const list=document.getElementById('contacts'),status=document.getElementById('status'),count=document.getElementById('count');
let tracks=[],chosen=null,updated=0;
function draw(){
 const w=canvas.width=canvas.clientWidth*devicePixelRatio,h=canvas.height=canvas.clientHeight*devicePixelRatio;
 ctx.fillStyle='#061015';ctx.fillRect(0,0,w,h);
 const cx=w/2,cy=h/2,r=Math.min(w,h)*.41;
 ctx.strokeStyle='#164a42';ctx.lineWidth=1;
 for(let i=1;i<=4;i++){ctx.beginPath();ctx.arc(cx,cy,r*i/4,0,Math.PI*2);ctx.stroke();}
 for(let i=0;i<12;i++){let a=i*Math.PI/6;ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(cx+Math.cos(a)*r,cy+Math.sin(a)*r);ctx.stroke();}
 ctx.fillStyle='#00dfae';ctx.font=`${12*devicePixelRatio}px monospace`;ctx.fillText('N',cx,cy-r-8);
 const base=tracks.find(t=>t.category==='BASE')?.position||tracks[0]?.position||{x:0,z:0};
 for(const t of tracks){const p=t.position||{},x=cx+(p.x-base.x)/256*r,z=cy+(p.z-base.z)/256*r;
 if(Math.hypot(x-cx,z-cy)>r)continue;
 ctx.fillStyle=t.category==='PLAYER'?'#18e9c0':t.category==='HOSTILE'?'#ff6969':'#e4c879';
 ctx.beginPath();ctx.arc(x,z,(t.id===chosen?6:3)*devicePixelRatio,0,Math.PI*2);ctx.fill();
 if(t.id===chosen){ctx.strokeStyle='#fff';ctx.strokeRect(x-9,z-9,18,18);}
 }requestAnimationFrame(draw);
}
async function refresh(){
 try{const response=await fetch('/api/radar/live',{cache:'no-store'});if(!response.ok)throw Error(response.status);
 const data=await response.json();tracks=data.tracks||[];updated=data.received_at||0;
 status.textContent=data.stale?'OFFLINE / STALE':'LIVE';count.textContent=tracks.length+' CONTACTS';
 list.replaceChildren();for(const t of tracks){const row=document.createElement('button');row.className='track';row.textContent=`${t.category||'OTHER'} · ${t.name||t.entityType||t.id||'Unknown'} · ${Math.round(t.position.x)}, ${Math.round(t.position.y)}, ${Math.round(t.position.z)}`;row.onclick=()=>{chosen=t.id;document.getElementById('selected').textContent=JSON.stringify(t,null,2)};list.append(row);}
 }catch(e){status.textContent='NO CONNECTION'}
}draw();refresh();setInterval(refresh,3000);
