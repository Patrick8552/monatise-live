"""Bounded captured-window metrics; never a continuity or dealer certificate."""
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal, localcontext
from math import log, sqrt

from monatise.research.databento.advanced import Observation, book_metrics
from .models import MarketObservation, digest, number


def unique(observations, *, schema, start_ns, end_ns, capacity=50000):
    if not start_ns < end_ns or not 1 <= capacity <= 100000:
        raise ValueError("bounded_indicator_scope_required")
    positions, ordered, identity, kind, previous = {}, [], None, None, None
    for value in observations:
        if not isinstance(value, MarketObservation) or value.schema != schema:
            raise ValueError("indicator_schema_mismatch")
        clock = value.receive_ns if value.receive_ns is not None else value.event_ns
        if not start_ns <= clock < end_ns:
            raise ValueError("indicator_outside_declared_scope")
        if identity is not None and (value.contract != identity or value.source.evidence_kind != kind):
            raise ValueError("mixed_contract_or_evidence_kind")
        identity, kind = value.contract, value.source.evidence_kind
        prior = positions.get(value.source.position)
        signature = digest(value)
        if prior is not None:
            if prior != signature:
                raise ValueError("native_source_position_revision")
            continue
        if len(positions) >= capacity:
            raise ValueError("indicator_capacity_exceeded")
        if previous is not None and clock < previous:
            raise ValueError("unordered_native_observations")
        previous = clock
        positions[value.source.position] = signature
        ordered.append(value)
    return tuple(ordered)


def provenance(values, *, start_ns, end_ns, session_reference):
    if not session_reference:
        raise ValueError("declared_session_reference_required")
    return dict(input_sha256=digest(values), count=len(values), start_ns=start_ns, end_ns=end_ns,
                session_reference=session_reference, complete_exchange_continuity=False,
                evidence_kind=values[0].source.evidence_kind if values else "UNAVAILABLE",
                identity=values[0].contract.identity if values else None,
                source_archives=sorted({v.source.archive_sha256 for v in values}),
                availability_basis="RETROSPECTIVE_LOCAL_ADMISSION", execution_eligible=False)


def trade_indicators(observations, *, start_ns, end_ns, session_reference, capacity=50000):
    values = unique(observations, schema="trades", start_ns=start_ns, end_ns=end_ns, capacity=capacity)
    inputs = provenance(values, start_ns=start_ns, end_ns=end_ns, session_reference=session_reference)
    if not values:
        return dict(status="UNAVAILABLE", reason="no_executed_observations", inputs=inputs,
                    vwap=None, profile=[], point_of_control=None, cvd=None)
    profile, volume, buy, sell, unknown, weighted = defaultdict(int), 0, 0, 0, 0, Decimal(0)
    cvd_path = []
    with localcontext() as ctx:
        ctx.prec = 40
        for v in values:
            p, size, side = v.payload
            p = number(p)
            if type(size) is not int or size <= 0 or side not in {"BUY", "SELL", None}:
                raise ValueError("executed_quantity_or_side_invalid")
            profile[p] += size
            volume += size
            weighted += p*size
            if side == "BUY": buy += size
            elif side == "SELL": sell += size
            else: unknown += size
            cvd_path.append((v.receive_ns, buy-sell))
        vwap = weighted/volume
    poc = min(profile, key=lambda p:(-profile[p], p))
    return dict(status="PARTIAL", methodology="executed-price-volume-exact-tick-profile-v1",
        inputs=inputs, vwap=str(vwap), executed_contracts=volume,
        profile=[(str(p), profile[p]) for p in sorted(profile)], point_of_control=str(poc),
        point_of_control_tie_rule="lowest_native_price", buy_contracts=buy, sell_contracts=sell,
        unknown_side_contracts=unknown, known_side_delta=buy-sell,
        cvd=buy-sell if not unknown else None, cvd_path=cvd_path if not unknown else None,
        cvd_status="CAPTURED_KNOWN_SIDES_ONLY" if not unknown else "UNAVAILABLE_UNKNOWN_AGGRESSOR",
        limitations=["Only captured executions in the declared window; no missing-activity certification.",
                     "Exact-price profile, not a complete-session profile unless independently established.",
                     "Quantities are contracts; unknown aggressors are never inferred."])


def book_indicator(value):
    if not isinstance(value, MarketObservation) or value.schema not in {"mbp-1", "mbp-10"}:
        raise ValueError("native_book_observation_required")
    m = value.contract.metadata
    original = Observation(m.dataset, value.schema, m.namespace, m.publisher_id, m.instrument_id,
        m.raw_symbol, value.event_ns, value.receive_ns, value.sequence, value.flags, "N",
        value.source.record_sha256, value.payload, m.definition_sha256)
    return {**book_metrics(original), "status":"PARTIAL", "inputs":encode_source(value),
            "limitation":"One captured visible snapshot; neither execution volume nor institutional intent."}


def encode_source(value):
    return dict(source=asdict(value.source), identity=value.contract.identity,
                definition_sha256=value.contract.metadata.definition_sha256,
                event_ns=value.event_ns, receive_ns=value.receive_ns,
                input_sha256=digest(value), complete_exchange_continuity=False)


def volatility(observations, *, start_ns, end_ns, session_reference):
    values = unique(observations, schema="ohlcv-1m", start_ns=start_ns, end_ns=end_ns)
    inputs = provenance(values, start_ns=start_ns, end_ns=end_ns, session_reference=session_reference)
    if (len(values) < 3 or any(v.payload[1]>end_ns for v in values)
            or any(b.payload[0] != a.payload[1] for a,b in zip(values, values[1:]))):
        return dict(status="UNAVAILABLE", reason="insufficient_or_noncontiguous_prices", inputs=inputs, value=None)
    prices = [v.payload[5] for v in values]
    if min(prices) <= 0:
        return dict(status="UNAVAILABLE", reason="log_returns_require_positive_prices", inputs=inputs, value=None)
    returns = [log(b/a) for a,b in zip(prices, prices[1:])]
    mean = sum(returns)/len(returns)
    stdev = sqrt(sum((r-mean)**2 for r in returns)/(len(returns)-1))
    return dict(status="PARTIAL", value=format(stdev, ".16g"), inputs=inputs,
                methodology="sample-stdev-log-close-returns-1m-v1", annualized=False,
                limitation="Captured contiguous native minutes only; no imputed prices or annualization.")


def open_interest_change(previous, current, *, cutoff_ns):
    if (any(v.schema != "statistics" for v in (previous, current))
            or previous.contract != current.contract
            or previous.source.evidence_kind != current.source.evidence_kind
            or any(v.payload[0] != "OPEN_INTEREST" for v in (previous, current))
            or not previous.payload[2] < current.payload[2]
            or not previous.receive_ns < current.receive_ns <= cutoff_ns
            or max(v.source.admission_ns for v in (previous,current)) > cutoff_ns):
        raise ValueError("published_oi_identity_order_or_availability_invalid")
    return dict(status="AVAILABLE", change_contracts=current.payload[1]-previous.payload[1],
                reference_ns=current.payload[2], publication_ns=current.receive_ns,
                inputs=[encode_source(previous), encode_source(current)],
                methodology="difference-of-distinct-published-oi-reference-periods-v1",
                signed_dealer_position=None, execution_eligible=False)
