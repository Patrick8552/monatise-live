import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../app/app.js", import.meta.url), "utf8");

assert.ok(!source.includes("selectedAsset = snapshot.symbol"), "backend status must not overwrite the selected chart asset");
assert.ok(!source.includes("selectedAsset = selectableAssets"), "market refresh must not directly overwrite selected asset");
assert.ok(!source.includes("selectedAsset = markets"), "market refresh must not directly overwrite selected asset");
assert.ok(source.includes("function structuredSignalFromHealth"), "signals must be gated by candle/structure signature");
assert.ok(!source.includes("createdAt: new Date().toISOString(),"), "signal createdAt must not reset on render refresh");
assert.ok(
  source.includes("lastStructuredSignalCreatedAt = new Date().toISOString();"),
  "new signal timestamps should only be created with a fresh structure signature"
);
assert.ok(source.includes("function signalSafetyBlocks"), "signal safety blocks must be separate from tracking/login blocks");
assert.ok(source.includes("\"User session\", \"Private sync\", \"Signal access\""), "login/access gates must not suppress structurally valid signals");
assert.ok(source.includes("const canTrack = canReview && Boolean(currentUser.authenticated);"), "tracking permission must stay separate from signal review readiness");
assert.ok(source.includes("blockReasons"), "hard signal blocks must be listed separately from cautions");
assert.ok(source.includes("function signalTrustSummary"), "signals must expose a trust summary with drivers, cautions, blocks, and timing");
assert.ok(source.includes("signal.reasons"), "signal explanations must carry named evidence drivers");
assert.ok(source.includes("function stopLossModel"), "signals must preserve the stop-loss calculation model");
assert.ok(source.includes("function trendGridSummary"), "signals must explain the trend-based grid shape");

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing function ${name}`);
  const signatureEnd = source.indexOf(") {", start);
  assert.notEqual(signatureEnd, -1, `missing function body for ${name}`);
  const bodyStart = source.indexOf("{", signatureEnd);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index];
    if (char === "{") depth += 1;
    if (char === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated function ${name}`);
}

const context = vm.createContext({
  Date,
  Intl,
  Math,
  Number,
  String,
  forexPairs: ["EURUSD", "GBPUSD", "USDJPY", "XAG"],
  selectedAsset: "BTC",
  state: { candles: [] },
  tradingRules: {
    leverage: 10,
    maxPositionValue: 5000,
    maxTotalNotional: 5000,
    orderQuoteSize: 25
  }
});

[
  "terminalSignalStatus",
  "candleTime",
  "setupRiskPct",
  "setupMinRiskPct",
  "boundedRiskDistance",
  "stopLossModel",
  "stopLossSummary",
  "trendGridSummary",
  "plannedEntry",
  "targetWithMinimumReward",
  "buildEntryLadder",
  "signalHasExecutablePlan",
  "money",
  "formatLotSize",
  "forexLotLabel",
  "tradeSizingFromSignal",
  "gradeSignalEntry"
].forEach((name) => vm.runInContext(extractFunction(name), context));

function checkSignal(signal) {
  assert.ok(Number.isFinite(signal.entry), "entry must be finite");
  assert.ok(Number.isFinite(signal.stop), "stop must be finite");
  assert.ok(Number.isFinite(signal.targetOne), "target must be finite");
  if (signal.direction === "LONG") {
    assert.ok(signal.stop < signal.entry, "long stop must be below entry");
    assert.ok(signal.targetOne > signal.entry, "long target must be above entry");
  } else {
    assert.ok(signal.stop > signal.entry, "short stop must be above entry");
    assert.ok(signal.targetOne < signal.entry, "short target must be below entry");
  }
}

const longRisk = context.boundedRiskDistance(100, 96, 1, "BTC");
assert.ok(longRisk <= 0.350001, "crypto risk must cap near 0.35% of entry");
const longTarget = context.targetWithMinimumReward("LONG", 100, 101, longRisk);
const longSignal = { direction: "LONG", entry: 100, stop: 100 - longRisk, targetOne: longTarget, targetTwo: longTarget + longRisk };
checkSignal(longSignal);

const shortRisk = context.boundedRiskDistance(100, 104, 1, "BTC");
const shortTarget = context.targetWithMinimumReward("SHORT", 100, 99, shortRisk);
const shortSignal = { direction: "SHORT", entry: 100, stop: 100 + shortRisk, targetOne: shortTarget, targetTwo: shortTarget - shortRisk };
checkSignal(shortSignal);

const ladderLong = context.buildEntryLadder("LONG", 101, 100, longRisk, longTarget, "BTC");
assert.equal(ladderLong.length, 3, "long ladder should expose three entries");
ladderLong.forEach((level) => {
  assert.ok(level.stop < level.price, `${level.key} long stop must be below entry`);
  assert.ok(level.earlyTarget > level.price, `${level.key} long TP must be above entry`);
});

const ladderShort = context.buildEntryLadder("SHORT", 99, 100, shortRisk, shortTarget, "BTC");
assert.equal(ladderShort.length, 3, "short ladder should expose three entries");
ladderShort.forEach((level) => {
  assert.ok(level.stop > level.price, `${level.key} short stop must be above entry`);
  assert.ok(level.earlyTarget < level.price, `${level.key} short TP must be below entry`);
});

const forexRisk = context.boundedRiskDistance(1.085, 1.075, 0.001, "EURUSD");
assert.ok(forexRisk > 0 && forexRisk < 0.002, "forex risk must stay price-scale aware");

const goldStop = context.stopLossModel("LONG", 4155, 4140, 10, 8, "GOLD");
assert.ok(goldStop.stop === 4147, "long stop model should place stop below entry by risk distance");
assert.match(context.stopLossSummary({ entry: 4155, stop: 4147, stopModel: goldStop }), /Stop model/);
assert.match(context.trendGridSummary({ direction: "LONG", entryLevels: [1, 2, 3] }, {}), /LONG pullback grid/);

const sizing = context.tradeSizingFromSignal(longSignal, 10000, 0.05);
assert.ok(sizing.notional > 0, "sizing should produce notional for executable signal");
assert.ok(sizing.stopLoss <= 25.000001, "sizing should respect alert risk budget");
assert.ok(sizing.quantityLabel.includes("lot"), "sizing should be displayed in forex lots");

const ambiguous = context.gradeSignalEntry(
  {
    createdAt: "2026-06-15T10:00:00Z",
    direction: "LONG",
    entry: 100,
    expiresAt: "2026-06-15T10:30:00Z",
    status: "PENDING",
    stop: 98,
    targetOne: 102
  },
  [{ timestamp: "2026-06-15T10:05:00Z", high: 103, low: 97 }]
);
assert.equal(ambiguous.status, "LOSS");
assert.match(ambiguous.outcomeDetail, /same candle/);

assert.equal(
  context.signalHasExecutablePlan({ direction: "LONG", entry: 100, stop: 99, targetOne: 102 }),
  true,
  "long signal with valid geometry should be reviewable"
);
assert.equal(
  context.signalHasExecutablePlan({ direction: "LONG", entry: 100, stop: 101, targetOne: 102 }),
  false,
  "long signal with stop above entry must not be reviewable"
);
assert.equal(
  context.signalHasExecutablePlan({ direction: "SHORT", entry: 100, stop: 101, targetOne: 98 }),
  true,
  "short signal with valid geometry should be reviewable"
);
assert.equal(
  context.signalHasExecutablePlan({ direction: "SHORT", entry: 100, stop: 99, targetOne: 98 }),
  false,
  "short signal with stop below entry must not be reviewable"
);

console.log("signal safety checks passed");
