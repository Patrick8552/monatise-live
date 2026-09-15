# FlashAlpha evidence and NQ direction integrity

`US100.cash` is the FTMO Nasdaq-100 index CFD. The registry links it to
`NQ` / `MNQ` futures context; it does not identify the CFD as a futures contract.
FlashAlpha requests use `NQ=F`. Index market structure continues to use the
shared hierarchy and authenticated MT5 CFD candles.

FlashAlpha's `stored_sign_mismatch` is an upstream gamma-boundary certification
failure: the repriced option book disagrees with the provider's stored net-GEX
sign. It is not a request to invert the trade direction or the CFD mapping.
See the provider's [reason-code methodology](https://flashalpha.com/articles/gamma-flip-stability-why-levels-disappear-near-close)
and [API changelog](https://flashalpha.com/docs/changelog).

The adapter retains signed `net_gex` without inversion. Positioning bias compares
price with a certified gamma boundary; signed exposure is not a trade side.
An uncertified boundary yields neutral context, including when an indicative
numeric boundary is present. Each endpoint's certificate and advertised source
feed timestamps must validate independently. A second endpoint cannot restore a
certificate rejected by the first. Walls must bracket the observed underlying
price. Provider quality failures remain execution-ineligible.

The shared H1 structure remains the direction authority. Conflicting NQ context
can veto a setup; it cannot reverse the hierarchy's direction. Long maps to buy
and short maps to sell. Broker conversion uses the real Ask for buys and Bid for
sells and positive price scaling, preserving SL/TP geometry. An observed market
price and a permitted entry zone remain separate facts.

Confirmed hierarchy records now reject a changed direction for an existing
bundle. Publication and approval validate persisted signal identity and direction
against the proposal; pending-entry revalidation uses the same check. A mismatch
fails closed instead of editing a stored signal or displaying another direction.

Read-only FlashAlpha requests retry temporary HTTP 502/503/504 and timeouts,
including timeouts wrapped by `URLError`. The existing three-attempt limit,
short retry-delay limit and exhausted-quota protection remain. Authentication,
coverage, malformed payload and quality failures are not retried into eligibility.

Regression coverage includes both NQ directions with positive and negative GEX,
raw adapter output, scanner traces, confirmed evidence, persisted signals,
Telegram proposal text, Ask/Bid conversion, approval intents, duplicate approvals,
rejection after an integrity failure, uncertified indicative levels, endpoint
disagreement, missing source timestamps, wall geometry and bounded retries.
