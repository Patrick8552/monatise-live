const CG_BASE = "/api/coinglass/proxy";
const HYPER_BASE = "https://api.hyperliquid.xyz/info";
const ELEVEN_BASE = "https://api.elevenlabs.io";
const OPENAI_BASE = "https://api.openai.com";
const SESSION_KEY = "btc-coinglass-dashboard-session-coinglass-only";
const API_KEY_STORAGE = "btc-coinglass-api-key";
const ABLY_KEY_STORAGE = "monatise-ably-api-key";
const ABLY_CHANNEL_STORAGE = "monatise-ably-channel";
const ELEVEN_KEY_STORAGE = "monatise-elevenlabs-api-key";
const ELEVEN_VOICE_STORAGE = "monatise-elevenlabs-voice-id";
const OPENAI_KEY_STORAGE = "monatise-openai-api-key";
const OPENAI_MODEL_STORAGE = "monatise-openai-model";
const TRADER_ACCOUNT_STORAGE = "monatise-trader-account-size";
const TRADER_RISK_STORAGE = "monatise-trader-risk-pct";
const LOCKED_SIGNAL_STORAGE = "monatise-locked-signal";
const ANALYSIS_INTERVAL = "30m";
const XAU_ANALYSIS_INTERVALS = ["15m", "5m"];
const XAU_PRIMARY_ANALYSIS_INTERVAL = "15m";
const XAU_CONFIRMATION_INTERVAL = "5m";
const DEFAULT_VIEW_INTERVAL = "1h";
const ASSET_DEFINITIONS = [
  "BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "TRX", "TON", "DOT", "BCH", "LTC", "UNI", "NEAR",
  "APT", "ICP", "ETC", "ATOM", "FIL", "ARB", "OP", "SUI", "SEI", "INJ", "TIA", "WLD", "AAVE", "MKR", "RUNE", "GRT",
  "ALGO", "JUP", "PYTH", "JTO", "ONDO", "ENA", "WIF", "PEPE", "SHIB", "FLOKI", "BONK", "ORDI", "1000SATS", "1000RATS",
  "FET", "RNDR", "TAO", "LDO", "STX", "IMX", "SAND", "MANA", "AXS", "GALA", "APE", "GMT", "DYDX", "BLUR", "STRK",
  "ZK", "ZRO", "NOT", "PEOPLE", "ENS", "CRV", "COMP", "SNX", "SUSHI", "YFI", "1INCH", "KAS", "MATIC", "POL", "XLM",
  "HBAR", "VET", "THETA", "EGLD", "XMR", "ZEC", "DASH", "KAVA", "MINA", "ROSE", "CELO", "FLOW", "CHZ", "QNT"
].map((coin) => ({
  coin,
  hyper: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"].includes(coin) ? coin : "",
  pair: `${coin}USDT`,
  tv: `BINANCE:${coin}USDT`
})).concat([
  { coin: "GOLD", hyper: "GOLD", hyperAliases: ["GOLD", "xyz:GOLD"], pair: "XAUUSD", search: "GOLD XAU XAUUSD", tv: "OANDA:XAUUSD" },
  { coin: "XAU", hyper: "GOLD", hyperAliases: ["GOLD", "xyz:GOLD"], pair: "XAUUSD", search: "GOLD XAU XAUUSD", tv: "OANDA:XAUUSD" },
  { coin: "XAG", hyper: "", pair: "XAGUSD", search: "SILVER XAG XAGUSD", tv: "OANDA:XAGUSD" },
  { coin: "CL", hyper: "CL", pair: "USOIL", search: "WTI OIL CL USOIL", tv: "NYMEX:CL1!" },
  { coin: "BRENTOIL", hyper: "BRENTOIL", pair: "UKOIL", search: "BRENT OIL UKOIL", tv: "TVC:UKOIL" },
  { coin: "EURUSD", hyper: "", pair: "EURUSD", search: "EUR USD EURO DOLLAR", tv: "FX:EURUSD" },
  { coin: "GBPUSD", hyper: "", pair: "GBPUSD", search: "GBP USD CABLE", tv: "FX:GBPUSD" },
  { coin: "USDJPY", hyper: "", pair: "USDJPY", search: "USD JPY YEN", tv: "FX:USDJPY" },
  { coin: "AUDUSD", hyper: "", pair: "AUDUSD", search: "AUD USD AUSSIE", tv: "FX:AUDUSD" },
  { coin: "AUDJPY", hyper: "", pair: "AUDJPY", search: "AUD JPY", tv: "FX:AUDJPY" },
  { coin: "EURGBP", hyper: "", pair: "EURGBP", search: "EUR GBP", tv: "FX:EURGBP" },
  { coin: "EURJPY", hyper: "", pair: "EURJPY", search: "EUR JPY", tv: "FX:EURJPY" },
  { coin: "NZDUSD", hyper: "", pair: "NZDUSD", search: "NZD USD KIWI", tv: "FX:NZDUSD" }
]);
const ASSETS = Object.fromEntries(ASSET_DEFINITIONS.map((asset) => [asset.coin, asset]));

const els = {
  apiKeyInput: document.querySelector("#apiKeyInput"),
  assetSearchInput: document.querySelector("#assetSearchInput"),
  assetSearchResults: document.querySelector("#assetSearchResults"),
  assetSelect: document.querySelector("#assetSelect"),
  exchangeSelect: document.querySelector("#exchangeSelect"),
  intervalSelect: document.querySelector("#intervalSelect"),
  liqRangeSelect: document.querySelector("#liqRangeSelect"),
  ablyKeyInput: document.querySelector("#ablyKeyInput"),
  ablyChannelInput: document.querySelector("#ablyChannelInput"),
  elevenKeyInput: document.querySelector("#elevenKeyInput"),
  elevenVoiceInput: document.querySelector("#elevenVoiceInput"),
  voiceQuestionInput: document.querySelector("#voiceQuestionInput"),
  voiceRecordButton: document.querySelector("#voiceRecordButton"),
  voiceAskButton: document.querySelector("#voiceAskButton"),
  voiceStopButton: document.querySelector("#voiceStopButton"),
  openaiKeyInput: document.querySelector("#openaiKeyInput"),
  openaiModelInput: document.querySelector("#openaiModelInput"),
  copilotQuestionInput: document.querySelector("#copilotQuestionInput"),
  copilotAskButton: document.querySelector("#copilotAskButton"),
  refreshButton: document.querySelector("#refreshButton"),
  openIntegrationsButton: document.querySelector("#openIntegrationsButton"),
  installDashboardButton: document.querySelector("#installDashboardButton"),
  clearSessionButton: document.querySelector("#clearSessionButton"),
  sessionStatusDot: document.querySelector("#sessionStatusDot"),
  sessionStatusText: document.querySelector("#sessionStatusText"),
  sessionUpdated: document.querySelector("#sessionUpdated"),
  dashboardTitle: document.querySelector("#dashboardTitle"),
  headerMarketSymbol: document.querySelector("#headerMarketSymbol"),
  headerAssetPrice: document.querySelector("#headerAssetPrice"),
  headerPriceChange: document.querySelector("#headerPriceChange"),
  marketSymbol: document.querySelector("#marketSymbol"),
  monitorGrid: document.querySelector("#monitorGrid"),
  monitorStatus: document.querySelector("#monitorStatus"),
  assetPrice: document.querySelector("#assetPrice"),
  priceChange: document.querySelector("#priceChange"),
  liquidityAtlasCanvas: document.querySelector("#liquidityAtlasCanvas"),
  atlasMode: document.querySelector("#atlasMode"),
  atlasSignal: document.querySelector("#atlasSignal"),
  atlasDetail: document.querySelector("#atlasDetail"),
  atlasButtons: document.querySelectorAll("[data-atlas-view]"),
  fundingAverage: document.querySelector("#fundingAverage"),
  openInterest: document.querySelector("#openInterest"),
  fearGreed: document.querySelector("#fearGreed"),
  liqBias: document.querySelector("#liqBias"),
  vwapMetric: document.querySelector("#vwapMetric"),
  coinGlassStatus: document.querySelector("#coinGlassStatus"),
  coinGlassStatusDetail: document.querySelector("#coinGlassStatusDetail"),
  coinGlassPriceRef: document.querySelector("#coinGlassPriceRef"),
  coinGlassRouteRef: document.querySelector("#coinGlassRouteRef"),
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
  signalTimestamp: document.querySelector("#signalTimestamp"),
  signalState: document.querySelector("#signalState"),
  signalAsset: document.querySelector("#signalAsset"),
  signalAction: document.querySelector("#signalAction"),
  signalThesis: document.querySelector("#signalThesis"),
  signalEntry: document.querySelector("#signalEntry"),
  signalEntryPlan: document.querySelector("#signalEntryPlan"),
  signalInvalidation: document.querySelector("#signalInvalidation"),
  signalInvalidationPlan: document.querySelector("#signalInvalidationPlan"),
  signalGridHedge: document.querySelector("#signalGridHedge"),
  signalGridHedgePlan: document.querySelector("#signalGridHedgePlan"),
  signalEvidence: document.querySelector("#signalEvidence"),
  signalEvidencePlan: document.querySelector("#signalEvidencePlan"),
  signalLog: document.querySelector("#signalLog"),
  traderAccountInput: document.querySelector("#traderAccountInput"),
  traderRiskInput: document.querySelector("#traderRiskInput"),
  traderMaxLoss: document.querySelector("#traderMaxLoss"),
  traderPositionSize: document.querySelector("#traderPositionSize"),
  traderStopDistance: document.querySelector("#traderStopDistance"),
  traderRewardRisk: document.querySelector("#traderRewardRisk"),
  traderRiskNote: document.querySelector("#traderRiskNote"),
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
  structureSummary: document.querySelector("#structureSummary"),
  indicatorStack: document.querySelector("#indicatorStack"),
  tradingViewFrame: document.querySelector("#tradingViewFrame"),
  tradingViewLink: document.querySelector("#tradingViewLink"),
  tradingViewSource: document.querySelector("#tradingViewSource"),
  liqCanvas: document.querySelector("#liqCanvas"),
  fundingList: document.querySelector("#fundingList"),
  oiList: document.querySelector("#oiList"),
  hyperList: document.querySelector("#hyperList"),
  newsList: document.querySelector("#newsList"),
  sessionTimers: document.querySelector("#sessionTimers"),
  liveAlertStatus: document.querySelector("#liveAlertStatus"),
  liveAlertList: document.querySelector("#liveAlertList"),
  voiceStatus: document.querySelector("#voiceStatus"),
  voiceTranscript: document.querySelector("#voiceTranscript"),
  voiceAnswer: document.querySelector("#voiceAnswer"),
  voiceAudio: document.querySelector("#voiceAudio"),
  copilotStatus: document.querySelector("#copilotStatus"),
  copilotAnswer: document.querySelector("#copilotAnswer"),
  telemetryList: document.querySelector("#telemetryList"),
  fgGauge: document.querySelector("#fgGauge"),
  fgLabel: document.querySelector("#fgLabel")
};

let deferredDashboardInstallPrompt = null;

const state = {
  telemetry: readSession(),
  apiKey: localStorage.getItem(API_KEY_STORAGE) || "",
  operator: null,
  serverCoinGlassReady: false,
  priceSeries: [],
  lastPrice: null,
  signals: [],
  lockedSignal: readLockedSignal(),
  activeSignal: null,
  atlas: {
    renderer: null,
    scene: null,
    camera: null,
    mesh: null,
    particles: null,
    material: null,
    heatmapGroup: null,
    zoneGroup: null,
    structureGroup: null,
    ecosystemGroup: null,
    heatmapBars: [],
    zones: [],
    ecosystemNodes: [],
    view: "btc",
    pointer: { x: 0, y: 0 },
    mode: "WAIT",
    started: false,
    fallback: false
  },
  realtime: {
    client: null,
    channel: null,
    key: localStorage.getItem(ABLY_KEY_STORAGE) || "",
    channelName: localStorage.getItem(ABLY_CHANNEL_STORAGE) || "monatise-live-alerts",
    events: [],
    lastSetup: null,
    lastEntrySignal: null,
    lastGridCompletion: null
  },
  voice: {
    apiKey: localStorage.getItem(ELEVEN_KEY_STORAGE) || "",
    voiceId: localStorage.getItem(ELEVEN_VOICE_STORAGE) || "JBFqnCBsd6RMkjVDRZzb",
    recorder: null,
    chunks: [],
    recording: false,
    audioUrl: null
  },
  copilot: {
    apiKey: localStorage.getItem(OPENAI_KEY_STORAGE) || "",
    model: localStorage.getItem(OPENAI_MODEL_STORAGE) || "gpt-5.5"
  },
  monitor: {
    cursor: 0,
    lastRun: 0,
    results: {},
    scanning: false
  },
  market: {
    priceChange: 0,
    fundingAverage: null,
    oiChange: null,
    liquidationBias: null,
    liquidationLevels: [],
    liquiditySource: "",
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
    pattern: null,
    indicatorScore: 0,
    indicatorSummary: "",
    indicatorRows: [],
    analysisFrame: ""
  }
};

const FALLBACK_SNAPSHOT_LOCK_MS = 30 * 60 * 1000;

function readLockedSignal() {
  try {
    const parsed = JSON.parse(localStorage.getItem(LOCKED_SIGNAL_STORAGE) || "null");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function setLockedSignal(signal) {
  state.lockedSignal = signal || null;
  if (state.lockedSignal) {
    localStorage.setItem(LOCKED_SIGNAL_STORAGE, JSON.stringify(state.lockedSignal));
  } else {
    localStorage.removeItem(LOCKED_SIGNAL_STORAGE);
  }
}

els.apiKeyInput.value = state.apiKey;
els.ablyKeyInput.value = state.realtime.key;
els.ablyChannelInput.value = state.realtime.channelName;
els.elevenKeyInput.value = state.voice.apiKey;
els.elevenVoiceInput.value = state.voice.voiceId;
els.openaiKeyInput.value = state.copilot.apiKey;
els.openaiModelInput.value = state.copilot.model;
els.traderAccountInput.value = localStorage.getItem(TRADER_ACCOUNT_STORAGE) || "1000";
els.traderRiskInput.value = localStorage.getItem(TRADER_RISK_STORAGE) || "1";
els.intervalSelect.value = DEFAULT_VIEW_INTERVAL;
if (!state.voice.apiKey) els.voiceStatus.textContent = "Text response mode";
if (!state.copilot.apiKey) els.copilotStatus.textContent = "Local copilot fallback";
renderTraderMode();

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

function setupDashboardInstall() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredDashboardInstallPrompt = event;
    if (els.installDashboardButton) els.installDashboardButton.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    deferredDashboardInstallPrompt = null;
    if (els.installDashboardButton) els.installDashboardButton.hidden = true;
  });
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

function parseDisplayedNumber(text) {
  const cleaned = String(text || "").replace(/[^0-9.-]/g, "");
  const number = Number(cleaned);
  return Number.isFinite(number) && number > 0 ? number : Number.NaN;
}

