"""Authenticating the OSNMA trust anchor through the EUSPA PKI.

Operational material: the public EUSPA Root CA, Galileo SCA and OSNMA ICA with
their CRLs, snapshotted in trust/euspa/ on 2026-09-30 by scripts/refresh_euspa_pki.py.
Test material: the test-phase PKI shipped inside the official OSNMA test vectors.

The operational Merkle tree itself is available only to registered GSC users, so
no test here can authenticate it. What is tested is every step around it: that the
operational chain above it holds, and that the verifier accepts a good chain,
rejects a broken one, rejects the wrong certificate role, and rejects a changed file.
"""
import datetime
import subprocess
from pathlib import Path

import pytest

from tw.gsc_pki import EUSPA_RCA_001_01_SHA256, cert_fingerprint, verify_merkle_tree

ROOT = Path(__file__).resolve().parents[1]
PKI = ROOT / "trust" / "euspa"
SNAPSHOT = int(datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc).timestamp())


def test_operational_root_is_the_pinned_one():
    assert cert_fingerprint((PKI / "rca_001_01.crt").read_bytes()) == EUSPA_RCA_001_01_SHA256


def test_operational_chain_root_sca_ica_holds_with_every_crl(tmp_path):
    cas = tmp_path / "cas.pem"
    cas.write_bytes((PKI / "rca_001_01.crt").read_bytes() + (PKI / "sca_001_01.crt").read_bytes())
    r = subprocess.run(["openssl", "verify", "-crl_check_all", "-x509_strict", "-attime",
                        str(SNAPSHOT), "-CAfile", str(cas),
                        "-CRLfile", str(PKI / "rca_001_01.crl"),
                        "-CRLfile", str(PKI / "sca_001_01.crl"),
                        "-CRLfile", str(PKI / "ica_001_01.crl"),
                        str(PKI / "ica_001_01.crt")], capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---- test-phase material from the official vectors --------------------------------
CM = ROOT / "vectors" / "osnma-official" / "Test_vectors" / "cryptographic_material"
needs_vectors = pytest.mark.skipif(not CM.is_dir(), reason=(
    "official OSNMA test vectors not present; run scripts/fetch_osnma_vectors.py"))
PK1 = CM / "Merkle_tree_1" / "PublicKey"
TREE = CM / "Merkle_tree_2" / "MerkleTree" / "OSNMA_MerkleTree_20230720113300_newPKID_2.xml"
IN_2023 = int(datetime.datetime(2023, 10, 7, tzinfo=datetime.timezone.utc).timestamp())


def _test_pki():
    rca = (PK1 / "euspa_root_ca_test_phase.crt").read_bytes()
    return dict(rca=rca, sca=(PK1 / "euspa_galileo_sca_test_phase.crt").read_bytes(),
                crls=[(PK1 / n).read_bytes() for n in (
                    "euspa_root_ca_test_phase.crl", "euspa_galileo_sca_test_phase.crl",
                    "OSNMA_PublicKeyCRL_20230803105952_newPKID_1.crl")],
                pinned_rca_sha256=cert_fingerprint(rca))


def _sig():
    return Path(str(TREE) + ".p256").read_text()


@needs_vectors
def test_signature_and_role_pass_but_an_unrooted_chain_is_refused():
    # The test-phase tree bundles a self-issued ICA that does not chain to the
    # test Root CA. Its signature is valid; that is not enough.
    r = verify_merkle_tree(TREE.read_bytes(), _sig(), TREE.with_suffix(".crt").read_bytes(),
                           at_unix=IN_2023, **_test_pki())
    c = r["checks"]
    assert c["XML_SIGNATURE"] and c["EE_IS_MERKLE_TREE_ROLE"] and c["RCA_PINNED"]
    assert not c["CHAIN_AND_CRLS"] and not r["ok"] and "root" not in r


@needs_vectors
def test_a_rooted_chain_passes_while_valid_and_fails_once_expired():
    # The PKR end-entity bundle chains properly: EE -> ICA -> test SCA -> test Root.
    bundle = (PK1 / "OSNMA_PublicKey_20230803105952_newPKID_1.crt").read_bytes()
    ok = verify_merkle_tree(TREE.read_bytes(), _sig(), bundle, at_unix=IN_2023, **_test_pki())
    assert ok["checks"]["CHAIN_AND_CRLS"]
    # ...but it is the public-key role, not the Merkle-tree role, and not the key
    # that signed this tree: both refused.
    assert not ok["checks"]["EE_IS_MERKLE_TREE_ROLE"] and not ok["checks"]["XML_SIGNATURE"]
    later = int(datetime.datetime(2031, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    assert not verify_merkle_tree(TREE.read_bytes(), _sig(), bundle, at_unix=later,
                                  **_test_pki())["checks"]["CHAIN_AND_CRLS"]


@needs_vectors
def test_a_changed_tree_file_fails_its_signature():
    xml = TREE.read_bytes().replace(b"A10C440F", b"A10C440E")
    r = verify_merkle_tree(xml, _sig(), TREE.with_suffix(".crt").read_bytes(),
                           at_unix=IN_2023, **_test_pki())
    assert not r["checks"]["XML_SIGNATURE"]


@needs_vectors
def test_a_substituted_root_ca_is_caught_by_the_pin():
    r = verify_merkle_tree(TREE.read_bytes(), _sig(), TREE.with_suffix(".crt").read_bytes(),
                           at_unix=IN_2023, **{**_test_pki(),
                                               "pinned_rca_sha256": EUSPA_RCA_001_01_SHA256})
    assert not r["checks"]["RCA_PINNED"]


# ---- the operational tree, authenticated once and recorded ------------------------
MT = ROOT / "trust" / "merkle-tree"
RECORDS = sorted(MT.glob("*.authenticated.json"))


@pytest.mark.parametrize("record", RECORDS, ids=[r.name for r in RECORDS])
def test_the_recorded_operational_trust_anchor_still_authenticates(record):
    """The GSC tree is not committed (registered access); its authentication record
    is. Where the tree files are present locally, every check is re-run at the time
    the record says it was made, against the committed PKI snapshot, and must reach
    the recorded root. Without the files this reports SKIPPED, never a pass."""
    import json
    rec = json.loads(record.read_text(encoding="utf-8"))
    xml = MT / rec["xml"]
    if not xml.exists():
        pytest.skip(f"{rec['xml']} not present locally (registered GSC access)")
    import hashlib
    assert hashlib.sha256(xml.read_bytes()).hexdigest() == rec["xml_sha256"]
    at = int(datetime.datetime.fromisoformat(rec["checked_at_utc"]).timestamp())
    r = verify_merkle_tree(xml.read_bytes(), Path(str(xml) + ".p256").read_text(),
                           xml.with_suffix(".crt").read_bytes(),
                           rca=(PKI / "rca_001_01.crt").read_bytes(),
                           sca=(PKI / "sca_001_01.crt").read_bytes(),
                           crls=[(PKI / n).read_bytes() for n in (
                               "rca_001_01.crl", "sca_001_01.crl", "ica_001_01.crl")],
                           at_unix=at)
    assert r["ok"], r["checks"]
    assert r["root"].hex().upper() == rec["merkle_root"]
