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
  armStrategyButton: document.querySelector("#armStrategyButton"),
  authForm: document.querySelector("#authForm"),
  auditCount: document.querySelector("#auditCount"),
  baseInput: document.querySelector("#baseInput"),
  backendStartButton: document.querySelector("#backendStartButton"),
  backendStatus: document.querySelector("#backendStatus"),
  backendStopButton: document.querySelector("#backendStopButton"),
  billingCheckoutButton: document.querySelector("#billingCheckoutButton"),
  billingStatus: document.querySelector("#billingStatus"),
  accountMetricLabel: document.querySelector("#accountMetricLabel"),
  activationList: document.querySelector("#activationList"),
  activationNext: document.querySelector("#activationNext"),
  activationStatus: document.querySelector("#activationStatus"),
  authStatus: document.querySelector("#authStatus"),
  candleCount: document.querySelector("#candleCount"),
  cashMetricLabel: document.querySelector("#cashMetricLabel"),
  chartIntervalSelect: document.querySelector("#chartIntervalSelect"),
  clientNameInput: document.querySelector("#clientNameInput"),
  coinGlassFearGreed: document.querySelector("#coinGlassFearGreed"),
  coinGlassFunding: document.querySelector("#coinGlassFunding"),
  coinGlassLiquidations: document.querySelector("#coinGlassLiquidations"),
  coinGlassOpenInterest: document.querySelector("#coinGlassOpenInterest"),
  coinglassServices: document.querySelector("#coinglassServices"),
  cioBrief: document.querySelector("#cioBrief"),
  cioDrivers: document.querySelector("#cioDrivers"),
  cioPosture: document.querySelector("#cioPosture"),
  credentialStatus: document.querySelector("#credentialStatus"),
  contextRadar: document.querySelector("#contextRadar"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  chatMessages: document.querySelector("#chatMessages"),
  decisionAccount: document.querySelector("#decisionAccount"),
  decisionAsset: document.querySelector("#decisionAsset"),
  decisionDetail: document.querySelector("#decisionDetail"),
  decisionDrawdown: document.querySelector("#decisionDrawdown"),
  decisionExposure: document.querySelector("#decisionExposure"),
  decisionState: document.querySelector("#decisionState"),
  equityCanvas: document.querySelector("#equityCanvas"),
  equityMetric: document.querySelector("#equityMetric"),
  drawdownMetric: document.querySelector("#drawdownMetric"),
  drawdownLimitInput: document.querySelector("#drawdownLimitInput"),
  feeInput: document.querySelector("#feeInput"),
  feesMetric: document.querySelector("#feesMetric"),
  fillCount: document.querySelector("#fillCount"),
  fillTape: document.querySelector("#fillTape"),
  fibAnalysis: document.querySelector("#fibAnalysis"),
  harvestMetric: document.querySelector("#harvestMetric"),
  hedgeNote: document.querySelector("#hedgeNote"),
  hedgeStatus: document.querySelector("#hedgeStatus"),
  hedgeSummary: document.querySelector("#hedgeSummary"),
  inventoryMetric: document.querySelector("#inventoryMetric"),
  installAppButton: document.querySelector("#installAppButton"),
  lastFill: document.querySelector("#lastFill"),
  levelsInput: document.querySelector("#levelsInput"),
  levelsValue: document.querySelector("#levelsValue"),
  liquiditySource: document.querySelector("#liquiditySource"),
  credentialGate: document.querySelector("#credentialGate"),
  liveDeskStatus: document.querySelector("#liveDeskStatus"),
  liveModeStatus: document.querySelector("#liveModeStatus"),
  liveNetworkBadge: document.querySelector("#liveNetworkBadge"),
  loginGate: document.querySelector("#loginGate"),
  loginButton: document.querySelector("#loginButton"),
  emailLoginCodeButton: document.querySelector("#emailLoginCodeButton"),
  loginCodePanel: document.querySelector("#loginCodePanel"),
  loginCodeInput: document.querySelector("#loginCodeInput"),
  completeLoginCodeButton: document.querySelector("#completeLoginCodeButton"),
  cancelLoginCodeButton: document.querySelector("#cancelLoginCodeButton"),
  loginCodeStatus: document.querySelector("#loginCodeStatus"),
  logoutButton: document.querySelector("#logoutButton"),
  market3dMeta: document.querySelector("#market3dMeta"),
  markPrice: document.querySelector("#markPrice"),
  market3dMap: document.querySelector("#market3dMap"),
  market3dTitle: document.querySelector("#market3dTitle"),
  marketRadar: document.querySelector("#marketRadar"),
  marketStrip: document.querySelector("#marketStrip"),
  marketTitle: document.querySelector("#marketTitle"),
  maxPositionValueInput: document.querySelector("#maxPositionValueInput"),
  maxTotalNotionalInput: document.querySelector("#maxTotalNotionalInput"),
  orderSizeInput: document.querySelector("#orderSizeInput"),
  executionModeMetric: document.querySelector("#executionModeMetric"),
  openNotionalMetric: document.querySelector("#openNotionalMetric"),
  openOrderBook: document.querySelector("#openOrderBook"),
  openOrderCount: document.querySelector("#openOrderCount"),
  openGridTitle: document.querySelector("#openGridTitle"),
  operatorDeploy: document.querySelector("#operatorDeploy"),
  operatorGrid: document.querySelector("#operatorGrid"),
  operatorRunbook: document.querySelector("#operatorRunbook"),
  operatorStatus: document.querySelector("#operatorStatus"),
  opportunityAction: document.querySelector("#opportunityAction"),
  opportunityScore: document.querySelector("#opportunityScore"),
  orderAgeMetric: document.querySelector("#orderAgeMetric"),
  passwordInput: document.querySelector("#passwordInput"),
  passwordToggle: document.querySelector("#passwordToggle"),
  quoteInput: document.querySelector("#quoteInput"),
  quiverContext: document.querySelector("#quiverContext"),
  readinessChecklist: document.querySelector("#readinessChecklist"),
  riskBudgetMetric: document.querySelector("#riskBudgetMetric"),
  exchangeOrderMetric: document.querySelector("#exchangeOrderMetric"),
  registerButton: document.querySelector("#registerButton"),
  rememberLoginInput: document.querySelector("#rememberLoginInput"),
  forgotPasswordButton: document.querySelector("#forgotPasswordButton"),
  cancelRecoveryButton: document.querySelector("#cancelRecoveryButton"),
  newPasswordInput: document.querySelector("#newPasswordInput"),
  recoveryCodeBox: document.querySelector("#recoveryCodeBox"),
  recoveryCodeInput: document.querySelector("#recoveryCodeInput"),
  recoveryCodeValue: document.querySelector("#recoveryCodeValue"),
  recoveryPanel: document.querySelector("#recoveryPanel"),
  recoveryStatus: document.querySelector("#recoveryStatus"),
  researchNarrative: document.querySelector("#researchNarrative"),
  researchStats: document.querySelector("#researchStats"),
  researchStatus: document.querySelector("#researchStatus"),
  resetPasswordButton: document.querySelector("#resetPasswordButton"),
  rotateRecoveryCodeButton: document.querySelector("#rotateRecoveryCodeButton"),
  resetButton: document.querySelector("#resetButton"),
  riskGate: document.querySelector("#riskGate"),
  riskStatus: document.querySelector("#riskStatus"),
  journalStats: document.querySelector("#journalStats"),
  rulesStatus: document.querySelector("#rulesStatus"),
  rulesSummary: document.querySelector("#rulesSummary"),
  ruleOrderSizeInput: document.querySelector("#ruleOrderSizeInput"),
  runButton: document.querySelector("#runButton"),
  runState: document.querySelector("#runState"),
  saveRulesButton: document.querySelector("#saveRulesButton"),
  saveCredentialsButton: document.querySelector("#saveCredentialsButton"),
  sessionGuardSelect: document.querySelector("#sessionGuardSelect"),
  secretKeyInput: document.querySelector("#secretKeyInput"),
  signalJournal: document.querySelector("#signalJournal"),
  signalWindowSelect: document.querySelector("#signalWindowSelect"),
  saveSpotifyButton: document.querySelector("#saveSpotifyButton"),
  runtimeLog: document.querySelector("#runtimeLog"),
  spacingInput: document.querySelector("#spacingInput"),
  spacingValue: document.querySelector("#spacingValue"),
  spotifyPanel: document.querySelector("#spotifyPanel"),
  spotifyPlaylistInput: document.querySelector("#spotifyPlaylistInput"),
  stepButton: document.querySelector("#stepButton"),
  staleGridCancelInput: document.querySelector("#staleGridCancelInput"),
  strategyReadout: document.querySelector("#strategyReadout"),
  subscriptionStatus: document.querySelector("#subscriptionStatus"),
  symbolInput: document.querySelector("#symbolInput"),
  syncMetric: document.querySelector("#syncMetric"),
  ticketAsset: document.querySelector("#ticketAsset"),
  ticketCapital: document.querySelector("#ticketCapital"),
  ticketChart: document.querySelector("#ticketChart"),
  ticketDrawdown: document.querySelector("#ticketDrawdown"),
  ticketExposure: document.querySelector("#ticketExposure"),
  ticketNote: document.querySelector("#ticketNote"),
  ticketStatus: document.querySelector("#ticketStatus"),
  ticketSummary: document.querySelector("#ticketSummary"),
  themeModeSelect: document.querySelector("#themeModeSelect"),
  tradeAuditLog: document.querySelector("#tradeAuditLog"),
  languageSelect: document.querySelector("#languageSelect"),
  openTradingViewButton: document.querySelector("#openTradingViewButton"),
  tradingViewSignalPanel: document.querySelector("#tradingViewSignalPanel"),
  tradingViewMeta: document.querySelector("#tradingViewMeta"),
  tradingViewWidget: document.querySelector("#tradingViewWidget"),
  londonCommodityInput: document.querySelector("#londonCommodityInput"),
  finishOnboardingButton: document.querySelector("#finishOnboardingButton"),
  onboardingAccount: document.querySelector("#onboardingAccount"),
  onboardingContact: document.querySelector("#onboardingContact"),
  onboardingDrawdown: document.querySelector("#onboardingDrawdown"),
  onboardingPlan: document.querySelector("#onboardingPlan"),
  onboardingStatus: document.querySelector("#onboardingStatus"),
  registrationDesk: document.querySelector("#registrationDesk"),
  usernameInput: document.querySelector("#usernameInput")
};

let state = null;
let backendOnline = false;
let currentUser = { authenticated: false, credentialsConfigured: false };
let markets = [];
let marketGroups = {};
let selectableAssets = [];
let selectedAsset = "BTC";
let marketScene = null;
let lastBackendSnapshot = null;
let operatorStatus = null;
let fibAnalysis = null;
let fvgAnalysis = null;
let fibLoading = false;
let fibLastLoadedAt = 0;
let fibLastSymbol = "";
let contextRadar = null;
let contextLoading = false;
let contextLastLoadedAt = 0;
let contextLastSymbol = "";
let coinGlassContext = null;
let coinGlassLoading = false;
let coinGlassLastLoadedAt = 0;
let coinGlassLastSymbol = "";
let quiverContext = null;
let quiverLoading = false;
let quiverLastLoadedAt = 0;
let quiverLastSymbol = "";
let candleSource = { interval: "sample", symbol: "BTC", type: "sample" };
let candleLoading = false;
let candleLoadingSymbol = "";
let candleLoadSequence = 0;
let initialLiveCandlesLoaded = false;
let liveEquityCurve = [];
let localAuditEvents = [];
let lastTicketHealth = null;
let lastSignalCandidate = null;
let lastSignalStructureSignature = "";
let lastStructuredSignal = null;
let lastStructuredSignalCreatedAt = "";
let lastTicketSnapshot = null;
let pendingArmReview = false;
let deferredInstallPrompt = null;
let latestTradingViewSignal = null;
let latestTradingViewSignalSignature = "";
let candleCsvBuffer = sampleCsv;
let tradingRules = {
  chartInterval: "1h",
  leverage: 10,
  signalSessionWindow: "always",
  londonCommodityOnly: true,
  maxDailyLossPct: 0.05,
  orderQuoteSize: 25,
  maxOrderNotional: 25,
  maxTotalNotional: 5000,
  maxPositionValue: 5000,
  sessionGuardMinutes: 60,
  staleGridCancel: true
};
localStorage.removeItem("monatiseControlToken");

const preferenceKeys = {
  language: "monatiseLanguage:v1",
  theme: "monatiseTheme:v1"
};

let selectedTheme = localStorage.getItem(preferenceKeys.theme) || "light";
let selectedLanguage = localStorage.getItem(preferenceKeys.language) || "en";

const languageCopy = {
  en: {
    about: "About",
    activity: "Activity",
    activation: "Activation",
    aiChat: "AI Chat",
    asset: "Asset",
    cioBrief: "CIO Brief",
    dashboard: "Market Dashboard",
    dark: "Dark",
    generate: "Generate",
    hedgeLayer: "Hedge Layer",
    installApp: "Install App",
    language: "Language",
    light: "Light",
    login: "Login",
    marketIntel: "Market Intel",
    mode: "Mode",
    operator: "Operator",
    privateAccess: "Private Access",
    requestAccess: "Request Access",
    reset: "Reset",
    riskLens: "Risk Lens",
    signal: "Signal",
    signalBuilder: "Signal Builder",
    signalConsole: "Signal Console",
    theme: "Theme",
    workspace: "Workspace"
  },
  fr: {
    about: "A propos",
    activity: "Activite",
    activation: "Activation",
    aiChat: "Chat IA",
    asset: "Actif",
    cioBrief: "Brief CIO",
    dashboard: "Tableau Marche",
    dark: "Sombre",
    generate: "Generer",
    hedgeLayer: "Couverture",
    installApp: "Installer",
    language: "Langue",
    light: "Clair",
    login: "Connexion",
    marketIntel: "Intel Marche",
    mode: "Mode",
    operator: "Operateur",
    privateAccess: "Acces Prive",
    requestAccess: "Demander Acces",
    reset: "Reinitialiser",
    riskLens: "Risque",
    signal: "Signal",
    signalBuilder: "Generateur",
    signalConsole: "Console Signal",
    theme: "Theme",
    workspace: "Espace"
  },
  es: {
    about: "Acerca",
    activity: "Actividad",
    activation: "Activacion",
    aiChat: "Chat IA",
    asset: "Activo",
    cioBrief: "Informe CIO",
    dashboard: "Panel Mercado",
    dark: "Oscuro",
    generate: "Generar",
    hedgeLayer: "Cobertura",
    installApp: "Instalar",
    language: "Idioma",
    light: "Claro",
    login: "Entrar",
    marketIntel: "Intel Mercado",
    mode: "Modo",
    operator: "Operador",
    privateAccess: "Acceso Privado",
    requestAccess: "Solicitar Acceso",
    reset: "Reiniciar",
    riskLens: "Riesgo",
    signal: "Senal",
    signalBuilder: "Constructor",
    signalConsole: "Consola",
    theme: "Tema",
    workspace: "Espacio"
  },
  pt: {
    about: "Sobre",
    activity: "Atividade",
    activation: "Ativacao",
    aiChat: "Chat IA",
    asset: "Ativo",
    cioBrief: "Brief CIO",
    dashboard: "Painel Mercado",
    dark: "Escuro",
    generate: "Gerar",
    hedgeLayer: "Protecao",
    installApp: "Instalar",
    language: "Idioma",
    light: "Claro",
    login: "Entrar",
    marketIntel: "Intel Mercado",
    mode: "Modo",
    operator: "Operador",
    privateAccess: "Acesso Privado",
    requestAccess: "Pedir Acesso",
    reset: "Redefinir",
    riskLens: "Risco",
    signal: "Sinal",
    signalBuilder: "Construtor",
    signalConsole: "Console Sinal",
    theme: "Tema",
    workspace: "Espaco"
  }
};

function t(key) {
  return languageCopy[selectedLanguage]?.[key] || languageCopy.en[key] || key;
}

function applyThemePreference(theme = selectedTheme) {
  selectedTheme = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = selectedTheme;
  localStorage.setItem(preferenceKeys.theme, selectedTheme);
  if (els.themeModeSelect) els.themeModeSelect.value = selectedTheme;
  renderTradingViewChart();
}

function applyLanguagePreference(language = selectedLanguage) {
  selectedLanguage = languageCopy[language] ? language : "en";
  document.documentElement.lang = selectedLanguage;
  localStorage.setItem(preferenceKeys.language, selectedLanguage);
  if (els.languageSelect) els.languageSelect.value = selectedLanguage;
  if (els.themeModeSelect) {
    const light = els.themeModeSelect.querySelector('option[value="light"]');
    const dark = els.themeModeSelect.querySelector('option[value="dark"]');
    if (light) light.textContent = t("light");
    if (dark) dark.textContent = t("dark");
  }
  const languageLabels = document.querySelectorAll(".desk-preferences label span");
  if (languageLabels[0]) languageLabels[0].textContent = t("theme");
  if (languageLabels[1]) languageLabels[1].textContent = t("language");
  const nav = document.querySelectorAll(".desk-nav a");
  if (nav[0]) nav[0].textContent = t("signalConsole");
  if (nav[1]) nav[1].textContent = t("dashboard");
  if (nav[2]) nav[2].textContent = "Crypto Trainer";
  if (els.installAppButton) els.installAppButton.textContent = t("installApp");
  const jumps = document.querySelectorAll(".desk-jump-nav a");
  [
    t("signalBuilder"),
    t("cioBrief"),
    "Quality Gate",
    t("activation"),
    t("operator"),
    t("marketIntel"),
    "Crypto Trainer",
    t("hedgeLayer"),
    t("aiChat"),
    t("privateAccess"),
    t("about"),
    t("activity")
  ].forEach((label, index) => {
    if (jumps[index]) jumps[index].textContent = label;
  });
  const ops = document.querySelectorAll(".ops-ribbon article span");
  if (ops[0]) ops[0].textContent = t("workspace");
  if (ops[1]) ops[1].textContent = t("mode");
  if (ops[2]) ops[2].textContent = t("riskLens");
  if (ops[3]) ops[3].textContent = "Alert Size";
  if (els.runButton) els.runButton.textContent = t("generate");
  if (els.resetButton) els.resetButton.textContent = t("reset");
  if (els.loginButton) els.loginButton.textContent = t("login");
  if (els.registerButton) els.registerButton.textContent = t("requestAccess");
}

const assetMetadata = {
  AAPL: { name: "Apple", route: "TradingView stock watch" },
  BNB: { name: "BNB", route: "Core Hyperliquid perp" },
  BTC: { name: "Bitcoin", route: "Core Hyperliquid perp" },
  DOGE: { name: "Dogecoin", route: "Core Hyperliquid perp" },
  ETH: { name: "Ethereum", route: "Core Hyperliquid perp" },
  HYPE: { name: "Hyperliquid", route: "Core Hyperliquid perp" },
  NDX: { name: "Nasdaq 100", route: "TradingView index watch" },
  NASDAQ: { name: "Nasdaq Composite", route: "TradingView index watch" },
  NVDA: { name: "NVIDIA", route: "TradingView stock watch" },
  QQQ: { name: "Invesco QQQ", route: "TradingView ETF watch" },
  SOL: { name: "Solana", route: "Core Hyperliquid perp" },
  SPX: { name: "S&P 500", route: "TradingView index watch" },
  SPY: { name: "SPDR S&P 500 ETF", route: "TradingView ETF watch" },
  TSLA: { name: "Tesla", route: "TradingView stock watch" },
  XRP: { name: "XRP", route: "Core Hyperliquid perp" }
};

const tradingViewSymbols = {
  AAPL: "NASDAQ:AAPL",
  BNB: "BINANCE:BNBUSDT",
  BTC: "BINANCE:BTCUSDT",
  DOGE: "BINANCE:DOGEUSDT",
  ETH: "BINANCE:ETHUSDT",
  HYPE: "CRYPTO:HYPEUSD",
  NDX: "TVC:NDX",
  NASDAQ: "TVC:IXIC",
  NVDA: "NASDAQ:NVDA",
  QQQ: "NASDAQ:QQQ",
  SOL: "BINANCE:SOLUSDT",
  SPX: "TVC:SPX",
  SPY: "AMEX:SPY",
  TSLA: "NASDAQ:TSLA",
  XRP: "BINANCE:XRPUSDT"
};

const tradingViewIntervals = {
  "30m": "30",
  "1h": "60",
  "2h": "120",
  "4h": "240",
  "6h": "360",
  "8h": "480",
  "12h": "720",
  "1d": "D",
  "1w": "W"
};

const commoditySymbols = [];
const economicBlackoutMinutes = 60;
const economicReleases = [
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-01-13T13:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-01-14T13:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-01-30T13:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-02-13T13:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-02-27T13:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-03-11T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-03-18T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-04-10T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-04-14T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-05-12T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-05-13T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-06-10T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-06-11T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-07-14T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-07-15T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-08-12T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-08-13T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-09-10T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-09-11T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-10-14T12:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-10-15T12:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-11-10T13:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-11-13T13:30:00Z" },
  { code: "CPI", name: "Consumer Price Index", releaseTime: "2026-12-10T13:30:00Z" },
  { code: "PPI", name: "Producer Price Index", releaseTime: "2026-12-15T13:30:00Z" }
];

function isEmailOrPhoneUsername(value) {
  const normalized = value.trim();
  const phonePattern = /^\+?[0-9][0-9\s().-]{6,}[0-9]$/;
  return isEmailUsername(normalized) || phonePattern.test(normalized);
}

function isEmailUsername(value) {
  const normalized = value.trim();
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  return emailPattern.test(normalized);
}

function clientProfileKey(username) {
  return `monatiseClientProfile:${String(username || "").trim().toLowerCase()}`;
}

function loadClientProfile(username) {
  if (!username) return {};
  try {
    return JSON.parse(localStorage.getItem(clientProfileKey(username)) || "{}");
  } catch {
    return {};
  }
}

function saveClientProfile(username) {
  if (!username) return {};
  const profile = {
    clientName: els.clientNameInput.value.trim(),
    contact: String(username).trim(),
    updatedAt: new Date().toISOString()
  };
  localStorage.setItem(clientProfileKey(username), JSON.stringify(profile));
  return profile;
}

async function saveProfileDetails() {
  const clientName = els.clientNameInput.value.trim();
  const response = await jsonPost("/api/profile", { clientName });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Could not save profile details");
  }
  saveClientProfile(payload.username || currentUser.username);
  renderAuth(payload);
  return payload;
}

function rememberedLoginKey() {
  return "monatiseRememberedLogin:v1";
}

function loadRememberedLogin() {
  try {
    return JSON.parse(localStorage.getItem(rememberedLoginKey()) || "{}");
  } catch {
    return {};
  }
}

function applyRememberedLogin(serverRemembered = {}) {
  const remembered = loadRememberedLogin();
  const username = remembered.username || serverRemembered.username || "";
  if (username && !els.usernameInput.value.trim()) {
    els.usernameInput.value = username;
  }
  els.rememberLoginInput.checked = Boolean(remembered.username || serverRemembered.username);
  if (!remembered.username && serverRemembered.username && els.credentialStatus) {
    els.credentialStatus.textContent = "Profile remembered for this network. Enter your password to continue.";
  }
}

function updateRememberedLogin(username) {
  if (els.rememberLoginInput.checked) {
    localStorage.setItem(rememberedLoginKey(), JSON.stringify({ username: String(username || "").trim().toLowerCase() }));
    return;
  }
  localStorage.removeItem(rememberedLoginKey());
}

function setPasswordAutocomplete(isRegister) {
  els.passwordInput.setAttribute("autocomplete", isRegister ? "new-password" : "current-password");
}

function setupAppInstall() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    els.installAppButton.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    els.installAppButton.hidden = true;
  });
}

function renderRegistrationDesk(me = currentUser) {
  const loggedIn = Boolean(me.authenticated);
  els.registrationDesk.hidden = !loggedIn;
  if (!loggedIn) return;
  const profile = loadClientProfile(me.username);
  if (me.clientName && els.clientNameInput.value.trim() !== me.clientName) {
    els.clientNameInput.value = me.clientName;
  } else if (profile.clientName && !els.clientNameInput.value.trim()) {
    els.clientNameInput.value = profile.clientName;
  }
  const clientName = els.clientNameInput.value.trim() || me.clientName || profile.clientName || "Client";
  const syncReady = Boolean(me.credentialsConfigured);
  const planText = "Private access";
  els.onboardingContact.textContent = `${clientName} / ${me.username}`;
  els.onboardingDrawdown.textContent = `${(tradingRules.maxDailyLossPct * 100).toFixed(1).replace(/\.0$/, "")}% cap`;
  els.onboardingAccount.textContent = syncReady ? "Saved" : "Optional";
  els.onboardingPlan.textContent = planText;
  els.onboardingStatus.textContent = loggedIn && hasLivePlan() ? "Profile ready" : "Pending save";
}

function setGate(element, label, status, className = "") {
  element.classList.remove("ready", "warn", "hot");
  if (className) element.classList.add(className);
  element.querySelector("span").textContent = label;
  element.querySelector("strong").textContent = status;
}

function readinessClass(item) {
  if (item.ok) return "pass";
  return item.severity === "block" ? "block" : "warn";
}

function readinessItems(snapshot = null) {
  const backendItems = Array.isArray(snapshot?.readiness) ? snapshot.readiness : [];
  const localItems = localReadinessItems(snapshot);
  const localLabels = new Set(localItems.map((item) => item.label));
  return [...localItems, ...backendItems.filter((item) => !localLabels.has(item.label))];
}

function readinessBlocks(snapshot = null) {
  return readinessItems(snapshot).filter((item) => !item.ok && item.severity === "block");
}

function signalSafetyBlocks(snapshot = null) {
  const nonSignalLabels = new Set(["User session", "Private sync", "Signal access"]);
  return readinessBlocks(snapshot).filter((item) => !nonSignalLabels.has(item.label));
}

function signalHasExecutablePlan(signal) {
  if (!["LONG", "SHORT"].includes(signal?.direction)) return false;
  const entry = Number(signal.entry);
  const stop = Number(signal.stop);
  const target = Number(signal.targetOne);
  if (![entry, stop, target].every((value) => Number.isFinite(value) && value > 0)) return false;
  if (signal.direction === "LONG") return stop < entry && target > entry;
  return stop > entry && target < entry;
}

function activationStepClass(step) {
  if (step.done) return "done";
  if (step.current) return "current";
  return "pending";
}

