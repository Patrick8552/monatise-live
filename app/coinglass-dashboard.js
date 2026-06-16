const CG_BASE = "https://open-api-v4.coinglass.com";
const BINANCE_BASE = "https://api.binance.com";
const HYPER_BASE = "https://api.hyperliquid.xyz/info";
const ALT_FG = "https://api.alternative.me/fng/?limit=30&format=json";
const SESSION_KEY = "btc-coinglass-dashboard-session";
const API_KEY_STORAGE = "btc-coinglass-api-key";
const ASSETS = {
  BTC: { coin: "BTC", pair: "BTCUSDT", hyper: "BTC" },
  ETH: { coin: "ETH", pair: "ETHUSDT", hyper: "ETH" },
  SOL: { coin: "SOL", pair: "SOLUSDT", hyper: "SOL" },
  XRP: { coin: "XRP", pair: "XRPUSDT", hyper: "XRP" },
  DOGE: { coin: "DOGE", pair: "DOGEUSDT", hyper: "DOGE" },
  BNB: { coin: "BNB", pair: "BNBUSDT", hyper: "BNB" }
};

const els = {
  apiKeyInput: document.querySelector("#apiKeyInput"),
  assetSelect: document.querySelector("#assetSelect"),
  exchangeSelect: document.querySelector("#exchangeSelect"),
  intervalSelect: document.querySelector("#intervalSelect"),
  liqRangeSelect: document.querySelector("#liqRangeSelect"),
  refreshButton: document.querySelector("#refreshButton"),
  clearSessionButton: document.querySelector("#clearSessionButton"),
  sessionStatusDot: document.querySelector("#sessionStatusDot"),
  sessionStatusText: document.querySelector("#sessionStatusText"),
  sessionUpdated: document.querySelector("#sessionUpdated"),
  dashboardTitle: document.querySelector("#dashboardTitle"),
  marketSymbol: document.querySelector("#marketSymbol"),
  assetPrice: document.querySelector("#assetPrice"),
  priceChange: document.querySelector("#priceChange"),
  fundingAverage: document.querySelector("#fundingAverage"),
  openInterest: document.querySelector("#openInterest"),
  fearGreed: document.querySelector("#fearGreed"),
  liqBias: document.querySelector("#liqBias"),
  vwapMetric: document.querySelector("#vwapMetric"),
  priceSource: document.querySelector("#priceSource"),
  fundingSource: document.querySelector("#fundingSource"),
  oiSource: document.querySelector("#oiSource"),
  liqSource: document.querySelector("#liqSource"),
  fgSource: document.querySelector("#fgSource"),
  newsSource: document.querySelector("#newsSource"),
  hyperSource: document.querySelector("#hyperSource"),
  frameworkSource: document.querySelector("#frameworkSource"),
  pricePulse: document.querySelector("#pricePulse"),
  maxPain: document.querySelector("#maxPain"),
  setupConfidence: document.querySelector("#setupConfidence"),
  setupAsset: document.querySelector("#setupAsset"),
  setupDirection: document.querySelector("#setupDirection"),
  setupReason: document.querySelector("#setupReason"),
  gridDirection: document.querySelector("#gridDirection"),
  gridPlan: document.querySelector("#gridPlan"),
  hedgeDirection: document.querySelector("#hedgeDirection"),
  hedgePlan: document.querySelector("#hedgePlan"),
  frameworkChecks: document.querySelector("#frameworkChecks"),
  frameworkBias: document.querySelector("#frameworkBias"),
  researchSource: document.querySelector("#researchSource"),
  researchPattern: document.querySelector("#researchPattern"),
  historySignal: document.querySelector("#historySignal"),
  historyStats: document.querySelector("#historyStats"),
  vwapSignal: document.querySelector("#vwapSignal"),
  vwapDetail: document.querySelector("#vwapDetail"),
  scaleAction: document.querySelector("#scaleAction"),
  scalePlan: document.querySelector("#scalePlan"),
  patternMemory: document.querySelector("#patternMemory"),
  patternDetail: document.querySelector("#patternDetail"),
  pricePanelTitle: document.querySelector("#pricePanelTitle"),
  priceCanvas: document.querySelector("#priceCanvas"),
  liqCanvas: document.querySelector("#liqCanvas"),
  fundingList: document.querySelector("#fundingList"),
  oiList: document.querySelector("#oiList"),
  hyperList: document.querySelector("#hyperList"),
  newsList: document.querySelector("#newsList"),
  telemetryList: document.querySelector("#telemetryList"),
  fgGauge: document.querySelector("#fgGauge"),
  fgLabel: document.querySelector("#fgLabel")
};

const state = {
  telemetry: readSession(),
  apiKey: localStorage.getItem(API_KEY_STORAGE) || "",
  priceSeries: [],
  lastPrice: null,
  market: {
    priceChange: 0,
    fundingAverage: null,
    oiChange: null,
    liquidationBias: null,
    fearGreed: null,
    hyperFunding: null,
    hyperOpenInterest: null,
    hyperPrice: null,
    researchSignal: null,
    researchScore: 0,
    vwap: null,
    vwapDistance: null,
    vwapScore: 0,
    vwapSignal: null,
    scaleAction: "wait",
    pattern: null
  }
};

els.apiKeyInput.value = state.apiKey;

function readSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveSession() {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(state.telemetry.slice(-60)));
}

function formatUsd(value, compact = false) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "$--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: compact || Math.abs(number) >= 1000 ? 0 : 2,
    notation: compact ? "compact" : "standard"
  }).format(number);
}

