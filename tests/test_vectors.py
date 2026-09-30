"""The committed SYNTHETIC vectors still verify to their recorded verdicts.

The vectors are fixed bytes. If a change to the codec, the derivation or the
verifier alters what those bytes mean, this fails — which is the point: a verdict
on published bytes must not drift silently. Regenerating them is a deliberate
act (scripts/make_synthetic_vectors.py) that shows up in the diff.
"""
import json
import sys
from pathlib import Path

import pytest

from ctp import cbor
from ctp.model import UnsignedObservation

from tw.verify import verify_observation
from tw.witness import evidence_digest

VEC = Path(__file__).resolve().parents[1] / "vectors" / "synthetic"
MANIFEST = json.loads((VEC / "SYNTHETIC-manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(MANIFEST["cases"]))
def test_vector_verdict(name):
    case = MANIFEST["cases"][name]
    blob = (VEC / f"SYNTHETIC-{name}.blob.cbor").read_bytes()
    obs = UnsignedObservation.from_obj(cbor.loads((VEC / f"SYNTHETIC-{name}.obs.cbor").read_bytes()))
    anchors = None
    if case["anchor"]:
        a = (VEC / f"SYNTHETIC-{case['anchor']}.blob.cbor").read_bytes()
        anchors = {evidence_digest(a): a}
    checks, verdict, facts = verify_observation(obs, blob, anchors)
    assert verdict == case["expected_verdict"], checks
    assert facts["consistency"] == case["expected_consistency"]


def test_generator_is_deterministic_and_matches_the_committed_bytes():
    sys.path.insert(0, str(VEC.parents[1] / "scripts"))
    import make_synthetic_vectors as gen
    for name, (blob, obs, *_rest) in gen.build().items():
        assert (VEC / f"SYNTHETIC-{name}.blob.cbor").read_bytes() == blob
        assert (VEC / f"SYNTHETIC-{name}.obs.cbor").read_bytes() == obs.canonical()