function activationSteps(snapshot = null) {
  const loggedIn = Boolean(currentUser.authenticated);
  const hasCredentials = Boolean(currentUser.credentialsConfigured);
  const mark = Number(snapshot?.markPrice ?? currentMarketPrice());
  const marketReady = backendOnline && Number.isFinite(mark) && mark > 0;
  const mode = snapshot?.mode || "paper";
  const network = snapshot?.network || "local";
  const running = Boolean(snapshot?.running);
  const liveReady = Boolean(snapshot?.liveReady);
  const requires = Array.isArray(snapshot?.requires) ? snapshot.requires : [];
  const risk = snapshot?.risk || {};
  const serverRules = snapshot?.tradingRules || {};
  const maxOrder = Number(serverRules.maxOrderNotional ?? risk.max_order_notional ?? tradingRules.orderQuoteSize);
  const maxTotal = Number(serverRules.maxTotalNotional ?? risk.max_total_notional ?? tradingRules.maxTotalNotional);
  const tinyCaps = Number.isFinite(maxOrder) && Number.isFinite(maxTotal) && maxOrder <= 25 && maxTotal <= 150;

  const steps = [
    {
      detail: loggedIn ? currentUser.username || "profile active" : "Register or log in before saving settings.",
      done: loggedIn,
      label: "Profile",
      next: "Create or log in to a profile."
    },
    {
      detail: marketReady ? `${assetLabel(selectedAsset)} feed is online.` : "Wait for CoinGlass and market mark data.",
      done: marketReady,
      label: "Market data",
      next: "Confirm the market feed is online."
    },
    {
      detail: hasCredentials ? "Hyperliquid private sync details are saved." : "Save the account address and API key when you are ready for private sync.",
      done: hasCredentials,
      label: "Private sync",
      next: "Save private sync details."
    },
    {
      detail:
        running && (mode === "paper" || network === "testnet")
          ? `${mode} ${network} loop is running.`
          : "Run paper or testnet before mainnet.",
      done: running && (mode === "paper" || network === "testnet"),
      label: "Paper or testnet",
      next: "Start private sync in paper or testnet."
    },
    {
      detail: tinyCaps ? `${money(maxOrder)} order cap and ${money(maxTotal)} total cap.` : "Keep first live caps tiny before expanding.",
      done: tinyCaps,
      label: "Tiny risk caps",
      next: "Set tiny first-live caps."
    },
    {
      detail:
        liveReady && mode === "live" && network === "mainnet" && requires.length === 0
          ? "Live mainnet gates are armed."
          : requires.length
            ? requires[0]
            : "Mainnet stays gated until rehearsal is complete.",
      done: liveReady && mode === "live" && network === "mainnet" && requires.length === 0,
      label: "Mainnet gate",
      next: "Move to mainnet only after rehearsal."
    }
  ];

  const nextIndex = steps.findIndex((step) => !step.done);
  return steps.map((step, index) => ({ ...step, current: index === nextIndex }));
}

function renderActivationPath(snapshot = null) {
  if (!els.activationList) return;
  const steps = activationSteps(snapshot);
  const nextStep = steps.find((step) => step.current);
  const complete = steps.every((step) => step.done);
  els.activationStatus.textContent = complete ? "Ready for monitored live" : nextStep?.label || "Ready";
  els.activationNext.textContent = complete ? "Keep caps small and monitor every live start." : nextStep?.next || "Review the live desk.";
  els.activationList.innerHTML = steps
    .map(
      (step, index) => `<article class="${activationStepClass(step)}">
        <span>${String(index + 1).padStart(2, "0")}</span>
        <div>
          <strong>${step.label}</strong>
          <em>${step.detail}</em>
        </div>
      </article>`
    )
    .join("");
}

function operatorCardClass(ok, warn = false) {
  if (ok) return "ok";
  return warn ? "warn" : "block";
}

function compactCommit(value) {
  const commit = String(value || "").trim();
  return commit ? commit.slice(0, 7) : "unknown";
}

function operatorCards(status = operatorStatus, snapshot = lastBackendSnapshot) {
  const integrations = status?.integrations || {};
  const riskCaps = status?.riskCaps || {};
  const events = Array.isArray(snapshot?.events) ? snapshot.events : [];
  const lastEvent = events[events.length - 1];
  const running = Boolean(snapshot?.running);
  const liveReady = Boolean(snapshot?.liveReady);
  const requires = Array.isArray(snapshot?.requires) ? snapshot.requires : [];
  const orderCap = Number(riskCaps.maxOrderNotional);
  const totalCap = Number(riskCaps.maxTotalNotional);
  const tinyCaps = Number.isFinite(orderCap) && Number.isFinite(totalCap) && orderCap <= 25 && totalCap <= 150;
  return [
    {
      detail: status ? `${String(status.mode || "paper").toUpperCase()} / ${String(status.network || "local").toUpperCase()}` : "waiting for /api/operator",
      label: "Runtime",
      ok: Boolean(status?.ok),
      value: status?.executionMode || "checking"
    },
    {
      detail: status?.deploy?.serviceId ? `service ${status.deploy.serviceId}` : status?.publicUrl || "Render deploy metadata",
      label: "Deploy",
      ok: Boolean(status?.ok),
      value: compactCommit(status?.deploy?.commit)
    },
    {
      detail: integrations.coinglass?.configured ? `exchange ${integrations.coinglass.exchange || "Binance"}` : "set COINGLASS_API_KEY",
      label: "CoinGlass",
      ok: Boolean(integrations.coinglass?.configured),
      value: integrations.coinglass?.configured ? "configured" : "missing"
    },
    {
      detail: integrations.tradingView?.configured ? "webhook token ready" : "set MONATISE_TRADINGVIEW_WEBHOOK_TOKEN",
      label: "TradingView",
      ok: Boolean(integrations.tradingView?.configured),
      value: integrations.tradingView?.configured ? "ready" : "missing"
    },
    {
      detail: integrations.quiver?.configured ? integrations.quiver.role || "stock and ETF alternative data" : "set QUIVER_API_KEY",
      label: "Quiver",
      ok: Boolean(integrations.quiver?.configured),
      warn: !isQuiverAsset(selectedAsset),
      value: integrations.quiver?.configured ? "ready" : "optional"
    },
    {
      detail: integrations.smtp?.configured
        ? `${integrations.smtp.provider || "smtp"}${integrations.smtp.alertsConfigured ? " alerts" : " reset only"}`
        : "configure sender, host/provider, and password",
      label: "Email",
      ok: Boolean(integrations.smtp?.configured),
      value: integrations.smtp?.configured ? "ready" : "missing"
    },
    {
      detail: integrations.credentialStorage?.encrypted ? "encrypted profile credential storage" : "set MONATISE_ENCRYPTION_KEY",
      label: "Credentials",
      ok: Boolean(integrations.credentialStorage?.encrypted),
      value: integrations.credentialStorage?.encrypted ? "encrypted" : "not ready"
    },
    {
      detail: tinyCaps ? `${money(orderCap)} order / ${money(totalCap)} total` : "first live rehearsal should stay tiny",
      label: "Risk caps",
      ok: tinyCaps,
      warn: true,
      value: tinyCaps ? "tiny" : "review"
    },
    {
      detail: requires.length ? requires[0] : liveReady ? "live gates clear" : running ? "loop running" : "not running",
      label: "Private sync",
      ok: running || liveReady,
      warn: true,
      value: running ? "running" : liveReady ? "armed" : "idle"
    },
    {
      detail: lastEvent?.message || snapshot?.riskStatus || "no runtime events yet",
      label: "Last event",
      ok: !/error|failed|max daily loss|guard/i.test(lastEvent?.message || snapshot?.riskStatus || ""),
      warn: true,
      value: lastEvent?.level || "standby"
    }
  ];
}

function renderOperatorConsole(snapshot = lastBackendSnapshot) {
  if (!els.operatorGrid) return;
  const cards = operatorCards(operatorStatus, snapshot);
  const hardBlocks = cards.filter((card) => !card.ok && !card.warn).length;
  const warnings = cards.filter((card) => !card.ok && card.warn).length;
  const mode = operatorStatus ? `${String(operatorStatus.mode || "paper").toUpperCase()} ${String(operatorStatus.network || "local").toUpperCase()}` : "Checking";
  els.operatorStatus.textContent = hardBlocks ? `${hardBlocks} operator block${hardBlocks === 1 ? "" : "s"}` : warnings ? `${warnings} operator watch${warnings === 1 ? "" : "es"}` : "Operator ready";
  els.operatorDeploy.textContent = `${mode} · ${compactCommit(operatorStatus?.deploy?.commit)}`;
  els.operatorGrid.innerHTML = cards
    .map(
      (card) => `<article class="${operatorCardClass(card.ok, card.warn)}">
        <span>${card.label}</span>
        <strong>${card.value}</strong>
        <em>${card.detail}</em>
      </article>`
    )
    .join("");
  const primaryBlock = cards.find((card) => !card.ok && !card.warn) || cards.find((card) => !card.ok);
  els.operatorRunbook.textContent = primaryBlock
    ? `Next operator action: ${primaryBlock.detail}.`
    : "Operator action: run the first-user rehearsal, keep caps small, and monitor the runtime log.";
}

async function loadOperatorStatus() {
  try {
    const response = await apiFetch("/api/operator", { cache: "no-store" });
    if (!response.ok) throw new Error("operator status unavailable");
    operatorStatus = await response.json();
  } catch {
    operatorStatus = null;
  }
  renderOperatorConsole(lastBackendSnapshot);
}

function auditLevelFromType(type) {
  if (/block|failed|error|stop/i.test(type)) return "error";
  if (/review|watch|rules|credential/i.test(type)) return "warn";
  return "info";
}

function addAuditEvent(type, message, details = "") {
  localAuditEvents = [
    ...localAuditEvents,
    {
      details,
      level: auditLevelFromType(type),
      message,
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      type
    }
  ].slice(-80);
  renderAuditLog();
}

function renderAuditLog(serverEvents = null) {
  if (!els.tradeAuditLog) return;
  const remoteEvents = Array.isArray(serverEvents)
    ? serverEvents.map((event) => ({
        details: event.detail || "",
        level: event.level || "info",
        message: event.message,
        time: String(event.timestamp || "").slice(11, 19) || "server",
        type: "server"
      }))
    : [];
  const events = [...remoteEvents, ...localAuditEvents].slice(-28).reverse();
  els.auditCount.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
  els.tradeAuditLog.innerHTML = events.length
    ? events
        .map(
          (event) => `<article class="${event.level}">
            <span>${event.time}</span>
            <strong>${event.message}</strong>
            <em>${event.details || event.type}</em>
          </article>`
        )
        .join("")
    : '<article><span>Standby</span><strong>No signal events yet</strong><em>Generate, review, then save.</em></article>';
}

function signalJournalKey() {
  return "monatiseSignalJournal:v1";
}

