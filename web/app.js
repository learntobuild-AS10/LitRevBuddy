const DATA_ROOT = "./data";
const state = {
  manifest: null,
  clusters: [],
  indexes: new Map(),
  detailShards: new Map(),
  route: "search",
  query: "",
  years: new Set(),
  venues: new Set(),
  visible: 15,
  rendered: [],
  keyboardIndex: -1,
  activePaper: null,
  saved: new Set(JSON.parse(localStorage.getItem("lrb:saved") || "[]").map(Number)),
  recent: JSON.parse(localStorage.getItem("lrb:recent") || "[]").map(Number),
  theme: localStorage.getItem("lrb:theme") || "dark",
  storyCards: [],
  storyIndex: 0,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (value = "") => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const normalize = (value = "") => String(value).toLowerCase().replace(/[^a-z0-9%]+/g, " ").trim();
const tokens = value => normalize(value).split(/\s+/).filter(Boolean);
const debounce = (fn, wait = 160) => { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); }; };

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 1800);
}

async function fetchJSON(path) {
  const response = await fetch(path, { cache: "force-cache" });
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json();
}

async function boot() {
  document.documentElement.dataset.theme = state.theme;
  bindGlobalUI();
  showLoading();

  try {
    state.manifest = await fetchJSON(`${DATA_ROOT}/manifest.json`);
    state.clusters = await fetchJSON(`${DATA_ROOT}/clusters.json`);
    state.years.add(state.manifest.latest_year);
    await loadYear(state.manifest.latest_year);
    hydrateMeta();
    renderDaily();
    renderResults();
    renderTopics();
    renderAbout();
    routeFromHash();
  } catch (error) {
    console.error(error);
    $("#resultsList").innerHTML = `<div class="empty">The paper catalog has not been built yet. Run <code>python scripts/build_web_catalog.py</code> or let the GitHub Pages workflow build it.</div>`;
  }
}

function showLoading() {
  $("#dailyStack").innerHTML = Array.from({length:5}, () => '<div class="skeleton"></div>').join("");
  $("#resultsList").innerHTML = Array.from({length:4}, () => '<div class="skeleton"></div>').join("");
}

async function loadYear(year) {
  year = Number(year);
  if (state.indexes.has(year)) return state.indexes.get(year);
  const filename = state.manifest.index_files[String(year)];
  const data = await fetchJSON(`${DATA_ROOT}/${filename}`);
  state.indexes.set(year, data);
  return data;
}

async function loadSelectedYears() {
  await Promise.all([...state.years].map(loadYear));
}

function allLoadedPapers() {
  return [...state.indexes.values()].flat();
}

function hydrateMeta() {
  $("#paperCountHero").textContent = state.manifest.num_papers.toLocaleString();
  $("#savedCount").textContent = state.saved.size;
  $("#yearFilterBtn").textContent = state.years.size === 1 ? `${[...state.years][0]} ▾` : `${state.years.size} years ▾`;
}

function scorePaper(paper, query) {
  const q = normalize(query);
  if (!q) return 0;
  const qs = tokens(q);
  const title = normalize(paper.t);
  const abstract = normalize(paper.s);
  const authors = normalize(paper.a);
  const cluster = normalize(paper.cl);
  let score = title.includes(q) ? 120 : 0;
  if (abstract.includes(q)) score += 38;
  for (const term of qs) {
    if (title.includes(term)) score += 24;
    if (authors.includes(term)) score += 10;
    if (cluster.includes(term)) score += 8;
    if (abstract.includes(term)) score += 5;
    if (normalize(paper.v).includes(term)) score += 10;
  }
  score += Math.max(0, paper.y - 2023) * .25;
  return score;
}

function filteredPapers() {
  const papers = allLoadedPapers().filter(p => !state.venues.size || state.venues.has(p.v));
  if (!state.query.trim()) return papers.sort((a,b) => b.y-a.y || a.t.localeCompare(b.t));
  return papers
    .map(p => ({ paper:p, score:scorePaper(p,state.query) }))
    .filter(x => x.score > 0)
    .sort((a,b) => b.score-a.score)
    .map(x => ({...x.paper,_score:x.score}));
}

