# Databento native CME live pilot

Date: 13 October 2026. Starting implementation commit:
`5f8e50ebfe1ab03e31edde7acd18bbf315915a39`, branch `codex/monatise-phase6`.

## Outcome

A separately authorized, 60-second read-only Standard capture received genuine
GLBX.MDP3 definitions, executions and best bid/ask updates for exact contracts
GCZ6, ESZ6 and NQZ6. All three schema replays completed, all native definitions
passed identity/economic validation, all quote books were usable, and the successful
capture had no reported transport, backpressure or native validation failure.
The three sealed journals independently passed SHA-256, framing/count/size and native
byte decode round-trip checks. Two fresh offline replays produced identical output.

| Exact contract | Accepted definitions | Executed-trade records | MBP-1 quote updates |
|---|---:|---:|---:|
| GCZ6 | 1 | 17 | 593 |
| ESZ6 | 1 | 57 | 2,440 |
| NQZ6 | 1 | 38 | 8,828 |
| Total | 3 | 112 | 11,861 |

These are observation counts, not signals, entries, completed trades or wins.
MBP-1 updates are quote events; they are not counted again as executed volume.
GC prices remain GC futures prices. No broker XAUUSD mapping was attempted.

Fresh combined context was observed during the capture. At final shutdown ES had
no execution within the configured ten-second freshness window. The final combined
context therefore remained `UNAVAILABLE` with `trades:10252` stale, despite fresh
usable quotes, completed schema replays and no quarantining fault. The freshness
threshold was preserved. This does not establish complete exchange continuity,
unattended reliability, authenticated time or production trading certification.

## Genuine issues found and corrected

The initial live attempt stopped and quarantined its files. The gateway actually
returns numeric subscription IDs mapped to raw exchange symbols, not only numeric
output symbols. `FeedState` now accepts that documented form only if it exactly
matches the independently reviewed contract. Different expiries, products, parent
symbols and continuous symbols still quarantine. Original quarantined evidence was
retained; it was not admitted or rewritten.

Some genuine provider receive timestamps were ahead of the original Mac capture
clock. Independent read-only Cloudflare and Apple SNTP diagnostics both indicated
approximately 0.2 seconds of local clock lag. No system clock or security setting was
changed. The successful attempt used an explicit operator-reviewed, source-hashed,
short-lived uncertainty interval, initially approximately 114.848–303.767 ms UTC
minus local clock, with a conservative 100 ppm drift allowance.

New `ClockReview` validation bounds the interval, source reference, duration and
drift. Original timestamps remain unchanged. UTC capture bounds are additional
research metadata; conservative freshness, future-record rejection and session end
checks use those bounds. Default behavior still rejects provider timestamps ahead
of the unreviewed local clock. Public SNTP responses are unauthenticated and do not
certify production timing. The first capture is still quarantined and no automatic
reconnection, recovery or retry was enabled.

## Integrity and reproducibility

| Schema | Original native frames including controls | Bytes | SHA-256 |
|---|---:|---:|---|
| definition | 23 | 7,401 | `b8a32cbfdb2238ad1b7895dc720437380d01721699b940638353205ef309ac0f` |
| trades | 117 | 7,977 | `cddc7522ec776f244788524ff871384164b63ee9bdec7036ae70b0b464602482` |
| mbp-1 | 11,866 | 1,092,469 | `b90a1e24815c2735a55eab745fc11a71bccf05e57f558d9f9dfe2eec0f1b9e26` |

Framed native journals preserve exact DBN record bytes and original capture clocks;
they are not standalone DBN archives. Source frames include controls and mappings,
so their counts differ from accepted market observations above. Licensed data,
clock samples, detailed quote/trade output, permits and account observations remain
private and excluded from Git. Only sanitized methodology and verification evidence
are published here.

Two independent offline replay output SHA-256 values match:
`64e376233f77fe81c017e736cc21f872009ed7238a3d203e8b81be8e1ffa32a1`.
The accepted normalization stream SHA-256 is
`72c2bf546c34f4c43417a524449c4335bd14b17ee402c6bb631d72b2c2472f16`.
The original first-attempt journals remain quarantined under their original hashes.

## Validation and operational boundaries

Added 25 offline regression cases for genuine numeric-to-raw mappings, contradictory
contract outputs, strict default clocks, reviewed timestamp bounds, source validation,
review expiry/drift, conservative freshness and uncertain session boundaries.
The live preparation suite now has 83 passing tests. The final complete repository
suite passed 2,315 tests, without provider calls or production credentials.
Source/report hashes are in the companion validation JSON.

The pilot requested only live schemas included in the active Standard plan and free
metadata lookups. There were zero historical time-series acquisitions. Expected
incremental live usage charges are zero under the existing subscription; this is
not a newly reconciled provider invoice. Prior historical billing quarantines were
not released. No plan upgrade or additional subscription was requested.

Both attempts used new reviewed one-use permits. Automatic retries were zero. All
pilot connections closed, with no background service or deployment. The legacy
Boolean live adapter remains disabled. Production trading, Telegram approvals,
FTMO/Exness/MT5 operations, the frozen H1 selector and GIL routing were not changed.

## Remaining work before unattended or production use

- Establish and validate sustained host synchronization and an appropriate trusted
  clock source. This five-minute research review is not an unattended clock service.
- Test an explicitly reviewed live disconnect/recovery case, sustained durability,
  session transitions and contract rollover. None is certified by one short capture.
- Review freshness policy for quiet execution streams against the actual intended
  research consumer; this pilot does not silently loosen the existing threshold.
- Complete broker-native synchronized inputs and canonical research certification
  before considering production use. Options/depth/MBO were not activated.
- Preserve the new private evidence in a separate authorized encrypted backup
  checkpoint; the original Phase 1–5 backup is unchanged.

References: [Databento live symbology and controls](https://databento.com/docs/api-reference-live/basics/connection-limits),
[Standard pricing](https://databento.com/pricing),
[CME session/holiday reference](https://www.cmegroup.com/trading-hours.html).
