const sampleCsv = `timestamp,open,high,low,close,volume
2026-06-04T00:00:00Z,100000,100800,99200,100250,120
2026-06-04T00:01:00Z,100250,101050,99750,100900,130
2026-06-04T00:02:00Z,100900,101400,100100,100300,115
2026-06-04T00:03:00Z,100300,100900,99400,99650,126
2026-06-04T00:04:00Z,99650,100500,99050,100200,140
2026-06-04T00:05:00Z,100200,101200,99700,100850,150
2026-06-04T00:06:00Z,100850,101600,100000,100150,135
2026-06-04T00:07:00Z,100150,100700,99250,99550,111
2026-06-04T00:08:00Z,99550,100450,99000,100350,142
2026-06-04T00:09:00Z,100350,101000,99700,100000,118`;

const els = {
  accountAddressInput: document.querySelector("#accountAddressInput"),
  assetDetail: document.querySelector("#assetDetail"),
  assetGroups: document.querySelector("#assetGroups"),
  assetSelect: document.querySelector("#assetSelect"),
  baseInput: document.querySelector("#baseInput"),
  backendStartButton: document.querySelector("#backendStartButton"),
  backendStatus: document.querySelector("#backendStatus"),
  backendStopButton: document.querySelector("#backendStopButton"),
  accountMetricLabel: document.querySelector("#accountMetricLabel"),
  authStatus: document.querySelector("#authStatus"),
  candleCount: document.querySelector("#candleCount"),
  cashMetricLabel: document.querySelector("#cashMetricLabel"),
  chartIntervalSelect: document.querySelector("#chartIntervalSelect"),
  credentialStatus: document.querySelector("#credentialStatus"),
  contextRadar: document.querySelector("#contextRadar"),
  csvInput: document.querySelector("#csvInput"),
  equityCanvas: document.querySelector("#equityCanvas"),
  equityMetric: document.querySelector("#equityMetric"),
  drawdownMetric: document.querySelector("#drawdownMetric"),
  feeInput: document.querySelector("#feeInput"),
  feesMetric: document.querySelector("#feesMetric"),
  fillCount: document.querySelector("#fillCount"),
  fillTape: document.querySelector("#fillTape"),
  fibAnalysis: document.querySelector("#fibAnalysis"),
  forexSessions: document.querySelector("#forexSessions"),
  freePlanButton: document.querySelector("#freePlanButton"),
  harvestMetric: document.querySelector("#harvestMetric"),
  inventoryMetric: document.querySelector("#inventoryMetric"),
  lastFill: document.querySelector("#lastFill"),
  levelsInput: document.querySelector("#levelsInput"),
  levelsValue: document.querySelector("#levelsValue"),
  liquidityCanvas: document.querySelector("#liquidityCanvas"),
  liquiditySource: document.querySelector("#liquiditySource"),
  credentialGate: document.querySelector("#credentialGate"),
  liveDeskStatus: document.querySelector("#liveDeskStatus"),
  liveModeStatus: document.querySelector("#liveModeStatus"),
  liveNetworkBadge: document.querySelector("#liveNetworkBadge"),
  loginGate: document.querySelector("#loginGate"),
  loginButton: document.querySelector("#loginButton"),
  logoutButton: document.querySelector("#logoutButton"),
  markPrice: document.querySelector("#markPrice"),
  market3dMap: document.querySelector("#market3dMap"),
  marketRadar: document.querySelector("#marketRadar"),
  marketStrip: document.querySelector("#marketStrip"),
  marketTitle: document.querySelector("#marketTitle"),
  orderSizeInput: document.querySelector("#orderSizeInput"),
  executionModeMetric: document.querySelector("#executionModeMetric"),
  openNotionalMetric: document.querySelector("#openNotionalMetric"),
  openOrderBook: document.querySelector("#openOrderBook"),
  openOrderCount: document.querySelector("#openOrderCount"),
  openGridTitle: document.querySelector("#openGridTitle"),
  orderAgeMetric: document.querySelector("#orderAgeMetric"),
  paymentCurrencySelect: document.querySelector("#paymentCurrencySelect"),
  paymentEmailInput: document.querySelector("#paymentEmailInput"),
  paymentDestination: document.querySelector("#paymentDestination"),
  paymentMethodSelect: document.querySelector("#paymentMethodSelect"),
  paymentStatus: document.querySelector("#paymentStatus"),
  passwordInput: document.querySelector("#passwordInput"),
  proPlanButton: document.querySelector("#proPlanButton"),
  quoteInput: document.querySelector("#quoteInput"),
  riskBudgetMetric: document.querySelector("#riskBudgetMetric"),
  exchangeOrderMetric: document.querySelector("#exchangeOrderMetric"),
  registerButton: document.querySelector("#registerButton"),
  resetButton: document.querySelector("#resetButton"),
  riskGate: document.querySelector("#riskGate"),
  riskStatus: document.querySelector("#riskStatus"),
  rulesStatus: document.querySelector("#rulesStatus"),
  rulesSummary: document.querySelector("#rulesSummary"),
  runButton: document.querySelector("#runButton"),
  runState: document.querySelector("#runState"),
  saveRulesButton: document.querySelector("#saveRulesButton"),
  saveCredentialsButton: document.querySelector("#saveCredentialsButton"),
  sessionGuardSelect: document.querySelector("#sessionGuardSelect"),
  secretKeyInput: document.querySelector("#secretKeyInput"),
  runtimeLog: document.querySelector("#runtimeLog"),
  spacingInput: document.querySelector("#spacingInput"),
  spacingValue: document.querySelector("#spacingValue"),
  stepButton: document.querySelector("#stepButton"),
  staleGridCancelInput: document.querySelector("#staleGridCancelInput"),
  subscriptionStatus: document.querySelector("#subscriptionStatus"),
  symbolInput: document.querySelector("#symbolInput"),
  syncMetric: document.querySelector("#syncMetric"),
  londonCommodityInput: document.querySelector("#londonCommodityInput"),
  usernameInput: document.querySelector("#usernameInput")
};

let state = null;
let backendOnline = false;
let currentUser = { authenticated: false, credentialsConfigured: false };
let paymentConfig = null;
let markets = [];
let marketGroups = {};
let selectedAsset = "BTC";
let marketScene = null;
let lastBackendSnapshot = null;
let fibAnalysis = null;
let fibLoading = false;
let fibLastLoadedAt = 0;
let fibLastSymbol = "";
let contextRadar = null;
let contextLoading = false;
let contextLastLoadedAt = 0;
let contextLastSymbol = "";
let tradingRules = {
  chartInterval: "1h",
  londonCommodityOnly: true,
  sessionGuardMinutes: 60,
  staleGridCancel: true
};
localStorage.removeItem("monatiseControlToken");

const assetMetadata = {
  BNB: { name: "BNB", route: "Core Hyperliquid perp" },
  BRENTOIL: { name: "Brent Oil", route: "Hyperliquid xyz:BRENTOIL builder perp" },
  BTC: { name: "Bitcoin", route: "Core Hyperliquid perp" },
  CL: { name: "WTI Crude Oil", route: "Hyperliquid xyz:CL builder perp" },
  DOGE: { name: "Dogecoin", route: "Core Hyperliquid perp" },
  ETH: { name: "Ethereum", route: "Core Hyperliquid perp" },
  GOLD: { name: "Gold", route: "Hyperliquid xyz:GOLD builder perp" },
  HYPE: { name: "Hyperliquid", route: "Core Hyperliquid perp" },
  SOL: { name: "Solana", route: "Core Hyperliquid perp" },
  XRP: { name: "XRP", route: "Core Hyperliquid perp" }
};

const forexSessions = [
  { closeHour: 6, name: "Sydney", openHour: 21, pairs: ["AUDUSD", "NZDUSD", "AUDJPY"] },
  { closeHour: 9, name: "Tokyo", openHour: 0, pairs: ["USDJPY", "AUDJPY", "EURJPY"] },
  { closeHour: 16, name: "London", openHour: 7, pairs: ["EURUSD", "GBPUSD", "EURGBP"] },
  { closeHour: 21, name: "New York", openHour: 12, pairs: ["EURUSD", "GBPUSD", "USDJPY"] }
];
const forexPairs = Array.from(new Set(forexSessions.flatMap((session) => session.pairs)));
const commoditySymbols = ["GOLD", "CL", "BRENTOIL"];

function normalizeForexSymbol(symbol) {
  return String(symbol || "").replace(/[-/]/g, "").toUpperCase();
}

function setGate(element, label, status, className = "") {
  element.classList.remove("ready", "warn", "hot");
  if (className) element.classList.add(className);
  element.querySelector("span").textContent = label;
  element.querySelector("strong").textContent = status;
}

