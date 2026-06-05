# Hosting Monatise On Render

Render can host Monatise as a Docker web service. The included `render.yaml`
keeps secret values out of the repository and prompts for them during Blueprint
creation.

## Before Deploying

- Use the Hyperliquid main account address for `HYPERLIQUID_ACCOUNT_ADDRESS`.
- Use the API wallet private key for `HYPERLIQUID_SECRET_KEY`.
- Create a long random `MONATISE_CONTROL_TOKEN`; the dashboard needs this token
  before it can read status or start/stop live trading.
- Review the risk values in `render.yaml` before creating the service.

## Deploy

1. Push this project to a GitHub or GitLab repository.
2. In the Render Dashboard, choose **Blueprints** and connect the repository.
3. Render will detect `render.yaml`.
4. Enter these prompted secret values:
   - `MONATISE_CONTROL_TOKEN`
   - `HYPERLIQUID_ACCOUNT_ADDRESS`
   - `HYPERLIQUID_SECRET_KEY`
5. Create the Blueprint and wait for the service to deploy.

The service starts in live mainnet mode with real-order gates enabled. The
trading loop still starts only after you press **Start** in the dashboard or
POST `/api/start` with the control token.

## Dashboard Access

Open the Render service URL. When prompted, enter the same
`MONATISE_CONTROL_TOKEN` you set in Render.

For API calls:

```bash
curl -H "Authorization: Bearer $MONATISE_CONTROL_TOKEN" \
  https://your-service.onrender.com/api/status
```

Start live trading:

```bash
curl -X POST -H "Authorization: Bearer $MONATISE_CONTROL_TOKEN" \
  https://your-service.onrender.com/api/start
```

Stop live trading:

```bash
curl -X POST -H "Authorization: Bearer $MONATISE_CONTROL_TOKEN" \
  https://your-service.onrender.com/api/stop
```
