const root = document.querySelector("#cryptoTrainerApp") || document;
const canvas = root.querySelector("#trainerCanvas");
const ctx = canvas.getContext("2d");

const els = {
  score: root.querySelector("#scoreValue"),
  streak: root.querySelector("#streakValue"),
  discipline: root.querySelector("#disciplineValue"),
  round: root.querySelector("#roundValue"),
  session: root.querySelector("#sessionValue"),
  title: root.querySelector("#scenarioTitle"),
  meta: root.querySelector("#scenarioMeta"),
  funding: root.querySelector("#fundingValue"),
  oi: root.querySelector("#oiValue"),
  liq: root.querySelector("#liqValue"),
  vwap: root.querySelector("#vwapValue"),
  feedback: root.querySelector("#feedbackBox"),
  next: root.querySelector("#nextRoundButton"),
  buttons: Array.from(root.querySelectorAll("[data-decision]"))
};

const scenarios = [
  {
    asset: "BTC",
    title: "Short squeeze reclaim",
    answer: "long",
    session: "London/New York overlap",
    funding: "negative",
    oi: "rising",
    liq: "shorts trapped above VWAP",
    vwap: "reclaimed",
    note: "Negative funding plus rising OI can fuel a squeeze when price reclaims VWAP and liquidations sit above.",
    candles: [96, 94, 92, 91, 93, 95, 97, 101, 104, 106, 109, 112, 111, 115],
    zones: [{ y: 108, label: "short liq" }, { y: 94, label: "demand" }]
  },
  {
    asset: "ETH",
    title: "Long flush below VWAP",
    answer: "short",
    session: "US risk-off hour",
    funding: "positive",
    oi: "rising",
    liq: "longs stacked below",
    vwap: "lost",
    note: "Positive funding with rising OI becomes fragile when ETH loses VWAP and long liquidation liquidity sits below.",
    candles: [116, 118, 119, 117, 115, 112, 110, 108, 106, 103, 101, 98, 97, 95],
    zones: [{ y: 101, label: "long liq" }, { y: 114, label: "supply" }]
  },
  {
    asset: "SOL",
    title: "Chop with mixed participation",
    answer: "wait",
    session: "Asia handoff",
    funding: "flat",
    oi: "falling",
    liq: "balanced both sides",
    vwap: "inside",
    note: "Flat funding, falling OI, and balanced liquidation pockets are not enough for a high-quality directional decision.",
    candles: [101, 103, 100, 102, 99, 101, 100, 102, 101, 99, 100, 101, 100, 102],
    zones: [{ y: 104, label: "upper liq" }, { y: 98, label: "lower liq" }]
  },
  {
    asset: "HYPE",
    title: "Breakout without confirmation",
    answer: "wait",
    session: "Pre-overlap",
    funding: "slightly positive",
    oi: "flat",
    liq: "thin above",
    vwap: "extended above",
    note: "A stretched move above VWAP with flat OI and thin liquidity is a chase risk. Wait for pullback or fresh participation.",
    candles: [88, 89, 91, 93, 95, 97, 100, 103, 105, 106, 107, 107, 108, 108],
    zones: [{ y: 109, label: "thin liq" }, { y: 101, label: "pullback" }]
  },
  {
    asset: "BNB",
    title: "Failed reclaim at supply",
    answer: "short",
    session: "New York continuation",
    funding: "positive",
    oi: "rising",
    liq: "buyers trapped",
    vwap: "rejected",
    note: "A failed VWAP reclaim into supply with positive funding points to trapped longs rather than clean continuation.",
    candles: [104, 105, 107, 108, 106, 105, 103, 101, 102, 100, 98, 96, 95, 93],
    zones: [{ y: 108, label: "supply" }, { y: 97, label: "long liq" }]
  },
  {
    asset: "XRP",
    title: "Compression into demand",
    answer: "long",
    session: "London open",
    funding: "neutral",
    oi: "rising",
    liq: "shorts building above",
    vwap: "holding",
    note: "Rising OI while VWAP holds demand can support a long if shorts are building above the range.",
    candles: [99, 98, 99, 100, 99, 101, 100, 102, 103, 105, 104, 106, 108, 109],
    zones: [{ y: 107, label: "short liq" }, { y: 99, label: "demand" }]
  }
];

let roundIndex = 0;
let score = 0;
let streak = 0;
let discipline = 100;
let answered = false;
let scenario = scenarios[0];

function scaleSeries(values) {
  const min = Math.min(...values) - 3;
  const max = Math.max(...values) + 3;
  return { min, max, span: Math.max(1, max - min) };
}

function yFor(value, scale, top, height) {
  return top + (1 - (value - scale.min) / scale.span) * height;
}

