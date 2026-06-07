const presets = {
  aggressive: { activePct: 1, label: "Aggressive", maxDailyLossPct: 0.02, monthlyPct: 0.12 },
  full: { activePct: 1, label: "Full capital", maxDailyLossPct: 0.01, monthlyPct: 0.05 },
  operator: { activePct: 1, label: "Operator", maxDailyLossPct: 0.015, monthlyPct: 0.08 },
  starter: { activePct: 1, label: "Starter", maxDailyLossPct: 0.005, monthlyPct: 0.02 }
};

const els = {
  activeCapital: document.querySelector("#plannerActiveCapital"),
  capital: document.querySelector("#plannerCapital"),
  dailyTarget: document.querySelector("#plannerDailyTarget"),
  derisk: document.querySelector("#plannerDerisk"),
  idleReserve: document.querySelector("#plannerIdleReserve"),
  income: document.querySelector("#plannerIncome"),
  inflow: document.querySelector("#plannerInflow"),
  maxLoss: document.querySelector("#plannerMaxLoss"),
  monthlyTarget: document.querySelector("#plannerMonthlyTarget"),
  preset: document.querySelector("#plannerPreset"),
  requiredCapital: document.querySelector("#plannerRequiredCapital")
};

function money(value) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: "currency"
  }).format(Number.isFinite(value) ? value : 0);
}

function numberFrom(input) {
  return Math.max(0, Number(input.value || 0));
}

function updatePlanner() {
  const capital = numberFrom(els.capital);
  const desiredIncome = numberFrom(els.income);
  const inflow = numberFrom(els.inflow);
  const preset = presets[els.preset.value] || presets.full;
  const activeCapital = capital * preset.activePct;
  const idleReserve = Math.max(0, capital - activeCapital);
  const monthlyTarget = activeCapital * preset.monthlyPct;
  const dailyTarget = monthlyTarget / 30;
  const requiredCapital = desiredIncome > 0 ? desiredIncome / Math.max(0.0001, preset.monthlyPct * preset.activePct) : 0;
  const maxDailyLoss = activeCapital * preset.maxDailyLossPct;

  els.monthlyTarget.textContent = money(monthlyTarget);
  els.dailyTarget.textContent = money(dailyTarget);
  els.requiredCapital.textContent = money(requiredCapital);
  els.activeCapital.textContent = money(activeCapital);
  els.idleReserve.textContent = money(idleReserve);
  els.maxLoss.textContent = money(maxDailyLoss);

  const inflowPct = capital > 0 ? inflow / capital : 0;
  if (inflowPct >= 1) {
    els.derisk.textContent = `Major inflow detected: deploy only 25% to 40% of the new capital for 7 to 14 days, keep order size unchanged, and review fills before scaling.`;
    return;
  }
  if (inflowPct >= 0.25) {
    els.derisk.textContent = `Inflow is ${Math.round(inflowPct * 100)}% of current capital. Freeze order size for 7 days and add the new capital gradually after sync and drawdown stay clean.`;
    return;
  }
  els.derisk.textContent = `${preset.label} plan: target ${Math.round(preset.monthlyPct * 100)}% monthly with full capital available, and stop for the day near ${money(maxDailyLoss)} loss.`;
}

["input", "change"].forEach((eventName) => {
  [els.capital, els.income, els.inflow, els.preset].forEach((input) => {
    input.addEventListener(eventName, updatePlanner);
  });
});

updatePlanner();
