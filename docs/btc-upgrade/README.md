# BTC-only native analysis upgrade

This opt-in research package extends Monatise's native CME BTC path. It never connects to a data provider or broker, submits orders, changes subscriptions, or routes futures through canonical crypto or broker-gold engines. Existing source files and other instruments are unchanged.

## Analysis versus trading permission

Read `analysis_action`, `preferred_reference_setup` and `analysis` for the single preferred reference analysis. Missing H4 swing context and incomplete news coverage are disclosed as limitations rather than blanket analysis vetoes. The full native evidence panel remains available even when there is no supported setup.

A conditional reference is not an executable or engine-qualified trading signal. `trade_action`, `readiness`, `candidate_audit` and `regime` describe the separate strict shadow permission checks. Every output retains `execution_eligible=false` and `orders_created=0`. A user asking for one setup does not force a trade.

The package can return a fresh completed-trigger reference, or one interpreted future pullback watch based on a confirmed native break, a confirmed protective swing and an observed target. A watch explicitly requires a new future M5 retest/rejection and participation. Old replay triggers cannot be reactivated. No valid structural stop or realistic net reward/risk means No trade.

Hard analysis failures remain explicit: untrusted data, absent/invalid native quotes or stale structure, no usable native structure, invalidated geometry or insufficient net reward/risk. There is no invented CFD conversion or broker sizing.

## Implemented components

- `history.py`: persistent, append-only contract-keyed candle/source lineage; complete archive validation and revision refusal. It never fills missing candles or repairs old source evidence silently.
- `news.py`: hash-bound official-source reviews, causal receipt times, bounded calendar coverage and explicit missing publishers. Required scheduled-US scope: BLS, Federal Reserve, BEA, DOL and ISM. Capturing a page does not assert calendar completeness or cover unscheduled geopolitical/crypto news.
- `regime.py`: TREND / RANGE / TRANSITION / UNKNOWN for strict trading permission, plus closed-M15 hysteresis. Data unavailability never becomes a range. Intraday reference classification can continue when full higher-timeframe permission is unavailable.
- `setups.py`: existing native A/B/C trend observations, bullish and bearish; market-event-based expiry; bounded range rejection to midpoint; independent participation/economics/context attribution.
- `risk.py`: pause always dominates reduce/widen/normal; inventory, per-trade, aggregate open-risk and gross daily realized-loss caps in a local shadow ledger. Unresolved quote/fill exposure is not assumed flat. No martingale, averaging-down or broker-account claim.
- `service.py`: transactional/idempotent decisions using the existing ledger and arbitration, source-series continuity, frozen range boundaries, explicit gate groups, single preferred reference analysis and separate permission.
- `validation.py`: chronological replay, source-bound code/policy freeze for a bounded forward check, observed-L1 outcomes and clearly hypothetical rejected-plan followthrough. Repeated pathway labels are deduplicated by opportunity when counting rule attribution.
- `formatting.py`: one setup or No trade with actual snapshot timestamp and material limitations.

## Run against existing reviewed data

Use an environment with Databento/DBN support. Live validation here used Python 3.14 with Databento 0.90.0. Engineering tests also ran using the existing Python 3.12 project environment. Production dependency pins were not changed; `requirements-btc-upgrade.txt` is a separate research environment description.

```sh
PYTHONPATH=/absolute/path/to/source python -m monatise.research.btc_upgrade history \
  --manifest /private/btc-manifest.json --database /private/btc-history.sqlite \
  --output /private/new-history-receipt.json

PYTHONPATH=/absolute/path/to/source python -m monatise.research.btc_upgrade evaluate \
  --manifest /private/btc-manifest.json --policy /private/btc-policy.json \
  --news-review /private/btc-news-review.json --database /private/btc-shadow.sqlite \
  --stream btc-upgrade --series-id btc-reviewed-series \
  --output /private/new-analysis.json --text-output /private/new-analysis.md
```

Use new output paths; audit artifacts are not overwritten. A stable source series allows new captures while every decision still records the exact manifest, snapshot, configuration and code hashes. Changed policy/code requires a new stream/ledger; it cannot reuse an old selection as a newly optimized plan.

Run tests with `python -m pytest tests/research/btc_upgrade -q`. Genuine archive validation uses existing private hash-bound inputs and is separate from engineering fixtures.

## Initial research parameters

These are transparent hypotheses, not fitted or broker-calibrated defaults: native pivot radius 2; displacement baseline 12 M5 bars; quote age 5 seconds; trigger permission one M5 bar measured from the market trigger close; one native tick of drift and stop buffer; fees/slippage one native tick per side; minimum net RR 1 to the nearest observed trend objective.

Regime metrics use 20 M15 bars. Trend requires aligned native H4/H1/M15/M5 states, efficiency >=0.30 and CHOP <=50. Range requires confirmed non-directional higher context, CHOP >=55, efficiency <=0.25, at least two distinct visits to each boundary, and boundary drift <=20% of width. Regime activation needs two distinct closed M15 observations. Range edge zone is 15% of width, with two native ticks outside frozen boundaries as invalidation. Source gaps/insufficient confirmed context lead to UNKNOWN for trading permission; unsettled evidence leads to TRANSITION. Conditional analysis has its own configurable quote-age limit, default 60 seconds: ages up to and including 60 seconds may support a conditional reference; over 60 seconds produces STALE_DATA_REFRESH_REQUIRED and no setup. Quote timestamp/age remain explicit. The separately configurable entry quote limit remains five seconds in the initial research policy. Entry still requires a fresh quote and renewed trigger/price/stop/reward-risk checks. Expired or invalidated market triggers remain rejected regardless of quote age.

Reference analysis uses the available M15/M5 evidence and labels incomplete H4/H1 context. These descriptive metrics do not certify profitability or replace native swing provenance.

Risk defaults are local research limits: one standard CME contract, $1,000 per-trade/open-risk caps and $2,000 gross daily loss cap. The risk-day reset is explicitly UTC, not a claimed CME BTC trading-date/session-CVD anchor. None of these limits is a verified prop-firm account specification. Costs remain explicitly unverified research assumptions; this release refuses a verified-broker-cost claim without a separate calibration implementation.

## Remaining validation limits

A verified history response restores candles, not guaranteed swing geometry. The observed current clean history has 18 H4 candles and only one confirmed high: the complete two-high/two-low sequence is still unavailable. That is now reported distinctly from missing candle data.

Official calendar capture can remain incomplete, particularly for inaccessible sources. Such gaps no longer suppress reference analysis, but strict trading permission remains withheld.

A short post-freeze BTC capture checks causal timing and source handling. It cannot establish increased profitability, realistic CFD execution costs, a meaningful untouched out-of-sample win rate, or forward strategy performance. A longer preregistered sample and broker-specific cost evidence are still required. No new execution path is enabled.
