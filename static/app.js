/* dayloop — tabbed SPA. Talks to app.py; planner.py is the brain. */
const $  = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const api = {
  get:  async u => (await fetch(u)).json(),
  post: async (u, b) => (await fetch(u, {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(b||{})})).json(),
};
const TYPES = ["skill","achievement","influence","habit"];
const esc = s => (s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),1800);}
function toISO(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;}
function fromISO(s){const [y,m,dd]=s.split("-").map(Number);return new Date(y,m-1,dd);}
function busy(btn,on,label){if(on){btn.dataset.t=btn.textContent;btn.disabled=true;btn.innerHTML='<span class="spin"></span>'+(label||"…");}else{btn.disabled=false;btn.textContent=btn.dataset.t;}}

let STATE=null, GTYPE={}, GOALS=[], SHAPED={}, DRAINED=0;
let homeDate=new Date(); homeDate.setHours(0,0,0,0);
let calDate=new Date(); calDate.setHours(0,0,0,0);
let HOMEDAY=null;
const expanded=new Set();

const BUDDY=[
  "(  .  )",
  "( o o )",
  "( o o )\n |___|",
  "( ^ ^ )\n /|_|/",
  '( ^o^ )\n /|_|/\n  " "',
  '*( ^o^ )*\n /|_|/\n   db',
];
const STAGE=["a seed","hatching","standing","limber","thriving","radiant"];

/* ---------------- tabs ---------------- */
$$("#tabbar button").forEach(b=>b.onclick=()=>show(b.dataset.tab));
function show(tab){
  $$("#tabbar button").forEach(b=>b.classList.toggle("on",b.dataset.tab===tab));
  $$(".tab-view").forEach(v=>v.classList.remove("on"));
  $("#tab-"+tab).classList.add("on");
  if(tab==="home") loadHome();
  if(tab==="cal") loadCal();
  if(tab==="goals") loadGoals();
  if(tab==="journal") loadJournal();
}

/* ---------------- shared ---------------- */
async function loadState(){
  STATE=await api.get("/api/state");
  GTYPE={}; STATE.goals.forEach(g=>GTYPE[g.id]=g.type);
  const d=new Date();
  $("#masthead-meta").innerHTML=
    `${d.toLocaleDateString("en-US",{weekday:"short"})} ${toISO(d).slice(5)}<br>streak ${STATE.progress.streak}`;
  renderBuddy(STATE.progress);
}
function renderBuddy(p){
  $("#buddy").innerHTML=
    `<pre>${BUDDY[Math.min(p.stage,5)]}</pre>
     <div class="streak"><div class="n">${p.streak}</div><div class="u">day streak</div>
       <div class="note">${p.logged_today?"logged today":"not yet today"}</div></div>
     <div style="flex:1"><div class="na"><span class="l">stage ${p.stage} / 5 — ${STAGE[Math.min(p.stage,5)]}</span></div>
       <div class="note">grows with consistency + real progress</div></div>`;
}
function dotFor(goalId){
  const t=GTYPE[goalId];
  return TYPES.includes(t)?`<span class="dot ${t}"></span>`:"";
}

/* ---------------- schedule rendering ---------------- */
function renderSched(day, container, editable){
  container.innerHTML="";
  if(!day.blocks.length){container.innerHTML='<div class="empty">nothing scheduled.</div>';return;}
  day.blocks.forEach(b=>{
    const row=document.createElement("div");
    row.className="blk"+(b.event?" event":"");
    const tasks=SHAPED[b.name];
    row.innerHTML=
      `<div class="t">${b.start}–${b.end}</div>
       <div class="b">
         <span class="nm">${dotFor(b.goal)}${esc(b.name)}</span>
         <span class="k">${b.event?"event":(b.kind||"")}</span>
         ${tasks&&tasks.length?`<ul class="tasks">${tasks.map(t=>`<li>${esc(t)}</li>`).join("")}</ul>`:""}
         ${b.checkin?`<div class="ci"><button class="done">done</button><button class="skip">skip</button></div>`:""}
         ${b.event&&editable?`<button class="ghost del" style="margin-top:6px;padding:2px 8px">delete</button>`:""}
       </div>`;
    if(editable && !b.event){
      row.querySelector(".t").style.cursor="pointer";
      row.querySelector(".t").onclick=()=>editTime(b);
    }
    const ci=row.querySelector(".ci");
    if(ci){
      ci.querySelector(".done").onclick=e=>doCheckin(e.target,b.goal,1);
      ci.querySelector(".skip").onclick=e=>doCheckin(e.target,b.goal,0);
    }
    const del=row.querySelector(".del");
    if(del) del.onclick=()=>delEvent(b.id);
    container.appendChild(row);
  });
}
async function doCheckin(btn,goal,ok){
  btn.parentElement.querySelectorAll("button").forEach(x=>x.classList.remove("on"));
  btn.classList.add("on");
  const prog=await api.post("/api/checkin",{goal:goal||null,ok:!!ok});
  renderBuddy(prog); toast("logged");
}