function updateLiveDesk(snapshot = null) {
  const loggedIn = Boolean(currentUser.authenticated);
  const hasCredentials = Boolean(currentUser.credentialsConfigured);
  const paidLive = hasLivePlan();
  const mode = snapshot?.mode || "paper";
  const network = snapshot?.network || "local";
  const running = Boolean(snapshot?.running);
  const backendSessionGuard = snapshot?.sessionGuard || {};
  const localSessionGuard = activeSessionGuard(selectedAsset);
  const sessionGuard = backendSessionGuard.active ? backendSessionGuard : localSessionGuard;
  const sessionBlocked = Boolean(sessionGuard.active && mode === "live");
  const liveReady = Boolean(snapshot?.liveReady && paidLive && !sessionBlocked);
  const requires = Array.isArray(snapshot?.requires) ? snapshot.requires : [];

  setGate(els.loginGate, "Login", loggedIn ? "Ready" : "Needed", loggedIn ? "ready" : "warn");
  setGate(els.credentialGate, "API wallet", hasCredentials ? "Saved" : "Needed", hasCredentials ? "ready" : "warn");
  setGate(
    els.riskGate,
    "Risk gate",
    sessionBlocked ? "Session break" : liveReady ? "Armed" : requires[0] || "Waiting",
    liveReady ? "hot" : mode === "live" || sessionBlocked ? "warn" : "ready"
  );

  els.liveNetworkBadge.textContent = `${mode} / ${network}`;
  els.liveDeskStatus.textContent = running
    ? "Trading loop running"
    : sessionBlocked
      ? "Close trading window"
    : liveReady
      ? "Live armed"
      : loggedIn && hasCredentials
        ? paidLive
          ? "Ready to arm"
          : "Pro required"
        : "Not armed";
  els.liveModeStatus.textContent = running
    ? `${mode.toUpperCase()} running`
    : sessionBlocked
      ? `${sessionGuard.session} ${sessionGuard.transition} guard`
    : liveReady
      ? "Real orders armed"
      : `${mode.toUpperCase()} idle`;
  els.liveModeStatus.classList.toggle("live-mode", mode === "live");
  els.backendStartButton.classList.toggle("live-running", running);
  els.backendStartButton.textContent = running
    ? "Running"
    : sessionBlocked
      ? "Session Guard"
    : mode === "live" && !paidLive
      ? "Pro Required"
      : mode === "live"
        ? "Start Live"
        : "Start Paper";
  els.backendStartButton.disabled = !loggedIn || !hasCredentials || !paidLive || sessionBlocked;
  if (sessionBlocked) {
    els.riskStatus.textContent = sessionGuard.message || "forex session-break guard";
  }
}

async function apiFetch(path, options = {}) {
  return fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(options.headers || {})
    }
  });
}

async function jsonPost(path, payload = {}) {
  return apiFetch(path, {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "POST"
  });
}

function setAuthStatus(message) {
  els.authStatus.textContent = message;
}

function currentPlan() {
  return String(currentUser.subscription?.plan || "free").toLowerCase();
}

function assetLabel(symbol) {
  const meta = assetMetadata[symbol] || {};
  return meta.name ? `${symbol} - ${meta.name}` : symbol;
}

function radarSymbol(symbol) {
  return String(symbol || "").replace(/^xyz:/i, "").toUpperCase();
}

function radarAssetLabel(symbol) {
  const clean = radarSymbol(symbol);
  const meta = assetMetadata[clean];
  if (meta) return assetLabel(clean);
  if (String(symbol || "").toLowerCase().startsWith("xyz:")) return `${clean} - Builder market`;
  return clean;
}

function assetRoute(symbol) {
  return assetMetadata[symbol]?.route || "Watchlist or strategy-preview asset";
}

function minutesSinceUtcMidnight(date) {
  return date.getUTCHours() * 60 + date.getUTCMinutes();
}

function sessionWindow(session) {
  return {
    close: session.closeHour * 60,
    open: session.openHour * 60
  };
}

function isSessionOpen(session, date) {
  const now = minutesSinceUtcMidnight(date);
  const { close, open } = sessionWindow(session);
  if (open < close) return now >= open && now < close;
  return now >= open || now < close;
}

function minutesUntilSessionChange(session, date) {
  const now = minutesSinceUtcMidnight(date);
  const { close, open } = sessionWindow(session);
  const target = isSessionOpen(session, date) ? close : open;
  return (target - now + 1440) % 1440;
}

function londonSession() {
  return forexSessions.find((session) => session.name === "London");
}

function minutesFromUtcMinute(now, target) {
  const before = (target - now + 1440) % 1440;
  const after = (now - target + 1440) % 1440;
  if (before === 0) return { direction: "at", minutes: 0 };
  if (before <= after) return { direction: "before", minutes: before };
  return { direction: "after", minutes: after };
}

function sessionBreakProximity(session, date) {
  const now = minutesSinceUtcMidnight(date);
  const open = minutesFromUtcMinute(now, session.openHour * 60);
  const close = minutesFromUtcMinute(now, session.closeHour * 60);
  if (open.minutes <= close.minutes) {
    return { ...open, transition: "open" };
  }
  return { ...close, transition: "close" };
}

function forexSessionBreakGuard(symbol = selectedAsset, date = new Date()) {
  const pair = normalizeForexSymbol(symbol);
  if (!forexPairs.includes(pair)) return { active: false, symbol: pair };
  const guardMinutes = Number(tradingRules.sessionGuardMinutes || 60);
  const guarded = forexSessions
    .filter((session) => session.pairs.includes(pair))
    .map((session) => {
      const proximity = sessionBreakProximity(session, date);
      return {
        active: proximity.minutes <= guardMinutes,
        direction: proximity.direction,
        minutes: proximity.minutes,
        pairs: session.pairs,
        session: session.name,
        transition: proximity.transition
      };
    })
    .filter((guard) => guard.active)
    .sort((left, right) => left.minutes - right.minutes);
  if (!guarded.length) return { active: false, symbol: pair };
  const primary = guarded[0];
  return {
    active: true,
    affectedPairs: primary.pairs,
    direction: primary.direction,
    guardMinutes,
    message: `forex session-break guard: ${pair} is ${primary.minutes}m ${primary.direction} ${primary.session} ${primary.transition}`,
    minutes: primary.minutes,
    session: primary.session,
    symbol: pair,
    transition: primary.transition
  };
}

function commodityLondonGuard(symbol = selectedAsset, date = new Date()) {
  const asset = radarSymbol(symbol);
  const london = londonSession();
  if (!tradingRules.londonCommodityOnly || !commoditySymbols.includes(asset) || !london) {
    return { active: false, symbol: asset };
  }
  if (isSessionOpen(london, date)) return { active: false, symbol: asset, session: "London" };
  const proximity = sessionBreakProximity(london, date);
  return {
    active: true,
    direction: proximity.direction,
    message: `commodity session guard: ${asset} live grid orders are limited to the London session`,
    minutes: proximity.minutes,
    session: "London",
    symbol: asset,
    transition: proximity.transition
  };
}

function activeSessionGuard(symbol = selectedAsset, date = new Date()) {
  const forexGuard = forexSessionBreakGuard(symbol, date);
  if (forexGuard.active) return forexGuard;
  return commodityLondonGuard(symbol, date);
}

function durationLabel(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours <= 0) return `${remainder}m`;
  return `${hours}h ${String(remainder).padStart(2, "0")}m`;
}

function utcHourLabel(hour) {
  return `${String(hour).padStart(2, "0")}:00`;
}

function activeForexPairs(date = new Date()) {
  return Array.from(
    new Set(
      forexSessions
        .filter((session) => isSessionOpen(session, date))
        .flatMap((session) => session.pairs)
    )
  );
}

function renderForexSessions(date = new Date()) {
  if (!els.forexSessions) return;
  const activePairs = activeForexPairs(date);
  const sessionGuard = activeSessionGuard(selectedAsset, date);
  const rows = forexSessions
    .map((session) => {
      const open = isSessionOpen(session, date);
      const change = minutesUntilSessionChange(session, date);
      const proximity = sessionBreakProximity(session, date);
      const guarded = proximity.minutes <= Number(tradingRules.sessionGuardMinutes || 60);
      return `<article class="session-row ${open ? "open" : "closed"} ${guarded ? "guarded" : ""}">
        <div>
          <strong>${session.name}</strong>
          <span>${utcHourLabel(session.openHour)}-${utcHourLabel(session.closeHour)} UTC</span>
        </div>
        <em>${open ? "Open" : "Closed"}</em>
        <b>${open ? "closes" : "opens"} in ${durationLabel(change)}</b>
      </article>`;
    })
    .join("");
  els.forexSessions.innerHTML = `
    <div class="session-head">
      <strong>Forex Session Timers</strong>
      <span>${date.toISOString().slice(11, 19)} UTC</span>
    </div>
    <div class="session-grid">${rows}</div>
    <div class="session-pairs ${sessionGuard.active ? "guarded" : ""}">
      <strong>${sessionGuard.active ? "Close trading" : "Active pairs"}</strong>
      <span>${
        sessionGuard.active
          ? `${sessionGuard.symbol}: ${durationLabel(sessionGuard.minutes)} ${sessionGuard.direction} ${sessionGuard.session} ${sessionGuard.transition}`
          : activePairs.length
            ? activePairs.join(" · ")
            : "No major session active"
      }</span>
    </div>
  `;
  updateLiveDesk(lastBackendSnapshot);
}

