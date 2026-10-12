# Phase 5 broker ingestion and mapping

Authentic GC→XAUUSD, ES→US500.cash and NQ→US100.cash mappings are **unavailable**.
No genuine synchronized broker observations were found in the inspected research
artifacts. No current terminal quote was represented as a historical observation.

`broker_import.py` admits bounded local exports with an independent source/clock
review. Broker, server, opaque account reference, native symbol, digits, tick,
point, contract size, currency and price unit form a source-bound namespace.
Reviewed sessions bind to that namespace. Quote prices use exact decimal strings;
event, optional receipt, original availability and local admission remain separate.
Native millisecond clocks must agree with exported nanoseconds. OHLC imports require
five bounded finalized continuous timeframes, explicit UTC, native tick geometry
and broker tick-count volume. Session closures require a separately reviewed calendar.

An absent receipt remains null. Historical imports are available at local admission;
they are not backdated. A point-in-time claim needs original capture proof. The
canonical candle adapter validates these exports through existing CandleEvidence and
asset engines; it does not connect to a terminal, bridge or production store.

`mapping_report.py` reuses ContextMapper and GoldBasisService. It rejects future,
stale, mixed-server, mismatched contract/unit, expired, out-of-session and duplicated
paired evidence. There must be at least five distinct source positions on both sides,
with bounded age/skew and independently reviewed overlapping sessions. Every report
binds the level, contract, policy, sessions and paired observations in its input hash.
Rejected reports retain available clocks, including null receipts.

Valid engineering reports include native contract and source price, broker identity,
observed basis, mapped reference, paired clocks, sample count, uncertainty, expiry,
quality, rejection reasons and provenance. Uncertainty is the existing observed
dispersion/half-spread bound, not a statistical confidence interval. All mapped
levels are context only; they cannot supply broker entry or execution authority.

Authentic reports contain null basis, mapped levels, uncertainty and expiry with
`MAPPING_UNAVAILABLE`. Public unit tests cover all three relationships using clearly
labelled engineering data. Raw licensed prices and account observations stay private.

To complete authentic mapping, supply bounded reviewed broker tick/candle exports,
original UTC/capture/session/specification evidence and synchronized exact-contract
exchange quotes. Live broker login, account access, bridge/store writes or terminal
execution remain separate authorization dependencies. The existing MT5 trading EA
was not run. Historical receipt absence cannot be repaired by inventing a timestamp.
