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
  credentialStatus: document.querySelector("#credentialStatus"),
  csvInput: document.querySelector("#csvInput"),
  equityCanvas: document.querySelector("#equityCanvas"),
  equityMetric: document.querySelector("#equityMetric"),
  feeInput: document.querySelector("#feeInput"),
  feesMetric: document.querySelector("#feesMetric"),
  fillCount: document.querySelector("#fillCount"),
  fillTape: document.querySelector("#fillTape"),
  businessPlanButton: document.querySelector("#businessPlanButton"),
  freePlanButton: document.querySelector("#freePlanButton"),
  harvestMetric: document.querySelector("#harvestMetric"),
  inventoryMetric: document.querySelector("#inventoryMetric"),
  lastFill: document.querySelector("#lastFill"),
  levelsInput: document.querySelector("#levelsInput"),
  levelsValue: document.querySelector("#levelsValue"),
  liquidityCanvas: document.querySelector("#liquidityCanvas"),
  loginButton: document.querySelector("#loginButton"),
  logoutButton: document.querySelector("#logoutButton"),
  markPrice: document.querySelector("#markPrice"),
  market3dMap: document.querySelector("#market3dMap"),
  marketStrip: document.querySelector("#marketStrip"),
  marketTitle: document.querySelector("#marketTitle"),
  orderSizeInput: document.querySelector("#orderSizeInput"),
  paymentCurrencySelect: document.querySelector("#paymentCurrencySelect"),
  paymentEmailInput: document.querySelector("#paymentEmailInput"),
  paymentMethodSelect: document.querySelector("#paymentMethodSelect"),
  paymentStatus: document.querySelector("#paymentStatus"),
  passwordInput: document.querySelector("#passwordInput"),
  proPlanButton: document.querySelector("#proPlanButton"),
  quoteInput: document.querySelector("#quoteInput"),
  registerButton: document.querySelector("#registerButton"),
  resetButton: document.querySelector("#resetButton"),
  riskStatus: document.querySelector("#riskStatus"),
  runButton: document.querySelector("#runButton"),
  runState: document.querySelector("#runState"),
  saveCredentialsButton: document.querySelector("#saveCredentialsButton"),
  secretKeyInput: document.querySelector("#secretKeyInput"),
  runtimeLog: document.querySelector("#runtimeLog"),
  spacingInput: document.querySelector("#spacingInput"),
  spacingValue: document.querySelector("#spacingValue"),
  stepButton: document.querySelector("#stepButton"),
  subscriptionStatus: document.querySelector("#subscriptionStatus"),
  symbolInput: document.querySelector("#symbolInput"),
  usernameInput: document.querySelector("#usernameInput")
};

let state = null;
let backendOnline = false;
let currentUser = { authenticated: false, credentialsConfigured: false };
let markets = [];
let marketGroups = {};
let selectedAsset = "BTC";
let marketScene = null;
localStorage.removeItem("monatiseControlToken");

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

function renderAuth(me) {
  currentUser = me;
  selectedAsset = me.selectedSymbol || selectedAsset;
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
  els.backendStartButton.disabled = !loggedIn || !me.credentialsConfigured;
  els.backendStopButton.disabled = !loggedIn;
  if (!loggedIn) {
    backendOnline = false;
    els.backendStatus.textContent = "Login required";
  }
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
        .map((asset) => `<option value="${asset.symbol}">${asset.symbol}</option>`)
        .join("");
    }
    if (!markets.some((asset) => asset.symbol === selectedAsset) && markets[0]) {
      selectedAsset = markets[0].symbol;
    }
    syncSelectedAsset();
    if (!backendOnline) {
      const active = markets.find((asset) => asset.symbol === selectedAsset);
      if (active) {
        els.markPrice.textContent = money(active.price);
        els.marketTitle.textContent = `${selectedAsset}-USD liquidity map`;
      }
    }
  } catch {
    if (!els.assetSelect.options.length) {
      ["BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE"].forEach((symbol) => {
        els.assetSelect.add(new Option(symbol, symbol));
      });
    }
  }
}

function renderMarkets() {
  els.marketStrip.innerHTML = markets
    .map(
      (asset) => `<button type="button" data-symbol="${asset.symbol}" class="${asset.symbol === selectedAsset ? "active" : ""}">
        <strong>${asset.symbol}</strong>
        <span>${money(asset.price)}</span>
      </button>`
    )
    .join("");
  renderAssetGroups();
  updateMarketMap();
}

function renderAssetGroups() {
  const groups = [
    ["Crypto perps", marketGroups.crypto || markets],
    ["HIP-3 builder", marketGroups.builder || []],
    ["Forex watch", marketGroups.forex || []],
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
                      return `<button type="button" data-symbol="${asset.symbol}">${asset.symbol} ${money(asset.price)}</button>`;
                    }
                    return `<span class="asset-chip unavailable">${asset.symbol}</span>`;
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
  syncSelectedAsset();
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
      : `${payload.amount} ${payload.currency} on ${payload.network}: ${payload.address} ref ${payload.reference}`;
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
    if (!currentUser.authenticated) {
      backendOnline = false;
      els.backendStatus.textContent = "Login required";
      return;
    }
    const response = await apiFetch("/api/status", { cache: "no-store" });
    if (response.status === 401) {
      backendOnline = false;
      els.backendStatus.textContent = "Login required";
      renderAuth({ authenticated: false, credentialsConfigured: false });
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
  const response = await jsonPost(path);
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
  const live = markets.find((asset) => asset.symbol === selectedAsset);
  els.markPrice.textContent = live ? money(live.price) : money(mark);
  els.marketTitle.textContent = `${selectedAsset}-USD liquidity map`;
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
els.assetSelect.addEventListener("change", () => saveSelectedAsset(els.assetSelect.value));
els.marketStrip.addEventListener("click", (event) => {
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
els.freePlanButton.addEventListener("click", () => checkoutPlan("free"));
els.proPlanButton.addEventListener("click", () => checkoutPlan("pro"));
els.businessPlanButton.addEventListener("click", () => checkoutPlan("business"));
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
loadMe();
refreshBackend();
setInterval(loadMarkets, 5000);
setInterval(refreshBackend, 2500);