function normalizedTradingRules(rules = {}) {
  const interval = String(rules.chartInterval || "1h");
  return {
    chartInterval: ["1h", "15m", "5m", "1m"].includes(interval) ? interval : "1h",
    londonCommodityOnly: rules.londonCommodityOnly !== false,
    sessionGuardMinutes: [5, 15, 30, 60, 90].includes(Number(rules.sessionGuardMinutes))
      ? Number(rules.sessionGuardMinutes)
      : 60,
    staleGridCancel: rules.staleGridCancel !== false
  };
}

function applyTradingRules(rules = {}) {
  tradingRules = normalizedTradingRules(rules);
  if (tradingRules.chartInterval === "1m" && !hasLivePlan()) {
    tradingRules.chartInterval = "5m";
  }
  els.chartIntervalSelect.value = tradingRules.chartInterval;
  els.chartIntervalSelect.querySelector('option[value="1m"]').disabled = !hasLivePlan();
  els.sessionGuardSelect.value = String(tradingRules.sessionGuardMinutes);
  els.staleGridCancelInput.checked = tradingRules.staleGridCancel;
  els.londonCommodityInput.checked = tradingRules.londonCommodityOnly;
  renderTradingRules();
}

function renderTradingRules() {
  const proNote = hasLivePlan() ? "Pro enabled" : "1m requires Pro";
  els.rulesStatus.textContent = `${tradingRules.chartInterval} grid feed`;
  els.rulesSummary.textContent = `${tradingRules.chartInterval} analysis · ${tradingRules.sessionGuardMinutes}m session guard · ${
    tradingRules.londonCommodityOnly ? "London commodity guard on" : "London commodity guard off"
  } · ${tradingRules.staleGridCancel ? "stale cancel on" : "stale cancel off"} · ${proNote}`;
  els.chartIntervalSelect.querySelector('option[value="1m"]').disabled = !hasLivePlan();
  renderForexSessions();
}

function hasLivePlan() {
  return currentPlan() === "pro";
}

function renderAuth(me) {
  currentUser = me;
  selectedAsset = me.selectedSymbol || selectedAsset;
  applyTradingRules(me.tradingRules || tradingRules);
  const loggedIn = Boolean(me.authenticated);
  els.authStatus.textContent = loggedIn ? me.username : "Logged out";
  els.subscriptionStatus.textContent = me.subscription
    ? `${me.subscription.plan} ${me.subscription.status}`
    : "free active";
  els.credentialStatus.textContent = loggedIn
    ? me.credentialsConfigured
      ? "Hyperliquid credentials saved for this user."
      : "Save your funded account address and API wallet secret key."
    : "Register or log in to connect your own Hyperliquid account.";
  els.logoutButton.disabled = !loggedIn;
  els.saveCredentialsButton.disabled = !loggedIn;
  els.backendStartButton.disabled = !loggedIn || !me.credentialsConfigured || !hasLivePlan();
  els.backendStopButton.disabled = !loggedIn;
  if (loggedIn && me.credentialsConfigured && !hasLivePlan()) {
    els.backendStatus.textContent = "Pro required for mainnet live";
  }
  if (!loggedIn) {
    backendOnline = false;
    els.backendStatus.textContent = "Login required";
  }
  updateLiveDesk();
  syncSelectedAsset();
}

async function loadMe() {
  const response = await apiFetch("/api/me", { cache: "no-store" });
  if (!response.ok) {
    renderAuth({ authenticated: false, credentialsConfigured: false });
    return;
  }
  renderAuth(await response.json());
}

async function loginOrRegister(path) {
  const username = els.usernameInput.value.trim();
  const password = els.passwordInput.value;
  const response = await jsonPost(path, { username, password });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setAuthStatus(payload.error || "Auth failed");
    return;
  }
  els.passwordInput.value = "";
  renderAuth(payload);
  refreshBackend();
}

async function saveCredentials() {
  const response = await jsonPost("/api/credentials", {
    accountAddress: els.accountAddressInput.value.trim(),
    secretKey: els.secretKeyInput.value.trim()
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    els.credentialStatus.textContent = payload.error || "Could not save credentials";
    return;
  }
  els.secretKeyInput.value = "";
  await loadMe();
  refreshBackend();
}

function syncSelectedAsset() {
  if (els.assetSelect.options.length && els.assetSelect.value !== selectedAsset) {
    els.assetSelect.value = selectedAsset;
  }
  els.symbolInput.value = `${selectedAsset}-USD`;
  const live = markets.find((asset) => asset.symbol === selectedAsset);
  if (els.assetDetail) {
    els.assetDetail.innerHTML = `
      <strong>${assetLabel(selectedAsset)}</strong>
      <span>${assetRoute(selectedAsset)}${live ? ` · live mark ${money(live.price)}` : " · not returned by current venue feed"}</span>
    `;
  }
  renderMarkets();
}

async function loadMarkets() {
  try {
    const response = await apiFetch("/api/markets", { cache: "no-store" });
    if (!response.ok) throw new Error("market fetch failed");
    const payload = await response.json();
    markets = (payload.assets || []).filter((asset) => Number.isFinite(Number(asset.price)));
    marketGroups = payload.groups || {};
    if (!els.assetSelect.options.length && markets.length) {
      els.assetSelect.innerHTML = markets
        .map((asset) => `<option value="${asset.symbol}">${assetLabel(asset.symbol)}</option>`)
        .join("");
    }
    if (!markets.some((asset) => asset.symbol === selectedAsset) && markets[0]) {
      selectedAsset = markets[0].symbol;
    }
    syncSelectedAsset();
    loadFibonacciAnalysis();
    loadContextRadar();
    if (!backendOnline) {
      const active = markets.find((asset) => asset.symbol === selectedAsset);
      if (active) {
        els.markPrice.textContent = money(active.price);
        els.marketTitle.textContent = `${selectedAsset}-USD strategy map`;
      }
    }
  } catch {
    if (!els.assetSelect.options.length) {
      ["BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE"].forEach((symbol) => {
        els.assetSelect.add(new Option(assetLabel(symbol), symbol));
      });
    }
  }
}

async function loadFibonacciAnalysis(options = {}) {
  if (fibLoading && !options.force) return;
  const now = Date.now();
  const interval = tradingRules.chartInterval;
  if (!options.force && fibLastSymbol === `${selectedAsset}:${interval}` && now - fibLastLoadedAt < 60_000) return;
  const requestSymbol = selectedAsset;
  const requestInterval = interval;
  let shouldRender = true;
  fibLoading = true;
  try {
    const response = await apiFetch(
      `/api/analysis/fibonacci?symbol=${encodeURIComponent(requestSymbol)}&interval=${encodeURIComponent(requestInterval)}&limit=120`,
      { cache: "no-store" }
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "fibonacci analysis unavailable");
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) {
      shouldRender = false;
      return;
    }
    fibAnalysis = payload.analysis;
    fibLastLoadedAt = now;
    fibLastSymbol = `${requestSymbol}:${requestInterval}`;
  } catch (error) {
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) {
      shouldRender = false;
      return;
    }
    fibAnalysis = { error: error.message || "fibonacci analysis unavailable", symbol: requestSymbol };
    fibLastLoadedAt = now;
    fibLastSymbol = `${requestSymbol}:${requestInterval}`;
  } finally {
    fibLoading = false;
    if (!shouldRender) return;
    renderFibonacciAnalysis();
    if (lastBackendSnapshot) {
      renderBackend(lastBackendSnapshot);
    } else {
      render();
    }
  }
}

