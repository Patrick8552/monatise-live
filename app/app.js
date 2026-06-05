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

const controlTokenKey = "monatiseControlToken";

const els = {
  baseInput: document.querySelector("#baseInput"),
  backendStartButton: document.querySelector("#backendStartButton"),
  backendStatus: document.querySelector("#backendStatus"),
  backendStopButton: document.querySelector("#backendStopButton"),
  accountMetricLabel: document.querySelector("#accountMetricLabel"),
  candleCount: document.querySelector("#candleCount"),
  cashMetricLabel: document.querySelector("#cashMetricLabel"),
  csvInput: document.querySelector("#csvInput"),
  equityCanvas: document.querySelector("#equityCanvas"),
  equityMetric: document.querySelector("#equityMetric"),
  feeInput: document.querySelector("#feeInput"),
  feesMetric: document.querySelector("#feesMetric"),
  fillCount: document.querySelector("#fillCount"),
  fillTape: document.querySelector("#fillTape"),
  harvestMetric: document.querySelector("#harvestMetric"),
  inventoryMetric: document.querySelector("#inventoryMetric"),
  lastFill: document.querySelector("#lastFill"),
  levelsInput: document.querySelector("#levelsInput"),
  levelsValue: document.querySelector("#levelsValue"),
  liquidityCanvas: document.querySelector("#liquidityCanvas"),
  markPrice: document.querySelector("#markPrice"),
  marketTitle: document.querySelector("#marketTitle"),
  orderSizeInput: document.querySelector("#orderSizeInput"),
  quoteInput: document.querySelector("#quoteInput"),
  resetButton: document.querySelector("#resetButton"),
  riskStatus: document.querySelector("#riskStatus"),
  runButton: document.querySelector("#runButton"),
  runState: document.querySelector("#runState"),
  runtimeLog: document.querySelector("#runtimeLog"),
  spacingInput: document.querySelector("#spacingInput"),
  spacingValue: document.querySelector("#spacingValue"),
  stepButton: document.querySelector("#stepButton"),
  symbolInput: document.querySelector("#symbolInput")
};

let state = null;
let backendOnline = false;

function authHeaders() {
  const token = localStorage.getItem(controlTokenKey);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function promptForControlToken() {
  const token = window.prompt("Control token");
  if (!token) return false;
  localStorage.setItem(controlTokenKey, token.trim());
  return true;
}

async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {})
    }
  });
  if (response.status !== 401) return response;
  if (!promptForControlToken()) return response;
  return fetch(path, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {})
    }
  });
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: "currency"
  }).format(value || 0);
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

function configFromInputs() {
  const candles = parseCsv(els.csvInput.value);
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
    symbol: els.symbolInput.value.trim() || "BTC-USD",
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

function drawLiquidity() {
  const { ctx, height, width } = setupCanvas(els.liquidityCanvas);
  const candle = state.candles[Math.max(0, Math.min(state.activeIndex, state.candles.length - 1))];
  const levels = buildLevels(candle.close);
  const prices = [...levels.map((level) => level.price), candle.high, candle.low, candle.close];
  const min = Math.min(...prices) * 0.998;
  const max = Math.max(...prices) * 1.002;
  const yFor = (price) => height - 34 - ((price - min) / (max - min)) * (height - 72);

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

  levels.forEach((level) => {
    const y = yFor(level.price);
    const isBuy = level.side === "buy";
    const start = isBuy ? 40 : width * 0.52;
    const end = isBuy ? width * 0.48 : width - 40;
    ctx.strokeStyle = isBuy ? "#0f9f7a" : "#c74747";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(start, y);
    ctx.lineTo(end, y);
    ctx.stroke();

    ctx.fillStyle = "#202523";
    ctx.font = "700 12px system-ui";
    ctx.textAlign = isBuy ? "left" : "right";
    ctx.fillText(`${level.side.toUpperCase()} ${money(level.price)}`, isBuy ? 42 : width - 42, y - 9);
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
  ctx.fillText(candle.timestamp, width / 2, height - 12);
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
  els.backendStatus.textContent = `${snapshot.mode} ${snapshot.running ? "running" : "stopped"}`;
  els.candleCount.textContent = snapshot.running ? "backend loop" : "backend idle";
  els.riskStatus.textContent = snapshot.riskStatus || "ready";
  els.runState.textContent = snapshot.running ? "Backend running" : "Backend ready";
  if (snapshot.markPrice) {
    els.markPrice.textContent = money(snapshot.markPrice);
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

async function refreshBackend() {
  try {
    const response = await apiFetch("/api/status", { cache: "no-store" });
    if (response.status === 401) {
      backendOnline = false;
      els.backendStatus.textContent = "Locked";
      return;
    }
    if (!response.ok) throw new Error("backend offline");
    renderBackend(await response.json());
  } catch {
    backendOnline = false;
    els.backendStatus.textContent = "Offline";
  }
}

async function backendCommand(path) {
  const response = await apiFetch(path, { method: "POST" });
  if (!response.ok) throw new Error(`request failed: ${path}`);
  renderBackend(await response.json());
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
  els.markPrice.textContent = money(mark);
  els.marketTitle.textContent = `${state.symbol} liquidity map`;
  els.runState.textContent = state.activeIndex >= state.candles.length ? "Complete" : "Ready";
  renderTape();
  drawLiquidity();
  drawEquity();
  if (!backendOnline) {
    els.runtimeLog.innerHTML = "<article>Serve with the live backend to control paper/live loops.</article>";
    els.riskStatus.textContent = "local";
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
reset();
refreshBackend();
setInterval(refreshBackend, 2500);
