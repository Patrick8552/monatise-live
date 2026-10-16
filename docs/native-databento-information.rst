Native Databento information path
================================

Databento normalizes the exchange feed. This adapter interprets DBN fields; it
does not impose statistical price, MAD, spread or trading qualification caps.
Native information has no inherited trade/book/OI age cutoff and no extra
ten-second candle hold. Observed age and reference/publication times are exposed.
A dated observation is not a contemporaneous or executable quote.

The local source-position hashes, contract identity, record shape, native flags,
source ordering, as-of availability, real candle children, raw error records and
gap evidence remain. These prevent misinterpretation and false provenance; they
are implementation integrity checks, not additional Databento trading rules.
Unknown gaps do not become zero-volume candles. Provider timestamp/quality flags
remain visible and do not become invented timestamps or independent truth.
Resource limits and no-purchase/no-execution boundaries remain separate from
market information availability.

Process separation
------------------

Do not call FuturesMarketInfo.analyse or load_capture in the capture callback or
capture asyncio monitor. The collector may write source_snapshot from the latest
per-instrument book (constant-size data, no history scan). A separate OS process
uses this command against the existing private capture::

  python -m monatise.research.native_futures.cache --refresh \
    --capture /private/capture --cache /private/analysis.json \
    --duration 300 --interval 30

The worker performs forensic reconstruction and atomic snapshot replacement.
Failed refreshes preserve the prior result and record REFRESH_FAILED; they do not
silently reconnect or retry a provider. Source progress must be published
independently by the collector. This worker creates no provider connections.
The finite duration bounds scheduling, not an already-running reconstruction.

Read the cached result without scanning history::

  python -m monatise.research.native_futures.cache \
    --cache /private/analysis.json --source-snapshot /private/source.json

Response delivery reports analysis age, source-observation age and quote age.
The optional quote overlay must match the exact capture and contract. It cannot
certify current connection state or broker executability. A last refresh READY
status is not proof the worker or collector remains running. Closed/failed
sources remain explicitly historical/unavailable for current live use.

Official references
-------------------

* https://databento.com/docs/api-reference-live
* https://databento.com/docs/standards-and-conventions/common-fields-enums-types
* https://databento.com/docs/schemas-and-data-formats/ohlcv
* https://databento.com/blog/live-api-changes-2026-04

Databento recommends nonblocking callbacks and using heartbeat/control/error
messages. Slow-reader warn preserves messages but can increase lag. Native
REPLAY_COMPLETED is per schema; END_OF_INTERVAL establishes interval publication.
No new subscription, deployment, order placement, crypto graph, frozen H1, GIL
or XAUUSD router is part of this path. MBP-10 previously denied by the gateway
remains excluded. This module is not production or full-session certification.