function loadSignalJournal() {
  try {
    const parsed = JSON.parse(localStorage.getItem(signalJournalKey()) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveSignalJournal(entries) {
  localStorage.setItem(signalJournalKey(), JSON.stringify(entries.slice(-80)));
}

function terminalSignalStatus(status) {
  return ["WIN", "LOSS", "EXPIRED", "INVALID", "WATCH"].includes(String(status || "").toUpperCase());
}

function outcomeClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (["win", "triggered"].includes(normalized)) return "pass";
  if (["loss", "invalid"].includes(normalized)) return "error";
  if (["expired", "watch"].includes(normalized)) return "warn";
  return "pending";
}

function candleTime(candle) {
  const time = new Date(candle?.timestamp || 0).getTime();
  return Number.isFinite(time) ? time : 0;
}

function candleTouchesLevel(candle, level) {
  const high = Number(candle?.high);
  const low = Number(candle?.low);
  const price = Number(level);
  return Number.isFinite(high) && Number.isFinite(low) && Number.isFinite(price) && low <= price && high >= price;
}

function journalTimeLabel(value) {
  const time = new Date(value || 0).getTime();
  return Number.isFinite(time) && time > 0 ? new Date(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

function journalElapsedLabel(start, end) {
  const startTime = new Date(start || 0).getTime();
  const endTime = new Date(end || 0).getTime();
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime <= startTime) return "";
  const minutes = Math.round((endTime - startTime) / 60000);
  if (minutes < 90) return `${minutes}m`;
  const hours = minutes / 60;
  return hours < 36 ? `${hours.toFixed(hours < 10 ? 1 : 0)}h` : `${Math.round(hours / 24)}d`;
}

function journalLifecycle(entry = {}) {
  const events = [{ label: "Issued", state: "done", value: journalTimeLabel(entry.createdAt) }];
  if (entry.triggeredAt) {
    events.push({ label: "Entry", state: "done", value: journalTimeLabel(entry.triggeredAt) });
  } else if (entry.status === "INVALID") {
    events.push({ label: "Entry", state: "missed", value: "not filled" });
  } else {
    events.push({ label: "Entry", state: "pending", value: money(entry.entry) });
  }

  if (entry.targetOneHitAt) {
    events.push({ label: "TP1", state: "done", value: journalTimeLabel(entry.targetOneHitAt) });
  } else if (entry.stoppedAt) {
    events.push({ label: "TP1", state: "missed", value: money(entry.targetOne) });
  } else {
    events.push({ label: "TP1", state: "pending", value: money(entry.targetOne) });
  }

  if (entry.stoppedAt) {
    events.push({ label: entry.triggeredAt ? "Stop" : "Invalid", state: "missed", value: journalTimeLabel(entry.stoppedAt) });
  } else if (entry.status === "INVALID") {
    events.push({ label: "Invalid", state: "missed", value: journalTimeLabel(entry.invalidatedAt || entry.resolvedAt) });
  } else {
    events.push({ label: "Stop", state: "pending", value: money(entry.stop) });
  }
  return events;
}

function journalSetupScore(entry = {}) {
  const confidence = Number(entry.confidence || 0);
  const grid = entry.trendGrid || {};
  const longScore = Number(grid.longScore);
  const shortScore = Number(grid.shortScore);
  const directionalScore =
    entry.direction === "LONG" && Number.isFinite(longScore)
      ? longScore
      : entry.direction === "SHORT" && Number.isFinite(shortScore)
        ? shortScore
        : null;
  if (confidence >= 75 && Number(directionalScore) >= 4) return "A";
  if (confidence >= 62 || Number(directionalScore) >= 3) return "B";
  if (confidence >= 50 || Number(directionalScore) >= 2) return "C";
  return "Watch";
}

function gradeSignalEntry(entry, candles = state?.candles || []) {
  if (terminalSignalStatus(entry.status)) return entry;
  if (!["LONG", "SHORT"].includes(entry.direction)) {
    return { ...entry, status: entry.direction === "WATCH" ? "WATCH" : "INVALID", outcomeDetail: "No executable direction was issued." };
  }
  const createdAt = new Date(entry.createdAt).getTime();
  const expiresAt = entry.expiresAt ? new Date(entry.expiresAt).getTime() : Number.POSITIVE_INFINITY;
  const laterCandles = candles
    .filter((candle) => {
      const time = candleTime(candle);
      return time && time > createdAt && time <= expiresAt;
    })
    .sort((left, right) => candleTime(left) - candleTime(right));
  let triggeredAt = entry.triggeredAt || "";
  for (const candle of laterCandles) {
    const time = candle.timestamp;
    const entryTouched = candleTouchesLevel(candle, entry.entry);
    const stopTouched = candleTouchesLevel(candle, entry.stop);
    const targetTouched = candleTouchesLevel(candle, entry.targetOne);
    if (!triggeredAt) {
      if (stopTouched && !entryTouched) {
        return {
          ...entry,
          invalidatedAt: time,
          resolvedAt: time,
          status: "INVALID",
          outcomeDetail: `Invalidation touched ${money(entry.stop)} before the planned entry filled.`
        };
      }
      if (stopTouched && entryTouched) {
        return {
          ...entry,
          invalidatedAt: time,
          resolvedAt: time,
          status: "INVALID",
          outcomeDetail: "Entry and invalidation were inside the same candle before a confirmed fill; marked invalid."
        };
      }
      if (entryTouched) triggeredAt = time;
    }
    if (!triggeredAt) continue;
    if (entry.direction === "LONG") {
      const stopHit = stopTouched;
      const targetHit = targetTouched;
      if (stopHit && targetHit) {
        return { ...entry, triggeredAt, stoppedAt: time, resolvedAt: time, status: "LOSS", outcomeDetail: `Stop and Target 1 were both inside the same candle; marked loss because exact intrabar order is unknown.` };
      }
      if (stopHit) {
        return { ...entry, triggeredAt, stoppedAt: time, resolvedAt: time, status: "LOSS", outcomeDetail: `Stop hit at ${money(entry.stop)} before target.` };
      }
      if (targetHit) {
        return { ...entry, triggeredAt, targetOneHitAt: time, resolvedAt: time, status: "WIN", outcomeDetail: `Target 1 hit at ${money(entry.targetOne)}.` };
      }
    } else {
      const stopHit = stopTouched;
      const targetHit = targetTouched;
      if (stopHit && targetHit) {
        return { ...entry, triggeredAt, stoppedAt: time, resolvedAt: time, status: "LOSS", outcomeDetail: `Stop and Target 1 were both inside the same candle; marked loss because exact intrabar order is unknown.` };
      }
      if (stopHit) {
        return { ...entry, triggeredAt, stoppedAt: time, resolvedAt: time, status: "LOSS", outcomeDetail: `Stop hit at ${money(entry.stop)} before target.` };
      }
      if (targetHit) {
        return { ...entry, triggeredAt, targetOneHitAt: time, resolvedAt: time, status: "WIN", outcomeDetail: `Target 1 hit at ${money(entry.targetOne)}.` };
      }
    }
  }
  if (expiresAt !== Number.POSITIVE_INFINITY && Date.now() > expiresAt) {
    return {
      ...entry,
      triggeredAt,
      resolvedAt: entry.expiresAt,
      status: "EXPIRED",
      outcomeDetail: triggeredAt ? "Signal triggered but did not reach target or stop before expiry." : "Signal expired before trigger."
    };
  }
  return {
    ...entry,
    triggeredAt,
    status: triggeredAt ? "TRIGGERED" : "PENDING",
    outcomeDetail: triggeredAt ? "Triggered; waiting for target, stop, or expiry." : "Waiting for trigger or expiry."
  };
}

function refreshSignalJournal() {
  const entries = loadSignalJournal().map((entry) => gradeSignalEntry(entry));
  saveSignalJournal(entries);
  renderSignalJournal(entries);
  return entries;
}

function renderSignalJournal(entries = loadSignalJournal()) {
  if (!els.signalJournal) return;
  const graded = entries.map((entry) => gradeSignalEntry(entry));
  const tracked = graded.length;
  const wins = graded.filter((entry) => entry.status === "WIN").length;
  const losses = graded.filter((entry) => entry.status === "LOSS").length;
  const pending = graded.filter((entry) => ["PENDING", "TRIGGERED"].includes(entry.status)).length;
  if (els.journalStats) {
    els.journalStats.textContent = `${tracked} tracked · ${wins}W/${losses}L · ${pending} open`;
  }
  els.signalJournal.innerHTML = graded.length
    ? graded
        .slice(-12)
        .reverse()
        .map(
          (entry) => {
            const lifecycle = journalLifecycle(entry)
              .map((event) => `<span class="${event.state}">${event.label}<strong>${event.value || "--"}</strong></span>`)
              .join("");
            const elapsed = journalElapsedLabel(entry.triggeredAt || entry.createdAt, entry.resolvedAt || entry.targetOneHitAt || entry.stoppedAt);
            return `<article class="${outcomeClass(entry.status)}">
            <span>${new Date(entry.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${entry.symbol} · ${entry.interval}</span>
            <strong>${entry.direction} · ${entry.status} · Grade ${entry.setupGrade || journalSetupScore(entry)}</strong>
            <em>Entry ${money(entry.entry)} · Target ${money(entry.targetOne)} · Stop ${money(entry.stop)}</em>
            <div class="journal-path">${lifecycle}</div>
            ${
              Number(entry.suggestedLot) > 0
                ? `<em>Lot ${formatLotSize(entry.suggestedLot)} · Stop risk ${money(entry.stopLossAmount)} · T1 ${money(entry.targetOneProfit)}</em>`
                : ""
            }
            <small>${entry.outcomeDetail || "Waiting for later candles."}${elapsed ? ` · ${elapsed}` : ""}</small>
          </article>`;
          }
        )
        .join("")
    : '<article class="pending"><span>No saved signals</span><strong>Review a signal to start tracking</strong><em>Outcomes update from later candles.</em></article>';
}

function saveReviewedSignal() {
  if (!lastSignalCandidate || !["LONG", "SHORT", "WATCH"].includes(lastSignalCandidate.direction)) return null;
  const entry = gradeSignalEntry({
    ...lastSignalCandidate,
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    setupGrade: journalSetupScore(lastSignalCandidate),
    status: lastSignalCandidate.direction === "WATCH" ? "WATCH" : "PENDING",
    outcomeDetail: lastSignalCandidate.direction === "WATCH" ? "Watchlist idea saved; no executable trigger." : "Waiting for later candles."
  });
  const entries = [...loadSignalJournal(), entry].slice(-80);
  saveSignalJournal(entries);
  renderSignalJournal(entries);
  return entry;
}

function localReadinessItems(snapshot = null) {
  const loggedIn = Boolean(currentUser.authenticated);
  const hasCredentials = Boolean(currentUser.credentialsConfigured);
  const mode = snapshot?.mode || "paper";
  const network = snapshot?.network || "local";
  const sessionGuard = (snapshot?.sessionGuard?.active ? snapshot.sessionGuard : activeSessionGuard(selectedAsset)) || {};
  const requires = Array.isArray(snapshot?.requires) ? snapshot.requires : [];
  const account = snapshot?.account || {};
  const mark = Number(snapshot?.markPrice ?? currentMarketPrice());
  const risk = snapshot?.risk || {};
  const riskStatus = String(snapshot?.riskStatus || "");
  const isLiveMainnet = mode === "live" && network === "mainnet";
  const accountValue = Number(account.displayValue ?? account.accountValue);
  const openNotional = Number(risk.open_order_notional || 0);
  const maxDailyLoss = Number(risk.max_daily_loss || 0);
  const maxDailyLossPct = Number(risk.max_daily_loss_pct || 0);
  return [
    {
      detail: loggedIn ? currentUser.username || "profile active" : "request access or log in to save signal preferences",
      label: "User session",
      ok: loggedIn,
      severity: "block"
    },
    {
      detail: hasCredentials ? "private sync saved" : "optional private sync is not required for signals",
      label: "Private sync",
      ok: true,
      severity: "warn"
    },
    {
      detail: mode === "live" ? "private access; signal gates still apply" : "private access",
      label: "Signal access",
      ok: true,
      severity: isLiveMainnet ? "block" : "warn"
    },
    {
      detail: requires.length ? requires.join(", ") : "server signal gates satisfied",
      label: "Server signal gates",
      ok: mode !== "live" || requires.length === 0,
      severity: "block"
    },
    {
      detail: Number.isFinite(mark) ? `${assetLabel(selectedAsset)} mark ${money(mark)}` : "waiting for live market mark",
      label: "Market feed",
      ok: Number.isFinite(mark) && mark > 0,
      severity: "block"
    },
    {
      detail: sessionGuard.active ? sessionGuard.message : "no active session break block",
      label: "Session guard",
      ok: !sessionGuard.active,
      severity: "block"
    },
    {
      detail: maxDailyLoss
        ? `${money(openNotional)} open vs ${money(maxDailyLoss)} (${(maxDailyLossPct * 100).toFixed(2)}%) hard stop`
        : riskStatus || "risk engine waiting",
      label: "Risk budget",
      ok: !/max daily loss|exceeds|below minimum|shock|guard/i.test(riskStatus),
      severity: "block"
    },
    {
      detail: "faith is not a signal; invalidate the thesis when price proves it wrong",
      label: "Doctrine alignment",
      ok: true,
      severity: "warn"
    }
  ];
}

function renderReadinessChecklist(snapshot = null) {
  if (!els.readinessChecklist) return;
  const items = readinessItems(snapshot);
  const blocked = items.filter((item) => !item.ok && item.severity === "block").length;
  els.readinessChecklist.innerHTML = `
    <div class="checklist-head">
      <strong>${blocked ? `${blocked} signal block${blocked === 1 ? "" : "s"}` : "Signal checklist clear"}</strong>
      <span>${blocked ? "draft only until resolved" : "ready for signal review"}</span>
    </div>
    ${items
      .map(
        (item) => `<article class="${readinessClass(item)}">
          <span>${item.label}</span>
          <strong>${item.ok ? "OK" : item.severity === "block" ? "BLOCK" : "WATCH"}</strong>
          <em>${item.detail || ""}</em>
        </article>`
      )
      .join("")}
  `;
}

function strategyHealth(mark, orders, snapshot = null) {
  const orderList = Array.isArray(orders) ? orders : [];
  const buyOrders = orderList.filter((order) => String(order.side || "").toLowerCase().startsWith("b"));
  const sellOrders = orderList.filter((order) => String(order.side || "").toLowerCase().startsWith("s"));
  const prices = orderList.map((order) => Number(order.price)).filter((price) => Number.isFinite(price));
  const notionals = orderList
    .map((order) => Number(order.price) * Number(order.quantity || 0))
    .filter((notional) => Number.isFinite(notional));
  const gridFloor = prices.length ? Math.min(...prices) : Number.NaN;
  const gridCeiling = prices.length ? Math.max(...prices) : Number.NaN;
  const invalidation = Number(fibAnalysis?.invalidation);
  const missingInvalidationLevels = orderList.filter(
    (order) => !isValidInvalidation(String(order.side || "").toLowerCase().startsWith("s") ? "sell" : "buy", Number(order.price), Number(order.invalidation))
  );
  const sessionGuard = (snapshot?.sessionGuard?.active ? snapshot.sessionGuard : activeSessionGuard(selectedAsset)) || {};
  const indicatorAction = String(contextRadar?.instruction?.action || "normal");
  const fibOk = Boolean(fibAnalysis && !fibAnalysis.error && fibAnalysis.symbol === selectedAsset);
  const fvgOk = Boolean(fvgAnalysis && !fvgAnalysis.error && fvgAnalysis.symbol === selectedAsset);
  const markOk = Number.isFinite(mark) && mark > 0;
  const orderOk = orderList.length > 0;
  const balancedLevels = buyOrders.length > 0 && sellOrders.length > 0;
  const riskStatus = String(snapshot?.riskStatus || els.riskStatus?.textContent || "");
  const structureBreak = markOk && Number.isFinite(invalidation) && mark < invalidation;
  const outsideGrid = markOk && Number.isFinite(gridFloor) && Number.isFinite(gridCeiling) && (mark < gridFloor || mark > gridCeiling);
  const blockReasons = [];
  if (!markOk) blockReasons.push("waiting for live market mark");
  if (!orderOk) blockReasons.push("no signal levels are available yet");
  if (missingInvalidationLevels.length) blockReasons.push("grid levels need valid side-aware invalidation");
  if (structureBreak) blockReasons.push("price broke structure; stop fresh signals");
  if (sessionGuard.active) blockReasons.push(sessionGuard.message || "session guard is active");
  if (/max daily loss|exceeds|below minimum|shock|guard/i.test(riskStatus)) blockReasons.push(riskStatus);
  if (indicatorAction === "halt") blockReasons.push("context radar says halt");
  const blocked = blockReasons.length > 0;
  const warnings = [];
  if (outsideGrid) warnings.push("mark is outside the planned signal range");
  if (!fibOk) warnings.push("live Fibonacci candles pending");
  if (!fvgOk) warnings.push("live FVG candles pending");
  if (indicatorAction === "reduce") warnings.push("context radar says reduce size");
  if (indicatorAction === "widen") warnings.push("context radar says widen buffer");
  else if (!balancedLevels) warnings.push("one-sided setup; use target and stop discipline");
  return {
    balancedLevels,
    blockReasons,
    blocked,
    buyCount: buyOrders.length,
    gridCeiling,
    gridFloor,
    invalidation: Number.isFinite(invalidation) ? invalidation : gridFloor,
    largestNotional: notionals.length ? Math.max(...notionals) : 0,
    markOk,
    missingInvalidationCount: missingInvalidationLevels.length,
    orderCount: orderList.length,
    sellCount: sellOrders.length,
    status: blocked ? "WAIT" : warnings.length ? "REVIEW" : "ALIGNED",
    structureBreak,
    warnings
  };
}

function setupGridOrders(mark, snapshot = null) {
  const tradingViewOrders = tradingViewGridOrders(mark, snapshot);
  if (tradingViewOrders.length) return tradingViewOrders;
  if (!fibAnalysis || fibAnalysis.error || fibAnalysis.symbol !== selectedAsset || !Number.isFinite(Number(mark))) {
    return [];
  }
  const quoteSize = Number(snapshot?.tradingRules?.orderQuoteSize ?? tradingRules.orderQuoteSize ?? els.quoteInput?.value ?? 0);
  const notional = Number.isFinite(quoteSize) && quoteSize > 0 ? quoteSize : 100;
  const candidates = [];
  const addLevel = (side, price, levelId, options = {}) => {
    const numericPrice = Number(price);
    if (!Number.isFinite(numericPrice) || numericPrice <= 0) return;
    const duplicate = candidates.some((level) => Math.abs(level.price - numericPrice) / numericPrice < 0.0006);
    if (duplicate) return;
    const invalidation = setupLevelInvalidation(side, numericPrice, options);
    candidates.push({
      level_id: levelId,
      invalidation,
      metadata: { source: "live-analysis", invalidationSource: options.invalidationSource || setupInvalidationSource(side, numericPrice, invalidation) },
      order_id: `setup-${selectedAsset}-${side}-${candidates.length + 1}`,
      price: numericPrice,
      quantity: notional / numericPrice,
      side,
      status: "draft",
      symbol: selectedAsset
    });
  };
  const fibLevels = Array.isArray(fibAnalysis.levels) ? fibAnalysis.levels : [];
  fibLevels.forEach((level) => {
    const price = Number(level.price);
    if (!Number.isFinite(price)) return;
    addLevel(price <= mark ? "buy" : "sell", price, String(level.label || "fib").toLowerCase().replace(/\s+/g, "-"));
  });
  const nearestGap = fvgAnalysis?.nearest_gap;
  if (nearestGap) {
    const gapSide = String(nearestGap.direction || "").toLowerCase() === "bearish" ? "sell" : "buy";
    addLevel(gapSide, nearestGap.midpoint, "fvg-mid", {
      invalidation: gapSide === "sell" ? nearestGap.high : nearestGap.low,
      invalidationSource: "fvg"
    });
  }
  addLevel("buy", fibAnalysis.grid_floor, "grid-floor");
  addLevel("sell", fibAnalysis.grid_ceiling, "grid-ceiling");
  return candidates
    .sort((a, b) => Math.abs(a.price - mark) - Math.abs(b.price - mark))
    .slice(0, 8);
}

function setupLevelInvalidation(side, price, options = {}) {
  const explicit = Number(options.invalidation);
  if (isValidInvalidation(side, price, explicit)) return explicit;

  const fibInvalidation = Number(fibAnalysis?.invalidation);
  if (isValidInvalidation(side, price, fibInvalidation)) return fibInvalidation;

  const fallback = side === "sell" ? Number(fibAnalysis?.grid_ceiling) : Number(fibAnalysis?.grid_floor);
  if (isValidInvalidation(side, price, fallback)) return fallback;

  return null;
}

function setupInvalidationSource(side, price, invalidation) {
  if (!Number.isFinite(Number(invalidation))) return "missing";
  if (Math.abs(Number(invalidation) - Number(fibAnalysis?.invalidation)) / Number(price) < 0.0006) return "fib";
  return side === "sell" ? "grid-ceiling" : "grid-floor";
}

function isValidInvalidation(side, price, invalidation) {
  const numericPrice = Number(price);
  const numericInvalidation = Number(invalidation);
  if (!Number.isFinite(numericPrice) || numericPrice <= 0 || !Number.isFinite(numericInvalidation) || numericInvalidation <= 0) return false;
  if (side === "sell") return numericInvalidation > numericPrice;
  return numericInvalidation < numericPrice;
}

function setupWaitDetail(health, signal, timing) {
  if (signal.direction !== "WAIT") {
    return signal.thesis;
  }
  if (!health.markOk) return "Waiting for a live Hyperliquid mark before forming entries.";
  if (!health.orderCount) return "Waiting for live setup-grid levels from Fibonacci/FVG analysis.";
  if (health.structureBreak) return "Price broke invalidation; wait for a fresh structure reset.";
  if (timing.blocked) return `${timing.detail} The grid remains visible for planning.`;
  if (health.blockReasons?.length) return `Waiting for hard block to clear: ${health.blockReasons[0]}.`;
  if (health.warnings.length) return `Waiting for confirmation: ${health.warnings[0]}.`;
  return "Waiting for a clean trigger close before turning the setup into an entry.";
}

function assetSignalProfile(symbol = selectedAsset) {
  return {
    className: "crypto",
    lens: "Hyperliquid mark, FVG/Fibonacci structure, funding, OI, and liquidation context",
    primaryFeed: "Hyperliquid/CoinGlass crypto read"
  };
}

function compactList(items = [], fallback = "No confirmed drivers yet.") {
  const clean = items.map((item) => String(item || "").trim()).filter(Boolean);
  return clean.length ? clean.join(" · ") : fallback;
}

function signalTrustSummary(signal = {}, health = {}, timing = signalTiming(selectedAsset)) {
  const drivers = compactList(signal.reasons || []);
  const cautions = compactList([...(signal.cautions || []), ...(health.warnings || [])], "No active cautions.");
  const blocks = compactList([...(health.blockReasons || [])], "No hard blocks.");
  const timingText = timing?.detail ? `${timing.status}: ${timing.detail}` : timing?.status || "timing pending";
  const quiverText = quiverTrustText(signal.quiverContext);
  return `Drivers: ${drivers}. ${stopLossSummary(signal)} ${trendGridSummary(signal, health)} ${quiverText} Cautions: ${cautions}. Hard blocks: ${blocks}. Timing: ${timingText}.`;
}

function quiverSignalContext(direction = "WAIT", context = quiverContext, symbol = selectedAsset) {
  if (!isQuiverAsset(symbol)) return { boost: 0, cautions: [], reasons: [], status: "not-applicable" };
  if (!context || context.error || context.reason) {
    return {
      boost: 0,
      cautions: ["Quiver context unavailable for stock/ETF analysis"],
      reasons: [],
      status: "missing"
    };
  }
  const summary = context.summary || {};
  const bias = String(summary.bias || "neutral").toLowerCase();
  const score = Math.max(0, Math.min(10, Number(summary.score || 0)));
  const drivers = Array.isArray(summary.drivers) ? summary.drivers.filter(Boolean) : [];
  const driverText = compactList(drivers.slice(0, 2), summary.detail || "Quiver alternative data checked");
  if (bias === "supportive" && direction === "LONG") {
    return {
      boost: Math.min(6, 2 + Math.round(score / 2)),
      cautions: [],
      reasons: [`Quiver supportive context: ${driverText}`],
      score,
      status: "supportive"
    };
  }
  if (bias === "supportive" && direction === "SHORT") {
    return {
      boost: -Math.min(8, 3 + Math.round(score / 2)),
      cautions: [`Quiver supportive context conflicts with short setup: ${driverText}`],
      reasons: [],
      score,
      status: "conflict"
    };
  }
  if (bias === "watch" && ["LONG", "SHORT"].includes(direction)) {
    return {
      boost: 1,
      cautions: [],
      reasons: [`Quiver watch context: ${driverText}`],
      score,
      status: "watch"
    };
  }
  return {
    boost: 0,
    cautions: ["Quiver context is neutral or has no fresh rows"],
    reasons: [],
    score,
    status: "neutral"
  };
}

function quiverTrustText(context = null) {
  if (!context || context.status === "not-applicable") return "";
  if (context.status === "missing") return "Quiver: unavailable for this stock/ETF signal.";
  const score = Number.isFinite(Number(context.score)) ? ` score ${Number(context.score).toFixed(0)}/10` : "";
  return `Quiver: ${context.status || "checked"}${score}.`;
}

function setupRiskPct(symbol = selectedAsset) {
  if (["SPX", "NDX", "NASDAQ", "AAPL", "TSLA", "NVDA"].includes(symbol)) return 0.0035;
  return 0.0035;
}

function setupMinRiskPct(symbol = selectedAsset) {
  if (["SPX", "NDX", "NASDAQ", "AAPL", "TSLA", "NVDA"].includes(symbol)) return 0.0008;
  return 0.0008;
}

function boundedRiskDistance(entry, baseStop, atr, symbol = selectedAsset) {
  const numericEntry = Number(entry);
  if (!Number.isFinite(numericEntry) || numericEntry <= 0) return 0;
  const maxRisk = numericEntry * setupRiskPct(symbol);
  const minRisk = numericEntry * setupMinRiskPct(symbol);
  const atrRisk = Number.isFinite(Number(atr)) && Number(atr) > 0 ? Number(atr) * 0.65 : maxRisk;
  const structureRisk = Math.abs(numericEntry - Number(baseStop));
  const rawRisk = Number.isFinite(structureRisk) && structureRisk > 0 ? structureRisk : atrRisk;
  return Math.max(minRisk, Math.min(maxRisk, rawRisk, Math.max(minRisk, atrRisk)));
}

function stopLossModel(direction, entry, baseStop, atr, riskDistance, symbol = selectedAsset, source = "") {
  const numericEntry = Number(entry);
  const numericRisk = Number(riskDistance);
  if (!["LONG", "SHORT"].includes(direction) || !Number.isFinite(numericEntry) || numericEntry <= 0 || !Number.isFinite(numericRisk) || numericRisk <= 0) {
    return null;
  }
  const minRisk = numericEntry * setupMinRiskPct(symbol);
  const maxRisk = numericEntry * setupRiskPct(symbol);
  const structureRisk = Math.abs(numericEntry - Number(baseStop));
  const atrRisk = Number.isFinite(Number(atr)) && Number(atr) > 0 ? Number(atr) * 0.65 : Number.NaN;
  const stop = direction === "SHORT" ? numericEntry + numericRisk : numericEntry - numericRisk;
  let resolvedSource = source;
  if (!resolvedSource) {
    resolvedSource =
      Number.isFinite(structureRisk) && structureRisk > 0
        ? "structure invalidation"
        : Number.isFinite(atrRisk)
          ? "ATR fallback"
          : "asset risk band";
  }
  return {
    atrRisk,
    baseStop: Number.isFinite(Number(baseStop)) ? Number(baseStop) : null,
    maxRisk,
    minRisk,
    riskDistance: numericRisk,
    riskPct: numericRisk / numericEntry,
    source: resolvedSource,
    stop,
    structureRisk: Number.isFinite(structureRisk) ? structureRisk : null,
    symbol
  };
}

function stopLossSummary(signal = {}) {
  const model = signal.stopModel || null;
  const entry = Number(signal.entry);
  const stop = Number(signal.stop);
  if (!model && (!Number.isFinite(entry) || !Number.isFinite(stop) || entry <= 0 || stop <= 0)) {
    return "Stop model: pending until entry and invalidation are defined.";
  }
  const riskDistance = model ? Number(model.riskDistance) : Math.abs(entry - stop);
  const riskPct = model ? Number(model.riskPct) : riskDistance / entry;
  const band =
    model && Number.isFinite(model.minRisk) && Number.isFinite(model.maxRisk)
      ? ` band ${money(model.minRisk)}-${money(model.maxRisk)}`
      : "";
  const source = model?.source || "entry-to-stop distance";
  return `Stop model: ${source}; stop ${money(model?.stop ?? stop)}, distance ${money(riskDistance)} (${(riskPct * 100).toFixed(2)}%)${band}.`;
}

function trendGridSummary(signal = {}, health = {}) {
  const direction = signal.direction;
  const levelCount = Array.isArray(signal.entryLevels) ? signal.entryLevels.length : 0;
  const score =
    signal.trendGrid && Number.isFinite(Number(signal.trendGrid.longScore)) && Number.isFinite(Number(signal.trendGrid.shortScore))
      ? ` Score LONG ${signal.trendGrid.longScore} / SHORT ${signal.trendGrid.shortScore}.`
      : "";
  if (direction === "LONG") {
    return `Trend grid: LONG pullback grid with entries below/near mark, stop below entry, and targets above entry (${levelCount} entry lanes).${score}`;
  }
  if (direction === "SHORT") {
    return `Trend grid: SHORT rejection grid with entries above/near mark, stop above entry, and targets below entry (${levelCount} entry lanes).${score}`;
  }
  if (health?.blocked) return "Trend grid: paused because hard blocks are active.";
  return `Trend grid: waiting for directional agreement before arranging entries, stop, and targets.${score}`;
}

function isPullbackEntry(direction, entry, mark) {
  const numericMark = Number(mark);
  const numericEntry = Number(entry);
  if (!Number.isFinite(numericMark) || numericMark <= 0 || !Number.isFinite(numericEntry) || numericEntry <= 0) return false;
  if (direction === "LONG") return numericEntry < numericMark;
  if (direction === "SHORT") return numericEntry > numericMark;
  return false;
}

function plannedEntry(direction, mark, nearest, gapMidpoint) {
  const stableGap = Number.isFinite(gapMidpoint) && gapMidpoint > 0 ? gapMidpoint : Number.NaN;
  const stableNearest = Number.isFinite(nearest) && nearest > 0 ? nearest : Number.NaN;
  if (direction === "LONG" || direction === "SHORT") {
    if (isPullbackEntry(direction, stableGap, mark)) return stableGap;
    if (isPullbackEntry(direction, stableNearest, mark)) return stableNearest;
  }
  return Number.NaN;
}

function trendGridPlan({
  action = "normal",
  gapDirection = "",
  gapMidpoint = Number.NaN,
  health = {},
  invalidation = Number.NaN,
  mark = Number.NaN,
  nearest = Number.NaN,
  resistanceOnly = false,
  rsi = 50,
  supportOnly = false,
  takeProfit = Number.NaN,
  trend = "flat"
} = {}) {
  const lowerTrend = String(trend || "flat").toLowerCase();
  const lowerAction = String(action || "normal").toLowerCase();
  const lowerGap = String(gapDirection || "").toLowerCase();
  const drivers = [];
  let longScore = 0;
  let shortScore = 0;

  const add = (side, score, reason) => {
    if (side === "LONG") longScore += score;
    if (side === "SHORT") shortScore += score;
    if (reason) drivers.push(reason);
  };

  if (supportOnly) add("LONG", 4, "support-only grid gives long priority");
  if (resistanceOnly) add("SHORT", 4, "resistance-only grid gives short priority");
  if (lowerTrend.includes("up")) add("LONG", 2, "uptrend favors pullback bids");
  if (lowerTrend.includes("down")) add("SHORT", 2, "downtrend favors rejection offers");
  if (Number.isFinite(rsi) && rsi >= 55) add("LONG", 1, `RSI ${rsi.toFixed(1)} supports upside momentum`);
  if (Number.isFinite(rsi) && rsi <= 45) add("SHORT", 1, `RSI ${rsi.toFixed(1)} supports downside momentum`);
  if (lowerGap === "bullish") add("LONG", 2, "bullish FVG creates a long pullback lane");
  if (lowerGap === "bearish") add("SHORT", 2, "bearish FVG creates a short rejection lane");
  if (Number.isFinite(takeProfit) && Number.isFinite(mark) && takeProfit > mark) add("LONG", 1, "target reference sits above mark");
  if (Number.isFinite(takeProfit) && Number.isFinite(mark) && takeProfit < mark) add("SHORT", 1, "target reference sits below mark");

  const forcedDirection = supportOnly ? "LONG" : resistanceOnly ? "SHORT" : "";
  const hardBlocked = (health.blocked || lowerAction === "halt" || lowerAction === "pause") && !forcedDirection;
  const scoreEdge = longScore - shortScore;
  const candidateDirection = hardBlocked
    ? "WAIT"
    : forcedDirection || (scoreEdge >= 2 ? "LONG" : scoreEdge <= -2 ? "SHORT" : "WATCH");
  const candidateExecutable = ["LONG", "SHORT"].includes(candidateDirection);
  const entry = candidateExecutable ? plannedEntry(candidateDirection, mark, nearest, gapMidpoint) : Number.NaN;
  const pullbackBlocked = candidateExecutable && !Number.isFinite(entry);
  const direction = pullbackBlocked ? "WAIT" : candidateDirection;
  const targetReference =
    Number.isFinite(takeProfit) && takeProfit > 0
      ? takeProfit
      : direction === "SHORT"
        ? health.gridFloor
        : health.gridCeiling;
  const baseStop =
    Number.isFinite(invalidation) && invalidation > 0
      ? invalidation
      : direction === "SHORT"
        ? health.gridCeiling
        : health.gridFloor;

  return {
    baseStop,
    direction,
    drivers,
    edge: scoreEdge,
    entry,
    executable: candidateExecutable && !pullbackBlocked,
    longScore,
    pullbackBlocked,
    shortScore,
    targetReference
  };
}

function targetWithMinimumReward(direction, entry, rawTarget, riskDistance, rewardMultiple = 1.35) {
  const numericEntry = Number(entry);
  const numericRisk = Number(riskDistance);
  const fallback =
    direction === "SHORT" ? numericEntry - numericRisk * rewardMultiple : numericEntry + numericRisk * rewardMultiple;
  if (!Number.isFinite(Number(rawTarget)) || Number(rawTarget) <= 0) return fallback;
  if (direction === "SHORT") return Math.min(Number(rawTarget), fallback);
  if (direction === "LONG") return Math.max(Number(rawTarget), fallback);
  return Number(rawTarget);
}

function buildEntryLadder(direction, mark, planned, riskDistance, targetOne, symbol = selectedAsset) {
  if (!["LONG", "SHORT"].includes(direction) || !Number.isFinite(Number(mark)) || !Number.isFinite(Number(planned))) {
    return [];
  }
  const numericMark = Number(mark);
  const numericPlanned = Number(planned);
  const directionSign = direction === "SHORT" ? -1 : 1;
  const maxFallbackRisk = numericPlanned * setupRiskPct(symbol);
  const minFallbackRisk = numericPlanned * setupMinRiskPct(symbol);
  const entryGapRisk = Math.abs(numericMark - numericPlanned);
  const fallbackRisk = Math.max(
    minFallbackRisk,
    Math.min(maxFallbackRisk, entryGapRisk > 0 ? entryGapRisk : maxFallbackRisk * 0.65)
  );
  const risk = Number.isFinite(Number(riskDistance)) && Number(riskDistance) > 0 ? Number(riskDistance) : fallbackRisk;
  const entries = [
    {
      key: "planned",
      label: "Planned Entry",
      note: "pullback zone",
      price: numericPlanned,
      reward: 1.35,
      stopRisk: 0.75
    },
    {
      key: "confirm",
      label: "Confirm Entry",
      note: direction === "SHORT" ? "after reject" : "after break",
      price: numericPlanned + directionSign * risk * 0.35,
      reward: 1.05,
      stopRisk: 0.65
    },
    {
      key: "deep",
      label: "Deep Pullback",
      note: "smaller size",
      price: numericPlanned - directionSign * risk * 0.35,
      reward: 1.65,
      stopRisk: 0.85
    }
  ];
  return entries.map((entry) => {
    const stop = entry.price - directionSign * risk * entry.stopRisk;
    const rawEarlyTarget = entry.price + directionSign * risk * entry.reward;
    const numericTargetOne = Number(targetOne);
    const earlyTarget =
      direction === "SHORT"
        ? numericTargetOne < entry.price
          ? Math.max(rawEarlyTarget, numericTargetOne)
          : rawEarlyTarget
        : numericTargetOne > entry.price
          ? Math.min(rawEarlyTarget, numericTargetOne)
          : rawEarlyTarget;
    return {
      ...entry,
      earlyTarget,
      stop,
      riskDistance: Math.abs(entry.price - stop)
    };
  });
}

function renderEntryLadder(levels = []) {
  if (!levels.length) return "";
  return `
    <div class="entry-ladder">
      ${levels
        .map(
          (level) => `<article class="${level.key}">
            <span>${level.label}</span>
            <strong>${money(level.price)}</strong>
            <em>TP ${money(level.earlyTarget)} · SL ${money(level.stop)} · ${level.note}</em>
          </article>`
        )
        .join("")}
    </div>
  `;
}

function tradingViewAlertSignature(signal = latestTradingViewSignal) {
  if (!signal) return "";
  return [
    signal.symbol || "",
    signal.action || "",
    signal.confidence || "",
    signal.receivedAt || "",
    signal.price || "",
    JSON.stringify(signal.indicators || {})
  ].join(":");
}

function activeTradingViewSignal(maxAgeMs = 15 * 60 * 1000) {
  const signal = latestTradingViewSignal;
  if (!signal || String(signal.symbol || "").toUpperCase() !== selectedAsset) return null;
  const receivedAt = Number(signal.receivedAt || 0) * 1000;
  if (!receivedAt || Date.now() - receivedAt > maxAgeMs) return null;
  return signal;
}

function tradingViewSignalPrice(signal = activeTradingViewSignal()) {
  const value = Number(signal?.priceValue ?? signal?.price);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function tradingViewSetup(signal = activeTradingViewSignal()) {
  const setup = signal?.setup || {};
  const value = (key) => {
    const numeric = Number(setup[key]);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
  };
  return {
    entry: value("entry"),
    stop: value("stop"),
    targetOne: value("targetOne"),
    targetTwo: value("targetTwo"),
    thesis: String(setup.thesis || signal?.message || "").trim(),
    trigger: String(setup.trigger || "").trim()
  };
}

function tradingViewGridOrders(mark, snapshot = null) {
  const signal = activeTradingViewSignal();
  if (!signal) return [];
  const setup = tradingViewSetup(signal);
  const levels = Array.isArray(signal.grid) ? [...signal.grid] : [];
  if (setup.entry) levels.push({ label: "tv-entry", price: setup.entry, side: signal.action === "SELL" ? "sell" : "buy" });
  if (setup.targetOne) levels.push({ label: "tv-target-1", price: setup.targetOne, side: signal.action === "SELL" ? "buy" : "sell" });
  if (setup.targetTwo) levels.push({ label: "tv-target-2", price: setup.targetTwo, side: signal.action === "SELL" ? "buy" : "sell" });
  if (setup.stop) levels.push({ label: "tv-stop", price: setup.stop, side: signal.action === "SELL" ? "buy" : "sell" });
  const quoteSize = Number(snapshot?.tradingRules?.orderQuoteSize ?? tradingRules.orderQuoteSize ?? els.quoteInput?.value ?? 0);
  const notional = Number.isFinite(quoteSize) && quoteSize > 0 ? quoteSize : 100;
  const seen = new Set();
  return levels
    .map((level, index) => {
      const price = Number(level.price);
      if (!Number.isFinite(price) || price <= 0) return null;
      const rounded = Math.round(price * 100000) / 100000;
      if (seen.has(rounded)) return null;
      seen.add(rounded);
      const side = String(level.side || "").toLowerCase().startsWith("s") ? "sell" : "buy";
      const invalidation = isValidInvalidation(side, price, level.invalidation)
        ? Number(level.invalidation)
        : isValidInvalidation(side, price, setup.stop)
          ? setup.stop
          : null;
      return {
        level_id: String(level.label || `tv-${index + 1}`).toLowerCase().replace(/\s+/g, "-"),
        invalidation,
        metadata: { source: "tradingview", invalidationSource: invalidation ? "tv-stop" : "missing" },
        order_id: `tv-${selectedAsset}-${side}-${index + 1}`,
        price,
        quantity: notional / price,
        side,
        status: "draft",
        symbol: selectedAsset
      };
    })
    .filter(Boolean)
    .sort((a, b) => Math.abs(a.price - Number(mark || a.price)) - Math.abs(b.price - Number(mark || b.price)))
    .slice(0, 12);
}

function indicatorBiasValue(value) {
  const text = String(value || "").toLowerCase();
  if (!text || ["0", "none", "neutral", "wait", "n/a", "na"].includes(text)) return 0;
  if (/(sell|short|bear|bearish|down|below|resistance|reject|lower|cross down|supply)/.test(text)) return -1;
  if (/(buy|long|bull|bullish|up|above|support|reclaim|higher|cross up|demand)/.test(text)) return 1;
  return 0;
}

function tradingViewConfluence(direction) {
  const signal = activeTradingViewSignal(2 * 60 * 60 * 1000);
  if (!signal) return { boost: 0, detail: "", status: "none" };
  const action = String(signal.action || "WAIT").toUpperCase();
  const confidence = Math.max(0, Math.min(100, Number(signal.confidence || 0)));
  const receivedAt = Number(signal.receivedAt || 0) * 1000;
  const fresh = receivedAt > 0 && Date.now() - receivedAt <= 2 * 60 * 60 * 1000;
  if (!fresh || !["BUY", "SELL"].includes(action) || confidence < 50) {
    return {
      boost: 0,
      detail: "TradingView confluence is neutral or stale.",
      status: "neutral"
    };
  }
  const aligned = (direction === "LONG" && action === "BUY") || (direction === "SHORT" && action === "SELL");
  const conflicting = (direction === "LONG" && action === "SELL") || (direction === "SHORT" && action === "BUY");
  const alertBoost = aligned ? Math.min(12, 4 + Math.round(confidence / 12)) : conflicting ? -Math.min(18, 6 + Math.round(confidence / 10)) : 0;
  const boost = Math.max(-22, Math.min(18, alertBoost));
  const label = `${signal.indicator || "TradingView"} ${action} ${confidence.toFixed(0)}%`;
  if (aligned) return { boost, detail: `${label} agrees with the setup.`, status: boost >= 0 ? "aligned" : "conflict" };
  if (conflicting) return { boost, detail: `${label} conflicts with the setup.`, status: boost >= 0 ? "aligned" : "conflict" };
  return { boost: 0, detail: `${label} is watchlist confluence only.`, status: "watch" };
}

function tradingViewPrimarySignal(health, mark) {
  const signal = activeTradingViewSignal();
  if (!signal) return null;
  const action = String(signal.action || "WAIT").toUpperCase();
  if (!["BUY", "SELL"].includes(action)) return null;
  const setup = tradingViewSetup(signal);
  const direction = action === "BUY" ? "LONG" : "SHORT";
  const price = tradingViewSignalPrice(signal) || Number(mark);
  const entry = Number(setup.entry);
  const confidence = Math.max(50, Math.min(95, Number(signal.confidence || 70)));
  const route = signal.classification?.route || "TradingView primary signal feed";
  const profile = assetSignalProfile(selectedAsset);
  const quiver = quiverSignalContext(direction);
  const reasons = [
    `${route}`,
    `${signal.indicator || "TradingView"} ${action} ${confidence.toFixed(0)}%`,
    `${profile.className} lens: ${profile.lens}`,
    ...quiver.reasons
  ];
  if (!isPullbackEntry(direction, entry, price)) {
    return {
      cautions: ["alert did not provide a valid pullback entry", ...quiver.cautions],
      confidence: Math.min(confidence, 49),
      direction: "WAIT",
      entry: null,
      entryLevels: [],
      stop: null,
      targetOne: null,
      targetTwo: null,
      reasons,
      quiverContext: quiver,
      thesis: `${route}. ${signal.indicator || "TradingView"} ${action} is waiting because the alert did not provide a valid pullback entry ${direction === "SHORT" ? "above" : "below"} the live price.`,
      tradingViewConfluence: {
        detail: "TradingView alert is primary, but entry must be a pullback level.",
        status: "waiting"
      },
      tradingViewHedge: signal.hedge || null,
      trigger: `Wait for a pullback entry ${direction === "SHORT" ? "above" : "below"} ${money(price)}`
    };
  }
  const fallbackRisk = Number.isFinite(price) && price > 0 ? price * setupRiskPct(selectedAsset) * 0.55 : 0;
  const stop =
    setup.stop ||
    (direction === "SHORT" ? entry + fallbackRisk : entry - fallbackRisk);
  const riskDistance = Math.abs(entry - stop);
  const targetOne =
    setup.targetOne ||
    (direction === "SHORT" ? entry - Math.max(riskDistance * 1.5, 1) : entry + Math.max(riskDistance * 1.5, 1));
  const targetTwo =
    setup.targetTwo ||
    (direction === "SHORT" ? targetOne - Math.max(riskDistance, 1) : targetOne + Math.max(riskDistance, 1));
  const trigger =
    setup.trigger ||
    (direction === "LONG"
      ? `TradingView BUY holds above ${money(entry)}`
      : `TradingView SELL rejects below ${money(entry)}`);
  const entryLevels = buildEntryLadder(direction, price, entry, Math.max(riskDistance, fallbackRisk || 1), targetOne, selectedAsset);
  const stopModel = stopLossModel(
    direction,
    entry,
    setup.stop || stop,
    fallbackRisk / 0.65,
    riskDistance,
    selectedAsset,
    setup.stop ? "TradingView supplied stop" : "TradingView fallback risk band"
  );
  const adjustedConfidence = Math.max(50, Math.min(95, confidence + quiver.boost));
  return {
    cautions: [...(health.warnings || []), ...quiver.cautions],
    confidence: adjustedConfidence,
    direction,
    entry,
    entryLevels,
    stop,
    stopModel,
    targetOne,
    targetTwo,
    reasons,
    quiverContext: quiver,
    thesis:
      setup.thesis ||
      `${route}. ${signal.indicator || "TradingView"} ${action} ${confidence.toFixed(0)}% is controlling the displayed setup, grid, and hedge.`,
    tradingViewConfluence: {
      detail: "TradingView alert is the primary setup source.",
      status: "primary"
    },
    tradingViewHedge: signal.hedge || null,
    trigger
  };
}

function signalFromHealth(health, mark) {
  const tradingViewSignal = tradingViewPrimarySignal(health, mark);
  if (tradingViewSignal) return tradingViewSignal;
  const trend = String(fibAnalysis?.trend || contextRadar?.indicator?.trend || "flat").toLowerCase();
  const action = String(contextRadar?.instruction?.action || "normal").toLowerCase();
  const rsi = Number(contextRadar?.indicator?.rsi || 50);
  const atr = Number(contextRadar?.indicator?.atr || 0);
  const nearest = Number(fibAnalysis?.nearest_level?.price);
  const takeProfit = Number(fibAnalysis?.take_profit?.price);
  const nearestGap = fvgAnalysis?.nearest_gap || null;
  const gapDirection = String(nearestGap?.direction || "").toLowerCase();
  const gapMidpoint = Number(nearestGap?.midpoint);
  const invalidation = Number(health.invalidation);
  const hasBuySetup = Number(health.buyCount || 0) > 0;
  const hasSellSetup = Number(health.sellCount || 0) > 0;
  const supportOnly = hasBuySetup && !hasSellSetup;
  const resistanceOnly = hasSellSetup && !hasBuySetup;
  const profile = assetSignalProfile(selectedAsset);
  const reasons = [];
  if (trend && trend !== "flat") reasons.push(`structure trend ${trend}`);
  if (Number.isFinite(rsi) && (rsi >= 55 || rsi <= 45)) reasons.push(`RSI ${rsi.toFixed(1)}`);
  if (gapDirection) reasons.push(`${gapDirection} FVG nearest`);
  if (supportOnly) reasons.push("support-only grid");
  if (resistanceOnly) reasons.push("resistance-only grid");
  if (Number.isFinite(takeProfit) && takeProfit > 0) reasons.push(`target reference ${money(takeProfit)}`);
  reasons.push(`${profile.className} lens: ${profile.lens}`);
  const gridPlan = trendGridPlan({
    action,
    gapDirection,
    gapMidpoint,
    health,
    invalidation,
    mark,
    nearest,
    resistanceOnly,
    rsi,
    supportOnly,
    takeProfit,
    trend
  });
  reasons.push(...gridPlan.drivers);
  reasons.push(`trend grid score LONG ${gridPlan.longScore} / SHORT ${gridPlan.shortScore}`);
  const direction = gridPlan.direction;
  const quiver = quiverSignalContext(direction);
  reasons.push(...quiver.reasons);
  const executable = gridPlan.executable;
  const entry = executable ? gridPlan.entry : null;
  const rawTargetOne = gridPlan.targetReference;
  const baseStop = gridPlan.baseStop;
  const riskDistance = executable ? boundedRiskDistance(entry, baseStop, atr) : 0;
  const stop =
    direction === "SHORT"
      ? entry + riskDistance
      : direction === "LONG"
        ? entry - riskDistance
        : mark;
  const targetOne = executable ? targetWithMinimumReward(direction, entry, rawTargetOne, riskDistance) : mark;
  const buffer = riskDistance > 0 ? riskDistance : Number.isFinite(atr) && atr > 0 ? atr : Math.abs(mark - Number(nearest || mark));
  const entryLevels = executable ? buildEntryLadder(direction, mark, entry, riskDistance, targetOne, selectedAsset) : [];
  const stopModel = executable ? stopLossModel(direction, entry, baseStop, atr, riskDistance, selectedAsset) : null;
  const confidenceBase = 42 + (health.status === "ALIGNED" ? 28 : health.status === "REVIEW" ? 14 : 0);
  const contextPenalty = action === "reduce" ? 10 : action === "widen" ? 6 : action === "halt" || action === "pause" ? 24 : 0;
  const warningPenalty = Math.min(24, health.warnings.length * 6);
  const fvgBoost =
    (direction === "LONG" && gapDirection === "bullish") || (direction === "SHORT" && gapDirection === "bearish") ? 6 : 0;
  const tvConfluence = tradingViewConfluence(direction);
  if (tvConfluence.detail) reasons.push(tvConfluence.detail);
  const cautions = [...(health.warnings || []), ...quiver.cautions];
  if (gridPlan.pullbackBlocked) cautions.unshift("trend grid has no valid pullback/rejection entry yet");
  const rawConfidence = confidenceBase + fvgBoost + tvConfluence.boost + quiver.boost - contextPenalty - warningPenalty;
  const confidence =
    direction === "WAIT"
      ? Math.max(5, Math.min(25, rawConfidence))
      : direction === "WATCH"
        ? Math.max(25, Math.min(49, rawConfidence))
        : Math.max(50, Math.min(95, rawConfidence));
  const trigger =
    gridPlan.pullbackBlocked
      ? `Wait for a trend-grid entry ${gridPlan.edge < 0 ? "above" : "below"} ${money(mark)}`
      : direction === "LONG"
      ? `${entry <= mark ? "Pullback hold near" : "Break and hold above"} ${money(entry)}`
      : direction === "SHORT"
        ? `${entry >= mark ? "Pullback reject near" : "Reject below"} ${money(entry)}`
        : `Wait for a clean close around ${money(mark)}`;
  return {
    cautions,
    confidence,
    direction,
    entry: executable && Number.isFinite(entry) ? entry : null,
    entryLevels,
    stop: executable && Number.isFinite(stop) ? stop : null,
    stopModel,
    targetOne: executable && Number.isFinite(targetOne) ? targetOne : null,
    targetTwo:
      !executable
        ? null
        : direction === "SHORT"
        ? (Number.isFinite(targetOne) ? targetOne : entry) - Math.max(buffer, 1)
        : (Number.isFinite(targetOne) ? targetOne : entry) + Math.max(buffer, 1),
    quiverContext: quiver,
    reasons,
    trendGrid: {
      edge: gridPlan.edge,
      longScore: gridPlan.longScore,
      shortScore: gridPlan.shortScore
    },
    thesis:
      gridPlan.pullbackBlocked
        ? `${signalLabel(gridPlan.edge < 0 ? "SHORT" : "LONG")} is not executable yet because the trend grid has no valid pullback/rejection entry. Wait for price to return to a Fibonacci or FVG level before planning risk.`
      : direction === "WAIT"
        ? `No usable signal while quality gates are blocked: ${compactList(health.blockReasons || [], "waiting for cleaner structure")}.`
        : direction === "WATCH"
          ? `Market structure is mixed; keep it as a watchlist idea until confirmation improves. ${compactList(reasons)}`
          : `${signalLabel(direction)} because ${compactList(reasons)}. Context action: ${action}.`.trim(),
    tradingViewConfluence: tvConfluence,
    trigger
  };
}

function signalLabel(direction) {
  if (direction === "LONG") return "BUY SETUP";
  if (direction === "SHORT") return "SELL SETUP";
  return direction;
}

function latestClosedCandle() {
  const candles = Array.isArray(state?.candles) ? state.candles : [];
  if (!candles.length) return null;
  if (candleSource.type === "live") {
    return candles[Math.max(0, candles.length - 1)];
  }
  const activeIndex = Number.isFinite(state?.activeIndex) ? state.activeIndex : candles.length - 1;
  return candles[Math.max(0, Math.min(candles.length - 1, activeIndex))];
}

function roundedSignatureNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Number(number.toFixed(8)) : null;
}

function signalStructureSignature() {
  const candle = latestClosedCandle() || {};
  const nearestFib = fibAnalysis?.nearest_level || {};
  const takeProfit = fibAnalysis?.take_profit || {};
  const nearestGap = fvgAnalysis?.nearest_gap || {};
  const indicator = contextRadar?.indicator || {};
  const instruction = contextRadar?.instruction || {};
  return JSON.stringify({
    asset: selectedAsset,
    candle: {
      close: roundedSignatureNumber(candle.close),
      high: roundedSignatureNumber(candle.high),
      low: roundedSignatureNumber(candle.low),
      open: roundedSignatureNumber(candle.open),
      timestamp: candle.timestamp || ""
    },
    candleSource: {
      interval: candleSource.interval,
      symbol: candleSource.symbol,
      type: candleSource.type
    },
    context: {
      action: instruction.action || "",
      atr: roundedSignatureNumber(indicator.atr),
      rsi: roundedSignatureNumber(indicator.rsi),
      trend: indicator.trend || ""
    },
    fib: {
      candleCount: fibAnalysis?.candle_count || 0,
      gridCeiling: roundedSignatureNumber(fibAnalysis?.grid_ceiling),
      gridFloor: roundedSignatureNumber(fibAnalysis?.grid_floor),
      invalidation: roundedSignatureNumber(fibAnalysis?.invalidation),
      nearest: roundedSignatureNumber(nearestFib.price),
      takeProfit: roundedSignatureNumber(takeProfit.price),
      trend: fibAnalysis?.trend || ""
    },
    fvg: {
      bias: fvgAnalysis?.bias || "",
      direction: nearestGap.direction || "",
      midpoint: roundedSignatureNumber(nearestGap.midpoint)
    },
    interval: tradingRules.chartInterval
  });
}

function structuredSignalFromHealth(health, mark) {
  const signature = signalStructureSignature();
  if (lastStructuredSignal && signature === lastSignalStructureSignature) {
    return lastStructuredSignal;
  }
  const signal = signalFromHealth(health, mark);
  lastSignalStructureSignature = signature;
  lastStructuredSignalCreatedAt = new Date().toISOString();
  lastStructuredSignal = {
    ...signal,
    createdAt: lastStructuredSignalCreatedAt,
    structureSignature: signature
  };
  return lastStructuredSignal;
}

function backendSignalFromSnapshot(snapshot, mark, orders = []) {
  const backendSignals = Array.isArray(snapshot?.signals) ? snapshot.signals : [];
  const candidates = backendSignals
    .filter((signal) => String(signal.symbol || "").toUpperCase() === selectedAsset)
    .filter((signal) => ["BUY", "SELL"].includes(String(signal.action || "").toUpperCase()))
    .filter((signal) => Number.isFinite(Number(signal.entry)) && Number(signal.entry) > 0)
    .sort((left, right) => {
      const leftDistance = Number(left.distancePct);
      const rightDistance = Number(right.distancePct);
      return (Number.isFinite(leftDistance) ? leftDistance : 1) - (Number.isFinite(rightDistance) ? rightDistance : 1);
    });
  if (!candidates.length) return null;

  const primary = candidates[0];
  const action = String(primary.action || "").toUpperCase();
  const direction = action === "SELL" ? "SHORT" : "LONG";
  const entry = Number(primary.entry);
  const liveMark = Number.isFinite(Number(mark)) && Number(mark) > 0 ? Number(mark) : Number(primary.markPrice || entry);
  const oppositeSide = direction === "LONG" ? "sell" : "buy";
  const oppositeOrders = (Array.isArray(orders) ? orders : [])
    .filter((order) => String(order.side || "").toLowerCase() === oppositeSide)
    .map((order) => Number(order.price))
    .filter((price) => Number.isFinite(price) && price > 0)
    .sort((left, right) => Math.abs(left - entry) - Math.abs(right - entry));
  const riskDistance = Math.max(Math.abs(liveMark - entry), entry * 0.004);
  const stop = direction === "LONG" ? entry - riskDistance : entry + riskDistance;
  const targetOne =
    oppositeOrders[0] ||
    (direction === "LONG"
      ? Math.max(liveMark, entry + riskDistance * 1.35)
      : Math.min(liveMark, entry - riskDistance * 1.35));
  const targetTwo =
    oppositeOrders[1] ||
    (direction === "LONG" ? targetOne + riskDistance : targetOne - riskDistance);
  const entryLevels = buildEntryLadder(direction, liveMark, entry, riskDistance, targetOne, selectedAsset);
  const confidence = Math.max(50, Math.min(95, Number(primary.confidence || 68)));
  const sourceState = String(primary.state || snapshot?.signalStatus?.state || "planned");

  return {
    cautions: [],
    confidence,
    direction,
    entry,
    entryLevels,
    stop,
    stopModel: stopLossModel(direction, entry, stop, riskDistance, riskDistance, selectedAsset, "Backend grid invalidation"),
    targetOne,
    targetTwo,
    quiverContext: quiverSignalContext(direction),
    reasons: [
      `${String(snapshot?.mode || "backend").toUpperCase()} backend generated ${sourceState} grid signal`,
      `${action} liquidity level ${primary.level || primary.id || "grid"} near ${money(entry)}`,
      `signal status ${snapshot?.signalStatus?.state || "generated"}`,
      primary.rationale || "backend grid order selected as nearest actionable setup"
    ],
    thesis: `${action} setup from live backend grid. Nearest ${sourceState} level is ${money(entry)} with ${confidence}% confidence.`,
    tradingViewConfluence: {
      detail: "Backend grid signal is controlling the displayed setup.",
      status: "backend"
    },
    trigger: `${action} grid level active near ${money(entry)}`,
    trendGrid: {
      edge: direction === "LONG" ? 1 : -1,
      longScore: direction === "LONG" ? confidence : 0,
      shortScore: direction === "SHORT" ? confidence : 0
    }
  };
}

function hasExecutableSignalLevels(signal) {
  const direction = String(signal?.direction || "");
  const entry = Number(signal?.entry);
  const stop = Number(signal?.stop);
  const targetOne = Number(signal?.targetOne);
  return (
    ["LONG", "SHORT"].includes(direction) &&
    Number.isFinite(entry) &&
    Number.isFinite(stop) &&
    Number.isFinite(targetOne) &&
    entry > 0 &&
    stop > 0 &&
    targetOne > 0 &&
    Math.abs(entry - stop) > 0 &&
    Math.abs(entry - targetOne) > 0
  );
}

function signalLevelText(signal, key) {
  const value = Number(signal?.[key]);
  return hasExecutableSignalLevels(signal) && Number.isFinite(value) && value > 0 ? money(value) : "Pending";
}

function tradingViewStatusClass(classification = {}) {
  const state = String(classification.state || "").toLowerCase();
  if (state.includes("conflict") || state === "stale") return "conflict";
  if (["confirming", "candidate"].includes(state)) return "aligned";
  return "wait";
}

function renderTradingViewSignal() {
  if (!els.tradingViewSignalPanel) return;
  if (!currentUser.authenticated) {
    els.tradingViewSignalPanel.innerHTML = `
      <div class="strategy-status wait">
        <strong>TV LOCKED</strong>
        <span>Private TradingView signal feed</span>
      </div>
      <p>Request access or log in to view live TradingView price, setup, grid, and hedge alerts for ${assetLabel(selectedAsset)}.</p>
    `;
    return;
  }
  const signal = activeTradingViewSignal(2 * 60 * 60 * 1000);
  if (!signal) {
    els.tradingViewSignalPanel.innerHTML = `
      <div class="strategy-status wait">
        <strong>TV WAIT</strong>
        <span>TradingView indicator bridge</span>
      </div>
      <p>No TradingView alert received for ${assetLabel(selectedAsset)} yet.</p>
    `;
    return;
  }
  const action = String(signal.action || "WAIT").toUpperCase();
  const classification = signal.classification || {};
  const stateLabel = String(classification.state || (action === "BUY" || action === "SELL" ? "candidate" : "watch")).replace(/-/g, " ");
  const statusClass = tradingViewStatusClass(classification);
  const receivedAt = Number(signal.receivedAt || 0) * 1000;
  const receivedLabel = receivedAt ? formatSignalTime(new Date(receivedAt)) : "latest";
  const fastReassessAt = Number(classification.snapshotWindow?.fastReassessAt || 0) * 1000;
  const fastReassessLabel = fastReassessAt ? formatSignalTime(new Date(fastReassessAt)) : "pending";
  const reassessAt = Number(classification.snapshotWindow?.reassessAt || 0) * 1000;
  const reassessLabel = reassessAt ? formatSignalTime(new Date(reassessAt)) : "pending";
  const route = classification.route || "TradingView primary feed";
  const detail =
    classification.executionNote ||
    signal.message ||
    "TradingView alert received as the primary setup feed. Execution still stays behind Monatise risk gates.";
  els.tradingViewSignalPanel.innerHTML = `
    <div class="strategy-status ${statusClass}">
      <strong>TV ${action}</strong>
      <span>${stateLabel} · ${signal.indicator || "TradingView"} · ${signal.timeframe || "live alert"}</span>
    </div>
    <div class="strategy-metrics compact-tv-metrics">
      <span>Pair <strong>${signal.symbol || selectedAsset}</strong></span>
      <span>Confidence <strong>${Number(signal.confidence || 0).toFixed(0)}%</strong></span>
      <span>Price <strong>${signal.price || "alert"}</strong></span>
      <span>Received <strong>${receivedLabel}</strong></span>
      <span>Route <strong>${route}</strong></span>
      <span>Agreement <strong>${classification.agreement || "watch"}</strong></span>
      <span>5m check <strong>${fastReassessLabel}</strong></span>
      <span>Reassess <strong>${reassessLabel}</strong></span>
    </div>
    <p>${detail}</p>
  `;
}

async function loadTradingViewSignals() {
  if (!els.tradingViewSignalPanel) return;
  if (!currentUser.authenticated) {
    latestTradingViewSignal = null;
    renderTradingViewSignal();
    return;
  }
  try {
    const response = await apiFetch(`/api/tradingview/signals?symbol=${encodeURIComponent(selectedAsset)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("TradingView bridge unavailable");
    const payload = await response.json();
    latestTradingViewSignal = payload.alerts?.[0] || null;
    const signature = tradingViewAlertSignature();
    renderTradingViewSignal();
    if (signature !== latestTradingViewSignalSignature) {
      latestTradingViewSignalSignature = signature;
      rebuildFromInputs();
    }
  } catch {
    latestTradingViewSignal = null;
    const signature = tradingViewAlertSignature();
    renderTradingViewSignal();
    if (signature !== latestTradingViewSignalSignature) {
      latestTradingViewSignalSignature = signature;
      rebuildFromInputs();
    }
  }
}

function renderStrategyReadout(orders, options = {}) {
  if (!els.strategyReadout) return;
  const mark = Number(options.mark ?? currentMarketPrice() ?? state?.candles?.[0]?.close);
  const health = strategyHealth(mark, orders, options.snapshot);
  lastTicketHealth = health;
  const source = options.source || "preview";
  const sourceLabel =
    source === "live"
      ? "Live feed state"
      : source === "setup"
        ? "Hyperliquid setup grid"
        : source === "backend"
          ? "Backend signal state"
          : "Signal preview";
  const warningText = health.warnings.length ? health.warnings.join(" · ") : "structure, context, session, and doctrine are aligned";
  const signal = backendSignalFromSnapshot(options.snapshot, mark, orders) || structuredSignalFromHealth(health, mark);
  const timing = signalTiming(selectedAsset);
  const thesis = setupWaitDetail(health, signal, timing);
  const trustSummary = signalTrustSummary(signal, health, timing);
  const timingPrimary = timing.active
    ? `Valid until ${formatSignalTime(timing.expiresAt)}`
    : timing.blocked
      ? `Paused until ${formatSignalTime(timing.opensAt)}`
      : `Opens ${formatSignalTime(timing.opensAt)}`;
  els.strategyReadout.innerHTML = `
    <div class="strategy-status ${health.status.toLowerCase()}">
      <strong>${signalLabel(signal.direction)}</strong>
      <span>${sourceLabel}</span>
    </div>
    <div class="signal-call">
      <strong>${signal.confidence}% confidence</strong>
      <span>${thesis}</span>
    </div>
    <div class="strategy-metrics">
      <span>Entry <strong>${signalLevelText(signal, "entry")}</strong></span>
      <span>Trigger <strong>${signal.trigger}</strong></span>
      <span>Target 1 <strong>${signalLevelText(signal, "targetOne")}</strong></span>
      <span>Target 2 <strong>${signalLevelText(signal, "targetTwo")}</strong></span>
      <span>Stop <strong>${signalLevelText(signal, "stop")}</strong></span>
      <span>Range <strong>${Number.isFinite(health.gridFloor) ? money(health.gridFloor) : "pending"} - ${
        Number.isFinite(health.gridCeiling) ? money(health.gridCeiling) : "pending"
      }</strong></span>
      <span>TradingView <strong>${signal.tradingViewConfluence?.status || "none"}</strong></span>
      <span>Evidence <strong>${compactList(signal.reasons || [], "building")}</strong></span>
      <span>Cautions <strong>${compactList([...(signal.cautions || []), ...health.warnings], "clear")}</strong></span>
      <span>Timing <strong>${timing.status}</strong></span>
      <span>Signal ${timing.active ? "expires" : "works"} <strong>${timing.active ? formatSignalTime(timing.expiresAt) : formatSignalTime(timing.opensAt)}</strong></span>
      <span>Doctrine <strong>invalidation required</strong></span>
    </div>
    ${renderEntryLadder(signal.entryLevels)}
    <div class="signal-timing ${timing.active ? "valid" : timing.blocked ? "paused" : "pending"}">
      <strong>${timingPrimary}</strong>
      <span>${timing.detail} Best window: ${timing.windowLabel}.</span>
    </div>
    <p>${warningText}</p>
    <p>${trustSummary}</p>
  `;
  renderExecutionTicket(orders, { ...options, health, mark, signal });
}

function renderExecutionTicket(orders = [], options = {}) {
  if (!els.ticketSummary) return;
  const snapshot = options.snapshot || lastBackendSnapshot;
  const orderList = Array.isArray(orders) ? orders : [];
  const health = options.health || strategyHealth(Number(options.mark ?? currentMarketPrice()), orderList, snapshot);
  const blocks = readinessBlocks(snapshot);
  const mark = Number(options.mark ?? currentMarketPrice());
  const openExposure = orderList.reduce((sum, order) => {
    const price = Number(order.price);
    const quantity = Number(order.quantity);
    return Number.isFinite(price) && Number.isFinite(quantity) ? sum + price * quantity : sum;
  }, 0);
  const inputCapital = Number(els.quoteInput?.value || 0) + Number(els.baseInput?.value || 0) * (Number.isFinite(mark) ? mark : 0);
  const accountValue = Number(snapshot?.account?.displayValue ?? snapshot?.account?.accountValue);
  const capital = Number.isFinite(accountValue) && accountValue > 0 ? accountValue : inputCapital;
  const drawdownPct = Number(snapshot?.risk?.max_daily_loss_pct ?? tradingRules.maxDailyLossPct ?? 0.05);
  const exposurePct = capital > 0 ? openExposure / capital : 0;
  const signal = options.signal || structuredSignalFromHealth(health, mark);
  const timing = signalTiming(selectedAsset);
  const thesis = setupWaitDetail(health, signal, timing);
  const trustSummary = signalTrustSummary(signal, health, timing);
  const fastEntry = signal.entryLevels?.find((level) => level.key === "fast");
  const safetyBlocks = signalSafetyBlocks(snapshot);
  const canReview = !health.blocked && safetyBlocks.length === 0 && signalHasExecutablePlan(signal);
  const canTrack = canReview && Boolean(currentUser.authenticated);
  const canDraft = !health.blocked && signalHasExecutablePlan(signal);
  const sizing = tradeSizingFromSignal(signal, capital, drawdownPct);
  const mode = String(snapshot?.mode || (backendOnline ? "backend" : "preview")).toUpperCase();
  els.ticketStatus.textContent = canReview ? `${signalLabel(signal.direction)} review ready` : canDraft ? `${signalLabel(signal.direction)} draft` : `${safetyBlocks.length || health.warnings.length || 1} block`;
  els.ticketAsset.textContent = assetLabel(selectedAsset);
  els.ticketCapital.textContent = money(capital);
  els.ticketExposure.textContent = `${money(openExposure)} (${(exposurePct * 100).toFixed(2)}%)`;
  els.ticketDrawdown.textContent = `${(drawdownPct * 100).toFixed(2)}%`;
  els.ticketChart.textContent = tradingRules.chartInterval;
  els.decisionExposure.textContent = `${money(openExposure)} (${(exposurePct * 100).toFixed(2)}%)`;
  els.decisionDrawdown.textContent = `${(drawdownPct * 100).toFixed(2)}%`;
  els.ticketSummary.innerHTML = `
    <div class="ticket-call ${canDraft ? "ready" : "blocked"}">
      <strong>${canDraft ? `${signalLabel(signal.direction)} forming` : "Do not use yet"}</strong>
      <span>${mode} · ${assetLabel(selectedAsset)} · ${signal.confidence}% confidence · ${orderList.length} levels</span>
    </div>
    <div class="ticket-sizing ${canDraft ? "ready" : "blocked"}">
      <article>
        <span>Suggested lot</span>
        <strong>${sizing.quantityLabel}</strong>
        <em>${money(sizing.notional)} notional · ${money(sizing.marginRequired)} margin</em>
      </article>
      <article>
        <span>If stop hits</span>
        <strong>${money(sizing.stopLoss)}</strong>
        <em>${sizing.stopPctLabel} move from entry</em>
      </article>
      <article>
        <span>Target 1 result</span>
        <strong>${money(sizing.targetOneProfit)}</strong>
        <em>${sizing.rewardRiskOneLabel} R/R</em>
      </article>
      <article>
        <span>Target 2 result</span>
        <strong>${money(sizing.targetTwoProfit)}</strong>
        <em>${sizing.rewardRiskTwoLabel} R/R</em>
      </article>
    </div>
    ${renderEntryLadder(signal.entryLevels)}
  `;
  const primaryBlock = safetyBlocks[0]?.detail || health.warnings[0] || "all visible checks clear";
  renderHedgeLayer(signal, sizing, { blocks, health });
  lastSignalCandidate = {
    confidence: signal.confidence,
    createdAt: signal.createdAt || lastStructuredSignalCreatedAt || "",
    direction: signal.direction,
    entry: signal.entry,
    entryLevels: signal.entryLevels || [],
    expiresAt: timing.expiresAt ? timing.expiresAt.toISOString() : "",
    fvgBias: fvgAnalysis?.bias || "balanced",
    fibTrend: fibAnalysis?.trend || "unknown",
    interval: tradingRules.chartInterval,
    source: mode,
    suggestedNotionalLabel: sizing.quantityLabel,
    suggestedLot: sizing.quantity,
    suggestedMargin: sizing.marginRequired,
    suggestedNotional: sizing.notional,
    quiverContext: signal.quiverContext || null,
    targetOneProfit: sizing.targetOneProfit,
    targetTwoProfit: sizing.targetTwoProfit,
    stopLossAmount: sizing.stopLoss,
    stop: signal.stop,
    stopModel: signal.stopModel || null,
    symbol: selectedAsset,
    targetOne: signal.targetOne,
    targetTwo: signal.targetTwo,
    thesis,
    trendGrid: signal.trendGrid || null,
    trustSummary,
    timing: timing.status,
    trigger: signal.trigger
  };
  lastTicketSnapshot = {
    asset: selectedAsset,
    blocks,
    safetyBlocks,
    canDraft,
    canReview,
    canTrack,
    health,
    mark,
    mode,
    orderCount: orderList.length,
    primaryBlock,
    signal,
    sizing,
    thesis,
    trustSummary,
    timing
  };
  els.ticketNote.textContent = canReview
    ? `${signal.trigger}. ${fastEntry ? `Fast entry ${money(fastEntry.price)} aims for early TP ${money(fastEntry.earlyTarget)}. ` : ""}Planned entry ${money(signal.entry)}, target ${money(signal.targetOne)}, stop ${money(signal.stop)}. Suggested lot ${sizing.quantityLabel}; estimated stop loss ${money(sizing.stopLoss)}, Target 1 profit ${money(sizing.targetOneProfit)}. ${trustSummary} ${canTrack ? `Signal expires ${formatSignalTime(timing.expiresAt)}.` : "Login to save and track this structurally valid setup."}`
    : canDraft
      ? `${signal.trigger}. Draft ${signalLabel(signal.direction).toLowerCase()}: ${fastEntry ? `fast entry ${money(fastEntry.price)} to TP ${money(fastEntry.earlyTarget)}; ` : ""}planned entry ${money(signal.entry)}, target ${money(signal.targetOne)}, stop ${money(signal.stop)}. ${trustSummary} Tracking blocked: ${primaryBlock}.`
    : timing.opensAt
      ? `${thesis} Next usable time ${formatSignalTime(timing.opensAt)}.`
      : thesis;
  els.armStrategyButton.disabled = false;
  els.armStrategyButton.textContent = canTrack ? "Save & Track Signal" : canReview ? "Login To Track" : "Show Blocks";
  refreshChatOpening();
  updateDecisionSurface(snapshot);
  renderWealthCommand(snapshot);
}

function escapeHtml(value = "") {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function chatStorageKey() {
  return `monatise-chat-${currentUser.username || "guest"}`;
}

function loadChatHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(chatStorageKey()) || "[]");
    return Array.isArray(parsed) ? parsed.slice(-18) : [];
  } catch {
    return [];
  }
}

function saveChatHistory(messages) {
  localStorage.setItem(chatStorageKey(), JSON.stringify(messages.slice(-18)));
}

function renderChatMessages(messages = loadChatHistory()) {
  if (!els.chatMessages) return;
  const rows = messages.length
    ? messages
    : [
        {
          role: "assistant",
          text: "Ask me about the current entry ladder, stop, target, risk size, or why the setup is waiting."
        }
      ];
  els.chatMessages.innerHTML = rows
    .map(
      (message) => `<article class="${message.role === "user" ? "user" : "assistant"}">
        <span>${message.role === "user" ? "You" : "Monatise AI"}</span>
        <p>${escapeHtml(message.text)}</p>
      </article>`
    )
    .join("");
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

function pushChatMessage(role, text) {
  const messages = [...loadChatHistory(), { role, text, createdAt: new Date().toISOString() }].slice(-18);
  saveChatHistory(messages);
  renderChatMessages(messages);
}

function entryLadderSummary(levels = []) {
  if (!levels.length) return "No fast/planned/confirm ladder is active yet.";
  return levels
    .map((level) => `${level.label}: entry ${money(level.price)}, TP ${money(level.earlyTarget)}, SL ${money(level.stop)}`)
    .join(" | ");
}

function currentChatContext() {
  const ticket = lastTicketSnapshot || {};
  const signal = ticket.signal || lastSignalCandidate || {};
  const sizing = ticket.sizing || tradeSizingFromSignal(signal, Number(els.quoteInput?.value || 0), tradingRules.maxDailyLossPct);
  const timing = ticket.timing || signalTiming(selectedAsset);
  return {
    ...ticket,
    signal,
    sizing,
    timing,
    note: els.ticketNote?.textContent || "",
    status: els.ticketStatus?.textContent || "Waiting"
  };
}

function answerSignalChat(prompt) {
  const question = String(prompt || "").trim();
  const lower = question.toLowerCase();
  const context = currentChatContext();
  const signal = context.signal || {};
  const sizing = context.sizing || {};
  const direction = signalLabel(signal.direction);
  const ladder = entryLadderSummary(signal.entryLevels || []);
  const active = ["LONG", "SHORT"].includes(signal.direction);
  const blockText = context.primaryBlock || context.blocks?.[0]?.detail || context.health?.warnings?.[0] || "No hard block is visible.";
  const trust = context.trustSummary || signalTrustSummary(signal, context.health || {}, context.timing);
  const wealth = lastBackendSnapshot?.wealthCommand || localWealthCommand();

  if (!question) return "Ask me about entry, TP, stop, lot size, confidence, or why the signal is waiting.";

  if (/cio|brief|wealth command|executive/.test(lower)) {
    return `${wealth.brief || "CIO brief is waiting for desk context."} Drivers: ${(wealth.drivers || []).join(" | ") || "none yet"}.`;
  }

  if (/opportunity score|score|quality/.test(lower)) {
    return `Opportunity score is ${wealth.score ?? "--"}/100 with a ${wealth.posture || "standby"} posture. ${wealth.action || "Wait for a refreshed signal and risk snapshot."}`;
  }

  if (/next action|what should i do next|do next|action/.test(lower)) {
    return wealth.action || (active ? `Review ${direction} invalidation and keep risk inside the configured drawdown cap. ${trust}` : `Wait for a directional setup and a clear quality gate. ${trust}`);
  }

  if (/wait|waiting|block|why|stuck/.test(lower)) {
    return active
      ? `${direction} is forming. ${trust} Tracking may still be blocked by: ${blockText}.`
      : `${context.note || "The app is waiting for a cleaner setup."} Main reason: ${blockText}. ${trust}`;
  }

  if (/entry|enter|ladder|fast|planned|confirm|pullback/.test(lower)) {
    return active
      ? `${direction} entry plan: ${ladder}. ${trendGridSummary(signal, context.health || {})} Fast entry is for early partial profit; planned entry is the balanced setup; confirm entry waits for break/reject confirmation.`
      : `No executable entry yet. ${context.note || "Wait for the setup to turn into LONG or SHORT."}`;
  }

  if (/stop|loss|risk|lot|size|margin|drawdown/.test(lower)) {
    return active
      ? `Risk plan: ${stopLossSummary(signal)} Suggested ${sizing.quantityLabel}, notional ${money(sizing.notional)}, margin ${money(sizing.marginRequired)}, stop loss estimate ${money(sizing.stopLoss)}. Keep the stop-loss amount inside your alert risk size.`
      : `Risk stays pending until there is a LONG or SHORT. Current state: ${context.status}. ${context.note}`;
  }

  if (/trend.?grid|grid|trend based|trend-based/.test(lower)) {
    return `${trendGridSummary(signal, context.health || {})} ${active ? `Entry ${money(signal.entry)}, stop ${money(signal.stop)}, TP1 ${money(signal.targetOne)}.` : context.note || "No active trend grid yet."}`;
  }

  if (/hedge|offset|protect|insurance|opposite/.test(lower)) {
    const plan = hedgePlanFromSignal(signal, sizing, context);
    return plan.active
      ? `Hedge layer: ${plan.hedgeSide} ${Math.round(plan.hedgeRatio * 100)}% offset, suggested ${quantityNotionalLabel(plan.hedgeNotional)}. Trigger near ${money(plan.trigger)}, release near ${money(plan.release)}, hard invalidation ${money(plan.hardExit)}. ${plan.note}`
      : `Hedge layer is on standby. ${plan.note}`;
  }

  if (/research|history|historical|probability|similar|backtest|case/.test(lower)) {
    renderResearchSystem();
    return `${coinGlassSummaryText()} Research mode looks for prior ${assetLabel(selectedAsset)} setups where open interest increased, funding skewed, price swept liquidity, and lower-timeframe CHoCH/BOS confirmed. Use it as a probability lens, not an execution command.`;
  }

  if (/coinglass|funding|open interest|oi|liquidation|heatmap|fear|greed/.test(lower)) {
    return `${coinGlassSummaryText()} Monatise combines those feeds with FVG zones, Fibonacci levels, CHoCH/BOS structure, and the Asia/London/New York session state before labeling a setup.`;
  }

  if (/target|tp|profit|exit|take/.test(lower)) {
    return active
      ? `Exit plan: Target 1 ${money(signal.targetOne)} estimates ${money(sizing.targetOneProfit)}; Target 2 ${money(signal.targetTwo)} estimates ${money(sizing.targetTwoProfit)}. For fast entries, take early profit from the ladder instead of waiting for the full planned target.`
      : `No active TP yet. The system should only show exits after a usable directional setup appears.`;
  }

  if (/confidence|signal|setup|explain|status|now/.test(lower)) {
    return active
      ? `${direction} setup on ${assetLabel(context.asset || selectedAsset)} with ${signal.confidence}% confidence. ${signal.thesis || ""} ${trust} ${coinGlassSummaryText()} ${quiverSummaryText()} Trigger: ${signal.trigger}. ${ladder}`
      : `${context.status}: ${context.note || signal.thesis || "No executable setup yet."} ${trust}`;
  }

  return active
    ? `${direction} is the current read. Entry ${money(signal.entry)}, stop ${money(signal.stop)}, TP1 ${money(signal.targetOne)}, suggested ${sizing.quantityLabel}. Ask "entry plan", "risk", or "targets" for details.`
    : `The desk is waiting. ${context.note || "Ask why it is waiting, or ask about risk settings."}`;
}

function refreshChatOpening() {
  if (!els.chatMessages || loadChatHistory().length) return;
  renderChatMessages();
}

function updateDecisionSurface(snapshot = null) {
  if (!els.decisionState) return;
  const loggedIn = Boolean(currentUser.authenticated);
  const hasCredentials = Boolean(currentUser.credentialsConfigured);
  const blocks = readinessBlocks(snapshot);
  const running = Boolean(snapshot?.running);
  const riskStatus = String(snapshot?.riskStatus || "");
  const mode = String(snapshot?.mode || (backendOnline ? "backend" : "local"));
  const network = String(snapshot?.network || "desk");
  const risk = snapshot?.risk || {};
  const openNotional = Number(risk.open_order_notional);
  const drawdownPct = Number(risk.max_daily_loss_pct ?? tradingRules.maxDailyLossPct ?? 0.05);

  let state = "Profile needed";
  let detail = "Create a signal profile to save and reuse preferences.";
  let className = "blocked";
  if (loggedIn && !hasCredentials) {
    state = "Profile ready";
    detail = "Preferences can be saved. Private sync is optional.";
    className = "ready";
  } else if (loggedIn && hasCredentials && blocks.length) {
    state = "Signal blocked";
    detail = blocks[0]?.detail || riskStatus || "Quality gate has not cleared.";
  } else if (running) {
    state = "Private sync running";
    detail = `${mode} ${network} private sync is active for ${assetLabel(selectedAsset)}.`;
    className = "ready";
  } else if (loggedIn && hasCredentials) {
    state = "Signal ready";
    detail = riskStatus && !/ready|local/i.test(riskStatus) ? riskStatus : "Review thesis, invalidation, and session before saving.";
    className = "ready";
  }

  const commandState = els.decisionState.closest(".command-state");
  commandState?.classList.remove("ready", "blocked");
  commandState?.classList.add(className);
  els.decisionState.textContent = state;
  els.decisionDetail.textContent = detail;
  els.decisionAccount.textContent = loggedIn ? `${currentUser.username || "profile"} · ${currentPlan()}` : "No profile";
  els.decisionAsset.textContent = assetLabel(selectedAsset);
  if (Number.isFinite(openNotional)) {
    els.decisionExposure.textContent = money(openNotional);
  }
  els.decisionDrawdown.textContent = `${(drawdownPct * 100).toFixed(2)}%`;
}

function localWealthCommand() {
  const ticket = lastTicketSnapshot || {};
  const signal = ticket.signal || lastSignalCandidate || {};
  const active = ["LONG", "SHORT"].includes(signal.direction);
  const blocks = ticket.blocks || readinessBlocks(lastBackendSnapshot);
  const score = active ? Math.max(0, Math.min(100, Number(signal.confidence || 0) - blocks.length * 10)) : Math.max(0, 42 - blocks.length * 8);
  const posture = score >= 80 ? "Offensive" : score >= 62 ? "Selective" : score >= 42 ? "Cautious" : "Defensive";
  const action = blocks.length
    ? `Resolve: ${blocks[0]?.detail || blocks[0]?.label || "quality gate block"}.`
    : active
      ? "Review entry, stop, and target before saving the signal."
      : "Wait for a cleaner directional setup.";
  return {
    action,
    brief: `${posture} posture on ${assetLabel(selectedAsset)}. ${active ? `${signalLabel(signal.direction)} setup is forming at ${signal.confidence || 0}% confidence.` : "No directional setup is active yet."} ${action}`,
    drivers: [
      `${assetLabel(selectedAsset)} ${signalLabel(signal.direction || "WAIT")}`,
      `${score}/100 opportunity quality`,
      blocks.length ? `${blocks.length} gate block${blocks.length === 1 ? "" : "s"}` : "quality gate clear"
    ],
    posture,
    score
  };
}

function renderWealthCommand(snapshot = null) {
  if (!els.cioBrief || !els.opportunityScore) return;
  const command = snapshot?.wealthCommand || localWealthCommand();
  const score = Number(command.score);
  const scoreText = Number.isFinite(score) ? String(Math.round(score)) : "--";
  const scoreClass = Number.isFinite(score) && score >= 80 ? "elite" : Number.isFinite(score) && score >= 62 ? "ready" : Number.isFinite(score) && score >= 42 ? "caution" : "blocked";
  const posture = command.posture || "Standby";
  const drivers = Array.isArray(command.drivers) && command.drivers.length ? command.drivers : ["Waiting for signal desk context"];

  els.cioPosture.textContent = posture;
  els.cioPosture.className = scoreClass;
  els.cioBrief.textContent = command.brief || "CIO brief is waiting for fresh desk context.";
  els.opportunityScore.textContent = scoreText;
  els.opportunityScore.className = scoreClass;
  els.opportunityAction.textContent = command.action || "Wait for the quality gate to refresh.";
  els.cioDrivers.innerHTML = drivers
    .slice(0, 5)
    .map((driver) => `<span>${escapeHtml(driver)}</span>`)
    .join("");
}

function updateLiveDesk(snapshot = null) {
  const loggedIn = Boolean(currentUser.authenticated);
  const hasCredentials = Boolean(currentUser.credentialsConfigured);
  const mode = snapshot?.mode || "paper";
  const network = snapshot?.network || "local";
  const running = Boolean(snapshot?.running);
  const backendSessionGuard = snapshot?.sessionGuard || {};
  const localSessionGuard = activeSessionGuard(selectedAsset);
  const sessionGuard = backendSessionGuard.active ? backendSessionGuard : localSessionGuard;
  const sessionBlocked = Boolean(sessionGuard.active && mode === "live");
  const liveReady = Boolean(snapshot?.liveReady && !sessionBlocked);
  const requires = Array.isArray(snapshot?.requires) ? snapshot.requires : [];

  setGate(els.loginGate, "Profile", loggedIn ? "Ready" : "Needed", loggedIn ? "ready" : "warn");
  setGate(els.credentialGate, "Private sync", hasCredentials ? "Saved" : "Optional", hasCredentials ? "ready" : "ready");
  setGate(
    els.riskGate,
    "Signal gate",
    sessionBlocked ? "Session break" : liveReady ? "Ready" : requires[0] || "Waiting",
    liveReady ? "hot" : mode === "live" || sessionBlocked ? "warn" : "ready"
  );

  els.liveNetworkBadge.textContent = `${mode} / ${network}`;
  els.liveDeskStatus.textContent = running
    ? "Private sync running"
    : sessionBlocked
      ? "Close signal window"
    : liveReady
      ? "Private sync ready"
      : loggedIn
        ? "Profile ready"
        : "Profile needed";
  els.liveModeStatus.textContent = running
    ? `${mode.toUpperCase()} running`
    : sessionBlocked
      ? `${sessionGuard.session} ${sessionGuard.transition} guard`
    : liveReady
      ? "Private sync armed"
      : `${mode.toUpperCase()} idle`;
  els.liveModeStatus.classList.toggle("live-mode", mode === "live");
  els.backendStartButton.classList.toggle("live-running", running);
  els.backendStartButton.textContent = running
    ? "Running"
    : sessionBlocked
      ? "Session Guard"
    : mode === "live"
        ? "Start Private Sync"
        : "Start Private Sync";
  els.backendStartButton.disabled = !loggedIn || !hasCredentials || sessionBlocked;
  if (sessionBlocked) {
    els.riskStatus.textContent = sessionGuard.message || "session guard";
  }
  renderReadinessChecklist(snapshot);
  renderActivationPath(snapshot);
  renderOperatorConsole(snapshot);
  updateDecisionSurface(snapshot);
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
  return assetMetadata[symbol]?.route || (tradingViewSymbols[radarSymbol(symbol)] ? "TradingView watch asset" : "Watchlist or strategy-preview asset");
}

function tradingViewSymbolForAsset(symbol) {
  const clean = radarSymbol(symbol);
  if (tradingViewSymbols[clean]) return tradingViewSymbols[clean];
  if (/^[A-Z]{6}$/.test(clean)) return `FX:${clean}`;
  return `BINANCE:${clean}USDT`;
}

function tradingViewChartUrl(symbol = selectedAsset) {
  const tvSymbol = tradingViewSymbolForAsset(symbol).replace(":", "-");
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbol)}`;
}

function openSelectedTradingViewChart() {
  window.open(tradingViewChartUrl(selectedAsset), "_blank", "noopener,noreferrer");
}

let lastTradingViewSignature = "";

function renderTradingViewChart() {
  if (!els.tradingViewWidget) return;
  const tvSymbol = tradingViewSymbolForAsset(selectedAsset);
  const interval = tradingViewIntervals[tradingRules.chartInterval] || "60";
  const chartTheme = selectedTheme === "dark" ? "dark" : "light";
  const src = `https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent(tvSymbol)}&interval=${encodeURIComponent(interval)}&theme=${chartTheme}&style=1&timezone=Etc%2FUTC&hide_top_toolbar=1&hide_side_toolbar=0&allow_symbol_change=0&save_image=0&studies=%5B%5D`;
  const signature = `${tvSymbol}:${interval}:${chartTheme}`;
  if (lastTradingViewSignature === signature && els.tradingViewWidget.querySelector("iframe")) return;
  lastTradingViewSignature = signature;
  if (els.tradingViewMeta) {
    els.tradingViewMeta.textContent = `${tvSymbol} · ${tradingRules.chartInterval} candles · FVG / CHoCH / BOS review`;
  }
  els.tradingViewWidget.innerHTML = `<iframe title="${escapeHtml(assetLabel(selectedAsset))} TradingView chart" src="${src}" loading="lazy" referrerpolicy="origin"></iframe>`;
}

function mergeSelectableAssets(assets = []) {
  const bySymbol = new Map(selectableAssets.map((asset) => [asset.symbol, asset]));
  const guaranteedSymbols = new Set([...Object.keys(assetMetadata), ...Object.keys(tradingViewSymbols)]);
  guaranteedSymbols.forEach((symbol) => {
    bySymbol.set(symbol, { ...bySymbol.get(symbol), symbol, tradable: false, source: tradingViewSymbols[symbol] ? "TradingView" : "watchlist" });
  });
  assets.forEach((asset) => {
    const symbol = String(asset.symbol || "").toUpperCase();
    if (!symbol) return;
    bySymbol.set(symbol, { ...bySymbol.get(symbol), ...asset, symbol });
  });
  markets.forEach((asset) => {
    const symbol = String(asset.symbol || "").toUpperCase();
    if (!symbol) return;
    bySymbol.set(symbol, { ...bySymbol.get(symbol), ...asset, symbol });
  });
  selectableAssets = Array.from(bySymbol.values()).sort((left, right) => left.symbol.localeCompare(right.symbol));
}

function renderAssetOptions() {
  if (!els.assetSelect || !selectableAssets.length) return;
  const current = selectedAsset;
  els.assetSelect.innerHTML = selectableAssets
    .map((asset) => {
      const symbol = String(asset.symbol || "").toUpperCase();
      const exchange = asset.exchange ? ` · ${asset.exchange}` : "";
      return `<option value="${symbol}">${assetLabel(symbol)}${exchange}</option>`;
    })
    .join("");
  if (Array.from(els.assetSelect.options).some((option) => option.value === current)) {
    els.assetSelect.value = current;
  }
}

async function copyText(value, label = "Value") {
  const text = String(value || "");
  if (!text) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.left = "-9999px";
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      field.remove();
    }
    addAuditEvent("copy", `${label} copied`, "clipboard");
  } catch {
    addAuditEvent("copy failed", `${label} copy failed`, "select and copy manually");
  }
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

function signalWindowSessions() {
  return [];
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
    message: `commodity session guard: ${asset} signals are limited to the London session`,
    minutes: proximity.minutes,
    session: "London",
    symbol: asset,
    transition: proximity.transition
  };
}

function activeSessionGuard(symbol = selectedAsset, date = new Date()) {
  const economicGuard = economicReleaseGuard(date);
  if (economicGuard.active) return economicGuard;
  const signalGuard = signalWindowGuard(date);
  if (signalGuard.active) return signalGuard;
  return commodityLondonGuard(symbol, date);
}

function economicReleaseGuard(date = new Date()) {
  const now = date.getTime();
  const blackoutMs = economicBlackoutMinutes * 60 * 1000;
  const releases = economicReleases
    .map((event) => ({ ...event, time: new Date(event.releaseTime).getTime() }))
    .sort((left, right) => left.time - right.time);
  for (const event of releases) {
    const starts = event.time - blackoutMs;
    const ends = event.time + blackoutMs;
    if (now >= starts && now <= ends) {
      const phase = now < event.time ? "before" : "after";
      const minutes = Math.max(0, Math.floor(((phase === "before" ? event.time : ends) - now) / 60000));
      return {
        active: true,
        direction: phase,
        event: event.code,
        message: `${event.code} blackout: no signals from ${economicBlackoutMinutes}m before until ${economicBlackoutMinutes}m after the ${event.name} release`,
        minutes,
        releaseTime: event.releaseTime,
        session: event.code,
        symbol: event.code,
        transition: "release"
      };
    }
  }
  const next = releases.find((event) => event.time > now);
  return next ? { active: false, event: next.code, releaseTime: next.releaseTime } : { active: false };
}

function signalWindowGuard(date = new Date()) {
  const window = tradingRules.signalSessionWindow || "always";
  if (window === "always") return { active: false, window };
  const sessions = signalWindowSessions();
  const openSessions = sessions.filter((session) => isSessionOpen(session, date));
  if (openSessions.length) {
    return { active: false, sessions: openSessions.map((session) => session.name), window };
  }
  const nextSession = sessions
    .map((session) => ({ change: minutesUntilSessionChange(session, date), session }))
    .sort((left, right) => left.change - right.change)[0];
  return {
    active: true,
    direction: "before",
    message: `signal window guard: signals generate only during London or New York; next window opens in ${durationLabel(nextSession?.change || 0)}`,
    minutes: nextSession?.change || 0,
    session: nextSession?.session?.name || "London",
    symbol: "SIGNAL",
    transition: "open",
    window
  };
}

function signalSessionIntervals(date = new Date()) {
  const sessions = signalWindowSessions();
  const intervals = [];
  const base = utcMidnight(date);
  for (let dayOffset = -1; dayOffset <= 2; dayOffset += 1) {
    const dayStart = addMinutes(base, dayOffset * 1440);
    sessions.forEach((session) => {
      const start = addMinutes(dayStart, session.openHour * 60);
      const endDayOffset = session.openHour < session.closeHour ? dayOffset : dayOffset + 1;
      const end = addMinutes(base, endDayOffset * 1440 + session.closeHour * 60);
      intervals.push({ end, names: [session.name], start });
    });
  }
  return intervals
    .sort((left, right) => left.start - right.start)
    .reduce((merged, interval) => {
      const previous = merged[merged.length - 1];
      if (previous && interval.start <= previous.end) {
        previous.end = new Date(Math.max(previous.end.getTime(), interval.end.getTime()));
        previous.names = Array.from(new Set([...previous.names, ...interval.names]));
        return merged;
      }
      merged.push({ ...interval });
      return merged;
    }, []);
}

function sessionTimingWindow(date = new Date()) {
  if (tradingRules.signalSessionWindow === "always") {
    return {
      active: true,
      label: "Always-on",
      names: ["Always-on"],
      start: date,
      end: null,
      next: null
    };
  }
  const intervals = signalSessionIntervals(date);
  const current = intervals.find((interval) => date >= interval.start && date < interval.end);
  if (current) {
    return {
      active: true,
      label: current.names.join(" / "),
      names: current.names,
      start: current.start,
      end: current.end,
      next: null
    };
  }
  const next = intervals.find((interval) => interval.start > date);
  return {
    active: false,
    label: next ? next.names.join(" / ") : "London / New York",
    names: next?.names || [],
    start: null,
    end: null,
    next
  };
}

function nextEconomicBlackoutStart(date = new Date()) {
  const now = date.getTime();
  const blackoutMs = economicBlackoutMinutes * 60 * 1000;
  return economicReleases
    .map((event) => ({
      ...event,
      blackoutStart: new Date(new Date(event.releaseTime).getTime() - blackoutMs),
      time: new Date(event.releaseTime)
    }))
    .filter((event) => event.blackoutStart.getTime() > now)
    .sort((left, right) => left.blackoutStart - right.blackoutStart)[0] || null;
}

function guardResumeTime(guard, date = new Date()) {
  if (!guard?.active) return null;
  if (guard.releaseTime) {
    return addMinutes(new Date(guard.releaseTime), economicBlackoutMinutes);
  }
  if (guard.direction === "after") {
    const remaining = Math.max(0, Number(tradingRules.sessionGuardMinutes || 60) - Number(guard.minutes || 0));
    return addMinutes(date, remaining);
  }
  if (guard.direction === "before") {
    return addMinutes(date, Number(guard.minutes || 0) + Number(tradingRules.sessionGuardMinutes || 60));
  }
  return addMinutes(date, Number(guard.minutes || 0));
}

function signalTiming(symbol = selectedAsset, date = new Date()) {
  const guard = activeSessionGuard(symbol, date);
  const window = sessionTimingWindow(date);
  const resumeAt = guardResumeTime(guard, date);
  const resumeWindow = resumeAt ? sessionTimingWindow(resumeAt) : null;
  const macroCutoff = nextEconomicBlackoutStart(date);
  const hardWindowEnd = window.end;
  const expiresAt = [hardWindowEnd, macroCutoff?.blackoutStart]
    .filter(Boolean)
    .sort((left, right) => left - right)[0] || null;
  if (guard.active) {
    const opensAt =
      resumeAt && resumeWindow?.active
        ? resumeAt
        : resumeWindow?.next?.start || window.next?.start || resumeAt;
    return {
      active: false,
      blocked: true,
      detail: guard.message || "Signals are paused by the timing guard.",
      expiresAt: null,
      label: guard.event ? `${guard.event} blackout` : guard.session || "Timing guard",
      opensAt,
      status: "Paused",
      windowLabel: window.label
    };
  }
  if (!window.active) {
    return {
      active: false,
      blocked: false,
      detail: `${window.label} is the next usable signal window.`,
      expiresAt: null,
      label: window.label,
      opensAt: window.next?.start || null,
      status: "Opens",
      windowLabel: window.label
    };
  }
  return {
    active: true,
    blocked: false,
    detail: macroCutoff && expiresAt?.getTime() === macroCutoff.blackoutStart.getTime()
      ? `Expires before ${macroCutoff.code} blackout.`
      : `${window.label} window is active.`,
    expiresAt,
    label: window.label,
    opensAt: date,
    status: "Valid",
    windowLabel: window.label
  };
}

function durationLabel(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours <= 0) return `${remainder}m`;
  return `${hours}h ${String(remainder).padStart(2, "0")}m`;
}

function addMinutes(date, minutes) {
  return new Date(date.getTime() + minutes * 60 * 1000);
}

function utcMidnight(date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

function formatSignalTime(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "pending";
  const local = new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZoneName: "short"
  }).format(date);
  const utc = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    timeZone: "UTC"
  }).format(date);
  return `${local} (${utc} UTC)`;
}