function positiveInputValue(input, fallback) {
  const value = Number(input?.value);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function formatPercent(value, digits = 3) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}%`;
}

function updateTopPrice(price, detail = "Live mark") {
  const value = Number(price);
  if (!Number.isFinite(value) || value <= 0) return;
  const formatted = formatUsd(value);
  els.assetPrice.textContent = formatted;
  els.headerAssetPrice.textContent = formatted;
  els.headerPriceChange.textContent = detail;
  els.headerPriceChange.className = "";
}

function setSessionStatus(kind, text) {
  els.sessionStatusDot.className = `status-dot ${kind === "good" ? "good" : kind === "bad" ? "bad" : ""}`;
  els.sessionStatusText.textContent = text;
  els.sessionUpdated.textContent = new Date().toLocaleTimeString();
}

function initLiquidityAtlas() {
  const canvas = els.liquidityAtlasCanvas;
  if (!canvas || state.atlas.started) return;
  state.atlas.started = true;
  if (!window.THREE) {
    state.atlas.fallback = true;
    drawAtlasFallback();
    return;
  }
  const THREE = window.THREE;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0.9, 7);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, canvas, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x081018, 1);

  const geometry = new THREE.PlaneGeometry(9, 3.4, 96, 28);
  const material = new THREE.MeshStandardMaterial({
    color: 0x75ffd6,
    emissive: 0x102c31,
    metalness: 0.25,
    roughness: 0.55,
    wireframe: true
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = -0.72;
  mesh.position.y = -0.45;
  scene.add(mesh);

  const points = new THREE.BufferGeometry();
  const positions = [];
  const colors = [];
  for (let i = 0; i < 260; i += 1) {
    positions.push((Math.random() - 0.5) * 9, (Math.random() - 0.5) * 3.4, (Math.random() - 0.5) * 2.2);
    colors.push(0.45 + Math.random() * 0.4, 0.8 + Math.random() * 0.2, 0.72 + Math.random() * 0.28);
  }
  points.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  points.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  const particles = new THREE.Points(points, new THREE.PointsMaterial({ size: 0.045, vertexColors: true, transparent: true, opacity: 0.86 }));
  scene.add(particles);

  const heatmapGroup = new THREE.Group();
  const zoneGroup = new THREE.Group();
  const structureGroup = new THREE.Group();
  const ecosystemGroup = new THREE.Group();
  scene.add(heatmapGroup, zoneGroup, structureGroup, ecosystemGroup);
  buildAtlasHeatmap(THREE, heatmapGroup);
  buildAtlasZones(THREE, zoneGroup);
  buildAtlasStructure(THREE, structureGroup);
  buildAtlasEcosystem(THREE, ecosystemGroup);

  scene.add(new THREE.AmbientLight(0x8fd7ff, 0.75));
  const keyLight = new THREE.PointLight(0xff62d2, 1.25, 12);
  keyLight.position.set(3.8, 2.3, 4);
  scene.add(keyLight);
  const fillLight = new THREE.PointLight(0x75ffd6, 1.15, 10);
  fillLight.position.set(-3.5, -1.6, 3);
  scene.add(fillLight);

  state.atlas.renderer = renderer;
  state.atlas.scene = scene;
  state.atlas.camera = camera;
  state.atlas.mesh = mesh;
  state.atlas.particles = particles;
  state.atlas.material = material;
  state.atlas.heatmapGroup = heatmapGroup;
  state.atlas.zoneGroup = zoneGroup;
  state.atlas.structureGroup = structureGroup;
  state.atlas.ecosystemGroup = ecosystemGroup;

  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    state.atlas.pointer.x = ((event.clientX - rect.left) / Math.max(1, rect.width) - 0.5) * 2;
    state.atlas.pointer.y = ((event.clientY - rect.top) / Math.max(1, rect.height) - 0.5) * -2;
  });

  const render = (time) => {
    if (!state.atlas.renderer) return;
    resizeAtlas();
    const t = time * 0.001;
    const positionsAttr = mesh.geometry.attributes.position;
    const directionLift = state.atlas.mode.includes("BUY") ? 0.18 : state.atlas.mode.includes("SELL") ? -0.18 : 0;
    for (let i = 0; i < positionsAttr.count; i += 1) {
      const x = positionsAttr.getX(i);
      const y = positionsAttr.getY(i);
      positionsAttr.setZ(i, Math.sin(x * 1.6 + t * 1.1) * 0.16 + Math.cos(y * 3.4 + t * 0.8) * 0.09 + directionLift);
    }
    positionsAttr.needsUpdate = true;
    mesh.rotation.z = Math.sin(t * 0.16) * 0.025;
    particles.rotation.z = t * 0.045;
    particles.rotation.x = Math.sin(t * 0.12) * 0.08;
    heatmapGroup.rotation.y = state.atlas.pointer.x * 0.08;
    zoneGroup.children.forEach((zone, index) => {
      zone.position.y += Math.sin(t * 0.9 + index) * 0.0009;
      zone.rotation.z = Math.sin(t * 0.35 + index) * 0.08;
    });
    structureGroup.children.forEach((child, index) => {
      child.position.z = Math.sin(t * 1.4 + index) * 0.04;
    });
    ecosystemGroup.rotation.y += (state.atlas.pointer.x * 0.16 - ecosystemGroup.rotation.y) * 0.04;
    ecosystemGroup.rotation.x += (state.atlas.pointer.y * 0.08 - ecosystemGroup.rotation.x) * 0.04;
    renderer.render(scene, camera);
    requestAnimationFrame(render);
  };
  requestAnimationFrame(render);
}

function buildAtlasHeatmap(THREE, group) {
  const geometry = new THREE.BoxGeometry(0.12, 1, 0.12);
  state.atlas.heatmapBars = [];
  for (let i = 0; i < 42; i += 1) {
    const side = i % 2 === 0 ? 1 : -1;
    const distance = Math.floor(i / 2);
    const material = new THREE.MeshStandardMaterial({
      color: side > 0 ? 0x75ffd6 : 0xff62d2,
      emissive: side > 0 ? 0x12342f : 0x371229,
      transparent: true,
      opacity: 0.74,
      roughness: 0.42,
      metalness: 0.2
    });
    const bar = new THREE.Mesh(geometry, material);
    bar.position.set((distance - 10) * 0.36, -1.36, side * (0.55 + distance * 0.025));
    bar.scale.y = 0.15 + Math.abs(Math.sin(i * 1.7)) * 0.72;
    group.add(bar);
    state.atlas.heatmapBars.push(bar);
  }
}

function buildAtlasZones(THREE, group) {
  const zoneGeometry = new THREE.PlaneGeometry(1.35, 0.22);
  state.atlas.zones = [];
  for (let i = 0; i < 8; i += 1) {
    const material = new THREE.MeshBasicMaterial({
      color: i % 2 ? 0xffbf47 : 0x52d6ff,
      transparent: true,
      opacity: 0.24,
      side: THREE.DoubleSide
    });
    const zone = new THREE.Mesh(zoneGeometry, material);
    zone.position.set(-3.7 + i * 1.05, 0.1 + Math.sin(i) * 0.35, -0.4 + (i % 3) * 0.42);
    zone.rotation.x = -0.62;
    group.add(zone);
    state.atlas.zones.push(zone);
  }
}

function buildAtlasStructure(THREE, group) {
  const bullish = new THREE.LineBasicMaterial({ color: 0x75ffd6, transparent: true, opacity: 0.95 });
  const bearish = new THREE.LineBasicMaterial({ color: 0xff62d2, transparent: true, opacity: 0.95 });
  for (let lane = 0; lane < 3; lane += 1) {
    const points = [];
    for (let i = 0; i < 8; i += 1) {
      points.push(new THREE.Vector3(-4 + i * 1.14, 0.55 + Math.sin(i * 0.9 + lane) * 0.32, -0.9 + lane * 0.55));
    }
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    group.add(new THREE.Line(geometry, lane === 1 ? bearish : bullish));
  }
}

function buildAtlasEcosystem(THREE, group) {
  const btc = createAtlasNode(THREE, "BTC", 0xffbf47, -1.15);
  const gold = createAtlasNode(THREE, "Gold", 0xf7d774, 1.15);
  group.add(btc.mesh, gold.mesh);
  state.atlas.ecosystemNodes = [btc, gold];
}

function createAtlasNode(THREE, label, color, x) {
  const geometry = new THREE.SphereGeometry(0.34, 32, 16);
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color === 0xffbf47 ? 0x402800 : 0x332600,
    metalness: 0.45,
    roughness: 0.32
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(x, 0.82, 0.35);
  mesh.userData.label = label;
  return { label, mesh };
}

function resizeAtlas() {
  if (state.atlas.fallback) {
    drawAtlasFallback();
    return;
  }
  const canvas = els.liquidityAtlasCanvas;
  const renderer = state.atlas.renderer;
  if (!canvas || !renderer || !state.atlas.camera || !window.THREE) return;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  const size = renderer.getSize(new window.THREE.Vector2());
  if (size.x !== width || size.y !== height) {
    renderer.setSize(width, height, false);
    state.atlas.camera.aspect = width / height;
    state.atlas.camera.updateProjectionMatrix();
  }
}

function updateLiquidityAtlas() {
  const direction = els.setupDirection.textContent || "WAIT";
  const asset = selectedCoin();
  const viewLabel = state.atlas.view === "gold" ? "Gold macro" : state.atlas.view === "dual" ? `${asset} + Gold` : `${asset} crypto`;
  const vwap = state.market.vwapSignal || "VWAP pending";
  const funding = state.market.fundingAverage == null ? "CoinGlass funding pending" : `CoinGlass funding ${formatPercent(state.market.fundingAverage, 4)}`;
  const liq = state.market.liquidationBias || "liquidity forming";
  state.atlas.mode = direction;
  els.atlasMode.textContent = `Monatise Liquidity Atlas · ${viewLabel}`;
  els.atlasSignal.textContent = state.atlas.view === "gold" ? `Gold ${goldSignalFromCrypto(direction)}` : `${asset} ${direction}`;
  els.atlasSignal.className = direction.includes("BUY") ? "positive" : direction.includes("SELL") ? "negative" : "";
  els.atlasDetail.textContent = state.atlas.view === "gold"
    ? `Gold hedge lens · BTC ${direction} · ${vwap} · ${liq}`
    : `${vwap} · ${liq} · ${funding}`;
  if (state.atlas.material) {
    const color = state.atlas.view === "gold" ? 0xf7d774 : direction.includes("BUY") ? 0x75ffd6 : direction.includes("SELL") ? 0xff62d2 : 0xffbf47;
    state.atlas.material.color.setHex(color);
    state.atlas.material.emissive.setHex(direction.includes("SELL") ? 0x321326 : direction.includes("BUY") ? 0x102c31 : 0x2b2110);
  }
  updateAtlasHeatmapObjects(direction);
  updateAtlasEcosystemObjects();
  if (state.atlas.fallback) drawAtlasFallback();
}

function goldSignalFromCrypto(direction) {
  if (direction.includes("BUY")) return "hedge watch";
  if (direction.includes("SELL")) return "safe-haven bid";
  return "macro neutral";
}

function updateAtlasHeatmapObjects(direction) {
  const squeeze = state.market.liquidationBias === "short squeeze";
  const flush = state.market.liquidationBias === "long flush";
  const vwapLift = Number(state.market.vwapScore || 0);
  state.atlas.heatmapBars.forEach((bar, index) => {
    const side = index % 2 === 0 ? 1 : -1;
    const bias = squeeze && side > 0 ? 1.55 : flush && side < 0 ? 1.55 : 0.86;
    const directionBias = direction.includes("BUY") && side > 0 ? 1.25 : direction.includes("SELL") && side < 0 ? 1.25 : 1;
    const goldBias = state.atlas.view === "gold" ? 0.72 + (index % 5) * 0.08 : 1;
    bar.scale.y = (0.18 + Math.abs(Math.sin(index * 1.27 + vwapLift)) * 0.92) * bias * directionBias * goldBias;
    bar.position.y = -1.48 + bar.scale.y * 0.45;
    bar.material.opacity = Math.min(0.9, 0.46 + bar.scale.y * 0.18);
  });
  state.atlas.zones.forEach((zone, index) => {
    const isGold = state.atlas.view === "gold";
    zone.material.color.setHex(isGold ? 0xf7d774 : index % 2 ? 0xffbf47 : 0x52d6ff);
    zone.material.opacity = isGold ? 0.2 + (index % 3) * 0.04 : 0.22 + Math.abs(vwapLift) * 0.04;
  });
}

function updateAtlasEcosystemObjects() {
  state.atlas.ecosystemNodes.forEach((node) => {
    const isGold = node.label === "Gold";
    const active =
      state.atlas.view === "dual" ||
      (state.atlas.view === "gold" && isGold) ||
      (state.atlas.view === "btc" && !isGold);
    node.mesh.visible = state.atlas.view === "dual" || active;
    node.mesh.scale.setScalar(active ? 1.18 : 0.72);
    node.mesh.material.opacity = active ? 1 : 0.42;
    node.mesh.material.transparent = !active;
  });
}

function drawAtlasFallback() {
  const canvas = els.liquidityAtlasCanvas;
  if (!canvas) return;
  const ctx = prepareCanvas(canvas);
  const { width, height } = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "rgba(117, 255, 214, 0.22)");
  gradient.addColorStop(0.45, "rgba(82, 214, 255, 0.08)");
  gradient.addColorStop(1, "rgba(255, 98, 210, 0.18)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  for (let i = 0; i < 34; i += 1) {
    const y = (height / 34) * i;
    ctx.strokeStyle = `rgba(238, 244, 251, ${i % 5 === 0 ? 0.18 : 0.06})`;
    ctx.beginPath();
    ctx.moveTo(0, y);
    for (let x = 0; x <= width; x += 18) {
      ctx.lineTo(x, y + Math.sin(x * 0.02 + i) * 10);
    }
    ctx.stroke();
  }
  const view = state.atlas.view;
  const nodes = view === "dual" ? [["BTC", width * 0.36, height * 0.42], ["Gold", width * 0.64, height * 0.42]] : [[view === "gold" ? "Gold" : selectedCoin(), width * 0.5, height * 0.42]];
  nodes.forEach(([label, x, y]) => {
    ctx.beginPath();
    ctx.arc(x, y, 28, 0, Math.PI * 2);
    ctx.fillStyle = label === "Gold" ? "rgba(247, 215, 116, 0.34)" : "rgba(117, 255, 214, 0.28)";
    ctx.fill();
    ctx.strokeStyle = label === "Gold" ? "rgba(247, 215, 116, 0.86)" : "rgba(117, 255, 214, 0.86)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#eef4fb";
    ctx.font = "bold 13px system-ui";
    ctx.textAlign = "center";
    ctx.fillText(label, x, y + 4);
  });
  for (let i = 0; i < 14; i += 1) {
    const x = (width / 14) * i + 6;
    const h = 14 + Math.abs(Math.sin(i + state.market.vwapScore)) * 54;
    ctx.fillStyle = i % 2 ? "rgba(255, 98, 210, 0.48)" : "rgba(117, 255, 214, 0.48)";
    ctx.fillRect(x, height - h - 12, Math.max(3, width / 42), h);
  }
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

function renderLiveAlerts() {
  if (!state.realtime.events.length) {
    els.liveAlertList.innerHTML = `
      <div class="news-item">
        <strong>No live events yet</strong>
        <small>State changes, entries, and grid completions will appear here.</small>
      </div>
    `;
    return;
  }
  els.liveAlertList.innerHTML = state.realtime.events.slice(0, 8).map((event) => `
    <div class="news-item">
      <strong>${event.title}</strong>
      <small>${event.asset} · ${event.kind} · ${event.time}</small>
      <p>${event.detail}</p>
    </div>
  `).join("");
}

function setLiveAlertStatus(text) {
  els.liveAlertStatus.textContent = text;
}

async function connectRealtime() {
  const key = state.realtime.key.trim();
  const channelName = state.realtime.channelName.trim() || "monatise-live-alerts";
  if (state.realtime.client) {
    state.realtime.client.close();
    state.realtime.client = null;
    state.realtime.channel = null;
  }
  if (!key) {
    setLiveAlertStatus("Local event stream ready");
    return;
  }
  if (!window.Ably?.Realtime) {
    setLiveAlertStatus("Ably SDK unavailable");
    recordTelemetry("Live alerts", "Ably", false, 0, "SDK unavailable");
    return;
  }
  const started = performance.now();
  const clientId = `monatise-${Math.random().toString(16).slice(2)}`;
  const client = new window.Ably.Realtime({ key, clientId });
  const channel = client.channels.get(channelName);
  state.realtime.client = client;
  state.realtime.channel = channel;

  client.connection.on("connected", () => {
    recordTelemetry("Live alerts", "Ably", true, Math.round(performance.now() - started), channelName);
    setLiveAlertStatus(`Ably live · ${channelName}`);
  });
  client.connection.on("failed", (error) => {
    const reason = error?.reason?.message || "connection failed";
    recordTelemetry("Live alerts", "Ably", false, Math.round(performance.now() - started), reason);
    setLiveAlertStatus(`Ably failed · ${reason}`);
  });
  client.connection.on("disconnected", () => setLiveAlertStatus("Ably reconnecting"));
  channel.subscribe("monatise-alert", (message) => {
    if (message.clientId === clientId) return;
    pushLiveAlert({
      kind: message.data?.kind || "external",
      asset: message.data?.asset || selectedCoin(),
      title: message.data?.title || "External live alert",
      detail: message.data?.detail || "Realtime message received.",
      payload: message.data?.payload || {}
    }, false);
  });
}

function pushLiveAlert(event, shouldPublish = true) {
  const item = {
    kind: event.kind,
    asset: event.asset,
    title: event.title,
    detail: event.detail,
    payload: event.payload || {},
    time: new Date().toLocaleTimeString()
  };
  state.realtime.events.unshift(item);
  state.realtime.events = state.realtime.events.slice(0, 40);
  renderLiveAlerts();
  if (shouldPublish && state.realtime.channel) {
    state.realtime.channel.publish("monatise-alert", item).catch((error) => {
      recordTelemetry("Publish alert", "Ably", false, 0, error.message);
      setLiveAlertStatus(`Ably publish failed · ${error.message}`);
    });
  }
}

function evaluateLiveAlerts(setup) {
  if (!setup) return;
  const asset = setup.asset;
  const setupSignature = `${asset}:${setup.direction}:${setup.gridDirection}:${setup.hedgeDirection}`;
  if (state.realtime.lastSetup && state.realtime.lastSetup !== setupSignature) {
    pushLiveAlert({
      kind: "state change",
      asset,
      title: `${asset} setup changed to ${setup.direction}`,
      detail: `${setup.gridDirection}; ${setup.hedgeDirection}. Confidence ${setup.confidence}%.`,
      payload: setup
    });
  }
  state.realtime.lastSetup = setupSignature;

  const entryReady = setup.direction !== "WAIT" && setup.confidence >= 55 && setup.liveChecks >= 5;
  const entrySignature = `${asset}:${setup.direction}:${Math.floor(Date.now() / 300000)}`;
  if (entryReady && state.realtime.lastEntrySignal !== entrySignature) {
    state.realtime.lastEntrySignal = entrySignature;
    pushLiveAlert({
      kind: "entry notification",
      asset,
      title: `${asset} ${setup.direction} entry window`,
      detail: `${setup.gridDirection}. ${setup.gridPlan}`,
      payload: setup
    });
  }

  const vwap = Number(setup.vwap);
  const price = Number(setup.price);
  const completed =
    setup.direction === "BUY SETUP"
      ? Number.isFinite(price) && Number.isFinite(vwap) && price >= vwap
      : setup.direction === "SELL SETUP"
        ? Number.isFinite(price) && Number.isFinite(vwap) && price <= vwap
        : false;
  const gridSignature = `${asset}:${setup.direction}:${Math.round(vwap || 0)}:${Math.floor(Date.now() / 900000)}`;
  if (completed && state.realtime.lastGridCompletion !== gridSignature) {
    state.realtime.lastGridCompletion = gridSignature;
    pushLiveAlert({
      kind: "grid completion",
      asset,
      title: `${asset} grid reached VWAP target`,
      detail: `Price ${formatUsd(price)} reached VWAP ${formatUsd(vwap)}. Review partials, hedge, and next grid.`,
      payload: setup
    });
  }
}

function publishGeneratedSignal(setup) {
  if (!setup) return;
  const rawPrice = Number(setup.price);
  const rawVwap = Number(setup.vwap);
  const price = Number.isFinite(rawPrice) && rawPrice > 0 ? rawPrice : state.lastPrice;
  const vwap = Number.isFinite(rawVwap) && rawVwap > 0 ? rawVwap : null;
  const candidate = buildGeneratedSignal(setup, price, vwap);
  const signal = snapshotLockedSignal(candidate, setup, price);
  renderGeneratedSignal(signal);

  const snapshotDurationMs = Number(signal.snapshotDurationMs) || selectedSnapshotLockMs();
  const signature = `${signal.asset}:${signal.action}:${Math.round(signal.entry || 0)}:${signal.score}:${Math.floor(signal.snapshotAtMs / snapshotDurationMs)}`;
  if (state.signals[0]?.signature !== signature) {
    state.signals.unshift({ ...signal, signature });
    state.signals = state.signals.slice(0, 8);
    renderSignalLog();
    pushLiveAlert({
      kind: "monatise signal",
      asset: signal.asset,
      title: `${signal.asset} ${signal.action}`,
      detail: `${signal.buyGridPlan} ${signal.sellGridPlan} Hedge: ${signal.hedgeDirection}.`,
      payload: signal
    });
  }
}

function snapshotLockedSignal(candidate, setup, price) {
  const now = Date.now();
  const locked = state.lockedSignal;
  const sameAsset = locked && locked.asset === candidate.asset;
  const snapshotInterval = selectedSnapshotInterval();
  const sameSnapshotFrame = sameAsset && locked.snapshotInterval === snapshotInterval;
  const stillLocked = sameSnapshotFrame && now < locked.reassessAtMs;
  if (sameAsset && !sameSnapshotFrame) {
    setLockedSignal(null);
  }
  const resolution = stillLocked ? lockedSignalResolution(locked, price, now) : null;
  const invalidated = stillLocked && (resolution?.status === "invalidated" || hasStructuralInvalidation(locked, setup, price));

  if (resolution || invalidated) {
    const resolvedStatus = resolution?.status || "invalidated";
    const resolvedLabel = resolvedStatus === "target-hit" ? "target hit" : resolvedStatus;
    const canceled = {
      ...locked,
      action: "WAIT",
      liveChecks: candidate.liveChecks,
      checksTotal: candidate.checksTotal,
      evidence: candidate.evidence,
      status: resolvedStatus,
      stateLabel: `setup ${resolvedLabel}`,
      thesis: resolution?.detail || `Setup canceled. Structural invalidation confirmed beyond ${formatUsd(locked.invalidation)}. Waiting for the next snapshot.`,
      entryPlan: "No new entry until a fresh BUY or SELL snapshot forms.",
      invalidationPlan: resolution?.detail || "Major structural invalidation canceled the setup. A fresh snapshot is required.",
      time: candidate.time
    };
    setLockedSignal(null);
    return canceled;
  }

  if (stillLocked && locked.action !== "WAIT") {
    const liveActionChanged = candidate.action !== locked.action;
    const liveWait = candidate.action === "WAIT";
    return {
      ...locked,
      liveChecks: candidate.liveChecks,
      checksTotal: candidate.checksTotal,
      evidence: candidate.evidence,
      status: liveActionChanged ? "locked" : "active",
      stateLabel: liveWait ? "active snapshot - wait ignored" : liveActionChanged ? "active snapshot - bias locked" : "active snapshot",
      thesis: snapshotThesis(locked, candidate),
      time: candidate.time
    };
  }

  const snapshotAtMs = now;
  const snapshotDurationMs = selectedSnapshotLockMs();
  const reassessAtMs = now + snapshotDurationMs;
  const fresh = {
    ...candidate,
    snapshotAtMs,
    reassessAtMs,
    snapshotDurationMs,
    snapshotInterval,
    snapshotTime: formatClock(snapshotAtMs),
    reassessTime: formatClock(reassessAtMs),
    status: candidate.action === "WAIT" ? "watch" : "active",
    stateLabel: candidate.action === "WAIT" ? "watch signal" : "active snapshot",
    thesis: candidate.action === "WAIT"
      ? candidate.thesis
      : `At ${formatClock(snapshotAtMs)}, probability favored ${candidate.action === "BUY" ? "buyers" : "sellers"}. Grid, invalidation, and target are locked on the ${snapshotInterval} snapshot until ${formatClock(reassessAtMs)}.`
  };
  setLockedSignal(fresh.action === "WAIT" ? null : fresh);
  return fresh;
}

function lockedSignalResolution(signal, price, now = Date.now()) {
  const mark = currentSignalMark(price);
  const target = Number(signal.target);
  const invalidation = Number(signal.invalidation);
  if (Number(signal.reassessAtMs) && now >= Number(signal.reassessAtMs)) {
    return {
      status: "expired",
      detail: `Snapshot expired at ${signal.reassessTime}. Waiting for the next framework pass.`
    };
  }
  if (!Number.isFinite(mark)) return null;
  if (signal.action === "BUY") {
    if (Number.isFinite(target) && mark >= target) {
      return { status: "target-hit", detail: `Target reached at ${formatUsd(target)} with mark at ${formatUsd(mark)}. Waiting for the next snapshot.` };
    }
    if (isSignalInvalidated(signal.action, mark, invalidation)) {
      return { status: "invalidated", detail: `BUY invalidation accepted below ${formatUsd(invalidation)} with mark at ${formatUsd(mark)}. Waiting for the next snapshot.` };
    }
  }
  if (signal.action === "SELL") {
    if (Number.isFinite(target) && mark <= target) {
      return { status: "target-hit", detail: `Target reached at ${formatUsd(target)} with mark at ${formatUsd(mark)}. Waiting for the next snapshot.` };
    }
    if (isSignalInvalidated(signal.action, mark, invalidation)) {
      return { status: "invalidated", detail: `SELL invalidation accepted above ${formatUsd(invalidation)} with mark at ${formatUsd(mark)}. Waiting for the next snapshot.` };
    }
  }
  return null;
}

function currentSignalMark(price) {
  const displayed = parseDisplayedNumber(els.assetPrice?.textContent);
  if (Number.isFinite(displayed) && displayed > 0) return displayed;
  const mark = Number(price);
  if (Number.isFinite(mark) && mark > 0) return mark;
  const last = Number(state.lastPrice);
  return Number.isFinite(last) && last > 0 ? last : Number.NaN;
}

function signalInvalidationTolerance(invalidation) {
  const value = Math.abs(Number(invalidation));
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.max(value * 0.00005, isXauAsset() ? 0.5 : 0);
}

function isSignalInvalidated(action, mark, invalidation) {
  if (!Number.isFinite(mark) || !Number.isFinite(invalidation)) return false;
  const tolerance = signalInvalidationTolerance(invalidation);
  if (action === "BUY") return mark < invalidation - tolerance;
  if (action === "SELL") return mark > invalidation + tolerance;
  return false;
}

function invalidationInstruction(action, invalidation, plan = null) {
  const detail = plan?.detail ? ` ${plan.detail}` : "";
  if (action === "BUY") return `Invalidate only after acceptance below ${formatUsd(invalidation)}.${detail}`;
  if (action === "SELL") return `Invalidate only after acceptance above ${formatUsd(invalidation)}.${detail}`;
  return "VWAP and market structure are the wait-state guard rails.";
}

function hasStructuralInvalidation(signal, setup, price) {
  const mark = currentSignalMark(price);
  const invalidation = Number(signal.invalidation);
  if (!Number.isFinite(mark) || !Number.isFinite(invalidation)) return false;
  const oppositeStrong =
    (signal.action === "BUY" && setup.direction === "SELL SETUP" && setup.score <= -3) ||
    (signal.action === "SELL" && setup.direction === "BUY SETUP" && setup.score >= 3);
  const priceInvalidated = isSignalInvalidated(signal.action, mark, invalidation);
  return priceInvalidated && oppositeStrong;
}

function snapshotThesis(locked, candidate) {
  const interval = locked.snapshotInterval ? ` on the ${locked.snapshotInterval} snapshot` : "";
  const base = `At ${locked.snapshotTime}, probability favored ${locked.action === "BUY" ? "buyers" : "sellers"}${interval}. Grid, invalidation, and target stay fixed until ${locked.reassessTime}.`;
  if (candidate.action === "WAIT") {
    return `${base} Live framework moved to WAIT, but the active snapshot remains in force until target, invalidation, or expiry.`;
  }
  if (candidate.action !== locked.action && candidate.action !== "WAIT") {
    return `${base} Live data is conflicting now, but structural invalidation has not confirmed.`;
  }
  return base;
}

function formatClock(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function intervalToMs(interval) {
  const value = String(interval || "").trim().toLowerCase();
  const match = value.match(/^(\d+)(m|h|d)$/);
  if (!match) return FALLBACK_SNAPSHOT_LOCK_MS;
  const amount = Number(match[1]);
  const unit = match[2];
  if (!Number.isFinite(amount) || amount <= 0) return FALLBACK_SNAPSHOT_LOCK_MS;
  if (unit === "m") return amount * 60 * 1000;
  if (unit === "h") return amount * 60 * 60 * 1000;
  return amount * 24 * 60 * 60 * 1000;
}

function combinedIntervalsToMs(intervals) {
  const total = intervals
    .map((interval) => intervalToMs(interval))
    .reduce((sum, duration) => sum + duration, 0);
  return total > 0 ? total : FALLBACK_SNAPSHOT_LOCK_MS;
}

function selectedSnapshotInterval() {
  if (isXauAsset()) return `${XAU_PRIMARY_ANALYSIS_INTERVAL} + ${XAU_CONFIRMATION_INTERVAL}`;
  return els.intervalSelect?.value || DEFAULT_VIEW_INTERVAL;
}

function selectedSnapshotLockMs() {
  if (isXauAsset()) return combinedIntervalsToMs(XAU_ANALYSIS_INTERVALS);
  return intervalToMs(selectedSnapshotInterval());
}

function isDashboardPullbackEntry(action, entry, mark) {
  const numericEntry = Number(entry);
  const numericMark = Number(mark);
  if (!Number.isFinite(numericEntry) || numericEntry <= 0 || !Number.isFinite(numericMark) || numericMark <= 0) return false;
  if (action === "BUY") return numericEntry < numericMark;
  if (action === "SELL") return numericEntry > numericMark;
  return false;
}

function plannedDashboardEntry(action, mark, vwap, buyGrid = [], sellGrid = []) {
  if (!["BUY", "SELL"].includes(action)) return Number.NaN;
  const candidates = [
    Number(vwap),
    ...(action === "BUY" ? buyGrid : sellGrid).map((level) => Number(level))
  ].filter((level) => isDashboardPullbackEntry(action, level, mark));
  if (!candidates.length) return Number.NaN;
  return candidates.sort((left, right) => Math.abs(left - mark) - Math.abs(right - mark))[0];
}

function averageTrueRange(rows) {
  if (rows.length < 2) return 0;
  const ranges = rows.slice(1).map((row, index) => {
    const previousClose = rows[index].close;
    return Math.max(row.high - row.low, Math.abs(row.high - previousClose), Math.abs(row.low - previousClose));
  });
  return average(ranges);
}

function lastRealLiquiditySweep(action, entry, rows = state.priceSeries) {
  const numericEntry = Number(entry);
  const recent = rows
    .slice(-80)
    .filter((row) => Number.isFinite(row.high) && Number.isFinite(row.low) && Number.isFinite(row.close));
  if (!["BUY", "SELL"].includes(action) || !Number.isFinite(numericEntry) || numericEntry <= 0 || recent.length < 8) {
    return Number.NaN;
  }
  const swings = [];
  for (let i = 2; i < recent.length - 2; i += 1) {
    const row = recent[i];
    const isHigh = row.high > recent[i - 1].high && row.high > recent[i - 2].high && row.high >= recent[i + 1].high && row.high >= recent[i + 2].high;
    const isLow = row.low < recent[i - 1].low && row.low < recent[i - 2].low && row.low <= recent[i + 1].low && row.low <= recent[i + 2].low;
    if (isHigh) swings.push({ price: row.high, type: "high" });
    if (isLow) swings.push({ price: row.low, type: "low" });
  }
  const side = action === "BUY" ? "low" : "high";
  const structural = swings
    .filter((swing) => swing.type === side)
    .filter((swing) => action === "BUY" ? swing.price < numericEntry : swing.price > numericEntry)
    .at(-1);
  if (structural) return structural.price;
  const lows = recent.map((row) => row.low);
  const highs = recent.map((row) => row.high);
  return action === "BUY" ? Math.min(...lows) : Math.max(...highs);
}

function dynamicInvalidationPlan(action, entry, mark) {
  const numericEntry = Number(entry);
  if (!["BUY", "SELL"].includes(action) || !Number.isFinite(numericEntry) || numericEntry <= 0) {
    return { executable: false, invalidation: Number.NaN, detail: "No valid entry for dynamic invalidation." };
  }
  const rows = state.priceSeries.slice(-80);
  const atr = averageTrueRange(rows.slice(-24));
  const atrPct = Number.isFinite(atr) && atr > 0 ? (atr / numericEntry) * 100 : averageTrueRangePercent(rows.slice(-24));
  const structuralLevel = lastRealLiquiditySweep(action, numericEntry, rows);
  const structuralDistance = Number.isFinite(structuralLevel) ? Math.abs(numericEntry - structuralLevel) : 0;
  const atrDistance = Number.isFinite(atr) && atr > 0 ? atr * 0.25 : numericEntry * 0.001;
  const activeMarket = Math.abs(Number(state.market?.priceChange || 0)) > 0.8 || Math.abs(Number(state.market?.vwapDistance || 0)) > 1.2;
  const spreadAllowance = Math.max(numericEntry * (isCommodityAsset() ? 0.00012 : 0.00008), Number.isFinite(atr) && atr > 0 ? atr * 0.06 : 0);
  const baseBuffer = Math.max(numericEntry * 0.0008, atrDistance);
  const volatileBuffer = Math.max(numericEntry * 0.0012, Number.isFinite(atr) && atr > 0 ? atr * 0.35 : 0);
  const buffer = (activeMarket ? volatileBuffer : baseBuffer) + spreadAllowance;
  const riskDistance = Math.max(structuralDistance + buffer, Number.isFinite(atr) && atr > 0 ? atr * 0.65 : numericEntry * 0.0035);
  const maxReasonableRisk = numericEntry * (activeMarket || isCommodityAsset() ? 0.018 : 0.012);
  const maxManeuverRisk = numericEntry * (activeMarket || isCommodityAsset() ? 0.028 : 0.02);
  const invalidation = action === "BUY" ? numericEntry - riskDistance : numericEntry + riskDistance;
  const wide = riskDistance > numericEntry * 0.006 || riskDistance > Math.max(atr || 0, numericEntry * 0.001) * 1.8;
  const reducedSize = riskDistance > maxReasonableRisk && riskDistance <= maxManeuverRisk;
  const detail = [
    `Structural sweep ${Number.isFinite(structuralLevel) ? formatUsd(structuralLevel) : "unavailable"}`,
    `ATR buffer ${formatUsd(buffer)}`,
    reducedSize
      ? "Maneuver mode: use small lot size, wider stop, same account risk."
      : wide
        ? "Use small lot size, wider stop, same account risk."
        : "ATR-based buffer, not fixed points."
  ].join(" · ");
  return {
    atrPct,
    buffer,
    detail,
    executable: Number.isFinite(invalidation) && invalidation > 0 && riskDistance <= maxManeuverRisk,
    invalidation,
    maxManeuverRisk,
    maxReasonableRisk,
    reducedSize,
    riskDistance,
    structuralLevel,
    wide
  };
}

function buildGeneratedSignal(setup, price, vwap) {
  const setupAction = setup.direction === "BUY SETUP" ? "BUY" : setup.direction === "SELL SETUP" ? "SELL" : "WAIT";
  const atrPct = averageTrueRangePercent(state.priceSeries.slice(-24)) || 0.6;
  const riskPct = Math.max(0.35, Math.min(1.6, atrPct * 1.15));
  const spacingPct = Math.max(0.12, Math.min(0.55, riskPct / 3));
  const mark = Number.isFinite(price) ? price : state.lastPrice;
  const anchor = Number.isFinite(vwap) && vwap > 0 ? vwap : mark;
  const buyGrid = buildGridLevels(anchor, "buy", spacingPct, setupAction);
  const sellGrid = buildGridLevels(anchor, "sell", spacingPct, setupAction);
  const plannedEntry = plannedDashboardEntry(setupAction, mark, vwap, buyGrid, sellGrid);
  const action = setupAction === "WAIT" || !Number.isFinite(plannedEntry) ? "WAIT" : setupAction;
  const entry = action === "WAIT" ? null : plannedEntry;
  const invalidationPlan = dynamicInvalidationPlan(action, entry, mark);
  const actionBlocked = action !== "WAIT" && !invalidationPlan.executable;
  const executableAction = actionBlocked ? "WAIT" : action;
  const executableEntry = actionBlocked ? null : entry;
  const invalidation = executableAction === "WAIT"
    ? Number.isFinite(vwap) ? vwap : mark
    : invalidationPlan.invalidation;
  const target = action === "BUY"
    ? Math.max(entry + invalidationPlan.riskDistance * 1.35, Number.isFinite(vwap) ? vwap : entry)
    : action === "SELL"
      ? Math.min(entry - invalidationPlan.riskDistance * 1.35, Number.isFinite(vwap) ? vwap : entry)
      : Number.isFinite(vwap) ? vwap : mark;
  const bestChecks = setup.checks
    .filter((check) => check.live || Math.abs(check.score) > 0)
    .slice(0, 4)
    .map((check) => `${check.name}: ${check.detail}`);
  return {
    asset: setup.asset,
    action: executableAction,
    confidence: actionBlocked
      ? Math.min(setup.confidence, 25)
      : invalidationPlan.reducedSize
        ? Math.min(setup.confidence, 55)
        : setup.confidence,
    score: setup.score,
    liveChecks: setup.liveChecks,
    checksTotal: setup.checks.length,
    entry: executableEntry,
    invalidation,
    target: actionBlocked ? Number.isFinite(vwap) ? vwap : mark : target,
    buyGrid,
    sellGrid,
    buyGridText: formatGridLevels(buyGrid),
    sellGridText: formatGridLevels(sellGrid),
    entryPlan: executableAction === "WAIT"
      ? setupAction === "WAIT"
        ? "No entry until the framework score clears the setup threshold."
        : actionBlocked
          ? `No trade: dynamic stop is too wide for ${setup.asset}. Use small lot size only if a later setup becomes tradable; otherwise wait for a closer structural sweep or lower ATR.`
          : `No ${setupAction} entry at mark. Wait for a pullback ${setupAction === "BUY" ? "below" : "above"} ${formatUsd(mark)}.`
      : invalidationPlan.reducedSize
        ? `${executableAction} maneuver entry ${formatUsd(executableEntry)}; use small lot size, keep the wider invalidation, and hold account risk constant. First target ${formatUsd(target)}.`
        : `${executableAction} pullback entry ${formatUsd(executableEntry)}; first target ${formatUsd(target)}.`,
    invalidationPlan: executableAction === "WAIT"
      ? actionBlocked
        ? `${invalidationPlan.detail} Stop became unreasonable, so Monatise stays in NO TRADE. If the next valid setup still needs a wide stop, use small lot size.`
        : "VWAP and market structure are the wait-state guard rails."
      : invalidationInstruction(executableAction, invalidation, invalidationPlan),
    buyGridPlan: gridSidePlan("buy", executableAction, setup.asset, buyGrid, setup.scaleAction),
    sellGridPlan: gridSidePlan("sell", executableAction, setup.asset, sellGrid, setup.scaleAction),
    hedgeDirection: setup.hedgeDirection,
    hedgePlan: `${setup.gridPlan} ${setup.hedgePlan}`,
    gridHedge: `Buys ${formatGridLevels(buyGrid)}; sells ${formatGridLevels(sellGrid)}; ${setup.hedgeDirection}`,
    gridHedgePlan: `${setup.gridPlan} ${setup.hedgePlan}`,
    thesis: actionBlocked
      ? `${setup.direction} blocked · dynamic stop too wide · score ${setup.score >= 0 ? "+" : ""}${setup.score}`
      : invalidationPlan.reducedSize
        ? `${setup.direction} maneuver · small lot size · wider stop accepted · score ${setup.score >= 0 ? "+" : ""}${setup.score}`
      : `${setup.direction} · confidence ${setup.confidence}% · score ${setup.score >= 0 ? "+" : ""}${setup.score}`,
    evidence: bestChecks.length ? bestChecks.join(" · ") : "Framework checks are still warming up.",
    time: new Date().toLocaleTimeString()
  };
}

function buildGridLevels(anchor, side, spacingPct, action) {
  if (!Number.isFinite(anchor)) return [];
  const biasShift = action === "BUY" ? 0.35 : action === "SELL" ? -0.35 : 0;
  return [1, 2, 3].map((step) => {
    const direction = side === "buy" ? -1 : 1;
    const pct = spacingPct * (step + (side === "buy" ? -biasShift : biasShift));
    return anchor * (1 + direction * pct / 100);
  });
}

function formatGridLevels(levels) {
  if (!levels.length) return "--";
  return levels.map((level) => formatUsd(level)).join(" / ");
}

function twoSidedGridLevelsText(signal) {
  return `BUY ${formatGridLevels(signal.buyGrid)}; SELL ${formatGridLevels(signal.sellGrid)}`;
}

function setupGridPlan(signal) {
  const levels = twoSidedGridLevelsText(signal);
  if (signal.action === "BUY") {
    return `${levels}. Active BUY idea is wrong only if ${formatUsd(signal.invalidation)} breaks.`;
  }
  if (signal.action === "SELL") {
    return `${levels}. Active SELL idea is wrong only if ${formatUsd(signal.invalidation)} breaks.`;
  }
  return signal.entryPlan;
}

function setupInvalidationPlan(signal) {
  if (signal.action === "BUY") {
    return `One overall invalidation for the setup: the buy idea is wrong only below ${formatUsd(signal.invalidation)}.`;
  }
  if (signal.action === "SELL") {
    return `One overall invalidation for the setup: the sell idea is wrong only above ${formatUsd(signal.invalidation)}.`;
  }
  return "VWAP and market structure are the wait-state guard rails.";
}

function gridSidePlan(side, action, asset, levels, scaleAction) {
  const levelText = formatGridLevels(levels);
  if (action === "WAIT") {
    return side === "buy"
      ? `Rest small ${asset} bids only after VWAP/structure confirms: ${levelText}.`
      : `Rest small ${asset} asks only after VWAP/structure confirms: ${levelText}.`;
  }
  if (action === "BUY") {
    return side === "buy"
      ? `Primary ${asset} grid buys below mark: ${levelText}; ${scaleAction === "average down" ? "average down carefully into researched support" : "add only on controlled pullbacks"}.`
      : `Take-profit ${asset} grid sells above mark: ${levelText}; recycle fills back into lower bids.`;
  }
  return side === "sell"
    ? `Primary ${asset} grid sells above mark: ${levelText}; ${scaleAction === "average up" ? "average up carefully into researched resistance" : "add only into controlled strength"}.`
    : `Cover ${asset} grid buys below mark: ${levelText}; recycle fills back into higher offers.`;
}

function renderTraderMode(signal = state.activeSignal) {
  const accountSize = positiveInputValue(els.traderAccountInput, 1000);
  const riskPct = positiveInputValue(els.traderRiskInput, 1);
  const maxLoss = accountSize * riskPct / 100;
  const action = signal?.action || "WAIT";
  const entry = Number(signal?.entry);
  const invalidation = Number(signal?.invalidation);
  const target = Number(signal?.target);
  const hasSizingInputs = ["BUY", "SELL"].includes(action)
    && Number.isFinite(entry)
    && Number.isFinite(invalidation)
    && Number.isFinite(target)
    && entry > 0
    && invalidation > 0
    && target > 0
    && entry !== invalidation;

  els.traderMaxLoss.textContent = formatUsd(maxLoss);

  if (!hasSizingInputs) {
    els.traderPositionSize.textContent = "--";
    els.traderStopDistance.textContent = "--";
    els.traderRewardRisk.textContent = "--";
    els.traderRiskNote.textContent = "Waiting for an active BUY or SELL snapshot with invalidation.";
    return;
  }

  const stopDistance = Math.abs(entry - invalidation);
  const rewardDistance = Math.abs(target - entry);
  const units = maxLoss / stopDistance;
  const notional = units * entry;
  const rewardRisk = rewardDistance / stopDistance;
  const unitLabel = signal.asset || selectedCoin();
  const unitText = units >= 100
    ? units.toLocaleString(undefined, { maximumFractionDigits: 0 })
    : units.toLocaleString(undefined, { maximumFractionDigits: 4 });

  els.traderPositionSize.textContent = `${unitText} ${unitLabel}`;
  els.traderStopDistance.textContent = formatUsd(stopDistance);
  els.traderRewardRisk.textContent = `${rewardRisk.toFixed(2)}R`;
  els.traderRiskNote.textContent = `${formatUsd(maxLoss)} max loss from ${formatUsd(entry)} entry to ${formatUsd(invalidation)} invalidation. Est. notional ${formatUsd(notional)}.`;
}

function renderGeneratedSignal(signal) {
  state.activeSignal = signal;
  els.signalTimestamp.textContent = signal.snapshotTime
    ? `Snapshot ${signal.snapshotTime} · reassess ${signal.reassessTime}`
    : `Generated ${signal.time}`;
  els.signalState.textContent = signal.stateLabel || (signal.action === "WAIT" ? "watch signal" : "active signal");
  els.signalState.className = `pill ${signal.action === "BUY" ? "positive" : signal.action === "SELL" ? "negative" : signal.status === "invalidated" ? "negative" : ""}`;
  els.signalAsset.textContent = `${signal.asset} generated signal`;
  els.signalAction.textContent = signal.action;
  els.signalAction.className = signal.action === "BUY" ? "positive" : signal.action === "SELL" ? "negative" : "";
  els.signalThesis.textContent = signal.thesis;
  els.signalEntry.textContent = signal.action === "WAIT" ? "--" : "BUY / SELL grid";
  els.signalEntryPlan.textContent = setupGridPlan(signal);
  els.signalInvalidation.textContent = signal.action === "WAIT" ? "VWAP / structure" : formatUsd(signal.invalidation);
  els.signalInvalidationPlan.textContent = setupInvalidationPlan(signal);
  els.signalGridHedge.textContent = signal.action === "WAIT" ? "--" : formatUsd(signal.target);
  els.signalGridHedgePlan.textContent = signal.action === "WAIT"
    ? "No target until a BUY or SELL snapshot is active."
    : `First target locked from snapshot. Hedge: ${signal.hedgeDirection}. ${signal.hedgePlan}`;
  els.signalEvidence.textContent = `${signal.liveChecks} / ${signal.checksTotal} checks`;
  els.signalEvidencePlan.textContent = signal.evidence;
  renderTraderMode(signal);
}

function renderSignalLog() {
  if (!state.signals.length) {
    els.signalLog.innerHTML = `<div class="signal-row"><strong>No signals yet</strong><span>--</span><small>Waiting for the first framework pass.</small></div>`;
    return;
  }
  els.signalLog.innerHTML = state.signals.slice(0, 5).map((signal) => `
    <div class="signal-row">
      <strong class="${signal.action === "BUY" ? "positive" : signal.action === "SELL" ? "negative" : ""}">${signal.action}</strong>
      <span>${signal.asset} · ${signal.snapshotTime || signal.time}</span>
      <small>${signal.thesis} · ${signal.action === "WAIT" ? "setup grid waiting" : twoSidedGridLevelsText(signal)} · invalidation ${signal.action === "WAIT" ? "VWAP / structure" : formatUsd(signal.invalidation)} · target ${formatUsd(signal.target)} · ${signal.hedgeDirection}</small>
    </div>
  `).join("");
}

function setVoiceStatus(text) {
  els.voiceStatus.textContent = text;
}

function elevenHeaders(contentType = "application/json") {
  const headers = { "xi-api-key": state.voice.apiKey };
  if (contentType) headers["Content-Type"] = contentType;
  return headers;
}

function currentSetupSnapshot() {
  return {
    asset: selectedCoin(),
    symbol: selectedPair(),
    price: els.assetPrice.textContent,
    signalAction: els.signalAction.textContent,
    signalEntry: els.signalEntry.textContent,
    signalEntryPlan: els.signalEntryPlan.textContent,
    signalInvalidation: els.signalInvalidation.textContent,
    signalInvalidationPlan: els.signalInvalidationPlan.textContent,
    signalTarget: els.signalGridHedge.textContent,
    signalState: els.signalState.textContent,
    signalTiming: els.signalTimestamp.textContent,
    signalThesis: els.signalThesis.textContent,
    direction: els.setupDirection.textContent,
    confidence: els.setupConfidence.textContent,
    grid: els.gridDirection.textContent,
    gridPlan: els.gridPlan.textContent,
    hedge: els.hedgeDirection.textContent,
    hedgePlan: els.hedgePlan.textContent,
    vwap: els.vwapMetric.textContent,
    vwapSignal: els.vwapSignal.textContent,
    funding: els.fundingAverage.textContent,
    oi: els.openInterest.textContent,
    liquidation: els.liqBias.textContent,
    fearGreed: els.fearGreed.textContent,
    research: els.historySignal.textContent,
    scale: els.scaleAction.textContent,
    checks: els.frameworkChecks.textContent,
    reason: els.setupReason.textContent
  };
}

function answerVoiceQuestion(question) {
  const q = question.toLowerCase();
  const s = currentSetupSnapshot();
  if (!question.trim()) return "Ask me about the current setup, grid, hedge, VWAP, funding, open interest, or liquidation map.";
  if (q.includes("hedge")) {
    return `${s.asset} hedge is ${s.hedge}. ${s.hedgePlan} The current setup is ${s.direction} with ${s.confidence}.`;
  }
  if (q.includes("grid") || q.includes("entry") || q.includes("buy") || q.includes("sell")) {
    return `${s.asset} is showing ${s.direction}. ${s.signalEntryPlan} ${s.signalInvalidationPlan} VWAP is ${s.vwap}, and the framework has ${s.checks} live checks.`;
  }
  if (q.includes("vwap")) {
    return `${s.asset} VWAP read is ${s.vwap}. VWAP position is ${s.vwapSignal}. That is being combined with research, funding, open interest, and liquidations before Monatise labels the setup.`;
  }
  if (q.includes("funding") || q.includes("interest") || q.includes("oi") || q.includes("liquidation")) {
    return `${s.asset} derivatives context: funding average is ${s.funding}, open interest is ${s.oi}, liquidation bias is ${s.liquidation}, and fear and greed is ${s.fearGreed}.`;
  }
  if (q.includes("average") || q.includes("scale") || q.includes("research") || q.includes("history")) {
    return `${s.asset} research signal is ${s.research}. Scale plan says ${s.scale}. The framework reason is: ${s.reason}`;
  }
  return `${s.asset} is currently ${s.direction} with ${s.confidence}. The grid is ${s.grid}, hedge is ${s.hedge}, VWAP is ${s.vwap}, and the active thesis is: ${s.reason}`;
}

function setCopilotStatus(text) {
  els.copilotStatus.textContent = text;
}

function extractOpenAIText(payload) {
  if (payload.output_text) return payload.output_text;
  const chunks = [];
  (payload.output || []).forEach((item) => {
    (item.content || []).forEach((part) => {
      if (part.text) chunks.push(part.text);
    });
  });
  return chunks.join("\n").trim() || "No copilot text returned.";
}

function localCopilotAnswer(question) {
  const clean = question.trim();
  const q = clean.toLowerCase();
  const s = currentSetupSnapshot();
  const isActive = ["BUY", "SELL"].includes(s.signalAction);
  const personalPrefix = `${s.asset} personal read: ${isActive ? `${s.signalAction} snapshot is active` : `${s.direction} is not an active entry yet`}.`;
  const levels = isActive
    ? `${s.signalEntry}: ${s.signalEntryPlan} Invalidation ${s.signalInvalidation}; target ${s.signalTarget}.`
    : `No locked entry/target yet. Wait for an active BUY or SELL snapshot; current guard rail is ${s.signalInvalidation}.`;

  if (q.includes("should i") || q.includes("can i") || q.includes("enter") || q.includes("buy now") || q.includes("sell now")) {
    return [
      personalPrefix,
      levels,
      isActive
        ? `If you choose to act, the invalidation is the line that proves the setup wrong; do not chase beyond the entry zone.`
        : "For you personally, the cleaner action is patience until Monatise prints a locked BUY or SELL snapshot.",
      `Context: ${s.confidence}; ${s.reason}`
    ].join("\n");
  }

  if (q.includes("already in") || q.includes("holding") || q.includes("position") || q.includes("manage")) {
    return [
      personalPrefix,
      levels,
      isActive
        ? `If your position matches ${s.signalAction}, manage around the locked invalidation and first target. If it is opposite, reduce risk or wait for structural invalidation before trusting the flip.`
        : "If you are already in while Monatise is waiting, tighten risk around market structure instead of treating this as a fresh confirmation.",
      `Hedge context: ${s.hedge}. ${s.hedgePlan}`
    ].join("\n");
  }

  if (q.includes("risk") || q.includes("size") || q.includes("lot") || q.includes("capital") || q.includes("account")) {
    const capitalMatch = clean.match(/(?:\$|usd\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)(?:\s*(?:usd|dollars|account|capital))?/i);
    const capital = capitalMatch ? Number(capitalMatch[1].replace(/,/g, "")) : null;
    const riskMatch = clean.match(/([0-9]+(?:\.[0-9]+)?)\s*%/);
    const riskPct = riskMatch ? Number(riskMatch[1]) : 1;
    const riskLine = Number.isFinite(capital) && capital > 0
      ? `At ${riskPct}% risk on ${formatUsd(capital)}, maximum loss budget is ${formatUsd(capital * riskPct / 100)}. Size the trade so entry to invalidation equals that budget or less.`
      : "Use a fixed risk budget first, then size from entry to invalidation. Without account size, I would not guess your lot size.";
    return [
      personalPrefix,
      levels,
      riskLine,
      "This is analysis, not financial advice; keep risk small enough that invalidation can be honored."
    ].join("\n");
  }

  if (q.includes("stop") || q.includes("invalidation") || q.includes("wrong")) {
    return [
      personalPrefix,
      `Invalidation: ${s.signalInvalidation}.`,
      isActive
        ? "That is the fixed line for the current snapshot. Do not move it just because live data wiggles."
        : "There is no active fixed stop yet because the signal is not in BUY/SELL snapshot mode.",
      `Snapshot state: ${s.signalState}; ${s.signalTiming}`
    ].join("\n");
  }

  if (q.includes("target") || q.includes("take profit") || q.includes("tp")) {
    return [
      personalPrefix,
      `Target: ${s.signalTarget}.`,
      isActive
        ? "Treat this as the first target from the locked snapshot; reassess after the snapshot window or if invalidation hits."
        : "No active target is locked yet because the setup is still waiting.",
      `Thesis: ${s.signalThesis}`
    ].join("\n");
  }

  return [
    `${s.asset} copilot: ${s.direction} with ${s.confidence}.`,
    `Signal: ${s.signalAction} · ${levels}`,
    `Grid: ${s.grid}. ${s.gridPlan}`,
    `Hedge: ${s.hedge}. ${s.hedgePlan}`,
    `VWAP: ${s.vwap}; ${s.vwapSignal}. Funding ${s.funding}, OI ${s.oi}, liquidation bias ${s.liquidation}.`,
    clean ? `Your question: ${clean}` : "Ask a personal setup, risk, entry, invalidation, target, or position-management question."
  ].join("\n");
}

async function askOpenAICopilot(question) {
  const clean = question.trim();
  const snapshot = currentSetupSnapshot();
  if (!clean) return "Ask the copilot about setup, grid, hedge, invalidation, risk, VWAP, funding, or open interest.";
  if (!state.copilot.apiKey.trim()) return localCopilotAnswer(clean);

  const started = performance.now();
  const response = await fetch(`${OPENAI_BASE}/v1/responses`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${state.copilot.apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: state.copilot.model.trim() || "gpt-5.5",
      reasoning: { effort: "low" },
      instructions: [
        "You are the Monatise trading copilot inside a dashboard.",
        "Use only the provided dashboard snapshot and question.",
        "Answer the user's individual question directly using the visible signal fields.",
        "When the user asks what they should do, frame the answer as conditional analysis: if they choose to trade, use the displayed entry, invalidation, target, and risk controls.",
        "Do not invent live prices, exchange fills, or execution certainty.",
        "Answer with entry, invalidation, target, setup, grid, hedge, and caution when relevant.",
        "If the dashboard has no active BUY or SELL snapshot, say to wait instead of fabricating a trade.",
        "This is trading analysis, not financial advice."
      ].join(" "),
      input: [
        {
          role: "developer",
          content: `Dashboard snapshot:\n${JSON.stringify(snapshot, null, 2)}`
        },
        {
          role: "user",
          content: clean
        }
      ]
    })
  });
  const ms = Math.round(performance.now() - started);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const payload = await response.json();
  recordTelemetry("AI copilot", "OpenAI", true, ms, state.copilot.model);
  return extractOpenAIText(payload);
}

async function handleCopilotQuestion() {
  const question = els.copilotQuestionInput.value;
  setCopilotStatus(state.copilot.apiKey.trim() ? "Thinking with OpenAI" : "Using local copilot fallback");
  els.copilotAskButton.disabled = true;
  els.copilotAskButton.textContent = "Thinking";
  try {
    const answer = await askOpenAICopilot(question);
    els.copilotAnswer.textContent = answer;
    pushLiveAlert({
      kind: "ai copilot",
      asset: selectedCoin(),
      title: `${selectedCoin()} AI copilot response`,
      detail: answer.slice(0, 260),
      payload: { question, answer }
    });
    setCopilotStatus(state.copilot.apiKey.trim() ? "OpenAI copilot complete" : "Local copilot complete");
  } catch (error) {
    recordTelemetry("AI copilot", "OpenAI", false, 0, error.message);
    els.copilotAnswer.textContent = localCopilotAnswer(question);
    setCopilotStatus(`OpenAI copilot failed · ${error.message}`);
  } finally {
    els.copilotAskButton.disabled = false;
    els.copilotAskButton.textContent = "Ask";
  }
}

async function transcribeWithElevenLabs(blob) {
  const started = performance.now();
  const form = new FormData();
  form.append("model_id", "scribe_v2");
  form.append("file", blob, "monatise-question.webm");
  const response = await fetch(`${ELEVEN_BASE}/v1/speech-to-text`, {
    method: "POST",
    headers: { "xi-api-key": state.voice.apiKey },
    body: form
  });
  const ms = Math.round(performance.now() - started);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const data = await response.json();
  recordTelemetry("Voice transcript", "ElevenLabs", true, ms);
  return data.text || "";
}

async function speakWithElevenLabs(text) {
  const voiceId = state.voice.voiceId.trim();
  if (!voiceId) throw new Error("Voice ID required");
  const started = performance.now();
  const response = await fetch(`${ELEVEN_BASE}/v1/text-to-speech/${encodeURIComponent(voiceId)}?output_format=mp3_44100_128`, {
    method: "POST",
    headers: elevenHeaders(),
    body: JSON.stringify({
      text,
      model_id: "eleven_multilingual_v2"
    })
  });
  const ms = Math.round(performance.now() - started);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const audioBlob = await response.blob();
  if (state.voice.audioUrl) URL.revokeObjectURL(state.voice.audioUrl);
  state.voice.audioUrl = URL.createObjectURL(audioBlob);
  els.voiceAudio.src = state.voice.audioUrl;
  recordTelemetry("Voice response", "ElevenLabs", true, ms);
  await els.voiceAudio.play().catch(() => undefined);
}

async function handleVoiceQuestion(question) {
  const clean = question.trim();
  els.voiceTranscript.textContent = clean || "No question detected.";
  const answer = answerVoiceQuestion(clean);
  els.voiceAnswer.textContent = answer;
  pushLiveAlert({
    kind: "voice query",
    asset: selectedCoin(),
    title: `${selectedCoin()} voice response`,
    detail: answer,
    payload: { question: clean, answer }
  });
  if (!state.voice.apiKey.trim()) {
    setVoiceStatus("Text response mode");
    return;
  }
  setVoiceStatus("Speaking with ElevenLabs");
  try {
    await speakWithElevenLabs(answer);
    setVoiceStatus("Voice response complete");
  } catch (error) {
    recordTelemetry("Voice response", "ElevenLabs", false, 0, error.message);
    setVoiceStatus(`ElevenLabs speech failed · ${error.message}`);
  }
}

async function startVoiceRecording() {
  if (!state.voice.apiKey.trim()) {
    setVoiceStatus("Use typed questions or connect ElevenLabs");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setVoiceStatus("Browser recording is unavailable");
    return;
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  state.voice.chunks = [];
  const recorder = new MediaRecorder(stream);
  state.voice.recorder = recorder;
  state.voice.recording = true;
  els.voiceRecordButton.textContent = "Recording";
  setVoiceStatus("Listening");
  recorder.ondataavailable = (event) => {
    if (event.data.size) state.voice.chunks.push(event.data);
  };
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    state.voice.recording = false;
    els.voiceRecordButton.textContent = "Record";
    const blob = new Blob(state.voice.chunks, { type: recorder.mimeType || "audio/webm" });
    setVoiceStatus("Transcribing with ElevenLabs");
    try {
      const transcript = await transcribeWithElevenLabs(blob);
      els.voiceQuestionInput.value = transcript;
      await handleVoiceQuestion(transcript);
    } catch (error) {
      recordTelemetry("Voice transcript", "ElevenLabs", false, 0, error.message);
      setVoiceStatus(`ElevenLabs transcript failed · ${error.message}`);
    }
  };
  recorder.start();
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

function currentCoinGlassKey() {
  return (els.apiKeyInput?.value || state.apiKey || "").trim();
}

function syncCoinGlassKey(message = "") {
  state.apiKey = currentCoinGlassKey();
  localStorage.setItem(API_KEY_STORAGE, state.apiKey);
  updateCoinGlassSourceStatus(message || (state.apiKey ? "CoinGlass local override saved." : ""));
}

function cgHeaders() {
  const headers = { accept: "application/json" };
  const key = currentCoinGlassKey();
  if (key) headers["X-CG-API-KEY"] = key;
  return headers;
}

function hasKey() {
  return state.serverCoinGlassReady || currentCoinGlassKey().length > 0;
}

function requireCoinGlass(label) {
  if (!hasKey()) throw new Error(`CoinGlass connection required for ${label}`);
}

async function loadOperatorStatus() {
  try {
    const response = await fetch("/api/operator", { cache: "no-store" });
    if (!response.ok) throw new Error("operator unavailable");
    state.operator = await response.json();
    state.serverCoinGlassReady = Boolean(state.operator?.integrations?.coinglass?.configured);
  } catch {
    state.operator = null;
    state.serverCoinGlassReady = false;
  }
  updateCoinGlassSourceStatus();
}

function selectedAsset() {
  return ASSETS[els.assetSelect.value] || ASSETS.BTC;
}

function populateAssetSelect() {
  const current = els.assetSelect.value || "BTC";
  els.assetSelect.innerHTML = ASSET_DEFINITIONS.map((asset) => (
    `<option value="${asset.coin}">${asset.coin}</option>`
  )).join("");
  els.assetSelect.value = ASSETS[current] ? current : "BTC";
}

function selectedCoin() {
  return selectedAsset().coin;
}

function selectedPair() {
  return selectedAsset().pair;
}

function isXauAsset(asset = selectedAsset()) {
  return ["GOLD", "XAU"].includes(asset.coin);
}

function usesServerMarketCandles(asset = selectedAsset()) {
  return ["GOLD", "XAU", "CL", "BRENTOIL"].includes(asset.coin);
}

function syncAssetLabels() {
  const asset = selectedAsset();
  els.dashboardTitle.textContent = `${asset.coin} Market Dashboard`;
  els.marketSymbol.textContent = asset.pair;
  els.headerMarketSymbol.textContent = asset.pair;
  els.pricePanelTitle.textContent = `${asset.coin} Live Candles`;
  els.setupAsset.textContent = `${asset.coin} setup`;
  updateCoinGlassSourceStatus();
  syncTradingView(asset);
}

function assetMatches(query) {
  const clean = query.trim().toUpperCase();
  if (!clean) return ASSET_DEFINITIONS.slice(0, 18);
  return ASSET_DEFINITIONS.filter((asset) => (
    asset.coin.includes(clean) ||
    asset.pair.includes(clean) ||
    asset.tv.toUpperCase().includes(clean) ||
    String(asset.search || "").toUpperCase().includes(clean)
  )).slice(0, 24);
}

function renderAssetSearch() {
  if (!els.assetSearchResults) return;
  const matches = assetMatches(els.assetSearchInput.value);
  els.assetSearchResults.innerHTML = matches.length
    ? matches.map((asset) => `
        <button type="button" data-asset-search="${asset.coin}">
          <strong>${asset.coin}</strong>
          <small>${asset.pair}</small>
        </button>
      `).join("")
    : `<button type="button" disabled><strong>No match</strong><small>Try GOLD, XAU, EURUSD, BTC</small></button>`;
  els.assetSearchResults.classList.toggle("open", Boolean(els.assetSearchInput.value.trim()));
}

function chooseAsset(coin) {
  if (!ASSETS[coin]) return;
  els.assetSelect.value = coin;
  if (els.assetSearchInput) els.assetSearchInput.value = "";
  els.assetSearchResults?.classList.remove("open");
  resetMarketContext();
  state.lastPrice = null;
  state.priceSeries = [];
  els.assetPrice.textContent = "$--";
  els.headerAssetPrice.textContent = "$--";
  els.priceChange.textContent = "Loading";
  els.priceChange.className = "";
  els.headerPriceChange.textContent = "Loading";
  els.headerPriceChange.className = "";
  setLockedSignal(null);
  state.realtime.lastSetup = null;
  state.realtime.lastEntrySignal = null;
  state.realtime.lastGridCompletion = null;
  refreshDashboard();
}

function updateCoinGlassSourceStatus(message = "") {
  const asset = selectedAsset();
  const exchange = els.exchangeSelect.value;
  const viewInterval = els.intervalSelect.value || DEFAULT_VIEW_INTERVAL;
  const localKey = currentCoinGlassKey();
  const serverReady = Boolean(state.serverCoinGlassReady);
  const ready = serverReady || localKey.length > 0;
  const sourceBand = document.querySelector(".source-band");
  sourceBand?.classList.toggle("ready", ready);
  sourceBand?.classList.toggle("waiting", !ready);
  els.coinGlassStatus.textContent = serverReady ? "Server connected" : localKey ? "Local key saved" : "Connection required";
  els.coinGlassStatusDetail.textContent = ready
    ? message || (serverReady
      ? `Render provides the CoinGlass connection${state.operator?.integrations?.coinglass?.exchange ? ` via ${state.operator.integrations.coinglass.exchange}` : ""}. Local key override is optional.`
      : "CoinGlass local key is saved for this browser.")
    : "CoinGlass is not connected. Add a local key only if the server integration is unavailable.";
  els.coinGlassPriceRef.textContent = usesServerMarketCandles(asset)
    ? `${asset.tv} · Monatise market candles`
    : `${asset.pair} · CoinGlass futures price history`;
  els.coinGlassRouteRef.textContent = usesServerMarketCandles(asset)
    ? `/api/candles · symbol ${asset.coin} · ${isXauAsset(asset) ? `analysis ${XAU_ANALYSIS_INTERVALS.join(" + ")}` : `view ${viewInterval}`}`
    : `/api/futures/price/history · exchange ${exchange} · analysis ${ANALYSIS_INTERVAL} · view ${viewInterval}`;
  els.openIntegrationsButton.textContent = serverReady ? "CoinGlass Connected" : localKey ? "Update Local Key" : "Add Local Key";
}

function syncTradingView(asset = selectedAsset()) {
  const intervalMap = { "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D" };
  const interval = intervalMap[els.intervalSelect.value] || "60";
  const symbol = asset.tv;
  const chartUrl = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}`;
  const embedUrl = `https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent(symbol)}&interval=${interval}&theme=dark&style=1&hide_side_toolbar=0&allow_symbol_change=0&save_image=0&studies=VWAP%40tv-basicstudies`;
  els.tradingViewSource.textContent = `${symbol} · ${els.intervalSelect.value}`;
  els.tradingViewLink.href = chartUrl;
  if (els.tradingViewFrame.src !== embedUrl) {
    els.tradingViewFrame.src = embedUrl;
  }
}

