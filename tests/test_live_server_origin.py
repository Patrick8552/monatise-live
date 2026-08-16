from __future__ import annotations

from types import SimpleNamespace

from monatise.live.server import MonatiseHandler


def handler(headers: dict[str, str]) -> SimpleNamespace:
    # _valid_request_origin only touches self.headers.get(...); a plain
    # dict already supports .get(key, default) the same way the real
    # http.server headers object does for simple lookups.
    return SimpleNamespace(headers=headers)


def test_missing_origin_and_referer_is_allowed() -> None:
    assert MonatiseHandler._valid_request_origin(handler({})) is True


def test_matching_host_is_allowed() -> None:
    request = handler({"Origin": "https://legit.example", "Host": "legit.example"})
    assert MonatiseHandler._valid_request_origin(request) is True


def test_mismatched_origin_is_rejected() -> None:
    request = handler({"Origin": "https://evil.example", "Host": "legit.example"})
    assert MonatiseHandler._valid_request_origin(request) is False


def test_x_forwarded_host_cannot_be_used_to_self_validate_a_forged_origin() -> None:
    # A direct (non-browser) HTTP client can set arbitrary headers, so
    # trusting a client-supplied X-Forwarded-Host would let an attacker
    # satisfy this check by simply setting Origin and X-Forwarded-Host to
    # the same value they chose -- regardless of the real Host they're
    # actually connecting through.
    request = handler({
        "Origin": "https://evil.example",
        "Host": "legit.example",
        "X-Forwarded-Host": "evil.example",
    })
    assert MonatiseHandler._valid_request_origin(request) is False