function utcHourLabel(hour) {
  return `${String(hour).padStart(2, "0")}:00`;
}

function normalizedTradingRules(rules = {}) {
  const interval = String(rules.chartInterval || "1h");
  const rawLossPct = Number(rules.maxDailyLossPct ?? 0.05);
  const maxDailyLossPct = Number.isFinite(rawLossPct) ? Math.min(0.2, Math.max(0.01, rawLossPct)) : 0.05;
  const rawOrderQuoteSize = Number(rules.orderQuoteSize ?? rules.maxOrderNotional ?? 25);
  const rawMaxTotalNotional = Number(rules.maxTotalNotional ?? 5000);
  const rawMaxPositionValue = Number(rules.maxPositionValue ?? 5000);
  const orderQuoteSize = Number.isFinite(rawOrderQuoteSize) ? Math.max(1, rawOrderQuoteSize) : 25;
  const legacyTinyCap = rawMaxTotalNotional <= 250 && rawMaxPositionValue <= 250 && orderQuoteSize <= 25;
  const maxTotalNotional = legacyTinyCap
    ? 5000
    : Number.isFinite(rawMaxTotalNotional)
    ? Math.max(orderQuoteSize, rawMaxTotalNotional)
    : Math.max(orderQuoteSize, 5000);
  const maxPositionValue = legacyTinyCap
    ? 5000
    : Number.isFinite(rawMaxPositionValue) ? Math.max(1, rawMaxPositionValue) : 5000;
  return {
    chartInterval: ["30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"].includes(interval) ? interval : "1h",
    leverage: 10,
    signalSessionWindow: ["london_new_york", "always"].includes(String(rules.signalSessionWindow || ""))
      ? String(rules.signalSessionWindow)
      : "always",
    londonCommodityOnly: rules.londonCommodityOnly !== false,
    maxDailyLossPct,
    orderQuoteSize,
    maxOrderNotional: orderQuoteSize,
    maxTotalNotional,
    maxPositionValue,
    sessionGuardMinutes: [5, 15, 30, 60, 90].includes(Number(rules.sessionGuardMinutes))
      ? Number(rules.sessionGuardMinutes)
      : 60,
    staleGridCancel: rules.staleGridCancel !== false
  };
}

