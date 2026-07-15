const els = {
  candidateCount: document.querySelector("#candidateCount"),
  lookupForm: document.querySelector("#tokenLookupForm"),
  lookupStatus: document.querySelector("#lookupStatus"),
  methodology: document.querySelector("#radarMethodology"),
  refreshButton: document.querySelector("#refreshRadarButton"),
  screenedCount: document.querySelector("#screenedCount"),
  tokenAddress: document.querySelector("#tokenAddressInput"),
  tokenDetail: document.querySelector("#tokenDetail"),
  tokenGrid: document.querySelector("#tokenGrid"),
};

const WATCHLIST_KEY = "monatise-memecoin-watchlist";
const state = { tokens: [], watchlist: new Set(JSON.parse(localStorage.getItem(WATCHLIST_KEY) || "[]")) };

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : "#";
  } catch {
    return "#";
  }
}

function money(value, compact = false) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (number > 0 && number < 0.0001) return `$${number.toExponential(3)}`;
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : number < 1 ? 8 : 2,
  }).format(number);
}

function compact(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(number) : "--";
}

function shortAddress(value) {
  const text = String(value || "");
  return text.length > 12 ? `${text.slice(0, 6)}…${text.slice(-5)}` : text;
}

function riskClass(label) {
  return String(label || "").toLowerCase().replaceAll(" ", "-");
}

function tokenAvatar(token, large = false) {
  const image = safeUrl(token.imageUrl);
  if (image !== "#") return `<span class="token-media ${large ? "large" : ""}"><img data-token-image src="${escapeHtml(image)}" alt="" loading="lazy" referrerpolicy="no-referrer" /><span class="token-avatar" hidden>${escapeHtml(String(token.symbol || "?").slice(0, 1))}</span></span>`;
  return `<span class="token-avatar${large ? " large" : ""}">${escapeHtml(String(token.symbol || "?").slice(0, 1))}</span>`;
}

function renderTokenCard(token) {
  const risk = token.risk || {};
  const watched = state.watchlist.has(token.address);
  return `
    <article class="token-card" data-address="${escapeHtml(token.address)}">
      <div class="token-card-head">
        <div class="token-identity">${tokenAvatar(token)}<div><strong>${escapeHtml(token.name)}</strong><small>${escapeHtml(token.symbol)} · ${escapeHtml(shortAddress(token.address))}</small></div></div>
        <span class="risk-pill ${riskClass(risk.label)}">${escapeHtml(risk.label)} ${escapeHtml(risk.score)}</span>
      </div>
      <div class="token-price"><strong>${money(token.priceUsd)}</strong><small>${Number(token.priceChange?.h24 || 0) >= 0 ? "+" : ""}${escapeHtml(token.priceChange?.h24 || 0)}% · 24 hours</small></div>
      <div class="token-stats">
        <div><span>Liquidity</span><strong>${money(token.liquidityUsd, true)}</strong></div>
        <div><span>Volume</span><strong>${money(token.volume?.h24, true)}</strong></div>
        <div><span>Age</span><strong>${risk.ageHours ? `${Math.round(risk.ageHours)}h` : "--"}</strong></div>
      </div>
      <div class="token-actions">
        <button class="primary" type="button" data-action="inspect">Inspect</button>
        <button type="button" data-action="watch" aria-label="${watched ? "Remove from" : "Add to"} watchlist">${watched ? "Saved" : "+ Watch"}</button>
      </div>
    </article>`;
}

function paperPlan(token) {
  const mark = Number(token.priceUsd);
  if (!Number.isFinite(mark) || mark <= 0) return [];
  const move = Math.abs(Number(token.priceChange?.h1 || token.priceChange?.h24 || 12));
  const spacing = Math.max(0.04, Math.min(0.18, move / 300));
  return [
    { label: "Bid 1", value: mark * (1 - spacing), side: "buy" },
    { label: "Bid 2", value: mark * (1 - spacing * 2), side: "buy" },
    { label: "Bid 3", value: mark * (1 - spacing * 3), side: "buy" },
    { label: "TP 1", value: mark * (1 + spacing), side: "sell" },
    { label: "TP 2", value: mark * (1 + spacing * 2), side: "sell" },
    { label: "Invalidation", value: mark * (1 - spacing * 4.5), side: "sell" },
  ];
}

