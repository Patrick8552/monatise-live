# Phase 5 authentic data acceptance

Existing GC is the previously accepted native source. Genuine ESZ6/NQZ6 definitions,
trades and candles were subsequently acquired using the supplied SDK credential,
validated locally and replayed twice. Their research admission remains quarantined
for exact billing reconciliation. Engineering fixtures remain separate; standard OG
options were not acquired.

| Dataset / asset | Schemas / interface | Authentic acceptance | Boundary |
|---|---|---|---|
| GLBX.MDP3 GCZ6 | definition, trades, ohlcv-1m, mbp-1 | Existing licensed archives replayed twice | Captured window; continuity and historical local availability uncertified |
| GLBX.MDP3 ESZ6 / NQZ6 | definition, trades, ohlcv-1m | Genuine archives validated/replayed; billing admission quarantined | ES IID 10252, NQ IID 261401, publisher 1 / XCME; no MBP-1 acquired |
| GLBX.MDP3 standard OG | definition, statistics/OI, quotes | Native acceptance blocked | Bounded selection/input joins implemented; no broad chain acquired |
| Broker XAUUSD / US500.cash / US100.cash | reviewed bid/ask and five-timeframe OHLC imports | Blocked: no authentic reviewed exports | Broker/server/spec/session/clock binding required |
| Native crypto | existing canonical candles/derivatives path | Blocked: no sufficient genuine inputs | CME futures never substitute for native exchange observations |
| MBP-10 / MBO | existing opt-in adapters | No acquisition | Disabled; MBO requires a separate question and cost review |
| Other feeds / CL | existing registry descriptors / typed CL normalization | No new acquisition | No unrelated feed, subscription or infrastructure added |

The October 5, 2026 15:00–15:15 UTC GC window contains 1,014 trade records, 15 one-minute
candles and one retained MBP-1 snapshot. Publisher 1 / instrument 41271 / GCZ6 / XCEC
identity and native USD-per-troy-ounce economics are reused from the accepted archive.
No display-factor rescaling or synthetic XAUUSD conversion occurs.

Captured executed volume is 1,470 contracts; three contracts have unknown aggressor
side. Full CVD therefore remains unavailable. VWAP/profile/POC, known-side delta,
visible best-quote quantities and unannualized sampled volatility retain their
actual captured scope and limitations. Visible size is not executed volume or intent.

Normalized GC SHA-256 remains
`2c9d0fb72a2a04ed5dc635010c652bc9aac05a562f737883445da7433ccc67ba`, matching Phase 4.
New versioned inputs, source/runtime hashes, immutable replay/normalized/indicator/
quality objects and two byte-identical outputs are in private Phase 5 acceptance.
The final replay hash and test evidence are recorded in the implementation report.

Original 69 valid Fibonacci assessments across 12 H1 episodes are preserved as
assessment findings. The frozen selector, 21 unresolved Class E minute gaps,
affected H4 gap and 4,049 zero-admission cutoff findings are unchanged. They are not
trade wins or a win rate, and do not impose a blanket rule on independent future scopes.

## Cost, cache and billing

Six requests were acquired with a total provider estimate of **$0.026535756885**.
The displayed credit balance decreased by approximately $0.02; rounded aggregate
account usage also increased by $0.02. Detailed account amounts remain private. Exact per-request usage/credit remains **unreconciled**.
Observed current cash balance remained zero. The shared research budget now records
the user-authorized available-credit ceiling; six $1 permits are reserved, not spent.
Existing GC cache and unknown original billing were preserved. New unsettled data
cannot pass the cached-bundle admission seam. The isolated replay makes no requests.

Authenticated Safari showed available credit, zero displayed current balance and
usage-based access with no limit. Details remain in a private account observation.
The displayed aggregate October usage does not prove individual request settlement.
Fresh exact-scope costs were obtained before each request. Internal historical T+1
access was checked against authenticated usage-based access and the provider policy;
no live license/subscription was created. Credit expiry was inspected as May 1, 2027.
The conservative permit total was far below unexpired credit. Exact billed amounts
remain unknown; estimates are not hard provider charge caps.

The metadata-only SDK command resolves exact ESZ6/NQZ6 IDs and quotes individual
requests without calling a download endpoint. Definitions cover October 5 00:00–15:00
UTC so a reviewed revision available before the sample can be selected; trades and
OHLCV use 15:00–15:15, or the explicit 15:00–15:20 alternative. Optional MBP-1 is quoted
only when explicitly selected. Cache inspection, native economics/licenses, a fresh
credit review, a bound credit-only ceiling and one-use receipts remain required.
After acceptance, the user authorized the needed ES/NQ downloads up to available
account credit. The derived ceiling and authorization are recorded privately;
fresh lower credit takes precedence. Exact quotes and request permits are pending.

```sh
.venv/bin/python -m monatise.research.institutional.phase5_metadata \
  --output private-reports/phase5-exact-metadata-proposal-next.json --prompt-key
```

The prompt keeps the credential hidden and in memory. Do not paste a key into chat
or a command argument. The initial credential-free invocation produced
`BLOCKED_SECURE_API_CREDENTIAL_UNAVAILABLE`. The user subsequently supplied the SDK
credential, and authenticated metadata/cost checks and the six downloads completed.
The credential is saved in an ignored owner-only private file; it is not in source.
The existing guarded acquisition and shared cost ledger remain the only billable
transport boundary. A browser estimate for a whole product is not an exact quote.

## Acquired index observations

| Contract | Native identity | Definition / candles / trades | Executed contracts | Unknown side | Missing minutes |
|---|---|---|---|---|---|
| ESZ6 | GLBX.MDP3 / 1 / 10252 / XCME | 1 / 15 / 9,094 | 31,453 | 0 | 0 |
| NQZ6 | GLBX.MDP3 / 1 / 261401 / XCME | 1 / 15 / 7,750 | 11,704 | 0 | 0 |

Both native multipliers (50 / 20 USD per index point), 0.25 ticks and expiry identities
were independently checked. The native tick-value field includes the display factor;
its division by that factor recovers USD tick value. DBN market prices remain in
conventional index points and are never multiplied/divided by the display factor.
See [Databento's contract-notional reference](https://databento.com/docs/examples/instrument-definitions/contract-notional)
and [CME's index economics](https://www.cmegroup.com/education/courses/introduction-to-equity-index-products/discover-equity-index-notional-value-and-price).

The captured-window VWAP/profile/POC, delta/CVD and volatility were calculated using
the existing indicator engine. They are partial diagnostics, not complete-session
measurements. MBP-1/depth/OI remain unavailable. Fifteen minutes cannot produce a
complete H1/H4 source. Broker candles/quotes and required primary index positioning
are absent, so canonical strategy evaluation remains blocked.

Two identical replays contain source/record/contract/provenance hashes and retained
billing quarantine. ES normalized SHA-256:
`d671c2e13fc16274b9f3682cef5d0c1878156fcacf38e29d9322cbbb714cf687`;
NQ: `d224d1120402f154e91cc73f1721967ee3197a01c3ff314738309dcaddcc1817`.
No successful paid call was repeated; the cached ES definition was reused after
the economics check was corrected. Raw archives and detailed diagnostics stay private.
