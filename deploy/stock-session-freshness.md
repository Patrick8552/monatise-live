# Stock candle freshness

Stocks retain the shared hierarchy: 4h context, 1h analysis, 15m setup/stop,
5m confirmation and 1m entry. Their calendar semantics differ from 24/7 crypto.

Before requesting candles, the stock boundary obtains Alpaca's exchange calendar
over the same history window as the intraday bars. It validates calendar rows,
uses America/New_York for session dates and requires the current regular session
to be open. The session is checked again after provider responses arrive.

Freshness means the latest expected completed regular-session bar is present.
The expected timestamp is computed independently of returned candles. Overnight,
weekend and holiday closures create no expected regular-session bars; a missing
bar during a session cannot be hidden by these closures or by a newer forming bar.

Existing Alpaca UTC bucket timestamps and OHLCV are preserved. Only intervals
overlapping a verified regular session enter the stock hierarchy. Buckets are not
rebinned at 09:30 or shortened at an early close. In particular, a bucket that
overlaps an early close must still reach its nominal provider interval end and
the configured close buffer, because its aggregate can include extended trades.
The two independent matching observations required for finalization remain.

`candle_diagnostics` reports the expected open/close, latest closed open, latest
received open, calendar coverage, counts and close buffer. Scanner audit records
retain these fields. `4h_expected_closed_candle_missing` identifies an absent
expected bar; it must not be replaced with a quote or synthetic zero-volume bar.
An empty, malformed or inconsistent calendar fails closed. IEX can omit intervals
without qualifying trades; absent required evidence still blocks the setup.

This change does not extend existing signal/approval expiries or reopen a closed
exchange. Gamma certification/source freshness, coverage, strategy confirmation,
observed-price/entry-zone separation, broker Bid/Ask validation and risk gates
remain independent requirements. Crypto and broker-sourced index freshness keep
their existing behavior.

Regression coverage includes the SNOW morning case, overnight and holiday/weekend
carry-forward, daylight saving, early closes, market opening, forming bars, missing
expected bars, delayed evidence, timestamp corruption and unchanged downstream
risk/approval behavior.

Provider references: [calendar endpoint](https://docs.alpaca.markets/us/v1.1/reference/getcalendar-1),
[bar aggregation rules](https://docs.alpaca.markets/us/docs/market-data-faq).
