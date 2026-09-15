"""Read-only independent options evidence; never uses indicative quotes.

The collector is capability discovery, not a certificate. Alpaca does not supply
all of this reconstruction model's dated carry/expiry inputs. No defaults are
manufactured for them. A complete authorized source must supply those inputs.
"""

import threading
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlencode

from monatise.application.gamma_reconstruction import GammaQualityError


class AlpacaGammaProvider:
    name = "alpaca"

    def __init__(self, market_data):
        self.market_data = market_data
        self._denied_until = 0.0
        self._lock = threading.Lock()

    def chain(self, symbol):
        # Share the entitlement backoff across symbols in a scanner cycle.
        with self._lock:
            if monotonic() < self._denied_until:
                raise GammaQualityError("opra_access_denied_backoff")
            started = monotonic()
            try:
                snapshots = self._pages(
                    lambda query: self.market_data._get(
                        f"/v1beta1/options/snapshots/{symbol}", query
                    ),
                    {"feed": "opra", "limit": 1000},
                    "snapshots",
                    started,
                )
            except Exception as exc:
                if "Alpaca HTTP 403" in str(exc):
                    self._denied_until = monotonic() + 300
                    raise GammaQualityError("opra_access_denied") from exc
                if isinstance(exc, GammaQualityError):
                    raise
                raise GammaQualityError("options_provider_unavailable") from exc
            today = datetime.now(timezone.utc).date().isoformat()
            contracts = self._pages(
                lambda query: self.market_data._get_absolute(
                    self.market_data.trading_base_url
                    + "/v2/options/contracts?"
                    + urlencode(query)
                ),
                {
                    "underlying_symbols": symbol,
                    "expiration_date_gte": today,
                    "expiration_date_lte": "2099-12-31",
                    "status": "active",
                    "limit": 1000,
                },
                "option_contracts",
                started,
            )
            if not contracts or any(
                row.get("symbol") not in snapshots
                for row in contracts
                if str(row.get("open_interest")) != "0"
            ):
                raise GammaQualityError("chain_snapshots_incomplete")
            # Verified pricing inputs are intentionally mandatory. Listing OI
            # and a snapshot is not equivalent to an independently repriced book.
            raise GammaQualityError("verified_pricing_inputs_unavailable")

    @staticmethod
    def _pages(fetch, query, field, started):
        result = {} if field == "snapshots" else []
        seen_tokens, seen_symbols = set(), set()
        for _ in range(5):
            if monotonic() - started > 15:
                raise GammaQualityError("chain_collection_budget")
            payload = fetch(query)
            if not isinstance(payload, dict) or not isinstance(
                payload.get(field), type(result)
            ):
                raise GammaQualityError("chain_payload_invalid")
            rows = payload[field]
            symbols = (
                list(rows)
                if isinstance(rows, dict)
                else [row.get("symbol") for row in rows if isinstance(row, dict)]
            )
            if (
                len(symbols) != len(rows)
                or any(
                    not isinstance(s, str) or not s or s in seen_symbols
                    for s in symbols
                )
                or len(set(symbols)) != len(symbols)
            ):
                raise GammaQualityError("chain_duplicate_or_malformed_contract")
            seen_symbols.update(symbols)
            if isinstance(result, dict):
                result.update(rows)
            else:
                result.extend(rows)
            if len(result) > 4000:
                raise GammaQualityError("chain_collection_budget")
            token = payload.get("next_page_token")
            if token is None:
                return result
            if not isinstance(token, str) or not token or token in seen_tokens:
                raise GammaQualityError("chain_pagination_invalid")
            seen_tokens.add(token)
            query = {**query, "page_token": token}
        raise GammaQualityError("chain_pagination_incomplete")