function renderFibonacciAnalysis() {
  if (!els.fibAnalysis) return;
  if (!fibAnalysis) {
    els.fibAnalysis.innerHTML = `<div class="fib-head"><strong>Fibonacci Grid Analysis</strong><span>Waiting for live candles</span></div>`;
    return;
  }
  if (fibAnalysis.error) {
    els.fibAnalysis.innerHTML = `<div class="fib-head"><strong>Fibonacci Grid Analysis</strong><span>${fibAnalysis.error}</span></div>`;
    return;
  }
  const levels = (fibAnalysis.levels || [])
    .map(
      (level) => `<span class="fib-level ${level.kind}">
        <strong>${level.label}</strong>
        <em>${money(level.price)}</em>
      </span>`
    )
    .join("");
  els.fibAnalysis.innerHTML = `
    <div class="fib-head">
      <strong>Fibonacci Grid Analysis</strong>
      <span>${fibAnalysis.interval} · ${fibAnalysis.candle_count} live candles · ${fibAnalysis.trend} structure</span>
    </div>
    <div class="fib-metrics">
      <span>High <strong>${money(fibAnalysis.swing_high)}</strong></span>
      <span>Low <strong>${money(fibAnalysis.swing_low)}</strong></span>
      <span>Nearest ${fibAnalysis.nearest_level.label} <strong>${money(fibAnalysis.nearest_level.price)}</strong></span>
      <span>Grid ${money(fibAnalysis.grid_floor)} - ${money(fibAnalysis.grid_ceiling)}</span>
      <span>Invalidation <strong>${money(fibAnalysis.invalidation)}</strong></span>
    </div>
    <div class="fib-levels">${levels}</div>
  `;
}

async function loadContextRadar(options = {}) {
  if (contextLoading && !options.force) return;
  const now = Date.now();
  const interval = tradingRules.chartInterval;
  if (!options.force && contextLastSymbol === `${selectedAsset}:${interval}` && now - contextLastLoadedAt < 60_000) return;
  const requestSymbol = selectedAsset;
  const requestInterval = interval;
  let shouldRender = true;
  contextLoading = true;
  try {
    const response = await apiFetch(
      `/api/context/radar?symbol=${encodeURIComponent(requestSymbol)}&interval=${encodeURIComponent(requestInterval)}&limit=120`,
      { cache: "no-store" }
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "context radar unavailable");
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) {
      shouldRender = false;
      return;
    }
    contextRadar = payload;
    contextLastLoadedAt = now;
    contextLastSymbol = `${requestSymbol}:${requestInterval}`;
  } catch (error) {
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) {
      shouldRender = false;
      return;
    }
    contextRadar = { error: error.message || "context radar unavailable", symbol: requestSymbol };
    contextLastLoadedAt = now;
    contextLastSymbol = `${requestSymbol}:${requestInterval}`;
  } finally {
    contextLoading = false;
    if (shouldRender) renderContextRadar();
  }
}

function renderContextRadar() {
  if (!els.contextRadar) return;
  if (!contextRadar) {
    els.contextRadar.innerHTML = `<div class="context-head"><strong>Context Radar</strong><span>Waiting for indicators</span></div>`;
    return;
  }
  if (contextRadar.error) {
    els.contextRadar.innerHTML = `<div class="context-head"><strong>Context Radar</strong><span>${contextRadar.error}</span></div>`;
    return;
  }
  const indicator = contextRadar.indicator || {};
  const instruction = contextRadar.instruction || {};
  const action = String(instruction.action || "normal");
  const assets = (contextRadar.contextAssets || [])
    .map((asset) => {
      const price = Number(asset.price);
      const hasPrice = asset.price !== null && asset.price !== undefined && Number.isFinite(price);
      return `<span class="context-asset ${hasPrice ? "live" : "offline"}">
        <strong>${asset.symbol}</strong>
        <em>${asset.label}</em>
        <b>${hasPrice ? money(price) : "External / pending"}</b>
      </span>`;
    })
    .join("");
  const reasons = (instruction.reasons || []).map((reason) => `<li>${reason}</li>`).join("");
  els.contextRadar.innerHTML = `
    <div class="context-head">
      <strong>Context Radar</strong>
      <span>${contextRadar.interval} · ${assetLabel(contextRadar.symbol)} · ${action.toUpperCase()}</span>
    </div>
    <div class="context-action ${action}">
      <strong>${action}</strong>
      <span>Spacing x${Number(instruction.spacingMultiplier || 0).toFixed(2)} · Size x${Number(instruction.sizeMultiplier || 0).toFixed(2)}</span>
    </div>
    <div class="context-metrics">
      <span>ATR <strong>${money(indicator.atr || 0)}</strong></span>
      <span>ATR% <strong>${((indicator.atr_pct || 0) * 100).toFixed(2)}%</strong></span>
      <span>Chop <strong>${Number(indicator.choppiness || 0).toFixed(1)}</strong></span>
      <span>RSI <strong>${Number(indicator.rsi || 0).toFixed(1)}</strong></span>
      <span>Trend <strong>${String(indicator.trend || "flat").toUpperCase()}</strong></span>
    </div>
    <div class="context-assets">${assets}</div>
    <ul class="context-reasons">${reasons}</ul>
  `;
}

function renderMarkets() {
  els.marketStrip.innerHTML = markets
    .map(
      (asset) => `<button type="button" data-symbol="${asset.symbol}" class="${asset.symbol === selectedAsset ? "active" : ""}">
        <strong>${assetLabel(asset.symbol)}</strong>
        <span>${money(asset.price)}</span>
      </button>`
    )
    .join("");
  renderMarketRadar();
  renderAssetGroups();
  updateMarketMap();
}

function radarSection(title, items, limit = 18) {
  const visible = (items || []).slice(0, limit);
  return `<section class="market-radar-section">
    <div class="market-radar-head">
      <strong>${title}</strong>
      <span>${visible.length} assets</span>
    </div>
    <div class="market-radar-grid">
      ${
        visible.length
          ? visible
              .map((asset) => {
                const price = Number(asset.price);
                const hasPrice = asset.price !== null && asset.price !== undefined && Number.isFinite(price);
                const clean = radarSymbol(asset.symbol);
                const selectable = Array.from(els.assetSelect.options).some((option) => option.value === clean);
                const tag = selectable ? "button" : "span";
                const status = asset.tradable && hasPrice ? "Live" : hasPrice ? "Watch" : "Offline";
                const attrs = selectable ? ` type="button" data-symbol="${clean}"` : "";
                return `<${tag}${attrs} class="market-radar-row ${selectable ? "selectable" : ""} ${clean === selectedAsset ? "active" : ""}">
                  <strong>${radarAssetLabel(asset.symbol)}</strong>
                  <span>${hasPrice ? money(price) : "No mark"}</span>
                  <small>${status}</small>
                </${tag}>`;
              })
              .join("")
          : '<span class="market-radar-empty">No marks returned</span>'
      }
    </div>
  </section>`;
}

function renderMarketRadar() {
  if (!els.marketRadar) return;
  const commodityWatch = marketGroups.commodities && marketGroups.commodities.length
    ? marketGroups.commodities
    : [];
  const sections = [
    ["Routed", marketGroups.crypto || markets, 12],
    ["Gold / Oil", commodityWatch, 8],
    ["Builder", marketGroups.builder || [], 18],
    ["Stocks", marketGroups.stocks || [], 8],
    ["Forex", marketGroups.forex || [], 8]
  ];
  els.marketRadar.innerHTML = sections
    .map(([title, items, limit]) => radarSection(title, items, limit))
    .join("");
}

function renderAssetGroups() {
  const commodityWatch = marketGroups.commodities && marketGroups.commodities.length
    ? [...marketGroups.commodities]
    : ["GOLD", "CL", "BRENTOIL"].map((symbol) => ({ symbol, tradable: false }));
  ["GOLD", "CL", "BRENTOIL"].forEach((symbol) => {
    if (!commodityWatch.some((asset) => asset.symbol === symbol)) {
      commodityWatch.push({ symbol, tradable: false });
    }
  });
  const forexWatch = marketGroups.forex && marketGroups.forex.length
    ? [...marketGroups.forex]
    : ["EURUSD", "GBPUSD", "USDJPY", "XAG"].map((symbol) => ({ symbol, tradable: false }));
  const groups = [
    ["Routed markets", marketGroups.crypto || markets],
    ["HIP-3 builder", marketGroups.builder || []],
    ["Gold / oil perps", commodityWatch],
    ["Forex watch", forexWatch],
    ["Stock watch", marketGroups.stocks || []]
  ];
  els.assetGroups.innerHTML = groups
    .map(([title, items]) => {
      const visible = (items || []).slice(0, 8);
      return `<section class="asset-group">
        <h3>${title}</h3>
        <div class="asset-list">
          ${
            visible.length
              ? visible
                  .map((asset) => {
                    const tradable = asset.tradable && Number.isFinite(Number(asset.price));
                    if (tradable) {
                      return `<button type="button" data-symbol="${asset.symbol}">${assetLabel(asset.symbol)} ${money(asset.price)}</button>`;
                    }
                    return `<span class="asset-chip unavailable">${assetLabel(asset.symbol)}</span>`;
                  })
                  .join("")
              : '<span class="asset-chip unavailable">No live listings</span>'
          }
        </div>
      </section>`;
    })
    .join("");
}