function drawChart() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const pad = { left: 42, right: 28, top: 34, bottom: 44 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const scale = scaleSeries(scenario.candles);

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfa";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(17, 24, 23, 0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 6; i += 1) {
    const y = pad.top + (chartH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  const vwap = scenario.candles.reduce((sum, value) => sum + value, 0) / scenario.candles.length;
  const vwapY = yFor(vwap, scale, pad.top, chartH);
  ctx.strokeStyle = "#246bfe";
  ctx.setLineDash([8, 7]);
  ctx.beginPath();
  ctx.moveTo(pad.left, vwapY);
  ctx.lineTo(width - pad.right, vwapY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#246bfe";
  ctx.font = "700 12px Inter, system-ui";
  ctx.fillText("VWAP", pad.left + 6, vwapY - 8);

  scenario.zones.forEach((zone, index) => {
    const y = yFor(zone.y, scale, pad.top, chartH);
    ctx.fillStyle = index % 2 ? "rgba(0, 168, 120, 0.12)" : "rgba(216, 58, 70, 0.12)";
    ctx.fillRect(pad.left, y - 14, chartW, 28);
    ctx.fillStyle = index % 2 ? "#007d62" : "#b52d3a";
    ctx.fillText(zone.label, width - pad.right - 92, y + 4);
  });

  const step = chartW / (scenario.candles.length - 1);
  scenario.candles.forEach((close, index) => {
    const previous = scenario.candles[Math.max(0, index - 1)];
    const open = index ? previous : close - 1;
    const high = Math.max(open, close) + 1.4 + (index % 3) * 0.4;
    const low = Math.min(open, close) - 1.2 - (index % 2) * 0.35;
    const x = pad.left + index * step;
    const openY = yFor(open, scale, pad.top, chartH);
    const closeY = yFor(close, scale, pad.top, chartH);
    const highY = yFor(high, scale, pad.top, chartH);
    const lowY = yFor(low, scale, pad.top, chartH);
    const up = close >= open;
    ctx.strokeStyle = up ? "#00a878" : "#e7425f";
    ctx.fillStyle = up ? "#00a878" : "#e7425f";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();
    ctx.fillRect(x - 7, Math.min(openY, closeY), 14, Math.max(3, Math.abs(closeY - openY)));
  });

  ctx.fillStyle = "#111817";
  ctx.font = "900 18px Inter, system-ui";
  ctx.fillText(`${scenario.asset} ${scenario.title}`, pad.left, 24);
  ctx.fillStyle = "#63716c";
  ctx.font = "750 12px Inter, system-ui";
  ctx.fillText("Hyperliquid core + optional CoinGlass context drill", pad.left, height - 16);
}

function renderScenario() {
  scenario = scenarios[roundIndex % scenarios.length];
  answered = false;
  els.buttons.forEach((button) => {
    button.disabled = false;
    button.classList.remove("correct", "wrong");
  });
  els.session.textContent = scenario.session;
  els.title.textContent = scenario.title;
  els.meta.textContent = `${scenario.asset} · Hyperliquid + optional CoinGlass context`;
  els.funding.textContent = scenario.funding;
  els.oi.textContent = scenario.oi;
  els.liq.textContent = scenario.liq;
  els.vwap.textContent = scenario.vwap;
  els.round.textContent = `${(roundIndex % 12) + 1}/12`;
  els.score.textContent = String(score);
  els.streak.textContent = String(streak);
  els.discipline.textContent = `${discipline}%`;
  els.feedback.innerHTML = "<strong>Awaiting decision</strong><p>Read the crypto context, then choose Long, Short, or Wait.</p>";
  drawChart();
}

function decide(choice) {
  if (answered) return;
  answered = true;
  const correct = choice === scenario.answer;
  if (correct) {
    streak += 1;
    score += 10 + Math.min(10, streak * 2);
  } else {
    streak = 0;
    discipline = Math.max(0, discipline - (choice === "wait" ? 6 : 12));
  }
  els.buttons.forEach((button) => {
    button.disabled = true;
    const buttonChoice = button.dataset.decision;
    if (buttonChoice === scenario.answer) button.classList.add("correct");
    if (buttonChoice === choice && !correct) button.classList.add("wrong");
  });
  els.score.textContent = String(score);
  els.streak.textContent = String(streak);
  els.discipline.textContent = `${discipline}%`;
  els.feedback.innerHTML = `
    <strong>${correct ? "Correct read" : "Review the context"}</strong>
    <p>${scenario.note}</p>
  `;
}

els.buttons.forEach((button) => {
  button.addEventListener("click", () => decide(button.dataset.decision));
});

els.next.addEventListener("click", () => {
  roundIndex = (roundIndex + 1) % 12;
  if (roundIndex === 0) {
    discipline = Math.min(100, discipline + 4);
  }
  renderScenario();
});

window.addEventListener("resize", drawChart);
renderScenario();