function resetMarketContext() {
  state.market = {
    priceChange: 0,
    fundingAverage: null,
    oiChange: null,
    liquidationBias: null,
    liquidationLevels: [],
    liquiditySource: "",
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
    pattern: null,
    indicatorScore: 0,
    indicatorSummary: "",
    indicatorRows: [],
    analysisFrame: ""
  };
}

async function fetchServerMarketCandles(asset, interval, limit = "96") {
  const params = new URLSearchParams({
    symbol: asset.coin,
    interval,
    limit
  });
  const payload = await timedFetch(
    `${asset.coin} ${interval} market candles`,
    "Monatise market feed",
    `/api/candles?${params}`,
    {}
  );
  const rows = (Array.isArray(payload.candles) ? payload.candles : []).map((row) => ({
    time: Number(row.time ?? row.timestamp),
    open: Number(row.open ?? row.close),
    close: Number(row.close),
    high: Number(row.high),
    low: Number(row.low),
    volume: Number(row.volume ?? 0)
  })).filter((row) => Number.isFinite(row.close) && Number.isFinite(row.high) && Number.isFinite(row.low));
  if (!rows.length) throw new Error(`${asset.coin} ${interval} market feed returned no candle rows`);
  rows.source = payload.source || "Monatise market feed";
  rows.interval = payload.interval || interval;
  return rows;
}