async function saveSelectedAsset(symbol) {
  selectedAsset = symbol;
  fibAnalysis = null;
  contextRadar = null;
  syncSelectedAsset();
  rebuildFromInputs();
  loadFibonacciAnalysis({ force: true });
  loadContextRadar({ force: true });
  if (!currentUser.authenticated) {
    render();
    return;
  }
  const response = await jsonPost("/api/settings", { selectedSymbol: symbol });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    els.riskStatus.textContent = payload.error || "asset update failed";
    return;
  }
  currentUser = {
    ...currentUser,
    selectedSymbol: payload.selectedSymbol,
    subscription: payload.subscription || currentUser.subscription
  };
  refreshBackend();
}

async function checkoutPlan(plan) {
  if (!currentUser.authenticated) {
    els.subscriptionStatus.textContent = "login required";
    return;
  }
  const response = await jsonPost("/api/payments/checkout", {
    currency: els.paymentCurrencySelect.value,
    email: els.paymentEmailInput.value.trim(),
    method: els.paymentMethodSelect.value,
    plan
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    els.paymentStatus.textContent = payload.error || "payment error";
    return;
  }
  if (payload.status === "redirect" && payload.checkoutUrl) {
    window.location.href = payload.checkoutUrl;
    return;
  }
  if (payload.provider === "crypto") {
    els.paymentStatus.textContent = payload.setupRequired
      ? "crypto address not configured"
      : `${payload.recipient || "Monatise"} receives ${payload.amount} ${payload.currency} on ${payload.network}: ${payload.address} ref ${payload.reference}`;
    return;
  }
  if (payload.status === "setup_required") {
    els.paymentStatus.textContent = payload.message || "payment setup required";
    return;
  }
  if (payload.subscription) {
    currentUser = { ...currentUser, subscription: payload.subscription };
    els.subscriptionStatus.textContent = `${payload.subscription.plan} ${payload.subscription.status}`;
    els.paymentStatus.textContent = `${payload.subscription.plan} active`;
  }
}

async function loadPaymentConfig() {
  try {
    const response = await fetch("/api/payments/config");
    if (!response.ok) throw new Error("payment config unavailable");
    paymentConfig = await response.json();
    renderPaymentDestination();
  } catch (error) {
    els.paymentDestination.textContent = "Payment destination unavailable.";
  }
}

function renderPaymentDestination() {
  if (!paymentConfig || !els.paymentDestination) return;
  const rails = paymentConfig.rails || {};
  const ready = [];
  if (rails.stripe?.configured) ready.push("Stripe merchant account");
  if (rails.flutterwave?.configured) ready.push("Flutterwave merchant account");
  if (rails.crypto?.configured) ready.push(`${rails.crypto.network}: ${rails.crypto.destination}`);
  const missing = [];
  if (rails.stripe && !rails.stripe.configured) {
    missing.push(rails.stripe.webhookConfigured ? "Stripe secret" : "Stripe secret/webhook");
  }
  if (rails.flutterwave && !rails.flutterwave.configured) missing.push("Flutterwave secret");
  if (rails.crypto && !rails.crypto.configured) missing.push("crypto wallet");
  const destination = ready.length ? ready.join(" · ") : "No paid payment rail configured yet";
  const setup = missing.length ? ` Setup needed: ${missing.join(", ")}.` : "";
  els.paymentDestination.textContent = `Recipient: ${paymentConfig.recipient || "Monatise"}. Destination: ${destination}.${setup}`;
}

function initMarketMap() {
  if (marketScene || !window.THREE || !els.market3dMap) return;
  const THREE = window.THREE;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  camera.position.set(0, 5.2, 12);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  els.market3dMap.appendChild(renderer.domElement);

  const group = new THREE.Group();
  scene.add(group);

  const ambient = new THREE.AmbientLight(0xffffff, 0.72);
  scene.add(ambient);
  const key = new THREE.PointLight(0x00d4ff, 2.2, 40);
  key.position.set(-5, 5, 7);
  scene.add(key);
  const fill = new THREE.PointLight(0xffbe0b, 1.6, 35);
  fill.position.set(6, -2, 4);
  scene.add(fill);

  const grid = new THREE.GridHelper(18, 18, 0x3a86ff, 0x24505d);
  grid.position.y = -2.2;
  grid.material.transparent = true;
  grid.material.opacity = 0.34;
  scene.add(grid);

  const ringMaterial = new THREE.MeshBasicMaterial({ color: 0x00d4ff, transparent: true, opacity: 0.24, side: THREE.DoubleSide });
  const ring = new THREE.Mesh(new THREE.RingGeometry(3.2, 3.25, 96), ringMaterial);
  ring.rotation.x = Math.PI / 2;
  group.add(ring);

  marketScene = { camera, group, renderer, scene, sprites: [] };
  resizeMarketMap();
  animateMarketMap();
}

function updateMarketMap() {
  initMarketMap();
  if (!marketScene || !window.THREE) return;
  const THREE = window.THREE;
  marketScene.sprites.forEach((sprite) => marketScene.group.remove(sprite));
  marketScene.sprites = [];
  const values = markets.map((asset) => Number(asset.price || 0)).filter(Boolean);
  const min = Math.min(...values, 1);
  const max = Math.max(...values, 1);
  markets.slice(0, 10).forEach((asset, index) => {
    const price = Number(asset.price || 0);
    const t = (price - min) / Math.max(1, max - min);
    const angle = (index / Math.max(1, markets.length)) * Math.PI * 2;
    const radius = 2.6 + t * 2.6;
    const geometry = new THREE.SphereGeometry(0.16 + t * 0.32, 24, 24);
    const palette = [0x00d4ff, 0x00a878, 0xffbe0b, 0xff4d6d, 0x8338ec, 0xfb5607];
    const material = new THREE.MeshStandardMaterial({
      color: palette[index % palette.length],
      emissive: palette[index % palette.length],
      emissiveIntensity: asset.symbol === selectedAsset ? 0.65 : 0.25,
      metalness: 0.34,
      roughness: 0.28
    });
    const sphere = new THREE.Mesh(geometry, material);
    sphere.position.set(Math.cos(angle) * radius, -0.25 + t * 2.1, Math.sin(angle) * radius);
    sphere.userData = { angle, radius, speed: 0.004 + index * 0.0007, t };
    marketScene.group.add(sphere);
    marketScene.sprites.push(sphere);
  });
}

function resizeMarketMap() {
  if (!marketScene) return;
  const rect = els.market3dMap.getBoundingClientRect();
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  marketScene.renderer.setSize(width, height, false);
  marketScene.camera.aspect = width / height;
  marketScene.camera.updateProjectionMatrix();
}

function animateMarketMap() {
  if (!marketScene) return;
  marketScene.group.rotation.y += 0.0035;
  marketScene.sprites.forEach((sprite) => {
    const data = sprite.userData;
    data.angle += data.speed;
    sprite.position.x = Math.cos(data.angle) * data.radius;
    sprite.position.z = Math.sin(data.angle) * data.radius;
    sprite.position.y += Math.sin(Date.now() * 0.002 + data.radius) * 0.002;
  });
  marketScene.renderer.render(marketScene.scene, marketScene.camera);
  requestAnimationFrame(animateMarketMap);
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: "currency"
  }).format(value || 0);
}

function currentMarketPrice() {
  const live = markets.find((asset) => asset.symbol === selectedAsset);
  return Number.isFinite(Number(live?.price)) ? Number(live.price) : null;
}

function parseCsv(text) {
  const rows = text.trim().split(/\r?\n/).filter(Boolean);
  const headers = rows.shift().split(",").map((header) => header.trim());
  return rows.map((row) => {
    const values = row.split(",").map((value) => value.trim());
    const item = Object.fromEntries(headers.map((header, index) => [header, values[index]]));
    return {
      timestamp: item.timestamp,
      open: Number(item.open),
      high: Number(item.high),
      low: Number(item.low),
      close: Number(item.close),
      volume: Number(item.volume || 0)
    };
  });
}

function scaleCandlesToSelectedAsset(candles) {
  const liveMark = currentMarketPrice();
  const reference = Number(candles[0]?.close || candles[0]?.open || 0);
  if (!liveMark || !reference) return candles;
  const scale = liveMark / reference;
  return candles.map((candle) => ({
    ...candle,
    close: candle.close * scale,
    high: candle.high * scale,
    low: candle.low * scale,
    open: candle.open * scale
  }));
}