function paperCard(paper, index = 0, compact = false) {
  const saved = state.saved.has(Number(paper.id));
  const score = paper._score ? `<span class="score">relevance ${paper._score.toFixed(0)}</span>` : "";
  return `
    <article class="paper-card" data-paper-id="${paper.id}" data-index="${index}">
      <div>
        <div class="paper-meta"><span>${esc(paper.v)}</span><span>·</span><span>${paper.y}</span>${score}</div>
        <h3 data-open-paper="${paper.id}">${esc(paper.t)}</h3>
        ${compact ? "" : `<p>${esc(paper.s || "Abstract preview unavailable.")}</p>`}
      </div>
      <div class="paper-actions">
        <button class="action-btn primary" data-open-paper="${paper.id}">Open</button>
        <button class="action-btn ${saved ? "saved" : ""}" data-save-paper="${paper.id}">${saved ? "Saved" : "Save"}</button>
      </div>
    </article>`;
}

function renderResults() {
  const results = filteredPapers();
  state.rendered = results;
  state.keyboardIndex = -1;
  const showing = results.slice(0,state.visible);

  $("#resultsEyebrow").textContent = state.query ? `${results.length.toLocaleString()} matches` : "Fresh papers";
  $("#resultsTitle").textContent = state.query ? `Results for “${state.query}”` : "Recent work worth browsing";
  $("#resultsList").innerHTML = showing.length
    ? showing.map((p,i) => paperCard(p,i)).join("")
    : '<div class="empty">No papers match this search. Try fewer terms or broaden the filters.</div>';
  $("#loadMoreBtn").hidden = state.visible >= results.length;
  renderActiveFilters();
}

function renderActiveFilters() {
  const bits = [...state.years].map(y => `<span class="filter-pill">${y}</span>`);
  if (state.venues.size) bits.push(...[...state.venues].map(v => `<span class="filter-pill">${esc(v)}</span>`));
  $("#activeFilters").innerHTML = bits.join("");
}

function dailySeed() {
  const d = new Date();
  return Number(`${d.getUTCFullYear()}${String(d.getUTCMonth()+1).padStart(2,"0")}${String(d.getUTCDate()).padStart(2,"0")}`);
}
function seededRandom(seed) {
  let t = seed + 0x6D2B79F5;
  return () => {
    t += 0x6D2B79F5;
    let r = Math.imul(t ^ t >>> 15, 1 | t);
    r ^= r + Math.imul(r ^ r >>> 7, 61 | r);
    return ((r ^ r >>> 14) >>> 0) / 4294967296;
  };
}
function renderDaily() {
  const pool = state.indexes.get(state.manifest.latest_year) || [];
  const rng = seededRandom(dailySeed());
  const picks = [];
  const used = new Set();
  while (picks.length < Math.min(5,pool.length)) {
    const idx = Math.floor(rng()*pool.length);
    if (!used.has(idx)) { used.add(idx); picks.push(pool[idx]); }
  }
  $("#dailyStack").innerHTML = picks.map((p,i) => `
    <article class="daily-card" data-open-paper="${p.id}">
      <span class="number">0${i+1}</span>
      <h3>${esc(p.t)}</h3>
      <p>${esc(p.s)}</p>
      <div class="meta">${esc(p.v)} · ${p.y}</div>
    </article>`).join("");
}

function surprise() {
  const pool = allLoadedPapers();
  if (!pool.length) return;
  openPaper(pool[Math.floor(Math.random()*pool.length)].id);
}

async function detailFor(paper) {
  const key = `${paper.y}:${paper.v}`;
  if (!state.detailShards.has(key)) {
    const path = state.manifest.detail_files[key];
    if (!path) return paper;
    state.detailShards.set(key, await fetchJSON(`${DATA_ROOT}/${path}`));
  }
  return state.detailShards.get(key)[String(paper.id)] || paper;
}

function findLoadedPaper(id) {
  id = Number(id);
  for (const year of state.indexes.values()) {
    const found = year.find(p => Number(p.id) === id);
    if (found) return found;
  }
  return null;
}

async function ensurePaper(id) {
  let paper = findLoadedPaper(id);
  if (paper) return paper;
  await Promise.all(state.manifest.years.map(loadYear));
  return findLoadedPaper(id);
}