async function getPriceForAsset(asset, limit = "96") {
  if (usesServerMarketCandles(asset)) {
    if (isXauAsset(asset)) {
      const [primaryRows, confirmationRows] = await Promise.all([
        fetchServerMarketCandles(asset, XAU_PRIMARY_ANALYSIS_INTERVAL, limit),
        fetchServerMarketCandles(asset, XAU_CONFIRMATION_INTERVAL, "180")
      ]);
      primaryRows.multiTimeframe = {
        primary: XAU_PRIMARY_ANALYSIS_INTERVAL,
        confirmation: XAU_CONFIRMATION_INTERVAL,
        series: {
          [XAU_PRIMARY_ANALYSIS_INTERVAL]: primaryRows,
          [XAU_CONFIRMATION_INTERVAL]: confirmationRows
        }
      };
      primaryRows.source = primaryRows.source || confirmationRows.source || "Monatise market feed";
      primaryRows.interval = `${XAU_PRIMARY_ANALYSIS_INTERVAL} + ${XAU_CONFIRMATION_INTERVAL}`;
      return primaryRows;
    }
    return fetchServerMarketCandles(asset, els.intervalSelect.value || DEFAULT_VIEW_INTERVAL, limit);
  }
  const exchange = els.exchangeSelect.value;
  const interval = ANALYSIS_INTERVAL;
  requireCoinGlass(`${asset.coin} price history`);
  const params = new URLSearchParams({
    exchange,
    symbol: asset.pair,
    interval,
    limit
  });
  const payload = await timedFetch(
    `${asset.coin} price`,
    "CoinGlass",
    `${CG_BASE}/api/futures/price/history?${params}`,
    { headers: cgHeaders() }
  );
  const rows = (Array.isArray(payload.data) ? payload.data : []).map((row) => ({
    time: Number(row.time),
    open: Number(row.open ?? row.close),
    close: Number(row.close),
    high: Number(row.high),
    low: Number(row.low),
    volume: Number(row.volume_usd)
  })).filter((row) => Number.isFinite(row.close) && Number.isFinite(row.high) && Number.isFinite(row.low));
  if (!rows.length) throw new Error(`CoinGlass returned no ${asset.coin} price rows`);
  return rows;
}

