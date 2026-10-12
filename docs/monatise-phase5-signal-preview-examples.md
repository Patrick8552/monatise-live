# Phase 5 research preview examples

The complete machine contract includes asset/market/source/broker identity, UTC
analysis time, H4/H1/M15/M5/M1 evidence, institutional/Fibonacci/liquidity evidence,
direction/decision, entry/stop/targets/RR/expiry, quality/missing/rejection fields,
mapping status/uncertainty, provenance and analytical qualification. Missing inputs
remain null. `text_preview` formats those fields without importing a publisher.

Authentic GC example (genuine native context, missing broker evidence):

```text
RESEARCH ONLY — UNAVAILABLE
Asset: GC
Market: BROKER_CFD
Source instrument: GCZ6
Broker instrument: XAU/USD
H4 regime: unavailable
H1 structure: unavailable
M15 setup: unavailable
M5 trigger: unavailable
M1 entry zone: unavailable
Institutional evidence: captured native GC window, continuity uncertified
Fibonacci evidence: unavailable
Liquidity evidence: unavailable
Direction: unavailable
Decision: MAPPING_UNAVAILABLE
Reference entry: unavailable
Structural stop: unavailable
Take-profit targets: unavailable
Risk-to-reward: unavailable
Expiration: unavailable
Missing evidence: authentic broker candles and synchronized broker quotes
Mapping status: MAPPING_UNAVAILABLE
Mapping uncertainty: unavailable
Analytical qualification: BLOCKED_AUTHENTIC_INPUTS
Publication eligible: FALSE
Approval eligible: FALSE
Execution eligible: FALSE
```

The private output includes exact UTC nanoseconds, provenance and full partial
indicator metadata. ES/NQ additionally lack accepted native samples and mandatory
primary positioning. BTC lacks sufficient native exchange inputs. A blocked
evaluation is not presented as a genuine end-to-end strategy assessment.

Engineering output is explicitly headed `RESEARCH ONLY — ENGINEERING_SYNTHETIC`.
The controlled Gold fixture produces qualified LONG geometry and the separate SHORT
test produces SHORT geometry through the unchanged canonical hierarchy. Its complete
preview exposes actual H1/M15/M5/Fibonacci/liquidity fields returned by the engine;
all operational eligibility flags remain false. Index and crypto acceptance fixtures
return NO_TRADE and retain null unqualified geometry. Scores remain confluence
measures, not win probabilities. No historical win rate or executed trade is reported.

No message was sent to Telegram and no approval request was created. This document
describes future presentation formatting only; it does not register a production flow.
