from __future__ import annotations

import base64
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from solders.pubkey import Pubkey

DEXSCREENER_BASE = "https://api.dexscreener.com"
PUMP_FUN_COIN_BASE = "https://pump.fun/coin"
SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# Pump.fun program address and its BondingCurve account layout, sourced from
# the official IDL (github.com/pump-fun/pump-public-docs, idl/pump.json).
# Verified live against a real mint: PDA derivation + discriminator check +
# creator-field offset all matched. One getAccountInfo call per mint, no
# transaction history walking -- pump.fun tokens routinely rack up
# thousands of transactions within seconds of launch via sniper bots, so
# walking signature history back to genesis is not viable at any practical
# page budget.
PUMP_FUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
BONDING_CURVE_SEED = b"bonding-curve"
BONDING_CURVE_DISCRIMINATOR = bytes([23, 183, 248, 55, 96, 216, 172, 96])
# discriminator(8) + virtual_token_reserves(8) + virtual_quote_reserves(8) +
# real_token_reserves(8) + real_quote_reserves(8) + token_total_supply(8) +
# complete(1) = 49, then creator: pubkey (32 bytes).
BONDING_CURVE_CREATOR_OFFSET = 49


def _json_request(url: str, *, payload: dict | None = None, timeout: int = 12):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "Monatise-Memecoin-Radar/1.0",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"market data returned HTTP {error.code}") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"market data request failed: {error}") from error


def validate_solana_address(address: str) -> str:
    clean = str(address or "").strip()
    if not SOLANA_ADDRESS.fullmatch(clean):
        raise ValueError("enter a valid Solana token mint address")
    return clean


def _number(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _best_pair(pairs: list[dict]) -> dict:
    solana_pairs = [pair for pair in pairs if pair.get("chainId") == "solana"]
    if not solana_pairs:
        return {}
    return max(solana_pairs, key=lambda pair: _number((pair.get("liquidity") or {}).get("usd")))


def _is_pumpfun_token(address: str, pair: dict | None = None) -> bool:
    dex_id = str((pair or {}).get("dexId") or "").lower()
    return address.lower().endswith("pump") or "pump" in dex_id


def solana_mint_snapshot(address: str, rpc_url: str) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [address, {"encoding": "base64", "commitment": "confirmed"}],
    }
    response = _json_request(rpc_url, payload=payload)
    value = ((response or {}).get("result") or {}).get("value")
    if not isinstance(value, dict):
        return {"available": False, "reason": "mint account was not found on Solana"}
    encoded = (value.get("data") or [""])[0]
    try:
        raw = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return {"available": False, "reason": "mint account data could not be decoded"}
    if len(raw) < 82:
        return {"available": False, "reason": "account is not a standard Solana mint"}
    decimals = raw[44]
    supply = int.from_bytes(raw[36:44], "little")
    return {
        "available": True,
        "decimals": decimals,
        "freezeAuthorityActive": int.from_bytes(raw[46:50], "little") != 0,
        "initialized": raw[45] != 0,
        "mintAuthorityActive": int.from_bytes(raw[0:4], "little") != 0,
        "ownerProgram": value.get("owner"),
        "supply": supply,
        "uiSupply": supply / (10**decimals) if decimals <= 18 else None,
    }


def risk_assessment(pair: dict, mint: dict | None = None) -> dict:
    mint = mint or {}
    liquidity = _number((pair.get("liquidity") or {}).get("usd"))
    volume = _number((pair.get("volume") or {}).get("h24"))
    txns = pair.get("txns") or {}
    h24 = txns.get("h24") or {}
    trades = int(_number(h24.get("buys")) + _number(h24.get("sells")))
    created_ms = _number(pair.get("pairCreatedAt"))
    age_hours = max(0.0, (time.time() * 1000 - created_ms) / 3_600_000) if created_ms else None
    score = 100
    cautions: list[str] = []

    if liquidity <= 0:
        score -= 40
        cautions.append("Liquidity is unavailable.")
    elif liquidity < 50_000:
        score -= 45
        cautions.append("Executable liquidity is below $50k.")
    elif liquidity < 250_000:
        score -= 20
        cautions.append("Liquidity is below the preferred public-screening range.")

    if volume < 25_000:
        score -= 20
        cautions.append("24h volume is below $25k.")
    elif volume < 100_000:
        score -= 10
        cautions.append("24h volume is still thin.")

    if not created_ms:
        score -= 10
        cautions.append("Pool age is unavailable.")
    elif age_hours < 1:
        score -= 30
        cautions.append("Pool is less than one hour old.")
    elif age_hours < 24:
        score -= 18
        cautions.append("Pool is less than one day old.")
    elif age_hours < 168:
        score -= 6
        cautions.append("Pool is less than seven days old.")

    if trades < 50:
        score -= 10
        cautions.append("Fewer than 50 trades were reported in 24h.")
    if mint.get("mintAuthorityActive"):
        score -= 25
        cautions.append("Mint authority remains active.")
    if mint.get("freezeAuthorityActive"):
        score -= 30
        cautions.append("Freeze authority remains active.")
    if not mint.get("available", False):
        score -= 8
        cautions.append("Solana mint controls could not be verified.")

    score = max(0, min(100, score))
    label = "Screened" if score >= 70 else "Speculative" if score >= 45 else "High risk"
    return {
        "ageHours": round(age_hours, 1) if age_hours is not None else None,
        "cautions": cautions or ["No basic screening warnings were triggered; this is not a safety guarantee."],
        "label": label,
        "score": score,
        "trades24h": trades,
    }