async function getPrice() {
  const asset = selectedAsset();
  const exchange = els.exchangeSelect.value;
  const interval = ANALYSIS_INTERVAL;
  const rows = await getPriceForAsset(asset);
  els.priceSource.textContent = usesServerMarketCandles(asset)
    ? `${rows.source || "Monatise market feed"} · ${asset.tv} · ${isXauAsset(asset) ? "15m structure + 5m execution candles" : `${rows.interval || els.intervalSelect.value || DEFAULT_VIEW_INTERVAL} TradingView-aligned candles`}`
    : `CoinGlass futures price history · ${asset.pair} · ${exchange} · analysis ${interval} · view ${els.intervalSelect.value || DEFAULT_VIEW_INTERVAL}`;
  return rows;
}

function monitorAssetKeys() {
  const selected = selectedCoin();
  const keys = ASSET_DEFINITIONS.map((asset) => asset.coin);
  return [selected, ...keys.filter((coin) => coin !== selected)];
}

function renderMonitorGrid() {
  if (!els.monitorGrid) return;
  const results = Object.values(state.monitor.results)
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, 36);
  els.monitorGrid.innerHTML = results.length
    ? results.map((item) => {
        const pct = Number(item.changePct);
        const className = item.error ? "error" : pct > 0 ? "positive" : pct < 0 ? "negative" : "";
        return `
          <button type="button" class="monitor-card ${className}" data-monitor-asset="${item.coin}">
            <span>${item.pair}</span>
            <strong>${item.price || "$--"}</strong>
            <small>${item.error ? item.error : `${formatPercent(pct || 0, 2)} · ${item.direction}`}</small>
          </button>
        `;
      }).join("")
    : `<article class="monitor-card"><span>Scanner idle</span><strong>--</strong><small>CoinGlass connection starts autonomous monitoring.</small></article>`;
}

async function refreshAutonomousMonitor() {
  if (!els.monitorStatus || state.monitor.scanning) return;
  if (!hasKey()) {
    els.monitorStatus.textContent = "Connect CoinGlass to autonomously scan supported futures assets";
    renderMonitorGrid();
    return;
  }
  state.monitor.scanning = true;
  const keys = monitorAssetKeys();
  const batchSize = 8;
  const start = state.monitor.cursor % keys.length;
  const batch = Array.from({ length: batchSize }, (_, index) => keys[(start + index) % keys.length]);
  state.monitor.cursor = (start + batchSize) % keys.length;
  els.monitorStatus.textContent = `Scanning ${batch.join(", ")} · ${keys.length} assets in rotation`;
  const settled = await Promise.allSettled(batch.map(async (coin) => {
    const asset = ASSETS[coin];
    const rows = await getPriceForAsset(asset, "32");
    const last = rows.at(-1);
    const prior = rows.at(-2) || rows[0];
    const changePct = prior?.close ? ((last.close - prior.close) / prior.close) * 100 : 0;
    state.monitor.results[coin] = {
      coin,
      pair: asset.pair,
      price: formatUsd(last.close),
      changePct,
      direction: changePct > 0.12 ? "bid lifting" : changePct < -0.12 ? "offer pressure" : "range",
      updatedAt: Date.now()
    };
  }));
  settled.forEach((result, index) => {
    if (result.status === "rejected") {
      const coin = batch[index];
      const asset = ASSETS[coin];
      state.monitor.results[coin] = {
        coin,
        pair: asset.pair,
        error: result.reason?.message || "unavailable",
        updatedAt: Date.now()
      };
    }
  });
  state.monitor.lastRun = Date.now();
  state.monitor.scanning = false;
  els.monitorStatus.textContent = `Autonomous scan active · ${Object.keys(state.monitor.results).length}/${keys.length} assets checked · last ${new Date(state.monitor.lastRun).toLocaleTimeString()}`;
  renderMonitorGrid();
}

async function getFunding() {
  const asset = selectedAsset();
  requireCoinGlass(`${asset.coin} funding`);
  const payload = await timedFetch(
    "Funding rate",
    "CoinGlass",
    `${CG_BASE}/api/futures/funding-rate/exchange-list`,
    { headers: cgHeaders() }
  );
  const coin = (payload.data || []).find((item) => item.symbol === asset.coin);
  const stable = coin?.stablecoin_margin_list || [];
  return stable.slice().sort((a, b) => Math.abs(b.funding_rate) - Math.abs(a.funding_rate)).slice(0, 8);
}

async function getOpenInterest() {
  const asset = selectedAsset();
  requireCoinGlass(`${asset.coin} open interest`);
  const payload = await timedFetch(
    "Open interest",
    "CoinGlass",
    `${CG_BASE}/api/futures/open-interest/exchange-list?symbol=${asset.coin}`,
    { headers: cgHeaders() }
  );
  return (payload.data || []).slice(0, 8);
}

async function getLiquidations() {
  const asset = selectedAsset();
  requireCoinGlass(`${asset.coin} liquidation map`);
  const range = els.liqRangeSelect.value;
  const mapUrls = [
    `${CG_BASE}/api/futures/liquidation/aggregated-map?symbol=${asset.pair}&range=${range}`,
    `${CG_BASE}/api/futures/liquidation/aggregated-map?symbol=${asset.coin}&range=${range}`
  ];
  const painPromise = timedFetch(
    "Liquidation max pain",
    "CoinGlass",
    `${CG_BASE}/api/futures/liquidation/max-pain?range=24h`,
    { headers: cgHeaders() }
  );
  const mapErrors = [];
  let levels = [];
  let mapSymbol = asset.pair;
  for (const url of mapUrls) {
    try {
      const payload = await timedFetch("Liquidation map", "CoinGlass", url, { headers: cgHeaders() });
      const shapeSummary = summarizeLiquidationPayload(payload);
      document.body.dataset.liqShape = shapeSummary.label;
      const payloadError = coinGlassPayloadError(payload);
      if (payloadError) {
        const symbol = new URL(url, window.location.origin).searchParams.get("symbol") || asset.pair;
        mapErrors.push(`${symbol}: ${payloadError}`);
        continue;
      }
      levels = parseLiquidationMap(payload);
      mapSymbol = new URL(url, window.location.origin).searchParams.get("symbol") || mapSymbol;
      if (levels.length) break;
      mapErrors.push(`${mapSymbol}: no price levels`);
    } catch (error) {
      mapErrors.push(error.message);
    }
  }
  const painPayload = await Promise.resolve(painPromise).then(
    (value) => ({ status: "fulfilled", value }),
    (reason) => ({ status: "rejected", reason })
  );
  const assetPain = painPayload.status === "fulfilled"
    ? (painPayload.value.data || []).find((item) => item.symbol === asset.coin)
    : null;
  if (!levels.length && mapErrors.length) {
    const shape = document.body.dataset.liqShape || "unknown payload";
    throw new Error(`CoinGlass liquidation map returned no price levels (${mapErrors.join("; ")}; shape ${shape})`);
  }
  return { levels, assetPain, mapSymbol };
}

async function getFearGreed() {
  requireCoinGlass("fear and greed history");
  const payload = await timedFetch(
    "Fear and greed",
    "CoinGlass",
    `${CG_BASE}/api/index/fear-greed-history`,
    { headers: cgHeaders() }
  );
  const first = Array.isArray(payload.data) ? payload.data[0] : null;
  const values = first?.data_list || [];
  const times = first?.time_list || [];
  const rows = values.map((value, index) => ({ value: Number(value), time: Number(times[index]) * 1000 })).filter((row) => Number.isFinite(row.value));
  if (!rows.length) throw new Error("CoinGlass returned no fear and greed rows");
  els.fgSource.textContent = "CoinGlass crypto fear and greed history";
  return rows;
}

async function getNews() {
  requireCoinGlass("news alerts");
  const end = Date.now();
  const start = end - 1000 * 60 * 60 * 24 * 3;
  const params = new URLSearchParams({
    start_time: String(start),
    end_time: String(end),
    language: "en",
    page: "1",
    per_page: "8"
  });
  const payload = await timedFetch("News alerts", "CoinGlass", `${CG_BASE}/api/article/list?${params}`, { headers: cgHeaders() });
  return (payload.data || []).slice(0, 8);
}

async function getHyperliquidContext() {
  const asset = selectedAsset();
  const hyperNames = [asset.hyper, ...(asset.hyperAliases || [])].filter(Boolean);
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
  const index = universe.findIndex((item) => hyperNames.includes(item.name));
  if (index < 0 || !contexts[index]) {
    throw new Error(`${hyperNames.join(" / ") || asset.coin} not listed on Hyperliquid`);
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

async function getHyperliquidBookLiquidity() {
  const asset = selectedAsset();
  if (!asset.hyper) throw new Error(`${asset.coin} is not mapped to a Hyperliquid market`);
  const payload = await timedFetch(
    `${asset.coin} Hyperliquid book`,
    "Hyperliquid public",
    HYPER_BASE,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "l2Book", coin: asset.hyper })
    }
  );
  const [bids = [], asks = []] = payload?.levels || [];
  const toLevel = (row, side) => {
    const price = Number(row.px);
    const size = Number(row.sz);
    if (!Number.isFinite(price) || !Number.isFinite(size) || price <= 0 || size <= 0) return null;
    return {
      level: price * size,
      price,
      side,
      source: "Hyperliquid order book"
    };
  };
  const levels = [
    ...bids.slice(0, 20).map((row) => toLevel(row, "bid")),
    ...asks.slice(0, 20).map((row) => toLevel(row, "ask"))
  ].filter(Boolean);
  if (!levels.length) throw new Error("Hyperliquid order book returned no depth levels");
  return { levels, mapSymbol: `${asset.hyper}-PERP`, source: "Hyperliquid order book" };
}

function parseLiquidationMap(payload) {
  const raw = payload?.data?.data || payload?.data || {};
  const entries = [];
  const addLevel = (row) => {
    if (Array.isArray(row)) {
      const price = Number(row[0]);
      const level = row.slice(1).reduce((sum, value) => {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? sum + numeric : sum;
      }, 0);
      if (Number.isFinite(price) && Number.isFinite(level)) entries.push({ price, level });
      return;
    }
    if (!row || typeof row !== "object") return;
    const price = firstFinite(row, [
      "price",
      "liq_price",
      "liquidation_price",
      "price_level",
      "bin",
      "x"
    ]);
    const level = firstFinite(row, [
      "liquidation_usd",
      "liquidationUsd",
      "liq_usd",
      "liqUsd",
      "amount_usd",
      "amountUsd",
      "value",
      "vol_usd",
      "volume_usd",
      "total",
      "y",
      "long_liquidation_usd",
      "short_liquidation_usd"
    ]);
    const longLevel = firstFinite(row, ["long_liquidation_usd", "longLiquidationUsd", "long_liq_usd", "longLiqUsd"]);
    const shortLevel = firstFinite(row, ["short_liquidation_usd", "shortLiquidationUsd", "short_liq_usd", "shortLiqUsd"]);
    const combined = Number.isFinite(longLevel) || Number.isFinite(shortLevel)
      ? (Number.isFinite(longLevel) ? longLevel : 0) + (Number.isFinite(shortLevel) ? shortLevel : 0)
      : level;
    if (Number.isFinite(price) && Number.isFinite(combined)) entries.push({ price, level: combined });
  };
  const addMatrixLevels = (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const priceAxis = firstNumericArray(value, [
      "prices",
      "price_list",
      "priceList",
      "price_axis",
      "priceAxis",
      "y_axis",
      "yAxis",
      "y"
    ]);
    if (!priceAxis.length) return false;
    const matrix = firstArray(value, [
      "heatmap",
      "liq_map",
      "liqMap",
      "liquidation_map",
      "liquidationMap",
      "liquidation_list",
      "liquidationList",
      "values",
      "series",
      "data"
    ]);
    if (!Array.isArray(matrix) || !matrix.length) return false;
    let added = 0;
    matrix.forEach((row, rowIndex) => {
      if (!Array.isArray(row)) return;
      if (row.length >= 3) {
        const priceIndex = Number(row[1]);
        const price = Number.isInteger(priceIndex) && priceAxis[priceIndex] != null ? priceAxis[priceIndex] : Number(row[0]);
        const level = row.slice(2).reduce((sum, value) => {
          const numeric = Number(value);
          return Number.isFinite(numeric) && numeric > 0 ? sum + numeric : sum;
        }, 0);
        if (Number.isFinite(price) && level > 0) {
          entries.push({ price, level });
          added += 1;
        }
        return;
      }
      if (row.length === priceAxis.length) {
        row.forEach((value, index) => {
          const price = priceAxis[index];
          const level = Number(value);
          if (Number.isFinite(price) && Number.isFinite(level) && level > 0) {
            entries.push({ price, level });
            added += 1;
          }
        });
        return;
      }
      const price = priceAxis[rowIndex];
      const level = row.reduce((sum, value) => {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0 ? sum + numeric : sum;
      }, 0);
      if (Number.isFinite(price) && level > 0) {
        entries.push({ price, level });
        added += 1;
      }
    });
    return added > 0;
  };
  const visit = (value) => {
    if (!value) return;
    if (Array.isArray(value)) {
      if (value.length >= 2 && value.every((item) => typeof item !== "object" || item === null)) {
        addLevel(value);
        return;
      }
      value.forEach(visit);
      return;
    }
    if (typeof value === "object") {
      if (addMatrixLevels(value)) return;
      addLevel(value);
      Object.entries(value).forEach(([key, child]) => {
        const numericKey = Number(key);
        if (Number.isFinite(numericKey) && Array.isArray(child)) {
          child.forEach((level) => addLevel([numericKey, Array.isArray(level) ? level[1] ?? level[0] : level]));
        } else {
          visit(child);
        }
      });
    }
  };
  visit(raw);
  const byPrice = new Map();
  entries.forEach((row) => {
    const rounded = Math.round(row.price * 100) / 100;
    byPrice.set(rounded, (byPrice.get(rounded) || 0) + Math.max(0, row.level));
  });
  return Array.from(byPrice, ([price, level]) => ({ price, level }))
    .filter((row) => row.level > 0)
    .sort((a, b) => a.price - b.price);
}

function firstFinite(row, keys) {
  for (const key of keys) {
    const value = Number(row[key]);
    if (Number.isFinite(value)) return value;
  }
  return NaN;
}

function firstNumericArray(row, keys) {
  for (const key of keys) {
    const value = row[key];
    if (!Array.isArray(value)) continue;
    const numbers = value.map(Number).filter(Number.isFinite);
    if (numbers.length) return numbers;
  }
  return [];
}

function firstArray(row, keys) {
  for (const key of keys) {
    if (Array.isArray(row[key])) return row[key];
  }
  return [];
}

function coinGlassPayloadError(payload) {
  const code = payload?.code;
  if (code == null || ["0", "200"].includes(String(code))) return "";
  return `CoinGlass code ${code}: ${payload?.msg || payload?.message || "request returned no data"}`;
}

function summarizeLiquidationPayload(payload) {
  const seen = new Set();
  const parts = [];
  const walk = (value, path = "root", depth = 0) => {
    if (parts.length > 12 || depth > 3 || value == null) return;
    if (Array.isArray(value)) {
      parts.push(`${path}:array(${value.length})`);
      if (value.length) walk(value[0], `${path}[0]`, depth + 1);
      return;
    }
    if (typeof value !== "object" || seen.has(value)) return;
    seen.add(value);
    const keys = Object.keys(value).slice(0, 12);
    parts.push(`${path}:{${keys.join(",")}}`);
    keys.slice(0, 8).forEach((key) => walk(value[key], `${path}.${key}`, depth + 1));
  };
  walk(payload);
  return { label: parts.join(" > ") };
}