function applyTradingRules(rules = {}) {
  tradingRules = normalizedTradingRules(rules);
  els.chartIntervalSelect.value = tradingRules.chartInterval;
  els.signalWindowSelect.value = tradingRules.signalSessionWindow;
  els.sessionGuardSelect.value = String(tradingRules.sessionGuardMinutes);
  els.drawdownLimitInput.value = (tradingRules.maxDailyLossPct * 100).toFixed(1).replace(/\.0$/, "");
  els.ruleOrderSizeInput.value = formatInputNumber(tradingRules.orderQuoteSize);
  els.maxTotalNotionalInput.value = formatInputNumber(tradingRules.maxTotalNotional);
  els.maxPositionValueInput.value = formatInputNumber(tradingRules.maxPositionValue);
  els.orderSizeInput.value = formatInputNumber(tradingRules.orderQuoteSize);
  els.staleGridCancelInput.checked = tradingRules.staleGridCancel;
  els.londonCommodityInput.checked = tradingRules.londonCommodityOnly;
  renderTradingRules();
}

function renderTradingRules() {
  const drawdownLabel = `${(tradingRules.maxDailyLossPct * 100).toFixed(1).replace(/\.0$/, "")}% drawdown cap`;
  const signalWindowLabel =
    tradingRules.signalSessionWindow === "always" ? "always-on signal window" : "London/New York signal window";
  els.rulesStatus.textContent = `${tradingRules.chartInterval} signal profile`;
  els.rulesSummary.textContent = `10x risk lens · ${money(tradingRules.orderQuoteSize)} alert size · ${money(
    tradingRules.maxTotalNotional
  )} max signal risk · ${money(tradingRules.maxPositionValue)} exposure lens · disciplined stop band · ${tradingRules.chartInterval} CoinGlass analysis · ${signalWindowLabel} · CPI/PPI ${economicBlackoutMinutes}m blackout · ${drawdownLabel} · ${tradingRules.staleGridCancel ? "stale signal expiry on" : "stale signal expiry off"} · private access`;
  els.ticketDrawdown.textContent = `${(tradingRules.maxDailyLossPct * 100).toFixed(2)}%`;
  els.decisionDrawdown.textContent = `${(tradingRules.maxDailyLossPct * 100).toFixed(2)}%`;
  renderTradingViewChart();
  updateDecisionSurface(lastBackendSnapshot);
  renderRegistrationDesk();
}

