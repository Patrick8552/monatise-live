# Versioned initial research definitions

These are opt-in exploratory hypotheses, not calibrated production settings or evidence of an edge. `Policy()` ships unresolved and cannot produce BUY/SELL. Behavioral checks, engineering fixtures and source-data inventory must precede an exploratory run; its rationale hash binds this document. No profitability search selects these values.

| Parameter/definition | Initial exploratory value | Rationale and limit |
| --- | --- | --- |
| Confirmed pivot | Strict two bars each side; ambiguous outside extrema excluded | Reproduces the reviewed native descriptive swing baseline. Requires completed, available right-hand candles; not a proven optimum. |
| Displacement baseline | 12 preceding M5 bodies | One H1 observation window, a transparent clock-based baseline rather than a fitted trade-performance parameter. Directional body must exceed its median and close in its directional half. |
| Break | Completed close at least one native tick beyond a previously confirmed reference | Smallest representable strict break; reference must exist before the break bar begins. |
| Retest | A later M5 candle touches within one tick of the broken reference and closes at least one tick on the intended side | Native-resolution contact and closed rejection. Same-candle sweep/reversal sequencing is not inferred. |
| Stop | Completed retest extreme plus one adverse native tick | Structural invalidation, not a distance selected to improve reward/risk. |
| Trigger permission | One M5 bar after trigger availability, or reviewed session end/expiry if earlier | Same trigger timeframe; no retired H1 expiry selector. Structural invalidation can end it sooner. |
| Entry tolerance | One tick of adverse drift, with explicit spread and modeled slippage | A native-resolution hypothesis, not guaranteed fillability. Actual permitted modeled zone is frozen at selection. |
| Quote age | 5 seconds | Existing finite-capture heartbeat interval; this is a conservative research age rule, not certification that a quote is executable. |
| Volume variant 1 | AGGRESSOR_ROBUST | Complete retained trigger-window coverage; directional signed volume must exceed unknown volume even if all unknowns oppose it. No arbitrary unknown-side percentage. |
| Volume variant 2 | EXECUTED_BAR_PARTICIPATION | Genuine executed OHLCV volume at least preceding 12-bar median and a directional rejection close. Unsigned volume is participation, not inferred aggressor delta or absorption. |
| Net R:R floor | 1 to nearest observed target, after modeled costs | Symmetric reward/loss economic floor for this hypothesis; not a break-even win probability or profitability claim. |
| Fee sensitivity | One native tick-value per side | Explicit hypothetical fee-equivalent cost, not a broker commission quotation. Report this assumption and stress it; real broker costs remain unavailable. |
| Slippage sensitivity | One adverse native tick per modeled entry/exit | Explicit hypothetical cost; model includes it in fills, not twice in fees. |
| Historical modeled spread | Maximum development-capture native L1 spread in ticks, frozen by manifest | Source-backed finite-sample assumption, not a guaranteed future spread bound. Native L1 is used when available; modeled quotes remain clearly labelled. |
| H1 mixed transition | Matching separately confirmed break may permit A/C | A mixed label alone is never neutral or directional. B still requires full confirmed alignment. |
| H4 neutral/mixed and M15 neutral/mixed | Neutral H4 veto by default; neutral M15 allowed; mixed only with matching explicit transition rule | Vetoes and allowances are documented policy choices. No missing-data neutrality. |
| News | Strict policy requires coverage; exploratory historical run can explicitly waive completeness | Known events retained with declared windows. A waiver is a material limitation and does not validate news-aware trading. |

The historical sample is too short and has already been inspected. Later-date comparisons are retrospective chronological holdout checks, not untouched out-of-sample or forward validation. Degraded dates are conservatively screened ex post, and the resulting sample exclusions must be disclosed.