function renderPrice(series) {
  const asset = selectedAsset();
  if (isXauAsset(asset) && series.multiTimeframe) {
    renderXauMultiTimeframePrice(series, asset);
    return;
  }
  state.priceSeries = series;
  const last = series.at(-1);
  const previous = series.at(-2);
  if (!last) return;
  state.lastPrice = last.close;
  const change = previous ? ((last.close - previous.close) / previous.close) * 100 : 0;
  state.market.priceChange = change;
  updateTopPrice(last.close, `${change >= 0 ? "Up" : "Down"} ${formatPercent(change, 2)}`);
  els.priceChange.textContent = `${change >= 0 ? "Up" : "Down"} ${formatPercent(change, 2)} last candle`;
  els.priceChange.className = change >= 0 ? "positive" : "negative";
  els.headerPriceChange.className = change >= 0 ? "positive" : "negative";
  els.pricePulse.textContent = "live";
  updateCoinGlassSourceStatus(`Live CoinGlass price ${formatUsd(last.close)} · ${series.length} candles loaded.`);
  const research = studyHistoricalPattern(series);
  renderResearch(research);
  const structure = analyzeMarketStructure(series, research);
  const indicatorStack = analyzeIndicatorStack(series, research, structure);
  renderIndicatorStack(indicatorStack);
  renderStructureSummary(structure);
  drawStructureChart(els.priceCanvas, series, structure, research);
}

function latestCandle(series) {
  return Array.isArray(series) ? series.at(-1) : null;
}

function scoreDirection(score) {
  const value = Number(score);
  if (value > 0) return 1;
  if (value < 0) return -1;
  return 0;
}

function signalFromScore(score) {
  const direction = scoreDirection(score);
  return direction > 0 ? "BUY" : direction < 0 ? "SELL" : "WAIT";
}