function configFromInputs() {
  const candles = scaleCandlesToSelectedAsset(parseCsv(els.csvInput.value));
  if (!candles.length) {
    throw new Error("No candles found");
  }
  return {
    base: Number(els.baseInput.value),
    candles,
    feeRate: Number(els.feeInput.value) / 100,
    levelsEachSide: Number(els.levelsInput.value),
    orderQuoteSize: Number(els.orderSizeInput.value),
    quote: Number(els.quoteInput.value),
    spacingPct: Number(els.spacingInput.value) / 100,
    symbol: `${selectedAsset}-USD`,
    targetInventoryRatio: 0.5,
    maxInventorySkew: 0.25
  };
}

function createState(config) {
  const first = config.candles[0];
  return {
    ...config,
    activeIndex: 0,
    base: config.base,
    equityCurve: [{ timestamp: first.timestamp, equity: config.quote + config.base * first.open }],
    feePaid: 0,
    fills: [],
    openOrders: [],
    quote: config.quote,
    realizedHarvest: 0,
    restingBuys: new Map()
  };
}

function equity(mark) {
  return state.quote + state.base * mark;
}

function inventoryRatio(mark) {
  const total = equity(mark);
  return total <= 0 ? 0 : (state.base * mark) / total;
}

function buildLevels(mark) {
  const levels = [];
  for (let index = state.levelsEachSide; index > 0; index -= 1) {
    levels.push({
      levelId: `buy-${index}`,
      price: mark * (1 - state.spacingPct * index),
      side: "buy"
    });
  }
  for (let index = 1; index <= state.levelsEachSide; index += 1) {
    levels.push({
      levelId: `sell-${index}`,
      price: mark * (1 + state.spacingPct * index),
      side: "sell"
    });
  }
  return levels;
}

function planOrders(mark) {
  const ratio = inventoryRatio(mark);
  const buyAllowed = ratio <= state.targetInventoryRatio + state.maxInventorySkew;
  const sellAllowed = ratio >= state.targetInventoryRatio - state.maxInventorySkew;
  let availableQuote = state.quote;
  let availableBase = state.base;

  state.openOrders = buildLevels(mark).flatMap((level, index) => {
    if (level.side === "buy" && !buyAllowed) return [];
    if (level.side === "sell" && !sellAllowed) return [];

    const quantity = state.orderQuoteSize / level.price;
    const notional = quantity * level.price;
    const fee = notional * state.feeRate;

    if (level.side === "buy" && notional + fee <= availableQuote + 1e-8) {
      availableQuote = Math.max(0, availableQuote - notional - fee);
      return [{ ...level, orderId: `local-${state.activeIndex}-${index}`, quantity }];
    }

    if (level.side === "sell" && quantity <= availableBase + 1e-10) {
      availableBase = Math.max(0, availableBase - quantity);
      return [{ ...level, orderId: `local-${state.activeIndex}-${index}`, quantity }];
    }

    return [];
  });
}

function applyFill(fill) {
  const fee = fill.price * fill.quantity * state.feeRate;
  fill.fee = fee;

  if (fill.side === "buy") {
    state.quote -= fill.price * fill.quantity + fee;
    state.base += fill.quantity;
    state.restingBuys.set(fill.levelId, fill);
  } else {
    state.quote += fill.price * fill.quantity - fee;
    state.base -= fill.quantity;
    const paired = state.restingBuys.get(fill.levelId.replace("sell", "buy"));
    if (paired) {
      state.realizedHarvest += (fill.price - paired.price) * Math.min(fill.quantity, paired.quantity) - fill.fee - paired.fee;
      state.restingBuys.delete(paired.levelId);
    }
  }

  state.feePaid += fee;
  state.fills.push(fill);
}

function stepSimulation() {
  const candle = state.candles[state.activeIndex];
  if (!candle) return false;

  if (!state.openOrders.length) {
    planOrders(candle.open);
  }

  const crossed = [];
  state.openOrders = state.openOrders.filter((order) => {
    const hit = order.side === "buy" ? candle.low <= order.price : candle.high >= order.price;
    if (hit) {
      crossed.push({
        orderId: order.orderId,
        levelId: order.levelId,
        price: order.price,
        quantity: order.quantity,
        side: order.side,
        symbol: state.symbol,
        timestamp: candle.timestamp
      });
    }
    return !hit;
  });

  crossed.forEach(applyFill);
  state.equityCurve.push({ timestamp: candle.timestamp, equity: equity(candle.close) });
  planOrders(candle.close);
  state.activeIndex += 1;
  return true;
}

function runAll() {
  while (state.activeIndex < state.candles.length) {
    stepSimulation();
  }
}

function setupCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, height: rect.height, width: rect.width };
}

