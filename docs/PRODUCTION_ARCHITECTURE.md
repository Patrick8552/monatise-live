# Monatise Live production architecture

Status: canonical production system

- Production repository: `monatise-live`
- Production host: Render
- Primary signal-quality data API: CoinGlass
- Fallback when CoinGlass is unavailable: Hyperliquid public market data
- Order execution: globally disabled
- Weekend trade generation: disabled
- Payments: no Stripe or USDC payment flow
- Session gating: no London-session gate; economic-release safety remains
- Supported clients: web dashboard and Telegram/OpenClaw analysis skills

Cloudflare, Android, AWS App Runner, Intelligence Terminal, Stripe, USDC payment,
and earlier Monatise prototypes are historical work. They are not production,
must not receive deployment credentials, and must not have scheduled jobs.
