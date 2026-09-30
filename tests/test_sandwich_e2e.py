"""End to end: official Galileo data inside a chronology-protocol sandwich.

What is real and what is not, precisely:

- REAL: the Galileo E1-B pages (official OSNMA test vector, configuration 2, 27 July
  2023) and the Merkle tree they chain to (the official test material's file).
- MADE HERE, LABELLED: a test PKI (Root, SCA, ICA, Merkle-tree certificate, CRLs),
  because the test material's own tree certificates do not chain to its root
  (test_gsc_pki shows that refusal). It signs the official tree file, and the test
  pins its Root. Nothing here is signed by EUSPA.
- SYNTHETIC: the receiver timing frames, the NTP witnesses and the blocks, from this
  repository's and chronology-protocol's own test helpers.

What it shows: the evidence blob carries everything the Galileo bound rests on, and
chronology-protocol's unmodified verification path — plus the extension — re-derives
the bound from the bytes of the bundle.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CTP = ROOT.parent / "chronology-protocol"
sys.path.insert(0, str(CTP / "tests"))

from ctp.pq import PQUnavailable, ensure_available  # noqa: E402

from tw import synth  # noqa: E402
from tw.gsc_pki import cert_fingerprint  # noqa: E402
from tw.ubx_inav import page_sfrbx  # noqa: E402
from tw.witness import (derive, device_profile, evidence_blob, observation,  # noqa: E402
                        trust_anchor_material)

CM = ROOT / "vectors" / "osnma-official" / "Test_vectors"
pytestmark = pytest.mark.skipif(not CM.is_dir(), reason=(
    "official OSNMA test vectors not present; run scripts/fetch_osnma_vectors.py"))

TREE = CM / "cryptographic_material" / "Merkle_tree_2" / "MerkleTree" / \
    "OSNMA_MerkleTree_20230720113300_newPKID_2.xml"


def _run(*a, cwd):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def make_test_pki(d: Path) -> dict:
    """Root -> SCA -> ICA -> Merkle-tree EE, P-256, valid 2020-2040, with CRLs."""
    nb, na = "20200101000000Z", "20400101000000Z"
    ca_ext = ("basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
              "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n")
    (d / "ca.ext").write_text(ca_ext)
    (d / "ee.ext").write_text("basicConstraints=critical,CA:FALSE\n"
                              "keyUsage=critical,digitalSignature\n"
                              "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n")
    names = {"rca": "TEST ONLY ROOT CA", "sca": "TEST ONLY SCA", "ica": "TEST ONLY ICA",
             "ee": "EUSPA OSNMA EE MERKLE TREE"}
    for k in names:
        _run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out",
             f"{k}.key", cwd=d)
    _run("openssl", "req", "-x509", "-new", "-key", "rca.key", "-subj",
         f"/O=TIME-WITNESS TEST/CN={names['rca']}", "-not_before", nb, "-not_after", na,
         "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-out", "rca.pem", cwd=d)
    for child, parent, ext in (("sca", "rca", "ca.ext"), ("ica", "sca", "ca.ext"),
                               ("ee", "ica", "ee.ext")):
        _run("openssl", "req", "-new", "-key", f"{child}.key", "-subj",
             f"/O=TIME-WITNESS TEST/CN={names[child]}", "-out", f"{child}.csr", cwd=d)
        _run("openssl", "x509", "-req", "-in", f"{child}.csr", "-CA", f"{parent}.pem",
             "-CAkey", f"{parent}.key", "-set_serial", str(len(child) * 7 + ord(child[0])),
             "-not_before", nb, "-not_after", na, "-extfile", ext, "-out", f"{child}.pem",
             cwd=d)
    crls = []
    for ca in ("rca", "sca", "ica"):
        (d / f"{ca}.idx").write_text("")
        (d / f"{ca}.crlnum").write_text("01\n")
        (d / f"{ca}.cnf").write_text(
            f"[ca]\ndefault_ca=c\n[c]\ndatabase={ca}.idx\ncrlnumber={ca}.crlnum\n"
            "default_md=sha256\ndefault_crl_days=7300\n")
        _run("openssl", "ca", "-gencrl", "-config", f"{ca}.cnf", "-keyfile", f"{ca}.key",
             "-cert", f"{ca}.pem", "-crl_lastupdate", nb, "-crl_nextupdate", na,
             "-out", f"{ca}.crl", cwd=d)
        crls.append((d / f"{ca}.crl").read_bytes())
    # Sign the official tree file the way the GSC does: ECDSA P-256/SHA-256, hex r||s.
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(d / "ee.key"), str(TREE)],
                         capture_output=True, check=True).stdout
    r, s = _der_sig_to_rs(der)
    rca = (d / "rca.pem").read_bytes()
    return {"anchor": trust_anchor_material(
                TREE.read_bytes(), (r + s).hex().upper(),
                (d / "ee.pem").read_bytes() + (d / "ica.pem").read_bytes(),
                rca, (d / "sca.pem").read_bytes(), crls),
            "pin": cert_fingerprint(rca)}


def _der_sig_to_rs(der: bytes) -> tuple[bytes, bytes]:
    i = 2
    parts = []
    for _ in range(2):
        n = der[i + 1]
        parts.append(der[i + 2:i + 2 + n].lstrip(b"\x00").rjust(32, b"\x00"))
        i += 2 + n
    return parts[0], parts[1]


def galileo_capture(minutes: int = 15):
    import csv
    import glob
    from tw.osnma import hex_to_bits, page_time_from_word5, pages_from_bits
    (f,) = glob.glob(str(CM / "osnma_test_vectors" / "configuration_2" / "*.csv"))
    caps = []
    with open(f, newline="") as fh:
        for row in csv.DictReader(fh):
            bits = hex_to_bits(row["NavBitsHEX"], int(row["NumNavBits"]))
            sv = int(row["SVID"])
            ps = pages_from_bits(sv, bits, 0)
            if page_time_from_word5(ps) is None:
                continue
            for k, p in enumerate(ps[:minutes * 30]):
                mono = 10**12 + k * 2_000_000_000 + sv * 1_000_000     # 2 s apart, per-SV jitter
                caps.append((mono, page_sfrbx(sv, p.even, p.odd)))
    caps.sort()
    return caps


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    return make_test_pki(tmp_path_factory.mktemp("pki"))


def test_the_blob_carries_a_galileo_bound_that_re_derives(pki):
    blob = evidence_blob("PPS", _profile(), _pps_frames(), 10**12, 0,
                         galileo=galileo_capture(), trust_anchor=pki["anchor"])
    g = derive(blob, pinned_rca=pki["pin"])["galileo"]
    assert all(g["trust_anchor"].values()), g["trust_anchor"]
    assert g["merkle_root"].startswith("A10C440F")
    assert g["usable_keys"] > 0 and g["key_failures"] == 0
    b = g["bound"]
    # 27 July 2023 is a Thursday: GST week 1248, and the capture starts at 00:00:01.
    # With 15 minutes captured, the latest usable key's sub-frame starts at 00:14:30.
    # (Fifteen, not five: this hour opens with the 6-hourly public-key broadcast, and
    # the chain root's DSM-KROOT only completes at 00:06:30. No KROOT, no bound.)
    assert (b["wn"], b["tow"]) == (1248, 4 * 86400 + 14 * 60 + 30)


def test_under_the_real_euspa_pin_the_test_pki_is_refused_and_no_bound_is_claimed(pki):
    blob = evidence_blob("PPS", _profile(), _pps_frames(), 10**12, 0,
                         galileo=galileo_capture(1), trust_anchor=pki["anchor"])
    g = derive(blob)["galileo"]
    assert g["trust_anchor"]["RCA_PINNED"] is False and g["bound"] is None


def test_a_capture_without_a_trust_anchor_claims_nothing():
    blob = evidence_blob("PPS", _profile(), _pps_frames(), 10**12, 0, galileo=galileo_capture(1))
    g = derive(blob)["galileo"]
    assert g["trust_anchor"] == "ABSENT" and g["bound"] is None


def _profile():
    return device_profile("e2e", tacc_k=3, cable_unc_ps=1_000, calib_unc_ps=2_000,
                          timescale_unc_ps=50_000, osc_y_ppq=10_000, osc_aging_ppq_day=5_000,
                          host_ppm=50, firmware="SYNTHETIC")


def _pps_frames(week=2386, tow_ms=345_600_000):
    return [synth.tim_tp(tow_ms, 0, -1234, week),
            synth.nav_timegps(tow_ms - 1000, -250, week, 18, 7), synth.nav_status()]


def test_in_a_sandwich_through_chronology_protocols_verifier(pki, tmp_path):
    try:
        ensure_available()
    except PQUnavailable:
        pytest.skip("OpenSSL with ML-DSA/SLH-DSA unavailable")
    from test_sandwich import _mine_easy, _pq_keys, synthetic_exchange
    from ctp.bitcoin_jan09 import anchor_payload
    from ctp.genesis import build_protocol_genesis
    from ctp.model import build_checkpoint, sign_checkpoint, sign_observation
    from ctp.sandwich import (SandwichBundle, challenge, derive_measurement, era_expectation,
                              evidence_blob as ntp_blob, exchange_nonce, ntp_unsigned,
                              verify_sandwich)
    from tw.sandwich_ext import make_extensions

    genesis = build_protocol_genesis((CTP / "SPEC.md").read_bytes(),
                                     (CTP / "INVARIANTS.md").read_bytes())
    gid = genesis.genesis_id()
    b0 = _mine_easy(anchor_payload(0, b"\x00" * 32, b"\x00" * 48), "11" * 32, 1_787_000_000)
    session = bytes(range(32))
    q = challenge(b0["hash"], session)
    origin_s = 1_787_000_000 - (1_787_000_000 % 86400)
    history, blobs = [], []
    for host in ("a.example", "b.example", "c.example", "d.example"):
        ex = synthetic_exchange(host, exchange_nonce(q, host, 0), 1_787_000_100)
        blob = ntp_blob(0, ex, q, b0["hash"], session)
        history.append(sign_observation(
            ntp_unsigned(0, ex, derive_measurement(ex), blob, gid, None, origin_s),
            _pq_keys(tmp_path, host)))
        blobs.append(blob)

    # Receiver frames dated at the NTP witnesses' instant (Unix 1787000100 = GPS week
    # 2432, TOW 161718 s): a frame-relative claim a year away would not fit the
    # canonical-CBOR integer range, and chronology-protocol rightly refuses it.
    tw_blob = evidence_blob("PPS", _profile(), _pps_frames(2432, 161_718_000), 10**12, 0, q=q,
                            b0_hash=bytes.fromhex(b0["hash"]), session=session,
                            galileo=galileo_capture(), trust_anchor=pki["anchor"])
    u = observation(tw_blob, derive(tw_blob, pinned_rca=pki["pin"]), gid, None,
                    origin_unix_s=origin_s)
    history.append(sign_observation(u, _pq_keys(tmp_path, "tw")))
    blobs.append(tw_blob)

    scp = sign_checkpoint(build_checkpoint(1, history, f=1), _pq_keys(tmp_path, "coord"))
    com = scp.record_commitment()
    c = _mine_easy(anchor_payload(1, com.sha256, com.shake384), b0["hash"], 1_787_000_200)
    b1 = _mine_easy(anchor_payload(2, b"\x01" * 32, b"\x01" * 48), c["hash"], 1_787_000_300)
    cp = scp.unsigned
    bundle = SandwichBundle(
        b0_raw=b0["raw"], b0_height=1, session_id=session, evidence=blobs, history=history,
        checkpoint=scp, block_c_raw=c["raw"], path_headers=[], b1_headers=[b1["header"]],
        expectation=era_expectation(origin_s, (cp.interval.lower + cp.interval.upper) // 2),
        genesis=genesis)
    raw = bundle.canonical()

    checks, verdict, facts = verify_sandwich(SandwichBundle.from_bytes(raw),
                                             make_extensions(pinned_rca=pki["pin"]))
    assert verdict == "SANDWICH_PASS", checks
    (ext,) = facts["extensions"]
    assert ext["result"] is True and ext["galileo"]["bound"]["wn"] == 1248

    # Without the extension, chronology-protocol cannot check this evidence and says so.
    _, v2, f2 = verify_sandwich(SandwichBundle.from_bytes(raw))
    assert v2 == "INDETERMINATE_UNCHECKED_EVIDENCE"
    assert f2["unchecked_evidence_types"] == ["TW-GNSS/v1"]