async function openPaper(id) {
  const lite = await ensurePaper(id);
  if (!lite) return;
  const paper = await detailFor(lite);
  state.activePaper = paper;
  addRecent(paper.id);

  const related = allLoadedPapers()
    .filter(p => p.id !== paper.id && p.c === paper.c)
    .slice(0,5);

  $("#drawerContent").innerHTML = `
    <div class="drawer-meta">${esc(paper.v)} · ${paper.y} · ${esc(paper.cl)}</div>
    <h2 class="drawer-title">${esc(paper.t)}</h2>
    <div class="drawer-authors">${esc(paper.a || "Authors unavailable")}</div>
    <div class="drawer-actions">
      <button class="action-btn primary" id="storyFromPaper">Story</button>
      <button class="action-btn ${state.saved.has(Number(paper.id)) ? "saved" : ""}" data-save-paper="${paper.id}">${state.saved.has(Number(paper.id)) ? "Saved" : "Save"}</button>
      ${paper.p ? `<a class="action-btn" href="${esc(paper.p)}" target="_blank" rel="noopener">Paper ↗</a>` : ""}
      ${paper.pdf ? `<a class="action-btn" href="${esc(paper.pdf)}" target="_blank" rel="noopener">PDF ↗</a>` : ""}
    </div>
    <section class="drawer-section">
      <h3>Abstract</h3>
      <p>${esc(paper.abstract || paper.s || "Abstract unavailable.")}</p>
    </section>
    <section class="drawer-section">
      <h3>Follow the thread</h3>
      <div class="related-row">
        ${related.map(r => `<button class="related-item" data-open-paper="${r.id}"><strong>${esc(r.t)}</strong><br><span>${esc(r.v)} · ${r.y}</span></button>`).join("") || "<p>No nearby papers loaded yet.</p>"}
      </div>
    </section>`;

  $("#paperDrawer").classList.add("open");
  $("#paperDrawer").setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
  $("#storyFromPaper")?.addEventListener("click", () => openStory(paper));
}

function closeDrawer() {
  $("#paperDrawer").classList.remove("open");
  $("#paperDrawer").setAttribute("aria-hidden","true");
  if (!$("#storyModal").classList.contains("open")) document.body.style.overflow = "";
}

function splitSentences(text) {
  return (text || "")
    .replace(/\s+/g," ")
    .match(/[^.!?]+[.!?]+|[^.!?]+$/g)?.map(s=>s.trim()).filter(s=>s.length>28) || [];
}

function extractiveCards(paper) {
  const sentences = splitSentences(paper.abstract || paper.s);
  if (!sentences.length) return [];
  const pick = (regex, fallback) => sentences.find(s => regex.test(s)) || sentences[fallback] || sentences[0];
  const candidates = [
    ["Problem", pick(/challenge|problem|limited|limitation|difficult|however|despite/i,0)],
    ["Core idea", pick(/we propose|we present|we introduce|we develop|our method|our approach/i,1)],
    ["How it works", pick(/using|through|via|consists|framework|architecture|module|encoder|decoder/i,2)],
    ["Evidence", pick(/outperform|achiev|improv|result|accuracy|auc|dice|significant|%/i,Math.max(0,sentences.length-2))],
    ["Takeaway", sentences[sentences.length-1]],
  ];
  const seen = new Set();
  return candidates.filter(([,body]) => {
    const key = normalize(body);
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  }).map(([label,body]) => ({
    label,
    headline: label === "Problem" ? "What this paper is trying to solve"
      : label === "Core idea" ? "The central move"
      : label === "How it works" ? "The mechanism in one step"
      : label === "Evidence" ? "What the abstract reports"
      : "What to remember",
    body,
    evidence: body,
  }));
}

