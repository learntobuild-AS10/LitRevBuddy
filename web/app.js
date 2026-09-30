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
  saved: new Set(),
  recent: [],
  theme: window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark",
  openRouterKey: "",
  storyCards: [],
  storyIndex: 0,
  storyMode: "quick",
  deepText: "",
  deepSourceLabel: "",
  citationGraph: null,
  citationGraphSource: "",
  citationPoints: [],
  citationSelection: null,
  citationFilter: "citations",
  citationQuery: "",
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
      ${paper.p ? `<a class="action-btn" href="${esc(paper.p)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Paper ↗</a>` : ""}
      ${paper.pdf ? `<a class="action-btn" href="${esc(paper.pdf)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">PDF ↗</a>` : ""}
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

const STORY_STOPWORDS = new Set([
  "the","and","for","with","that","this","from","were","was","are","our","their","they","using","into","through",
  "have","has","had","but","not","can","than","which","these","those","been","also","between","over","under","across",
  "paper","method","model","models","results","approach","based","show","shows","propose","proposed","we","a","an","of",
  "to","in","on","as","by","is","it","be","or","at","its"
]);

function keyTerms(text, limit=4) {
  const counts = new Map();
  for (const token of normalize(text).split(/\s+/)) {
    if (token.length < 4 || STORY_STOPWORDS.has(token) || /^\d+$/.test(token)) continue;
    counts.set(token,(counts.get(token)||0)+1);
  }
  return [...counts.entries()].sort((a,b)=>b[1]-a[1] || b[0].length-a[0].length).slice(0,limit).map(([term])=>term);
}

function findSentence(sentences, regexes, used=new Set(), preferNumbers=false) {
  let best=null;
  let bestScore=-Infinity;
  sentences.forEach((sentence,index)=>{
    if(used.has(sentence)) return;
    let score=0;
    for(const regex of regexes) if(regex.test(sentence)) score+=8;
    if(preferNumbers && /\b\d+(?:\.\d+)?%|\b0\.\d+\b|\bp\s*[<=>]/i.test(sentence)) score+=5;
    if(sentence.length>=70 && sentence.length<=360) score+=2;
    if(index<Math.max(3,Math.floor(sentences.length*.15))) score+=.5;
    if(score>bestScore){bestScore=score;best={sentence,index,score}}
  });
  return bestScore>0?best:null;
}

function supportingSentence(sentences,index,used) {
  for(const offset of [1,-1,2]){
    const candidate=sentences[index+offset];
    if(candidate && !used.has(candidate) && candidate.length<420) return candidate;
  }
  return "";
}

function metricFrom(text) {
  return text.match(/\b\d+(?:\.\d+)?%|\b0\.\d{2,}\b|\b\d+(?:\.\d+)?\s*(?:points?|pp)\b/i)?.[0] || "";
}

function makeStoryCard({label,headline,primary,support="",type="concept",source="Abstract"}) {
  const combined=[primary,support].filter(Boolean).join(" ");
  return {
    label,headline,
    body:combined,
    evidence:primary,
    bullets:keyTerms(combined,4),
    type,
    metric:type==="result"?metricFrom(combined):"",
    source
  };
}

