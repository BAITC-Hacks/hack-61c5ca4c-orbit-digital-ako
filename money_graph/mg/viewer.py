"""Экран просмотра: один офлайн HTML-файл (vis-network встроен, интернет не нужен)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROLE_COLORS = {
    "coordinator": "#d62728", "consolidator": "#ff7f0e", "distributor": "#9467bd",
    "transit": "#1f77b4", "terminal": "#2ca02c", "truncated": "#8c8c8c", "peripheral": "#c7c7c7",
}
ROLE_RU = {
    "coordinator": "координатор", "consolidator": "консолидатор", "distributor": "распределитель",
    "transit": "транзит", "terminal": "конечный получатель", "truncated": "обрезан 4-м хопом",
    "peripheral": "периферия",
}


def _num(x, nd=4):
    return None if pd.isna(x) else round(float(x), nd)


def write_viewer(path: Path, df, edges, clusters, top, res, summary, vis_js: Path):
    nodes = [{
        "id": str(g), "role": r.role, "rs": _num(r.role_score, 2), "cl": int(r.cluster_id),
        "pr": _num(r.priority_score), "ev": r.evidence, "d": int(r.depth), "seed": bool(r.is_seed),
        "ind": int(r.in_deg), "outd": int(r.out_deg), "ink": _num(r.in_kzt, 0), "outk": _num(r.out_kzt, 0),
        "pt": _num(r.pass_through, 3), "ts": _num(r.taint_share, 3), "ti": _num(r.tainted_in_kzt, 0),
        "bi": _num(r.block_impact, 4), "po": _num(r.p_onward, 3), "fs": _num(r.fast_share, 2),
        "cy": int(r.cycles_le4),
    } for g, r in df.iterrows()]
    eds = [[str(r.src), str(r.dst), float(r.sum_kzt), int(r.n_tx)] for r in edges.itertuples()]
    data = {
        "nodes": nodes, "edges": eds, "colors": ROLE_COLORS, "roleRu": ROLE_RU,
        "clusters": json.loads(clusters.to_json(orient="records", force_ascii=False)),
        "top": json.loads(top.assign(gid=top.gid.astype(str)).to_json(orient="records", force_ascii=False)),
        "res": json.loads(res.to_json(orient="records")), "summary": summary,
    }
    html = TEMPLATE.replace("/*VIS*/", vis_js.read_text(encoding="utf-8")) \
                   .replace("/*DATA*/", json.dumps(data, ensure_ascii=False))
    path.write_text(html, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Граф денег — просмотр</title>
<script>/*VIS*/</script>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e2e2dc;--acc:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#9a9a93;--line:#34342f;--acc:#ff8a80}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink);display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}header .s{color:var(--muted);font-size:12px}
main{flex:1;display:grid;grid-template-columns:minmax(320px,440px) 1fr;min-height:0}
@media (max-width:900px){main{grid-template-columns:1fr;grid-template-rows:auto 60vh}}
#side{border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0;background:var(--panel)}
nav{display:flex;border-bottom:1px solid var(--line);overflow-x:auto}
nav button{flex:1;padding:9px 6px;border:0;background:none;color:var(--muted);cursor:pointer;font:inherit;border-bottom:2px solid transparent;white-space:nowrap}
nav button.on{color:var(--ink);border-bottom-color:var(--acc)}
.pane{display:none;overflow:auto;padding:12px;flex:1}.pane.on{display:block}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
tr.row{cursor:pointer}tr.row:hover{background:var(--bg)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
button.b{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);cursor:pointer}
#wrap{position:relative;min-height:0}#net{position:absolute;inset:0}
#card{position:absolute;right:12px;top:12px;width:min(360px,calc(100% - 24px));max-height:calc(100% - 24px);overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;display:none;box-shadow:0 4px 18px rgba(0,0,0,.12)}
#card h3{margin:0 0 6px;font-size:14px;word-break:break-all}.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:12.5px}.kv span:nth-child(odd){color:var(--muted)}
#legend{position:absolute;left:12px;bottom:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:12px}
.hint{color:var(--muted);font-size:12px}.ev{background:var(--bg);border-radius:6px;padding:6px 8px;margin:8px 0;font-size:12.5px}
</style></head><body>
<header><h1>Граф денег</h1><span class="s" id="stat"></span></header>
<main>
<section id="side">
 <nav><button data-p="top" class="on">Приоритет</button><button data-p="search">Поиск gid</button><button data-p="cl">Кластеры</button><button data-p="res">Блокировка</button></nav>
 <div class="pane on" id="p-top"><p class="hint">На карте подписаны значимые цифры gid (7 цифр перед «100»). Кого смотреть первым. Клик — узел и его связи на карте. Все выводы — гипотезы для проверки.</p><table id="ttop"></table></div>
 <div class="pane" id="p-search">
  <div style="display:flex;gap:6px;flex-wrap:wrap"><input id="q" placeholder="gid, например 100000003684369100" style="flex:1;min-width:200px">
  <select id="hops"><option value="1">1 хоп</option><option value="2" selected>2 хопа</option></select><button class="b" id="go">Найти</button></div>
  <p class="hint">Можно ввести часть gid. Показываются входящие и исходящие связи на выбранную глубину.</p><div id="sres"></div></div>
 <div class="pane" id="p-cl"><p class="hint">Louvain на неориентированной проекции. Клик — показать кластер целиком.</p><table id="tcl"></table></div>
 <div class="pane" id="p-res"><p class="hint">Сколько «меченого» потока (денег, прослеживаемых к seed) остаётся, если заблокировать топ-N узлов по приоритету, против N случайных узлов.</p><div id="chart"></div><table id="tres"></table></div>
</section>
<section id="wrap"><div id="net"></div><div id="card"></div><div id="legend"></div></section>
</main>
<script>
const D=/*DATA*/;
const N=new Map(D.nodes.map(n=>[n.id,n]));
const OUT=new Map(),IN=new Map();
D.edges.forEach(e=>{(OUT.get(e[0])||OUT.set(e[0],[]).get(e[0])).push(e);(IN.get(e[1])||IN.set(e[1],[]).get(e[1])).push(e)});
const kzt=x=>x==null?'н/д':x>=1e6?(x/1e6).toFixed(1).replace('.',',')+' млн':x>=1e3?Math.round(x/1e3)+' тыс':Math.round(x)+'';
const sh=id=>id.slice(-10,-3);
const pct=x=>x==null?'н/д':Math.round(x*100)+'%';
const S=D.summary;document.getElementById('stat').textContent=`${S.nodes} узлов · ${S.edges} рёбер · ${S.clusters} кластеров · меченый поток ${kzt(S.tainted_flow_kzt)} KZT · пересчёт ${S.runtime_sec} с`;
document.getElementById('legend').innerHTML=Object.entries(D.colors).map(([r,c])=>`<div><span class="dot" style="background:${c}"></span>${D.roleRu[r]}</div>`).join('')+'<div class="hint">толстая рамка — seed</div>';
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button,.pane').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.getElementById('p-'+b.dataset.p).classList.add('on')});

let net=null;
function draw(ids,focus){
  const set=new Set(ids);
  const nodes=[...set].map(id=>{const n=N.get(id);return{id,label:sh(id),title:`${id}\n${D.roleRu[n.role]} · приоритет ${n.pr}`,
    color:{background:D.colors[n.role],border:n.seed?'#000':D.colors[n.role]},borderWidth:n.seed?4:1,
    size:5+18*Math.pow(n.pr||0,3),shape:'dot',font:{size:id===focus?16:10,color:getComputedStyle(document.body).color}}});
  const edges=D.edges.filter(e=>set.has(e[0])&&set.has(e[1])).map((e,i)=>({id:i,from:e[0],to:e[1],arrows:'to',
    width:Math.max(1,Math.log10(e[2])-3),title:`${kzt(e[2])} KZT, ${e[3]} перев.`,color:{color:'#999',opacity:.6},smooth:{type:'continuous'}}));
  if(net)net.destroy();
  net=new vis.Network(document.getElementById('net'),{nodes,edges},{physics:{solver:'forceAtlas2Based',stabilization:{iterations:200}},interaction:{hover:true,tooltipDelay:100}});
  net.once('stabilizationIterationsDone',()=>{net.setOptions({physics:false});if(focus){net.selectNodes([focus]);net.focus(focus,{scale:1.1,animation:true})}});
  net.on('click',p=>{if(p.nodes.length)card(p.nodes[0])});
  if(focus)card(focus);
}
function ego(id,h){const s=new Set([id]);let f=[id];for(let i=0;i<h;i++){const nf=[];f.forEach(v=>{(OUT.get(v)||[]).forEach(e=>{if(!s.has(e[1])){s.add(e[1]);nf.push(e[1])}});(IN.get(v)||[]).forEach(e=>{if(!s.has(e[0])){s.add(e[0]);nf.push(e[0])}})});f=nf}return[...s]}
function card(id){const n=N.get(id),c=document.getElementById('card');
  const outs=(OUT.get(id)||[]).sort((a,b)=>b[2]-a[2]).slice(0,5),ins=(IN.get(id)||[]).sort((a,b)=>b[2]-a[2]).slice(0,5);
  const lst=a=>a.map(e=>`<div>${sh(e[0]===id?e[1]:e[0])} · ${kzt(e[2])} (${e[3]})</div>`).join('')||'<div class="hint">нет</div>';
  c.innerHTML=`<h3>${id}</h3><div><span class="dot" style="background:${D.colors[n.role]}"></span><b>${D.roleRu[n.role]}</b> · уверенность ${n.rs} · приоритет ${n.pr}</div>
  <div class="ev">${n.ev}</div><div class="kv">
  <span>хоп / seed</span><span>${n.d} / ${n.seed?'да':'нет'}</span><span>кластер</span><span>${n.cl}</span>
  <span>вход</span><span>${kzt(n.ink)} от ${n.ind}</span><span>выход</span><span>${kzt(n.outk)} к ${n.outd}</span>
  <span>передал дальше</span><span>${pct(n.pt)}</span><span>ушло за ≤2 дня</span><span>${pct(n.fs)}</span>
  <span>меченые деньги</span><span>${kzt(n.ti)} (${pct(n.ts)})</span><span>блокировка срезает</span><span>${n.bi==null?'н/д':(n.bi*100).toFixed(1)+'%'} потока</span>
  <span>циклы ≤4</span><span>${n.cy}</span>${n.po!=null?`<span>P(дальше)</span><span>${pct(n.po)}</span>`:''}</div>
  <p class="hint" style="margin:8px 0 2px">Крупнейшие входящие</p>${lst(ins)}<p class="hint" style="margin:8px 0 2px">Крупнейшие исходящие</p>${lst(outs)}
  <p style="margin-top:8px"><button class="b" onclick="draw(ego('${id}',2),'${id}')">Окружение 2 хопа</button> <button class="b" onclick="document.getElementById('card').style.display='none'">×</button></p>`;
  c.style.display='block'}

document.getElementById('ttop').innerHTML='<tr><th>#</th><th>gid</th><th>роль</th><th>приор.</th></tr>'+D.top.map(t=>`<tr class="row" data-g="${t.gid}" title="${t.why.replace(/"/g,'&quot;')}"><td>${t.rank}</td><td>${t.gid}</td><td><span class="dot" style="background:${D.colors[t.role]}"></span>${D.roleRu[t.role]}</td><td>${t.priority_score.toFixed(3)}</td></tr>`).join('');
document.querySelectorAll('#ttop tr.row').forEach(r=>r.onclick=()=>draw(ego(r.dataset.g,1),r.dataset.g));

function search(){const q=document.getElementById('q').value.trim(),h=+document.getElementById('hops').value,box=document.getElementById('sres');
  if(!q)return;if(N.has(q)){box.innerHTML='';draw(ego(q,h),q);return}
  const m=D.nodes.filter(n=>n.id.includes(q)).slice(0,30);
  box.innerHTML=m.length?'<table>'+m.map(n=>`<tr class="row" data-g="${n.id}"><td>${n.id}</td><td>${D.roleRu[n.role]}</td></tr>`).join('')+'</table>':'<p>Не найдено</p>';
  box.querySelectorAll('tr.row').forEach(r=>r.onclick=()=>draw(ego(r.dataset.g,h),r.dataset.g))}
document.getElementById('go').onclick=search;document.getElementById('q').onkeydown=e=>{if(e.key==='Enter')search()};

document.getElementById('tcl').innerHTML='<tr><th>id</th><th>узл.</th><th>seed</th><th>гипотеза</th></tr>'+D.clusters.map(c=>`<tr class="row" data-c="${c.cluster_id}"><td>${c.cluster_id}</td><td>${c.n_nodes}</td><td>${c.n_seed}</td><td style="font-size:12px">${c.hypothesis}</td></tr>`).join('');
document.querySelectorAll('#tcl tr.row').forEach(r=>r.onclick=()=>{const cid=+r.dataset.c;const ids=D.nodes.filter(n=>n.cl===cid).map(n=>n.id);
  const top=ids.slice().sort((a,b)=>N.get(b).pr-N.get(a).pr)[0];draw(ids,top)});

(function(){const R=D.res,W=400,H=200,p=30,mx=R.length-1;
  const x=i=>p+(W-2*p)*i/mx,y=v=>H-p-(H-2*p)*v;
  const line=(k,c)=>`<polyline fill="none" stroke="${c}" stroke-width="2" points="${R.map((r,i)=>x(i)+','+y(r[k])).join(' ')}"/>`;
  document.getElementById('chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:420px">
  <line x1="${p}" y1="${H-p}" x2="${W-p}" y2="${H-p}" stroke="currentColor" opacity=".3"/><line x1="${p}" y1="${p}" x2="${p}" y2="${H-p}" stroke="currentColor" opacity=".3"/>
  ${line('tainted_flow_left','#d62728')}${line('random_flow_left','#888')}
  <text x="${p}" y="${p-8}" font-size="11" fill="currentColor">100% потока</text><text x="${W-p}" y="${H-8}" font-size="11" text-anchor="end" fill="currentColor">N заблокировано → ${mx}</text>
  <text x="${W-p}" y="${p+12}" font-size="11" text-anchor="end" fill="#d62728">топ-N по приоритету</text><text x="${W-p}" y="${p+26}" font-size="11" text-anchor="end" fill="#888">N случайных</text></svg>`;
  document.getElementById('tres').innerHTML='<tr><th>N</th><th>осталось (топ)</th><th>осталось (случ.)</th><th>фрагментов</th></tr>'+R.filter(r=>[0,1,3,5,10,20,30].includes(r.n_blocked)).map(r=>`<tr><td>${r.n_blocked}</td><td>${pct(r.tainted_flow_left)}</td><td>${pct(r.random_flow_left)}</td><td>${r.n_components}</td></tr>`).join('')})();

draw(ego(D.top[0].gid,1),D.top[0].gid);
</script></body></html>
"""
