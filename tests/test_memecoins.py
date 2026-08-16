from __future__ import annotations

import pytest

import monatise.adapters.memecoins as memecoins


PUMP_MINT = "11111111111111111111111111111111pump"
# A real, base58-valid 32-byte mint address -- PUMP_MINT above is only a
# string fixture for suffix/regex tests, not a decodable pubkey, which the
# on-chain PDA derivation in resolve_creator needs.
VALID_PUMP_MINT = "8mtTLauYuiCmmao3tuaLNMJ7B9TN5t1VU4YeVdrWpump"


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


CREATOR_PUBKEY = "tXBoC4cg7DEQXBtKhrXqmQUmj8ddqV6GYmbs58acePK"


def fake_bonding_curve_account(creator: str = CREATOR_PUBKEY, *, complete: bool = True, corrupt_discriminator: bool = False) -> str:
    import base64

    from solders.pubkey import Pubkey

    discriminator = bytes([1, 2, 3, 4, 5, 6, 7, 8]) if corrupt_discriminator else memecoins.BONDING_CURVE_DISCRIMINATOR
    raw = (
        discriminator
        + (0).to_bytes(8, "little") * 5  # virtual/real reserves + total supply, values don't matter for this
        + bytes([1 if complete else 0])
        + bytes(Pubkey.from_string(creator))
        + bytes([0, 0])  # is_mayhem_mode, is_cashback_coin
        + bytes(Pubkey.from_string(creator))  # quote_mint, value doesn't matter here
    )
    return base64.b64encode(raw).decode()


def test_resolve_creator_reads_the_bonding_curve_account(monkeypatch) -> None:  # noqa: ANN001
    calls: list[dict] = []

    def fake_request(url: str, *, payload: dict, **_kwargs):  # noqa: ANN202
        calls.append(payload)
        assert payload["method"] == "getAccountInfo"
        return {"result": {"value": {"data": [fake_bonding_curve_account(), "base64"]}}}

    monkeypatch.setattr(memecoins, "_json_request", fake_request)
    creator = memecoins.resolve_creator(VALID_PUMP_MINT, "https://rpc.example")
    assert creator == CREATOR_PUBKEY
    assert len(calls) == 1


def test_resolve_creator_treats_an_all_zero_creator_field_as_unresolved(monkeypatch) -> None:  # noqa: ANN001
    # Bonding-curve accounts predating pump.fun's addition of a creator
    # field to this layout read as 32 zero bytes there, which decodes to
    # the System Program address ("111...1") rather than a real wallet --
    # verified live against a graduated token. Must resolve to None, not a
    # bogus "creator".
    zero_creator = "11111111111111111111111111111111"
    monkeypatch.setattr(
        memecoins,
        "_json_request",
        lambda url, **_kwargs: {"result": {"value": {"data": [fake_bonding_curve_account(zero_creator), "base64"]}}},
    )
    assert memecoins.resolve_creator(VALID_PUMP_MINT, "https://rpc.example") is None


def test_resolve_creator_derives_the_correct_bonding_curve_pda(monkeypatch) -> None:  # noqa: ANN001
    from solders.pubkey import Pubkey

    seen_addresses: list[str] = []

    def fake_request(url: str, *, payload: dict, **_kwargs):  # noqa: ANN202
        seen_addresses.append(payload["params"][0])
        return {"result": {"value": {"data": [fake_bonding_curve_account(), "base64"]}}}

    monkeypatch.setattr(memecoins, "_json_request", fake_request)
    memecoins.resolve_creator(VALID_PUMP_MINT, "https://rpc.example")
    expected_pda, _bump = Pubkey.find_program_address(
        [memecoins.BONDING_CURVE_SEED, bytes(Pubkey.from_string(VALID_PUMP_MINT))], memecoins.PUMP_FUN_PROGRAM_ID
    )
    assert seen_addresses == [str(expected_pda)]


def test_resolve_creator_rejects_an_account_with_the_wrong_discriminator(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        memecoins,
        "_json_request",
        lambda url, **_kwargs: {"result": {"value": {"data": [fake_bonding_curve_account(corrupt_discriminator=True), "base64"]}}},
    )
    assert memecoins.resolve_creator(VALID_PUMP_MINT, "https://rpc.example") is None


def test_resolve_creator_handles_a_missing_account(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(memecoins, "_json_request", lambda url, **_kwargs: {"result": {"value": None}})
    assert memecoins.resolve_creator(VALID_PUMP_MINT, "https://rpc.example") is None


def test_resolve_creator_rejects_an_invalid_mint_address() -> None:
    assert memecoins.resolve_creator("not-a-real-address", "https://rpc.example") is None


def test_resolve_creator_fails_closed_on_rpc_error(monkeypatch) -> None:  # noqa: ANN001
    def boom(url: str, **_kwargs):  # noqa: ANN202
        raise RuntimeError("rpc unavailable")

    monkeypatch.setattr(memecoins, "_json_request", boom)
    assert memecoins.resolve_creator(VALID_PUMP_MINT, "https://rpc.example") is None


def test_creator_leaderboard_ranks_by_launches_observed_in_window() -> None:
    def token(address: str, score: int, label: str, liquidity: float) -> dict:
        return {"address": address, "symbol": "MEME", "liquidityUsd": liquidity, "risk": {"score": score, "label": label}}

    tokens = [
        token("mintA", 20, "High risk", 5_000),
        token("mintB", 25, "High risk", 6_000),
        token("mintC", 80, "Screened", 300_000),
    ]
    creators_by_address = {"mintA": "serial-creator", "mintB": "serial-creator", "mintC": "one-off-creator"}

    leaderboard = memecoins.creator_leaderboard(tokens, creators_by_address, limit=15)

    assert leaderboard["windowTokensScanned"] == 3
    assert leaderboard["windowTokensWithResolvedCreator"] == 3
    top = leaderboard["creators"][0]
    assert top["address"] == "serial-creator"
    assert top["launchesObserved"] == 2
    assert top["repeatLauncher"] is True
    assert top["highRiskCount"] == 2
    assert leaderboard["creators"][1]["address"] == "one-off-creator"
    assert leaderboard["creators"][1]["repeatLauncher"] is False


def test_creator_leaderboard_skips_tokens_with_no_resolved_creator() -> None:
    tokens = [{"address": "mintA", "symbol": "MEME", "liquidityUsd": 1_000, "risk": {"score": 10, "label": "High risk"}}]
    leaderboard = memecoins.creator_leaderboard(tokens, {"mintA": None}, limit=15)
    assert leaderboard["creators"] == []
    assert leaderboard["windowTokensWithResolvedCreator"] == 0