function finiteScore(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function mergeXauIndicatorStack(primaryStack, confirmationStack, primaryResearch, confirmationResearch) {
  const primaryDirection = scoreDirection(finiteScore(primaryStack.score) || finiteScore(primaryResearch.score));
  const confirmationDirection = scoreDirection(finiteScore(confirmationStack.score) || finiteScore(confirmationResearch.score));
  const aligned = primaryDirection !== 0 && primaryDirection === confirmationDirection;
  const conflict = primaryDirection !== 0 && confirmationDirection !== 0 && primaryDirection !== confirmationDirection;
  const rawScore = finiteScore(primaryStack.score) + finiteScore(confirmationStack.score) + (aligned ? primaryDirection : conflict ? -primaryDirection : 0);
  const score = clampScore(rawScore, -3, 3);
  const bias = signalFromScore(score);
  const rows = [
    {
      name: `${XAU_PRIMARY_ANALYSIS_INTERVAL} structure`,
      signal: signalFromScore(primaryStack.score),
      score: clampScore(primaryStack.score, -2, 2),
      detail: `${primaryStack.summary} · ${primaryResearch.signal} · ${primaryResearch.vwapSignal}`
    },
    {
      name: `${XAU_CONFIRMATION_INTERVAL} execution`,
      signal: signalFromScore(confirmationStack.score),
      score: clampScore(confirmationStack.score, -2, 2),
      detail: `${confirmationStack.summary} · ${confirmationResearch.signal} · ${confirmationResearch.vwapSignal}`
    },
    {
      name: "15m/5m alignment",
      signal: aligned ? `${bias} ALIGNED` : conflict ? "CONFLICT" : "WAIT",
      score: aligned ? primaryDirection : conflict ? -primaryDirection : 0,
      detail: aligned ? "5m confirms the 15m XAU/USD setup." : conflict ? "5m is fighting the 15m structure; reduce conviction." : "One timeframe is neutral."
    },
    ...primaryStack.rows.slice(0, 4).map((row) => ({ ...row, name: `15m ${row.name}` })),
    ...confirmationStack.rows.slice(0, 4).map((row) => ({ ...row, name: `5m ${row.name}` }))
  ];
  return {
    score,
    summary: `XAU/USD 15m + 5m ${bias} stack ${score >= 0 ? "+" : ""}${score}`,
    rows
  };
}

function renderXauMultiTimeframePrice(series, asset) {
  const frames = series.multiTimeframe.series || {};
  const primarySeries = frames[XAU_PRIMARY_ANALYSIS_INTERVAL] || series;
  const confirmationSeries = frames[XAU_CONFIRMATION_INTERVAL] || [];
  state.priceSeries = primarySeries;

  const primaryLast = latestCandle(primarySeries);
  const confirmationLast = latestCandle(confirmationSeries);
  const last = confirmationLast || primaryLast;
  const previous = confirmationSeries.at(-2) || primarySeries.at(-2);
  if (!last) return;

  state.lastPrice = last.close;
  const change = previous ? ((last.close - previous.close) / previous.close) * 100 : 0;
  state.market.priceChange = change;
  state.market.analysisFrame = `${XAU_PRIMARY_ANALYSIS_INTERVAL} + ${XAU_CONFIRMATION_INTERVAL}`;
  updateTopPrice(last.close, `${change >= 0 ? "Up" : "Down"} ${formatPercent(change, 2)} on ${XAU_CONFIRMATION_INTERVAL}`);
  els.priceChange.textContent = `${change >= 0 ? "Up" : "Down"} ${formatPercent(change, 2)} ${XAU_CONFIRMATION_INTERVAL} candle`;
  els.priceChange.className = change >= 0 ? "positive" : "negative";
  els.headerPriceChange.className = change >= 0 ? "positive" : "negative";
  els.pricePulse.textContent = "live";
  updateCoinGlassSourceStatus(`XAU/USD setup uses ${primarySeries.length} ${XAU_PRIMARY_ANALYSIS_INTERVAL} candles and ${confirmationSeries.length} ${XAU_CONFIRMATION_INTERVAL} candles.`);

  const primaryResearch = studyHistoricalPattern(primarySeries);
  const confirmationResearch = studyHistoricalPattern(confirmationSeries.length ? confirmationSeries : primarySeries);
  renderResearch(primaryResearch);

  const primaryStructure = analyzeMarketStructure(primarySeries, primaryResearch);
  const confirmationStructure = analyzeMarketStructure(confirmationSeries.length ? confirmationSeries : primarySeries, confirmationResearch);
  const primaryStack = analyzeIndicatorStack(primarySeries, primaryResearch, primaryStructure);
  const confirmationStack = analyzeIndicatorStack(confirmationSeries.length ? confirmationSeries : primarySeries, confirmationResearch, confirmationStructure);
  const mergedStack = mergeXauIndicatorStack(primaryStack, confirmationStack, primaryResearch, confirmationResearch);

  const researchScore = clampScore(finiteScore(primaryResearch.score) + finiteScore(confirmationResearch.score), -3, 3);
  const vwapScore = clampScore(finiteScore(primaryResearch.vwapScore) + finiteScore(confirmationResearch.vwapScore), -1, 1);
  state.market.researchSignal = `${primaryResearch.signal} / ${confirmationResearch.signal}`;
  state.market.researchScore = researchScore;
  state.market.vwap = primaryResearch.vwap;
  state.market.vwapDistance = primaryResearch.vwapDistance;
  state.market.vwapScore = vwapScore;
  state.market.vwapSignal = vwapScore > 0 ? "above VWAP" : vwapScore < 0 ? "below VWAP" : "near VWAP";
  state.market.scaleAction = primaryResearch.action !== "wait" ? primaryResearch.action : confirmationResearch.action;
  state.market.pattern = `${primaryResearch.pattern} + ${confirmationResearch.pattern}`;

  els.researchSource.textContent = `XAU/USD setup study · ${XAU_PRIMARY_ANALYSIS_INTERVAL} structure + ${XAU_CONFIRMATION_INTERVAL} execution`;
  els.researchPattern.textContent = state.market.pattern;
  els.historySignal.textContent = state.market.researchSignal;
  els.historyStats.textContent = `${XAU_PRIMARY_ANALYSIS_INTERVAL}: ${primaryResearch.stats} · ${XAU_CONFIRMATION_INTERVAL}: ${confirmationResearch.stats}`;
  els.vwapMetric.textContent = `${state.market.vwapSignal} ${formatPercent(primaryResearch.vwapDistance, 2)} / ${formatPercent(confirmationResearch.vwapDistance, 2)}`;
  els.vwapMetric.className = vwapScore > 0 ? "positive" : vwapScore < 0 ? "negative" : "";
  els.vwapSignal.textContent = state.market.vwapSignal;
  els.vwapSignal.className = els.vwapMetric.className;
  els.vwapDetail.textContent = `15m VWAP ${formatUsd(primaryResearch.vwap)} · 5m VWAP ${formatUsd(confirmationResearch.vwap)} · setup requires both frames.`;
  els.scaleAction.textContent = state.market.scaleAction;
  els.scaleAction.className = state.market.scaleAction === "average down" || state.market.scaleAction === "average up" ? "positive" : state.market.scaleAction === "scale out" ? "negative" : "";
  els.scalePlan.textContent = `Use 15m for direction and invalidation; use 5m for entry timing and pullback confirmation. ${primaryResearch.plan}`;
  els.patternMemory.textContent = `${XAU_PRIMARY_ANALYSIS_INTERVAL} ${primaryResearch.memory} · ${XAU_CONFIRMATION_INTERVAL} ${confirmationResearch.memory}`;
  els.patternDetail.textContent = `${XAU_PRIMARY_ANALYSIS_INTERVAL}: ${primaryResearch.detail} · ${XAU_CONFIRMATION_INTERVAL}: ${confirmationResearch.detail}`;

  renderIndicatorStack(mergedStack);
  renderStructureSummary(primaryStructure);
  drawStructureChart(els.priceCanvas, primarySeries, primaryStructure, primaryResearch);
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
  els.researchSource.textContent = usesServerMarketCandles(asset)
    ? `Hyperliquid/Monatise indicator study · ${asset.coin} · ${els.intervalSelect.value || DEFAULT_VIEW_INTERVAL}`
    : `CoinGlass history study · ${asset.coin} · ${ANALYSIS_INTERVAL} analysis candles`;
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

function clampScore(value, min = -3, max = 3) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(min, Math.min(max, number));
}

function lastEma(values, period) {
  const filtered = values.filter(Number.isFinite);
  if (!filtered.length) return 0;
  const multiplier = 2 / (period + 1);
  return filtered.reduce((ema, value, index) => index === 0 ? value : (value - ema) * multiplier + ema, filtered[0]);
}

function nearestEqualLevel(levels, price, tolerancePct = 0.08) {
  if (!Number.isFinite(price)) return null;
  return levels
    .filter((level) => Number.isFinite(level.price))
    .map((level) => ({ ...level, distancePct: Math.abs(((price - level.price) / price) * 100) }))
    .filter((level) => level.distancePct <= tolerancePct)
    .sort((a, b) => a.distancePct - b.distancePct)[0] || null;
}

function candleWickProfile(row) {
  if (!row) return { upperPct: 0, lowerPct: 0, bodyPct: 0 };
  const range = Math.max(row.high - row.low, Math.abs(row.close) * 0.0001);
  const upper = row.high - Math.max(row.open, row.close);
  const lower = Math.min(row.open, row.close) - row.low;
  const body = Math.abs(row.close - row.open);
  return {
    upperPct: (upper / range) * 100,
    lowerPct: (lower / range) * 100,
    bodyPct: (body / range) * 100
  };
}

function volumeProfilePoc(rows, bins = 24) {
  const pricedRows = rows.filter((row) => Number.isFinite(row.high) && Number.isFinite(row.low) && Number.isFinite(row.close));
  if (!pricedRows.length) return null;
  const high = Math.max(...pricedRows.map((row) => row.high));
  const low = Math.min(...pricedRows.map((row) => row.low));
  const range = Math.max(high - low, Math.abs(high) * 0.0001);
  const buckets = Array.from({ length: bins }, (_, index) => ({
    low: low + (range / bins) * index,
    high: low + (range / bins) * (index + 1),
    volume: 0
  }));
  pricedRows.forEach((row) => {
    const typical = average([row.high, row.low, row.close].filter(Number.isFinite));
    const index = Math.max(0, Math.min(bins - 1, Math.floor(((typical - low) / range) * bins)));
    buckets[index].volume += Number.isFinite(row.volume) && row.volume > 0 ? row.volume : 1;
  });
  const poc = buckets.sort((a, b) => b.volume - a.volume)[0];
  return {
    price: average([poc.low, poc.high]),
    high,
    low
  };
}

function aggregateCandles(rows, size = 4) {
  const output = [];
  for (let i = 0; i < rows.length; i += size) {
    const chunk = rows.slice(i, i + size);
    if (chunk.length < size) continue;
    output.push({
      time: chunk[0].time,
      open: chunk[0].open,
      close: chunk.at(-1).close,
      high: Math.max(...chunk.map((row) => row.high)),
      low: Math.min(...chunk.map((row) => row.low)),
      volume: chunk.reduce((sum, row) => sum + (Number(row.volume) || 0), 0)
    });
  }
  return output;
}

function analyzeMarketStructure(series, research) {
  const rows = series.slice(-80);
  const swings = [];
  for (let i = 2; i < rows.length - 2; i += 1) {
    const row = rows[i];
    const isHigh = row.high > rows[i - 1].high && row.high > rows[i - 2].high && row.high >= rows[i + 1].high && row.high >= rows[i + 2].high;
    const isLow = row.low < rows[i - 1].low && row.low < rows[i - 2].low && row.low <= rows[i + 1].low && row.low <= rows[i + 2].low;
    if (isHigh) swings.push({ index: i, price: row.high, type: "high" });
    if (isLow) swings.push({ index: i, price: row.low, type: "low" });
  }

  const fvgs = [];
  for (let i = 2; i < rows.length; i += 1) {
    const left = rows[i - 2];
    const current = rows[i];
    if (current.low > left.high) {
      fvgs.push({ index: i, low: left.high, high: current.low, side: "bullish" });
    } else if (current.high < left.low) {
      fvgs.push({ index: i, low: current.high, high: left.low, side: "bearish" });
    }
  }

  const last = rows.at(-1);
  const recentHigh = swings.filter((swing) => swing.type === "high").at(-1);
  const recentLow = swings.filter((swing) => swing.type === "low").at(-1);
  const previousHigh = swings.filter((swing) => swing.type === "high").at(-2);
  const previousLow = swings.filter((swing) => swing.type === "low").at(-2);
  const brokeHigh = recentHigh && last.close > recentHigh.price;
  const brokeLow = recentLow && last.close < recentLow.price;
  const priorTrend = previousHigh && recentHigh && recentHigh.price > previousHigh.price ? "up" : previousLow && recentLow && recentLow.price < previousLow.price ? "down" : "range";
  const marker = brokeHigh
    ? { type: priorTrend === "down" ? "CHOCH" : "BOS", side: "bullish", price: recentHigh.price, index: rows.length - 1 }
    : brokeLow
      ? { type: priorTrend === "up" ? "CHOCH" : "BOS", side: "bearish", price: recentLow.price, index: rows.length - 1 }
      : null;

  const signal = research.score >= 2
    ? { side: "BUY", price: last.close, reason: `${research.signal} · ${research.action}` }
    : research.score <= -2
      ? { side: "SELL", price: last.close, reason: `${research.signal} · ${research.action}` }
      : { side: "WAIT", price: last.close, reason: `${research.signal} · neutral grid` };

  return {
    rows,
    swings: swings.slice(-10),
    fvgZones: fvgs.slice(-8),
    liquidityZones: swings.slice(-8).map((swing) => ({
      price: swing.price,
      side: swing.type === "high" ? "buy-side liquidity" : "sell-side liquidity",
      index: swing.index
    })),
    marker,
    signal
  };
}

function analyzeIndicatorStack(series, research, structure) {
  const rows = series.slice(-96);
  const closes = rows.map((row) => row.close).filter(Number.isFinite);
  const last = rows.at(-1);
  if (!last || closes.length < 20) {
    return {
      score: 0,
      summary: "waiting for enough GOLD candles",
      rows: [{ name: "Indicator stack", signal: "WAIT", score: 0, detail: "Need at least 20 candles before building the native stack." }]
    };
  }

  const recent = rows.slice(-24);
  const emaFast = lastEma(closes.slice(-48), 21);
  const emaSlow = lastEma(closes.slice(-80), 50);
  const recentHigh = Math.max(...recent.map((row) => row.high));
  const recentLow = Math.min(...recent.map((row) => row.low));
  const range = Math.max(recentHigh - recentLow, Math.abs(last.close) * 0.0001);
  const wick = candleWickProfile(last);
  const highLevels = structure.swings.filter((swing) => swing.type === "high");
  const lowLevels = structure.swings.filter((swing) => swing.type === "low");
  const equalHigh = nearestEqualLevel(highLevels, last.close);
  const equalLow = nearestEqualLevel(lowLevels, last.close);
  const latestSwingHigh = highLevels.at(-1);
  const latestSwingLow = lowLevels.at(-1);
  const fib618 = recentHigh - range * 0.618;
  const fib382 = recentHigh - range * 0.382;
  const fibBias = last.close <= fib618 ? 1 : last.close >= fib382 ? -1 : 0;
  const vwapScore = clampScore(research.vwapScore || 0, -1, 1);
  const poc = volumeProfilePoc(rows);
  const pocDistance = poc ? ((last.close - poc.price) / poc.price) * 100 : 0;
  const htfRows = aggregateCandles(rows, 4);
  const htfHigh = htfRows.length ? Math.max(...htfRows.slice(-12).map((row) => row.high)) : recentHigh;
  const htfLow = htfRows.length ? Math.min(...htfRows.slice(-12).map((row) => row.low)) : recentLow;
  const htfScore = last.close > htfHigh ? 1 : last.close < htfLow ? -1 : 0;
  const trendScore = emaFast > emaSlow && last.close > emaFast ? 1 : emaFast < emaSlow && last.close < emaFast ? -1 : 0;
  const historicalScore = clampScore(research.score, -1, 1);
  const swingScore = latestSwingHigh && last.close > latestSwingHigh.price ? 1 : latestSwingLow && last.close < latestSwingLow.price ? -1 : 0;
  const wickScore = wick.lowerPct >= 45 && last.close > last.open ? 1 : wick.upperPct >= 45 && last.close < last.open ? -1 : 0;
  const equalScore = equalLow && !equalHigh ? 1 : equalHigh && !equalLow ? -1 : 0;
  const grabScore = latestSwingLow && last.low < latestSwingLow.price && last.close > latestSwingLow.price
    ? 1
    : latestSwingHigh && last.high > latestSwingHigh.price && last.close < latestSwingHigh.price
      ? -1
      : 0;
  const pivotScore = structure.marker?.side === "bullish" ? 1 : structure.marker?.side === "bearish" ? -1 : trendScore;
  const volumeScore = poc ? (last.close > poc.price && Math.abs(pocDistance) <= 1.2 ? 1 : last.close < poc.price && Math.abs(pocDistance) <= 1.2 ? -1 : 0) : 0;
  const luxProxyScore = clampScore(trendScore + vwapScore + grabScore + swingScore, -2, 2);
  const stackRows = [
    {
      name: "LuxAlgo proxy",
      signal: luxProxyScore > 0 ? "BUY CONFLUENCE" : luxProxyScore < 0 ? "SELL CONFLUENCE" : "WAIT",
      score: luxProxyScore,
      detail: "Proxy only: structure, VWAP, trend and liquidity confluence from native candles."
    },
    {
      name: "Historical Colored",
      signal: historicalScore > 0 ? "BULL HISTORY" : historicalScore < 0 ? "BEAR HISTORY" : "RANGE",
      score: historicalScore,
      detail: research.detail || research.stats || "Historical candle memory."
    },
    {
      name: "Liquidity Swings",
      signal: swingScore > 0 ? "HIGH BREAK" : swingScore < 0 ? "LOW BREAK" : "INSIDE SWINGS",
      score: swingScore,
      detail: `${structure.swings.length} recent swings · last high ${latestSwingHigh ? formatUsd(latestSwingHigh.price) : "--"} · last low ${latestSwingLow ? formatUsd(latestSwingLow.price) : "--"}`
    },
    {
      name: "Wick Extremity",
      signal: wickScore > 0 ? "BUY REJECTION" : wickScore < 0 ? "SELL REJECTION" : "NO EXTREME",
      score: wickScore,
      detail: `Upper wick ${wick.upperPct.toFixed(0)}% · lower wick ${wick.lowerPct.toFixed(0)}% · body ${wick.bodyPct.toFixed(0)}%`
    },
    {
      name: "Equal Highs/Lows",
      signal: equalScore > 0 ? "EQUAL LOW" : equalScore < 0 ? "EQUAL HIGH" : "NO NEAR LEVEL",
      score: equalScore,
      detail: equalHigh || equalLow ? `Nearest pool ${formatUsd((equalHigh || equalLow).price)} · ${formatPercent((equalHigh || equalLow).distancePct, 2)} away` : "No equal high/low within tolerance."
    },
    {
      name: "Liquidity Grabs",
      signal: grabScore > 0 ? "LOW SWEPT" : grabScore < 0 ? "HIGH SWEPT" : "NO SWEEP",
      score: grabScore,
      detail: "Detects a sweep through the latest swing that closes back inside the level."
    },
    {
      name: "Dynamic Trend Pivot",
      signal: pivotScore > 0 ? "BULL PIVOT" : pivotScore < 0 ? "BEAR PIVOT" : "NEUTRAL",
      score: pivotScore,
      detail: structure.marker ? `${structure.marker.type} ${structure.marker.side} at ${formatUsd(structure.marker.price)}` : `EMA21 ${formatUsd(emaFast)} · EMA50 ${formatUsd(emaSlow)}`
    },
    {
      name: "Auto Fib Retracement",
      signal: fibBias > 0 ? "DISCOUNT" : fibBias < 0 ? "PREMIUM" : "MID RANGE",
      score: fibBias,
      detail: `24-candle fib zone · 0.618 ${formatUsd(fib618)} · 0.382 ${formatUsd(fib382)}`
    },
    {
      name: "Daily VWAP",
      signal: vwapScore > 0 ? "ABOVE VWAP" : vwapScore < 0 ? "BELOW VWAP" : "AT VWAP",
      score: vwapScore,
      detail: `VWAP ${formatUsd(research.vwap)} · ${formatPercent(research.vwapDistance, 2)} distance`
    },
    {
      name: "Volume Profile",
      signal: volumeScore > 0 ? "ABOVE POC" : volumeScore < 0 ? "BELOW POC" : "AWAY FROM POC",
      score: volumeScore,
      detail: poc ? `Fixed range POC ${formatUsd(poc.price)} · ${formatPercent(pocDistance, 2)} from price` : "No volume profile sample."
    },
    {
      name: "HTF Levels",
      signal: htfScore > 0 ? "HTF BREAKOUT" : htfScore < 0 ? "HTF BREAKDOWN" : "HTF RANGE",
      score: htfScore,
      detail: `Aggregated high ${formatUsd(htfHigh)} · low ${formatUsd(htfLow)}`
    }
  ];
  const rawScore = stackRows.reduce((sum, row) => sum + clampScore(row.score, -2, 2), 0);
  const score = clampScore(rawScore, -3, 3);
  const bias = score > 0 ? "BUY" : score < 0 ? "SELL" : "WAIT";
  const aligned = stackRows.filter((row) => score > 0 ? row.score > 0 : score < 0 ? row.score < 0 : row.score === 0).length;
  return {
    score,
    summary: `${bias} stack ${score >= 0 ? "+" : ""}${score} · ${aligned}/${stackRows.length} aligned`,
    rows: stackRows
  };
}

function renderIndicatorStack(stack) {
  state.market.indicatorScore = stack.score;
  state.market.indicatorSummary = stack.summary;
  state.market.indicatorRows = stack.rows;
  if (!els.indicatorStack) return;
  els.indicatorStack.innerHTML = stack.rows.map((row) => {
    const score = clampScore(row.score, -2, 2);
    const className = score > 0 ? "positive" : score < 0 ? "negative" : "";
    return `
      <article class="indicator-row">
        <div>
          <span>${escapeHtml(row.name)}</span>
          <strong class="${className}">${escapeHtml(row.signal)}</strong>
        </div>
        <b class="${className}">${score > 0 ? "+" : ""}${score}</b>
        <small>${escapeHtml(row.detail)}</small>
      </article>
    `;
  }).join("");
}

function renderStructureSummary(structure) {
  const markerText = structure.marker ? `${structure.marker.type} ${structure.marker.side}` : "No fresh CHOCH/BOS";
  const fvgText = `${structure.fvgZones.length} FVG`;
  const liqText = `${structure.liquidityZones.length} liquidity zones`;
  els.structureSummary.textContent = `${markerText} · ${fvgText} · ${liqText} · Monatise ${structure.signal.side}: ${structure.signal.reason}`;
}

function renderFunding(rows) {
  const asset = selectedAsset();
  if (!rows.length) throw new Error("No funding rows");
  const average = rows.reduce((sum, row) => sum + Number(row.funding_rate || 0), 0) / rows.length;
  state.market.fundingAverage = average;
  els.fundingAverage.textContent = formatPercent(average, 4);
  els.fundingAverage.className = average >= 0 ? "positive" : "negative";
  els.fundingSource.textContent = `CoinGlass ${asset.coin} futures funding rate · stablecoin margin`;
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
  els.fundingAverage.textContent = "CoinGlass key";
  els.fundingAverage.className = "";
  els.fundingSource.textContent = "CoinGlass funding required";
  els.fundingList.innerHTML = lockedRows("Funding rate", error.message, [
    "Primary endpoint: /api/futures/funding-rate/exchange-list",
    "Monatise will not score funding without CoinGlass data"
  ]);
}

function renderOpenInterest(rows) {
  const asset = selectedAsset();
  if (!rows.length) throw new Error("No open interest rows");
  const all = rows.find((row) => row.exchange === "All") || rows[0];
  state.market.oiChange = Number(all.open_interest_change_percent_24h);
  els.openInterest.textContent = formatUsd(all.open_interest_usd, true);
  els.oiSource.textContent = `CoinGlass futures open interest · ${asset.coin}`;
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
  els.openInterest.textContent = "CoinGlass key";
  els.oiSource.textContent = "CoinGlass open interest required";
  els.oiList.innerHTML = lockedRows("Open interest", error.message, [
    `Primary endpoint: /api/futures/open-interest/exchange-list?symbol=${selectedCoin()}`,
    "Monatise will not score open interest without CoinGlass data"
  ]);
}

function renderLiquidations(result) {
  const asset = selectedAsset();
  const current = state.lastPrice || 100000;
  const levels = result.levels || [];
  const source = result.source || "CoinGlass";
  if (!levels.length) throw new Error(`${source} returned no liquidity levels`);
  const below = levels.filter((row) => row.price < current).reduce((sum, row) => sum + row.level, 0);
  const above = levels.filter((row) => row.price >= current).reduce((sum, row) => sum + row.level, 0);
  const bias = source === "Hyperliquid order book"
    ? above > below ? "ask wall" : "bid wall"
    : above > below ? "short squeeze" : "long flush";
  state.market.liquidationBias = bias;
  state.market.liquidationLevels = levels;
  state.market.liquiditySource = source;
  els.liqBias.textContent = bias;
  els.liqBias.className = above > below ? "positive" : "negative";
  els.liqSource.textContent = source === "Hyperliquid order book"
    ? `Hyperliquid order-book liquidity fallback · ${result.mapSymbol || asset.hyper}`
    : `CoinGlass aggregated liquidation map · ${result.mapSymbol || asset.pair}`;
  if (result.assetPain) {
    els.maxPain.textContent = `max pain ${formatUsd(result.assetPain.short_max_pain_liq_price)} / ${formatUsd(result.assetPain.long_max_pain_liq_price)}`;
  } else if (source === "Hyperliquid order book") {
    els.maxPain.textContent = "order-book liquidity, not liquidation heat map";
  } else {
    els.maxPain.textContent = "max pain gated";
  }
  drawLiquidationMap(els.liqCanvas, levels, current);
}

async function renderLiquidationsLocked(error) {
  try {
    const fallback = await getHyperliquidBookLiquidity();
    renderLiquidations(fallback);
  } catch (fallbackError) {
    els.liqSource.textContent = "CoinGlass liquidation map and Hyperliquid book unavailable";
    els.maxPain.textContent = `${error.message}; ${fallbackError.message}`.slice(0, 160);
    els.liqBias.textContent = "Liquidity pending";
    els.liqBias.className = "";
    state.market.liquidationBias = null;
    state.market.liquidationLevels = [];
    state.market.liquiditySource = "";
    drawCanvasNotice(els.liqCanvas, "Liquidity data unavailable", `${error.message}; ${fallbackError.message}`);
  }
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
  els.newsSource.textContent = "CoinGlass instant news alerts";
  els.newsList.innerHTML = rows.map((row) => {
    const title = stripHtml(row.article_title || "Market alert");
    const description = stripHtml(row.article_description || "").slice(0, 180);
    return `
      <article class="news-item rich-news">
        <img src="${newsImageData(title, description)}" alt="" loading="lazy" />
        <div>
          <strong>${escapeHtml(title)}</strong>
          <small>${escapeHtml(row.source_name || "CoinGlass")} · ${formatTime(row.article_release_time)}</small>
          <p>${escapeHtml(description || "Market event detected. Review price, funding, OI, liquidations, and session timing before acting.")}</p>
        </div>
      </article>
    `;
  }).join("");
}

function renderNewsLocked(error) {
  els.newsSource.textContent = "CoinGlass news required";
  els.newsList.innerHTML = lockedRows("News alerts", error.message, [
    "Primary endpoint: /api/article/list",
    "Monatise will only publish news alerts from CoinGlass"
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
  ], "confirm");
}

function marketFundingContext(market = state.market) {
  const cg = Number(market.fundingAverage);
  if (Number.isFinite(cg)) {
    return { label: "CoinGlass funding", live: true, source: "CoinGlass", value: cg };
  }
  const hyper = Number(market.hyperFunding);
  if (Number.isFinite(hyper)) {
    return { label: "Hyperliquid funding fallback", live: true, source: "Hyperliquid", value: hyper };
  }
  return { label: "Funding", live: false, source: "", value: null };
}

function marketOpenInterestContext(market = state.market) {
  const cgChange = Number(market.oiChange);
  if (Number.isFinite(cgChange)) {
    return { label: "CoinGlass open interest", live: true, source: "CoinGlass", type: "change", value: cgChange };
  }
  const hyperOi = Number(market.hyperOpenInterest);
  if (Number.isFinite(hyperOi) && hyperOi > 0) {
    return { label: "Hyperliquid OI fallback", live: true, source: "Hyperliquid", type: "level", value: hyperOi };
  }
  return { label: "Open interest", live: false, source: "", type: "", value: null };
}

function applyMonatiseFramework() {
  const asset = selectedAsset();
  const m = state.market;
  const checks = [];
  const fundingContext = marketFundingContext(m);
  const oiContext = marketOpenInterestContext(m);

  addCheck(checks, "Price trend", m.priceChange, m.priceChange > 0.15 ? 1 : m.priceChange < -0.15 ? -1 : 0, `${formatPercent(m.priceChange || 0, 2)} last candle`);
  addCheck(checks, "Funding", fundingContext.live ? fundingContext.value : null, fundingContext.value > 0.015 ? -1 : fundingContext.value < -0.015 ? 1 : 0, fundingContext.live ? `${formatPercent(fundingContext.value, 4)} · ${fundingContext.source}` : "waiting");
  addCheck(
    checks,
    "Open interest",
    oiContext.live ? oiContext.value : null,
    oiContext.type === "change" ? (oiContext.value > 0.5 ? 1 : oiContext.value < -0.5 ? -1 : 0) : 0,
    oiContext.live
      ? oiContext.type === "change"
        ? `${formatPercent(oiContext.value, 2)} 24h · ${oiContext.source}`
        : `${Number(oiContext.value).toLocaleString(undefined, { maximumFractionDigits: 0 })} contracts · ${oiContext.source}`
      : "waiting"
  );
  addCheck(
    checks,
    m.liquiditySource === "Hyperliquid order book" ? "Book liquidity" : "Liquidations",
    m.liquidationBias,
    m.liquidationBias === "short squeeze" || m.liquidationBias === "bid wall" ? 1 : m.liquidationBias === "long flush" || m.liquidationBias === "ask wall" ? -1 : 0,
    m.liquidationBias ? `${m.liquidationBias}${m.liquiditySource ? ` · ${m.liquiditySource}` : ""}` : "waiting"
  );
  addCheck(checks, "Fear/greed", m.fearGreed, m.fearGreed > 72 ? -1 : m.fearGreed < 28 ? 1 : 0, m.fearGreed == null ? "waiting" : `${Math.round(m.fearGreed)}`);
  addCheck(checks, "VWAP", m.vwapSignal, m.vwapScore, m.vwapSignal ? `${m.vwapSignal} · ${formatPercent(m.vwapDistance, 2)} from VWAP` : "waiting");
  addCheck(checks, "History research", m.researchSignal, m.researchScore > 0 ? 1 : m.researchScore < 0 ? -1 : 0, m.researchSignal ? `${m.researchSignal} · ${m.scaleAction}` : "waiting");
  addCheck(checks, "Indicator stack", m.indicatorSummary, clampScore(m.indicatorScore || 0), m.indicatorSummary || "waiting");
  if (isXauAsset(asset)) {
    addCheck(checks, "XAU timeframe", m.analysisFrame, m.analysisFrame === `${XAU_PRIMARY_ANALYSIS_INTERVAL} + ${XAU_CONFIRMATION_INTERVAL}` ? 1 : 0, m.analysisFrame ? `${m.analysisFrame} setup analysis` : "waiting for 15m + 5m");
  }

  const liveChecks = checks.filter((check) => check.live).length;
  const score = checks.reduce((sum, check) => sum + check.score, 0);
  const direction = score >= 2 ? "BUY SETUP" : score <= -2 ? "SELL SETUP" : "WAIT";
  const confidence = Math.min(100, Math.round((Math.abs(score) / 6) * 100 + liveChecks * 5));
  const hedge = hedgeFromCoinGlass({ direction, score, confidence, market: m });

  els.frameworkSource.textContent = isXauAsset(asset)
    ? `${asset.coin} selected · XAU/USD ${XAU_PRIMARY_ANALYSIS_INTERVAL} structure + ${XAU_CONFIRMATION_INTERVAL} execution + CoinGlass/Hyperliquid context`
    : `${asset.coin} selected · Native indicator stack + market candles + CoinGlass/Hyperliquid context`;
  els.setupDirection.textContent = direction;
  els.setupDirection.className = direction.includes("BUY") ? "positive" : direction.includes("SELL") ? "negative" : "";
  els.setupConfidence.textContent = `confidence ${confidence}%`;
  els.frameworkChecks.textContent = `${liveChecks} / ${checks.length}`;
  els.frameworkBias.textContent = `Score ${score >= 0 ? "+" : ""}${score} from ${checks.length} checks`;
  els.setupReason.textContent = checks.map((check) => `${check.name}: ${check.detail}`).join(" · ");

  let gridDirection = `Neutral grid ${asset.coin}`;
  let gridPlan = "Use small two-sided grid or wait until funding/OI/liquidation checks align.";
  let hedgeDirection = hedge.direction;
  let hedgePlan = hedge.plan;

  if (direction === "BUY SETUP") {
    gridDirection = `Buy grid ${asset.coin}`;
    gridPlan = gridPlanForResearch("buy", m.scaleAction, m.vwapSignal);
  } else if (direction === "SELL SETUP") {
    gridDirection = `Sell grid ${asset.coin}`;
    gridPlan = gridPlanForResearch("sell", m.scaleAction, m.vwapSignal);
  }

  els.gridDirection.textContent = gridDirection;
  els.gridPlan.textContent = gridPlan;
  els.hedgeDirection.textContent = hedgeDirection;
  els.hedgePlan.textContent = hedgePlan;
  updateLiquidityAtlas();

  return {
    asset: asset.coin,
    direction,
    confidence,
    liveChecks,
    score,
    gridDirection,
    gridPlan,
    hedgeDirection,
    hedgePlan,
    hedgePct: hedge.percent,
    hedgeData: hedge.data,
    price: state.lastPrice,
    vwap: m.vwap,
    vwapSignal: m.vwapSignal,
    scaleAction: m.scaleAction,
    checks
  };
}

function hedgeFromCoinGlass({ direction, score, confidence, market }) {
  const m = market || {};
  const reasons = [];
  const data = [];
  let pressure = 0;
  const add = (label, value, contribution, reason) => {
    const hasValue = value !== null && value !== undefined && value !== "";
    const live = hasValue && (Number.isFinite(Number(value)) || typeof value === "string");
    if (!live) return;
    data.push(label);
    pressure += contribution;
    if (contribution) reasons.push(reason);
  };

  const fundingContext = marketFundingContext(m);
  const funding = Number(fundingContext.value);
  if (fundingContext.live) {
    add(
      fundingContext.source === "Hyperliquid" ? "Hyperliquid funding" : "CoinGlass funding",
      funding,
      funding > 0.015 ? -1 : funding < -0.015 ? 1 : 0,
      `${fundingContext.label} ${formatPercent(funding, 4)}`
    );
    if (Math.abs(funding) > 0.04) {
      pressure += funding > 0 ? -1 : 1;
      reasons.push(`crowded ${fundingContext.source || "market"} funding ${formatPercent(funding, 4)}`);
    }
  }

  const oiContext = marketOpenInterestContext(m);
  const oi = Number(oiContext.value);
  if (oiContext.live) {
    add(
      oiContext.source === "Hyperliquid" ? "Hyperliquid OI" : "CoinGlass OI",
      oi,
      oiContext.type === "change" ? (oi > 0.5 ? 1 : oi < -0.5 ? -1 : 0) : 0,
      oiContext.type === "change"
        ? `${oiContext.label} ${formatPercent(oi, 2)} 24h`
        : `${oiContext.label} ${oi.toLocaleString(undefined, { maximumFractionDigits: 0 })} contracts`
    );
    if (oiContext.type === "level" && Math.abs(pressure) > 0) {
      reasons.push(`${oiContext.label} confirms live derivatives participation`);
    }
  }

  if (m.liquidationBias) {
    const bookFallback = m.liquiditySource === "Hyperliquid order book";
    add(
      bookFallback ? "Hyperliquid book" : "CoinGlass liquidations",
      m.liquidationBias,
      m.liquidationBias === "short squeeze" || m.liquidationBias === "bid wall" ? 1 : m.liquidationBias === "long flush" || m.liquidationBias === "ask wall" ? -1 : 0,
      bookFallback ? `order book ${m.liquidationBias}` : `liquidation map ${m.liquidationBias}`
    );
  }

  const vwapScore = Number(m.vwapScore);
  if (Number.isFinite(vwapScore) && m.vwapSignal) {
    add("VWAP", m.vwapSignal, vwapScore, `${m.vwapSignal} ${formatPercent(Number(m.vwapDistance || 0), 2)}`);
  }

  const fearGreed = Number(m.fearGreed);
  if (Number.isFinite(fearGreed)) {
    add("fear/greed", fearGreed, fearGreed > 72 ? -1 : fearGreed < 28 ? 1 : 0, `fear/greed ${Math.round(fearGreed)}`);
  }

  if (m.researchSignal) {
    add("history", m.researchSignal, Number(m.researchScore || 0), `${m.researchSignal} history`);
  }

  const setupSide = direction === "BUY SETUP" ? 1 : direction === "SELL SETUP" ? -1 : 0;
  const adversePressure = setupSide ? pressure * -setupSide : Math.abs(pressure);
  const liveData = data.length;
  const enoughData = liveData >= 2;
  const strongSetup = Math.abs(Number(score || 0)) >= 3 || Number(confidence || 0) >= 65;
  let percent = 0;
  if (enoughData && adversePressure >= 3) percent = strongSetup ? 50 : 35;
  else if (enoughData && adversePressure >= 2) percent = 25;
  else if (enoughData && adversePressure >= 1) percent = 15;

  if (!setupSide) {
    return {
      data,
      direction: enoughData && Math.abs(pressure) >= 2 ? `Hedge watch ${pressure > 0 ? "short risk" : "long risk"}` : "Flat hedge",
      percent: 0,
      plan: enoughData
        ? `No active BUY/SELL hedge yet. Hedge lens is reading ${pressure > 0 ? "upside squeeze risk" : pressure < 0 ? "downside flush risk" : "balanced risk"} from ${data.join(", ")}.`
        : "Add CoinGlass or Hyperliquid funding/OI plus liquidation map or VWAP data to unlock hedge sizing."
    };
  }

  const hedgeSide = setupSide > 0 ? "Short" : "Long";
  const setupLabel = setupSide > 0 ? "long" : "short";
  return {
    data,
    direction: percent ? `${hedgeSide} hedge ${percent}%` : "No hedge",
    percent,
    plan: percent
      ? `${hedgeSide} ${percent}% because market data shows adverse risk against the ${setupLabel} setup: ${reasons.slice(0, 4).join(" · ")}. Datapoints: ${data.join(", ")}.`
      : enoughData
        ? `No hedge required yet. Datapoints (${data.join(", ")}) do not show enough adverse pressure against the ${setupLabel} setup.`
        : "Hedge sizing needs at least two live datapoints: CoinGlass/Hyperliquid funding, OI, liquidations, VWAP, fear/greed, or history."
  };
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

function lockedRows(title, detail, lines, status = "required") {
  return lines.map((line, index) => `
    <div class="metric-row">
      <div>
        <strong>${index === 0 ? title : "Route"}</strong><br />
        <small>${line}</small>
      </div>
      <span class="metric-value">${index === 0 ? status : detail}</span>
    </div>
  `).join("");
}

function drawStructureChart(canvas, series, structure, research) {
  const ctx = prepareCanvas(canvas);
  const { width, height } = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);
  drawGrid(ctx, width, height);
  const rows = structure.rows.length ? structure.rows : series.slice(-80);
  if (rows.length < 2) return;
  const prices = rows.flatMap((row) => [row.high, row.low, row.close, row.open || row.close]).concat(
    structure.fvgZones.flatMap((zone) => [zone.low, zone.high]),
    structure.liquidityZones.map((zone) => zone.price),
    research.vwap || []
  ).filter(Number.isFinite);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const pad = (max - min || 1) * 0.12;
  const xFor = (index) => 44 + (index / Math.max(1, rows.length - 1)) * (width - 76);
  const yFor = (value) => height - 34 - ((value - min + pad) / (max - min + pad * 2)) * (height - 64);
  const candleStep = (width - 76) / Math.max(1, rows.length - 1);
  const candleWidth = Math.max(3, Math.min(11, candleStep * 0.58));

  structure.fvgZones.forEach((zone) => {
    const startX = xFor(Math.max(0, zone.index - 2));
    const yTop = yFor(zone.high);
    const yBottom = yFor(zone.low);
    ctx.fillStyle = zone.side === "bullish" ? "rgba(90, 230, 143, 0.12)" : "rgba(255, 107, 127, 0.12)";
    ctx.strokeStyle = zone.side === "bullish" ? "rgba(90, 230, 143, 0.45)" : "rgba(255, 107, 127, 0.45)";
    ctx.fillRect(startX, Math.min(yTop, yBottom), width - startX - 24, Math.max(4, Math.abs(yBottom - yTop)));
    ctx.strokeRect(startX, Math.min(yTop, yBottom), width - startX - 24, Math.max(4, Math.abs(yBottom - yTop)));
  });

  structure.liquidityZones.forEach((zone) => {
    const y = yFor(zone.price);
    ctx.strokeStyle = zone.side.startsWith("buy") ? "rgba(82, 214, 255, 0.7)" : "rgba(255, 191, 71, 0.7)";
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(42, y);
    ctx.lineTo(width - 24, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#90a3b8";
    ctx.font = "11px system-ui";
    ctx.fillText(zone.side, 48, y - 4);
  });

  if (Number.isFinite(research.vwap)) {
    const y = yFor(research.vwap);
    ctx.strokeStyle = "rgba(181, 146, 255, 0.9)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(42, y);
    ctx.lineTo(width - 24, y);
    ctx.stroke();
    ctx.fillStyle = "#b592ff";
    ctx.font = "12px system-ui";
    ctx.fillText("VWAP", width - 66, y - 6);
  }

  rows.forEach((row, index) => {
    const x = xFor(index);
    const open = Number.isFinite(row.open) ? row.open : row.close;
    const up = row.close >= open;
    const yOpen = yFor(open);
    const yClose = yFor(row.close);
    const yHigh = yFor(row.high);
    const yLow = yFor(row.low);
    ctx.strokeStyle = up ? "#5ae68f" : "#ff6b7f";
    ctx.fillStyle = up ? "rgba(90, 230, 143, 0.88)" : "rgba(255, 107, 127, 0.88)";
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.moveTo(x, yHigh);
    ctx.lineTo(x, yLow);
    ctx.stroke();
    ctx.fillRect(x - candleWidth / 2, Math.min(yOpen, yClose), candleWidth, Math.max(2, Math.abs(yClose - yOpen)));
  });

  if (structure.marker) {
    const x = xFor(structure.marker.index);
    const y = yFor(structure.marker.price);
    ctx.fillStyle = structure.marker.side === "bullish" ? "#5ae68f" : "#ff6b7f";
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#eef4fb";
    ctx.font = "bold 12px system-ui";
    ctx.fillText(structure.marker.type, Math.max(48, x - 44), y - 10);
  }

  const signalY = yFor(structure.signal.price);
  ctx.fillStyle = structure.signal.side === "BUY" ? "#5ae68f" : structure.signal.side === "SELL" ? "#ff6b7f" : "#ffbf47";
  ctx.font = "bold 12px system-ui";
  ctx.fillText(`Monatise ${structure.signal.side}`, width - 142, signalY - 10);

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
    ctx.fillStyle =
      row.side === "ask"
        ? "rgba(255, 107, 127, 0.72)"
        : row.side === "bid"
          ? "rgba(90, 230, 143, 0.72)"
          : row.price >= current ? "rgba(90, 230, 143, 0.72)" : "rgba(255, 107, 127, 0.72)";
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
  if (levels.some((row) => row.source === "Hyperliquid order book")) {
    ctx.fillStyle = "#90a3b8";
    ctx.fillText("Hyperliquid book depth", 48, 28);
  }
  ctx.fillStyle = "#90a3b8";
  ctx.fillText(formatUsd(minPrice), 12, height - 12);
  ctx.fillText(formatUsd(maxPrice), width - 104, height - 12);
}

function drawCanvasNotice(canvas, title, detail) {
  const ctx = prepareCanvas(canvas);
  const { width, height } = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, width, height);
  drawGrid(ctx, width, height);
  ctx.fillStyle = "#eef4fb";
  ctx.font = "600 14px system-ui";
  ctx.textAlign = "center";
  ctx.fillText(title, width / 2, height / 2 - 8);
  ctx.fillStyle = "#90a3b8";
  ctx.font = "12px system-ui";
  ctx.fillText(detail, width / 2, height / 2 + 14, Math.max(120, width - 40));
  ctx.textAlign = "start";
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

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stripHtml(input) {
  const template = document.createElement("template");
  template.innerHTML = input || "";
  return (template.content.textContent || "").replace(/\s+/g, " ").trim();
}

function newsTopic(title, description = "") {
  const text = `${title} ${description}`.toLowerCase();
  if (/bitcoin|btc/.test(text)) return { accent: "#ffbf47", label: "BTC", shape: "bars" };
  if (/ethereum|eth/.test(text)) return { accent: "#7aa7ff", label: "ETH", shape: "nodes" };
  if (/fed|rate|inflation|cpi|ppi|macro|dollar|treasury/.test(text)) return { accent: "#52d6ff", label: "MACRO", shape: "wave" };
  if (/hack|security|exploit|attack|risk|liquidation/.test(text)) return { accent: "#ff6b7f", label: "RISK", shape: "alert" };
  if (/etf|institution|fund|flow/.test(text)) return { accent: "#75ffd6", label: "FLOW", shape: "flow" };
  if (/solana|sol/.test(text)) return { accent: "#b592ff", label: "SOL", shape: "nodes" };
  return { accent: "#ff62d2", label: "NEWS", shape: "wave" };
}

function newsImageData(title, description = "") {
  const topic = newsTopic(title, description);
  const paths = {
    alert: `<path d="M44 22 18 70h52L44 22Z" fill="${topic.accent}" opacity=".82"/><rect x="41" y="39" width="6" height="18" rx="3" fill="#081018"/><circle cx="44" cy="62" r="3" fill="#081018"/>`,
    bars: `<rect x="16" y="52" width="9" height="24" rx="3" fill="${topic.accent}"/><rect x="31" y="36" width="9" height="40" rx="3" fill="${topic.accent}" opacity=".78"/><rect x="46" y="24" width="9" height="52" rx="3" fill="${topic.accent}" opacity=".58"/><path d="M13 58c18-22 37-27 62-41" stroke="#eef4fb" stroke-width="4" fill="none" opacity=".8"/>`,
    flow: `<path d="M14 55c18-18 34 17 52-1" stroke="${topic.accent}" stroke-width="8" fill="none" stroke-linecap="round"/><path d="M14 36c16-16 35 12 56-7" stroke="#eef4fb" stroke-width="5" fill="none" stroke-linecap="round" opacity=".72"/>`,
    nodes: `<circle cx="24" cy="30" r="10" fill="${topic.accent}"/><circle cx="62" cy="26" r="7" fill="#eef4fb" opacity=".78"/><circle cx="48" cy="66" r="12" fill="${topic.accent}" opacity=".72"/><path d="M31 34 55 28M29 38l14 20M57 34 50 55" stroke="#eef4fb" stroke-width="3" opacity=".65"/>`,
    wave: `<path d="M9 57c14-25 25 22 40-2s26-8 34 10" stroke="${topic.accent}" stroke-width="7" fill="none" stroke-linecap="round"/><path d="M8 36c19-12 36 9 53-12" stroke="#eef4fb" stroke-width="4" fill="none" opacity=".65"/>`
  };
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 88 88"><defs><linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#111923"/><stop offset="1" stop-color="#081018"/></linearGradient></defs><rect width="88" height="88" rx="12" fill="url(#bg)"/><circle cx="72" cy="16" r="22" fill="${topic.accent}" opacity=".16"/><circle cx="15" cy="78" r="28" fill="${topic.accent}" opacity=".1"/>${paths[topic.shape]}<text x="12" y="82" fill="#90a3b8" font-size="9" font-family="Arial, sans-serif" font-weight="700">${topic.label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const SESSION_WINDOWS = [
  { asset: "crypto", close: null, focus: "Crypto", note: "24/7 market. Best liquidity usually appears during London/New York overlap.", open: null },
  { asset: "forex", close: 6, focus: "Sydney", note: "AUD/NZD pairs; lower volatility than London/New York.", open: 21 },
  { asset: "forex", close: 9, focus: "Tokyo", note: "JPY and Asia risk tone.", open: 0 },
  { asset: "forex", close: 16, focus: "London", note: "Best forex liquidity for EUR, GBP, gold, oil, and crypto continuation.", open: 7 },
  { asset: "forex", close: 21, focus: "New York", note: "Best overlap with London from 12:00-16:00 UTC.", open: 12 }
];

function utcMinutes(date = new Date()) {
  return date.getUTCHours() * 60 + date.getUTCMinutes();
}

function isUtcWindowOpen(openHour, closeHour, date = new Date()) {
  if (openHour == null || closeHour == null) return true;
  const now = utcMinutes(date);
  const open = openHour * 60;
  const close = closeHour * 60;
  return open < close ? now >= open && now < close : now >= open || now < close;
}

function minutesUntilUtcHour(hour, date = new Date()) {
  const target = hour * 60;
  const now = utcMinutes(date);
  return (target - now + 1440) % 1440;
}

function durationShort(minutes) {
  const value = Math.max(0, Math.round(minutes));
  const hours = Math.floor(value / 60);
  const mins = value % 60;
  return hours ? `${hours}h ${mins}m` : `${mins}m`;
}

function utcHour(hour) {
  return `${String(hour).padStart(2, "0")}:00 UTC`;
}

function localHour(hour) {
  const now = new Date();
  const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, 0, 0));
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function renderSessionTimers(date = new Date()) {
  if (!els.sessionTimers) return;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
  const rows = SESSION_WINDOWS.map((session) => {
    if (session.asset === "crypto") {
      return `<article class="session-card open">
        <span>${escapeHtml(session.focus)}</span>
        <strong>Open 24/7</strong>
        <small>Best: 12:00-16:00 UTC (${localHour(12)}-${localHour(16)} local) · ${escapeHtml(session.note)}</small>
      </article>`;
    }
    const open = isUtcWindowOpen(session.open, session.close, date);
    const change = open ? minutesUntilUtcHour(session.close, date) : minutesUntilUtcHour(session.open, date);
    return `<article class="session-card ${open ? "open" : "closed"}">
      <span>${escapeHtml(session.focus)}</span>
      <strong>${open ? `Closes in ${durationShort(change)}` : `Opens in ${durationShort(change)}`}</strong>
      <small>${utcHour(session.open)}-${utcHour(session.close)} · ${localHour(session.open)}-${localHour(session.close)} local · ${escapeHtml(session.note)}</small>
    </article>`;
  }).join("");
  els.sessionTimers.innerHTML = `
    <div class="timezone-strip">
      <strong>${date.toISOString().slice(11, 19)} UTC</strong>
      <span>${date.toLocaleTimeString()} · ${escapeHtml(tz)}</span>
    </div>
    <div class="best-window">
      <strong>Best windows</strong>
      <span>Crypto: London/New York overlap, 12:00-16:00 UTC. Forex: London 07:00-16:00 UTC and London/New York overlap 12:00-16:00 UTC.</span>
    </div>
    <div class="session-card-grid">${rows}</div>
  `;
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
    state.lastPrice = null;
    state.priceSeries = [];
    state.market.priceChange = null;
    els.assetPrice.textContent = "$--";
    els.headerAssetPrice.textContent = "$--";
    els.priceChange.textContent = "CoinGlass required";
    els.priceChange.className = "";
    els.headerPriceChange.textContent = "CoinGlass required";
    els.headerPriceChange.className = "";
    els.priceSource.textContent = `CoinGlass price unavailable · ${error.message}`;
    els.pricePulse.textContent = "offline";
    updateCoinGlassSourceStatus(error.message);
    drawCanvasNotice(els.priceCanvas, "CoinGlass price history required", error.message);
  }

  const jobs = [
    getFunding().then(renderFunding).catch(renderFundingLocked),
    getOpenInterest().then(renderOpenInterest).catch(renderOpenInterestLocked),
    getLiquidations().then(renderLiquidations).catch(renderLiquidationsLocked),
    getFearGreed().then(renderFearGreed).catch((error) => {
      state.market.fearGreed = null;
      els.fearGreed.textContent = "CoinGlass key";
      els.fgLabel.textContent = error.message;
      els.fgGauge.querySelector("span").textContent = "--";
      els.fgGauge.style.background = "";
      els.fgSource.textContent = `CoinGlass fear and greed unavailable · ${error.message}`;
    }),
    getHyperliquidContext().then(renderHyperliquid).catch(renderHyperliquidLocked),
    getNews().then(renderNews).catch(renderNewsLocked)
  ];

  await Promise.allSettled(jobs);
  const setup = applyMonatiseFramework();
  publishGeneratedSignal(setup);
  evaluateLiveAlerts(setup);
  const failures = state.telemetry.slice(0, 8).filter((item) => !item.ok).length;
  setSessionStatus(failures ? "bad" : "good", failures ? "Session degraded" : "Session live");
  els.refreshButton.disabled = false;
  els.refreshButton.textContent = "Refresh";
}

els.apiKeyInput.addEventListener("input", () => {
  syncCoinGlassKey();
});

els.apiKeyInput.addEventListener("change", () => {
  syncCoinGlassKey(state.apiKey ? "CoinGlass key saved locally. Refreshing live market data." : "CoinGlass key removed.");
  refreshDashboard();
  refreshAutonomousMonitor();
});

els.ablyKeyInput.addEventListener("change", () => {
  state.realtime.key = els.ablyKeyInput.value.trim();
  localStorage.setItem(ABLY_KEY_STORAGE, state.realtime.key);
  connectRealtime();
});

els.ablyChannelInput.addEventListener("change", () => {
  state.realtime.channelName = els.ablyChannelInput.value.trim() || "monatise-live-alerts";
  els.ablyChannelInput.value = state.realtime.channelName;
  localStorage.setItem(ABLY_CHANNEL_STORAGE, state.realtime.channelName);
  connectRealtime();
});

els.elevenKeyInput.addEventListener("change", () => {
  state.voice.apiKey = els.elevenKeyInput.value.trim();
  localStorage.setItem(ELEVEN_KEY_STORAGE, state.voice.apiKey);
  setVoiceStatus(state.voice.apiKey ? "ElevenLabs saved locally" : "Text response mode");
});

els.elevenVoiceInput.addEventListener("change", () => {
  state.voice.voiceId = els.elevenVoiceInput.value.trim() || "JBFqnCBsd6RMkjVDRZzb";
  els.elevenVoiceInput.value = state.voice.voiceId;
  localStorage.setItem(ELEVEN_VOICE_STORAGE, state.voice.voiceId);
  setVoiceStatus("ElevenLabs voice saved locally");
});

els.voiceAskButton.addEventListener("click", () => {
  handleVoiceQuestion(els.voiceQuestionInput.value);
});

els.voiceQuestionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") handleVoiceQuestion(els.voiceQuestionInput.value);
});

