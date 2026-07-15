from __future__ import annotations

import pytest

import monatise.adapters.memecoins as memecoins


PUMP_MINT = "11111111111111111111111111111111pump"


def sample_pair(*, liquidity: float = 400_000, volume: float = 200_000, created_at: int | None = None) -> dict:
    return {
        "baseToken": {"address": PUMP_MINT, "name": "Public Meme", "symbol": "MEME"},
        "chainId": "solana",
        "dexId": "pumpswap",
        "liquidity": {"usd": liquidity},
        "pairAddress": "pair-address",
        "pairCreatedAt": created_at or 1_700_000_000_000,
        "priceChange": {"h1": 4, "h24": 18},
        "priceUsd": "0.0042",
        "txns": {"h24": {"buys": 400, "sells": 300}},
        "url": "https://dexscreener.com/solana/pair-address",
        "volume": {"h24": volume},
    }


def test_validate_solana_address_rejects_ticker_and_url() -> None:
    with pytest.raises(ValueError, match="valid Solana token mint"):
        memecoins.validate_solana_address("MEME")
    with pytest.raises(ValueError, match="valid Solana token mint"):
        memecoins.validate_solana_address("https://pump.fun/coin/token")


def test_risk_assessment_penalizes_authorities_and_thin_market() -> None:
    risky = memecoins.risk_assessment(
        sample_pair(liquidity=20_000, volume=10_000, created_at=int(memecoins.time.time() * 1000)),
        {"available": True, "mintAuthorityActive": True, "freezeAuthorityActive": True},
    )
    assert risky["label"] == "High risk"
    assert risky["score"] < 30
    assert any("Mint authority" in caution for caution in risky["cautions"])
    assert any("Freeze authority" in caution for caution in risky["cautions"])


def test_normalize_pair_marks_pumpfun_and_exposes_public_links() -> None:
    token = memecoins.normalize_pair(
        sample_pair(),
        mint={"available": True, "mintAuthorityActive": False, "freezeAuthorityActive": False},
    )
    assert token["isPumpFun"] is True
    assert token["pumpFunUrl"].endswith(PUMP_MINT)
    assert token["symbol"] == "MEME"
    assert token["risk"]["score"] >= 70


def test_discovery_deduplicates_pairs_and_uses_deepest_liquidity(monkeypatch) -> None:  # noqa: ANN001
    profiles = [{"chainId": "solana", "tokenAddress": PUMP_MINT, "url": "https://dexscreener.com"}]
    pairs = [sample_pair(liquidity=80_000), sample_pair(liquidity=600_000)]

    def fake_request(url: str, **_kwargs):  # noqa: ANN202
        return profiles if "token-profiles" in url else pairs

    monkeypatch.setattr(memecoins, "_json_request", fake_request)
    payload = memecoins.discover_pumpfun(12)

    assert payload["count"] == 1
    assert payload["tokens"][0]["liquidityUsd"] == 600_000
    assert "paid boosts" in payload["methodology"]