function drawLiquidity(options = {}) {
  const { ctx, height, width } = setupCanvas(els.liquidityCanvas);
  const candle = state.candles[Math.max(0, Math.min(state.activeIndex, state.candles.length - 1))];
  const mark = Number(options.mark ?? currentMarketPrice() ?? candle.close);
  const sourceType = options.sourceType || "preview";
  const sourceLabel = options.sourceLabel || "Strategy preview only. No exchange orders.";
  const orders = Array.isArray(options.orders) ? options.orders : buildLevels(mark);
  const prices = [
    ...orders.map((order) => Number(order.price)).filter((price) => Number.isFinite(price)),
    ...((fibAnalysis?.levels || []).map((level) => Number(level.price)).filter((price) => Number.isFinite(price))),
    Number(fibAnalysis?.grid_floor),
    Number(fibAnalysis?.grid_ceiling),
    candle.high,
    candle.low,
    mark
  ].filter((price) => Number.isFinite(price));
  const min = Math.min(...prices) * 0.998;
  const max = Math.max(...prices) * 1.002;
  const yFor = (price) => height - 34 - ((price - min) / (max - min || 1)) * (height - 72);

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfa";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#d9ded8";
  ctx.lineWidth = 1;
  for (let i = 0; i < 6; i += 1) {
    const y = 30 + (i * (height - 64)) / 5;
    ctx.beginPath();
    ctx.moveTo(24, y);
    ctx.lineTo(width - 24, y);
    ctx.stroke();
  }

  ctx.fillStyle = sourceType === "live" ? "#eafff5" : sourceType === "backend" ? "#eef7ff" : "#fff8df";
  ctx.strokeStyle = sourceType === "live" ? "#0f9f7a" : sourceType === "backend" ? "#246bfe" : "#d69b00";
  ctx.lineWidth = 1;
  const badgeWidth = Math.min(width - 48, 450);
  ctx.fillRect(24, 16, badgeWidth, 30);
  ctx.strokeRect(24, 16, badgeWidth, 30);
  ctx.fillStyle = "#202523";
  ctx.font = "800 12px system-ui";
  ctx.textAlign = "left";
  ctx.fillText(sourceLabel, 36, 36);

  const markY = yFor(mark);
  ctx.strokeStyle = "#20323a";
  ctx.lineWidth = 2;
  ctx.setLineDash([7, 7]);
  ctx.beginPath();
  ctx.moveTo(32, markY);
  ctx.lineTo(width - 32, markY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#202523";
  ctx.font = "850 12px system-ui";
  ctx.textAlign = "center";
  ctx.fillText(`MARK ${money(mark)}`, width / 2, Math.max(58, markY - 10));

  if (fibAnalysis && !fibAnalysis.error && fibAnalysis.symbol === selectedAsset) {
    ctx.font = "800 11px system-ui";
    (fibAnalysis.levels || []).forEach((level) => {
      const price = Number(level.price);
      if (!Number.isFinite(price)) return;
      const y = yFor(price);
      const isExtension = level.kind === "extension";
      ctx.strokeStyle = isExtension ? "rgba(199, 71, 71, 0.72)" : "rgba(15, 159, 122, 0.72)";
      ctx.lineWidth = isExtension ? 2 : 1.5;
      ctx.setLineDash(isExtension ? [9, 7] : [4, 5]);
      ctx.beginPath();
      ctx.moveTo(32, y);
      ctx.lineTo(width - 32, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = isExtension ? "#9e2f2f" : "#0b755b";
      ctx.textAlign = "left";
      ctx.fillText(`FIB ${level.label} ${money(price)}`, 38, Math.max(54, y - 6));
    });
  }

  if (!orders.length) {
    ctx.fillStyle = "#56605c";
    ctx.font = "850 14px system-ui";
    ctx.textAlign = "center";
    ctx.fillText("No resting exchange orders yet", width / 2, height / 2);
  }

  orders.forEach((level) => {
    const price = Number(level.price);
    if (!Number.isFinite(price)) return;
    const y = yFor(price);
    const side = String(level.side || "").toLowerCase();
    const isBuy = side === "buy" || side === "b";
    const start = isBuy ? 40 : width * 0.52;
    const end = isBuy ? width * 0.48 : width - 40;
    ctx.strokeStyle = isBuy ? "#0f9f7a" : "#c74747";
    ctx.lineWidth = sourceType === "live" ? 7 : 4;
    ctx.beginPath();
    ctx.moveTo(start, y);
    ctx.lineTo(end, y);
    ctx.stroke();

    ctx.fillStyle = "#202523";
    ctx.font = "700 12px system-ui";
    ctx.textAlign = isBuy ? "left" : "right";
    const quantity = Number(level.quantity || 0);
    const prefix = sourceType === "live" ? "LIVE" : "PREVIEW";
    const size = quantity > 0 ? ` · ${quantity.toFixed(5)} ${selectedAsset}` : "";
    ctx.fillText(`${prefix} ${isBuy ? "BUY" : "SELL"} ${money(price)}${size}`, isBuy ? 42 : width - 42, y - 9);
  });

  const candleX = width / 2;
  ctx.strokeStyle = "#365f6b";
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.moveTo(candleX, yFor(candle.low));
  ctx.lineTo(candleX, yFor(candle.high));
  ctx.stroke();
  ctx.fillStyle = "#d29d2b";
  ctx.beginPath();
  ctx.arc(candleX, yFor(candle.close), 7, 0, Math.PI * 2);
  ctx.fill();

  state.fills.slice(-12).forEach((fill, index) => {
    const x = 80 + index * Math.max(24, (width - 160) / 12);
    const y = yFor(fill.price);
    ctx.fillStyle = fill.side === "buy" ? "#0f9f7a" : "#c74747";
    ctx.globalAlpha = 0.22 + index / 18;
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  });

  ctx.fillStyle = "#6b746f";
  ctx.font = "750 12px system-ui";
  ctx.textAlign = "center";
  ctx.fillText(sourceType === "preview" ? `sample candle ${candle.timestamp}` : `live ${selectedAsset} order state`, width / 2, height - 12);
}

function drawEquity() {
  const { ctx, height, width } = setupCanvas(els.equityCanvas);
  const points = state.equityCurve;
  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const xFor = (index) => 16 + (index / Math.max(1, points.length - 1)) * (width - 32);
  const yFor = (value) => height - 18 - ((value - min) / span) * (height - 36);

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfa";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d9ded8";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(12, height - 18);
  ctx.lineTo(width - 12, height - 18);
  ctx.stroke();

  ctx.strokeStyle = "#365f6b";
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.equity);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#202523";
  ctx.font = "750 12px system-ui";
  ctx.fillText(money(values[values.length - 1] || 0), 16, 18);
}

function renderTape() {
  const fills = state.fills.slice(-20).reverse();
  els.fillTape.innerHTML = fills
    .map(
      (fill) => `<article class="fill-row ${fill.side}">
        <div>
          <strong>${fill.side} ${fill.levelId}</strong>
          <em>${fill.timestamp}</em>
        </div>
        <span>${money(fill.price)}</span>
      </article>`
    )
    .join("");
  els.lastFill.textContent = fills[0] ? `${fills[0].side.toUpperCase()} ${money(fills[0].price)}` : "No fills";
}

function renderBackend(snapshot) {
  backendOnline = true;
  lastBackendSnapshot = snapshot;
  els.backendStatus.textContent = `${snapshot.mode} ${snapshot.running ? "running" : "stopped"}`;
  els.candleCount.textContent = snapshot.running ? "backend loop" : "backend idle";
    els.riskStatus.textContent = snapshot.riskStatus || "ready";
  els.runState.textContent = snapshot.running ? "Backend running" : "Backend ready";
  updateLiveDesk(snapshot);
  if (snapshot.markPrice) {
    els.markPrice.textContent = money(snapshot.markPrice);
    selectedAsset = snapshot.symbol || selectedAsset;
    syncSelectedAsset();
  }
  if (snapshot.portfolio) {
    els.equityMetric.textContent = money(snapshot.account?.displayValue ?? snapshot.account?.accountValue ?? snapshot.portfolio.equity);
    if (snapshot.account && Number.isFinite(Number(snapshot.account.accountValue))) {
      els.accountMetricLabel.textContent = "Perp Account";
      els.cashMetricLabel.textContent = "Spot USDC";
      els.harvestMetric.textContent = money(snapshot.account.accountValue);
      els.feesMetric.textContent = money(snapshot.account.spotUsdc || 0);
    } else {
      els.accountMetricLabel.textContent = "Harvest";
      els.cashMetricLabel.textContent = "Fees";
      els.harvestMetric.textContent = money(snapshot.portfolio.realizedHarvest);
      els.feesMetric.textContent = money(snapshot.portfolio.feePaid);
    }
    els.inventoryMetric.textContent = snapshot.account && Number.isFinite(Number(snapshot.account.positionSize))
      ? `${Number(snapshot.account.positionSize || 0).toFixed(5)} ${snapshot.symbol}`
      : `${(snapshot.portfolio.inventoryRatio * 100).toFixed(2)}%`;
  }
  if (snapshot.risk) {
    els.drawdownMetric.textContent = `${money(snapshot.risk.drawdown)} (${((snapshot.risk.drawdown_pct || 0) * 100).toFixed(2)}%)`;
    els.openNotionalMetric.textContent = money(snapshot.risk.open_order_notional || 0);
    els.riskBudgetMetric.textContent = `${money(snapshot.risk.max_daily_loss || 0)} loss`;
  }
  if (snapshot.desk) {
    els.executionModeMetric.textContent = snapshot.desk.executionMode || snapshot.executionMode || "dry_run";
    els.orderAgeMetric.textContent = `${Math.round(snapshot.desk.orderAgeSeconds || 0)}s / ${Math.round(snapshot.desk.orderRefreshSeconds || 0)}s`;
    els.syncMetric.textContent = `${snapshot.desk.reconciledFillCount || 0} fills / ${Math.round(snapshot.desk.lastReconciliationSeconds || 0)}s`;
    els.exchangeOrderMetric.textContent = String(snapshot.desk.exchangeOrderCount || 0);
  }
  const liveOrders = snapshot.openOrders || [];
  const hasExchangeState = Boolean(snapshot.running || snapshot.liveReady || snapshot.desk?.exchangeOrderCount || liveOrders.length);
  renderOpenOrders(liveOrders, {
    emptyText: hasExchangeState ? "No resting exchange orders" : "Backend connected",
    emptyHint: hasExchangeState ? "Arm the desk to place live grid orders" : "No live orders are being shown",
    source: hasExchangeState ? "live" : "backend",
    title: hasExchangeState ? "Live Orders" : "Backend State"
  });
  const liveMark = Number(snapshot.markPrice ?? currentMarketPrice());
  const sourceLabel = hasExchangeState
    ? `${String(snapshot.mode || "live").toUpperCase()} ${String(snapshot.network || "mainnet").toUpperCase()} exchange/order state`
    : "Backend connected - no resting exchange orders";
  els.liquiditySource.textContent = sourceLabel;
  drawLiquidity({
    mark: Number.isFinite(liveMark) ? liveMark : undefined,
    orders: liveOrders,
    sourceLabel,
    sourceType: hasExchangeState ? "live" : "backend"
  });
  if (Array.isArray(snapshot.fills)) {
    els.fillCount.textContent = `${snapshot.fills.length} fills`;
    const fills = snapshot.fills.slice(-20).reverse();
    els.fillTape.innerHTML = fills
      .map(
        (fill) => `<article class="fill-row ${fill.side}">
          <div>
            <strong>${fill.side} ${fill.level_id}</strong>
            <em>${fill.timestamp}</em>
          </div>
          <span>${money(fill.price)}</span>
        </article>`
      )
      .join("");
    els.lastFill.textContent = fills[0] ? `${fills[0].side.toUpperCase()} ${money(fills[0].price)}` : "No fills";
  }
  if (Array.isArray(snapshot.events)) {
    els.runtimeLog.innerHTML = snapshot.events
      .slice(-12)
      .reverse()
      .map((event) => `<article class="${event.level}">${event.message}</article>`)
      .join("");
  }
}

function renderOpenOrders(orders, options = {}) {
  const source = options.source || "preview";
  els.openGridTitle.textContent = options.title || (source === "live" ? "Live Orders" : "Strategy Preview");
  els.openOrderCount.textContent = `${orders.length} orders`;
  els.openOrderBook.innerHTML = orders.length
    ? orders
        .slice(0, 12)
        .map(
          (order) => `<article class="order-row ${order.side} ${source}">
            <strong>${String(order.side).toUpperCase()} ${money(order.price)}</strong>
            <span>${Number(order.quantity || 0).toFixed(5)} ${order.symbol || selectedAsset}</span>
          </article>`
        )
        .join("")
    : `<article class="order-row empty"><strong>${options.emptyText || "No resting grid"}</strong><span>${options.emptyHint || "Waiting for arm"}</span></article>`;
}

async function refreshBackend() {
  try {
    if (!currentUser.authenticated) {
      backendOnline = false;
      lastBackendSnapshot = null;
      els.backendStatus.textContent = "Login required";
      updateLiveDesk();
      return;
    }
    const response = await apiFetch("/api/status", { cache: "no-store" });
    if (response.status === 401) {
      backendOnline = false;
      lastBackendSnapshot = null;
      els.backendStatus.textContent = "Login required";
      renderAuth({ authenticated: false, credentialsConfigured: false });
      return;
    }
    if (!response.ok) throw new Error("backend offline");
    renderBackend(await response.json());
  } catch {
    backendOnline = false;
    lastBackendSnapshot = null;
    els.backendStatus.textContent = "Offline";
    updateLiveDesk();
  }
}

async function backendCommand(path) {
  const sessionGuard = activeSessionGuard(selectedAsset);
  if (path === "/api/start" && sessionGuard.active && lastBackendSnapshot?.mode === "live") {
    els.riskStatus.textContent = sessionGuard.message;
    updateLiveDesk(lastBackendSnapshot);
    return;
  }
  const response = await jsonPost(path);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    els.riskStatus.textContent = payload.error || `request failed: ${path}`;
    throw new Error(payload.error || `request failed: ${path}`);
  }
  renderBackend(await response.json());
}

