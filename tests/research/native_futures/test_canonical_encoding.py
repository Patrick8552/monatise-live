"""Canonical byte parity when avoiding dataclass deep-copy traversal."""
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json

from monatise.research.institutional.models import encode, digest


def reference(value):
    if is_dataclass(value):
        return reference(asdict(value))
    if isinstance(value, dict):
        return {str(k): reference(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [reference(v) for v in value]
    if isinstance(value, (Decimal, datetime)):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    return value


def test_nested_canonical_encoding_and_hash_are_byte_exact_without_mutation():
    @dataclass(frozen=True)
    class Evidence:
        at: datetime
        prices: tuple
        metadata: dict
    x = Evidence(datetime(2026, 10, 16, tzinfo=UTC), (Decimal('1.000'), None, -3),
                 {1: [True, Decimal('0.1')]})
    value = {1: (x, x), 2: [], 3: {'nested': x}}
    expected = json.dumps(reference(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    assert json.dumps(encode(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode() == expected
    assert digest(value) == hashlib.sha256(expected).hexdigest()
    assert x.metadata == {1: [True, Decimal('0.1')]}


def test_native_bar_and_observation_hashes_match_original_encoder():
    from tests.research.native_futures.test_chart import service
    service_, pipeline, contract = service()
    values = [contract, tuple(pipeline.gates[contract.metadata.instrument_id].lineage_observations()), pipeline.bars]
    for value in values:
        encoded = reference(value)
        assert encode(value) == encoded
        expected = json.dumps(encoded, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        assert digest(value) == hashlib.sha256(expected).hexdigest()