function renderStory() {
  const paper = state.activePaper;
  const cards = state.storyCards;
  if (!paper || !cards.length) {
    $("#storyContent").innerHTML = '<div class="story-stage"><div class="empty">No source cards could be extracted from this paper.</div></div>';
    return;
  }
  state.storyIndex = Math.max(0,Math.min(state.storyIndex,cards.length-1));
  const card = cards[state.storyIndex];
  $("#storyContent").innerHTML = `
    <div class="story-stage">
      <div class="story-heading">
        <div class="eyebrow">${esc(paper.v)} · ${paper.y}</div>
        <h2>${esc(paper.t)}</h2>
        <p>Source-only card · ${state.storyIndex+1} of ${cards.length}</p>
      </div>
      <article class="story-card">
        <div class="story-step">${esc(card.label)}</div>
        <h3>${esc(card.headline)}</h3>
        <p>${esc(card.body)}</p>
        <div class="story-source">Source: abstract · exact sentence from the paper</div>
      </article>
      <div class="story-controls">
        <button class="secondary-btn" id="storyPrev" ${state.storyIndex===0?"disabled":""}>← Previous</button>
        <div class="story-dots">${cards.map((_,i)=>i===state.storyIndex?"●":"○").join(" ")}</div>
        <button class="secondary-btn" id="storyNext" ${state.storyIndex===cards.length-1?"disabled":""}>Next →</button>
      </div>
    </div>`;
  $("#storyPrev")?.addEventListener("click",()=>{state.storyIndex--;renderStory()});
  $("#storyNext")?.addEventListener("click",()=>{state.storyIndex++;renderStory()});
}

async function openStory(paper) {
  state.activePaper = paper;
  state.storyCards = extractiveCards(paper);
  state.storyIndex = 0;
  $("#storyModal").classList.add("open");
  $("#storyModal").setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
  $("#extractiveStoryBtn").classList.add("active");
  $("#aiStoryBtn").classList.remove("active");
  renderStory();
}

function closeStory() {
  $("#storyModal").classList.remove("open");
  $("#storyModal").setAttribute("aria-hidden","true");
  if (!$("#paperDrawer").classList.contains("open")) document.body.style.overflow = "";
}

function normalizeEvidence(value) {
  return normalize(value).replace(/\s+/g," ");
}

async function aiStory() {
  const paper = state.activePaper;
  if (!paper) return;
  let key = sessionStorage.getItem("lrb:openrouter-key") || "";
  if (!key) {
    $("#storyContent").innerHTML = `
      <div class="story-stage">
        <div class="ai-connect">
          <div class="eyebrow">Optional AI mode</div>
          <h2>Use your free OpenRouter key</h2>
          <p>Your key stays in this browser session and is sent directly to OpenRouter. LitRevBuddy does not store it.</p>
          <input id="orKey" type="password" placeholder="sk-or-v1-…" autocomplete="off" />
          <button id="connectAI" class="action-btn primary">Generate AI story</button>
          <button id="cancelAI" class="action-btn">Use source cards instead</button>
        </div>
      </div>`;
    $("#connectAI").addEventListener("click",()=>{
      const entered=$("#orKey").value.trim();
      if(!entered) return;
      sessionStorage.setItem("lrb:openrouter-key",entered);
      aiStory();
    });
    $("#cancelAI").addEventListener("click",()=>{ $("#extractiveStoryBtn").click(); });
    return;
  }

  $("#storyContent").innerHTML='<div class="story-stage"><div class="empty">Generating a concise, source-grounded story…</div></div>';
  const prompt = `Create 4-6 concise study cards from ONLY this abstract. Return JSON exactly as {"cards":[{"label":"Problem|Core idea|Method|Evidence|Limitation|Takeaway","headline":"max 12 words","body":"max 55 words","evidence":"an exact sentence copied from the abstract"}]}. Do not invent facts. ABSTRACT:\n${paper.abstract || paper.s}`;

  try {
    const response = await fetch("https://openrouter.ai/api/v1/chat/completions",{
      method:"POST",
      headers:{
        "Authorization":`Bearer ${key}`,
        "Content-Type":"application/json",
        "HTTP-Referer":location.origin,
        "X-Title":"LitRevBuddy"
      },
      body:JSON.stringify({
        model:"openrouter/free",
        messages:[{role:"user",content:prompt}],
        temperature:.2
      })
    });
    if(!response.ok) throw new Error("Free model request failed");
    const payload=await response.json();
    const raw=payload.choices?.[0]?.message?.content || "";
    const match=raw.match(/\{[\s\S]*\}/);
    if(!match) throw new Error("No JSON returned");
    const parsed=JSON.parse(match[0]);
    const sourceNorm=normalizeEvidence(paper.abstract || paper.s);
    const verified=(parsed.cards || []).filter(card=>{
      const evidence=normalizeEvidence(card.evidence || "");
      return evidence.length>20 && sourceNorm.includes(evidence);
    }).slice(0,6);
    if(verified.length<2) throw new Error("Too few cards could be verified");
    state.storyCards=verified;
    state.storyIndex=0;
    renderStory();
  } catch(error) {
    console.error(error);
    toast("AI route unavailable — showing source cards");
    sessionStorage.removeItem("lrb:openrouter-key");
    state.storyCards=extractiveCards(paper);
    state.storyIndex=0;
    $("#extractiveStoryBtn").classList.add("active");
    $("#aiStoryBtn").classList.remove("active");
    renderStory();
  }
}