function buildGroundedCards(text, source="Abstract", deep=false) {
  const sentences=splitSentences(text);
  if(!sentences.length) return [];
  const used=new Set();
  const specs = deep ? [
    ["Problem","What problem motivates the paper",[/\bproblem\b|\bchallenge\b|\blimit(?:ed|ation)?\b|\bshortcoming\b|\bneed for\b/i],"problem",false],
    ["Prior work","What existing approaches miss",[/\bprevious\b|\bprior work\b|\bexisting\b|\bstate[- ]of[- ]the[- ]art\b|\bhowever\b|\bdespite\b/i],"comparison",false],
    ["Core idea","The paper's central move",[/\bwe propose\b|\bwe present\b|\bwe introduce\b|\bwe develop\b|\bnovel\b|\bour framework\b/i],"concept",false],
    ["Method","How the method works",[/\barchitecture\b|\bframework\b|\bmodule\b|\bencoder\b|\bdecoder\b|\btraining\b|\boptimization\b|\balgorithm\b|\bconsists? of\b|\bcompris(?:e|es)\b/i],"method",false],
    ["Data","What they evaluate on",[/\bdataset\b|\bbenchmark\b|\bcohort\b|\btraining set\b|\btest set\b|\bvalidation set\b|\bsubjects?\b|\bpatients?\b/i],"data",true],
    ["Results","What the experiments report",[/\boutperform\b|\bachiev\w*\b|\bimprov\w*\b|\bresults?\b|\baccuracy\b|\bauroc\b|\bdice\b|\bf1\b|\bsignificant\b/i],"result",true],
    ["Ablation","What seems to drive performance",[/\bablation\b|\bvariant\b|\bcomponent\b|\bsensitivity\b|\bw\/o\b|\bwithout\b/i],"comparison",true],
    ["Limitations","What remains unresolved",[/\blimitation\b|\bfuture work\b|\bfail(?:s|ure)?\b|\bhowever\b|\balthough\b|\bremains?\b/i],"limitation",false],
    ["Takeaway","What to remember",[/\bconclusion\b|\bdemonstrat\w*\b|\bshow\w*\b|\boverall\b|\bwe find\b/i],"takeaway",false],
  ] : [
    ["Problem","Why this paper exists",[/\bproblem\b|\bchallenge\b|\blimit(?:ed|ation)?\b|\bshortcoming\b|\bneed for\b|\bhowever\b/i],"problem",false],
    ["Core idea","The central move",[/\bwe propose\b|\bwe present\b|\bwe introduce\b|\bwe develop\b|\bnovel\b|\bour framework\b/i],"concept",false],
    ["Method","How it works",[/\busing\b|\bthrough\b|\bvia\b|\bframework\b|\barchitecture\b|\bmodule\b|\bencoder\b|\bdecoder\b|\btraining\b/i],"method",false],
    ["Evidence","What the abstract reports",[/\boutperform\b|\bachiev\w*\b|\bimprov\w*\b|\bresult\w*\b|\baccuracy\b|\bauroc\b|\bdice\b|\bf1\b|%/i],"result",true],
    ["Limitations","What the abstract qualifies",[/\blimitation\b|\bhowever\b|\balthough\b|\bfuture\b|\bremains?\b/i],"limitation",false],
    ["Takeaway","What to remember",[/\bdemonstrat\w*\b|\bshow\w*\b|\bwe find\b|\boverall\b|\bconclusion\b/i],"takeaway",false],
  ];

  const cards=[];
  for(const [label,headline,regexes,type,preferNumbers] of specs){
    const hit=findSentence(sentences,regexes,used,preferNumbers);
    if(!hit) continue;
    used.add(hit.sentence);
    const support=supportingSentence(sentences,hit.index,used);
    if(support) used.add(support);
    cards.push(makeStoryCard({label,headline,primary:hit.sentence,support,type,source}));
  }

  if(cards.length<4){
    for(const sentence of sentences){
      if(cards.length>=6) break;
      if(used.has(sentence)) continue;
      used.add(sentence);
      cards.push(makeStoryCard({
        label:cards.length===0?"Overview":"Key point",
        headline:cards.length===0?"The paper in one view":"Another point worth keeping",
        primary:sentence,
        type:"concept",
        source
      }));
    }
  }
  return cards.slice(0,deep?9:7);
}

function extractiveCards(paper) {
  return buildGroundedCards(paper.abstract || paper.s,"Abstract",false);
}

