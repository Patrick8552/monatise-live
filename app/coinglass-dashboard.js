const CG_BASE = "https://open-api-v4.coinglass.com";
const BINANCE_BASE = "https://api.binance.com";
const HYPER_BASE = "https://api.hyperliquid.xyz/info";
const ALT_FG = "https://api.alternative.me/fng/?limit=30&format=json";
const ELEVEN_BASE = "https://api.elevenlabs.io";
const OPENAI_BASE = "https://api.openai.com";
const SESSION_KEY = "btc-coinglass-dashboard-session";
const API_KEY_STORAGE = "btc-coinglass-api-key";
const ABLY_KEY_STORAGE = "monatise-ably-api-key";
const ABLY_CHANNEL_STORAGE = "monatise-ably-channel";
const ELEVEN_KEY_STORAGE = "monatise-elevenlabs-api-key";
const ELEVEN_VOICE_STORAGE = "monatise-elevenlabs-voice-id";
const OPENAI_KEY_STORAGE = "monatise-openai-api-key";
const OPENAI_MODEL_STORAGE = "monatise-openai-model";
const ASSETS = {
  BTC: { coin: "BTC", pair: "BTCUSDT", hyper: "BTC", tv: "BINANCE:BTCUSDT" },
  ETH: { coin: "ETH", pair: "ETHUSDT", hyper: "ETH", tv: "BINANCE:ETHUSDT" },
  SOL: { coin: "SOL", pair: "SOLUSDT", hyper: "SOL", tv: "BINANCE:SOLUSDT" },
  XRP: { coin: "XRP", pair: "XRPUSDT", hyper: "XRP", tv: "BINANCE:XRPUSDT" },
  DOGE: { coin: "DOGE", pair: "DOGEUSDT", hyper: "DOGE", tv: "BINANCE:DOGEUSDT" },
  BNB: { coin: "BNB", pair: "BNBUSDT", hyper: "BNB", tv: "BINANCE:BNBUSDT" }
};