function toggleSave(id) {
  id=Number(id);
  if(state.saved.has(id)){state.saved.delete(id);toast("Removed from saved")}
  else{state.saved.add(id);toast("Saved")}
  localStorage.setItem("lrb:saved",JSON.stringify([...state.saved]));
  $("#savedCount").textContent=state.saved.size;
  renderResults();
  if(state.route==="saved") renderSaved();
  if(state.activePaper?.id===id) openPaper(id);
}

function addRecent(id) {
  id=Number(id);
  state.recent=[id,...state.recent.filter(x=>x!==id)].slice(0,12);
  localStorage.setItem("lrb:recent",JSON.stringify(state.recent));
}

async function renderSaved() {
  await Promise.all(state.manifest.years.map(loadYear));
  const all=allLoadedPapers();
  const saved=all.filter(p=>state.saved.has(Number(p.id)));
  $("#savedList").innerHTML=saved.length?saved.map((p,i)=>paperCard(p,i)).join(""):'<div class="empty">Save a paper and it will show up here.</div>';
  const recent=state.recent.map(id=>all.find(p=>Number(p.id)===Number(id))).filter(Boolean);
  $("#recentList").innerHTML=recent.length?recent.map((p,i)=>paperCard(p,i,true)).join(""):'<div class="empty">Your reading trail will appear here.</div>';
}

function renderTopics() {
  $("#topicGrid").innerHTML=state.clusters.map(c=>`
    <article class="topic-card" data-cluster="${c.id}">
      <div class="topic-count">${c.papers.toLocaleString()} papers</div>
      <h3>${esc(c.label)}</h3>
      <p>${esc(c.venues.slice(0,4).join(" · "))}</p>
    </article>`).join("");
}

function renderMap() {
  const canvas=$("#topicMap");
  const box=canvas.getBoundingClientRect();
  const ratio=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.floor(box.width*ratio);
  canvas.height=Math.floor(box.height*ratio);
  const ctx=canvas.getContext("2d");
  ctx.scale(ratio,ratio);
  ctx.clearRect(0,0,box.width,box.height);

  const papers=(state.indexes.get(state.manifest.latest_year)||[]);
  const sample=papers.length>2200?papers.filter((_,i)=>i%Math.ceil(papers.length/2200)===0):papers;
  const xs=sample.map(p=>p.x), ys=sample.map(p=>p.z);
  const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  const pad=26;
  state.mapPoints=sample.map(p=>({
    p,
    sx:pad+(p.x-minX)/(maxX-minX||1)*(box.width-pad*2),
    sy:pad+(p.z-minY)/(maxY-minY||1)*(box.height-pad*2)
  }));
  const style=getComputedStyle(document.documentElement);
  ctx.fillStyle=style.getPropertyValue("--muted").trim();
  ctx.globalAlpha=.42;
  state.mapPoints.forEach(pt=>{ctx.beginPath();ctx.arc(pt.sx,pt.sy,2.2,0,Math.PI*2);ctx.fill()});
  ctx.globalAlpha=1;
}

function renderAbout(){
  const m=state.manifest;
  $("#coverageStats").innerHTML=[
    [m.num_papers.toLocaleString(),"papers"],
    [m.venues.length,"venues"],
    [m.years.length,"years"],
    [m.num_clusters,"topic neighborhoods"],
  ].map(([value,label])=>`<div class="stat"><strong>${value}</strong><span>${label}</span></div>`).join("");
}