async function parsePdfBuffer(buffer) {
  const pdfjs = await import("./vendor/pdf.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL("./vendor/pdf.worker.mjs", import.meta.url).href;
  const pdf = await pdfjs.getDocument({data:new Uint8Array(buffer)}).promise;
  const pageCount=Math.min(pdf.numPages,80);
  const chunks=[];
  let total=0;
  for(let pageNo=1;pageNo<=pageCount && total<260000;pageNo++){
    const page=await pdf.getPage(pageNo);
    const content=await page.getTextContent();
    let pageText="";
    for(const item of content.items){
      if(!item.str) continue;
      pageText+=item.str+(item.hasEOL?"\n":" ");
    }
    pageText=pageText.replace(/[ \t]+/g," ").replace(/\n{3,}/g,"\n\n").trim();
    chunks.push(pageText);
    total+=pageText.length;
  }
  return chunks.join("\n\n").slice(0,260000);
}

async function loadDeepStoryFromBuffer(buffer,label="Full paper PDF") {
  $("#storyContent").innerHTML='<div class="story-stage"><div class="empty">Reading the PDF in your browser…</div></div>';
  const text=await parsePdfBuffer(buffer);
  if(text.length<1500) throw new Error("Too little text could be extracted from this PDF.");
  state.deepText=text;
  state.deepSourceLabel=label;
  state.storyMode="deep";
  state.storyCards=buildGroundedCards(text,label,true);
  state.storyIndex=0;
  renderStory();
}

function renderDeepStorySetup(message="Load the full paper for a deeper walkthrough.") {
  const paper=state.activePaper;
  $("#storyContent").innerHTML=`
    <div class="story-stage">
      <div class="deep-setup">
        <div class="eyebrow">Deep story</div>
        <h2>Read beyond the abstract</h2>
        <p>${esc(message)}</p>
        <div class="deep-actions">
          ${paper?.pdf?`<button id="loadPdfDirect" class="action-btn primary">Try paper PDF</button>`:""}
          <label class="action-btn upload-btn">Choose PDF<input id="deepPdfUpload" type="file" accept="application/pdf,.pdf" hidden /></label>
        </div>
        <p class="microcopy">PDF text is processed only in this page's memory. It is not uploaded to LitRevBuddy or persisted. If you later choose AI Story, a bounded portion of this extracted text will be sent directly to OpenRouter after your explicit confirmation.</p>
      </div>
    </div>`;

  $("#loadPdfDirect")?.addEventListener("click",async()=>{
    try{
      const response=await fetch(paper.pdf,{mode:"cors",credentials:"omit",referrerPolicy:"no-referrer"});
      if(!response.ok) throw new Error("PDF request failed");
      const buffer=await response.arrayBuffer();
      await loadDeepStoryFromBuffer(buffer,"Full paper PDF");
    }catch(error){
      console.error(error);
      renderDeepStorySetup("This publisher blocks direct browser PDF access. Choose the PDF from your device instead.");
    }
  });
  $("#deepPdfUpload")?.addEventListener("change",async event=>{
    const file=event.target.files?.[0];
    if(!file) return;
    if(file.size>35*1024*1024){toast("PDF is too large for browser processing");return}
    try{await loadDeepStoryFromBuffer(await file.arrayBuffer(),"Uploaded full paper PDF")}
    catch(error){console.error(error);renderDeepStorySetup(error.message||"Could not read this PDF.")}
  });
}

function renderStory() {
  const paper = state.activePaper;
  const cards = state.storyCards;
  if (!paper || !cards.length) {
    $("#storyContent").innerHTML = '<div class="story-stage"><div class="empty">No source-grounded cards could be extracted from this source.</div></div>';
    return;
  }
  state.storyIndex = Math.max(0,Math.min(state.storyIndex,cards.length-1));
  const card = cards[state.storyIndex];
  const modeLabel=state.storyMode==="deep"?"Deep story":"Quick story";
  const bullets=(card.bullets||[]).length?`<div class="story-keywords">${card.bullets.map(x=>`<span>${esc(x)}</span>`).join("")}</div>`:"";
  const metric=card.metric?`<div class="story-metric">${esc(card.metric)}</div>`:"";
  $("#storyContent").innerHTML = `
    <div class="story-stage">
      <div class="story-heading">
        <div class="eyebrow">${esc(paper.v)} · ${paper.y}</div>
        <h2>${esc(paper.t)}</h2>
        <p>${modeLabel} · ${state.storyIndex+1} of ${cards.length}</p>
      </div>
      <article class="story-card story-type-${esc(card.type||"concept")}">
        <div class="story-step">${esc(card.label)}</div>
        ${metric}
        <h3>${esc(card.headline)}</h3>
        <p>${esc(card.body)}</p>
        ${bullets}
        <details class="story-evidence">
          <summary>Evidence</summary>
          <blockquote>${esc(card.evidence)}</blockquote>
        </details>
        <div class="story-source">Source: ${esc(card.source||"Abstract")}</div>
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
  state.storyMode = "quick";
  state.storyCards = extractiveCards(paper);
  state.storyIndex = 0;
  state.deepText = "";
  state.deepSourceLabel = "";
  $("#storyModal").classList.add("open");
  $("#storyModal").setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
  $("#extractiveStoryBtn").classList.add("active");
  $("#deepStoryBtn").classList.remove("active");
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
  let key = state.openRouterKey || "";
  if (!key) {
    $("#storyContent").innerHTML = `
      <div class="story-stage">
        <div class="ai-connect">
          <div class="eyebrow">Optional AI mode</div>
          <h2>Use your free OpenRouter key</h2>
          <p>Your key is kept only in page memory and is sent directly from your browser to OpenRouter. LitRevBuddy does not persist it.</p>
          <input id="orKey" type="password" placeholder="sk-or-v1-…" autocomplete="off" />
          <label class="consent-row">
            <input id="aiConsent" type="checkbox" />
            <span>I understand that generating an AI story sends source text from this paper to OpenRouter, a third-party service. If Deep Story is loaded, this may include extracted full-paper text. LitRevBuddy does not create an account, subscription, or payment for me.</span>
          </label>
          <button id="connectAI" class="action-btn primary" disabled>Generate AI story</button>
          <button id="cancelAI" class="action-btn">Use source cards instead</button>
        </div>
      </div>`;
    const keyInput = $("#orKey");
    const consent = $("#aiConsent");
    const connect = $("#connectAI");
    const refreshConnectState = () => {
      connect.disabled = !(keyInput.value.trim() && consent.checked);
    };
    keyInput.addEventListener("input", refreshConnectState);
    consent.addEventListener("change", refreshConnectState);
    connect.addEventListener("click",()=>{
      const entered=keyInput.value.trim();
      if(!entered || !consent.checked) return;
      state.openRouterKey = entered;
      aiStory();
    });
    $("#cancelAI").addEventListener("click",()=>{ $("#extractiveStoryBtn").click(); });
    return;
  }

  $("#storyContent").innerHTML='<div class="story-stage"><div class="empty">Generating a concise, source-grounded story…</div></div>';
  const aiSource = state.deepText || paper.abstract || paper.s;
  const aiSourceLabel = state.deepText ? (state.deepSourceLabel || "Full paper PDF") : "Abstract";
  const boundedSource = aiSource.slice(0,24000);
  const prompt = `Create 6-8 concise study cards from ONLY the source text below. Cover problem, prior gap, core idea, method, evaluation, results, and limitations when supported. Return JSON exactly as {"cards":[{"label":"short label","headline":"max 12 words","body":"35-65 words","evidence":"one exact sentence copied from the source"}]}. Keep explanations concrete and technical. Never invent facts or numbers. SOURCE (${aiSourceLabel}):\n${boundedSource}`;

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
    const sourceNorm=normalizeEvidence(aiSource);
    const verified=(parsed.cards || []).filter(card=>{
      const evidence=normalizeEvidence(card.evidence || "");
      return evidence.length>20 && sourceNorm.includes(evidence);
    }).slice(0,6);
    if(verified.length<2) throw new Error("Too few cards could be verified");
    state.storyMode = state.deepText ? "deep" : "quick";
    state.storyCards=verified.map(card=>({
      ...card,
      type:/result|performance|evidence/i.test(card.label||"")?"result":
           /method|architecture|training/i.test(card.label||"")?"method":
           /limit|failure/i.test(card.label||"")?"limitation":"concept",
      bullets:keyTerms((card.body||"")+" "+(card.evidence||""),4),
      metric:metricFrom(card.body||""),
      source:aiSourceLabel
    }));
    state.storyIndex=0;
    renderStory();
  } catch(error) {
    console.error(error);
    toast("AI route unavailable — showing source cards");
    state.openRouterKey = "";
    state.storyMode="quick";
    state.storyCards=extractiveCards(paper);
    state.storyIndex=0;
    $("#extractiveStoryBtn").classList.add("active");
    $("#deepStoryBtn").classList.remove("active");
    $("#aiStoryBtn").classList.remove("active");
    renderStory();
  }
}

function toggleSave(id) {
  id=Number(id);
  if(state.saved.has(id)){state.saved.delete(id);toast("Removed from saved")}
  else{state.saved.add(id);toast("Saved")}
  $("#savedCount").textContent=state.saved.size;
  renderResults();
  if(state.route==="saved") renderSaved();
  if(state.activePaper?.id===id) openPaper(id);
}

function addRecent(id) {
  id=Number(id);
  state.recent=[id,...state.recent.filter(x=>x!==id)].slice(0,12);
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

function normalizeGraphifyGraph(raw) {
  const nodes = Array.isArray(raw?.nodes) ? raw.nodes : [];
  const edges = Array.isArray(raw?.edges) ? raw.edges : (Array.isArray(raw?.links) ? raw.links : []);
  const nodeMap = new Map(nodes.map(node => [String(node.id), {
    id:String(node.id),
    label:String(node.label || node.id || "Untitled"),
    file_type:String(node.file_type || node.type || "concept"),
    source_file:String(node.source_file || ""),
    source_location:String(node.source_location || ""),
    source_url:String(node.source_url || ""),
    community:Number.isFinite(Number(node.community)) ? Number(node.community) : 0
  }]));
  const cleanEdges = edges
    .map(edge => ({
      source:String(typeof edge.source==="object" ? edge.source.id : edge.source),
      target:String(typeof edge.target==="object" ? edge.target.id : edge.target),
      relation:String(edge.relation || "related_to"),
      confidence:String(edge.confidence || ""),
      confidence_score:Number(edge.confidence_score ?? edge.weight ?? 0),
      weight:Number(edge.weight ?? 1)
    }))
    .filter(edge => nodeMap.has(edge.source) && nodeMap.has(edge.target));
  return {nodes:[...nodeMap.values()],edges:cleanEdges};
}

function isCitationEdge(edge) {
  return /(^|_)(cite|cites|citation|reference|references|referenced_by)($|_)/i.test(edge.relation);
}

function citationFilteredEdges() {
  const graph=state.citationGraph;
  if(!graph) return [];
  if(state.citationFilter==="all") return graph.edges;
  if(state.citationFilter==="extracted") return graph.edges.filter(e => e.confidence.toUpperCase()==="EXTRACTED");
  const citations=graph.edges.filter(isCitationEdge);
  return citations.length ? citations : graph.edges.filter(e => e.confidence.toUpperCase()==="EXTRACTED");
}

function hashNumber(value) {
  let h=2166136261;
  for(const ch of String(value)){h^=ch.charCodeAt(0);h=Math.imul(h,16777619)}
  return (h>>>0)/4294967295;
}

function citationVisibleGraph() {
  const graph=state.citationGraph;
  if(!graph) return {nodes:[],edges:[]};
  const edges=citationFilteredEdges();
  const degree=new Map();
  edges.forEach(e=>{
    degree.set(e.source,(degree.get(e.source)||0)+1);
    degree.set(e.target,(degree.get(e.target)||0)+1);
  });
  let nodes=graph.nodes.filter(n=>degree.has(n.id));
  const q=normalize(state.citationQuery);
  if(q){
    const matched=new Set(nodes.filter(n=>normalize(n.label).includes(q)).map(n=>n.id));
    if(matched.size){
      edges.forEach(e=>{
        if(matched.has(e.source)) matched.add(e.target);
        if(matched.has(e.target)) matched.add(e.source);
      });
      nodes=nodes.filter(n=>matched.has(n.id));
    } else {
      nodes=[];
    }
  }
  if(nodes.length>3000){
    nodes=[...nodes].sort((a,b)=>(degree.get(b.id)||0)-(degree.get(a.id)||0)).slice(0,3000);
  }
  const ids=new Set(nodes.map(n=>n.id));
  return {nodes,edges:edges.filter(e=>ids.has(e.source)&&ids.has(e.target)).slice(0,12000),degree};
}

function layoutCitationNodes(nodes,width,height) {
  const groups=new Map();
  nodes.forEach(node=>{
    const key=node.community || node.file_type || 0;
    if(!groups.has(key)) groups.set(key,[]);
    groups.get(key).push(node);
  });
  const groupList=[...groups.entries()].sort((a,b)=>b[1].length-a[1].length);
  const centerX=width/2,centerY=height/2;
  const orbit=Math.min(width,height)*.31;
  const points=[];
  groupList.forEach(([group,members],gi)=>{
    const angle=(Math.PI*2*gi)/Math.max(1,groupList.length)-Math.PI/2;
    const gx=groupList.length===1?centerX:centerX+Math.cos(angle)*orbit;
    const gy=groupList.length===1?centerY:centerY+Math.sin(angle)*orbit*.78;
    const localRadius=Math.max(24,Math.min(150,22*Math.sqrt(members.length)));
    members.forEach((node,i)=>{
      const seed=hashNumber(node.id);
      const a=(i*2.399963229728653)+(seed*.8);
      const r=localRadius*Math.sqrt((i+.7)/Math.max(1,members.length));
      points.push({node,x:gx+Math.cos(a)*r,y:gy+Math.sin(a)*r,group});
    });
  });
  return points;
}

function renderCitationGraph() {
  const canvas=$("#citationMap");
  if(!canvas || !state.citationGraph) return;
  const box=canvas.getBoundingClientRect();
  const ratio=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.max(1,Math.floor(box.width*ratio));
  canvas.height=Math.max(1,Math.floor(box.height*ratio));
  const ctx=canvas.getContext("2d");
  ctx.setTransform(ratio,0,0,ratio,0,0);
  ctx.clearRect(0,0,box.width,box.height);

  const view=citationVisibleGraph();
  const points=layoutCitationNodes(view.nodes,box.width,box.height);
  state.citationPoints=points;
  const pointMap=new Map(points.map(p=>[p.node.id,p]));
  const styles=getComputedStyle(document.documentElement);
  const line=styles.getPropertyValue("--line").trim();
  const muted=styles.getPropertyValue("--muted").trim();
  const accent=styles.getPropertyValue("--accent").trim();
  const cyan=styles.getPropertyValue("--cyan").trim();

  ctx.lineWidth=.7;
  view.edges.forEach(edge=>{
    const a=pointMap.get(edge.source),b=pointMap.get(edge.target);
    if(!a||!b) return;
    ctx.globalAlpha=edge.confidence.toUpperCase()==="EXTRACTED"?.32:.13;
    ctx.strokeStyle=line;
    ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
  });

  points.forEach(point=>{
    const selected=state.citationSelection===point.node.id;
    const match=state.citationQuery && normalize(point.node.label).includes(normalize(state.citationQuery));
    const degree=view.degree?.get(point.node.id)||1;
    const radius=Math.min(7,2.4+Math.log2(degree+1)*.8);
    ctx.globalAlpha=selected||match?1:.78;
    ctx.fillStyle=selected?accent:(point.node.file_type==="paper"?cyan:muted);
    ctx.beginPath();ctx.arc(point.x,point.y,selected?radius+2:radius,0,Math.PI*2);ctx.fill();
  });
  ctx.globalAlpha=1;

  const originalNodes=state.citationGraph.nodes.length;
  const originalEdges=state.citationGraph.edges.length;
  $("#citationStatus").textContent =
    `${state.citationGraphSource || "Graph"} · showing ${view.nodes.length.toLocaleString()} nodes and ${view.edges.length.toLocaleString()} relationships (${originalNodes.toLocaleString()} nodes / ${originalEdges.toLocaleString()} total)`;
}

function citationNearest(event) {
  const canvas=$("#citationMap");
  const rect=canvas.getBoundingClientRect();
  const x=event.clientX-rect.left,y=event.clientY-rect.top;
  return state.citationPoints.reduce((best,pt)=>{
    const d=(pt.x-x)**2+(pt.y-y)**2;
    return !best||d<best.d?{pt,d}:best;
  },null);
}

function renderCitationDetails(nodeId) {
  const graph=state.citationGraph;
  if(!graph) return;
  const node=graph.nodes.find(n=>n.id===nodeId);
  if(!node) return;
  const connected=graph.edges.filter(e=>e.source===nodeId||e.target===nodeId);
  const neighbors=connected.slice(0,24).map(edge=>{
    const otherId=edge.source===nodeId?edge.target:edge.source;
    const other=graph.nodes.find(n=>n.id===otherId);
    return {edge,other};
  }).filter(x=>x.other);
  $("#citationDetails").innerHTML=`
    <div class="eyebrow">${esc(node.file_type)}${node.community?" · community "+esc(node.community):""}</div>
    <h3>${esc(node.label)}</h3>
    ${node.source_file?`<p class="citation-source">${esc(node.source_file)}${node.source_location?" · "+esc(node.source_location):""}</p>`:""}
    ${node.source_url?`<p><a href="${esc(node.source_url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open source ↗</a></p>`:""}
    <div class="citation-neighbors">
      <strong>${connected.length.toLocaleString()} relationships</strong>
      ${neighbors.map(({edge,other})=>`
        <button data-citation-node="${esc(other.id)}">
          <span>${esc(edge.relation.replaceAll("_"," "))}</span>
          <strong>${esc(other.label)}</strong>
          <small>${esc(edge.confidence || "unlabelled")}</small>
        </button>`).join("") || "<p>No connected nodes.</p>"}
    </div>`;
}

async function loadPublishedCitationGraph() {
  try{
    const response=await fetch(`${DATA_ROOT}/citation-graph/graph.json`,{cache:"no-cache"});
    if(!response.ok) throw new Error("No published graph");
    const raw=await response.json();
    state.citationGraph=normalizeGraphifyGraph(raw);
    state.citationGraphSource="Published Graphify map";
    renderCitationGraph();
  }catch(error){
    $("#citationStatus").textContent="No citation graph has been published yet. Open a Graphify graph.json from your device, or publish one through the repository workflow.";
    $("#citationDetails").innerHTML='<div class="empty compact-empty">Citation graph not published yet.</div>';
  }
}

function handleCitationUpload(file) {
  const reader=new FileReader();
  reader.onload=()=>{
    try{
      const raw=JSON.parse(String(reader.result||""));
      state.citationGraph=normalizeGraphifyGraph(raw);
      state.citationGraphSource="Local graph.json";
      state.citationSelection=null;
      renderCitationGraph();
      toast("Citation graph loaded in this page only");
    }catch(error){
      console.error(error);
      toast("Could not read this graph.json");
    }
  };
  reader.readAsText(file);
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
  if(route==="explore"){
    setTimeout(renderMap,50);
    if(!state.citationGraph) loadPublishedCitationGraph();
  }
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
    if(state.route==="explore")renderMap();
  });

  $(".tab-btn").forEach(btn=>btn.addEventListener("click",()=>{
    $(".tab-btn").forEach(b=>b.classList.toggle("active",b===btn));
    $(".explore-panel").forEach(p=>p.classList.remove("active"));
    const tab=btn.dataset.exploreTab;
    const panel=tab==="map"?"#mapPanel":tab==="citations"?"#citationsPanel":"#topicsPanel";
    $(panel).classList.add("active");
    if(tab==="map")setTimeout(renderMap,30);
    if(tab==="citations"){
      if(!state.citationGraph) loadPublishedCitationGraph();
      else setTimeout(renderCitationGraph,30);
    }
  }));

  $("#citationGraphUpload")?.addEventListener("change",event=>{
    const file=event.target.files?.[0];
    if(file) handleCitationUpload(file);
    event.target.value="";
  });
  $("#citationRelationFilter")?.addEventListener("change",event=>{
    state.citationFilter=event.target.value;
    state.citationSelection=null;
    renderCitationGraph();
  });
  $("#citationSearch")?.addEventListener("input",debounce(event=>{
    state.citationQuery=event.target.value.trim();
    state.citationSelection=null;
    renderCitationGraph();
  },100));
  $("#citationMap")?.addEventListener("mousemove",event=>{
    if(!state.citationPoints.length) return;
    const nearest=citationNearest(event);
    const tip=$("#citationTooltip");
    if(nearest&&nearest.d<324){
      tip.hidden=false;
      tip.textContent=nearest.pt.node.label;
      const rect=event.currentTarget.getBoundingClientRect();
      tip.style.left=`${Math.min(event.clientX-rect.left+12,rect.width-290)}px`;
      tip.style.top=`${Math.max(8,event.clientY-rect.top-12)}px`;
    }else tip.hidden=true;
  });
  $("#citationMap")?.addEventListener("click",event=>{
    const nearest=citationNearest(event);
    if(nearest&&nearest.d<625){
      state.citationSelection=nearest.pt.node.id;
      renderCitationGraph();
      renderCitationDetails(state.citationSelection);
    }
  });
  $("#citationDetails")?.addEventListener("click",event=>{
    const button=event.target.closest("[data-citation-node]");
    if(!button) return;
    state.citationSelection=button.dataset.citationNode;
    renderCitationGraph();
    renderCitationDetails(state.citationSelection);
  });

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
    $("#extractiveStoryBtn").classList.add("active");
    $("#deepStoryBtn").classList.remove("active");
    $("#aiStoryBtn").classList.remove("active");
    state.storyMode="quick";
    state.storyCards=extractiveCards(state.activePaper);
    state.storyIndex=0;
    renderStory();
  });
  $("#deepStoryBtn").addEventListener("click",()=>{
    $("#deepStoryBtn").classList.add("active");
    $("#extractiveStoryBtn").classList.remove("active");
    $("#aiStoryBtn").classList.remove("active");
    if(state.deepText){
      state.storyMode="deep";
      state.storyCards=buildGroundedCards(state.deepText,state.deepSourceLabel||"Full paper PDF",true);
      state.storyIndex=0;
      renderStory();
    }else{
      renderDeepStorySetup();
    }
  });
  $("#aiStoryBtn").addEventListener("click",()=>{
    $("#aiStoryBtn").classList.add("active");
    $("#extractiveStoryBtn").classList.remove("active");
    $("#deepStoryBtn").classList.remove("active");
    aiStory();
  });

  window.addEventListener("hashchange",routeFromHash);
  window.addEventListener("resize",debounce(()=>{
    if(state.route!=="explore") return;
    if($("#mapPanel").classList.contains("active")) renderMap();
    if($("#citationsPanel").classList.contains("active") && state.citationGraph) renderCitationGraph();
  },150));

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