/* ---------------- HOME ---------------- */
async function loadHome(){
  await loadState();
  $("#home-date").textContent = isToday(homeDate) ? "Today" :
    homeDate.toLocaleDateString("en-US",{weekday:"long",month:"short",day:"numeric"});
  HOMEDAY=await api.get("/api/day?date="+toISO(homeDate));
  renderSched(HOMEDAY,$("#home-sched"),true);
}
function isToday(d){return toISO(d)===toISO(new Date());}
$("#home-prev").onclick=()=>{homeDate.setDate(homeDate.getDate()-1);SHAPED={};loadHome();};
$("#home-next").onclick=()=>{homeDate.setDate(homeDate.getDate()+1);SHAPED={};loadHome();};

$("#home-shape").onclick=async e=>{
  busy(e.target,true,"shaping");
  const shaped=await api.post("/api/today");
  SHAPED={}; (shaped.schedule||[]).forEach(s=>SHAPED[s.block]=s.tasks);
  busy(e.target,false);
  renderSched(HOMEDAY,$("#home-sched"),true);
  toast(shaped.spillover&&shaped.spillover.length?("spillover: "+shaped.spillover.join(", ")):"today shaped");
};
$("#home-addblock").onclick=async()=>{
  const name=prompt("Block name?"); if(!name) return;
  const time=prompt("Time (start-end, 24h)","12:00-13:00")||"12:00-13:00";
  const [start,end]=time.split("-").map(s=>s.trim());
  HOMEDAY.blocks.push({id:"x"+Math.random().toString(36).slice(2,7),name,start,end,kind:"flex"});
  await saveHomeDay();
};
function editTime(b){
  const time=prompt("Time (start-end, 24h)",`${b.start}-${b.end}`); if(!time) return;
  const [start,end]=time.split("-").map(s=>s.trim());
  b.start=start; b.end=end; saveHomeDay();
}
async function saveHomeDay(){
  const blocks=HOMEDAY.blocks.filter(b=>!b.event);   // events stay in their own store
  await api.post("/api/day",{date:toISO(homeDate),blocks});
  loadHome(); toast("day saved");
}

/* daily journal → evening reveal (writes back + journals) */
$("#daily-good").onclick=()=>{DRAINED=0;$("#daily-good").classList.add("on");$("#daily-rough").classList.remove("on");};
$("#daily-rough").onclick=()=>{DRAINED=1;$("#daily-rough").classList.add("on");$("#daily-good").classList.remove("on");};
$("#daily-save").onclick=async e=>{
  const note=$("#daily-text").value.trim();
  if(!note){toast("write a line first");return;}
  busy(e.target,true,"writing");
  const r=await api.post("/api/evening",{note,drained:!!DRAINED});
  busy(e.target,false); $("#daily-text").value="";
  await loadState(); toast(r.note||"written back");
};

/* weekly check-in */
$("#weekly-open").onclick=async()=>{
  $("#weekly-panel").classList.remove("hide");
  $("#weekly-q").innerHTML='<span class="spin"></span>generating questions…';
  const q=await api.get("/api/questions");
  const parts=[];
  for(const [gid,qs] of Object.entries(q))
    parts.push(`<div class="q"><b>${esc(gid)}</b><br>${qs.map((t,i)=>`${i+1}. ${esc(t)}`).join("<br>")}</div>`);
  $("#weekly-q").innerHTML=parts.join("")||'<div class="q">No questions — just re-planning.</div>';
};
$("#weekly-cancel").onclick=()=>$("#weekly-panel").classList.add("hide");
$("#weekly-save").onclick=async e=>{
  busy(e.target,true,"re-deriving");
  await api.post("/api/plan",{answers:$("#weekly-text").value});
  busy(e.target,false); $("#weekly-panel").classList.add("hide"); $("#weekly-text").value="";
  await loadState(); toast("week re-derived");
};

