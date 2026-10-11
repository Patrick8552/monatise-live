# Native GCZ6 reference boundary

The approved first authentic download on 11 October 2026 contains five GCZ6
definitions (publisher 1, instrument 41271, XCEC, maturity December 2026).
All use `TRYOZ`, `display_factor=100000000`, a native tick of `100000000`,
size `100000000000` and increment amount `1000000000`.
The existing legacy validator rejects TRYOZ and requires a display factor of 1.
Those defaults remain unchanged.

`research/gc_fib/native_contract.py` is a narrowly scoped, offline reference
boundary for the exact reviewed contract. It reuses the publisher identity
policy, GCDefinition, HistoricalGCReference and downstream normalization.
It validates native outright identity, units, tick, size, currency convention,
activation, receive, event, maturity and expiry. Original bytes and native terms
remain immutable. Unknown formats or contradictory terms reject.

Databento's market price fields already use conventional normalized prices
in fixed-point units of 1e-9. CME's venue display factor must not be applied a
second time. The exact reference check is:
`increment_amount / display_factor == tick * contract_size`.
For this reviewed GC contract both sides equal USD 10. No inferred or nearest
currency convention is accepted.

Sources reviewed read-only:

- https://databento.com/docs/schemas-and-data-formats/instrument-definitions
- https://databento.com/docs/examples/instrument-definitions/contract-notional
- https://www.cmegroup.com/market-regulation/files/gold-futures-and-options-fact-card.pdf

This is research support, not a change to Gold trading rules, broker XAUUSD
units, GIL, execution or the frozen H1 selector. Current legacy rejection is
retained as an audit record. Retrospective references remain explicitly
uncertified for historical local point-in-time availability.
