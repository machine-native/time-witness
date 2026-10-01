"""A real Galileo capture bound into a chronology-protocol sandwich.

The capture is the committed Samsung M56 extract; the sandwich (NTP witnesses,
blocks) is built with chronology-protocol's own test helpers at easy difficulty, so
it is SYNTHETIC — what is real is the Galileo evidence and the binding logic.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "chronology-protocol" / "tests"))

from ctp.pq import PQUnavailable, ensure_available  # noqa: E402

from test_galmon_feed import LIVE, _root, _sis_public_key  # noqa: E402

CAPTURE = LIVE / "android-m56-2026-10-01" / "galileo-extract.txt"


def _sandwich(tmp: Path, record: bytes) -> bytes:
    import hashlib
    from test_sandwich import _mine_easy, _pq_keys, synthetic_exchange
    from ctp.binding import external_record_blob
    from ctp.bitcoin_jan09 import anchor_payload
    from ctp.genesis import build_protocol_genesis
    from ctp.model import build_checkpoint, sign_checkpoint, sign_observation
    from ctp.sandwich import (SandwichBundle, challenge, derive_measurement, era_expectation,
                              evidence_blob, exchange_nonce, ntp_unsigned)
    from tw.galileo_binding import SYSTEM_ID
    ctp_root = ROOT.parent / "chronology-protocol"
    genesis = build_protocol_genesis((ctp_root / "SPEC.md").read_bytes(),
                                     (ctp_root / "INVARIANTS.md").read_bytes())
    gid = genesis.genesis_id()
    b0 = _mine_easy(anchor_payload(0, b"\x00" * 32, b"\x00" * 48), "11" * 32, 1_787_000_000)
    session = bytes(range(32))
    q = challenge(b0["hash"], session)
    origin = 1_787_000_000 - 1_787_000_000 % 86400
    history, blobs = [], []
    for host in ("a.example", "b.example", "c.example", "d.example"):
        ex = synthetic_exchange(host, exchange_nonce(q, host, 0), 1_787_000_100)
        blob = evidence_blob(0, ex, q, b0["hash"], session)
        history.append(sign_observation(ntp_unsigned(0, ex, derive_measurement(ex), blob, gid,
                                                     None, origin), _pq_keys(tmp, host)))
        blobs.append(blob)
    blobs.append(external_record_blob(0, SYSTEM_ID, hashlib.sha256(record).digest(), q,
                                      b0["hash"], session))
    scp = sign_checkpoint(build_checkpoint(1, history, f=1), _pq_keys(tmp, "coord"))
    com = scp.record_commitment()
    c = _mine_easy(anchor_payload(1, com.sha256, com.shake384), b0["hash"], 1_787_000_200)
    b1 = _mine_easy(anchor_payload(2, b"\x01" * 32, b"\x01" * 48), c["hash"], 1_787_000_300)
    cp = scp.unsigned
    return SandwichBundle(
        b0_raw=b0["raw"], b0_height=1, session_id=session, evidence=blobs, history=history,
        checkpoint=scp, block_c_raw=c["raw"], path_headers=[], b1_headers=[b1["header"]],
        expectation=era_expectation(origin, (cp.interval.lower + cp.interval.upper) // 2),
        genesis=genesis).canonical()


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    try:
        ensure_available()
    except PQUnavailable:
        pytest.skip("OpenSSL with ML-DSA/SLH-DSA unavailable")
    return _sandwich(tmp_path_factory.mktemp("gb"), CAPTURE.read_bytes())


def test_the_real_capture_is_galileo_bound_inside_the_sandwich(bundle):
    from tw.galileo_binding import verify_galileo_binding
    r = verify_galileo_binding(bundle, CAPTURE.read_bytes(), "android", _root(),
                               [_sis_public_key()])
    assert r["verdict"] == "GALILEO_BOUND", r
    assert r["sandwich_verdict"] == "SANDWICH_PASS"
    assert r["binding_verdict"] == "UPPER_ONLY"        # no challenge in satellite data: expected
    assert (r["lower"]["wn"], r["lower"]["tow"]) == (1414, 395430)


def test_other_bytes_are_not_bound_by_this_sandwich(bundle):
    from tw.galileo_binding import verify_galileo_binding
    other = (LIVE / "galmon-2026-10-01-a" / "e1b-frames.bert").read_bytes()
    r = verify_galileo_binding(bundle, other, "galmon", _root(), [_sis_public_key()])
    assert r["verdict"] == "NOT_BOUND" and r["lower"] is not None   # bounded, but not by this
