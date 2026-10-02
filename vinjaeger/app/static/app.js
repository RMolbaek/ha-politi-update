"use strict";

const $ = (id) => document.getElementById(id);
const kr = new Intl.NumberFormat("da-DK", { style: "currency", currency: "DKK" });

const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* privat tilstand */ }
  },
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
  } catch { return "#"; }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = store.get("token", "");
  if (token) headers["X-Vinjaeger-Token"] = token;
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    let msg = `Fejl ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* ikke JSON */ }
    if (typeof msg !== "string") msg = "Ugyldigt input";
    throw new Error(msg);
  }
  return res.json();
}

/* ---------- Status ---------- */

let statusTimer = null;
function showStatus(messages) {
  hide("error");
  show("status");
  let i = 0;
  $("statusText").textContent = messages[0];
  clearInterval(statusTimer);
  statusTimer = setInterval(() => {
    i = Math.min(i + 1, messages.length - 1);
    $("statusText").textContent = messages[i];
  }, 7000);
}
function hideStatus() { clearInterval(statusTimer); hide("status"); }
function showError(msg) { hideStatus(); $("error").textContent = msg; show("error"); }
function show(id) { $(id).hidden = false; }
function hide(id) { $(id).hidden = true; }

/* ---------- Foto af etiket ---------- */

async function downscale(file, maxSide = 1600) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
}

$("photoInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  hide("results");
  showStatus(["Læser etiketten…", "Næsten der…"]);
  try {
    const blob = await downscale(file).catch(() => file);
    $("thumb").src = URL.createObjectURL(blob);
    const form = new FormData();
    form.append("image", blob, "etiket.jpg");
    const wine = await api("/api/identify", { method: "POST", body: form });
    hideStatus();
    showIdentified(wine);
    $("q").value = wine.search_query;
    $("vintage").value = wine.vintage ?? "";
    $("ean").value = "";
    if (wine.confidence >= 0.6) {
      search();
    } else {
      showError("Jeg er ikke helt sikker på vinen – ret navnet herunder og tryk søg.");
      $("q").focus();
    }
  } catch (err) {
    showError(err.message);
  }
});

function showIdentified(w) {
  const name = [w.producer, w.wine_name].filter(Boolean).join(" – ") || w.search_query;
  $("identName").textContent = w.vintage ? `${name} ${w.vintage}` : name;
  $("identMeta").textContent = [w.color, w.grapes, w.region, w.country]
    .filter(Boolean).join(" · ");
  show("identified");
}

/* ---------- Stregkode ---------- */

let scanStream = null;
if ("BarcodeDetector" in window) show("scanBtn");

$("scanBtn").addEventListener("click", async () => {
  try {
    const detector = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const video = $("scanVideo");
    video.srcObject = scanStream;
    await video.play();
    show("scanner");
    const tick = async () => {
      if (!scanStream) return;
      const codes = await detector.detect(video).catch(() => []);
      if (codes.length) {
        const code = codes[0].rawValue;
        stopScan();
        hide("identified");
        $("ean").value = code;
        if (!$("q").value) $("q").value = `EAN ${code}`;
        search();
      } else {
        requestAnimationFrame(tick);
      }
    };
    tick();
  } catch (err) {
    stopScan();
    showError("Kunne ikke starte kameraet: " + err.message);
  }
});

function stopScan() {
  scanStream?.getTracks().forEach((t) => t.stop());
  scanStream = null;
  hide("scanner");
}
$("scanStop").addEventListener("click", stopScan);

/* ---------- Søgning ---------- */

$("searchForm").addEventListener("submit", (e) => { e.preventDefault(); search(); });
$("q").addEventListener("input", () => { $("ean").value = ""; });
$("refreshLink").addEventListener("click", (e) => { e.preventDefault(); search(true); });

async function search(refresh = false) {
  const q = $("q").value.trim();
  if (q.length < 2) { $("q").focus(); return; }
  const params = new URLSearchParams({ q });
  const vintage = $("vintage").value.trim();
  if (vintage) params.set("vintage", vintage);
  if ($("ean").value) params.set("ean", $("ean").value);
  if (refresh) params.set("refresh", "true");

  $("searchBtn").disabled = true;
  hide("results");
  showStatus([
    "Søger hos vinforhandlere…",
    "Tjekker supermarkeder og webshops…",
    "Åbner produktsider og læser priser…",
    "Sammenligner priser…",
    "Det tager lidt tid at finde de bedste tilbud…",
  ]);
  try {
    const result = await api("/api/search?" + params);
    hideStatus();
    renderResults(result);
    remember(result, vintage);
  } catch (err) {
    showError(err.message);
  } finally {
    $("searchBtn").disabled = false;
  }
}

function offerMeta(o) {
  const bits = [];
  if (o.vintage) bits.push(`Årgang ${o.vintage}`);
  if (o.bottle_ml !== 750) bits.push(`${o.bottle_ml / 10} cl (${kr.format(o.price_per_75cl)} pr. 75 cl)`);
  if (o.in_stock === false) bits.push("Udsolgt");
  if (o.note) bits.push(o.note);
  return bits.join(" · ");
}

function renderResults(r) {
  const myPrice = parseFloat($("myPrice").value);
  const best = r.cheapest;

  if (!r.offers.length) {
    $("best").innerHTML = `<div class="label">Ingen tilbud fundet</div>
      <p>Prøv at skrive navnet lidt anderledes, fx kun producent og vinnavn.</p>`;
  } else if (!best) {
    $("best").innerHTML = `<div class="label">Ingen sikre tilbud</div>
      <p>Der blev fundet tilbud, men de er udsolgte eller har en anden årgang.</p>`;
  } else {
    let saving = "";
    if (myPrice > 0) {
      const diff = myPrice - best.price_per_75cl;
      saving = diff > 0.5
        ? `<div class="saving">Spar ${kr.format(diff)} pr. flaske (${Math.round(diff / myPrice * 100)} %)</div>`
        : `<div class="saving none">Prisen her (${kr.format(myPrice)}) er den bedste – køb den bare 🍷</div>`;
    }
    $("best").innerHTML = `
      <div class="label">Billigste pris${r.cached ? " · fra cache" : ""}</div>
      <div class="price">${esc(kr.format(best.price_dkk))}</div>
      <div class="shop">${esc(best.shop)}</div>
      <div class="muted small">${esc(offerMeta(best))}</div>
      ${saving}
      <a class="btn primary big" href="${esc(safeUrl(best.url))}" target="_blank" rel="noopener">Gå til butikken ↗</a>`;
  }

  $("summary").textContent = r.summary || "";
  $("offers").innerHTML = r.offers.map((o) => {
    const dim = o.in_stock === false || (best && o.vintage && best.vintage && o.vintage !== best.vintage);
    return `<li class="${dim ? "dim" : ""}"><a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">
      <span class="o-shop">${esc(o.shop)}</span>
      <span class="o-price">${esc(kr.format(o.price_dkk))}</span>
      <span class="o-meta">${esc(offerMeta(o))}</span>
    </a></li>`;
  }).join("");
  show("results");
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- Historik ---------- */

function remember(r, vintage) {
  const list = store.get("history", []).filter((h) => !(h.q === r.query && h.vintage === vintage));
  list.unshift({ q: r.query, vintage, price: r.cheapest?.price_dkk ?? null, shop: r.cheapest?.shop ?? null });
  store.set("history", list.slice(0, 15));
  renderHistory();
}

function renderHistory() {
  const list = store.get("history", []);
  $("historyBox").hidden = !list.length;
  $("history").innerHTML = list.map((h, i) => `<li><button data-i="${i}">
      <span>${esc(h.q)}${h.vintage ? " " + esc(h.vintage) : ""}</span>
      <span class="muted">${h.price ? esc(kr.format(h.price)) : "–"}</span>
    </button></li>`).join("");
}

$("history").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-i]");
  if (!btn) return;
  const h = store.get("history", [])[btn.dataset.i];
  if (!h) return;
  $("q").value = h.q;
  $("vintage").value = h.vintage || "";
  $("ean").value = "";
  hide("identified");
  search();
});

/* ---------- Indstillinger ---------- */

$("settingsBtn").addEventListener("click", () => {
  $("tokenInput").value = store.get("token", "");
  $("settings").showModal();
});
$("settings").addEventListener("close", () => {
  if ($("settings").returnValue === "save") store.set("token", $("tokenInput").value.trim());
});
$("clearHistory").addEventListener("click", () => {
  store.set("history", []);
  renderHistory();
});

renderHistory();

/* ================= Faner ================= */

function selectTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
  });
  $("tab-price").hidden = name !== "price";
  $("tab-deals").hidden = name !== "deals";
  store.set("tab", name);
}
document.querySelector(".tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (btn) selectTab(btn.dataset.tab);
});

/* ================= Tilbudsjæger ================= */

const EXAMPLE_PROFILE = {
  name: "Mine favoritter",
  criteria: {
    rules: [
      { colors: ["rød"], regions: ["Bourgogne"], grapes: [], producers: [], max_price: null },
      { colors: ["rød"], regions: ["Barolo", "Barbaresco"], grapes: ["Nebbiolo"], producers: [], max_price: null },
    ],
    max_price: 400,
    min_discount: null,
    notes: "",
  },
};
const EMPTY_RULE = { colors: [], regions: [], grapes: [], producers: [], max_price: null };

let profiles = store.get("profiles", null) || [EXAMPLE_PROFILE];
let currentProfile = Math.min(store.get("currentProfile", 0), profiles.length - 1);

const splitList = (v) => v.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 15);
const numOrNull = (v) => (v === "" || v == null ? null : Number(v));

function addRuleCard(rule = EMPTY_RULE) {
  const node = $("ruleTpl").content.firstElementChild.cloneNode(true);
  node.querySelectorAll(".chips input").forEach((cb) => { cb.checked = rule.colors.includes(cb.value); });
  for (const k of ["regions", "grapes", "producers"]) {
    node.querySelector(`[data-k="${k}"]`).value = (rule[k] || []).join(", ");
  }
  node.querySelector('[data-k="max_price"]').value = rule.max_price ?? "";
  node.querySelector(".rule-remove").addEventListener("click", () => {
    if ($("rules").children.length > 1) { node.remove(); numberRules(); }
  });
  $("rules").append(node);
  numberRules();
}

function numberRules() {
  [...$("rules").children].forEach((el, i) => {
    el.querySelector(".rule-title").textContent = `Regel ${i + 1}`;
  });
}

function readCriteria() {
  const rules = [...$("rules").children].map((el) => ({
    colors: [...el.querySelectorAll(".chips input:checked")].map((cb) => cb.value),
    regions: splitList(el.querySelector('[data-k="regions"]').value),
    grapes: splitList(el.querySelector('[data-k="grapes"]').value),
    producers: splitList(el.querySelector('[data-k="producers"]').value),
    max_price: numOrNull(el.querySelector('[data-k="max_price"]').value),
  }));
  return {
    rules,
    max_price: numOrNull($("dealMaxPrice").value),
    min_discount: numOrNull($("dealMinDiscount").value),
    notes: $("dealNotes").value.trim() || null,
  };
}

function loadProfile(i) {
  currentProfile = i;
  store.set("currentProfile", i);
  const p = profiles[i];
  $("profileName").value = p.name;
  $("rules").innerHTML = "";
  (p.criteria.rules.length ? p.criteria.rules : [EMPTY_RULE]).forEach(addRuleCard);
  $("dealMaxPrice").value = p.criteria.max_price ?? "";
  $("dealMinDiscount").value = p.criteria.min_discount ?? "";
  $("dealNotes").value = p.criteria.notes ?? "";
  renderProfileSelect();
}

function renderProfileSelect() {
  $("profileSelect").innerHTML = profiles
    .map((p, i) => `<option value="${i}"${i === currentProfile ? " selected" : ""}>${esc(p.name)}</option>`)
    .join("");
}

function saveProfile() {
  profiles[currentProfile] = {
    name: $("profileName").value.trim() || `Profil ${currentProfile + 1}`,
    criteria: readCriteria(),
  };
  store.set("profiles", profiles);
  renderProfileSelect();
}

// Gem automatisk, når der ændres i formularen.
$("tab-deals").addEventListener("input", (e) => { if (e.target.id !== "profileSelect") saveProfile(); });
$("tab-deals").addEventListener("change", (e) => {
  if (e.target.id === "profileSelect") loadProfile(Number(e.target.value));
  else saveProfile();
});
$("addRule").addEventListener("click", () => { if ($("rules").children.length < 10) { addRuleCard(); saveProfile(); } });
$("rules").addEventListener("click", (e) => { if (e.target.closest(".rule-remove")) saveProfile(); });
$("newProfile").addEventListener("click", () => {
  profiles.push({ name: `Profil ${profiles.length + 1}`, criteria: { rules: [EMPTY_RULE], max_price: null, min_discount: null, notes: "" } });
  store.set("profiles", profiles);
  loadProfile(profiles.length - 1);
  $("profileName").select();
});
$("deleteProfile").addEventListener("click", () => {
  if (profiles.length <= 1 || !confirm(`Slet profilen "${profiles[currentProfile].name}"?`)) return;
  profiles.splice(currentProfile, 1);
  store.set("profiles", profiles);
  loadProfile(0);
});

/* ---------- Jagten ---------- */

let pollTimer = null;
let dealStatusTimer = null;
const HUNT_MESSAGES = [
  "Agenten er sendt på jagt…",
  "Gennemgår tilbudssider hos vinhandlere…",
  "Tjekker supermarkedernes vintilbud…",
  "Åbner produktsider og læser priser…",
  "Sammenligner med normalpriser…",
  "Vurderer hvilke tilbud der er gode køb…",
  "Næsten færdig – samler de bedste fund…",
];

function setHunting(on) {
  $("huntBtn").disabled = on;
  clearInterval(dealStatusTimer);
  $("dealStatus").hidden = !on;
  if (!on) return;
  let i = 0;
  $("dealStatusText").textContent = HUNT_MESSAGES[0];
  dealStatusTimer = setInterval(() => {
    i = Math.min(i + 1, HUNT_MESSAGES.length - 1);
    $("dealStatusText").textContent = HUNT_MESSAGES[i];
  }, 20000);
}

async function hunt(refresh = false) {
  saveProfile();
  hide("dealError");
  hide("dealResults");
  setHunting(true);
  try {
    const job = await api("/api/deals" + (refresh ? "?refresh=true" : ""), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readCriteria()),
    });
    store.set("dealJob", job.id);
    handleJob(job);
  } catch (err) {
    setHunting(false);
    $("dealError").textContent = err.message;
    show("dealError");
  }
}

function handleJob(job) {
  clearTimeout(pollTimer);
  if (job.status === "running") {
    setHunting(true);
    pollTimer = setTimeout(() => pollJob(job.id), 5000);
    return;
  }
  setHunting(false);
  store.set("dealJob", null);
  if (job.status === "error") {
    $("dealError").textContent = job.error || "Tilbudsjagten fejlede";
    show("dealError");
  } else {
    store.set("lastDeals", job.result);
    renderDeals(job.result);
  }
}

async function pollJob(id) {
  try {
    handleJob(await api(`/api/deals/${encodeURIComponent(id)}`));
  } catch (err) {
    // Fx hvis serveren er genstartet - jobbet findes ikke længere.
    setHunting(false);
    store.set("dealJob", null);
    $("dealError").textContent = err.message;
    show("dealError");
  }
}

function renderDeals(r) {
  $("dealSummary").textContent = (r.cached ? "(Fra cache) " : "") + (r.summary || "");
  if (!r.deals.length) {
    $("dealList").innerHTML = `<li class="deal">Ingen tilbud matchede lige nu. Prøv at løsne kriterierne lidt.</li>`;
  } else {
    $("dealList").innerHTML = r.deals.map((d) => {
      const name = d.vintage ? `${d.wine} ${d.vintage}` : d.wine;
      const meta = [d.producer, d.region, d.grapes, d.color].filter(Boolean).join(" · ");
      const size = d.bottle_ml !== 750 ? ` · ${d.bottle_ml / 10} cl` : "";
      return `<li class="deal">
        <div class="deal-top">
          <div>
            <div class="deal-name">${esc(name)}</div>
            <div class="muted small">${esc(meta)}</div>
          </div>
          <div class="score ${d.deal_score >= 7 ? "" : "mid"}" title="Hvor godt et køb (1-10)">${esc(d.deal_score)}/10</div>
        </div>
        <div class="deal-prices">
          <span class="deal-price">${esc(kr.format(d.price_dkk))}</span>
          ${d.normal_price_dkk ? `<span class="deal-normal">${esc(kr.format(d.normal_price_dkk))}</span>` : ""}
          ${d.discount_pct ? `<span class="discount">−${esc(d.discount_pct)} %</span>` : ""}
        </div>
        <div class="small"><strong>${esc(d.shop)}</strong>${esc(size)}${d.matched_rule ? ` · regel ${esc(d.matched_rule)}` : ""}</div>
        ${d.why ? `<p class="deal-why small">${esc(d.why)}</p>` : ""}
        <a class="btn" href="${esc(safeUrl(d.url))}" target="_blank" rel="noopener">Se tilbuddet ↗</a>
      </li>`;
    }).join("");
  }
  show("dealResults");
}

$("huntBtn").addEventListener("click", () => hunt());
$("dealRefresh").addEventListener("click", (e) => { e.preventDefault(); hunt(true); });

/* ---------- Opstart ---------- */

loadProfile(currentProfile);
const lastDeals = store.get("lastDeals", null);
if (lastDeals) renderDeals(lastDeals);
const runningJob = store.get("dealJob", null);
if (runningJob) pollJob(runningJob);
selectTab(store.get("tab", "price"));
