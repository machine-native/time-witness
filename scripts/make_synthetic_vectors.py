#!/usr/bin/env python3
"""Write the SYNTHETIC vectors in vectors/synthetic/. NOT EVIDENCE.

Every byte comes from tw.synth: this repository's encoder, pinned to pyubx2, fed
invented values. The vectors exist so the verifier's verdicts on fixed bytes are
regression-tested (tests/test_vectors.py). They say nothing about any receiver,
and chronology-protocol invariant 14 applies — a simulator cannot establish a GNSS
or hardware claim.

Deterministic: running it twice produces identical files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from ctp.hashsuite import digest_pair, DOM_STATE          # noqa: E402

from tw import synth                                      # noqa: E402
from tw.witness import (derive, device_profile, evidence_blob,  # noqa: E402
                        evidence_digest, observation)

OUT = ROOT / "vectors" / "synthetic"
GENESIS = digest_pair(DOM_STATE, b"TW-SYNTHETIC-GENESIS/v1")
WEEK, TOW_MS, LEAP, MONO0 = 2386, 345_600_000, 18, 1_000_000_000_000
PROFILE = device_profile("SYNTHETIC-bench", tacc_k=3, cable_unc_ps=1_000,
                         calib_unc_ps=2_000, timescale_unc_ps=50_000, osc_y_ppq=10_000,
                         osc_aging_ppq_day=5_000, host_ppm=50, firmware="SYNTHETIC")


def osc(count, tow_ms, sub_ns, mono, seq, anchor=None):
    frames = [synth.tim_tm2(count, WEEK, tow_ms, sub_ns, 12),
              synth.nav_timegps(tow_ms - 500, 0, WEEK, LEAP, 7), synth.nav_status()]
    return evidence_blob("OSC", PROFILE, frames, mono, seq,
                         anchor=None if anchor is None else evidence_digest(anchor))


def build():
    pps = evidence_blob("PPS", PROFILE, [synth.tim_tp(TOW_MS, 0, -1234, WEEK),
                                         synth.nav_timegps(TOW_MS - 1000, -250, WEEK, LEAP, 7),
                                         synth.nav_status()], MONO0, 0)
    anchor = osc(65530, TOW_MS, 250, MONO0, 0)
    honest = osc(94, TOW_MS + 100_000, 251, MONO0 + 100_000_020_000, 1, anchor)
    delayed = osc(94, TOW_MS + 100_000, 251 + 50_000, MONO0 + 100_000_020_000, 1, anchor)
    anchors = {evidence_digest(anchor): anchor}
    ua = observation(anchor, derive(anchor), GENESIS, None)
    cases = {
        "pps": (pps, observation(pps, derive(pps), GENESIS, None), None, "PASS", "NO_ANCHOR"),
        "osc-anchor": (anchor, ua, None, "PASS", "NO_ANCHOR"),
        "osc-honest": (honest, observation(honest, derive(honest, anchors), GENESIS,
                                           ua.lineage_id()), "osc-anchor", "PASS", "CONSISTENT"),
        "osc-delayed-50us": (delayed, observation(delayed, derive(delayed, anchors), GENESIS,
                                                  ua.lineage_id()), "osc-anchor", "PASS",
                             "GNSS_OSCILLATOR_DISAGREE"),
    }
    return cases


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"label": "SYNTHETIC - not evidence; see scripts/make_synthetic_vectors.py",
                "cases": {}}
    for name, (blob, obs, anchor, verdict, consistency) in build().items():
        (OUT / f"SYNTHETIC-{name}.blob.cbor").write_bytes(blob)
        (OUT / f"SYNTHETIC-{name}.obs.cbor").write_bytes(obs.canonical())
        manifest["cases"][name] = {"anchor": anchor, "expected_verdict": verdict,
                                   "expected_consistency": consistency}
    (OUT / "SYNTHETIC-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                 encoding="utf-8", newline="\n")
    print(f"wrote {len(manifest['cases'])} synthetic cases to {OUT}")


if __name__ == "__main__":
    main()
