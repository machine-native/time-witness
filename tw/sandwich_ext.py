"""The chronology-protocol sandwich extension for TW-GNSS/v1 evidence.

    from tw.sandwich_ext import EXTENSIONS
    verify_sandwich(bundle, EXTENSIONS)

or from the command line, with this repository importable:

    python scripts/verify_sandwich.py BUNDLE.cbor --extension tw.sandwich_ext:EXTENSIONS

chronology-protocol still checks everything it owns — the blob's binding to the
session, the observation's signatures and chain, the checkpoint, the blocks. This
extension checks what is specific to the profile: that the observation says exactly
what its UBX frames say (tw.verify), and, when the blob carries a Galileo capture,
what that capture establishes (tw.witness.galileo_facts). The Galileo lower bound is
reported as a fact alongside the sandwich's own bounds; it never replaces them.
"""
from __future__ import annotations

from .verify import verify_observation
from .witness import BLOB_TYPE, evidence_digest

NOT_CHECKED = "NOT_CHECKED"          # chronology-protocol's value, repeated to avoid an import cycle


def make_extensions(*, pinned_rca: str | None = None) -> dict:
    """Extensions with an optional non-default Root CA pin (tests use a test PKI)."""

    def verify(unsigned, blob: bytes, same_type: list[bytes]):
        anchors = {evidence_digest(b): b for b in same_type}
        checks, verdict, facts = verify_observation(unsigned, blob, anchors,
                                                    pinned_rca=pinned_rca)
        result = {"PASS": True, "FAIL": False}.get(verdict, NOT_CHECKED)
        out = {"tw_verdict": verdict,
               "tw_failed": sorted(k for k, v in checks.items() if v is False)}
        for k in ("mode", "system", "consistency", "galileo"):
            if k in facts:
                out[k] = facts[k]
        return result, out

    return {BLOB_TYPE: verify}


EXTENSIONS = make_extensions()
