const root = document.querySelector("#goldTrainerApp") || document;
const canvas = root.querySelector("#trainerCanvas");
if (!canvas) {
  throw new Error("Gold trainer canvas not found");
}
const context = canvas.getContext("2d");
const scoreValue = root.querySelector("#scoreValue");
const streakValue = root.querySelector("#streakValue");
const disciplineValue = root.querySelector("#disciplineValue");
const roundValue = root.querySelector("#roundValue");
const sessionValue = root.querySelector("#sessionValue");
const scenarioTitle = root.querySelector("#scenarioTitle");
const scenarioMeta = root.querySelector("#scenarioMeta");
const feedbackBox = root.querySelector("#feedbackBox");
const nextRoundButton = root.querySelector("#nextRoundButton");
const decisionButtons = root.querySelectorAll("[data-decision]");

const scenarios = [
  {
    title: "Liquidity sweep into reclaim",
    session: "London/New York",
    bias: "long",
    answer: "long",
    news: "clear",
    confidence: 86,
    entry: 2374.2,
    invalidation: 2367.6,
    target: 2385.4,
    rhythm: "reclaim"
  },
  {
    title: "High-impact news window",
    session: "New York",
    bias: "none",
    answer: "skip",
    news: "FOMC in 12m",
    confidence: 42,
    entry: 2371.8,
    invalidation: 2364.1,
    target: 2380.6,
    rhythm: "volatile"
  },
  {
    title: "Failed high after compression",
    session: "London",
    bias: "short",
    answer: "short",
    news: "clear",
    confidence: 81,
    entry: 2368.5,
    invalidation: 2375.2,
    target: 2357.9,
    rhythm: "fade"
  },
  {
    title: "Chop around broker pivot",
    session: "Asia",
    bias: "none",
    answer: "skip",
    news: "clear",
    confidence: 54,
    entry: 2365.4,
    invalidation: 2359.8,
    target: 2372.1,
    rhythm: "chop"
  },
  {
    title: "Trend continuation above value",
    session: "London/New York",
    bias: "long",
    answer: "long",
    news: "clear",
    confidence: 88,
    entry: 2381.3,
    invalidation: 2373.4,
    target: 2394.8,
    rhythm: "trend"
  },
  {
    title: "Rejection below prior session high",
    session: "New York",
    bias: "short",
    answer: "short",
    news: "clear",
    confidence: 79,
    entry: 2378.6,
    invalidation: 2386.2,
    target: 2366.5,
    rhythm: "fade"
  },
  {
    title: "Fresh CPI impulse",
    session: "New York",
    bias: "none",
    answer: "skip",
    news: "CPI just released",
    confidence: 38,
    entry: 2390.1,
    invalidation: 2378.7,
    target: 2406.4,
    rhythm: "volatile"
  },
  {
    title: "Sweep below value, fast reclaim",
    session: "London",
    bias: "long",
    answer: "long",
    news: "clear",
    confidence: 84,
    entry: 2362.2,
    invalidation: 2355.9,
    target: 2374.6,
    rhythm: "reclaim"
  },
  {
    title: "Weak push into sell-side pressure",
    session: "London/New York",
    bias: "short",
    answer: "short",
    news: "clear",
    confidence: 76,
    entry: 2370.7,
    invalidation: 2378.8,
    target: 2359.1,
    rhythm: "fade"
  },
  {
    title: "Late-session exhaustion",
    session: "New York",
    bias: "none",
    answer: "skip",
    news: "session closing",
    confidence: 51,
    entry: 2384.3,
    invalidation: 2376.5,
    target: 2392.9,
    rhythm: "chop"
  }
];

const state = {
  round: 0,
  score: 0,
  streak: 0,
  misses: 0,
  decisions: 0,
  locked: false
};

function priceToY(price, min, max, height) {
  return height - 56 - ((price - min) / (max - min)) * (height - 112);
}

function buildCandles(scenario) {
  const seed = scenario.title.length + Math.round(scenario.entry);
  const candles = [];
  let close = scenario.entry - 8;

  for (let index = 0; index < 30; index += 1) {
    const wave = Math.sin((index + seed) / 2.4) * 2.4;
    const drift = scenario.bias === "long" ? index * 0.28 : scenario.bias === "short" ? -index * 0.22 : Math.sin(index) * 0.45;
    const shock = scenario.rhythm === "volatile" && index > 20 ? Math.sin(index * 2.2) * 6 : 0;
    const open = close;
    close = scenario.entry - 5 + wave + drift + shock;

    if (scenario.rhythm === "reclaim" && index === 20) close = scenario.invalidation + 1.2;
    if (scenario.rhythm === "fade" && index > 20) close -= (index - 20) * 0.55;
    if (scenario.rhythm === "trend" && index > 16) close += (index - 16) * 0.45;

    const high = Math.max(open, close) + 1.8 + Math.abs(Math.sin(index)) * 1.2;
    const low = Math.min(open, close) - 1.8 - Math.abs(Math.cos(index)) * 1.2;
    candles.push({ open, high, low, close });
  }

  return candles;
}