function renderTokenDetail(token) {
  const risk = token.risk || {};
  const mint = token.mint || {};
  const levels = paperPlan(token);
  const mintStatus = mint.available
    ? mint.mintAuthorityActive ? "Active" : "Revoked"
    : "Unverified";
  const freezeStatus = mint.available
    ? mint.freezeAuthorityActive ? "Active" : "Revoked"
    : "Unverified";
  els.tokenDetail.innerHTML = `
    <div class="detail-top">
      <div class="detail-title">${tokenAvatar(token, true)}<div><p class="eyebrow">${token.isPumpFun ? "Pump.fun-linked token" : "Solana token"}</p><h2>${escapeHtml(token.name)} <span>${escapeHtml(token.symbol)}</span></h2><p>${escapeHtml(token.address)}</p></div></div>
      <div class="detail-score ${riskClass(risk.label)}"><strong>${escapeHtml(risk.score)}</strong><span>${escapeHtml(risk.label)} · screening score</span></div>
    </div>
    <div class="detail-metrics">
      <article><span>Price</span><strong>${money(token.priceUsd)}</strong></article>
      <article><span>Liquidity</span><strong>${money(token.liquidityUsd, true)}</strong></article>
      <article><span>24h volume</span><strong>${money(token.volume?.h24, true)}</strong></article>
      <article><span>Mint authority</span><strong>${escapeHtml(mintStatus)}</strong></article>
      <article><span>Freeze authority</span><strong>${escapeHtml(freezeStatus)}</strong></article>
    </div>
    <div class="detail-body">
      <section class="risk-list"><h3>Screening notes</h3><ul>${(risk.cautions || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul></section>
      <section class="paper-plan"><h3>Volatility-aware paper grid</h3><div class="paper-grid">${levels.map((level) => `<article class="${level.side}"><span>${escapeHtml(level.label)}</span><strong>${money(level.value)}</strong></article>`).join("")}</div></section>
    </div>
    <div class="detail-links">
      <a href="${escapeHtml(safeUrl(token.pumpFunUrl))}" target="_blank" rel="noreferrer">View on Pump.fun ↗</a>
      <a href="${escapeHtml(safeUrl(token.url))}" target="_blank" rel="noreferrer">Market source ↗</a>
      <button type="button" data-copy-address="${escapeHtml(token.address)}">Copy mint address</button>
    </div>`;
  els.tokenDetail.hidden = false;
  els.tokenDetail.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "request failed");
  return payload;
}

async function inspectAddress(address) {
  const clean = String(address || "").trim();
  els.lookupStatus.classList.remove("error");
  els.lookupStatus.textContent = "Inspecting market data and Solana mint controls…";
  try {
    const token = await fetchJson(`/api/memecoins/token?address=${encodeURIComponent(clean)}`);
    renderTokenDetail(token);
    els.lookupStatus.textContent = `Inspection complete · ${token.source || "public market data"}`;
  } catch (error) {
    els.lookupStatus.textContent = error.message;
    els.lookupStatus.classList.add("error");
  }
}

async function loadRadar() {
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "Scanning…";
  els.tokenGrid.innerHTML = `<div class="loading-card"><span></span><strong>Scanning public markets</strong><small>Looking for Pump.fun mint candidates…</small></div>`;
  try {
    const payload = await fetchJson("/api/memecoins/discover?limit=12");
    state.tokens = payload.tokens || [];
    els.candidateCount.textContent = String(payload.count || state.tokens.length);
    els.screenedCount.textContent = String(state.tokens.filter((token) => Number(token.risk?.score) >= 70).length);
    els.methodology.textContent = `${payload.methodology || "Basic public market screening."} Source: ${payload.source || "public market data"}.`;
    els.tokenGrid.innerHTML = state.tokens.length
      ? state.tokens.map(renderTokenCard).join("")
      : `<div class="loading-card"><strong>No candidates in the latest public profile window</strong><small>Paste a Solana mint address above to inspect it directly.</small></div>`;
  } catch (error) {
    els.tokenGrid.innerHTML = `<div class="loading-card"><strong>Radar temporarily unavailable</strong><small>${escapeHtml(error.message)}. Direct mint inspection is still available.</small></div>`;
  } finally {
    els.refreshButton.disabled = false;
    els.refreshButton.textContent = "Refresh radar";
  }
}

els.lookupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  inspectAddress(els.tokenAddress.value);
});

els.refreshButton.addEventListener("click", loadRadar);

els.tokenGrid.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const card = button.closest("[data-address]");
  const address = card?.dataset.address;
  if (!address) return;
  if (button.dataset.action === "inspect") {
    els.tokenAddress.value = address;
    inspectAddress(address);
    return;
  }
  if (state.watchlist.has(address)) state.watchlist.delete(address); else state.watchlist.add(address);
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...state.watchlist]));
  button.textContent = state.watchlist.has(address) ? "Saved" : "+ Watch";
});

els.tokenDetail.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-address]");
  if (!button) return;
  await navigator.clipboard.writeText(button.dataset.copyAddress);
  button.textContent = "Copied";
});

document.addEventListener("error", (event) => {
  const image = event.target.closest?.("[data-token-image]");
  if (!image) return;
  image.hidden = true;
  if (image.nextElementSibling) image.nextElementSibling.hidden = false;
}, true);

loadRadar();