function formatPercent(value, digits = 3) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}%`;
}

function setSessionStatus(kind, text) {
  els.sessionStatusDot.className = `status-dot ${kind === "good" ? "good" : kind === "bad" ? "bad" : ""}`;
  els.sessionStatusText.textContent = text;
  els.sessionUpdated.textContent = new Date().toLocaleTimeString();
}

function recordTelemetry(name, source, ok, ms, detail = "") {
  state.telemetry.unshift({
    name,
    source,
    ok,
    ms,
    detail,
    time: new Date().toLocaleTimeString()
  });
  state.telemetry = state.telemetry.slice(0, 60);
  saveSession();
  renderTelemetry();
}

function renderTelemetry() {
  if (!state.telemetry.length) {
    els.telemetryList.innerHTML = `<div class="telemetry-row"><span>No requests yet</span><small>Start refresh</small><small>--</small></div>`;
    return;
  }
  els.telemetryList.innerHTML = state.telemetry.slice(0, 12).map((item) => {
    const tone = item.ok ? "positive" : "negative";
    return `
      <div class="telemetry-row">
        <span>${item.name}</span>
        <small>${item.source}${item.detail ? ` · ${item.detail}` : ""}</small>
        <strong class="${tone}">${item.ok ? "ok" : "fail"} · ${item.ms}ms · ${item.time}</strong>
      </div>
    `;
  }).join("");
}

async function timedFetch(name, source, url, options = {}) {
  const started = performance.now();
  try {
    const response = await fetch(url, options);
    const ms = Math.round(performance.now() - started);
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    const data = await response.json();
    recordTelemetry(name, source, true, ms);
    return data;
  } catch (error) {
    const ms = Math.round(performance.now() - started);
    recordTelemetry(name, source, false, ms, error.message);
    throw error;
  }
}

function cgHeaders() {
  return {
    accept: "application/json",
    "CG-API-KEY": state.apiKey
  };
}

function hasKey() {
  return state.apiKey.trim().length > 0;
}

function selectedAsset() {
  return ASSETS[els.assetSelect.value] || ASSETS.BTC;
}

function selectedCoin() {
  return selectedAsset().coin;
}

function selectedPair() {
  return selectedAsset().pair;
}

function syncAssetLabels() {
  const asset = selectedAsset();
  els.dashboardTitle.textContent = `${asset.coin} Trading Dashboard`;
  els.marketSymbol.textContent = asset.pair;
  els.pricePanelTitle.textContent = `${asset.coin} Price Reflection`;
  els.setupAsset.textContent = `${asset.coin} setup`;
}

function resetMarketContext() {
  state.market = {
    priceChange: 0,
    fundingAverage: null,
    oiChange: null,
    liquidationBias: null,
    fearGreed: null,
    hyperFunding: null,
    hyperOpenInterest: null,
    hyperPrice: null,
    researchSignal: null,
    researchScore: 0,
    vwap: null,
    vwapDistance: null,
    vwapScore: 0,
    vwapSignal: null,
    scaleAction: "wait",
    pattern: null
  };
}

async function getPrice() {
  const asset = selectedAsset();
  const exchange = els.exchangeSelect.value;
  const interval = els.intervalSelect.value;
  if (hasKey()) {
    const params = new URLSearchParams({
      exchange,
      symbol: asset.pair,
      interval,
      limit: "96"
    });
    const payload = await timedFetch(
      `${asset.coin} price`,
      "Coinglass",
      `${CG_BASE}/api/futures/price/history?${params}`,
      { headers: cgHeaders() }
    );
    const rows = Array.isArray(payload.data) ? payload.data : [];
    if (rows.length) {
      els.priceSource.textContent = `Coinglass futures price history · ${asset.pair} · ${exchange} · ${interval}`;
      return rows.map((row) => ({
        time: Number(row.time),
        close: Number(row.close),
        high: Number(row.high),
        low: Number(row.low),
        volume: Number(row.volume_usd)
      })).filter((row) => Number.isFinite(row.close));
    }
  }
  const binanceInterval = interval === "30m" ? "30m" : interval === "4h" ? "4h" : interval === "1d" ? "1d" : interval === "15m" ? "15m" : "1h";
  const payload = await timedFetch(
    `${asset.coin} price fallback`,
    "Binance public",
    `${BINANCE_BASE}/api/v3/klines?symbol=${asset.pair}&interval=${binanceInterval}&limit=96`
  );
  els.priceSource.textContent = "Binance public fallback · add CoinGlass key for primary route";
  return payload.map((row) => ({
    time: Number(row[0]),
    close: Number(row[4]),
    high: Number(row[2]),
    low: Number(row[3]),
    volume: Number(row[7])
  }));
}

async function getFunding() {
  const asset = selectedAsset();
  if (!hasKey()) throw new Error("CoinGlass API key required");
  const payload = await timedFetch(
    "Funding rate",
    "Coinglass",
    `${CG_BASE}/api/futures/funding-rate/exchange-list`,
    { headers: cgHeaders() }
  );
  const coin = (payload.data || []).find((item) => item.symbol === asset.coin);
  const stable = coin?.stablecoin_margin_list || [];
  return stable.slice().sort((a, b) => Math.abs(b.funding_rate) - Math.abs(a.funding_rate)).slice(0, 8);
}

async function getOpenInterest() {
  const asset = selectedAsset();
  if (!hasKey()) throw new Error("CoinGlass API key required");
  const payload = await timedFetch(
    "Open interest",
    "Coinglass",
    `${CG_BASE}/api/futures/open-interest/exchange-list?symbol=${asset.coin}`,
    { headers: cgHeaders() }
  );
  return (payload.data || []).slice(0, 8);
}

async function getLiquidations() {
  const asset = selectedAsset();
  if (!hasKey()) throw new Error("CoinGlass API key required");
  const range = els.liqRangeSelect.value;
  const mapPromise = timedFetch(
    "Liquidation map",
    "Coinglass",
    `${CG_BASE}/api/futures/liquidation/aggregated-map?symbol=${asset.coin}&range=${range}`,
    { headers: cgHeaders() }
  );
  const painPromise = timedFetch(
    "Liquidation max pain",
    "Coinglass",
    `${CG_BASE}/api/futures/liquidation/max-pain?range=24h`,
    { headers: cgHeaders() }
  );
  const [mapPayload, painPayload] = await Promise.allSettled([mapPromise, painPromise]);
  const levels = mapPayload.status === "fulfilled" ? parseLiquidationMap(mapPayload.value) : [];
  const assetPain = painPayload.status === "fulfilled"
    ? (painPayload.value.data || []).find((item) => item.symbol === asset.coin)
    : null;
  return { levels, assetPain };
}

async function getFearGreed() {
  if (hasKey()) {
    const payload = await timedFetch(
      "Fear and greed",
      "Coinglass",
      `${CG_BASE}/api/index/fear-greed-history`,
      { headers: cgHeaders() }
    );
    const first = Array.isArray(payload.data) ? payload.data[0] : null;
    const values = first?.data_list || [];
    const times = first?.time_list || [];
    if (values.length) {
      els.fgSource.textContent = "Coinglass crypto fear and greed history";
      return values.map((value, index) => ({ value: Number(value), time: Number(times[index]) * 1000 })).filter((row) => Number.isFinite(row.value));
    }
  }
  const fallback = await timedFetch("Fear and greed fallback", "Alternative.me public", ALT_FG);
  els.fgSource.textContent = "Alternative.me fallback · add CoinGlass key for primary route";
  return (fallback.data || []).reverse().map((row) => ({
    value: Number(row.value),
    time: Number(row.timestamp) * 1000,
    label: row.value_classification
  }));
}

async function getNews() {
  if (!hasKey()) throw new Error("CoinGlass API key required");
  const end = Date.now();
  const start = end - 1000 * 60 * 60 * 24 * 3;
  const params = new URLSearchParams({
    start_time: String(start),
    end_time: String(end),
    language: "en",
    page: "1",
    per_page: "8"
  });
  const payload = await timedFetch("News alerts", "Coinglass", `${CG_BASE}/api/article/list?${params}`, { headers: cgHeaders() });
  return (payload.data || []).slice(0, 8);
}

async function getHyperliquidContext() {
  const asset = selectedAsset();
  const payload = await timedFetch(
    `${asset.coin} Hyperliquid`,
    "Hyperliquid public",
    HYPER_BASE,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "metaAndAssetCtxs" })
    }
  );
  const universe = payload?.[0]?.universe || [];
  const contexts = payload?.[1] || [];
  const index = universe.findIndex((item) => item.name === asset.hyper);
  if (index < 0 || !contexts[index]) {
    throw new Error(`${asset.hyper} not listed on Hyperliquid`);
  }
  const ctx = contexts[index];
  return {
    coin: asset.coin,
    markPrice: Number(ctx.markPx),
    oraclePrice: Number(ctx.oraclePx),
    funding: Number(ctx.funding) * 100,
    openInterest: Number(ctx.openInterest),
    premium: Number(ctx.premium),
    dayVolume: Number(ctx.dayNtlVlm),
    prevDayPrice: Number(ctx.prevDayPx)
  };
}

function parseLiquidationMap(payload) {
  const raw = payload?.data?.data || payload?.data || {};
  const entries = [];
  Object.values(raw).forEach((bucket) => {
    if (!Array.isArray(bucket)) return;
    bucket.forEach((row) => {
      const price = Number(row?.[0]);
      const level = Number(row?.[1]);
      if (Number.isFinite(price) && Number.isFinite(level)) {
        entries.push({ price, level });
      }
    });
  });
  return entries.sort((a, b) => a.price - b.price);
}

function syntheticLiquidations(price) {
  const anchors = [-0.085, -0.055, -0.032, -0.018, 0.016, 0.029, 0.052, 0.081];
  return anchors.map((offset, index) => ({
    price: price * (1 + offset),
    level: (index % 2 ? 54 : 36) * 1_000_000 * (1 + Math.abs(offset) * 8)
  }));
}

function renderPrice(series) {
  const asset = selectedAsset();
  state.priceSeries = series;
  const last = series.at(-1);
  const previous = series.at(-2);
  if (!last) return;
  state.lastPrice = last.close;
  const change = previous ? ((last.close - previous.close) / previous.close) * 100 : 0;
  state.market.priceChange = change;
  els.assetPrice.textContent = formatUsd(last.close);
  els.priceChange.textContent = `${change >= 0 ? "Up" : "Down"} ${formatPercent(change, 2)} last candle`;
  els.priceChange.className = change >= 0 ? "positive" : "negative";
  els.pricePulse.textContent = "live";
  drawLineChart(els.priceCanvas, series.map((row) => row.close), {
    color: change >= 0 ? "#5ae68f" : "#ff6b7f",
    fill: "rgba(82, 214, 255, 0.10)",
    labels: series.map((row) => new Date(row.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))
  });
  renderResearch(studyHistoricalPattern(series));
}

function studyHistoricalPattern(series) {
  const closes = series.map((row) => row.close).filter(Number.isFinite);
  const highs = series.map((row) => row.high).filter(Number.isFinite);
  const lows = series.map((row) => row.low).filter(Number.isFinite);
  if (closes.length < 20) {
    return {
      signal: "Insufficient history",
      pattern: "thin sample",
      score: 0,
      action: "wait",
      stats: "Need at least 20 candles.",
      plan: "Wait for more history before averaging.",
      memory: "--",
      detail: "CoinGlass historical study needs a larger sample."
    };
  }

  const last = closes.at(-1);
  const maFast = average(closes.slice(-12));
  const maSlow = average(closes.slice(-48));
  const recentHigh = Math.max(...highs.slice(-48));
  const recentLow = Math.min(...lows.slice(-48));
  const range = Math.max(recentHigh - recentLow, last * 0.001);
  const rangePosition = (last - recentLow) / range;
  const vwap = calculateVWAP(series.slice(-96));
  const recentVwap = calculateVWAP(series.slice(-24));
  const vwapDistance = ((last - vwap) / vwap) * 100;
  const vwapSlope = ((recentVwap - vwap) / vwap) * 100;
  const vwapScore = vwapDistance > 0.15 && vwapSlope >= -0.05 ? 1 : vwapDistance < -0.15 && vwapSlope <= 0.05 ? -1 : 0;
  const drawdown = ((last - recentHigh) / recentHigh) * 100;
  const bounceRate = studyBounceRate(closes, lows, 20);
  const volatility = averageTrueRangePercent(series.slice(-24));
  const momentum = ((last - closes.at(-12)) / closes.at(-12)) * 100;
  const trendScore = maFast > maSlow ? 1 : -1;
  const supportScore = rangePosition < 0.34 && bounceRate >= 45 ? 1 : 0;
  const extensionScore = rangePosition > 0.72 && drawdown > -1.5 ? -1 : 0;
  const exhaustionScore = Math.abs(momentum) > volatility * 2.2 ? (momentum > 0 ? -1 : 1) : 0;
  const score = trendScore + supportScore + extensionScore + exhaustionScore + vwapScore;

  let action = "wait";
  let signal = "Range study";
  let plan = "Keep size small until pattern memory aligns with funding and liquidation checks.";
  if (score >= 2 && rangePosition < 0.55 && vwapDistance <= 1.2) {
    action = "average down";
    signal = "Support accumulation";
    plan = "Average down in smaller bids near support and VWAP; stop adding if price accepts below VWAP with expanding OI.";
  } else if (score >= 1 && maFast > maSlow && rangePosition >= 0.45) {
    action = "average up";
    signal = "Trend continuation";
    plan = "Average up only after pullbacks hold above fast history and VWAP; do not chase candles stretched far above VWAP.";
  } else if (score <= -2) {
    action = "scale out";
    signal = "Extension risk";
    plan = "Reduce grid exposure into strength and wait for a cleaner pullback before adding.";
  }

  return {
    signal,
    pattern: maFast > maSlow ? "up-history" : "down-history",
    score,
    vwap,
    vwapDistance,
    vwapSlope,
    vwapSignal: vwapScore > 0 ? "above VWAP" : vwapScore < 0 ? "below VWAP" : "near VWAP",
    vwapScore,
    action,
    stats: `MA12 ${formatUsd(maFast)} · MA48 ${formatUsd(maSlow)} · VWAP ${formatUsd(vwap)} · ATR ${volatility.toFixed(2)}%`,
    plan,
    memory: `${Math.round(bounceRate)}% bounce memory`,
    detail: `48-candle position ${Math.round(rangePosition * 100)}% · drawdown ${formatPercent(drawdown, 2)} · momentum ${formatPercent(momentum, 2)}`
  };
}

function renderResearch(research) {
  const asset = selectedAsset();
  state.market.researchSignal = research.signal;
  state.market.researchScore = research.score;
  state.market.vwap = research.vwap;
  state.market.vwapDistance = research.vwapDistance;
  state.market.vwapScore = research.vwapScore;
  state.market.vwapSignal = research.vwapSignal;
  state.market.scaleAction = research.action;
  state.market.pattern = research.pattern;
  els.vwapMetric.textContent = `${research.vwapSignal} ${formatPercent(research.vwapDistance, 2)}`;
  els.vwapMetric.className = research.vwapScore > 0 ? "positive" : research.vwapScore < 0 ? "negative" : "";
  els.researchSource.textContent = `CoinGlass history study · ${asset.coin} · ${els.intervalSelect.value} candles`;
  els.researchPattern.textContent = research.pattern;
  els.historySignal.textContent = research.signal;
  els.historyStats.textContent = research.stats;
  els.vwapSignal.textContent = research.vwapSignal;
  els.vwapSignal.className = research.vwapScore > 0 ? "positive" : research.vwapScore < 0 ? "negative" : "";
  els.vwapDetail.textContent = `VWAP ${formatUsd(research.vwap)} · distance ${formatPercent(research.vwapDistance, 2)} · slope ${formatPercent(research.vwapSlope, 2)}`;
  els.scaleAction.textContent = research.action;
  els.scaleAction.className = research.action === "average down" || research.action === "average up" ? "positive" : research.action === "scale out" ? "negative" : "";
  els.scalePlan.textContent = research.plan;
  els.patternMemory.textContent = research.memory;
  els.patternDetail.textContent = research.detail;
}

function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function calculateVWAP(rows) {
  let weightedPrice = 0;
  let totalWeight = 0;
  rows.forEach((row) => {
    const typicalPrice = average([row.high, row.low, row.close].filter(Number.isFinite));
    const weight = Number.isFinite(row.volume) && row.volume > 0 ? row.volume : 1;
    if (Number.isFinite(typicalPrice)) {
      weightedPrice += typicalPrice * weight;
      totalWeight += weight;
    }
  });
  return totalWeight ? weightedPrice / totalWeight : rows.at(-1)?.close || 0;
}

function studyBounceRate(closes, lows, lookback) {
  let tests = 0;
  let bounces = 0;
  for (let i = lookback; i < closes.length - 3; i += 1) {
    const support = Math.min(...lows.slice(i - lookback, i));
    const touchedSupport = lows[i] <= support * 1.006;
    if (touchedSupport) {
      tests += 1;
      const futureHigh = Math.max(...closes.slice(i + 1, i + 4));
      if (futureHigh >= closes[i] * 1.008) bounces += 1;
    }
  }
  return tests ? (bounces / tests) * 100 : 0;
}

function averageTrueRangePercent(rows) {
  if (rows.length < 2) return 0;
  const ranges = rows.slice(1).map((row, index) => {
    const previousClose = rows[index].close;
    const trueRange = Math.max(row.high - row.low, Math.abs(row.high - previousClose), Math.abs(row.low - previousClose));
    return (trueRange / row.close) * 100;
  });
  return average(ranges);
}

function renderFunding(rows) {
  const asset = selectedAsset();
  if (!rows.length) throw new Error("No funding rows");
  const average = rows.reduce((sum, row) => sum + Number(row.funding_rate || 0), 0) / rows.length;
  state.market.fundingAverage = average;
  els.fundingAverage.textContent = formatPercent(average, 4);
  els.fundingAverage.className = average >= 0 ? "positive" : "negative";
  els.fundingSource.textContent = `Coinglass ${asset.coin} futures funding rate · stablecoin margin`;
  els.fundingList.innerHTML = rows.map((row) => {
    const rate = Number(row.funding_rate);
    return `
      <div class="metric-row">
        <div>
          <strong>${row.exchange}</strong><br />
          <small>${row.funding_rate_interval || 8}h interval · next ${formatTime(row.next_funding_time)}</small>
        </div>
        <span class="metric-value ${rate >= 0 ? "positive" : "negative"}">${formatPercent(rate, 4)}</span>
      </div>
    `;
  }).join("");
}

function renderFundingLocked(error) {
  state.market.fundingAverage = null;
  els.fundingAverage.textContent = "key needed";
  els.fundingAverage.className = "";
  els.fundingSource.textContent = "CoinGlass API key required for live funding";
  els.fundingList.innerHTML = lockedRows("Funding rate", error.message, [
    "Primary endpoint: /api/futures/funding-rate/exchange-list",
    "Updates every 20 seconds on CoinGlass plans"
  ]);
}

function renderOpenInterest(rows) {
  const asset = selectedAsset();
  if (!rows.length) throw new Error("No open interest rows");
  const all = rows.find((row) => row.exchange === "All") || rows[0];
  state.market.oiChange = Number(all.open_interest_change_percent_24h);
  els.openInterest.textContent = formatUsd(all.open_interest_usd, true);
  els.oiSource.textContent = `Coinglass futures open interest · ${asset.coin}`;
  els.oiList.innerHTML = rows.map((row) => {
    const change = Number(row.open_interest_change_percent_24h);
    return `
      <div class="metric-row">
        <div>
          <strong>${row.exchange}</strong><br />
          <small>${formatUsd(row.open_interest_usd, true)} · ${Number(row.open_interest_quantity || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} ${asset.coin}</small>
        </div>
        <span class="metric-value ${change >= 0 ? "positive" : "negative"}">${formatPercent(change, 2)} 24h</span>
      </div>
    `;
  }).join("");
}

function renderOpenInterestLocked(error) {
  state.market.oiChange = null;
  els.openInterest.textContent = "key needed";
  els.oiSource.textContent = "CoinGlass API key required for live open interest";
  els.oiList.innerHTML = lockedRows("Open interest", error.message, [
    `Primary endpoint: /api/futures/open-interest/exchange-list?symbol=${selectedCoin()}`,
    "Includes all-exchange aggregation and exchange rows"
  ]);
}

function renderLiquidations(result) {
  const asset = selectedAsset();
  const current = state.lastPrice || 100000;
  const levels = result.levels.length ? result.levels : syntheticLiquidations(current);
  const below = levels.filter((row) => row.price < current).reduce((sum, row) => sum + row.level, 0);
  const above = levels.filter((row) => row.price >= current).reduce((sum, row) => sum + row.level, 0);
  const bias = above > below ? "short squeeze" : "long flush";
  state.market.liquidationBias = bias;
  els.liqBias.textContent = bias;
  els.liqBias.className = above > below ? "positive" : "negative";
  els.liqSource.textContent = result.levels.length
    ? "Coinglass aggregated liquidation map"
    : "Synthetic map fallback · CoinGlass plan/key needed";
  if (result.assetPain) {
    els.maxPain.textContent = `max pain ${formatUsd(result.assetPain.short_max_pain_liq_price)} / ${formatUsd(result.assetPain.long_max_pain_liq_price)}`;
  } else {
    els.maxPain.textContent = "max pain gated";
  }
  drawLiquidationMap(els.liqCanvas, levels, current);
}

function renderLiquidationsLocked(error) {
  const asset = selectedAsset();
  const current = state.lastPrice || 100000;
  els.liqSource.textContent = "CoinGlass Professional or Enterprise may be required";
  els.maxPain.textContent = "max pain gated";
  els.liqBias.textContent = "simulated";
  els.liqBias.className = "";
  state.market.liquidationBias = "simulated";
  drawLiquidationMap(els.liqCanvas, syntheticLiquidations(current), current);
  recordTelemetry("Liquidation fallback", "Local model", true, 0, error.message);
}

function renderFearGreed(rows) {
  if (!rows.length) throw new Error("No fear and greed rows");
  const latest = rows.at(-1);
  const value = Math.max(0, Math.min(100, Number(latest.value)));
  state.market.fearGreed = value;
  const label = latest.label || classifyFearGreed(value);
  els.fearGreed.textContent = `${Math.round(value)} ${label}`;
  els.fgGauge.style.background = `
    radial-gradient(circle at center, #111923 0 54%, transparent 55%),
    conic-gradient(${gaugeColor(value)} 0 ${value * 3.6}deg, #273342 ${value * 3.6}deg 360deg)
  `;
  els.fgGauge.querySelector("span").textContent = Math.round(value);
  els.fgLabel.textContent = `${label} · last update ${new Date(latest.time).toLocaleDateString()}`;
}

function renderNews(rows) {
  if (!rows.length) throw new Error("No news rows");
  els.newsSource.textContent = "Coinglass instant news alerts";
  els.newsList.innerHTML = rows.map((row) => `
    <div class="news-item">
      <strong>${stripHtml(row.article_title || "Market alert")}</strong>
      <small>${row.source_name || "Coinglass"} · ${formatTime(row.article_release_time)}</small>
      <p>${stripHtml(row.article_description || "").slice(0, 160)}</p>
    </div>
  `).join("");
}

function renderNewsLocked(error) {
  els.newsSource.textContent = "CoinGlass Startup or higher key required for news";
  els.newsList.innerHTML = lockedRows("News alerts", error.message, [
    "Primary endpoint: /api/article/list",
    "Use the API key field to unlock live alerts"
  ]);
}

function renderHyperliquid(ctx) {
  state.market.hyperFunding = ctx.funding;
  state.market.hyperOpenInterest = ctx.openInterest;
  state.market.hyperPrice = ctx.markPrice;
  els.hyperSource.textContent = `Hyperliquid public context · ${ctx.coin}-PERP`;
  els.hyperList.innerHTML = [
    ["Mark price", formatUsd(ctx.markPrice), "Oracle " + formatUsd(ctx.oraclePrice)],
    ["Funding", formatPercent(ctx.funding, 4), "Premium " + formatPercent(ctx.premium * 100, 4)],
    ["Open interest", `${ctx.openInterest.toLocaleString(undefined, { maximumFractionDigits: 0 })} ${ctx.coin}`, "Perp contracts"],
    ["24h volume", formatUsd(ctx.dayVolume, true), "Notional"]
  ].map(([label, value, detail]) => `
    <div class="metric-row">
      <div>
        <strong>${label}</strong><br />
        <small>${detail}</small>
      </div>
      <span class="metric-value">${value}</span>
    </div>
  `).join("");
}

function renderHyperliquidLocked(error) {
  state.market.hyperFunding = null;
  state.market.hyperOpenInterest = null;
  state.market.hyperPrice = null;
  els.hyperSource.textContent = "Hyperliquid public context unavailable";
  els.hyperList.innerHTML = lockedRows("Hyperliquid", error.message, [
    "Primary route: POST /info type=metaAndAssetCtxs",
    "Confirms mark price, funding, premium, OI, and volume"
  ]);
}

function applyMonatiseFramework() {
  const asset = selectedAsset();
  const m = state.market;
  const checks = [];

  addCheck(checks, "Price trend", m.priceChange, m.priceChange > 0.15 ? 1 : m.priceChange < -0.15 ? -1 : 0, `${formatPercent(m.priceChange || 0, 2)} last candle`);
  addCheck(checks, "Funding", m.fundingAverage, m.fundingAverage > 0.015 ? -1 : m.fundingAverage < -0.015 ? 1 : 0, m.fundingAverage == null ? "waiting" : `${formatPercent(m.fundingAverage, 4)} average`);
  addCheck(checks, "Open interest", m.oiChange, m.oiChange > 0.5 ? 1 : m.oiChange < -0.5 ? -1 : 0, m.oiChange == null ? "waiting" : `${formatPercent(m.oiChange, 2)} 24h`);
  addCheck(checks, "Liquidations", m.liquidationBias, m.liquidationBias === "short squeeze" ? 1 : m.liquidationBias === "long flush" ? -1 : 0, m.liquidationBias || "waiting");
  addCheck(checks, "Hyperliquid funding", m.hyperFunding, m.hyperFunding > 0.015 ? -1 : m.hyperFunding < -0.015 ? 1 : 0, m.hyperFunding == null ? "waiting" : `${formatPercent(m.hyperFunding, 4)}`);
  addCheck(checks, "Fear/greed", m.fearGreed, m.fearGreed > 72 ? -1 : m.fearGreed < 28 ? 1 : 0, m.fearGreed == null ? "waiting" : `${Math.round(m.fearGreed)}`);
  addCheck(checks, "VWAP", m.vwapSignal, m.vwapScore, m.vwapSignal ? `${m.vwapSignal} · ${formatPercent(m.vwapDistance, 2)} from VWAP` : "waiting");
  addCheck(checks, "History research", m.researchSignal, m.researchScore > 0 ? 1 : m.researchScore < 0 ? -1 : 0, m.researchSignal ? `${m.researchSignal} · ${m.scaleAction}` : "waiting");

  const liveChecks = checks.filter((check) => check.live).length;
  const score = checks.reduce((sum, check) => sum + check.score, 0);
  const direction = score >= 2 ? "BUY SETUP" : score <= -2 ? "SELL SETUP" : "WAIT";
  const confidence = Math.min(100, Math.round((Math.abs(score) / 6) * 100 + liveChecks * 5));
  const risk = Math.abs(Number(m.fundingAverage || 0)) > 0.04 || Math.abs(Number(m.hyperFunding || 0)) > 0.04 || m.liquidationBias === "simulated";
  const hedgePct = risk ? 50 : Math.abs(score) >= 3 ? 25 : 0;

  els.frameworkSource.textContent = `${asset.coin} selected · Coinglass research + VWAP + derivatives checks + Hyperliquid confirmation`;
  els.setupDirection.textContent = direction;
  els.setupDirection.className = direction.includes("BUY") ? "positive" : direction.includes("SELL") ? "negative" : "";
  els.setupConfidence.textContent = `confidence ${confidence}%`;
  els.frameworkChecks.textContent = `${liveChecks} / ${checks.length}`;
  els.frameworkBias.textContent = `Score ${score >= 0 ? "+" : ""}${score} from ${checks.length} checks`;
  els.setupReason.textContent = checks.map((check) => `${check.name}: ${check.detail}`).join(" · ");

  if (direction === "BUY SETUP") {
    els.gridDirection.textContent = `Buy grid ${asset.coin}`;
    els.gridPlan.textContent = gridPlanForResearch("buy", m.scaleAction, m.vwapSignal);
    els.hedgeDirection.textContent = hedgePct ? `Short hedge ${hedgePct}%` : "No hedge";
    els.hedgePlan.textContent = hedgePct ? "Keep a partial short while funding/liquidation risk is elevated." : "Long setup is clean enough to run unhedged.";
  } else if (direction === "SELL SETUP") {
    els.gridDirection.textContent = `Sell grid ${asset.coin}`;
    els.gridPlan.textContent = gridPlanForResearch("sell", m.scaleAction, m.vwapSignal);
    els.hedgeDirection.textContent = hedgePct ? `Long hedge ${hedgePct}%` : "No hedge";
    els.hedgePlan.textContent = hedgePct ? "Keep a partial long while squeeze or crowded-short risk is elevated." : "Short setup is clean enough to run unhedged.";
  } else {
    els.gridDirection.textContent = `Neutral grid ${asset.coin}`;
    els.gridPlan.textContent = "Use small two-sided grid or wait until funding/OI/liquidation checks align.";
    els.hedgeDirection.textContent = "Flat hedge";
    els.hedgePlan.textContent = "Stay capital-light until the setup confirms.";
  }
}

function gridPlanForResearch(side, action, vwapSignal) {
  if (side === "buy" && action === "average down") {
    return "Average down with staggered bids near researched support; pause if support fails with expanding OI.";
  }
  if (side === "buy" && action === "average up") {
    return "Average up only after shallow pullbacks hold above VWAP and fast history; avoid chasing candles stretched far above VWAP.";
  }
  if (side === "sell" && action === "scale out") {
    return "Sell grid into VWAP extension, take partials faster, and avoid adding after downside exhaustion.";
  }
  if (side === "sell" && action === "average up") {
    return "Build offers above mark as price extends; hedge squeeze risk with smaller order spacing.";
  }
  if (side === "buy" && vwapSignal === "below VWAP") {
    return "Wait for VWAP reclaim before increasing buy grid size; keep bids smaller below VWAP.";
  }
  if (side === "sell" && vwapSignal === "above VWAP") {
    return "Wait for VWAP rejection before increasing sell grid size; keep offers smaller above VWAP.";
  }
  return side === "buy"
    ? "Build bids below mark, harvest mean reversion, avoid chasing above current price."
    : "Build offers above mark, fade strength, avoid adding into downside exhaustion.";
}

function addCheck(checks, name, raw, score, detail) {
  checks.push({
    name,
    score,
    detail,
    live: raw !== null && raw !== undefined && raw !== "simulated"
  });
}

function lockedRows(title, detail, lines) {
  return lines.map((line, index) => `
    <div class="metric-row">
      <div>
        <strong>${index === 0 ? title : "Route"}</strong><br />
        <small>${line}</small>
      </div>
      <span class="metric-value">${index === 0 ? "locked" : detail}</span>
    </div>
  `).join("");
}

function drawLineChart(canvas, values, options) {
  const ctx = prepareCanvas(canvas);
  const { width, height } = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);
  drawGrid(ctx, width, height);
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min || 1) * 0.12;
  const xFor = (index) => 42 + (index / (values.length - 1)) * (width - 64);
  const yFor = (value) => height - 34 - ((value - min + pad) / (max - min + pad * 2)) * (height - 64);

  ctx.beginPath();
  values.forEach((value, index) => {
    const x = xFor(index);
    const y = yFor(value);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(xFor(values.length - 1), height - 30);
  ctx.lineTo(xFor(0), height - 30);
  ctx.closePath();
  ctx.fillStyle = options.fill;
  ctx.fill();

  ctx.beginPath();
  values.forEach((value, index) => {
    const x = xFor(index);
    const y = yFor(value);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = options.color;
  ctx.lineWidth = 3;
  ctx.stroke();

  ctx.fillStyle = "#90a3b8";
  ctx.font = "12px system-ui";
  ctx.fillText(formatUsd(max), 12, 24);
  ctx.fillText(formatUsd(min), 12, height - 18);
}

function drawLiquidationMap(canvas, levels, current) {
  const ctx = prepareCanvas(canvas);
  const { width, height } = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);
  drawGrid(ctx, width, height);
  if (!levels.length) return;
  const prices = levels.map((row) => row.price).concat(current);
  const maxLevel = Math.max(...levels.map((row) => row.level), 1);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const xFor = (price) => 42 + ((price - minPrice) / (maxPrice - minPrice || 1)) * (width - 70);
  levels.forEach((row) => {
    const x = xFor(row.price);
    const barHeight = Math.max(10, (row.level / maxLevel) * (height - 70));
    ctx.fillStyle = row.price >= current ? "rgba(90, 230, 143, 0.72)" : "rgba(255, 107, 127, 0.72)";
    ctx.fillRect(x - 7, height - 32 - barHeight, 14, barHeight);
  });
  const currentX = xFor(current);
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(currentX, 18);
  ctx.lineTo(currentX, height - 24);
  ctx.stroke();
  ctx.fillStyle = "#eef4fb";
  ctx.font = "12px system-ui";
  ctx.fillText(`${selectedCoin()} ${formatUsd(current)}`, Math.min(currentX + 8, width - 120), 28);
  ctx.fillStyle = "#90a3b8";
  ctx.fillText(formatUsd(minPrice), 12, height - 12);
  ctx.fillText(formatUsd(maxPrice), width - 104, height - 12);
}

function prepareCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return ctx;
}

function drawGrid(ctx, width, height) {
  ctx.fillStyle = "#0e151e";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(144, 163, 184, 0.12)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
}

function classifyFearGreed(value) {
  if (value < 25) return "Extreme fear";
  if (value < 45) return "Fear";
  if (value < 55) return "Neutral";
  if (value < 75) return "Greed";
  return "Extreme greed";
}

function gaugeColor(value) {
  if (value < 25) return "#ff6b7f";
  if (value < 45) return "#ffbf47";
  if (value < 55) return "#52d6ff";
  if (value < 75) return "#5ae68f";
  return "#b592ff";
}

function formatTime(ms) {
  const value = Number(ms);
  if (!Number.isFinite(value) || value <= 0) return "--";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function stripHtml(input) {
  const template = document.createElement("template");
  template.innerHTML = input || "";
  return (template.content.textContent || "").replace(/\s+/g, " ").trim();
}

async function refreshDashboard() {
  syncAssetLabels();
  els.refreshButton.disabled = true;
  els.refreshButton.textContent = "Refreshing";
  setSessionStatus("warn", "Refreshing market session");
  try {
    const price = await getPrice();
    renderPrice(price);
  } catch (error) {
    els.priceSource.textContent = `Price unavailable · ${error.message}`;
    els.pricePulse.textContent = "offline";
  }

  const jobs = [
    getFunding().then(renderFunding).catch(renderFundingLocked),
    getOpenInterest().then(renderOpenInterest).catch(renderOpenInterestLocked),
    getLiquidations().then(renderLiquidations).catch(renderLiquidationsLocked),
    getFearGreed().then(renderFearGreed).catch((error) => {
      state.market.fearGreed = null;
      els.fgSource.textContent = `Fear and greed unavailable · ${error.message}`;
    }),
    getHyperliquidContext().then(renderHyperliquid).catch(renderHyperliquidLocked),
    getNews().then(renderNews).catch(renderNewsLocked)
  ];

  await Promise.allSettled(jobs);
  applyMonatiseFramework();
  const failures = state.telemetry.slice(0, 8).filter((item) => !item.ok).length;
  setSessionStatus(failures ? "bad" : "good", failures ? "Session degraded" : "Session live");
  els.refreshButton.disabled = false;
  els.refreshButton.textContent = "Refresh";
}

els.apiKeyInput.addEventListener("change", () => {
  state.apiKey = els.apiKeyInput.value.trim();
  localStorage.setItem(API_KEY_STORAGE, state.apiKey);
  refreshDashboard();
});

els.refreshButton.addEventListener("click", refreshDashboard);
els.assetSelect.addEventListener("change", () => {
  resetMarketContext();
  refreshDashboard();
});
els.exchangeSelect.addEventListener("change", refreshDashboard);
els.intervalSelect.addEventListener("change", refreshDashboard);
els.liqRangeSelect.addEventListener("change", refreshDashboard);
els.clearSessionButton.addEventListener("click", () => {
  state.telemetry = [];
  saveSession();
  renderTelemetry();
  setSessionStatus("warn", "Session cleared");
});

window.addEventListener("resize", () => {
  if (state.priceSeries.length) renderPrice(state.priceSeries);
  if (state.lastPrice) drawLiquidationMap(els.liqCanvas, syntheticLiquidations(state.lastPrice), state.lastPrice);
});

renderTelemetry();
refreshDashboard();
setInterval(refreshDashboard, 60_000);