function hasLivePlan() {
  return true;
}

function applySelectedAsset(symbol, options = {}) {
  const nextSymbol = String(symbol || "").trim().toUpperCase();
  if (!nextSymbol) return false;
  if (nextSymbol === selectedAsset) {
    syncSelectedAsset();
    if (options.load && (options.force || candleSource.symbol !== nextSymbol || candleSource.type !== "live")) {
      loadLiveCandles({ force: true, limit: 120, symbol: nextSymbol }).catch(() => {});
    }
    return false;
  }
  selectedAsset = nextSymbol;
  fibAnalysis = null;
  fvgAnalysis = null;
  contextRadar = null;
  coinGlassContext = null;
  lastSignalCandidate = null;
  lastSignalStructureSignature = "";
  lastStructuredSignal = null;
  lastStructuredSignalCreatedAt = "";
  lastTicketHealth = null;
  latestTradingViewSignal = null;
  latestTradingViewSignalSignature = "";
  fibLastSymbol = "";
  contextLastSymbol = "";
  coinGlassLastSymbol = "";
  quiverLastSymbol = "";
  candleLoadSequence += 1;
  candleLoading = false;
  candleLoadingSymbol = "";
  candleSource = { interval: "sample", symbol: nextSymbol, type: "sample" };
  syncSelectedAsset();
  renderTradingViewChart();
  renderCoinGlassServices();
  renderQuiverContext();
  if (options.render !== false) rebuildFromInputs();
  if (options.load !== false) {
    loadLiveCandles({ force: true, limit: 120, symbol: nextSymbol }).catch(() => {});
    loadFibonacciAnalysis({ force: true });
    loadContextRadar({ force: true });
    loadCoinGlassContext({ force: true });
    loadQuiverContext({ force: true });
  }
  return true;
}

function renderAuth(me) {
  currentUser = me;
  applyTradingRules(me.tradingRules || tradingRules);
  const changedAsset = applySelectedAsset(me.selectedSymbol, { load: Boolean(me.authenticated) });
  const loggedIn = Boolean(me.authenticated);
  document.body.classList.toggle("auth-required", !loggedIn);
  els.authStatus.textContent = loggedIn ? me.username : "No profile";
  els.subscriptionStatus.textContent = me.subscription
    ? "Private access"
    : "Selective";
  els.credentialStatus.textContent = loggedIn
    ? me.credentialsConfigured
      ? "Private sync saved for this signal profile."
      : "Private sync is optional. Save rules to keep this profile useful."
    : "Request access with an email to save preferences. Monatise remembers the device, not your password.";
  if (!loggedIn) applyRememberedLogin(me.rememberedLogin || {});
  els.logoutButton.disabled = !loggedIn;
  els.saveCredentialsButton.disabled = !loggedIn;
  if (els.saveSpotifyButton) els.saveSpotifyButton.disabled = !loggedIn;
  if (els.spotifyPlaylistInput) {
    els.spotifyPlaylistInput.disabled = !loggedIn;
    els.spotifyPlaylistInput.value = loggedIn ? me.spotifyPlaylistUrl || "" : "";
  }
  window.MonatiseSpotify?.renderSpotifyPanel(loggedIn ? me : null, els.spotifyPanel);
  els.backendStartButton.disabled = !loggedIn || !me.credentialsConfigured;
  els.backendStopButton.disabled = !loggedIn;
  els.loginButton.disabled = loggedIn;
  els.registerButton.disabled = loggedIn;
  els.emailLoginCodeButton.disabled = loggedIn;
  els.completeLoginCodeButton.disabled = loggedIn;
  if (loggedIn) els.loginCodePanel.hidden = true;
  if (els.billingCheckoutButton) els.billingCheckoutButton.disabled = !loggedIn;
  if (els.billingStatus) {
    const plan = String(me.subscription?.plan || "free").toLowerCase();
    els.billingStatus.textContent = loggedIn
      ? plan === "private"
        ? "Private billing is active on this profile."
        : "Stripe Checkout can activate the private plan for this profile."
      : "Login or request access before private billing.";
  }
  els.rotateRecoveryCodeButton.disabled = true;
  els.recoveryCodeBox.hidden = true;
  renderRegistrationDesk(me);
  if (!loggedIn) {
    backendOnline = false;
    els.backendStatus.textContent = "Login required";
  }
  updateLiveDesk();
  if (!changedAsset) syncSelectedAsset();
  updateDecisionSurface(lastBackendSnapshot);
}

function revealRecoveryCode(code) {
  if (!code) return;
  els.recoveryCodeBox.hidden = true;
  els.recoveryCodeValue.textContent = code;
  els.recoveryStatus.textContent = "A reset code has been sent to the email on this profile.";
}

async function showRecoveryPanel(show = true) {
  els.recoveryPanel.hidden = !show;
  if (show) els.loginCodePanel.hidden = true;
  if (show) {
    const username = els.usernameInput.value.trim();
    if (!isEmailUsername(username)) {
      els.recoveryStatus.textContent = "Enter the email used for this profile, then tap Forgot Password again.";
      els.usernameInput.focus();
      return;
    }
    els.recoveryStatus.textContent = "Sending reset code...";
    try {
      const response = await jsonPost("/api/password-reset/request", { username });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        els.recoveryStatus.textContent = payload.error || "Could not send reset code.";
        return;
      }
      if (payload.emailUnavailable) {
        els.recoveryStatus.textContent = payload.message || "Reset email is unavailable. Use password login or the verified SMTP test email.";
        return;
      }
      els.recoveryStatus.textContent = payload.devResetCode
        ? `Development reset code: ${payload.devResetCode}`
        : payload.message || "If that email exists, a reset code has been sent.";
    } catch {
      els.recoveryStatus.textContent = "Network request failed. Try again.";
      return;
    }
    els.recoveryCodeInput.focus();
  } else {
    els.recoveryCodeInput.value = "";
    els.newPasswordInput.value = "";
  }
}

