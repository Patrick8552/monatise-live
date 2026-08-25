# FTMO XAU/USD Telegram price mismatch

Date: 2026-08-25

## Evidence recovered

The user's logged-in Telegram history contains a Monatise publication displayed
at `01:34` (the screenshot does not expose the date or Telegram display
timezone) with the following exact fields:

- Header: `MONATISE FTMO FUTURES SCANNER`
- Market: `Gold`
- FTMO Symbol: `XAU/USD`
- Underlying Futures: `GC`
- Micro Futures: `MGC`
- Direction: `LONG`
- Entry: `4,745.45`
- Invalidation: `4,627.59339082`
- Target: `5,000`
- Reward/risk: `2.16`
- Source: `FlashAlpha`

The publication itself therefore confirms that COMEX futures-derived numbers
were presented under the FTMO XAU/USD CFD label.

The canonical registry identifies `XAU/USD` as an FTMO spot CFD but maps its
external context provider to COMEX gold futures roots `GC` and `MGC`.

The production futures scanner requests FlashAlpha context for `GC=F`, then
passes FlashAlpha's `underlying_price`, gamma flip, and futures walls into
`build_flashalpha_futures_analysis()`. That function previously promoted those
futures values directly to `entry`, `stop_loss`, and `target`. The Telegram
formatter then displayed them as `Entry`, `Invalidation`, and `Target` for the
FTMO `XAU/USD` CFD.

This creates a deterministic product/feed mismatch:

- Analytical market: exchange-traded COMEX `GC` futures.
- Telegram instrument label: FTMO `XAU/USD` spot CFD.
- Previous executable-looking price levels: COMEX futures-derived.
- Required execution-price authority: the authenticated FTMO platform quote.

The codebase did not contain an FTMO account adapter, FTMO Bid/Ask ingestion,
or an FTMO symbol-specification service. Consequently, it could not validate
the displayed levels against the actual FTMO market.

## Historical evidence still missing

No corresponding production audit/publication record was available in the
local repository. The complete UTC timestamp, contemporaneous FTMO Bid/Ask,
spread, and FTMO candle therefore remain unverified. They must not be
reconstructed and presented as facts.

Once a read-only FTMO adapter is connected, the investigation should query the
durable Telegram/audit records and compare the original publication with FTMO
historical candles at the normalized UTC timestamp.

## Immediate containment

Futures-linked Telegram messages no longer expose an external provider's
entry, stop, or target as an FTMO signal. They are explicitly marked as
external context, and FTMO executable levels are withheld until a fresh FTMO
platform quote is available.

The new FTMO execution boundary is disabled by default and requires explicit
platform plus account identity configuration. It rejects stale quotes, closed
markets, excessive spreads, symbol mismatches, material external/FTMO price
deviation, invalid stops, insufficient loss capacity, excessive open risk, and
position sizes that cannot be normalized from FTMO specifications.

## Platform determination

MetaTrader 5 is installed on the user's Mac, but it was not running during the
read-only inspection and no FTMO account/server identity was exposed. The
repository and deployment configuration also do not identify whether the
actual account uses cTrader, MT4, or MT5. This must be confirmed before a real
adapter can be selected.

- cTrader: prefer its official Open API and OAuth flow.
- MT4/MT5: use a minimal terminal-side EA/bridge beside the authenticated FTMO
  terminal; do not scrape or click the browser interface.

FTMO's current documentation:

- <https://ftmo.com/en/trading-platforms/>
- <https://ftmo.com/en/faq/what-are-the-account-specifications/>
- <https://ftmo.com/en/faq/which-instruments-can-i-trade-and-what-strategies-am-i-allowed-to-use/>

## Remaining gate

Implementation can proceed through deterministic shadow tests without account
credentials. Live FTMO price alignment and demo order reconciliation require
the platform type, approved Free Trial/demo account identity, and a credential
flow configured through secrets rather than source code or chat.