/* ---------------- CALENDAR ---------------- */
let EVENTS=[];
async function loadCal(){
  EVENTS=await api.get("/api/events");
  renderStrip();
  renderCalDay();
  buildDayPickers();
}
function eventOn(ev,d){
  const iso=toISO(d);
  if(ev.date) return ev.date===iso;
  if(ev.recurrence&&ev.recurrence.freq==="weekly"){
    const wd=["sun","mon","tue","wed","thu","fri","sat"][d.getDay()];
    return (ev.recurrence.days||[]).map(x=>x.slice(0,3).toLowerCase()).includes(wd);
  }
  return false;
}
function renderStrip(){
  const el=$("#cal-strip"); el.innerHTML="";
  const base=new Date(); base.setHours(0,0,0,0);
  for(let i=0;i<21;i++){
    const d=new Date(base); d.setDate(base.getDate()+i);
    const has=EVENTS.some(ev=>eventOn(ev,d));
    const div=document.createElement("div");
    div.className="day"+(toISO(d)===toISO(calDate)?" sel":"");
    div.innerHTML=`<div class="wd">${d.toLocaleDateString("en-US",{weekday:"short"})}</div>
      <div class="dd">${d.getDate()}</div>${has?'<div class="pip"></div>':""}`;
    div.onclick=()=>{calDate=d;renderStrip();renderCalDay();};
    el.appendChild(div);
  }
}
async function renderCalDay(){
  const day=await api.get("/api/day?date="+toISO(calDate));
  $$("#tab-cal .label")[1].textContent =
    calDate.toLocaleDateString("en-US",{weekday:"long",month:"long",day:"numeric"});
  renderSched(day,$("#cal-day"),true);
}
function buildDayPickers(){
  const wrap=$("#ev-days");
  if(wrap.childElementCount) return;
  ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].forEach(d=>{
    const b=document.createElement("button"); b.className="ghost"; b.textContent=d; b.dataset.d=d.toLowerCase();
    b.onclick=()=>b.classList.toggle("on"); wrap.appendChild(b);
  });
  $("#ev-date").value=toISO(calDate);
}
$("#ev-kind").onchange=e=>{
  const weekly=e.target.value==="weekly";
  $("#ev-days-wrap").classList.toggle("hide",!weekly);
  $("#ev-date-wrap").classList.toggle("hide",weekly);
};
$("#ev-save").onclick=async()=>{
  const title=$("#ev-title").value.trim(); if(!title){toast("give it a title");return;}
  const body={title,start:$("#ev-start").value,end:$("#ev-end").value};
  if($("#ev-kind").value==="weekly"){
    const days=$$("#ev-days button.on").map(b=>b.dataset.d);
    if(!days.length){toast("pick a day");return;}
    body.recurrence={freq:"weekly",days};
  }else{ body.date=$("#ev-date").value||toISO(calDate); }
  await api.post("/api/events",body);
  $("#ev-title").value="";
  toast("event added"); loadCal();
};
async function delEvent(id){
  if(!confirm("Delete this event?")) return;
  await api.post("/api/events/delete",{id}); toast("deleted");
  if($("#tab-cal").classList.contains("on")) loadCal(); else loadHome();
}

