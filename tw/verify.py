"""Offline verification of a TW-GNSS/v1 observation against its evidence.

Three outcomes, never two, as in chronology-protocol:

  PASS           every claim in the observation re-derives exactly from the bytes
  FAIL           something re-derived differently, or the bytes are malformed
  INDETERMINATE  a check could not be run (an anchor blob was not supplied). Unable
                 to check is not the same as checked and failed.

What PASS means, precisely: the observation says what its evidence says. It does
NOT mean the receiver told the truth, that GNSS was not spoofed, or that the
declared device profile is accurate. Those are the evidence's content; this
checks its integrity. `facts["consistency"]` reports whether the GNSS and
oscillator sources agreed — a disagreement is a finding about the world, not a
verification failure, exactly as TIME_CONFLICT is in chronology-protocol.
"""
from __future__ import annotations

from ctp.hashsuite import DigestPair
from ctp.model import UnsignedObservation

from .timescale import PS, frame_for_origin, FRAME_PREFIX
from .witness import (AUTH_OSNMA_VERIFIED, EvidenceError, derive, evidence_digest,
                      witness_id)

UNAVAILABLE = "UNAVAILABLE"


def _origin(frame: str) -> int:
    if not frame.startswith(FRAME_PREFIX) or not frame.endswith("/v1"):
        raise ValueError(f"unknown reference frame {frame}")
    origin = int(frame[len(FRAME_PREFIX):-3])
    if frame_for_origin(origin) != frame:
        raise ValueError("non-canonical frame string")
    return origin


def verify_observation(obs: UnsignedObservation, blob: bytes,
                       anchors: dict[DigestPair, bytes] | None = None, *,
                       pinned_rca: str | None = None):
    checks, facts = {}, {}
    ev = evidence_digest(blob)
    checks["TW_EVIDENCE_REFERENCED"] = bool(obs.sources) and all(
        s.evidence == ev for s in obs.sources)

    try:
        d = derive(blob, anchors, pinned_rca=pinned_rca)
        checks["TW_EVIDENCE_PARSES"] = True
    except LookupError:
        checks["TW_EVIDENCE_PARSES"] = True
        checks["TW_ANCHOR_AVAILABLE"] = UNAVAILABLE
        d = None
    except (EvidenceError, ValueError) as e:
        checks["TW_EVIDENCE_PARSES"] = False
        facts["error"] = str(e)
        d = None

    if d is not None:
        try:
            base = _origin(obs.reference_frame) * PS
            lo, hi = d["interval_abs"]
            want = [(s["type"], s["claimed_abs_ps"] - base, s["uncertainty_ps"], s["auth"])
                    for s in d["sources"]]
            got = [(s.source_type, s.claimed_ps, s.uncertainty_ps, s.auth_state)
                   for s in obs.sources]
            checks["TW_SOURCES_REDERIVED"] = want == got
            checks["TW_INTERVAL_REDERIVED"] = (obs.interval.lower == lo - base
                                               and obs.interval.upper == hi - base)
        except ValueError as e:
            checks["TW_SOURCES_REDERIVED"] = checks["TW_INTERVAL_REDERIVED"] = False
            facts["error"] = str(e)
        checks["TW_WITNESS_IDENTITY"] = obs.witness_id == witness_id(d["device"])
        checks["TW_SEQUENCE"] = obs.sequence == d["sequence"]
        checks["TW_MONOTONIC"] = obs.monotonic_ps == d["mono_ns"] * 1000
        facts.update(mode=d["mode"], system=d["system"], consistency=d["consistency"],
                     receiver=d["receiver"], galileo=d["galileo"])

    # OSNMA authenticates navigation data, not when a signal arrived, so no timing
    # source can honestly claim it. This is a definite failure, not an unknown.
    if any(s.auth_state == AUTH_OSNMA_VERIFIED for s in obs.sources):
        checks["TW_NO_OSNMA_TIMING_CLAIM"] = False

    # A check that ran and failed is known; one that could not run is not. So a
    # definite failure outranks an unavailable check, and only a bundle with no
    # failures can be INDETERMINATE.
    if any(v is False for v in checks.values()):
        verdict = "FAIL"
    elif any(v == UNAVAILABLE for v in checks.values()):
        verdict = "INDETERMINATE"
    else:
        verdict = "PASS"
    return checks, verdict, facts
