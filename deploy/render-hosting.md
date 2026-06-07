# Hosting Monatise On Render

Render is the active hosting target for Monatise. The included `render.yaml`
deploys the Docker web service in `live` + `mainnet` mode with small risk caps.
Users log in and save their own Hyperliquid API wallet credentials in the
dashboard before starting the trading loop.

## Before Deploying

- Confirm `python3 -m pytest` passes locally or in GitHub Actions before
  treating a push as release-ready.
- Create a user in the Monatise dashboard after deploy.
- Save that user's Hyperliquid account address and API wallet private key in the
  dashboard.
- Review the risk values in `render.yaml` before increasing any limits.

## Deploy

1. Push this project to GitHub.
2. In the Render Dashboard, choose **Blueprints** and connect the repository.
3. Render will detect `render.yaml`.
4. Create the Blueprint and wait for the service to deploy.
5. Confirm the public health check returns `{"ok": true}`:

```bash
curl https://your-service.onrender.com/api/health
```

The service starts in live mainnet mode with real-order gates enabled and small
risk caps. It can place exchange orders only after a logged-in user saves
Hyperliquid credentials and presses **Start**.

## Dashboard Access

Open the Render service URL, register or log in, save Hyperliquid credentials,
and use the Real-money desk controls.

For API calls:

```bash
curl -b cookies.txt -c cookies.txt https://your-service.onrender.com/api/status
```

Start live trading:

```bash
curl -X POST -b cookies.txt -c cookies.txt https://your-service.onrender.com/api/start
```

Stop live trading:

```bash
curl -X POST -b cookies.txt -c cookies.txt https://your-service.onrender.com/api/stop
```