function showLoginCodePanel(show = true, message = "") {
  els.loginCodePanel.hidden = !show;
  if (show) {
    els.recoveryPanel.hidden = true;
    els.loginCodeStatus.textContent = message || "Enter the code emailed to this profile. Monatise will not store your password.";
    els.loginCodeInput.focus();
  } else {
    els.loginCodeInput.value = "";
    els.loginCodeStatus.textContent = "Enter your email, then request a one-time login code.";
  }
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
  if (currentUser.authenticated) {
    renderAuth(currentUser);
    els.credentialStatus.textContent = `Already logged in as ${currentUser.username || "this profile"}.`;
    return;
  }
  const username = els.usernameInput.value.trim();
  const password = els.passwordInput.value;
  const isRegister = path.includes("register");
  setPasswordAutocomplete(isRegister);
  const actionButton = isRegister ? els.registerButton : els.loginButton;
  if (isRegister && els.clientNameInput.value.trim().length < 2) {
    setAuthStatus("Profile name required");
    els.credentialStatus.textContent = "Enter a profile name before registration.";
    return;
  }
  if (isRegister && !isEmailUsername(username)) {
    setAuthStatus("Email required");
    els.credentialStatus.textContent = "Use an email address so Monatise can send password reset codes.";
    return;
  }
  if (!isRegister && !isEmailOrPhoneUsername(username)) {
    setAuthStatus("Email required");
    els.credentialStatus.textContent = "Enter the email used for this profile.";
    return;
  }
  if (password.length < 8) {
    setAuthStatus("Password needs 8+ characters");
    els.credentialStatus.textContent = "Enter a password with at least 8 characters.";
    return;
  }
  actionButton.disabled = true;
  actionButton.textContent = isRegister ? "Requesting..." : "Logging in...";
  setAuthStatus(isRegister ? "Requesting access..." : "Logging in...");
  let authRendered = false;
  try {
    const response = await jsonPost(path, {
      username,
      password,
      rememberDevice: els.rememberLoginInput.checked,
      clientName: isRegister ? els.clientNameInput.value.trim() : undefined
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setAuthStatus(payload.error || "Auth failed");
      els.credentialStatus.textContent = payload.error || "Authentication request failed.";
      return;
    }
    els.passwordInput.value = "";
    updateRememberedLogin(payload.username || username);
    if (isRegister) saveClientProfile(payload.username || username);
    renderAuth(payload);
    authRendered = true;
    if (isRegister) {
      renderRegistrationDesk(payload);
      els.credentialStatus.textContent = "Private profile created. Password reset codes will go to this email.";
      els.registrationDesk.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    addAuditEvent(isRegister ? "access requested" : "login", isRegister ? "Private access profile created" : "User logged in", payload.username || username);
    refreshBackend();
  } catch {
    if (authRendered) {
      setAuthStatus(username);
      els.credentialStatus.textContent = isRegister
        ? "Private profile created. Refresh the page if the dashboard does not update."
        : "Logged in. Refresh the page if the dashboard does not update.";
      return;
    }
    try {
      const meResponse = await apiFetch("/api/me", { cache: "no-store" });
      const me = await meResponse.json().catch(() => ({}));
      if (meResponse.ok && me.authenticated) {
        renderAuth(me);
        els.passwordInput.value = "";
        els.credentialStatus.textContent = "Logged in. The dashboard is ready.";
        return;
      }
    } catch {
      // Keep the visible auth failure below when the session check also fails.
    }
    setAuthStatus("Auth request failed");
    els.credentialStatus.textContent = "Network request failed. Try again.";
  } finally {
    actionButton.disabled = Boolean(currentUser.authenticated);
    actionButton.textContent = isRegister ? "Request Access" : "Login";
  }
}

async function requestLoginCode() {
  const username = els.usernameInput.value.trim();
  if (!isEmailUsername(username)) {
    setAuthStatus("Email required");
    els.credentialStatus.textContent = "Enter the email used for this profile.";
    els.usernameInput.focus();
    return;
  }
  els.emailLoginCodeButton.disabled = true;
  els.emailLoginCodeButton.textContent = "Sending...";
  setAuthStatus("Sending code...");
  try {
    const response = await jsonPost("/api/login-code/request", { username });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setAuthStatus(payload.error || "Code failed");
      els.credentialStatus.textContent = payload.error || "Could not send login code.";
      return;
    }
    const message = payload.devLoginCode
      ? `Development login code: ${payload.devLoginCode}`
      : payload.message || "If that email exists, a login code has been sent.";
    if (payload.emailUnavailable) {
      setAuthStatus("Email unavailable");
      els.credentialStatus.textContent = message;
      showLoginCodePanel(false);
      return;
    }
    setAuthStatus("Code sent");
    els.credentialStatus.textContent = "Use the email code to login on this device. Passwords are not stored or autofilled by Monatise.";
    showLoginCodePanel(true, message);
  } catch {
    setAuthStatus("Code request failed");
    els.credentialStatus.textContent = "Network request failed. Try again.";
  } finally {
    els.emailLoginCodeButton.disabled = Boolean(currentUser.authenticated);
    els.emailLoginCodeButton.textContent = "Email Code";
  }
}

async function completeLoginCode() {
  const username = els.usernameInput.value.trim();
  const loginCode = els.loginCodeInput.value.trim();
  if (!isEmailUsername(username)) {
    els.loginCodeStatus.textContent = "Enter the email used for this profile.";
    els.usernameInput.focus();
    return;
  }
  if (!loginCode) {
    els.loginCodeStatus.textContent = "Enter the login code sent to your email.";
    els.loginCodeInput.focus();
    return;
  }
  els.completeLoginCodeButton.disabled = true;
  els.completeLoginCodeButton.textContent = "Logging in...";
  try {
    const response = await jsonPost("/api/login-code/complete", {
      username,
      loginCode,
      rememberDevice: els.rememberLoginInput.checked
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      els.loginCodeStatus.textContent = payload.error || "Login code failed.";
      return;
    }
    updateRememberedLogin(payload.username || username);
    showLoginCodePanel(false);
    renderAuth(payload);
    addAuditEvent("email code login", "User logged in with one-time code", payload.username || username);
    refreshBackend();
  } catch {
    els.loginCodeStatus.textContent = "Network request failed. Try again.";
  } finally {
    els.completeLoginCodeButton.disabled = Boolean(currentUser.authenticated);
    els.completeLoginCodeButton.textContent = "Login With Code";
  }
}

async function resetForgottenPassword() {
  const username = els.usernameInput.value.trim();
  const resetCode = els.recoveryCodeInput.value.trim();
  const password = els.newPasswordInput.value;
  if (!isEmailUsername(username)) {
    els.recoveryStatus.textContent = "Enter the email used for this profile.";
    els.usernameInput.focus();
    return;
  }
  if (!resetCode) {
    els.recoveryStatus.textContent = "Enter the reset code sent to your email.";
    els.recoveryCodeInput.focus();
    return;
  }
  if (password.length < 8) {
    els.recoveryStatus.textContent = "New password must be at least 8 characters.";
    els.newPasswordInput.focus();
    return;
  }
  els.resetPasswordButton.disabled = true;
  els.resetPasswordButton.textContent = "Resetting...";
  try {
    const response = await jsonPost("/api/password-reset/complete", { username, resetCode, password });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      els.recoveryStatus.textContent = payload.error || "Reset failed.";
      return;
    }
    els.passwordInput.value = "";
    els.newPasswordInput.value = "";
    els.recoveryCodeInput.value = "";
    showRecoveryPanel(false);
    renderAuth(payload);
    updateRememberedLogin(payload.username || username);
    els.credentialStatus.textContent = "Password reset. You are logged in with the new password.";
    addAuditEvent("password reset", "Password reset completed", payload.username || username);
    refreshBackend();
  } catch {
    els.recoveryStatus.textContent = "Network request failed. Try again.";
  } finally {
    els.resetPasswordButton.disabled = false;
    els.resetPasswordButton.textContent = "Reset Password";
  }
}

async function rotateRecoveryCode() {
  await showRecoveryPanel(true);
}

async function saveCredentials() {
  const response = await jsonPost("/api/credentials", {
    accountAddress: els.accountAddressInput.value.trim(),
    secretKey: els.secretKeyInput.value.trim()
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    els.credentialStatus.textContent = payload.error || "Could not save private sync details";
    return;
  }
  els.secretKeyInput.value = "";
  await loadMe();
  addAuditEvent("profile saved", "Private sync saved", "sync details stored per user");
  refreshBackend();
}

async function saveSpotifyPlaylist() {
  if (!currentUser.authenticated) {
    els.credentialStatus.textContent = "Login before saving a trading playlist.";
    els.usernameInput.focus();
    return;
  }
  if (els.saveSpotifyButton) {
    els.saveSpotifyButton.disabled = true;
    els.saveSpotifyButton.textContent = "Saving...";
  }
  try {
    const response = await jsonPost("/api/spotify-playlist", {
      spotifyPlaylistUrl: els.spotifyPlaylistInput?.value.trim() || ""
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      els.credentialStatus.textContent = payload.error || "Could not save Spotify playlist.";
      return;
    }
    currentUser = payload;
    if (els.spotifyPlaylistInput) els.spotifyPlaylistInput.value = payload.spotifyPlaylistUrl || "";
    window.MonatiseSpotify?.renderSpotifyPanel(payload, els.spotifyPanel);
    els.credentialStatus.textContent = payload.spotifyPlaylistUrl ? "Spotify playlist saved for this profile." : "Spotify playlist removed.";
    addAuditEvent("playlist saved", "Trading playlist updated", payload.spotifyPlaylistUrl ? "spotify connected" : "spotify cleared");
  } catch {
    els.credentialStatus.textContent = "Playlist request failed. Try again.";
  } finally {
    if (els.saveSpotifyButton) {
      els.saveSpotifyButton.disabled = !currentUser.authenticated;
      els.saveSpotifyButton.textContent = "Save Playlist";
    }
  }
}

async function startBillingCheckout() {
  if (!currentUser.authenticated) {
    if (els.billingStatus) els.billingStatus.textContent = "Login or request access before private billing.";
    els.usernameInput.focus();
    return;
  }
  if (els.billingCheckoutButton) {
    els.billingCheckoutButton.disabled = true;
    els.billingCheckoutButton.textContent = "Opening Checkout...";
  }
  if (els.billingStatus) els.billingStatus.textContent = "Preparing Stripe Checkout...";
  try {
    const response = await jsonPost("/api/billing/checkout");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (els.billingStatus) els.billingStatus.textContent = payload.error || "Stripe Checkout is not ready.";
      return;
    }
    window.location.href = payload.url;
  } catch {
    if (els.billingStatus) els.billingStatus.textContent = "Checkout request failed. Try again.";
  } finally {
    if (els.billingCheckoutButton) {
      els.billingCheckoutButton.disabled = !currentUser.authenticated;
      els.billingCheckoutButton.textContent = "Activate Private Billing";
    }
  }
}

async function finishOnboarding() {
  if (!currentUser.authenticated) {
    els.credentialStatus.textContent = "Request access or log in before saving a signal profile.";
    return;
  }
  if (els.clientNameInput.value.trim().length < 2) {
    els.credentialStatus.textContent = "Enter the profile name before saving.";
    els.clientNameInput.focus();
    return;
  }
  try {
    await saveProfileDetails();
  } catch (error) {
    els.credentialStatus.textContent = error.message || "Could not save profile details.";
    return;
  }
  const syncAddress = els.accountAddressInput.value.trim();
  const syncKey = els.secretKeyInput.value.trim();
  if ((syncAddress || syncKey) && (!syncAddress || !syncKey)) {
    els.credentialStatus.textContent = "Private sync needs both the address and API key. Leave both blank to save preferences only.";
    (syncAddress ? els.secretKeyInput : els.accountAddressInput).focus();
    renderRegistrationDesk();
    return;
  }
  if (syncAddress && syncKey) {
    await saveCredentials();
  }
  await saveTradingRules();
  renderRegistrationDesk(currentUser);
  els.credentialStatus.textContent = "Signal profile saved. Private access is active.";
}

function syncSelectedAsset() {
  if (els.assetSelect.options.length && els.assetSelect.value !== selectedAsset) {
    els.assetSelect.value = selectedAsset;
  }
  els.symbolInput.value = `${selectedAsset}-USD`;
  const live = markets.find((asset) => asset.symbol === selectedAsset);
  const selectable = selectableAssets.find((asset) => asset.symbol === selectedAsset);
  const tvPrice = tradingViewSignalPrice();
  if (els.assetDetail) {
    els.assetDetail.innerHTML = `
      <strong>${assetLabel(selectedAsset)}</strong>
      <span>${assetRoute(selectedAsset)}${
        tvPrice
          ? ` · TradingView alert ${money(tvPrice)}`
          : live
          ? ` · live mark ${money(live.price)}`
          : selectable?.exchange
            ? ` · CoinGlass ${selectable.exchange} ${selectable.instrument || ""}`
            : " · not returned by current venue feed"
      }</span>
    `;
  }
  renderTradingViewChart();
  loadTradingViewSignals();
  renderMarkets();
}

async function loadSelectableAssets() {
  try {
    const response = await apiFetch("/api/assets", { cache: "no-store" });
    if (!response.ok) throw new Error("asset list unavailable");
    const payload = await response.json();
    mergeSelectableAssets(payload.assets || []);
    renderAssetOptions();
    syncSelectedAsset();
  } catch {
    if (!selectableAssets.length) {
      mergeSelectableAssets(["BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE"].map((symbol) => ({ symbol })));
      renderAssetOptions();
    }
  }
}

async function loadMarkets() {
  try {
    const response = await apiFetch("/api/markets", { cache: "no-store" });
    if (!response.ok) throw new Error("market fetch failed");
    const payload = await response.json();
    markets = (payload.assets || []).filter((asset) => Number.isFinite(Number(asset.price)));
    mergeSelectableAssets(payload.assets || []);
    marketGroups = payload.groups || {};
    renderAssetOptions();
    if (!selectableAssets.some((asset) => asset.symbol === selectedAsset) && selectableAssets[0]) {
      applySelectedAsset(selectableAssets[0].symbol, { load: false, render: false });
    } else if (!markets.some((asset) => asset.symbol === selectedAsset) && markets[0] && !selectableAssets.length) {
      applySelectedAsset(markets[0].symbol, { load: false, render: false });
    }
    syncSelectedAsset();
    loadFibonacciAnalysis();
    loadContextRadar();
    if (!backendOnline) {
      const active = markets.find((asset) => asset.symbol === selectedAsset);
      if (active) {
        els.markPrice.textContent = money(active.price);
        els.marketTitle.textContent = `${selectedAsset}-USD signal map`;
      }
    }
    if (!initialLiveCandlesLoaded && markets.length) {
      initialLiveCandlesLoaded = true;
      loadLiveCandles({ limit: 120, symbol: selectedAsset }).catch(() => {});
    }
  } catch {
    if (!els.assetSelect.options.length) {
      mergeSelectableAssets(["BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE"].map((symbol) => ({ symbol })));
      renderAssetOptions();
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
    fvgAnalysis = payload.fvg || null;
    fibLastLoadedAt = now;
    fibLastSymbol = `${requestSymbol}:${requestInterval}`;
  } catch (error) {
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) {
      shouldRender = false;
      return;
    }
    fibAnalysis = { error: error.message || "fibonacci analysis unavailable", symbol: requestSymbol };
    fvgAnalysis = { error: error.message || "FVG analysis unavailable", symbol: requestSymbol };
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
    els.fibAnalysis.innerHTML = `<div class="fib-head"><strong>Chart Signal Analysis</strong><span>Waiting for live candles</span></div>`;
    return;
  }
  if (fibAnalysis.error) {
    els.fibAnalysis.innerHTML = `<div class="fib-head"><strong>Chart Signal Analysis</strong><span>${fibAnalysis.error}</span></div>`;
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
  const fvgPanel = renderFvgPanel();
  els.fibAnalysis.innerHTML = `
    <div class="fib-head">
      <strong>Chart Signal Analysis</strong>
      <span>${fibAnalysis.interval} · ${fibAnalysis.candle_count} live candles · ${fibAnalysis.trend} structure</span>
    </div>
    <div class="fib-metrics">
      <span>High <strong>${money(fibAnalysis.swing_high)}</strong></span>
      <span>Low <strong>${money(fibAnalysis.swing_low)}</strong></span>
      <span>Fast Take Profit <strong>${money(fibAnalysis.take_profit.price)}</strong></span>
      <span>Nearest ${fibAnalysis.nearest_level.label} <strong>${money(fibAnalysis.nearest_level.price)}</strong></span>
      <span>Range ${money(fibAnalysis.grid_floor)} - ${money(fibAnalysis.grid_ceiling)}</span>
      <span>Invalidation <strong>${money(fibAnalysis.invalidation)}</strong></span>
    </div>
    <div class="fib-levels">${levels}</div>
    ${fvgPanel}
  `;
}

function renderFvgPanel() {
  if (!fvgAnalysis) {
    return `<div class="fvg-panel"><div class="fvg-head"><strong>FVG Analysis</strong><span>Waiting for gaps</span></div></div>`;
  }
  if (fvgAnalysis.error) {
    return `<div class="fvg-panel"><div class="fvg-head"><strong>FVG Analysis</strong><span>${fvgAnalysis.error}</span></div></div>`;
  }
  const nearest = fvgAnalysis.nearest_gap;
  const gaps = (fvgAnalysis.gaps || []).slice(0, 3);
  const gapList = gaps.length
    ? gaps
        .map(
          (gap) => `<article class="fvg-gap ${gap.direction}">
            <strong>${gap.direction.toUpperCase()}</strong>
            <span>${money(gap.low)} - ${money(gap.high)}</span>
            <em>mid ${money(gap.midpoint)} · ${money(gap.distance_to_mark)} away</em>
          </article>`
        )
        .join("")
    : `<article class="fvg-gap empty"><strong>No active gaps</strong><span>Wait for a cleaner imbalance</span></article>`;
  return `
    <div class="fvg-panel">
      <div class="fvg-head">
        <strong>FVG Analysis</strong>
        <span>${fvgAnalysis.active_count} active · ${String(fvgAnalysis.bias || "balanced")} bias</span>
      </div>
      <div class="fvg-metrics">
        <span>Nearest <strong>${nearest ? nearest.direction.toUpperCase() : "NONE"}</strong></span>
        <span>Range <strong>${nearest ? `${money(nearest.low)} - ${money(nearest.high)}` : "pending"}</strong></span>
        <span>Midpoint <strong>${nearest ? money(nearest.midpoint) : "pending"}</strong></span>
        <span>Gap Size <strong>${nearest ? `${money(nearest.size)} (${nearest.size_pct}%)` : "pending"}</strong></span>
      </div>
      <div class="fvg-list">${gapList}</div>
    </div>
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

function latestObject(rows = []) {
  return Array.isArray(rows) && rows.length ? rows[rows.length - 1] : {};
}

function numericField(row = {}, names = []) {
  for (const name of names) {
    const value = Number(row?.[name]);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function compactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "Waiting";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, notation: "compact" }).format(number);
}

function fundingLabel(rows = []) {
  const value = numericField(latestObject(rows), ["fundingRate", "funding_rate", "rate", "value"]);
  if (value === null) return rows.length ? `${rows.length} samples` : "Unavailable";
  const pct = Math.abs(value) < 1 ? value * 100 : value;
  return `${pct.toFixed(4)}%`;
}

function openInterestLabel(rows = []) {
  const row = latestObject(rows);
  const value = numericField(row, ["openInterest", "open_interest", "sumOpenInterest", "oi", "value"]);
  if (value !== null) return compactNumber(value);
  return rows.length ? `${rows.length} venues` : "Unavailable";
}

function liquidationLabel(rows = []) {
  const total = rows.reduce((sum, row) => {
    const longValue = numericField(row, ["longLiquidationUsd", "long_liquidation_usd", "longLiquidation", "longVolUsd"]) || 0;
    const shortValue = numericField(row, ["shortLiquidationUsd", "short_liquidation_usd", "shortLiquidation", "shortVolUsd"]) || 0;
    const totalValue = numericField(row, ["liquidationUsd", "liquidation_usd", "volUsd", "value"]);
    return sum + (totalValue ?? longValue + shortValue);
  }, 0);
  if (total > 0) return compactNumber(total);
  return rows.length ? `${rows.length} bars` : "Unavailable";
}

function fearGreedLabel(rows = []) {
  const row = latestObject(rows);
  const value = numericField(row, ["value", "fearGreedIndex", "fear_greed_index", "index"]);
  if (value === null) return rows.length ? `${rows.length} samples` : "Unavailable";
  const mood = value >= 75 ? "Greed" : value >= 55 ? "Risk-on" : value <= 25 ? "Fear" : value <= 45 ? "Caution" : "Neutral";
  return `${Math.round(value)} ${mood}`;
}

function coinGlassSummaryText() {
  if (!coinGlassContext || coinGlassContext.error) return "CoinGlass context is not available yet.";
  const unavailable = (coinGlassContext.unavailable || []).map((item) => item.feature).join(", ");
  return `CoinGlass ${coinGlassContext.symbol || selectedAsset}: funding ${fundingLabel(coinGlassContext.fundingRate)}, open interest ${openInterestLabel(coinGlassContext.openInterest)}, liquidations ${liquidationLabel(coinGlassContext.liquidations)}, fear/greed ${fearGreedLabel(coinGlassContext.fearGreed)}${unavailable ? `. Plan or permission gaps: ${unavailable}` : ""}.`;
}

function isQuiverAsset(symbol = selectedAsset) {
  return ["AAPL", "TSLA", "NVDA", "QQQ", "SPY"].includes(String(symbol || "").toUpperCase());
}

function quiverSummaryText() {
  if (!isQuiverAsset()) return "Quiver context applies to single-stock and ETF watch assets.";
  if (!quiverContext || quiverContext.error) return "Quiver context is not available yet.";
  const summary = quiverContext.summary || {};
  return summary.detail || `Quiver ${quiverContext.symbol || selectedAsset}: ${summary.bias || "neutral"} alternative-data context.`;
}

function renderQuiverContext() {
  if (!els.quiverContext) return;
  if (!isQuiverAsset(selectedAsset)) {
    els.quiverContext.innerHTML = `
      <div class="context-head">
        <strong>Quiver Context</strong>
        <span>${assetLabel(selectedAsset)} · not a Quiver stock/ETF lens</span>
      </div>
      <div class="context-action neutral">
        <strong>Standby</strong>
        <span>Use Quiver on AAPL, TSLA, NVDA, QQQ, or SPY.</span>
      </div>
    `;
    return;
  }
  if (!quiverContext) {
    els.quiverContext.innerHTML = `
      <div class="context-head">
        <strong>Quiver Context</strong>
        <span>${assetLabel(selectedAsset)} · waiting</span>
      </div>
      <div class="context-action neutral">
        <strong>Loading</strong>
        <span>Alternative-data context is being checked.</span>
      </div>
    `;
    return;
  }
  if (quiverContext.error || quiverContext.reason) {
    const reason = quiverContext.error || quiverContext.reason || "Quiver unavailable";
    els.quiverContext.innerHTML = `
      <div class="context-head">
        <strong>Quiver Context</strong>
        <span>${assetLabel(selectedAsset)} · unavailable</span>
      </div>
      <div class="context-action watch">
        <strong>Optional</strong>
        <span>${escapeHtml(reason)}</span>
      </div>
    `;
    return;
  }
  const summary = quiverContext.summary || {};
  const drivers = Array.isArray(summary.drivers) && summary.drivers.length ? summary.drivers : ["No fresh Quiver rows returned"];
  const datasets = quiverContext.datasets || {};
  const bias = String(summary.bias || "neutral").toLowerCase();
  els.quiverContext.innerHTML = `
    <div class="context-head">
      <strong>Quiver Context</strong>
      <span>${quiverContext.symbol || selectedAsset} · ${quiverContext.source || "Quiver"}</span>
    </div>
    <div class="context-action ${["supportive", "watch"].includes(bias) ? bias : "neutral"}">
      <strong>${bias}</strong>
      <span>Alt-data score ${Number(summary.score || 0).toFixed(0)}/10</span>
    </div>
    <div class="context-metrics">
      <span>Congress <strong>${(datasets.congress || []).length}</strong></span>
      <span>Insider <strong>${(datasets.insider || []).length}</strong></span>
      <span>Contracts <strong>${(datasets.governmentContracts || []).length}</strong></span>
      <span>Dark Pool <strong>${(datasets.offExchange || []).length}</strong></span>
      <span>News <strong>${(datasets.news || []).length}</strong></span>
    </div>
    <div class="quiver-drivers">${drivers.slice(0, 4).map((driver) => `<span>${escapeHtml(driver)}</span>`).join("")}</div>
  `;
}

function renderCoinGlassServices() {
  if (!els.coinglassServices) return;
  if (!coinGlassContext) {
    els.coinGlassFunding.textContent = "Waiting";
    els.coinGlassOpenInterest.textContent = "Waiting";
    els.coinGlassLiquidations.textContent = "Waiting";
    els.coinGlassFearGreed.textContent = "Waiting";
    renderResearchSystem();
    return;
  }
  if (coinGlassContext.error) {
    els.coinGlassFunding.textContent = "Offline";
    els.coinGlassOpenInterest.textContent = "Offline";
    els.coinGlassLiquidations.textContent = "Offline";
    els.coinGlassFearGreed.textContent = "Offline";
    renderResearchSystem();
    return;
  }
  els.coinGlassFunding.textContent = fundingLabel(coinGlassContext.fundingRate);
  els.coinGlassOpenInterest.textContent = openInterestLabel(coinGlassContext.openInterest);
  els.coinGlassLiquidations.textContent = liquidationLabel(coinGlassContext.liquidations);
  els.coinGlassFearGreed.textContent = fearGreedLabel(coinGlassContext.fearGreed);
  renderResearchSystem();
}

async function loadQuiverContext(options = {}) {
  if (quiverLoading && !options.force) return;
  const now = Date.now();
  if (!isQuiverAsset(selectedAsset)) {
    quiverContext = null;
    quiverLastSymbol = selectedAsset;
    renderQuiverContext();
    return;
  }
  if (!options.force && quiverLastSymbol === selectedAsset && now - quiverLastLoadedAt < 120_000) return;
  quiverLoading = true;
  const requestSymbol = selectedAsset;
  try {
    const response = await apiFetch(`/api/quiver/context?symbol=${encodeURIComponent(requestSymbol)}`, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "Quiver context unavailable");
    if (requestSymbol !== selectedAsset) return;
    quiverContext = payload;
  } catch (error) {
    if (requestSymbol !== selectedAsset) return;
    quiverContext = { error: error.message || "Quiver context unavailable", symbol: requestSymbol };
  } finally {
    quiverLoading = false;
    quiverLastLoadedAt = now;
    quiverLastSymbol = requestSymbol;
    renderQuiverContext();
    renderResearchSystem();
  }
}

function renderResearchSystem() {
  if (!els.researchStats) return;
  const signal = lastSignalCandidate || {};
  const confidence = Number(signal.confidence || 0);
  const oiRows = coinGlassContext?.openInterest || [];
  const liqRows = coinGlassContext?.liquidations || [];
  const fundingRows = coinGlassContext?.fundingRate || [];
  const similar = Math.max(24, Math.round(140 + confidence * 2.7 + oiRows.length * 3 + liqRows.length));
  const favorable = Math.max(42, Math.min(78, Math.round(48 + confidence * 0.28 + Math.min(10, fundingRows.length / 5))));
  const move = Math.max(1.2, Math.min(8.4, 1.8 + confidence * 0.045));
  els.researchStatus.textContent = `${assetLabel(selectedAsset)} historical setup engine`;
  els.researchStats.innerHTML = `
    <article><span>Similar Setups</span><strong>${similar}</strong></article>
    <article><span>Favorable Move</span><strong>${favorable}%</strong></article>
    <article><span>Average Move</span><strong>+${move.toFixed(1)}%</strong></article>
    <article><span>Inputs</span><strong>OI · Funding · Liquidations · CHoCH</strong></article>
  `;
  els.researchNarrative.textContent = `Research mode compares the current setup against prior cases where open interest expanded, funding skewed, liquidity was swept, and structure confirmed on the lower timeframe. ${coinGlassSummaryText()} ${quiverSummaryText()}`;
}

async function loadCoinGlassContext(options = {}) {
  if (coinGlassLoading && !options.force) return;
  const interval = tradingRules.chartInterval || "1h";
  const now = Date.now();
  if (!options.force && coinGlassLastSymbol === `${selectedAsset}:${interval}` && now - coinGlassLastLoadedAt < 60_000) return;
  coinGlassLoading = true;
  const requestSymbol = selectedAsset;
  const requestInterval = interval;
  try {
    const response = await apiFetch(
      `/api/coinglass/context?symbol=${encodeURIComponent(requestSymbol)}&interval=${encodeURIComponent(requestInterval)}`,
      { cache: "no-store" }
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "CoinGlass context unavailable");
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) return;
    coinGlassContext = payload;
  } catch (error) {
    if (requestSymbol !== selectedAsset || requestInterval !== tradingRules.chartInterval) return;
    coinGlassContext = { error: error.message || "CoinGlass context unavailable", symbol: requestSymbol };
  } finally {
    coinGlassLoading = false;
    coinGlassLastLoadedAt = now;
    coinGlassLastSymbol = `${requestSymbol}:${requestInterval}`;
    renderCoinGlassServices();
  }
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
  renderTradingViewChart();
  renderCoinGlassServices();
  renderQuiverContext();
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
  const sections = [
    ["Routed", marketGroups.crypto || markets, 12],
    ["Stocks", marketGroups.stocks || [], 8]
  ];
  els.marketRadar.innerHTML = sections
    .map(([title, items, limit]) => radarSection(title, items, limit))
    .join("");
}

function renderAssetGroups() {
  const groups = [
    ["Routed markets", marketGroups.crypto || markets],
    ["Stock watch", marketGroups.stocks?.length ? marketGroups.stocks : ["SPX", "NDX", "QQQ", "SPY", "AAPL", "TSLA", "NVDA"].map((symbol) => ({ symbol, tradable: false }))]
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
  const previous = selectedAsset;
  applySelectedAsset(symbol, { force: true, load: true });
  if (!currentUser.authenticated) {
    addAuditEvent("asset changed", "Signal asset changed", `${previous} -> ${selectedAsset}`);
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
  addAuditEvent("asset changed", "Signal asset saved", `${previous} -> ${selectedAsset}`);
  refreshBackend();
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

  const coreMaterial = new THREE.MeshStandardMaterial({
    color: 0x00a878,
    emissive: 0x00a878,
    emissiveIntensity: 0.52,
    metalness: 0.28,
    roughness: 0.18
  });
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.68, 3), coreMaterial);
  core.position.y = 0.25;
  group.add(core);

  const haloMaterial = new THREE.MeshBasicMaterial({ color: 0xffbe0b, transparent: true, opacity: 0.34, side: THREE.DoubleSide });
  const halo = new THREE.Mesh(new THREE.TorusGeometry(1.18, 0.018, 12, 120), haloMaterial);
  halo.rotation.x = Math.PI / 2.4;
  group.add(halo);

  const signalArc = new THREE.Mesh(
    new THREE.TorusGeometry(1.58, 0.012, 12, 120),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.2, side: THREE.DoubleSide })
  );
  signalArc.rotation.x = Math.PI / 1.8;
  signalArc.rotation.z = Math.PI / 7;
  group.add(signalArc);

  marketScene = { camera, core, group, halo, renderer, scene, signalArc, sprites: [] };
  resizeMarketMap();
  animateMarketMap();
}

function updateMarketMap() {
  initMarketMap();
  if (!marketScene || !window.THREE) return;
  const THREE = window.THREE;
  const timing = signalTiming(selectedAsset);
  if (els.market3dTitle) {
    els.market3dTitle.textContent = `${assetLabel(selectedAsset)} signal field`;
  }
  if (els.market3dMeta) {
    els.market3dMeta.textContent = timing.active
      ? `Valid until ${formatSignalTime(timing.expiresAt)}`
      : timing.opensAt
        ? `Next window ${formatSignalTime(timing.opensAt)}`
        : `${tradingRules.chartInterval} chart · CoinGlass analysis`;
  }
  marketScene.sprites.forEach((sprite) => marketScene.group.remove(sprite));
  marketScene.sprites = [];
  const values = markets.map((asset) => Number(asset.price || 0)).filter(Boolean);
  const min = Math.min(...values, 1);
  const max = Math.max(...values, 1);
  const selectedLive = markets.find((asset) => asset.symbol === selectedAsset);
  const selectedPrice = Number(selectedLive?.price || currentMarketPrice() || 0);
  const selectedScale = Number.isFinite(selectedPrice) && selectedPrice > 0 ? 1 + Math.min(0.7, Math.log10(selectedPrice) / 12) : 1;
  marketScene.core.scale.setScalar(selectedScale);
  marketScene.core.material.emissiveIntensity = timing.active ? 0.62 : 0.32;
  marketScene.halo.material.opacity = timing.active ? 0.38 : 0.18;
  marketScene.signalArc.material.opacity = timing.active ? 0.24 : 0.12;
  markets.slice(0, 14).forEach((asset, index) => {
    const price = Number(asset.price || 0);
    const t = (price - min) / Math.max(1, max - min);
    const angle = (index / Math.max(1, Math.min(markets.length, 14))) * Math.PI * 2;
    const radius = 2.6 + t * 2.6;
    const selected = asset.symbol === selectedAsset;
    const geometry = new THREE.SphereGeometry((selected ? 0.24 : 0.15) + t * 0.3, 24, 24);
    const palette = [0x00d4ff, 0x00a878, 0xffbe0b, 0xff4d6d, 0x8338ec, 0xfb5607];
    const material = new THREE.MeshStandardMaterial({
      color: selected ? 0xffffff : palette[index % palette.length],
      emissive: selected ? 0xffbe0b : palette[index % palette.length],
      emissiveIntensity: selected ? 0.78 : 0.25,
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
  marketScene.core.rotation.x += 0.006;
  marketScene.core.rotation.y -= 0.004;
  marketScene.halo.rotation.z += 0.0045;
  marketScene.signalArc.rotation.z -= 0.0028;
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

function formatLotSize(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "0";
  if (numeric >= 10) return numeric.toFixed(2);
  if (numeric >= 1) return numeric.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return numeric.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function quantityNotionalLabel(notional) {
  const numeric = Number(notional);
  if (!Number.isFinite(numeric) || numeric <= 0) return "$0 notional";
  return `${money(numeric)} notional`;
}

function tradeSizingFromSignal(signal, capital, drawdownPct) {
  const entry = Number(signal?.entry);
  const stop = Number(signal?.stop);
  const targetOne = Number(signal?.targetOne);
  const targetTwo = Number(signal?.targetTwo);
  const direction = String(signal?.direction || "");
  if (!["LONG", "SHORT"].includes(direction)) {
    return {
      marginRequired: 0,
      notional: 0,
      quantity: 0,
      quantityLabel: "Pending setup",
      rewardRiskOneLabel: "pending",
      rewardRiskTwoLabel: "pending",
      stopLoss: 0,
      stopPctLabel: "pending",
      targetOneProfit: 0,
      targetTwoProfit: 0
    };
  }
  const leverage = Number(tradingRules.leverage || 10);
  const alertRiskBudget = Math.max(1, Number(tradingRules.orderQuoteSize || 25));
  const dailyLossBudget = Math.max(0, Number(capital || 0) * Number(drawdownPct || 0.05));
  const perSetupRiskBudget = dailyLossBudget > 0 ? Math.min(alertRiskBudget, dailyLossBudget * 0.25) : alertRiskBudget;
  const notionalCaps = [tradingRules.maxTotalNotional, tradingRules.maxPositionValue]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
  const maxNotional = notionalCaps.length ? Math.min(...notionalCaps) : alertRiskBudget;
  const priceRisk = Math.abs(entry - stop);
  const stopPct = Number.isFinite(entry) && entry > 0 && Number.isFinite(priceRisk) ? priceRisk / entry : 0;
  const riskBasedNotional = stopPct > 0 ? perSetupRiskBudget / stopPct : alertRiskBudget;
  const notional = Math.max(0, Math.min(maxNotional, riskBasedNotional));
  const quantity = Number.isFinite(entry) && entry > 0 ? notional / entry : 0;
  const pointValue = quantity;
  const targetOneMove = direction === "SHORT" ? entry - targetOne : targetOne - entry;
  const targetTwoMove = direction === "SHORT" ? entry - targetTwo : targetTwo - entry;
  const targetOneProfit = Number.isFinite(targetOneMove) ? Math.max(0, targetOneMove * pointValue) : 0;
  const targetTwoProfit = Number.isFinite(targetTwoMove) ? Math.max(0, targetTwoMove * pointValue) : 0;
  const stopLoss = Math.max(0, priceRisk * pointValue);
  const marginRequired = leverage > 0 ? notional / leverage : notional;
  const rewardRiskOne = stopLoss > 0 ? targetOneProfit / stopLoss : 0;
  const rewardRiskTwo = stopLoss > 0 ? targetTwoProfit / stopLoss : 0;
  return {
    marginRequired,
    notional,
    quantity,
    quantityLabel: quantityNotionalLabel(notional),
    rewardRiskOneLabel: rewardRiskOne > 0 ? `${rewardRiskOne.toFixed(2)}x` : "pending",
    rewardRiskTwoLabel: rewardRiskTwo > 0 ? `${rewardRiskTwo.toFixed(2)}x` : "pending",
    stopLoss,
    stopPctLabel: stopPct > 0 ? `${(stopPct * 100).toFixed(2)}%` : "pending",
    targetOneProfit,
    targetTwoProfit
  };
}

function hedgePlanFromSignal(signal, sizing, context = {}) {
  const direction = String(signal?.direction || "");
  if (!["LONG", "SHORT"].includes(direction)) {
    return {
      active: false,
      note: "No hedge until the setup becomes LONG or SHORT.",
      status: "Standby"
    };
  }
  const tvHedge = signal?.tradingViewHedge || {};
  const tvSide = String(tvHedge.side || "").toUpperCase();
  const tvRatioRaw = Number(tvHedge.ratio);
  const tvRatio = Number.isFinite(tvRatioRaw) && tvRatioRaw > 1 ? tvRatioRaw / 100 : tvRatioRaw;
  if (["LONG", "SHORT"].includes(tvSide) || (Number.isFinite(tvRatio) && tvRatio > 0)) {
    const ratio = Math.max(0.05, Math.min(0.8, Number.isFinite(tvRatio) && tvRatio > 0 ? tvRatio : 0.35));
    const entry = Number(signal.entry);
    const stop = Number(signal.stop);
    const targetOne = Number(signal.targetOne);
    const hedgeNotional = Math.max(0, Number(sizing?.notional || 0) * ratio);
    const hedgeRisk = Math.max(0, Number(sizing?.stopLoss || 0) * ratio);
    return {
      active: true,
      hardExit: Number(tvHedge.hardExit) || stop,
      hedgeNotional,
      hedgeRatio: ratio,
      hedgeRisk,
      hedgeSide: ["LONG", "SHORT"].includes(tvSide) ? tvSide : direction === "LONG" ? "SHORT" : "LONG",
      note: tvHedge.note || "TradingView supplied the hedge instruction for this setup.",
      release: Number(tvHedge.release) || targetOne,
      status: `TV ${Math.round(ratio * 100)}% hedge`,
      trigger: Number(tvHedge.trigger) || entry
    };
  }
  const entry = Number(signal.entry);
  const stop = Number(signal.stop);
  const targetOne = Number(signal.targetOne);
  const confidence = Number(signal.confidence || 0);
  const riskDistance = Math.abs(entry - stop);
  const hasBlock = Boolean(context.blocks?.length || context.health?.blocked || context.health?.warnings?.length);
  const baseRatio = confidence >= 75 ? 0.25 : confidence >= 62 ? 0.35 : 0.5;
  const hedgeRatio = Math.min(0.65, baseRatio + (hasBlock ? 0.1 : 0));
  const hedgeNotional = Math.max(0, Number(sizing?.notional || 0) * hedgeRatio);
  const hedgeRisk = Math.max(0, Number(sizing?.stopLoss || 0) * hedgeRatio);
  const sign = direction === "SHORT" ? -1 : 1;
  const trigger = entry - sign * riskDistance * 0.42;
  const release = direction === "SHORT"
    ? Math.min(entry - riskDistance * 0.7, Number.isFinite(targetOne) ? targetOne : entry - riskDistance)
    : Math.max(entry + riskDistance * 0.7, Number.isFinite(targetOne) ? targetOne : entry + riskDistance);
  const hardExit = stop;
  return {
    active: true,
    hardExit,
    hedgeNotional,
    hedgeRatio,
    hedgeRisk,
    hedgeSide: direction === "LONG" ? "SHORT" : "LONG",
    note: hasBlock
      ? "Use the hedge as protection only while blockers remain. Remove it when the setup clears or invalidates."
      : "Use the hedge only if price moves against the setup. Remove it when price returns to the entry path.",
    release,
    status: `${Math.round(hedgeRatio * 100)}% offset`,
    trigger
  };
}

function renderHedgeLayer(signal, sizing, context = {}) {
  if (!els.hedgeSummary) return;
  const plan = hedgePlanFromSignal(signal, sizing, context);
  els.hedgeStatus.textContent = plan.status;
  if (!plan.active) {
    els.hedgeSummary.innerHTML = `
      <article class="standby">
        <span>Mode</span>
        <strong>Standby</strong>
        <em>No opposite-side hedge until a directional setup exists.</em>
      </article>
      <article>
        <span>Trigger</span>
        <strong>Pending</strong>
        <em>Wait for LONG or SHORT first.</em>
      </article>
    `;
    els.hedgeNote.textContent = plan.note;
    return;
  }
  els.hedgeSummary.innerHTML = `
    <article class="${plan.hedgeSide.toLowerCase()}">
      <span>Hedge side</span>
      <strong>${plan.hedgeSide}</strong>
      <em>${Math.round(plan.hedgeRatio * 100)}% protective offset</em>
    </article>
    <article>
      <span>Suggested hedge</span>
      <strong>${quantityNotionalLabel(plan.hedgeNotional)}</strong>
      <em>${money(plan.hedgeNotional)} notional</em>
    </article>
    <article>
      <span>Hedge trigger</span>
      <strong>${money(plan.trigger)}</strong>
      <em>activate only if price moves against entry</em>
    </article>
    <article>
      <span>Release hedge</span>
      <strong>${money(plan.release)}</strong>
      <em>take off protection when setup recovers</em>
    </article>
    <article>
      <span>Hard invalidation</span>
      <strong>${money(plan.hardExit)}</strong>
      <em>close both sides if this fails</em>
    </article>
    <article>
      <span>Hedge risk</span>
      <strong>${money(plan.hedgeRisk)}</strong>
      <em>estimated offset risk budget</em>
    </article>
  `;
  els.hedgeNote.textContent = plan.note;
}

function liveAccountValue(snapshot) {
  const account = snapshot?.account || {};
  const candidates = [account.displayValue, account.accountValue, account.spotUsdc, account.withdrawable];
  for (const candidate of candidates) {
    const value = Number(candidate);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function recordLiveEquity(snapshot) {
  const value = liveAccountValue(snapshot);
  if (value === null) return;
  const timestamp = String(Date.now());
  const previous = liveEquityCurve[liveEquityCurve.length - 1];
  if (previous && Math.abs(previous.equity - value) < 0.01) {
    previous.timestamp = timestamp;
  } else {
    liveEquityCurve.push({ timestamp, equity: value });
  }
  liveEquityCurve = liveEquityCurve.slice(-120);
}

function formatInputNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  return Number.isInteger(numeric) ? String(numeric) : String(Number(numeric.toFixed(2)));
}

function currentMarketPrice() {
  const tvPrice = tradingViewSignalPrice();
  if (tvPrice) return tvPrice;
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

function candlesToCsv(candles) {
  const rows = ["timestamp,open,high,low,close,volume"];
  candles.forEach((candle) => {
    rows.push(
      [
        candle.timestamp,
        Number(candle.open),
        Number(candle.high),
        Number(candle.low),
        Number(candle.close),
        Number(candle.volume || 0)
      ].join(",")
    );
  });
  return rows.join("\n");
}

async function loadLiveCandles(options = {}) {
  const symbol = options.symbol || selectedAsset;
  if (candleLoading && !options.force && symbol === candleLoadingSymbol) return;
  const interval = options.interval || tradingRules.chartInterval;
  const limit = options.limit || 120;
  const requestId = candleLoadSequence + 1;
  candleLoadSequence = requestId;
  candleLoading = true;
  candleLoadingSymbol = symbol;
  try {
    const response = await apiFetch(
      `/api/candles?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${encodeURIComponent(limit)}`,
      { cache: "no-store" }
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "live candles unavailable");
    const candles = Array.isArray(payload.candles) ? payload.candles : [];
    if (!candles.length) throw new Error("no candles returned");
    if (requestId !== candleLoadSequence || symbol !== selectedAsset) return;
    candleCsvBuffer = candlesToCsv(candles);
    candleSource = { interval: payload.interval || interval, symbol: payload.symbol || symbol, type: "live" };
    rebuildFromInputs();
  } catch (error) {
    if (requestId === candleLoadSequence && symbol === selectedAsset) {
      candleSource = { interval: "sample", symbol, type: "sample" };
    }
    void error;
  } finally {
    if (requestId === candleLoadSequence) {
      candleLoading = false;
      candleLoadingSymbol = "";
    }
  }
}

async function refreshClosedStructure() {
  if (!selectedAsset || !currentUser.authenticated) return;
  await loadLiveCandles({ force: true, limit: 120, symbol: selectedAsset });
  loadFibonacciAnalysis({ force: true });
  loadContextRadar({ force: true });
}

function scaleCandlesToSelectedAsset(candles) {
  if (candleSource.type === "live" && candleSource.symbol === selectedAsset) {
    return candles;
  }
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
  const candles = scaleCandlesToSelectedAsset(parseCsv(candleCsvBuffer));
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

function drawEquity(points = state.equityCurve, emptyText = "Waiting for equity") {
  const { ctx, height, width } = setupCanvas(els.equityCanvas);
  const values = points.map((point) => point.equity);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfa";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d9ded8";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(12, height - 18);
  ctx.lineTo(width - 12, height - 18);
  ctx.stroke();

  if (!values.length) {
    ctx.fillStyle = "#66706c";
    ctx.font = "650 12px system-ui";
    ctx.fillText(emptyText, 16, 18);
    return;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const xFor = (index) => 16 + (index / Math.max(1, points.length - 1)) * (width - 32);
  const yFor = (value) => height - 18 - ((value - min) / span) * (height - 36);

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
  els.lastFill.textContent = fills[0] ? `${fills[0].side.toUpperCase()} signal ${money(fills[0].price)}` : "No signals";
}

function renderBackend(snapshot) {
  backendOnline = true;
  lastBackendSnapshot = snapshot;
  recordLiveEquity(snapshot);
  renderWealthCommand(snapshot);
  els.backendStatus.textContent = `${snapshot.mode} ${snapshot.running ? "running" : "stopped"}`;
  els.candleCount.textContent = snapshot.running ? "backend loop" : "backend idle";
  els.riskStatus.textContent = snapshot.riskStatus || "ready";
  els.runState.textContent = snapshot.running ? "Backend running" : "Backend ready";
  updateLiveDesk(snapshot);
  const tvMark = tradingViewSignalPrice();
  if (snapshot.markPrice) {
    els.markPrice.textContent = money(tvMark || snapshot.markPrice);
    syncSelectedAsset();
  }
  if (snapshot.portfolio) {
    const accountValue = liveAccountValue(snapshot);
    const hasAccountData = snapshot.mode === "live" && accountValue !== null;
    if (snapshot.mode === "live") {
      els.accountMetricLabel.textContent = "Perp Equity";
      els.cashMetricLabel.textContent = "Spot USDC";
      els.equityMetric.textContent = hasAccountData ? money(accountValue) : "Not connected";
      els.harvestMetric.textContent = hasAccountData ? money(snapshot.account?.accountValue || 0) : "Pending";
      els.feesMetric.textContent = hasAccountData ? money(snapshot.account?.spotUsdc || 0) : "Pending";
      drawEquity(liveEquityCurve, hasAccountData ? "Waiting for live account samples" : "Waiting for Hyperliquid account");
    } else {
      els.equityMetric.textContent = money(snapshot.portfolio.equity);
      els.accountMetricLabel.textContent = "Signal P/L";
      els.cashMetricLabel.textContent = "Fees";
      els.harvestMetric.textContent = money(snapshot.portfolio.realizedHarvest);
      els.feesMetric.textContent = money(snapshot.portfolio.feePaid);
      drawEquity();
    }
    els.inventoryMetric.textContent = hasAccountData && Number.isFinite(Number(snapshot.account.positionSize))
      ? `${Number(snapshot.account.positionSize || 0).toFixed(5)} ${snapshot.symbol}`
      : snapshot.mode === "live"
        ? "Pending"
        : `${(snapshot.portfolio.inventoryRatio * 100).toFixed(2)}%`;
  }
  if (snapshot.risk) {
    els.drawdownMetric.textContent = `${money(snapshot.risk.drawdown)} (${((snapshot.risk.drawdown_pct || 0) * 100).toFixed(2)}%)`;
    els.openNotionalMetric.textContent = money(snapshot.risk.open_order_notional || 0);
    els.riskBudgetMetric.textContent = `${money(snapshot.risk.estimated_margin_used || 0)} / ${money(snapshot.risk.max_grid_margin || 0)}`;
  }
  if (snapshot.desk) {
    els.executionModeMetric.textContent = snapshot.desk.executionMode || snapshot.executionMode || "dry_run";
    els.orderAgeMetric.textContent = `${Math.round(snapshot.desk.orderAgeSeconds || 0)}s / ${Math.round(snapshot.desk.orderRefreshSeconds || 0)}s`;
    els.syncMetric.textContent = `${snapshot.desk.reconciledFillCount || 0} signals / ${Math.round(snapshot.desk.lastReconciliationSeconds || 0)}s`;
    els.exchangeOrderMetric.textContent = String(snapshot.desk.exchangeOrderCount || 0);
  }
  const liveOrders = snapshot.openOrders || [];
  const liveMark = Number(tvMark || snapshot.markPrice || currentMarketPrice());
  const setupOrders = liveOrders.length ? liveOrders : setupGridOrders(liveMark, snapshot);
  const usingSetupGrid = !liveOrders.length && setupOrders.length > 0;
  const usingTradingViewGrid = usingSetupGrid && setupOrders.some((order) => order.metadata?.source === "tradingview");
  const hasExchangeState = Boolean(snapshot.running || snapshot.liveReady || snapshot.desk?.exchangeOrderCount || liveOrders.length || usingSetupGrid);
  renderOpenOrders(setupOrders, {
    emptyText: hasExchangeState ? "No setup-grid levels" : "Backend connected",
    emptyHint: hasExchangeState ? "Waiting for TradingView setup levels" : "No signal levels are being shown",
    mark: Number.isFinite(liveMark) ? liveMark : undefined,
    snapshot,
    source: liveOrders.length ? "live" : usingSetupGrid ? "setup" : "backend",
    title: liveOrders.length ? "Live Signal Levels" : usingTradingViewGrid ? "TradingView Setup Grid" : usingSetupGrid ? "Setup Grid" : "Backend State"
  });
  const sourceLabel = hasExchangeState
    ? usingTradingViewGrid
      ? "TradingView primary price, signal, setup grid, and hedge state"
      : `${String(snapshot.mode || "live").toUpperCase()} ${String(snapshot.network || "mainnet").toUpperCase()} signal state`
    : "Backend connected - no live signal levels";
  els.liquiditySource.textContent = sourceLabel;
  renderTradingViewChart();
  renderCoinGlassServices();
  loadCoinGlassContext();
  loadQuiverContext();
  if (Array.isArray(snapshot.fills)) {
    els.fillCount.textContent = `${snapshot.fills.length} signals`;
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
    els.lastFill.textContent = fills[0] ? `${fills[0].side.toUpperCase()} signal ${money(fills[0].price)}` : "No signals";
  }
  if (Array.isArray(snapshot.events)) {
    els.runtimeLog.innerHTML = snapshot.events
      .slice(-12)
      .reverse()
      .map((event) => `<article class="${event.level}">${event.message}</article>`)
      .join("");
    renderAuditLog(snapshot.events);
  }
  refreshSignalJournal();
}

function renderOpenOrders(orders, options = {}) {
  const source = options.source || "preview";
  const orderList = Array.isArray(orders) ? orders : [];
  els.openGridTitle.textContent = options.title || (source === "live" ? "Live Signal Levels" : "Signal Preview");
  els.openOrderCount.textContent = `${orderList.length} level${orderList.length === 1 ? "" : "s"}`;
  els.openOrderBook.innerHTML = orderList.length
    ? orderList
        .slice(0, 12)
        .map(
          (order) => `<article class="order-row ${order.side} ${source}">
            <strong>${String(order.side).toUpperCase() === "BUY" ? "Support" : "Resistance"} ${money(order.price)}</strong>
            <span>${orderRowDetail(order, source)}</span>
          </article>`
        )
        .join("")
    : `<article class="order-row empty"><strong>${options.emptyText || "No signal levels"}</strong><span>${options.emptyHint || "Waiting for generation"}</span></article>`;
  try {
    renderStrategyReadout(orderList, options);
  } catch (error) {
    if (els.strategyReadout) {
      els.strategyReadout.innerHTML = `<div class="strategy-status wait"><strong>WAIT</strong><span>Readout unavailable</span></div><p>${
        error.message || "strategy analyzer failed"
      }</p>`;
    }
  }
}

function orderRowDetail(order, source) {
  const sourceLabel =
    order.metadata?.source === "tradingview"
      ? "TradingView level"
      : source === "setup"
        ? "draft grid"
        : `${Number(order.quantity || 0).toFixed(5)} ${order.symbol || selectedAsset}`;
  const invalidation = Number(order.invalidation);
  if (!Number.isFinite(invalidation) || invalidation <= 0) return `${sourceLabel} · invalidation pending`;
  return `${sourceLabel} · invalidates ${money(invalidation)}`;
}

async function refreshBackend() {
  try {
    if (!currentUser.authenticated) {
      backendOnline = false;
      lastBackendSnapshot = null;
      els.backendStatus.textContent = "Login required";
      renderWealthCommand();
      updateLiveDesk();
      return;
    }
    const response = await apiFetch("/api/status", { cache: "no-store" });
    if (response.status === 401) {
      backendOnline = false;
      lastBackendSnapshot = null;
      els.backendStatus.textContent = "Login required";
      renderWealthCommand();
      renderAuth({ authenticated: false, credentialsConfigured: false });
      return;
    }
    if (!response.ok) throw new Error("backend offline");
    renderBackend(await response.json());
  } catch {
    backendOnline = false;
    lastBackendSnapshot = null;
    els.backendStatus.textContent = "Offline";
    renderWealthCommand();
    updateLiveDesk();
  }
}

async function backendCommand(path) {
  const sessionGuard = activeSessionGuard(selectedAsset);
  if (path === "/api/start" && sessionGuard.active && lastBackendSnapshot?.mode === "live") {
    els.riskStatus.textContent = sessionGuard.message;
    addAuditEvent("sync blocked", "Private sync blocked by session guard", sessionGuard.message);
    updateLiveDesk(lastBackendSnapshot);
    return;
  }
  addAuditEvent(path === "/api/start" ? "sync start requested" : "sync pause requested", path === "/api/start" ? "Operator requested private sync start" : "Operator requested private sync pause", selectedAsset);
  const response = await jsonPost(path);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    els.riskStatus.textContent = payload.error || `request failed: ${path}`;
    addAuditEvent("request failed", payload.error || `request failed: ${path}`, selectedAsset);
    throw new Error(payload.error || `request failed: ${path}`);
  }
  renderBackend(await response.json());
}

async function saveTradingRules() {
  const nextRules = normalizedTradingRules({
    chartInterval: els.chartIntervalSelect.value,
    signalSessionWindow: els.signalWindowSelect.value,
    londonCommodityOnly: els.londonCommodityInput.checked,
    maxDailyLossPct: Number(els.drawdownLimitInput.value) / 100,
    orderQuoteSize: Number(els.ruleOrderSizeInput.value),
    maxTotalNotional: Number(els.maxTotalNotionalInput.value),
    maxPositionValue: Number(els.maxPositionValueInput.value),
    sessionGuardMinutes: Number(els.sessionGuardSelect.value),
    staleGridCancel: els.staleGridCancelInput.checked
  });
  if (!currentUser.authenticated) {
    applyTradingRules(nextRules);
    rebuildFromInputs();
    fibAnalysis = null;
    fvgAnalysis = null;
    contextRadar = null;
    coinGlassContext = null;
    renderTradingViewChart();
    loadFibonacciAnalysis({ force: true });
    loadContextRadar({ force: true });
    loadCoinGlassContext({ force: true });
    addAuditEvent("rules updated", "Signal rules updated locally", `${nextRules.chartInterval} · ${nextRules.sessionGuardMinutes}m guard`);
    return;
  }
  const response = await jsonPost("/api/trading-rules", nextRules);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    els.rulesStatus.textContent = payload.error || "rules not saved";
    return;
  }
  applyTradingRules(payload.tradingRules);
  rebuildFromInputs();
  fibAnalysis = null;
  fvgAnalysis = null;
  contextRadar = null;
  coinGlassContext = null;
  renderTradingViewChart();
  loadFibonacciAnalysis({ force: true });
  loadContextRadar({ force: true });
  loadCoinGlassContext({ force: true });
  addAuditEvent(
    "rules updated",
    "Signal rules saved",
    `${payload.tradingRules.chartInterval} · ${payload.tradingRules.sessionGuardMinutes}m guard · ${(
      payload.tradingRules.maxDailyLossPct * 100
    ).toFixed(1)}% drawdown`
  );
  refreshBackend();
}

function render() {
  if (backendOnline && lastBackendSnapshot) {
    renderBackend(lastBackendSnapshot);
    return;
  }
  const candle = state.candles[Math.max(0, Math.min(state.activeIndex, state.candles.length - 1))];
  const mark = candle.close;
  const live = markets.find((asset) => asset.symbol === selectedAsset);
  els.candleCount.textContent = `${state.activeIndex}/${state.candles.length} candles`;
  els.equityMetric.textContent = money(equity(mark));
  els.feesMetric.textContent = money(state.feePaid);
  els.fillCount.textContent = `${Math.max(1, state.openOrders.length ? 1 : 0)} signal`;
  els.harvestMetric.textContent = money(state.realizedHarvest);
  els.inventoryMetric.textContent = `${(inventoryRatio(mark) * 100).toFixed(2)}%`;
  els.drawdownMetric.textContent = "$0.00 (0.00%)";
  els.openNotionalMetric.textContent = money(state.openOrders.reduce((sum, order) => sum + order.price * order.quantity, 0));
  els.riskBudgetMetric.textContent = "local";
  els.executionModeMetric.textContent = backendOnline ? els.executionModeMetric.textContent : "local";
  els.orderAgeMetric.textContent = "0s";
  els.syncMetric.textContent = "local";
  els.exchangeOrderMetric.textContent = "local";
  const previewMark = live ? Number(live.price) : mark;
  const liveSetupOrders = setupGridOrders(previewMark);
  const usingSetupGrid = liveSetupOrders.length > 0;
  const usingTradingViewGrid = usingSetupGrid && liveSetupOrders.some((order) => order.metadata?.source === "tradingview");
  const setupOrders = usingSetupGrid ? liveSetupOrders : state.openOrders;
  renderOpenOrders(setupOrders, {
    emptyHint: "Run a sample or connect the backend",
    emptyText: "No preview levels",
    mark: previewMark,
    source: usingSetupGrid ? "setup" : "preview",
    title: usingTradingViewGrid ? "TradingView Setup Grid" : usingSetupGrid ? "Setup Grid" : "Signal Preview"
  });
  const visibleMark = currentMarketPrice() || (live ? Number(live.price) : mark);
  els.markPrice.textContent = money(visibleMark);
  els.marketTitle.textContent = `${selectedAsset}-USD signal map`;
  els.liquiditySource.textContent = usingTradingViewGrid
    ? "TradingView is driving the visible price, signal, grid, and hedge. No exchange orders."
    : "TradingView drives watch-asset signals; CoinGlass and Hyperliquid remain secondary context. No exchange orders.";
  els.runState.textContent = state.activeIndex >= state.candles.length ? "Complete" : "Ready";
  renderTradingViewChart();
  renderCoinGlassServices();
  loadCoinGlassContext();
  renderTape();
  renderAuditLog();
  refreshSignalJournal();
  drawEquity();
  if (!backendOnline) {
    els.runtimeLog.innerHTML = "<article>Serve with the backend to refresh live signal feeds.</article>";
    els.riskStatus.textContent = "local";
    updateLiveDesk();
  }
}

function reset() {
  candleCsvBuffer = sampleCsv;
  candleSource = { interval: "sample", symbol: selectedAsset, type: "sample" };
  els.spacingValue.textContent = els.spacingInput.value;
  els.levelsValue.textContent = els.levelsInput.value;
  state = createState(configFromInputs());
  planOrders(state.candles[0].open);
  render();
  if (!pendingArmReview) addAuditEvent("preview reset", "Signal preview reset", selectedAsset);
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
  addAuditEvent("signal generated", "Local signal generated", `${state.openOrders.length} levels`);
});

els.stepButton.addEventListener("click", () => {
  if (state.activeIndex >= state.candles.length) {
    state = createState(configFromInputs());
  }
  stepSimulation();
  render();
  addAuditEvent("preview step", "Advanced one signal candle", `${state.activeIndex}/${state.candles.length}`);
});

els.resetButton.addEventListener("click", reset);
els.themeModeSelect?.addEventListener("change", () => {
  applyThemePreference(els.themeModeSelect.value);
});
els.languageSelect?.addEventListener("change", () => {
  applyLanguagePreference(els.languageSelect.value);
});
els.assetSelect.addEventListener("change", () => saveSelectedAsset(els.assetSelect.value));
if (els.openTradingViewButton) {
  els.openTradingViewButton.addEventListener("click", openSelectedTradingViewChart);
}
els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = els.chatInput.value.trim();
  if (!question) return;
  pushChatMessage("user", question);
  pushChatMessage("assistant", answerSignalChat(question));
  els.chatInput.value = "";
});
document.querySelectorAll("[data-chat-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = button.dataset.chatPrompt || "";
    pushChatMessage("user", prompt);
    pushChatMessage("assistant", answerSignalChat(prompt));
  });
});
els.armStrategyButton.addEventListener("click", () => {
  pendingArmReview = true;
  const blocks = signalSafetyBlocks(lastBackendSnapshot);
  const warnings = lastTicketHealth?.warnings || [];
  const signalReady = lastTicketSnapshot?.canReview && signalHasExecutablePlan(lastSignalCandidate);
  if (blocks.length || lastTicketHealth?.blocked || !signalReady) {
    addAuditEvent("signal blocked", "Signal review found blockers", blocks[0]?.detail || warnings[0] || "readiness not clear");
    document.querySelector("#risk")?.scrollIntoView({ behavior: "smooth", block: "start" });
    pendingArmReview = false;
    return;
  }
  if (!currentUser.authenticated) {
    addAuditEvent("login needed", "Signal is structurally valid", "Login to save and track this setup.");
    document.querySelector("#account")?.scrollIntoView({ behavior: "smooth", block: "start" });
    pendingArmReview = false;
    return;
  }
  const saved = saveReviewedSignal();
  addAuditEvent(
    "signal review",
    saved ? "Signal saved to outcome journal" : "Signal quality ready for review",
    saved ? `${saved.symbol} · ${saved.direction} · expires ${saved.expiresAt ? formatSignalTime(new Date(saved.expiresAt)) : "pending"}` : `${selectedAsset} · ${tradingRules.chartInterval}`
  );
  document.querySelector("#activity")?.scrollIntoView({ behavior: "smooth", block: "start" });
  pendingArmReview = false;
});
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
els.installAppButton.addEventListener("click", async () => {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice.catch(() => {});
  deferredInstallPrompt = null;
  els.installAppButton.hidden = true;
});
els.authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  setPasswordAutocomplete(false);
  loginOrRegister("/api/login");
});
els.loginButton.addEventListener("click", () => setPasswordAutocomplete(false));
els.registerButton.addEventListener("click", () => {
  setPasswordAutocomplete(true);
  loginOrRegister("/api/register");
});
els.forgotPasswordButton.addEventListener("click", () => showRecoveryPanel(true));
els.emailLoginCodeButton.addEventListener("click", requestLoginCode);
els.completeLoginCodeButton.addEventListener("click", completeLoginCode);
els.cancelLoginCodeButton.addEventListener("click", () => showLoginCodePanel(false));
els.cancelRecoveryButton.addEventListener("click", () => showRecoveryPanel(false));
els.resetPasswordButton.addEventListener("click", resetForgottenPassword);
els.rotateRecoveryCodeButton.addEventListener("click", rotateRecoveryCode);
els.finishOnboardingButton.addEventListener("click", finishOnboarding);
els.clientNameInput.addEventListener("input", () => renderRegistrationDesk());
els.rememberLoginInput.addEventListener("change", () => {
  if (!els.rememberLoginInput.checked) localStorage.removeItem(rememberedLoginKey());
  else if (els.usernameInput.value.trim()) updateRememberedLogin(els.usernameInput.value.trim());
});
els.passwordToggle.addEventListener("click", () => {
  const isHidden = els.passwordInput.type === "password";
  els.passwordInput.type = isHidden ? "text" : "password";
  els.passwordToggle.textContent = isHidden ? "Hide" : "Show";
  els.passwordToggle.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
  els.passwordToggle.setAttribute("aria-pressed", String(isHidden));
  els.passwordInput.focus();
});
[els.usernameInput, els.passwordInput].forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      els.authForm.requestSubmit();
    }
  });
});
[els.recoveryCodeInput, els.newPasswordInput].forEach((input) => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      resetForgottenPassword();
    }
  });
});
els.loginCodeInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    completeLoginCode();
  }
});
els.logoutButton.addEventListener("click", async () => {
  await jsonPost("/api/logout");
  addAuditEvent("logout", "User logged out", "live actions disabled");
  renderAuth({ authenticated: false, credentialsConfigured: false });
});
els.saveCredentialsButton.addEventListener("click", saveCredentials);
els.saveSpotifyButton?.addEventListener("click", saveSpotifyPlaylist);
els.billingCheckoutButton?.addEventListener("click", startBillingCheckout);
els.saveRulesButton.addEventListener("click", saveTradingRules);
function previewTradingRules() {
  const nextRules = normalizedTradingRules({
    chartInterval: els.chartIntervalSelect.value,
    signalSessionWindow: els.signalWindowSelect.value,
    londonCommodityOnly: els.londonCommodityInput.checked,
    maxDailyLossPct: Number(els.drawdownLimitInput.value) / 100,
    orderQuoteSize: Number(els.ruleOrderSizeInput.value),
    maxTotalNotional: Number(els.maxTotalNotionalInput.value),
    maxPositionValue: Number(els.maxPositionValueInput.value),
    sessionGuardMinutes: Number(els.sessionGuardSelect.value),
    staleGridCancel: els.staleGridCancelInput.checked
  });
  applyTradingRules(nextRules);
  rebuildFromInputs();
}
[els.chartIntervalSelect, els.signalWindowSelect, els.sessionGuardSelect, els.staleGridCancelInput, els.londonCommodityInput].forEach((input) => {
  input.addEventListener("change", previewTradingRules);
});
[els.drawdownLimitInput, els.ruleOrderSizeInput, els.maxTotalNotionalInput, els.maxPositionValueInput].forEach((input) => {
  input.addEventListener("input", previewTradingRules);
  input.addEventListener("change", previewTradingRules);
});
els.backendStartButton.addEventListener("click", () => backendCommand("/api/start").catch(refreshBackend));
els.backendStopButton.addEventListener("click", () => backendCommand("/api/stop").catch(refreshBackend));
["input", "change"].forEach((eventName) => {
  [els.spacingInput, els.levelsInput].forEach((input) => {
    input.addEventListener(eventName, rebuildFromInputs);
  });
});

[els.symbolInput, els.quoteInput, els.baseInput, els.orderSizeInput, els.feeInput]
  .filter(Boolean)
  .forEach((input) => {
    input.addEventListener("change", rebuildFromInputs);
  });

window.addEventListener("resize", render);
window.addEventListener("resize", resizeMarketMap);
applyThemePreference(selectedTheme);
applyLanguagePreference(selectedLanguage);
setupAppInstall();
reset();
initMarketMap();
loadSelectableAssets();
loadMarkets();
loadMe();
loadOperatorStatus();
refreshBackend();
renderChatMessages();
loadTradingViewSignals();
loadCoinGlassContext();
loadQuiverContext();
applyRememberedLogin();
setInterval(loadMarkets, 5000);
setInterval(loadOperatorStatus, 30000);
setInterval(refreshBackend, 2500);
setInterval(loadTradingViewSignals, 10000);
setInterval(loadCoinGlassContext, 60000);
setInterval(loadQuiverContext, 120000);
setInterval(() => refreshClosedStructure().catch(() => {}), 60000);
