"use strict";

let view="investigation", workspaceVersion=0;
document.body.dataset.stage="graph";
function setStage(next) {
  document.body.dataset.stage=next;
  document.querySelectorAll("button[data-stage]").forEach(item=>item.setAttribute("aria-pressed",String(item.dataset.stage===next)));
  requestAnimationFrame(()=>{state.network?.redraw();state.network?.fit();});
}
document.querySelectorAll("button[data-stage]").forEach(button=>button.addEventListener("click",()=>setStage(button.dataset.stage)));
const selections=new Map();
const jsonOptions=body=>({method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
const caseUrl=()=>"/api/cases/"+encodeURIComponent(state.caseId);
const selectedGids=()=>{
  if(!selections.has(state.caseId)) selections.set(state.caseId,new Set());
  return selections.get(state.caseId);
};
const timestamp=value=>value ? new Date(value).toLocaleString("ru-RU") : "";
function message(id,text,error=false) { $(id).textContent=text;$(id).classList.toggle("error-message",error); }
function listItems(data) { return Array.isArray(data)?data:(data.items||[]); }

function showLogin(error="") {
  workspaceVersion++; session.generation++;session.user=null;session.csrf=null;
  state.loadVersion++;state.txVersion++;state.loadController?.abort();state.network?.destroy();state.network=null;
  state.data=null;state.nodes.clear();state.incoming.clear();state.outgoing.clear();state.workspaces.clear();selections.clear();
  state.positions={};state.hidden.clear();state.extras.clear();state.pinned.clear();state.selected=null;state.focus=null;state.tx=null;state.caseId="demo";
  state.loading=false;
  assistant.statusVersion++;assistant.configured=false;assistant.checked=false;assistant.availabilityError=false;
  resetAssistant(true);
  for(const id of ["assistant-result","assistant-error","assistant-availability","assistant-selection","assistant-selection-hint"]) clear($(id));
  $("assistant-panel").inert=true;
  $("workspace").inert=true;
  for(const id of ["list","node-card","case-select","report-list","report-selection","document-list","ask-sources","ask-answer","audit-list","user-list","user-message","developer-info","selected-evidence","graph-heading","graph-subtitle","case-overview","downloads","transaction-rows","transaction-pair","status","model-chart","graph-count","graph-legend","data-notice","m-nodes","m-edges","m-seeds","m-transactions","m-clusters","m-period","m-boundary"]) clear($(id));
  document.querySelectorAll("details[open]").forEach(details=>details.open=false);
  for(const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  $("application").hidden=true;$("login-screen").hidden=false;
  $("login-error").textContent=error;$("login-error").hidden=!error;
  document.querySelectorAll("form").forEach(form=>form.reset());
  document.querySelectorAll(".platform-page").forEach(page=>page.inert=false);
  $("selection-count").textContent="0";
}
window.addEventListener("auth-expired",()=>showLogin("Сессия завершена. Войдите снова."));

async function enterWorkspace(info,expectedGeneration=session.generation) {
  if(expectedGeneration!==session.generation)return;
  session.generation++;session.user=info.user;session.csrf=info.csrf_token;workspaceVersion++;
  const generation=session.generation;
  $("login-form").reset();$("login-screen").hidden=true;$("application").hidden=false;
  $("account-name").textContent=info.user.username+(info.user.role==="admin"?" · администратор":" · аналитик");
  document.querySelectorAll("[data-admin]").forEach(item=>item.hidden=info.user.role!=="admin");
  await setView("investigation",false);
  if(generation!==session.generation)return;
  if(info.user.must_change_password) {$("password-dialog").showModal();return;}
  loadAssistantStatus();
  await loadCases(new URLSearchParams(location.search).get("case")||"demo");
}
$("login-form").addEventListener("submit",async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;$("login-error").hidden=true;
  const generation=session.generation;
  try { const info=await api("/api/auth/login",jsonOptions(Object.fromEntries(new FormData(event.target))));await enterWorkspace(info,generation); }
  catch(error) {$("login-error").textContent=error.message;$("login-error").hidden=false;}
  finally {button.disabled=false;}
});
$("logout").addEventListener("click",async()=>{
  try {await api("/api/auth/logout",{method:"POST"});showLogin();history.replaceState(null,"","/");}
  catch(error) {status("Не удалось завершить серверную сессию: "+error.message,true);}
});
$("password-open").addEventListener("click",()=>$("password-dialog").showModal());
$("password-close").addEventListener("click",()=>{if(!session.user?.must_change_password) $("password-dialog").close();});
$("password-dialog").addEventListener("cancel",event=>{if(session.user?.must_change_password)event.preventDefault();});
$("password-form").addEventListener("submit",async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try {await api("/api/auth/password",jsonOptions(Object.fromEntries(new FormData(event.target))));showLogin("Пароль изменён. Войдите с новым паролем.");}
  catch(error) {message("password-message",error.message,true);}
  finally {button.disabled=false;}
});

async function setView(next,refresh=true) {
  if(["admin","developer"].includes(next)&&session.user?.role!=="admin") return;
  view=next;
  if(next!=="admin")clear($("user-message"));
  document.querySelectorAll("[data-page]").forEach(page=>page.hidden=page.dataset.page!==next);
  document.querySelectorAll("[data-view]").forEach(button=>{if(button.dataset.view===next)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");});
  if(next==="investigation") requestAnimationFrame(()=>{state.network?.redraw();state.network?.fit();});
  if(!refresh) return;
  try {
    if(next==="reports") {renderSelection();await refreshReports();}
    if(next==="knowledge") await refreshDocuments();
    if(next==="admin") await refreshUsers();
    if(next==="developer") {
      const version=workspaceVersion;const data=await api(caseUrl()+"/developer");
      if(version===workspaceVersion) $("developer-info").textContent=JSON.stringify(data,null,2);
    }
  } catch(error) {status(error.message,true);}
}
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>setView(button.dataset.view)));
window.addEventListener("case-loading",()=>{workspaceVersion++;});
window.addEventListener("case-loaded",()=>{
  workspaceVersion++;selections.set(state.caseId,selections.get(state.caseId)||new Set());
  $("inspector-panel").open=false;
  for(const id of ["ask-answer","ask-sources","report-message","document-message","report-list","audit-list","developer-info"]) clear($(id));
  $("report-form").reset();$("ask-form").reset();renderSelection();setView(view);
});
window.addEventListener("node-selected",event=>{
  $("report-selected").textContent=selectedGids().has(state.selected)?"✓ В отчёте":"+ В отчёт";
  if(event.detail.userInitiated && matchMedia("(max-width:699px)").matches&&document.body.dataset.stage==="priority") {
    setStage("graph");requestAnimationFrame(()=>$("network-panel").scrollIntoView({behavior:"smooth",block:"start"}));
  }
});
$("inspect-open").addEventListener("click",()=>{$("inspector-panel").open=true;$("inspector-panel").scrollIntoView({behavior:"smooth",block:"start"});});
function addSelection(gid) {
  if(!state.nodes.has(gid)) return;
  if(selectedGids().size>=30&&!selectedGids().has(gid)) {status("В один отчёт можно добавить до 30 клиентов.",true);return;}
  selectedGids().add(gid);renderSelection();
}
$("report-selected").addEventListener("click",()=>{
  addSelection(state.selected);status("Клиент добавлен. Откройте «Отчёты», чтобы сохранить версию с обоснованиями и схемой.");
});
$("select-top").addEventListener("click",()=>{for(const node of (state.data?.top||[]).slice(0,5))addSelection(node.gid);});
function renderSelection() {
  const selected=selectedGids();$("selection-count").textContent=String(selected.size);
  $("report-selected").textContent=selected.has(state.selected)?"✓ В отчёте":"+ В отчёт";
  const target=$("report-selection");clear(target);
  if(!selected.size) append(target,"p","muted","Добавьте клиентов из расследования или начните с топ-5. Выбор подтверждает аналитик.");
  for(const gid of selected) {
    const node=state.nodes.get(gid);if(!node) continue;
    const row=append(target,"div","selection-item"),text=append(row,"div");append(text,"strong","",gid);append(text,"small","",roleName(node.role)+" · приоритет "+node.priority_score);
    const remove=append(row,"button","button","Убрать");remove.type="button";remove.setAttribute("aria-label","Убрать "+gid+" из отчёта");remove.addEventListener("click",()=>{selected.delete(gid);renderSelection();});
  }
}
async function refreshReports() {
  const version=workspaceVersion;const base=caseUrl();
  const [reports,audit]=await Promise.all([api(base+"/reports"),api(base+"/audit")]);
  if(version!==workspaceVersion) return;
  const target=$("report-list");clear(target);
  for(const report of listItems(reports).slice().reverse()) {
    const row=append(target,"article","saved-item");append(row,"strong","",report.title);append(row,"small","","Версия "+report.version+" · "+timestamp(report.created_at));
    const actions=append(row,"div","card-actions");
    const preview=append(actions,"a","button primary","Открыть / PDF");preview.href=base+"/reports/"+encodeURIComponent(report.id)+"/view";preview.target="_blank";preview.rel="noopener noreferrer";
    for(const [format,label] of [["html","Отчёт со схемой"],["md","Markdown"],["json","JSON"]]) {
      const link=append(actions,"a","button",label);link.href=base+"/reports/"+encodeURIComponent(report.id)+"/download?format="+format;link.download="";
    }
  }
  if(!listItems(reports).length) append(target,"p","muted","Отчётов пока нет. Сохраните первую версию слева.");
  const history=$("audit-list");clear(history);
  for(const entry of listItems(audit).slice(-30).reverse()) append(history,"p","",timestamp(entry.created_at||entry.timestamp)+" · "+(entry.action||entry.event||"Изменение")+(entry.title?" · "+entry.title:""));
}
$("report-form").addEventListener("submit",async event=>{
  event.preventDefault();if(!selectedGids().size){message("report-message","Выберите хотя бы одного клиента.",true);return;}
  const version=workspaceVersion;const button=event.submitter;button.disabled=true;
  try {
    const result=await api(caseUrl()+"/reports",jsonOptions({title:$("report-title").value,selected_gids:[...selectedGids()],notes:$("report-notes").value}));
    if(version!==workspaceVersion)return;
    message("report-message","Сохранена версия "+result.version+". Отчёт доступен для скачивания справа.");await refreshReports();
  } catch(error){if(version===workspaceVersion)message("report-message",error.message,true);}
  finally {button.disabled=false;}
});

async function refreshDocuments() {
  const version=workspaceVersion;const docs=await api(caseUrl()+"/documents");if(version!==workspaceVersion)return;
  const target=$("document-list");clear(target);
  for(const doc of listItems(docs)) {
    const row=append(target,"article","saved-item");append(row,"strong","",doc.title);append(row,"small","",timestamp(doc.created_at));
    const remove=append(row,"button","button","Удалить документ");remove.type="button";
    remove.addEventListener("click",async()=>{
      if(!confirm("Удалить документ «"+doc.title+"» из этого кейса? Сохранённые отчёты останутся."))return;
      try{await api(caseUrl()+"/documents/"+encodeURIComponent(doc.id),{method:"DELETE"});await refreshDocuments();}catch(error){message("document-message",error.message,true);}
    });
  }
  if(!listItems(docs).length)append(target,"p","muted","Добавьте текст запроса или рабочую заметку. В поиске уже доступны метрики текущего кейса.");
}
$("document-form").addEventListener("submit",async event=>{
  event.preventDefault();const version=workspaceVersion;const file=$("document-file").files[0];
  if(!file||file.size>2*1024*1024){message("document-message","Выберите TXT/MD до 2 МБ.",true);return;}
  const button=event.submitter;button.disabled=true;
  try{await api(caseUrl()+"/documents",{method:"POST",body:new FormData(event.target)});if(version!==workspaceVersion)return;event.target.reset();message("document-message","Документ сохранён в вашем кейсе.");await refreshDocuments();}
  catch(error){if(version===workspaceVersion)message("document-message",error.message,true);}
  finally{button.disabled=false;}
});
$("ask-form").addEventListener("submit",async event=>{
  event.preventDefault();const version=workspaceVersion;const button=event.submitter;button.disabled=true;
  message("ask-answer","Ищем в источниках этого кейса…");clear($("ask-sources"));
  try {
    const result=await api(caseUrl()+"/ask",jsonOptions({question:$("ask-question").value}));if(version!==workspaceVersion)return;
    message("ask-answer",result.answer);
    for(const source of result.sources||[]) {
      const row=append($("ask-sources"),"article","saved-item");append(row,"span","source-tag","Источник "+source.id+" · "+source.kind);append(row,"strong","",source.title);append(row,"p","",source.excerpt);
    }
  }catch(error){if(version===workspaceVersion)message("ask-answer",error.message,true);}
  finally{button.disabled=false;}
});

async function refreshUsers() {
  const version=workspaceVersion;const users=await api("/api/admin/users");if(version!==workspaceVersion)return;
  const target=$("user-list");clear(target);
  for(const user of listItems(users)) {
    const row=append(target,"article","saved-item");append(row,"strong","",user.username);append(row,"small","",(user.role==="admin"?"Администратор":"Аналитик")+((user.disabled||user.is_active===false)?" · отключён":""));
    if(user.id!==session.user.id&&!user.disabled&&user.is_active!==false) {
      const disable=append(row,"button","button","Отключить доступ");disable.type="button";
      disable.addEventListener("click",async()=>{
        if(!confirm("Отключить учётную запись «"+user.username+"» и завершить её сессии?"))return;
        try{await api("/api/admin/users/"+encodeURIComponent(user.id)+"/disable",{method:"POST"});await refreshUsers();}catch(error){message("user-message",error.message,true);}
      });
    }
  }
}
$("user-form").addEventListener("submit",async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try {
    const result=await api("/api/admin/users",jsonOptions(Object.fromEntries(new FormData(event.target))));
    const target=$("user-message");clear(target);append(target,"p","","Создан "+result.user.username+". Одноразово показанный пароль:");append(target,"code","one-time-secret",result.temporary_password);append(target,"small","","Передайте пользователю лично. Не добавляйте в Git и не показывайте на публичном демо.");event.target.reset();await refreshUsers();
  }catch(error){message("user-message",error.message,true);}
  finally{button.disabled=false;}
});

// Remove legacy graph layout caches containing gids; private workspaces are kept in memory only.
try {for(const key of Object.keys(localStorage))if(key.startsWith("moneygraph-layout-"))localStorage.removeItem(key);}catch(_){}
const bootGeneration=session.generation;
$("login-form").querySelector("button[type=submit]").disabled=true;
api("/api/auth/me").then(info=>enterWorkspace(info,bootGeneration)).catch(error=>{if(session.user)status(error.message,true);else if(session.generation===bootGeneration)showLogin();}).finally(()=>{$("login-form").querySelector("button[type=submit]").disabled=false;});
window.addEventListener("pageshow",event=>{if(event.persisted)location.reload();});
document.addEventListener("visibilitychange",async()=>{
  if(document.hidden||!session.user)return;
  const expected=session.user.id;
  try {
    const info=await api("/api/auth/me");
    if(info.user.id!==expected) showLogin("Аккаунт изменился в другой вкладке. Войдите снова.");
  }catch(_){/* api clears an expired session; a temporary network error does not sign out. */}
});
