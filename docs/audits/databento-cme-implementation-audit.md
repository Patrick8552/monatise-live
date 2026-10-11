# CME infrastructure audit — 2026-10-11

Audit completed before implementation. Repository main is
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`. No AGENTS.md found.
This checkout began empty and was cloned from Patrick8552/monatise-live.
No production or billable acquisition is authorized by this implementation.

## Reusable components and compatibility

Main contains `adapters/databento_gold.py`: explicit GC selection, native
fixed-point prices, trades/MBP-1/statistics, bounded queues and quarantine.
`application/gold_basis.py` uses synchronized genuine midpoints, contract-specific
sample windows, dispersion/residual tests and contextual mapping only.
`application/gold_options.py` normalizes standard OG, joins exact GC underlying,
and implements American CRR/IV plus European benchmark Greeks. American gamma
certification and GC GIL activation remain unavailable.

Existing hierarchy, candle finalization, risk validation, PostgreSQL documents,
Redis coordination and approval guards are reusable. No new runtime route is
needed. FlashAlpha primary, ThetaData validation and Unusual Whales confirmation
remain unchanged; GC coverage of the latter two has not been established.

Separate local work was located under
`/Users/thankgod/Documents/Codex/2026-09-14/g/work/`:

* `monatise-databento-gc-research`, commit `a144db7`: strict feed/economic-exchange
  identity, definition registry, guarded acquisition, immutable DBN archive,
  PostgreSQL manifests, historical replay, native GCZ6 validation and aggregation.
* `monatise-gold-h1-fib-f0`, clean commit
  `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`: frozen H1 selector/shadow evaluator.
  It is absent from main. Use its credential-free pinned subprocess interface;
  do not change or duplicate its selector or shared analytical policies.
* Existing acquired data and reports are under
  `.../g/outputs/monatise-gc-research-2026-10-11/`. Saved expanded reports indicate
  69 valid constrained Fibonacci assessments across 12 distinct valid episodes
  among 557 assessments. Evaluation-period subset: 22 valid of 112. These are
  dependent anchor diagnostics, not trades. Entries/stops/RR/win rate are null;
  continuity and point-in-time availability are uncertified. Independent local
  re-execution and artifact hashing are required in final validation.

## Analytical capability inventory

| Capability | Status | Reuse / limitation |
|---|---|---|
| Fibonacci / validated anchors / 1.272, 1.414, 1.618 | Implemented | fibonacci_liquidity; frozen research constraint via external pinned checkout |
| Market structure / structural highs and lows / CHoCH | Implemented | market_structure engine; causal confirmation rules |
| Liquidity sweeps / displacement | Implemented | liquidity_sweep and Gold sweep_reversal |
| Failed reclaims | Implemented | reclaim engine |
| Volume profiles / POC / known-side delta and CVD | Partially implemented | GCReplay / historical replay; unknown sides retained, full coverage required |
| Order-book imbalance | Partially implemented | order_flow consumes supplied metric; native depth adapter missing |
| Visible liquidity concentration | Proposed | bounded MBP-10 metrics; no institutional-intent claim |
| Regime / higher-timeframe context | Implemented | regime and shared hierarchy; no production change |
| MBO lifecycle | Missing | optional offline event interface only; queue reconstruction requires separate certification |
| GC options GIL | Partially implemented | definitions/models exist; complete OI chain, certified American Greeks, positioning model absent |

## Gaps, debt and proposed changes

Reuse local historical infrastructure on main with its explicit optional identity
arguments and legacy defaults preserved. Add an observed dataset/schema registry,
bounded definition discovery for GC/OG/ES/NQ/CL, and exact-symbol selection.
Unrelated dataset codes are extension placeholders, not implemented providers.
Add local persistent manifests, overlap detection/cache planning, durable budget
reservations, separate credit/billing reporting, and settlement quarantine.
Add conservative contract-aware historical bars/session validation and disabled
advanced adapters. Reuse OG normalizer and add a point-in-time options input join.
Keep acquired licensed observations outside Git and generate versioned hash-bound
research reports. No deployment/configuration/FTMO/Telegram files need changes.

Compatibility risks: main's legacy GC definition expects economic publisher XCEC,
while actual metadata identifies feed GLBX. Actual GCZ6 definitions use TRYOZ and
display_factor 0.1; DBN prices are already normalized and must not be scaled twice.
Use the existing narrow native-contract validator for actual GCZ6 and separate
reviewed general metadata models. Do not relax production legacy checks.
UTC-grid aggregation rejects session-truncated H4 buckets; closures can make
H4 context stale. Missing OHLCV minutes can mean no trades, so never synthesize
bars or assert a transport gap without evidence. Explicit rolls retain both raw
contracts; no auto-adjusted continuous price or synthetic XAUUSD is permitted.

QuestDB/Grafana/Kafka add no demonstrated benefit for the current bounded local
research workload. Existing PostgreSQL control plane and filesystem DBN suffice;
a lightweight local metadata implementation supports credential-free research.
Revisit time-series infrastructure only with measured query/throughput requirements.

## Costs and validation plan

Implementation/tests/replays use already acquired data or synthetic fixtures:
incremental Databento cost $0. Saved prices are historical estimates, not a new
authorization or evidence of final spending. Obtain fresh exact request estimates
with metadata.get_cost before any new download. Estimate is not a provider charge
cap; signup credit is separately tracked usage, never proof of free acquisition.
Unknown billing and partial downloads remain quarantined. No automatic retries.

Required tests: existing GC/options/Gold/risk/approval suites plus request scopes,
metadata/schema compatibility, explicit symbols/expiry/rolls, fixed-point records,
sessions/closures/missing/forming/duplicate bars, immutable archive and replay
determinism, cache/overlaps, concurrent budgets and approval receipts, quarantine,
options point-in-time joins, default-disabled depth/MBO and secret-free isolation.
Run full Python regression suite; report environment-dependent database skips.

Official references checked: [historical API and get_cost](https://databento.com/docs/reference-historical/basics/),
[schemas](https://databento.com/docs/schemas-and-data-formats),
[GLBX dataset](https://databento.com/docs/venues-and-datasets/glbx-mdp3).
Schema listing establishes availability, not account entitlement. No API key or
subscription is needed for this implementation's offline acceptance tests.
