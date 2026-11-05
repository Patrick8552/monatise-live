# BTC Databento guidance and data upgrade

Reviewed 4 November 2026. User scope: BTC only. The user's later explicit permission authorizes one bounded read-only capture using the existing subscription. It supersedes the original no-new-live-connection boundary only for that capture. Shadow-only execution, production isolation, no paid historical downloads and no subscription changes continue to apply.

Databento documentation specifies data semantics and integration practices. It does not certify Monatise's models, dictate displacement/pivot/volume/R:R thresholds or establish profitability.

| Official guidance | Implementation response |
| --- | --- |
| Construct OHLCV from trades when feasible; vendor bars may differ in timestamp, trade-break and publication conventions. | Optional `TRADE_AGGREGATED_WHERE_COVERED` manifest mode creates receive-time minute bars only over reviewed retained-execution coverage. Vendor warm-up stays explicit. Disagreements are flagged; no-print intervals create no artificial candle. |
| OHLCV timestamps identify interval starts, and Databento bars use trade `ts_recv`. | Derived bars use left-closed/right-open receive-time windows and preserve native sequence/physical order at tied timestamps. Completed/available time is separate. |
| MBP-1 supplies every BBO update; TBBO is trade-sampled and BBO is interval-sampled. | The BTC capture uses actual `mbp-1`, alongside trades, definitions and minute bars. Updated BTC manifests disable modeled spreads. Missing/stale/absent native BBO remains ineligible. |
| `F_SNAPSHOT` is replay provenance; bad receive-clock and channel-gap flags are distinct. | Raw flags persist. Bit 32 alone is no longer a quality rejection; bits 8 and 4 remain explicit failures. This correction does not turn an MBO snapshot into a trade or reconstruct missing history. |
| Undefined or missing BBO sides cannot provide an executable reference quote. | Native BBO invalidation markers preserve absence without invented prices and invalidate the previous good quote until a valid later update. Final revalidation checks this state too. |
| Intraday replay is bounded, and completion is per schema. | Capture is finite, no automatic reconnect. All four subscription ACKs/replay-completed controls and raw/archive bytes must reconcile before admission. End-of-interval controls support completed-minute absence accounting. |
| Reconnection recovery must track the last filtering timestamp and count at that timestamp per instrument/schema. | This finite collector stops on transport failure instead of silently resuming with a gap. Existing source/native sequence and ordinal provenance are retained. Automatic recovery is not enabled or claimed by this release. |

Primary sources:

- [OHLCV conventions and best practices](https://databento.com/docs/schemas/ohlcv)
- [MBP-1 fields](https://databento.com/docs/schemas/mbp-1)
- [MBP-1, TBBO and BBO use cases](https://databento.com/docs/faqs/difference-between-mbp-and-tbbo)
- [Flags, side and undefined-price conventions](https://databento.com/docs/conventions/common-fields-enums-types)
- [Intraday replay](https://databento.com/docs/api-live/basics/intraday-replay?lang=python)
- [System messages and interval completion](https://databento.com/docs/api-live/basics/system-messages?lang=python)
- [Disconnection recovery](https://databento.com/docs/api-live/basics/recovering-after-a-disconnection?lang=python)

## Source and outcome modes

The original full comparison artifacts retain their old source/code hashes and results. They are not relabelled as results from upgraded code. Updated manifests and fresh experiment databases identify this release separately.

Trade reconstruction exposed overlapping replay copies with identical exchange event/payload/sequence but slightly different `ts_recv`/`ts_in_delta`. Full-byte deduplication counted 886 BTC executions twice in the earlier source inventory. The corrected reader identifies the exchange payload plus within-source occurrence, preserves repeated identical executions within one source, and records duplicate timing/flag/source aliases. It chooses the earliest actual capture admission as the canonical source, rather than selecting a favorable reconstructed receive timestamp. The original full comparison's volume/profile/flow evidence is superseded by this correction and must not be treated as validation of the corrected implementation. No profitability threshold was changed to obtain this correction.

`bar_source_mode` defaults to `VENDOR_OHLCV`. Optional `TRADE_AGGREGATED_WHERE_COVERED` derives only covered minutes and binds the transformation in a new manifest hash. A mismatching vendor/retained-trade minute carries `TRADE_VENDOR_AGGREGATE_MISMATCH`; it is not silently accepted as clean context. Old vendor bars remain available outside retained-execution coverage.

`outcome_mode` defaults to the existing `MINUTE_BAR` research model. Explicit `NATIVE_L1` uses later causally ordered observed quotes with reviewed coverage and declared slippage/fees. It never substitutes OHLC fills. Lost/flagged book coverage during a filled reference position yields an unresolved outcome. First-target/stop ordering can be resolved only where actual retained quote coverage supports it; queue execution, broker fills and exchange-wide completeness remain unverified.

Selected plans now explicitly store their complete frozen policy, policy hash and exact contract key. An outcome evaluator with changed cost/management policy fails; another contract's snapshot cannot fill the plan. This supplements immutable selected-plan and experiment configuration controls.

## BTC readiness command

```sh
python -m monatise.research.unified readiness \
  --manifest /absolute/path/to/btc-native-manifest.json \
  --policy /absolute/path/to/policy-btc-native-l1-strict-news.json \
  --output /absolute/path/to/readiness.json
```

This command reports actual L1 age/spread, context availability, retained flow, source disagreements, news coverage and unresolved policy parameters. It creates no connection or order. Readiness is not trading-performance validation.

Bounded comparisons can supply `--start-ns` and `--end-ns`. The result records that evaluation window separately from total source inventory. Do not treat a short fresh capture as months of untouched out-of-sample evidence.

## Remaining evidence requirements

Databento cannot provide prop-firm CFD execution costs/basis or complete economic-news coverage merely by supplying CME prices. No complete calendar or broker calibration is invented. Public BLS/Fed/ISM calendars were checked; the fetched BEA schedule did not expose usable release entries, so complete cross-source coverage is not asserted.

Strict news-required policy remains blocked until an adequately covered, timestamped calendar exists. The exploratory variant declares its incomplete-news waiver. Higher-timeframe context needs enough genuine, clean, causally confirmed history; a missing H4 swing is never converted into neutrality. More future observations and a frozen evaluation protocol are needed for statistical/forward conclusions. The five-second quote-age rule and all strategy/cost parameters are Monatise research choices, not Databento recommendations.