function showPopover(button, type) {
  const pop=$("#menuPopover");
  const rect=button.getBoundingClientRect();
  let options=[];
  if(type==="year"){
    options=state.manifest.years.map(y=>({label:String(y),active:state.years.has(y),value:y}));
  }else{
    options=state.manifest.venues.map(v=>({label:v,active:state.venues.has(v),value:v}));
  }
  pop.innerHTML=options.map(o=>`<button class="${o.active?"active":""}" data-pop-type="${type}" data-pop-value="${esc(o.value)}">${o.active?"✓ ":""}${esc(o.label)}</button>`).join("");
  pop.hidden=false;
  pop.style.top=`${rect.bottom+8}px`;
  pop.style.left=`${Math.min(rect.left,innerWidth-pop.offsetWidth-12)}px`;
}

async function handlePopoverChoice(type,value){
  if(type==="year"){
    const year=Number(value);
    if(state.years.has(year)&&state.years.size>1)state.years.delete(year);else state.years.add(year);
    await loadSelectedYears();
  }else{
    if(state.venues.has(value))state.venues.delete(value);else state.venues.add(value);
  }
  hydrateMeta();renderResults();$("#menuPopover").hidden=true;
}

function setRoute(route) {
  state.route=route;
  location.hash=route==="search"?"":route;
  $$(".view").forEach(v=>v.classList.toggle("active",v.dataset.view===route));
  $$(".nav-link").forEach(n=>n.classList.toggle("active",n.dataset.route===route));
  if(route==="saved")renderSaved();
  if(route==="explore")setTimeout(renderMap,50);
  $("#main").focus({preventScroll:true});
}

function routeFromHash(){
  const route=(location.hash.replace("#","").split("/")[0]||"search");
  setRoute(["search","explore","saved","about"].includes(route)?route:"search");
}

function highlightKeyboard(index){
  const cards=$$("#resultsList .paper-card");
  cards.forEach(c=>c.classList.remove("keyboard-active"));
  if(!cards.length)return;
  state.keyboardIndex=Math.max(0,Math.min(index,cards.length-1));
  const card=cards[state.keyboardIndex];
  card.classList.add("keyboard-active");
  card.scrollIntoView({block:"nearest",behavior:"smooth"});
}