def normalize_pair(pair: dict, *, profile: dict | None = None, mint: dict | None = None) -> dict:
    profile = profile or {}
    mint = mint or {}
    base_token = pair.get("baseToken") or {}
    address = str(base_token.get("address") or profile.get("tokenAddress") or "")
    assessment = risk_assessment(pair, mint)
    info = pair.get("info") or {}
    links = info.get("socials") or profile.get("links") or []
    return {
        "address": address,
        "chainId": pair.get("chainId"),
        "dexId": pair.get("dexId"),
        "fdv": pair.get("fdv"),
        "imageUrl": info.get("imageUrl") or profile.get("icon"),
        "isPumpFun": _is_pumpfun_token(address, pair),
        "liquidityUsd": _number((pair.get("liquidity") or {}).get("usd")),
        "marketCap": pair.get("marketCap"),
        "mint": mint,
        "name": base_token.get("name") or "Unknown token",
        "pairAddress": pair.get("pairAddress"),
        "pairCreatedAt": pair.get("pairCreatedAt"),
        "priceChange": pair.get("priceChange") or {},
        "priceUsd": _number(pair.get("priceUsd")),
        "profileUrl": profile.get("url"),
        "pumpFunUrl": f"{PUMP_FUN_COIN_BASE}/{address}" if address else None,
        "risk": assessment,
        "socials": links[:5] if isinstance(links, list) else [],
        "symbol": base_token.get("symbol") or "--",
        "transactions": pair.get("txns") or {},
        "url": pair.get("url"),
        "volume": pair.get("volume") or {},
    }


def resolve_creator(mint_address: str, rpc_url: str) -> str | None:
    """Creator lookup for a pump.fun mint via its on-chain bonding-curve
    account (one getAccountInfo call, no transaction history walking).

    Earlier versions of this walked the mint's transaction history back to
    its earliest signature and used the fee payer as a heuristic -- live
    testing showed that's not viable: pump.fun tokens routinely accumulate
    1000+ transactions within seconds of launch via sniper bots, so genesis
    is unreachable within any RPC page budget that respects the free public
    RPC's rate limits. Reading the bonding-curve account directly is a
    single, cheap, exact lookup instead, since pump.fun's own program
    already stores the creator's pubkey on-chain.
    """
    try:
        mint = Pubkey.from_string(mint_address)
    except ValueError:
        return None
    bonding_curve, _bump = Pubkey.find_program_address([BONDING_CURVE_SEED, bytes(mint)], PUMP_FUN_PROGRAM_ID)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [str(bonding_curve), {"encoding": "base64", "commitment": "confirmed"}],
    }
    try:
        response = _json_request(rpc_url, payload=payload)
    except RuntimeError:
        return None
    value = ((response or {}).get("result") or {}).get("value")
    if not isinstance(value, dict):
        return None
    encoded = (value.get("data") or [""])[0]
    try:
        raw = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None
    end = BONDING_CURVE_CREATOR_OFFSET + 32
    if len(raw) < end or raw[:8] != BONDING_CURVE_DISCRIMINATOR:
        return None
    creator_bytes = raw[BONDING_CURVE_CREATOR_OFFSET:end]
    if creator_bytes == bytes(32):
        # Older bonding-curve accounts predate pump.fun adding a creator
        # field to this layout; that byte range reads as 32 zero bytes,
        # which decodes to the System Program address rather than a real
        # creator wallet. Treat it the same as "unresolved".
        return None
    try:
        return str(Pubkey(creator_bytes))
    except ValueError:
        return None


