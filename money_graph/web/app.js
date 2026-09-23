"use strict";

const $ = id => document.getElementById(id);
const number = new Intl.NumberFormat("ru-RU");
const fmt = value => number.format(Math.round(Number(value) || 0));
const money = value => fmt(value) + " KZT";
const SHAPES = ["pictogram", "dot", "diamond", "star", "hexagon", "square", "triangle", "triangleDown", "box", "ellipse"];
const DEFAULT_SHAPES = {coordinator:"star",consolidator:"hexagon",distributor:"triangle",transit:"diamond",terminal:"square",truncated:"triangleDown",peripheral:"dot"};
const ICON_MARKS = {
  coordinator:'<circle cx="24" cy="24" r="5" fill="white"/><circle cx="13" cy="13" r="3" fill="white"/><circle cx="35" cy="13" r="3" fill="white"/><circle cx="13" cy="35" r="3" fill="white"/><circle cx="35" cy="35" r="3" fill="white"/><path d="M16 16 21 21M32 16 27 21M16 32 21 27M32 32 27 27" stroke="white" stroke-width="2"/>',
  consolidator:'<path d="M9 12 24 24 39 12M9 36 24 24 39 36" fill="none" stroke="white" stroke-width="3"/><circle cx="24" cy="24" r="5" fill="white"/>',
  distributor:'<path d="M10 24h25M26 15l10 9-10 9" fill="none" stroke="white" stroke-width="4"/><circle cx="12" cy="24" r="4" fill="white"/>',
  transit:'<path d="M8 24h32m-8-8 8 8-8 8M16 16l-8 8 8 8" fill="none" stroke="white" stroke-width="3"/>',
  terminal:'<path d="M12 12h24v24H12z" fill="none" stroke="white" stroke-width="3"/><path d="M17 24h14" stroke="white" stroke-width="3"/>',
  truncated:'<path d="M10 24h20m-7-8 8 8-8 8" fill="none" stroke="white" stroke-width="3"/><path d="M38 9v30" stroke="white" stroke-width="3" stroke-dasharray="4 4"/>',
  peripheral:'<circle cx="24" cy="24" r="9" fill="none" stroke="white" stroke-width="3"/>'
};
function pictogram(role,color) {
  const svg='<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><rect x="3" y="3" width="42" height="42" rx="12" fill="'+color+'"/>'+(ICON_MARKS[role]||ICON_MARKS.peripheral)+'</svg>';
  return 'data:image/svg+xml,'+encodeURIComponent(svg);
}
const state = {data:null,caseId:"demo",selected:null,tab:"top",cluster:null,network:null,hidden:new Set(),extras:new Set(),positions:{},pinned:new Set(),shapes:{...DEFAULT_SHAPES},nodes:new Map(),incoming:new Map(),outgoing:new Map()};

