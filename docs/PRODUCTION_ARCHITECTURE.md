# Monatise Live production architecture

Status: canonical production system

- Production repository: `monatise-live`
- Production host: Render
- Primary signal-quality data API: CoinGlass
- Market data: CoinGlass only; analysis fails closed when CoinGlass is unavailable
- Order execution: globally disabled
- Weekend trade generation: disabled
- Payments: no Stripe or USDC payment flow
- Session gating: no London-session gate; economic-release safety remains
- Supported clients: web dashboard and Telegram/OpenClaw analysis skills

Cloudflare, Android, AWS App Runner, Intelligence Terminal, Stripe, USDC payment,
and earlier Monatise prototypes are historical work. They are not production,
must not receive deployment credentials, and must not have scheduled jobs.

On-demand CoinGlass analysis is a separate read-only branch. It resolves a
requested base through `supported-coins`, `supported-exchange-pairs`, and
`pairs-markets`, runs asset-agnostic
engines, and applies strict history, freshness, liquidity, price-agreement,
derivatives-shape, and confirmation gates. It does not mutate the scheduled
BTC/ETH/SOL universe or reach notification, execution, configuration, or deploys.