def creator_leaderboard(tokens: list[dict], creators_by_address: dict[str, str | None], *, limit: int = 15) -> dict:
    """Groups already-screened tokens by their resolved creator and ranks
    creators by how many launches were observed in this window. This is
    NOT an all-time history -- it only reflects tokens discover_pumpfun
    surfaced just now, so a creator with one visible launch may well have
    others outside this window.
    """
    groups: dict[str, list[dict]] = {}
    for token in tokens:
        creator = creators_by_address.get(token.get("address"))
        if not creator:
            continue
        groups.setdefault(creator, []).append(token)

    creators = []
    for address, group_tokens in groups.items():
        scores = [_number(token.get("risk", {}).get("score")) for token in group_tokens]
        liquidity = [_number(token.get("liquidityUsd")) for token in group_tokens]
        high_risk = sum(1 for token in group_tokens if str(token.get("risk", {}).get("label")) == "High risk")
        creators.append({
            "address": address,
            "launchesObserved": len(group_tokens),
            "averageRiskScore": round(sum(scores) / len(scores), 1) if scores else None,
            "averageLiquidityUsd": round(sum(liquidity) / len(liquidity), 2) if liquidity else None,
            "highRiskCount": high_risk,
            "repeatLauncher": len(group_tokens) > 1,
            "tokens": [
                {"address": token.get("address"), "symbol": token.get("symbol"), "riskScore": token.get("risk", {}).get("score"), "riskLabel": token.get("risk", {}).get("label")}
                for token in group_tokens
            ],
        })
    creators.sort(key=lambda creator: creator["launchesObserved"], reverse=True)
    return {
        "creators": creators[:limit],
        "windowTokensScanned": len(tokens),
        "windowTokensWithResolvedCreator": sum(len(group) for group in groups.values()),
        "methodology": (
            "Creators ranked by number of pump.fun launches observed in the current "
            "discovery window only, not an all-time history -- a creator with one "
            "visible launch here may have others outside this window. Creator identity "
            "is read directly from each token's on-chain pump.fun bonding-curve "
            "account. A repeat launcher is not inherently good or bad -- serial "
            "token creation is also a common "
            "pattern in rug-pull operations. Review each launch individually."
        ),
        "source": "DEX Screener latest token profiles + Solana RPC creator resolution",
        "updatedAt": int(time.time()),
    }


def inspect_memecoin(address: str, rpc_url: str) -> dict:
    mint_address = validate_solana_address(address)
    pairs = _json_request(f"{DEXSCREENER_BASE}/token-pairs/v1/solana/{quote(mint_address)}")
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("no active Solana market was found for this mint")
    pair = _best_pair(pairs)
    mint = solana_mint_snapshot(mint_address, rpc_url)
    token = normalize_pair(pair, mint=mint)
    token["pairCount"] = len(pairs)
    token["source"] = "DEX Screener market data + Solana RPC mint inspection"
    return token


def discover_pumpfun(limit: int = 12) -> dict:
    requested = max(4, min(24, int(limit)))
    profiles = _json_request(f"{DEXSCREENER_BASE}/token-profiles/latest/v1")
    if not isinstance(profiles, list):
        profiles = []
    candidates = [
        profile
        for profile in profiles
        if profile.get("chainId") == "solana" and str(profile.get("tokenAddress") or "").lower().endswith("pump")
    ][:30]
    addresses = [str(profile.get("tokenAddress")) for profile in candidates]
    if not addresses:
        return {"tokens": [], "count": 0, "source": "DEX Screener latest profiles", "updatedAt": int(time.time())}
    pairs = _json_request(f"{DEXSCREENER_BASE}/tokens/v1/solana/{','.join(addresses)}")
    pairs = pairs if isinstance(pairs, list) else []
    profiles_by_address = {profile.get("tokenAddress"): profile for profile in candidates}
    best_by_address: dict[str, dict] = {}
    for pair in pairs:
        address = str((pair.get("baseToken") or {}).get("address") or "")
        current = best_by_address.get(address)
        if current is None or _number((pair.get("liquidity") or {}).get("usd")) > _number((current.get("liquidity") or {}).get("usd")):
            best_by_address[address] = pair
    tokens = [normalize_pair(pair, profile=profiles_by_address.get(address)) for address, pair in best_by_address.items()]
    tokens.sort(key=lambda token: (token["risk"]["score"], token["liquidityUsd"], _number((token["volume"] or {}).get("h24"))), reverse=True)
    return {
        "count": min(requested, len(tokens)),
        "methodology": "Pump.fun mint suffix candidates ranked by basic liquidity, activity and pool-age screening; paid boosts are not a quality signal.",
        "source": "DEX Screener latest token profiles and Solana market pairs",
        "tokens": tokens[:requested],
        "updatedAt": int(time.time()),
    }