const els = {
  apiKeyInput: document.querySelector("#apiKeyInput"),
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
  clearSessionButton: document.querySelector("#clearSessionButton"),
  sessionStatusDot: document.querySelector("#sessionStatusDot"),
  sessionStatusText: document.querySelector("#sessionStatusText"),
  sessionUpdated: document.querySelector("#sessionUpdated"),
  dashboardTitle: document.querySelector("#dashboardTitle"),
  marketSymbol: document.querySelector("#marketSymbol"),
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
  tradingViewFrame: document.querySelector("#tradingViewFrame"),
  tradingViewLink: document.querySelector("#tradingViewLink"),
  tradingViewSource: document.querySelector("#tradingViewSource"),
  liqCanvas: document.querySelector("#liqCanvas"),
  fundingList: document.querySelector("#fundingList"),
  oiList: document.querySelector("#oiList"),
  hyperList: document.querySelector("#hyperList"),
  newsList: document.querySelector("#newsList"),
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

const state = {
  telemetry: readSession(),
  apiKey: localStorage.getItem(API_KEY_STORAGE) || "",
  priceSeries: [],
  lastPrice: null,
  signals: [],
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
els.ablyKeyInput.value = state.realtime.key;
els.ablyChannelInput.value = state.realtime.channelName;
els.elevenKeyInput.value = state.voice.apiKey;
els.elevenVoiceInput.value = state.voice.voiceId;
els.openaiKeyInput.value = state.copilot.apiKey;
els.openaiModelInput.value = state.copilot.model;
if (!state.voice.apiKey) els.voiceStatus.textContent = "Text response mode";
if (!state.copilot.apiKey) els.copilotStatus.textContent = "Local copilot fallback";

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
  const funding = state.market.hyperFunding == null ? "funding pending" : `funding ${formatPercent(state.market.hyperFunding, 4)}`;
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
  const price = Number(setup.price);
  const vwap = Number(setup.vwap);
  const signal = buildGeneratedSignal(setup, price, vwap);
  renderGeneratedSignal(signal);

  const signature = `${signal.asset}:${signal.action}:${Math.round(price || 0)}:${signal.score}:${Math.floor(Date.now() / 60000)}`;
  if (state.signals[0]?.signature !== signature) {
    state.signals.unshift({ ...signal, signature });
    state.signals = state.signals.slice(0, 8);
    renderSignalLog();
    pushLiveAlert({
      kind: "monatise signal",
      asset: signal.asset,
      title: `${signal.asset} ${signal.action}`,
      detail: `${signal.entryPlan} ${signal.gridHedge}. ${signal.invalidationPlan}`,
      payload: signal
    });
  }
}

function buildGeneratedSignal(setup, price, vwap) {
  const action = setup.direction === "BUY SETUP" ? "BUY" : setup.direction === "SELL SETUP" ? "SELL" : "WAIT";
  const atrPct = averageTrueRangePercent(state.priceSeries.slice(-24)) || 0.6;
  const riskPct = Math.max(0.35, Math.min(1.6, atrPct * 1.15));
  const entry = Number.isFinite(price) ? price : state.lastPrice;
  const invalidation = action === "BUY"
    ? entry * (1 - riskPct / 100)
    : action === "SELL"
      ? entry * (1 + riskPct / 100)
      : Number.isFinite(vwap) ? vwap : entry;
  const target = action === "BUY"
    ? Math.max(entry * (1 + riskPct / 100), Number.isFinite(vwap) ? vwap : entry)
    : action === "SELL"
      ? Math.min(entry * (1 - riskPct / 100), Number.isFinite(vwap) ? vwap : entry)
      : Number.isFinite(vwap) ? vwap : entry;
  const bestChecks = setup.checks
    .filter((check) => check.live || Math.abs(check.score) > 0)
    .slice(0, 4)
    .map((check) => `${check.name}: ${check.detail}`);
  return {
    asset: setup.asset,
    action,
    confidence: setup.confidence,
    score: setup.score,
    liveChecks: setup.liveChecks,
    checksTotal: setup.checks.length,
    entry,
    invalidation,
    target,
    entryPlan: action === "WAIT"
      ? "No entry until the framework score clears the setup threshold."
      : `${action} near ${formatUsd(entry)}; first target ${formatUsd(target)}.`,
    invalidationPlan: action === "WAIT"
      ? "VWAP and market structure are the wait-state guard rails."
      : `Invalidate on acceptance beyond ${formatUsd(invalidation)}.`,
    gridHedge: `${setup.gridDirection}; ${setup.hedgeDirection}`,
    gridHedgePlan: `${setup.gridPlan} ${setup.hedgePlan}`,
    thesis: `${setup.direction} · confidence ${setup.confidence}% · score ${setup.score >= 0 ? "+" : ""}${setup.score}`,
    evidence: bestChecks.length ? bestChecks.join(" · ") : "Framework checks are still warming up.",
    time: new Date().toLocaleTimeString()
  };
}

function renderGeneratedSignal(signal) {
  els.signalTimestamp.textContent = `Generated ${signal.time}`;
  els.signalState.textContent = signal.action === "WAIT" ? "watch signal" : "active signal";
  els.signalState.className = `pill ${signal.action === "BUY" ? "positive" : signal.action === "SELL" ? "negative" : ""}`;
  els.signalAsset.textContent = `${signal.asset} generated signal`;
  els.signalAction.textContent = signal.action;
  els.signalAction.className = signal.action === "BUY" ? "positive" : signal.action === "SELL" ? "negative" : "";
  els.signalThesis.textContent = signal.thesis;
  els.signalEntry.textContent = signal.action === "WAIT" ? "WAIT" : formatUsd(signal.entry);
  els.signalEntryPlan.textContent = signal.entryPlan;
  els.signalInvalidation.textContent = signal.action === "WAIT" ? "VWAP / structure" : formatUsd(signal.invalidation);
  els.signalInvalidationPlan.textContent = signal.invalidationPlan;
  els.signalGridHedge.textContent = signal.gridHedge;
  els.signalGridHedgePlan.textContent = signal.gridHedgePlan;
  els.signalEvidence.textContent = `${signal.liveChecks} / ${signal.checksTotal} checks`;
  els.signalEvidencePlan.textContent = signal.evidence;
}

function renderSignalLog() {
  if (!state.signals.length) {
    els.signalLog.innerHTML = `<div class="signal-row"><strong>No signals yet</strong><span>--</span><small>Waiting for the first framework pass.</small></div>`;
    return;
  }
  els.signalLog.innerHTML = state.signals.slice(0, 5).map((signal) => `
    <div class="signal-row">
      <strong class="${signal.action === "BUY" ? "positive" : signal.action === "SELL" ? "negative" : ""}">${signal.action}</strong>
      <span>${signal.asset} · ${signal.time}</span>
      <small>${signal.thesis} · ${signal.gridHedge}</small>
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
    return `${s.asset} is showing ${s.direction}. Grid instruction: ${s.grid}. ${s.gridPlan} VWAP is ${s.vwap}, and the framework has ${s.checks} live checks.`;
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
  const s = currentSetupSnapshot();
  return [
    `${s.asset} copilot fallback: ${s.direction} with ${s.confidence}.`,
    `Grid: ${s.grid}. ${s.gridPlan}`,
    `Hedge: ${s.hedge}. ${s.hedgePlan}`,
    `VWAP: ${s.vwap}; ${s.vwapSignal}. Funding ${s.funding}, OI ${s.oi}, liquidation bias ${s.liquidation}.`,
    question.trim() ? `Question handled locally: ${question.trim()}` : "Connect OpenAI in Integrations to unlock deeper copilot reasoning."
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
        "Do not invent live prices, exchange fills, or execution certainty.",
        "Answer with setup, grid, hedge, invalidation, and caution when relevant.",
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
  els.pricePanelTitle.textContent = `${asset.coin} Live Candles`;
  els.setupAsset.textContent = `${asset.coin} setup`;
  syncTradingView(asset);
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
        open: Number(row.open ?? row.close),
        close: Number(row.close),
        high: Number(row.high),
        low: Number(row.low),
        volume: Number(row.volume_usd)
      })).filter((row) => Number.isFinite(row.close) && Number.isFinite(row.high) && Number.isFinite(row.low));
    }
  }
  const binanceInterval = interval === "30m" ? "30m" : interval === "4h" ? "4h" : interval === "1d" ? "1d" : interval === "15m" ? "15m" : "1h";
  const payload = await timedFetch(
    `${asset.coin} price fallback`,
    "Binance public",
    `${BINANCE_BASE}/api/v3/klines?symbol=${asset.pair}&interval=${binanceInterval}&limit=96`
  );
  els.priceSource.textContent = "Binance public live candles · CoinGlass optional";
  return payload.map((row) => ({
    time: Number(row[0]),
    open: Number(row[1]),
    close: Number(row[4]),
    high: Number(row[2]),
    low: Number(row[3]),
    volume: Number(row[7])
  })).filter((row) => Number.isFinite(row.close) && Number.isFinite(row.high) && Number.isFinite(row.low));
}

async function getFunding() {
  const asset = selectedAsset();
  if (!hasKey()) throw new Error("CoinGlass optional integration inactive");
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
  if (!hasKey()) throw new Error("CoinGlass optional integration inactive");
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
  if (!hasKey()) throw new Error("CoinGlass optional integration inactive");
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
  els.fgSource.textContent = "Alternative.me public index · CoinGlass optional";
  return (fallback.data || []).reverse().map((row) => ({
    value: Number(row.value),
    time: Number(row.timestamp) * 1000,
    label: row.value_classification
  }));
}

async function getNews() {
  if (!hasKey()) throw new Error("CoinGlass optional integration inactive");
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
  const research = studyHistoricalPattern(series);
  renderResearch(research);
  const structure = analyzeMarketStructure(series, research);
  renderStructureSummary(structure);
  drawStructureChart(els.priceCanvas, series, structure, research);
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
  els.fundingAverage.textContent = "public mode";
  els.fundingAverage.className = "";
  els.fundingSource.textContent = "CoinGlass funding optional · Hyperliquid still confirms funding";
  els.fundingList.innerHTML = lockedRows("Funding rate", error.message, [
    "Primary endpoint: /api/futures/funding-rate/exchange-list",
    "Public mode uses Hyperliquid funding confirmation"
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
  els.openInterest.textContent = "public mode";
  els.oiSource.textContent = "CoinGlass OI optional · Hyperliquid still confirms open interest";
  els.oiList.innerHTML = lockedRows("Open interest", error.message, [
    `Primary endpoint: /api/futures/open-interest/exchange-list?symbol=${selectedCoin()}`,
    "Public mode uses Hyperliquid perp open interest"
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
    : "Modeled liquidity map · CoinGlass optional";
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
  els.liqSource.textContent = "Modeled liquidity map · CoinGlass optional";
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
  els.newsSource.textContent = "CoinGlass news optional";
  els.newsList.innerHTML = lockedRows("News alerts", error.message, [
    "Primary endpoint: /api/article/list",
    "Live alerts still emit setup, state, entry, and grid events"
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

  let gridDirection = `Neutral grid ${asset.coin}`;
  let gridPlan = "Use small two-sided grid or wait until funding/OI/liquidation checks align.";
  let hedgeDirection = "Flat hedge";
  let hedgePlan = "Stay capital-light until the setup confirms.";

  if (direction === "BUY SETUP") {
    gridDirection = `Buy grid ${asset.coin}`;
    gridPlan = gridPlanForResearch("buy", m.scaleAction, m.vwapSignal);
    hedgeDirection = hedgePct ? `Short hedge ${hedgePct}%` : "No hedge";
    hedgePlan = hedgePct ? "Keep a partial short while funding/liquidation risk is elevated." : "Long setup is clean enough to run unhedged.";
  } else if (direction === "SELL SETUP") {
    gridDirection = `Sell grid ${asset.coin}`;
    gridPlan = gridPlanForResearch("sell", m.scaleAction, m.vwapSignal);
    hedgeDirection = hedgePct ? `Long hedge ${hedgePct}%` : "No hedge";
    hedgePlan = hedgePct ? "Keep a partial long while squeeze or crowded-short risk is elevated." : "Short setup is clean enough to run unhedged.";
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
    price: state.lastPrice,
    vwap: m.vwap,
    vwapSignal: m.vwapSignal,
    scaleAction: m.scaleAction,
    checks
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

function lockedRows(title, detail, lines) {
  return lines.map((line, index) => `
    <div class="metric-row">
      <div>
        <strong>${index === 0 ? title : "Route"}</strong><br />
        <small>${line}</small>
      </div>
      <span class="metric-value">${index === 0 ? "optional" : detail}</span>
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
  const setup = applyMonatiseFramework();
  publishGeneratedSignal(setup);
  evaluateLiveAlerts(setup);
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
els.assetSelect.addEventListener("change", () => {
  resetMarketContext();
  state.realtime.lastSetup = null;
  state.realtime.lastEntrySignal = null;
  state.realtime.lastGridCompletion = null;
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
  resizeAtlas();
});

renderTelemetry();
renderLiveAlerts();
renderSignalLog();
initLiquidityAtlas();
updateLiquidityAtlas();
connectRealtime();
refreshDashboard();
setInterval(refreshDashboard, 60_000);