/* ---------------- GOALS ---------------- */
async function loadGoals(){
  await loadState();
  GOALS=await api.get("/api/goals");
  renderTree();
}
function nextActionFor(id){const g=STATE.goals.find(x=>x.id===id);return g&&g.next_action;}
function renderTree(){
  const el=$("#goal-tree"); el.innerHTML="";
  GOALS.forEach((g,gi)=>{
    const open=expanded.has(g.id);
    const node=document.createElement("div"); node.className="gnode";
    const priCls=g.priority===1?"p1":g.priority===3?"p3":"p2";
    const priTxt=g.priority===1?"high":g.priority===3?"low":"med";
    node.innerHTML=
      `<div class="gh">
         <span class="disc">${open?"▾":"▸"}</span>
         ${dotForType(g.type)}<span class="gid">${esc(g.id)}</span>
         <span class="type">${esc(g.type)}</span>
         <span class="pri ${priCls}">${priTxt}</span>
       </div>`;
    node.querySelector(".gh").onclick=(e)=>{
      if(e.target.classList.contains("pri")){cyclePriority(gi);return;}
      open?expanded.delete(g.id):expanded.add(g.id); renderTree();
    };
    if(open){
      const body=document.createElement("div"); body.className="gbody";
      const na=nextActionFor(g.id);
      body.innerHTML=
        `<div class="why" data-w>${esc(g.why)||'<span class="empty">why? (tap to add)</span>'}</div>
         ${na?`<div class="na"><span class="l">current next action</span>${esc(na)}</div>`:""}
         <div class="chips">${(g.levers||[]).map(l=>`<span class="chip">${esc(l)}</span>`).join("")}
           <span class="chip" data-addlever style="cursor:pointer">+ lever</span></div>
         <div style="margin-top:10px">${(g.subgoals||[]).map((s,si)=>
           `<div class="sub ${s.done?"done":""}"><span class="box" data-sub="${si}">${s.done?"[x]":"[ ]"}</span><span class="txt">${esc(s.title)}</span></div>`).join("")}
           <div class="sub"><span class="box" data-addsub style="cursor:pointer">[+]</span><span class="txt" style="color:var(--muted)">add subgoal</span></div>
         </div>
         <div class="row" style="margin-top:10px"><button class="ghost" data-del>delete goal</button></div>`;
      body.querySelector("[data-w]").onclick=()=>{const v=prompt("Why this goal?",g.why||"");if(v!=null){g.why=v;renderTree();}};
      body.querySelector("[data-addlever]").onclick=()=>{const v=prompt("Lever / weak spot?");if(v){(g.levers=g.levers||[]).push(v);renderTree();}};
      body.querySelector("[data-addsub]").onclick=()=>{const v=prompt("Subgoal?");if(v){(g.subgoals=g.subgoals||[]).push({title:v,done:false});renderTree();}};
      body.querySelectorAll("[data-sub]").forEach(el2=>el2.onclick=()=>{const i=+el2.dataset.sub;g.subgoals[i].done=!g.subgoals[i].done;renderTree();});
      body.querySelector("[data-del]").onclick=()=>{if(confirm("Delete goal "+g.id+"?")){GOALS.splice(gi,1);expanded.delete(g.id);renderTree();}};
      node.appendChild(body);
    }
    el.appendChild(node);
  });
}
function dotForType(t){return TYPES.includes(t)?`<span class="dot ${t}"></span>`:"";}
function cyclePriority(gi){GOALS[gi].priority=(GOALS[gi].priority%3)+1;renderTree();}
$("#goal-add").onclick=()=>{
  const id=prompt("Goal id (short, e.g. thesis)?"); if(!id) return;
  const type=(prompt("Type — habit / skill / achievement / influence?","skill")||"skill").trim();
  const why=prompt("Why?","")||"";
  GOALS.push({id,type,why,priority:2,levers:[],subgoals:[]});
  expanded.add(id); renderTree();
};
$("#goal-save").onclick=async e=>{busy(e.target,true,"saving");await api.post("/api/goals",GOALS);busy(e.target,false);toast("tree saved");};

/* ---------------- JOURNAL ---------------- */
async function loadJournal(){
  const entries=await api.get("/api/journal");
  const el=$("#journal-list");
  if(!entries.length){el.innerHTML='<div class="empty">no entries yet — write one on the home tab.</div>';return;}
  el.innerHTML=entries.map(e=>
    `<div class="jentry"><div class="jm"><span class="kind">${esc(e.kind)}</span>
       <span>${esc(e.date)}</span></div>
       <div class="jt">${esc(e.text||"")}</div></div>`).join("");
}

/* ---------------- boot ---------------- */
loadHome();
if("serviceWorker" in navigator)
  window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}));