function el(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}
function append(parent, tag, cls, value) { const node=el(tag,cls,value); parent.append(node); return node; }
function clear(node) { node.replaceChildren(); }
function status(message, error=false) { $("status").textContent=message; $("status").classList.toggle("error",error); }
function roleName(role) { return state.data.role_names[role] || role; }
function rolePill(role) { const pill=el("span","role-pill",roleName(role)); pill.style.background=state.data.colors[role] || "#667c89"; return pill; }
function storageKey() { return "moneygraph-layout-"+state.caseId; }
function saveWorkspace() {
  try { localStorage.setItem(storageKey(),JSON.stringify({positions:state.positions,pinned:[...state.pinned],shapes:state.shapes})); } catch (_) { /* browser storage can be disabled */ }
}
function restoreWorkspace() {
  let saved={}; try { saved=JSON.parse(localStorage.getItem(storageKey()) || "{}"); } catch (_) { /* ignore corrupt storage */ }
  state.positions=saved.positions || {};
  state.pinned=new Set(saved.pinned || []);
  state.shapes={...DEFAULT_SHAPES,...(saved.shapes || {})};
}
function rememberPositions() {
  if (!state.network) return;
  for (const [id, xy] of Object.entries(state.network.getPositions())) state.positions[id]=xy;
  saveWorkspace();
}
async function api(url, options) {
  const response=await fetch(url,options);
  if (!response.ok) {
    let message="Ошибка сервера " + response.status;
    try { const body=await response.json(); message=body.detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}
async function loadCases(preferred) {
  const cases=await api("/api/cases");
  const select=$("case-select"); clear(select);
  for (const item of cases) { const option=el("option","",item.label); option.value=item.id; select.append(option); }
  const id=cases.some(item=>item.id===preferred) ? preferred : "demo";
  select.value=id;
  await loadCase(id);
}
async function loadCase(id) {
  status("Загружаем граф кейса…");
  const data=await api("/api/cases/"+encodeURIComponent(id)+"/graph");
  if (state.network) { state.network.destroy(); state.network=null; }
  state.data=data; state.caseId=id; state.hidden=new Set(); state.extras=new Set(); state.cluster=null; state.tab="top";
  state.nodes=new Map(data.nodes.map(node=>[node.gid,node]));
  state.incoming=new Map(); state.outgoing=new Map();
  for (const edge of data.edges) {
    if (!state.outgoing.has(edge[0])) state.outgoing.set(edge[0],[]);
    if (!state.incoming.has(edge[1])) state.incoming.set(edge[1],[]);
    state.outgoing.get(edge[0]).push(edge); state.incoming.get(edge[1]).push(edge);
  }
  restoreWorkspace();
  state.selected=data.top[0]?.gid || data.nodes[0]?.gid || null;
  $("case-select").value=id;
  $("search").value=""; $("role-filter").value=""; $("seed-only").checked=false;
  $("hops").value="1"; $("direction").value="both";
  history.replaceState(null,"",id==="demo"?"/":"/?case="+id);
  renderAll();
  status(data.label+" · "+fmt(data.summary.nodes)+" узлов · расчёт "+data.summary.runtime_sec+" с");
}
function renderAll() { renderSummary(); renderTabs(); renderList(); renderCard(); renderShapes(); renderGraph(); renderModel(); renderDownloads(); }
function renderSummary() {
  const s=state.data.summary;
  $("m-nodes").textContent=fmt(s.nodes); $("m-seeds").textContent=fmt(s.seeds ?? state.data.nodes.filter(n=>n.is_seed).length);
  $("m-transactions").textContent=fmt(s.transactions ?? state.data.edges.reduce((a,e)=>a+e[3],0));
  $("m-clusters").textContent=fmt(s.clusters);
  const dateLabel=value=>value ? new Intl.DateTimeFormat("ru-RU",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(new Date(value+"T00:00:00Z")) : "—";
  $("m-period").textContent=dateLabel(s.period_start)+" — "+dateLabel(s.period_end);
  $("m-edges").textContent=fmt(state.data.edges.length)+" связей между клиентами";
  $("m-boundary").textContent="Обход до "+(s.max_depth ?? 4)+" хопов · от "+fmt(s.min_tx_kzt ?? 5000)+" KZT";
  const legend=$("graph-legend"); clear(legend);
  for (const [role,name] of Object.entries(state.data.role_names)) {
    const item=append(legend,"span","legend-item");
    const dot=append(item,"i"); dot.style.background=state.data.colors[role];
    append(item,"span","",name);
  }
  const roles=$("role-filter"); clear(roles);
  const all=el("option","","Все роли"); all.value=""; roles.append(all);
  for (const role of Object.keys(state.data.role_names)) {
    if (!state.data.nodes.some(n=>n.role===role)) continue;
    const option=el("option","",roleName(role)); option.value=role; roles.append(option);
  }
}
function renderTabs() { document.querySelectorAll(".tab").forEach(button=>button.classList.toggle("active",button.dataset.tab===state.tab)); }
function activateNode(gid, keepCluster=false) {
  if (!state.nodes.has(gid)) return;
  rememberPositions();
  state.selected=gid;
  if (!keepCluster) state.cluster=null;
  renderList(); renderCard(); renderGraph();
}
function rowButton(parent, title, note, handler, active=false) {
  const button=append(parent,"button","row"+(active?" active":"")); button.type="button";
  const head=append(button,"div","row-head"); append(head,"span","",title);
  if (note) append(button,"div","row-note",note);
  button.addEventListener("click",handler);
  return button;
}
function renderList() {
  if (!state.data) return;
  const list=$("list"); clear(list);
  const q=$("search").value.trim();
  if (state.tab==="clusters") {
    const clusters=state.data.clusters.slice().sort((a,b)=>b.n_seed-a.n_seed || b.n_nodes-a.n_nodes);
    for (const cluster of clusters) {
      if (q && !String(cluster.top_gids).includes(q) && !String(cluster.cluster_id).includes(q)) continue;
      rowButton(list,"Кластер "+cluster.cluster_id+" · "+fmt(cluster.n_nodes)+" узлов",
        fmt(cluster.n_seed)+" seed · "+cluster.hypothesis,()=>{
          rememberPositions(); state.cluster=cluster.cluster_id; state.selected=String(cluster.top_gids).split(";")[0]; renderList();renderCard();renderGraph();
        },state.cluster===cluster.cluster_id);
    }
  } else if (state.tab==="requests") {
    for (const req of state.data.requests) {
      if (q && !req.gid.includes(q)) continue;
      rowButton(list,req.gid,req.reason,()=>activateNode(req.gid),req.gid===state.selected);
    }
  } else {
    const role=$("role-filter").value, seeds=$("seed-only").checked;
    const nodes=state.data.nodes.filter(n=>(!q || n.gid.includes(q)) && (!role || n.role===role) && (!seeds || n.is_seed))
      .sort((a,b)=>b.priority_score-a.priority_score || a.gid.localeCompare(b.gid)).slice(0,150);
    for (const [index,node] of nodes.entries()) {
      const button=rowButton(list,node.gid,node.evidence,
        ()=>activateNode(node.gid),node.gid===state.selected);
      button.firstChild.append(rolePill(node.role));
      const score=el("div","priority-caption","№ "+(index+1)+" в списке · приоритет "+Number(node.priority_score).toFixed(3)+" / 1");
      button.insertBefore(score,button.children[1]);
    }
  }
  if (!list.childElementCount) append(list,"p","muted","Ничего не найдено. Измените поиск или фильтр.");
  $("search-hint").textContent=q ? "Найденные gid показаны в списке" : "Поиск по всем "+fmt(state.data.nodes.length)+" узлам";
}
function detail(parent,label,value) { append(parent,"span","",label);append(parent,"span","",value); }
function connectionSection(parent,title,edges,incoming) {
  append(parent,"div","section-title",title);
  if (!edges.length) { append(parent,"small","","Нет связей в выгрузке"); return; }
  for (const edge of edges.slice().sort((a,b)=>b[2]-a[2]).slice(0,6)) {
    const gid=incoming?edge[0]:edge[1];
    const button=append(parent,"button","link-row",gid);
    append(button,"span","",money(edge[2])+" · "+fmt(edge[3])+" переводов");
    button.addEventListener("click",()=>activateNode(gid));
  }
}
function renderCard() {
  const card=$("node-card"); clear(card);
  const n=state.nodes.get(state.selected);
  if (!n) { append(card,"p","muted","Выберите узел."); return; }
  append(card,"small","","gid · клиент в обезличенной выгрузке");
  append(card,"div","gid",n.gid);
  const badges=append(card,"div","card-sub"); badges.append(rolePill(n.role));
  append(badges,"small","",n.is_seed?"Seed · хоп "+n.depth:"Хоп "+n.depth);
  append(card,"div","evidence",n.evidence);
  if (n.role==="truncated") append(card,"div","warning","Исходящие за границей обхода не наблюдались. Узел нельзя считать конечным получателем.");
  const kv=append(card,"div","kv");
  detail(kv,"Приоритет проверки",Number(n.priority_score).toFixed(3)+" / 1"); detail(kv,"Сила признаков роли",Math.round(n.role_score*100)+" / 100");
  detail(kv,"Кластер",n.cluster_id);detail(kv,"Плательщиков",fmt(n.in_deg));detail(kv,"Получателей",fmt(n.out_deg));
  detail(kv,"Входящий поток",money(n.in_kzt));detail(kv,"Исходящий поток",money(n.out_kzt));
  detail(kv,"Посредничество",Number(n.betweenness||0).toFixed(4));
  detail(kv,"Связь с seed",fmt(n.seed_sources)+" источников");
  if (n.p_onward!==null && !Number.isNaN(n.p_onward)) detail(kv,"Вероятность следующего хопа",Math.round(n.p_onward*100)+"%");
  const actions=append(card,"div","card-actions");
  const focus=append(actions,"button","button","Показать окружение");focus.addEventListener("click",()=>{state.cluster=null;renderGraph();});
  const go=append(actions,"a","button","Перейти к графу");go.href="#network-panel";
  const copy=append(actions,"button","button","Скопировать gid");copy.addEventListener("click",()=>navigator.clipboard.writeText(n.gid));
  connectionSection(card,"Крупнейшие входящие",state.incoming.get(n.gid)||[],true);
  connectionSection(card,"Крупнейшие исходящие",state.outgoing.get(n.gid)||[],false);
  $("pin-node").checked=state.pinned.has(n.gid);
}
function neighbours(start,hops,direction) {
  const found=new Set([start]);let frontier=[start];
  for (let depth=0;depth<hops;depth++) {
    const next=[];
    for (const id of frontier) {
      const links=[];
      if (direction!=="in") links.push(...(state.outgoing.get(id)||[]));
      if (direction!=="out") links.push(...(state.incoming.get(id)||[]));
      links.sort((a,b)=>b[2]-a[2]);
      for (const edge of links) {
        const other=edge[0]===id?edge[1]:edge[0];
        if (!found.has(other) && found.size<220) {found.add(other);next.push(other);}
      }
    }
    frontier=next;
  }
  return found;
}
function visibleIds() {
  let ids;
  if (state.cluster!==null) ids=new Set(state.data.nodes.filter(n=>n.cluster_id===state.cluster)
    .sort((a,b)=>b.priority_score-a.priority_score).slice(0,220).map(n=>n.gid));
  else ids=neighbours(state.selected,Number($("hops").value),$("direction").value);
  for (const id of state.extras) if (ids.size<220) ids.add(id);
  for (const id of state.hidden) ids.delete(id);
  return ids;
}
function renderShapes() {
  const root=$("shape-settings");clear(root);
  const labels={pictogram:"Пиктограмма",dot:"Круг",diamond:"Ромб",star:"Звезда",hexagon:"Шестиугольник",square:"Квадрат",triangle:"Треугольник",triangleDown:"Треугольник вниз",box:"Блок",ellipse:"Овал"};
  for (const [role,name] of Object.entries(state.data.role_names)) {
    const row=append(root,"label","shape-row");const swatch=append(row,"i");swatch.style.background=state.data.colors[role];append(row,"span","",name);
    const select=append(row,"select");select.setAttribute("aria-label","Форма роли "+name);
    for (const shape of SHAPES) {const option=append(select,"option","",labels[shape]);option.value=shape;}
    select.value=state.shapes[role]||"dot";
    select.addEventListener("change",()=>{state.shapes[role]=select.value;saveWorkspace();renderGraph();});
  }
}
function renderGraph() {
  if (!state.selected) return;
  rememberPositions();
  const ids=visibleIds(), flow=$("layout").value==="flow";
  $("graph-empty").hidden=ids.size>0;
  $("graph-empty").textContent="Все узлы скрыты. Нажмите «Вернуть».";
  $("graph-heading").textContent=state.cluster===null?"Связи выбранного клиента":"Кластер "+state.cluster;
  $("graph-subtitle").textContent="gid "+state.selected+" · стрелки показывают направление переводов";
  $("graph-count").textContent=fmt(ids.size)+" узлов на схеме · максимум 220 для читаемости";
  const vertices=[...ids].map(id=>{
    const n=state.nodes.get(id), xy=state.positions[id], selected=id===state.selected;
    const shape=state.shapes[n.role]||"dot";
    const vertex={id,label:$("node-labels").checked?id.slice(-7):"",title:id+" · "+roleName(n.role)+" · "+money(n.in_kzt),
      shape:shape==="pictogram"?"image":shape,size:11+15*Number(n.priority_score||0),level:n.depth,
      color:{background:state.data.colors[n.role]||"#607887",border:n.is_seed?"#152c3b":"#ffffff",highlight:{background:state.data.colors[n.role],border:"#132c3b"}},
      borderWidth:n.is_seed?4:2,borderWidthSelected:5,
      shapeProperties:{borderDashes:n.role==="truncated"?[4,3]:false,useBorderWithImage:true},
      font:{size:13,color:"#233e4b",strokeWidth:3,strokeColor:"#fff"},fixed:state.pinned.has(id)};
    if (xy && !flow) {vertex.x=xy.x;vertex.y=xy.y;}
    if (shape==="pictogram") vertex.image=pictogram(n.role,state.data.colors[n.role]||"#607887");
    if (selected) vertex.borderWidth=5;
    return vertex;
  });
  const links=state.data.edges.filter(e=>ids.has(e[0])&&ids.has(e[1])).map((e,i)=>({
    id:i,from:e[0],to:e[1],arrows:{to:{enabled:true,scaleFactor:.6}},
    width:Math.max(1,Math.min(5,Math.log10(Math.max(e[2],1))-2)),
    label:$("edge-labels").checked?fmt(e[2]):"",font:{size:9,color:"#5f7581",strokeWidth:3,strokeColor:"#fff"},
    title:money(e[2])+" · "+fmt(e[3])+" переводов",color:{color:"#7c95a2",opacity:.7},smooth:{type:"continuous",roundness:.12}
  }));
  if (state.network) state.network.destroy();
  state.network=new vis.Network($("graph"),{nodes:vertices,edges:links},{
    autoResize:true,
    layout:flow?{hierarchical:{enabled:true,direction:"LR",sortMethod:"directed",levelSeparation:130,nodeSpacing:95}}:{randomSeed:42,improvedLayout:true},
    physics:flow?false:{enabled:!Object.keys(state.positions).some(id=>ids.has(id)),solver:"forceAtlas2Based",stabilization:{iterations:120}},
    interaction:{hover:true,tooltipDelay:150,dragNodes:true,dragView:true,zoomView:true,multiselect:false},
    nodes:{chosen:true}
  });
  if (ids.has(state.selected)) state.network.selectNodes([state.selected]);
  state.network.on("click",event=>{if(event.nodes.length)activateNode(String(event.nodes[0]),state.cluster!==null);});
  state.network.on("dragEnd",()=>rememberPositions());
  const network=state.network;
  network.once("stabilized",()=>{if(state.network!==network)return;network.setOptions({physics:false});network.fit({animation:false});rememberPositions();});
  requestAnimationFrame(()=>{if(state.network===network){network.redraw();network.fit({animation:false});}});
}
function renderModel() {
  const root=$("model-chart");clear(root);
  const rows=state.data.resilience;
  if (!rows.length) {append(root,"p","muted","Нет сценарных данных.");return;}
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 500 145");svg.setAttribute("role","img");svg.setAttribute("aria-label","Доля потока после исключения приоритетных и случайных узлов");
  const add=(tag,attrs)=>{const node=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,String(v));svg.append(node);return node;};
  for(const y of [0,.5,1]) {const py=118-y*95;add("line",{x1:35,y1:py,x2:485,y2:py,stroke:"#e0e8eb"});const t=add("text",{x:3,y:py+3,fill:"#718592","font-size":10});t.textContent=Math.round(y*100)+"%";}
  const max=rows[rows.length-1].n_blocked||1;
  for(const [key,color] of [["tainted_flow_left","#b54d3a"],["random_flow_left","#4384a4"]]) {
    const points=rows.map(r=>(35+r.n_blocked/max*450)+","+(118-r[key]*95)).join(" ");add("polyline",{points,fill:"none",stroke:color,"stroke-width":3,"stroke-linecap":"round","stroke-linejoin":"round"});
  }
  root.append(svg);
  const legend=append(root,"small","","Красная линия — приоритетные узлы · синяя — случайные. По оси X: число исключённых узлов.");legend.style.padding="0";
}
function renderDownloads() {
  const root=$("downloads");clear(root);
  for (const [file,label] of [["nodes_roles.csv","Роли и приоритет"],["clusters.csv","Кластеры"],["top_nodes.csv","Топ узлов"],["requests.csv","Запросы данных"],["resilience.csv","Сценарий"]]) {
    const link=append(root,"a","",label+" ↗");link.href="/api/cases/"+state.caseId+"/exports/"+file;link.download=file;
  }
}
function search() {
  state.tab="top";renderTabs();renderList();
  const q=$("search").value.trim();
  if (!q) return;
  const matches=state.data.nodes.filter(n=>n.gid.includes(q)).sort((a,b)=>b.priority_score-a.priority_score);
  if (matches.length) {activateNode(matches[0].gid);status("Найдено "+fmt(matches.length)+" узлов. Открыт первый по приоритету.");}
  else status("Gid не найден в выбранном кейсе.",true);
}

document.querySelectorAll(".tab").forEach(button=>button.addEventListener("click",()=>{state.tab=button.dataset.tab;renderTabs();renderList();}));
$("case-select").addEventListener("change",async event=>{try{await loadCase(event.target.value);}catch(error){status(error.message,true);}});
$("search-go").addEventListener("click",search);
$("search").addEventListener("keydown",event=>{if(event.key==="Enter")search();});
$("search").addEventListener("input",renderList);
$("role-filter").addEventListener("change",renderList);
$("seed-only").addEventListener("change",renderList);
for(const id of ["direction","hops","layout","node-labels","edge-labels"]) $(id).addEventListener("change",renderGraph);
$("fit").addEventListener("click",()=>state.network?.fit({animation:true}));
$("expand").addEventListener("click",()=>{for(const id of neighbours(state.selected,1,"both"))state.extras.add(id);renderGraph();});
$("hide-node").addEventListener("click",()=>{if(state.selected){state.hidden.add(state.selected);renderGraph();}});
$("restore").addEventListener("click",()=>{state.hidden.clear();state.extras.clear();renderGraph();});
$("pin-node").addEventListener("change",event=>{if(event.target.checked)state.pinned.add(state.selected);else state.pinned.delete(state.selected);rememberPositions();renderGraph();});
$("reset-layout").addEventListener("click",()=>{state.positions={};state.pinned.clear();saveWorkspace();renderGraph();});
$("upload-open").addEventListener("click",()=>$("upload-dialog").showModal());
$("upload-close").addEventListener("click",()=>$("upload-dialog").close());
$("upload-form").addEventListener("submit",async event=>{
  event.preventDefault();const submit=$("upload-submit");submit.disabled=true;submit.textContent="Проверяем и рассчитываем…";
  $("upload-error").hidden=true;status("Проверяем файлы и пересчитываем граф…");
  try {
    const result=await api("/api/cases",{method:"POST",body:new FormData(event.target)});
    $("upload-dialog").close();event.target.reset();await loadCases(result.id);
  } catch(error) {$("upload-error").textContent=error.message;$("upload-error").hidden=false;status(error.message,true);}
  finally {submit.disabled=false;submit.textContent="Проверить и рассчитать";}
});
loadCases(new URLSearchParams(location.search).get("case")||"demo").catch(error=>status(error.message,true));