function drawChart(scenario) {
  const width = canvas.width;
  const height = canvas.height;
  const candles = buildCandles(scenario);
  const prices = candles.flatMap((candle) => [candle.high, candle.low, scenario.entry, scenario.invalidation, scenario.target]);
  const min = Math.min(...prices) - 4;
  const max = Math.max(...prices) + 4;

  context.clearRect(0, 0, width, height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);

  context.strokeStyle = "#d7dde4";
  context.lineWidth = 1;
  for (let i = 1; i < 6; i += 1) {
    const y = (height / 6) * i;
    context.beginPath();
    context.moveTo(32, y);
    context.lineTo(width - 28, y);
    context.stroke();
  }

  drawZone(scenario.target, "Target", "#0f766e", min, max, height, width);
  drawZone(scenario.entry, "Entry", "#2563eb", min, max, height, width);
  drawZone(scenario.invalidation, "Invalidation", "#be123c", min, max, height, width);

  const candleWidth = Math.max(10, (width - 96) / candles.length - 6);
  candles.forEach((candle, index) => {
    const x = 52 + index * ((width - 104) / candles.length);
    const yOpen = priceToY(candle.open, min, max, height);
    const yClose = priceToY(candle.close, min, max, height);
    const yHigh = priceToY(candle.high, min, max, height);
    const yLow = priceToY(candle.low, min, max, height);
    const up = candle.close >= candle.open;

    context.strokeStyle = up ? "#0f766e" : "#be123c";
    context.fillStyle = up ? "#d9f3ed" : "#ffe4e6";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(x + candleWidth / 2, yHigh);
    context.lineTo(x + candleWidth / 2, yLow);
    context.stroke();
    context.fillRect(x, Math.min(yOpen, yClose), candleWidth, Math.max(4, Math.abs(yClose - yOpen)));
    context.strokeRect(x, Math.min(yOpen, yClose), candleWidth, Math.max(4, Math.abs(yClose - yOpen)));
  });

  context.fillStyle = "#151515";
  context.font = "800 22px system-ui";
  context.fillText("XAUUSD", 36, 38);
  context.fillStyle = "#5c6570";
  context.font = "700 14px system-ui";
  context.fillText(`${scenario.session} · ${scenario.news}`, 36, 62);
}

function drawZone(price, label, color, min, max, height, width) {
  const y = priceToY(price, min, max, height);
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = 2;
  context.setLineDash([8, 8]);
  context.beginPath();
  context.moveTo(36, y);
  context.lineTo(width - 36, y);
  context.stroke();
  context.setLineDash([]);
  context.font = "800 13px system-ui";
  context.fillText(`${label} ${price.toFixed(2)}`, width - 190, y - 8);
}

function renderRound() {
  const scenario = scenarios[state.round];
  state.locked = false;
  scenarioTitle.textContent = scenario.title;
  sessionValue.textContent = scenario.session;
  scenarioMeta.textContent = `Confidence ${scenario.confidence}% · News: ${scenario.news}`;
  roundValue.textContent = `${state.round + 1}/${scenarios.length}`;
  feedbackBox.innerHTML = "<strong>Awaiting decision</strong><p>Read the structure and choose the cleanest action.</p>";
  decisionButtons.forEach((button) => button.disabled = false);
  drawChart(scenario);
  renderStats();
}

function renderStats() {
  const discipline = state.decisions ? Math.max(0, Math.round(((state.decisions - state.misses) / state.decisions) * 100)) : 100;
  scoreValue.textContent = String(state.score);
  streakValue.textContent = String(state.streak);
  disciplineValue.textContent = `${discipline}%`;
}

function choose(decision) {
  if (state.locked) return;
  const scenario = scenarios[state.round];
  const correct = decision === scenario.answer;
  state.locked = true;
  state.decisions += 1;

  if (correct) {
    const points = decision === "skip" ? 80 : 100 + Math.round(scenario.confidence / 5);
    state.score += points + state.streak * 10;
    state.streak += 1;
    feedbackBox.innerHTML = `<strong>Good read</strong><p>${feedbackText(scenario, decision)}</p>`;
  } else {
    state.streak = 0;
    state.misses += 1;
    feedbackBox.innerHTML = `<strong>Discipline break</strong><p>${feedbackText(scenario, decision)}</p>`;
  }

  decisionButtons.forEach((button) => button.disabled = true);
  renderStats();
}

function feedbackText(scenario, decision) {
  if (scenario.answer === "skip") return `Skip was correct. ${scenario.news} made execution quality poor.`;
  if (decision === scenario.answer) return `${scenario.answer.toUpperCase()} matched the structure. Target and invalidation were clean.`;
  return `Best action was ${scenario.answer.toUpperCase()}. Respect the invalidation and news filter.`;
}

function nextRound() {
  state.round = (state.round + 1) % scenarios.length;
  renderRound();
}

decisionButtons.forEach((button) => {
  button.addEventListener("click", () => choose(button.dataset.decision));
});
nextRoundButton.addEventListener("click", nextRound);

renderRound();
window.MonatiseSpotify?.loadSpotifyForSession(root.querySelector("#trainerSpotifyPanel"));
