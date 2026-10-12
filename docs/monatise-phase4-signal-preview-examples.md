# Phase 4 analytical preview examples

Every example is non-executable: execution, approval, publication, GIL and live
subscriptions are disabled. No preview is a filled trade or market-performance result.
The complete typed records, proposed geometry where supported, source hashes,
limitations/freshness/expiry and rejection reasons are in the private accepted
`private-reports/phase4-acceptance-v2/preview-01.json` and identical `preview-02.json`.
Raw licensed prices/derived values are retained locally outside Git.

| Example | Evidence | Decision / mapping | Explanation |
|---|---|---|---|
| GCZ6 / XAU/USD | Authentic archived GC institutional observations, October 5 15:00–15:15 UTC; no broker prices/candles | MAPPING_UNAVAILABLE | GC prices remain GC. No assumed broker offset or proposed entry/stop/target. Captured indicators have independent scope and retrospective provenance. |
| ES / US500.cash | Authentic ES definitions/observations and broker export absent | MAPPING_UNAVAILABLE; institutional data UNAVAILABLE | No guessed native ID/contract or synthetic broker signal. |
| NQ / US100.cash | Authentic NQ definitions/observations and broker export absent | MAPPING_UNAVAILABLE; institutional data UNAVAILABLE | Same explicit missing-data boundary; no Gold-engine substitution. |
| BTC | Authentic native exchange/CoinGlass export absent | INSUFFICIENT_MARKET_DATA; mapping NOT_APPLICABLE | Native crypto evidence is required; CME futures are not replacement prices. |
| Gold broker fixture | ENGINEERING_SYNTHETIC candles/units and distinct repeated-observation proofs | LONG analytical preview; mapping unavailable as independent context | Actual Gold coordinator/evaluator, structural geometry, targets/RR and expiry; no institutional scoring change. Separate SHORT fixture is tested. |
| ES broker/positioning fixture | ENGINEERING_SYNTHETIC broker candles and primary positioning context | NO_TRADE / awaiting confirmation | Existing index HierarchyLayerEvaluator and FlashAlpha validation are exercised; no snapshot-only fallback. |
| NQ broker/positioning fixture | ENGINEERING_SYNTHETIC broker candles and primary positioning context | NO_TRADE / awaiting confirmation | Index rules preserved. |
| BTC native-data fixture | ENGINEERING_SYNTHETIC candle/derivative scenario | NO_TRADE; structural execution geometry unavailable | Actual unchanged crypto analytical production builder/DecisionEngine; CoinGlass-shaped inputs retained and no Gold routing. |

The engineering mapping example demonstrates five synchronized paired observations
and a contextual estimate with observed uncertainty. It is not an observed broker
price. The engineering OG example produces American-model IV with gamma unavailable;
the European gamma primitive is a separate unsigned model benchmark, not dealer GEX.

To reproduce with the accepted local GC archives:

```bash
.venv/bin/python -m monatise.research.institutional.runner \
  --data-root /Users/thankgod/Documents/Codex/2026-09-14/g/outputs/monatise-gc-research-2026-10-11 \
  --prepared-file private-reports/gc-qualification-acceptance-v1/prepared-input.json \
  --output private-reports/phase4-new-version
```

Omit the two native-source arguments for credential-free fixture/unavailable examples.
Every output directory must be new; incomplete runs remain quarantined. The runner
does not accept production credentials or connect to providers, brokers or publishers.
