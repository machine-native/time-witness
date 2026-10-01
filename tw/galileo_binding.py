"""A Galileo capture bound into a chronology-protocol sandwich: both bounds, neither ours alone.

chronology-protocol's external-record binding (its docs/EXTERNAL-BINDING.md) gives
two half-bindings: the sandwich committing to a record's hash puts the record BEFORE
the anchor block (upper bound), and the record carrying a tag derived from the
session challenge puts it AFTER B0 (lower bound). A Galileo capture cannot carry the
challenge — its pages are the satellites' data — so by that vocabulary its binding is
UPPER_ONLY.

It does not need the challenge. It carries its own lower bound: TESLA keys that
Galileo kept secret until their sub-frames. So

    Galileo key release  <  capture  <  anchor block C  (< burial blocks)

and the verdict here is GALILEO_BOUND when the sandwich verifies, commits to exactly
these capture bytes, and the capture yields a Galileo bound. Each half is checked by
the code that owns it: the sandwich and the commitment by chronology-protocol, the
Galileo bound by tw.osnma.
"""
from __future__ import annotations

from pathlib import Path

from ctp.binding import verify_binding
from ctp.sandwich import SandwichBundle, verify_sandwich

from . import osnma

SYSTEM_ID = "GALILEO-E1B-CAPTURE"


def capture_pages(capture_bytes: bytes, kind: str):
    if kind == "galmon":
        from .galmon_feed import pages_from_stream
        return pages_from_stream(capture_bytes)[0]
    if kind == "android":
        from .android_nav import pages_from_log
        return pages_from_log(capture_bytes.decode("utf-8"))[0]
    raise ValueError(f"unknown capture kind {kind!r}")


def verify_galileo_binding(bundle_bytes: bytes, capture_bytes: bytes, kind: str,
                           merkle_root: bytes, public_keys: list, extensions=None) -> dict:
    bundle = SandwichBundle.from_bytes(bundle_bytes)
    s_checks, s_verdict, s_facts = verify_sandwich(bundle, extensions)
    b_checks, b_verdict = verify_binding(bundle, SYSTEM_ID, capture_bytes)
    rep = osnma.verify_stream(capture_pages(capture_bytes, kind), merkle_root,
                              extra_keys=public_keys, check_tags=False)
    bound = osnma.galileo_lower_bound(rep)
    ok = (s_verdict.startswith("SANDWICH_PASS")
          and b_checks["SANDWICH_COMMITS_TO_RECORD"] is True and bound is not None)
    return {
        "verdict": "GALILEO_BOUND" if ok else "NOT_BOUND",
        "sandwich_verdict": s_verdict,
        "binding_verdict": b_verdict,          # UPPER_ONLY is expected and correct here
        "record_sha256": b_checks["RECORD_SHA256"],
        "lower": bound,
        "upper": {"anchor_block_hash": s_facts.get("block_c_hash"),
                  "burial_depth": s_facts.get("burial_depth")},
        "kroots_verified": sum(1 for k in rep.kroots if k["signature_ok"]),
        "key_failures": len(rep.key_failures),
    }
