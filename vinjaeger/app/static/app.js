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