function bindGlobalUI(){
  document.addEventListener("click",async event=>{
    const route=event.target.closest("[data-route]")?.dataset.route;
    if(route){setRoute(route);return}
    const open=event.target.closest("[data-open-paper]")?.dataset.openPaper;
    if(open){openPaper(open);return}
    const save=event.target.closest("[data-save-paper]")?.dataset.savePaper;
    if(save){toggleSave(save);return}
    const cluster=event.target.closest("[data-cluster]")?.dataset.cluster;
    if(cluster){
      state.query=state.clusters.find(c=>String(c.id)===String(cluster))?.label||"";
      $("#searchInput").value=state.query;setRoute("search");renderResults();window.scrollTo({top:0,behavior:"smooth"});return
    }
    if(event.target.closest("[data-close-drawer]"))closeDrawer();
    if(event.target.closest("[data-close-story]"))closeStory();
    if(!event.target.closest(".popover")&&!event.target.closest(".filter-btn"))$("#menuPopover").hidden=true;
  });

  $("#searchInput").addEventListener("input",debounce(async e=>{
    state.query=e.target.value.trim();state.visible=15;
    await loadSelectedYears();renderResults();
    $("#resultsSection").scrollIntoView({block:"start",behavior:"smooth"});
  },120));

  $$(".chip").forEach(btn=>btn.addEventListener("click",()=>{
    state.query=btn.dataset.query;$("#searchInput").value=state.query;renderResults();$("#resultsSection").scrollIntoView({behavior:"smooth"});
  }));
  $("#loadMoreBtn").addEventListener("click",()=>{state.visible+=15;renderResults()});
  $("#surpriseBtn").addEventListener("click",surprise);
  $("#surpriseHeader").addEventListener("click",surprise);
  $("#yearFilterBtn").addEventListener("click",e=>showPopover(e.currentTarget,"year"));
  $("#venueFilterBtn").addEventListener("click",e=>showPopover(e.currentTarget,"venue"));
  $("#menuPopover").addEventListener("click",e=>{
    const btn=e.target.closest("[data-pop-type]");
    if(btn)handlePopoverChoice(btn.dataset.popType,btn.dataset.popValue);
  });

  $("#themeToggle").addEventListener("click",()=>{
    state.theme=state.theme==="dark"?"light":"dark";
    document.documentElement.dataset.theme=state.theme;
    localStorage.setItem("lrb:theme",state.theme);
    if(state.route==="explore")renderMap();
  });

  $$(".tab-btn").forEach(btn=>btn.addEventListener("click",()=>{
    $$(".tab-btn").forEach(b=>b.classList.toggle("active",b===btn));
    $$(".explore-panel").forEach(p=>p.classList.remove("active"));
    $(btn.dataset.exploreTab==="map"?"#mapPanel":"#topicsPanel").classList.add("active");
    if(btn.dataset.exploreTab==="map")setTimeout(renderMap,30);
  }));

  $("#topicMap").addEventListener("click",event=>{
    if(!state.mapPoints?.length)return;
    const rect=event.currentTarget.getBoundingClientRect();
    const x=event.clientX-rect.left,y=event.clientY-rect.top;
    const nearest=state.mapPoints.reduce((best,pt)=>{
      const d=(pt.sx-x)**2+(pt.sy-y)**2;
      return !best||d<best.d?{pt,d}:best;
    },null);
    if(nearest&&nearest.d<400)openPaper(nearest.pt.p.id);
  });
  $("#topicMap").addEventListener("mousemove",event=>{
    if(!state.mapPoints?.length)return;
    const rect=event.currentTarget.getBoundingClientRect();
    const x=event.clientX-rect.left,y=event.clientY-rect.top;
    const nearest=state.mapPoints.reduce((best,pt)=>{
      const d=(pt.sx-x)**2+(pt.sy-y)**2;
      return !best||d<best.d?{pt,d}:best;
    },null);
    const tip=$("#mapTooltip");
    if(nearest&&nearest.d<225){
      tip.hidden=false;tip.textContent=nearest.pt.p.t;tip.style.left=`${Math.min(x+12,rect.width-290)}px`;tip.style.top=`${Math.max(8,y-12)}px`;
    }else tip.hidden=true;
  });

  $("#extractiveStoryBtn").addEventListener("click",()=>{
    $("#extractiveStoryBtn").classList.add("active");$("#aiStoryBtn").classList.remove("active");
    state.storyCards=extractiveCards(state.activePaper);state.storyIndex=0;renderStory();
  });
  $("#aiStoryBtn").addEventListener("click",()=>{
    $("#aiStoryBtn").classList.add("active");$("#extractiveStoryBtn").classList.remove("active");aiStory();
  });

  window.addEventListener("hashchange",routeFromHash);
  window.addEventListener("resize",debounce(()=>{if(state.route==="explore"&&!$("#mapPanel").hidden)renderMap()},150));

  document.addEventListener("keydown",event=>{
    if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==="k"){event.preventDefault();setRoute("search");$("#searchInput").focus();return}
    if(event.key==="/"&&document.activeElement?.tagName!=="INPUT"){event.preventDefault();setRoute("search");$("#searchInput").focus();return}
    if(["INPUT","TEXTAREA"].includes(document.activeElement?.tagName))return;
    if(event.key.toLowerCase()==="j")highlightKeyboard(state.keyboardIndex+1);
    if(event.key.toLowerCase()==="k")highlightKeyboard(state.keyboardIndex-1);
    if(event.key==="Enter"&&state.keyboardIndex>=0){
      const p=state.rendered[state.keyboardIndex];if(p)openPaper(p.id);
    }
    if(event.key.toLowerCase()==="s"&&state.keyboardIndex>=0){
      const p=state.rendered[state.keyboardIndex];if(p)toggleSave(p.id);
    }
    if(event.key==="Escape"){closeStory();closeDrawer();$("#menuPopover").hidden=true}
  });
}

boot();
