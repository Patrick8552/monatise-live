# Stock gamma evidence and confidence policy

Stock analysis resolves gamma independently of candle direction. The primary number is never accepted merely because it is numeric. A rejected primary value remains in `quarantined_primary` with `trusted: false`; only a validated certificate can enter gamma directional bias.

## Resolution ladder

1. `CERTIFIED_PRIMARY`: explicit FlashAlpha `available` status, matching GEX/levels identities, complete timestamps, fresh source feeds, valid underlying/walls/net GEX. A quality failure permits one bounded full re-query; the replacement must be newly stamped and certified. Scheduled stock capacity budgets four primary requests per symbol. Existing transport retry/quota controls remain in force.
2. `CERTIFIED_RECONSTRUCTED`: a trusted independent adapter supplies the complete qualified options book. Repricing uses explicit constant-IV Black-Scholes and call-positive/put-negative open interest. Inputs require aligned OPRA quotes, dated carry inputs, exact expiries, expected exchange-session OI date, unadjusted contract multipliers and independently validated IV/Greeks. Incomplete books, weak quotes, ambiguous/no crossings, model disagreement and unstable strike perturbations reject certification.
3. `CERTIFIED_CROSS_PROVIDER`: an independent full-chain estimate with explicit calculation ownership, source lineage, snapshot identity, methodology and numerical-quality evidence. Ordinary equity quotes or a provider name do not satisfy this contract.
4. `UNCERTIFIED`: no accepted flip is present. The quarantined candidate is diagnostic only. The separate strategy-confidence policy decides whether independently confirmed candle evidence can proceed.

The independent policy is versioned in `gamma_reconstruction.py`: maximum age 120 seconds, timestamp skew 60 seconds, candidate/spot tolerance 0.25% of spot, maximum root movement 0.10% of spot under a +/-25% single-strike perturbation, bounded book size and computation time. These are conservative evidence thresholds, not measured profitability claims. All independent certificates expire no later than their supporting primary evidence. A certificate digest binds its value, source, quality and quarantine history.

## Confidence and strategy eligibility

The current shared candle strategy, `hierarchy-shadow-v1`, treats gamma as supplemental. A known uncertainty status such as `sensitive_root` can support a **DEGRADED** setup only when required underlying/wall/source evidence remains valid and all six independent checks pass: H1 structure, confirmed M15 liquidity sweep, value location, M5 confirmation, aligned valid M15 Fibonacci anchor and confirmed price action. Possible liquidity alone is insufficient. The shared timeframe policy remains 4H context, 1H analysis, 15M setup/stop, 5M trigger/confirmation and 1M entry.

A stored-sign mismatch, unknown provider status, stale/missing/mismatched supporting data or independent-provider disagreement cannot become a confidence downgrade. Certified gamma contradicting the candle direction still rejects the setup. Unknown/gamma-primary strategy versions require certified gamma. Crypto and futures-linked strategy policies are unchanged.

A degraded setup permits **0.50 times the otherwise allowed monetary risk budget**, after configured/account/drawdown limits and before stop-distance/tick-value lot sizing and downward rounding. A broker minimum lot above the permitted budget rejects the trade. The normal risk request, multiplier and confidence identity are persisted with the signal. Publication, approval, command delivery and pending leases revalidate these against the authoritative hierarchy proof. Revalidation cannot increase the amount/volume reviewed by the user.

Gamma and confidence form part of the immutable setup identity. Fresh recertification is a new setup requiring its own approval; it cannot silently enlarge an approved order. Old proofs remain auditable and superseded proofs lose execution eligibility. Approved pending orders retain their original SL/TP, expiry and entry zone; loss of eligibility revokes their cancellation lease. Observed/executable prices are never replaced with the desired entry price.

## Current provider capability

`AlpacaGammaProvider` is deliberately a capability/coverage collector, not a fabricated certificate. The production account returned HTTP 403 for OPRA snapshots on 15 September 2026. Even with OPRA entitlement, current Alpaca responses alone do not supply all dated carry/exact-expiry inputs this reconstruction model requires; those must come from a verified adapter. Indicative quotes are not substituted. No second GEX provider is configured. B/C paths are covered with deterministic qualified-source fixtures; they are not claimed as live independent confirmation for SNOW.

The adapter contracts are `chain(symbol)` for reconstruction and `gamma_estimate(symbol)` for cross-provider estimates, injected through `GammaEvidenceLadder`. This deliberately requires an explicit integration with a qualified provider rather than accepting arbitrary client evidence or an environment-provided number.

## Provider documentation

- FlashAlpha quality-status semantics: https://flashalpha.com/docs/changelog
- Alpaca option snapshots: https://docs.alpaca.markets/us/v1.1/reference/optionchain
- Alpaca contract metadata: https://docs.alpaca.markets/us/v1.1/reference/get-options-contracts
- Alpaca market-data entitlements: https://docs.alpaca.markets/us/docs/market-data-faq
