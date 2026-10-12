# Phase 5 GC options readiness

Standard OG is visible in the authenticated Databento catalog. No native standard OG
definitions, synchronized quotes, published OI or dated rates were acquired here.
Catalog coverage is not schema entitlement or accepted instrument lineage.

The options coverage adapter selects an exact normalized GC underlying, one explicit
expiration, up to four reviewed strikes and calls/puts, capped at eight contracts.
It rejects ambiguous revisions, mismatched underlying/publisher/economics, expired
contracts, unreviewed American conventions and future or unrelated OI. Missing OI
stays null; observed call/put and strike totals describe selected contracts only.
Settlement is a required reviewed reference, never inferred from a symbol name.

Existing native options metadata normalization, published OI clocks and option/
underlying quote joins are reused. Existing American CRR IV remains a model estimate;
American gamma is uncertified and null. The existing European benchmark is separate
model engineering. No signed dealer GEX, gamma flip, institutional positioning or
complete-chain claim is derived from aggregate OI.

The first authentic proposal should select at most one expiration and a small
strike region around a genuine source-bound GC observation. Resolve exact standard
OG definitions and underlying identities before creating HistoricalRequest objects.
Quote only definition, required statistics/OI and a narrow quote window; reuse cached
underlying data. Exact symbols, dates, fresh provider costs, cache/overlap, entitlements,
credit-only ceiling, zero-cash protection and individual receipts must be reviewed
before acquisition. Broad OG product download remains disabled.

FlashAlpha remains the primary gamma provider; ThetaData validation and Unusual
Whales confirmation retain their existing applicability requirements. Neither is
assumed to cover GC futures options. Databento supplies independent exchange
observations, not precomputed dealer positioning. GIL and the GC Fibonacci experiment
remain separate and disabled for this integration.