els.voiceRecordButton.addEventListener("click", () => {
  if (state.voice.recording && state.voice.recorder) {
    state.voice.recorder.stop();
    return;
  }
  startVoiceRecording().catch((error) => {
    setVoiceStatus(`Mic unavailable · ${error.message}`);
  });
});

els.voiceStopButton.addEventListener("click", () => {
  if (state.voice.recording && state.voice.recorder) {
    state.voice.recorder.stop();
  }
  els.voiceAudio.pause();
  setVoiceStatus("Voice stopped");
});

els.openaiKeyInput.addEventListener("change", () => {
  state.copilot.apiKey = els.openaiKeyInput.value.trim();
  localStorage.setItem(OPENAI_KEY_STORAGE, state.copilot.apiKey);
  setCopilotStatus(state.copilot.apiKey ? "OpenAI saved locally" : "Local copilot fallback");
});

els.openaiModelInput.addEventListener("change", () => {
  state.copilot.model = els.openaiModelInput.value.trim() || "gpt-5.5";
  els.openaiModelInput.value = state.copilot.model;
  localStorage.setItem(OPENAI_MODEL_STORAGE, state.copilot.model);
  setCopilotStatus(`OpenAI model set to ${state.copilot.model}`);
});

els.traderAccountInput.addEventListener("input", () => {
  localStorage.setItem(TRADER_ACCOUNT_STORAGE, els.traderAccountInput.value);
  renderTraderMode();
});

els.traderRiskInput.addEventListener("input", () => {
  localStorage.setItem(TRADER_RISK_STORAGE, els.traderRiskInput.value);
  renderTraderMode();
});

els.copilotAskButton.addEventListener("click", handleCopilotQuestion);
els.copilotQuestionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") handleCopilotQuestion();
});

els.atlasButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.atlas.view = button.dataset.atlasView || "btc";
    els.atlasButtons.forEach((item) => item.classList.toggle("active", item === button));
    updateLiquidityAtlas();
  });
});

els.refreshButton.addEventListener("click", refreshDashboard);
els.openIntegrationsButton?.addEventListener("click", () => {
  const drawer = els.apiKeyInput.closest(".integration-drawer");
  if (drawer) drawer.open = true;
  els.apiKeyInput.focus();
});
els.installDashboardButton?.addEventListener("click", async () => {
  if (!deferredDashboardInstallPrompt) return;
  deferredDashboardInstallPrompt.prompt();
  await deferredDashboardInstallPrompt.userChoice.catch(() => {});
  deferredDashboardInstallPrompt = null;
  els.installDashboardButton.hidden = true;
});
els.assetSearchInput?.addEventListener("input", renderAssetSearch);
els.assetSearchInput?.addEventListener("focus", renderAssetSearch);
els.assetSearchResults?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-asset-search]");
  if (button) chooseAsset(button.dataset.assetSearch);
});
els.monitorGrid?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-monitor-asset]");
  if (button) chooseAsset(button.dataset.monitorAsset);
});
els.assetSelect.addEventListener("change", () => {
  chooseAsset(els.assetSelect.value);
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
  if (state.market.liquidationLevels.length && state.lastPrice) {
    drawLiquidationMap(els.liqCanvas, state.market.liquidationLevels, state.lastPrice);
  } else {
    drawCanvasNotice(els.liqCanvas, "CoinGlass liquidation map required", "Waiting for CoinGlass liquidation levels");
  }
  resizeAtlas();
});

populateAssetSelect();
setupDashboardInstall();
renderTelemetry();
renderLiveAlerts();
renderSignalLog();
renderMonitorGrid();
renderSessionTimers();
initLiquidityAtlas();
updateLiquidityAtlas();
connectRealtime();
loadOperatorStatus().then(() => {
  refreshDashboard();
  refreshAutonomousMonitor();
});
setInterval(renderSessionTimers, 1000);
setInterval(refreshDashboard, 60_000);
setInterval(refreshAutonomousMonitor, 90_000);