async function saveTradingRules() {
  const nextRules = normalizedTradingRules({
    chartInterval: els.chartIntervalSelect.value,
    londonCommodityOnly: els.londonCommodityInput.checked,
    sessionGuardMinutes: Number(els.sessionGuardSelect.value),
    staleGridCancel: els.staleGridCancelInput.checked
  });
  if (nextRules.chartInterval === "1m" && !hasLivePlan()) {
    els.rulesStatus.textContent = "Pro required for 1m";
    els.chartIntervalSelect.value = tradingRules.chartInterval;
    return;
  }
  if (!currentUser.authenticated) {
    applyTradingRules(nextRules);
    fibAnalysis = null;
    contextRadar = null;
    loadFibonacciAnalysis({ force: true });
    loadContextRadar({ force: true });
    return;
  }
  const response = await jsonPost("/api/trading-rules", nextRules);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    els.rulesStatus.textContent = payload.error || "rules not saved";
    return;
  }
  applyTradingRules(payload.tradingRules);
  fibAnalysis = null;
  contextRadar = null;
  loadFibonacciAnalysis({ force: true });
  loadContextRadar({ force: true });
  refreshBackend();
}

function render() {
  const candle = state.candles[Math.max(0, Math.min(state.activeIndex, state.candles.length - 1))];
  const mark = candle.close;
  els.candleCount.textContent = `${state.activeIndex}/${state.candles.length} candles`;
  els.equityMetric.textContent = money(equity(mark));
  els.feesMetric.textContent = money(state.feePaid);
  els.fillCount.textContent = `${state.fills.length} fills`;
  els.harvestMetric.textContent = money(state.realizedHarvest);
  els.inventoryMetric.textContent = `${(inventoryRatio(mark) * 100).toFixed(2)}%`;
  els.drawdownMetric.textContent = "$0.00 (0.00%)";
  els.openNotionalMetric.textContent = money(state.openOrders.reduce((sum, order) => sum + order.price * order.quantity, 0));
  els.riskBudgetMetric.textContent = "local";
  els.executionModeMetric.textContent = backendOnline ? els.executionModeMetric.textContent : "local";
  els.orderAgeMetric.textContent = "0s";
  els.syncMetric.textContent = "local";
  els.exchangeOrderMetric.textContent = "local";
  renderOpenOrders(state.openOrders, {
    emptyHint: "Run a sample or connect the backend",
    emptyText: "No preview levels",
    source: "preview",
    title: "Strategy Preview"
  });
  const live = markets.find((asset) => asset.symbol === selectedAsset);
  els.markPrice.textContent = live ? money(live.price) : money(mark);
  els.marketTitle.textContent = `${selectedAsset}-USD strategy map`;
  els.liquiditySource.textContent = "Strategy preview only. No exchange orders.";
  els.runState.textContent = state.activeIndex >= state.candles.length ? "Complete" : "Ready";
  renderTape();
  drawLiquidity({
    mark: live ? Number(live.price) : mark,
    orders: state.openOrders,
    sourceLabel: "Strategy preview only. No exchange orders.",
    sourceType: "preview"
  });
  drawEquity();
  if (!backendOnline) {
    els.runtimeLog.innerHTML = "<article>Serve with the live backend to control paper/live loops.</article>";
    els.riskStatus.textContent = "local";
    updateLiveDesk();
  }
}

function reset() {
  els.csvInput.value = sampleCsv;
  els.spacingValue.textContent = els.spacingInput.value;
  els.levelsValue.textContent = els.levelsInput.value;
  state = createState(configFromInputs());
  planOrders(state.candles[0].open);
  render();
}

function rebuildFromInputs() {
  els.spacingValue.textContent = els.spacingInput.value;
  els.levelsValue.textContent = els.levelsInput.value;
  state = createState(configFromInputs());
  planOrders(state.candles[0].open);
  render();
}

els.runButton.addEventListener("click", () => {
  state = createState(configFromInputs());
  runAll();
  render();
});

els.stepButton.addEventListener("click", () => {
  if (state.activeIndex >= state.candles.length) {
    state = createState(configFromInputs());
  }
  stepSimulation();
  render();
});

els.resetButton.addEventListener("click", reset);
els.assetSelect.addEventListener("change", () => saveSelectedAsset(els.assetSelect.value));
els.marketStrip.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-symbol]");
  if (button) saveSelectedAsset(button.dataset.symbol);
});
els.marketRadar.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-symbol]");
  if (button) saveSelectedAsset(button.dataset.symbol);
});
els.assetGroups.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-symbol]");
  if (button) saveSelectedAsset(button.dataset.symbol);
});
els.loginButton.addEventListener("click", () => loginOrRegister("/api/login"));
els.registerButton.addEventListener("click", () => loginOrRegister("/api/register"));
els.logoutButton.addEventListener("click", async () => {
  await jsonPost("/api/logout");
  renderAuth({ authenticated: false, credentialsConfigured: false });
});
els.saveCredentialsButton.addEventListener("click", saveCredentials);
els.saveRulesButton.addEventListener("click", saveTradingRules);
[els.chartIntervalSelect, els.sessionGuardSelect, els.staleGridCancelInput, els.londonCommodityInput].forEach((input) => {
  input.addEventListener("change", () => {
    const nextRules = normalizedTradingRules({
      chartInterval: els.chartIntervalSelect.value,
      londonCommodityOnly: els.londonCommodityInput.checked,
      sessionGuardMinutes: Number(els.sessionGuardSelect.value),
      staleGridCancel: els.staleGridCancelInput.checked
    });
    if (nextRules.chartInterval === "1m" && !hasLivePlan()) {
      els.rulesStatus.textContent = "Pro required for 1m";
      els.chartIntervalSelect.value = tradingRules.chartInterval;
      return;
    }
    applyTradingRules(nextRules);
  });
});
els.freePlanButton.addEventListener("click", () => checkoutPlan("free"));
els.proPlanButton.addEventListener("click", () => checkoutPlan("pro"));
els.backendStartButton.addEventListener("click", () => backendCommand("/api/start").catch(refreshBackend));
els.backendStopButton.addEventListener("click", () => backendCommand("/api/stop").catch(refreshBackend));
["input", "change"].forEach((eventName) => {
  [els.spacingInput, els.levelsInput].forEach((input) => {
    input.addEventListener(eventName, rebuildFromInputs);
  });
});

[els.symbolInput, els.quoteInput, els.baseInput, els.orderSizeInput, els.feeInput, els.csvInput].forEach((input) => {
  input.addEventListener("change", rebuildFromInputs);
});

window.addEventListener("resize", render);
window.addEventListener("resize", resizeMarketMap);
reset();
initMarketMap();
loadMarkets();
loadPaymentConfig();
loadMe();
refreshBackend();
renderForexSessions();
setInterval(loadMarkets, 5000);
setInterval(refreshBackend, 2500);
setInterval(renderForexSessions, 1000);
