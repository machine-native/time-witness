"""Offline OSNMA verification against the official material, never against itself.

Two sources, both published by the European Union (docs/SOURCES.md):

1. Worked examples: Galileo OSNMA Receiver Guidelines, Issue 1.3, January 2024,
   Annex A ("Examples of OSNMA Verifications"). The hex values below are quoted
   unaltered from that annex, with section numbers. © European Union 2024; reproduced
   under the document's Terms of Use and Disclaimers, given in full in THIRD-PARTY.md.
2. Test vectors: the Annex B dataset (Test_vectors.zip, sha256 ef9b9afc...). It is
   not redistributed here; `scripts/fetch_osnma_vectors.py` downloads it from the
   GSC and refuses any other bytes. Without it, those tests report SKIPPED.

Everything else here is a negative case: the same material, altered, must fail.
"""
import csv
import glob
import os
from collections import Counter
from pathlib import Path

import pytest

from tw.osnma import (CRC24_G, galileo_lower_bound, NMAHeader, Page, bits_to_bytes, crc24, gst32, gst_seconds,
                      hex_to_bits, keys_from_gsc_xml, mac, page_time_from_word5,
                      pages_from_bits, parse_mack, trunc, u, ubits, verify_kroot, verify_pkr,
                      verify_stream)

H = hex_to_bits

# ---- Annex A, quoted -----------------------------------------------------------
# A.3 NMA Header
NMA = "10000010"
# A.4 DSM-KROOT (832 bits)
DSM_KROOT = H("2210492204E060610BDF26D77B5BF8C9CBFCF70422081475FD445DF0FFF8CD88299FA4605"
              "800207BFEBEAC55024053F30F7C69B35C15E60800AC3B6FE3ED0639952F7B028D8686744596"
              "1FFE94FB226BFF7006E0C451EE3F8728C177FB5E130DA4B44BBE7EC29522", 832)
# A.7 DSM-PKR (1352 bits) and A.7.2 Merkle root
DSM_PKR = H("717CBE05D9970CFC9E22D0A43A340EF557624453A2E821AADEAC989C405D78BA069"
            "56380BAB0D2C939EC6208151040CCFFCF1FB7156178FD1255BA0AECAAA253F7407B6C"
            "5DD4DF059FF8789474061301E1C34881DB7A367A913A3674300E21EAB124EF508389B"
            "7D446C3E2ECE8D459FBBD3239A794906F5B1F92469C640164FD87120303B2CE64BC20"
            "7BDD8BC4DF859187FCB686320D63FFA091410FC158FBB77980EAB8884C0D33D6", 1352)
ROOT = bytes.fromhex("A10C440F3AA62453526DB4AF76DF8D9410D35D8277397D7053C700D192702B0D")
# A.5.1 TESLA keys (WN 1248). The annex prints key 2's TOW as "34630"; the
# sub-frame sequence and A.5.2 both make it 345630, which is what verifies.
KEYS = {345630: "2DC3A3CDB117FAADB83B5F0B6FEA88EB",
        345690: "69C00AA7364237A65EBF006AD8DDBC73",
        349170: "01D3E3E2667A0A1894D04BDD98CABA17"}
# A.6.1 MACK at WN 1248 TOW 345660, from E02
MACK = H("E37BC4F858B08F0726A9000C12057BB238C883024FC8FB247323050F91F230FE4D0"
         "2CF2F1C4D28C1220F2E9C651C410CFF23D370497D28AB4B140000", 480)
# A.6.5.1 ADKD0 navigation data (549 bits) and A.6.5.2 ADKD4 data (141 bits)
NAV0 = H("0E96441475A496001DACFBAA0506FC0EB72D6AB6C9DEBDBF3C87EE63FDFA0EBFF0D"
         "C080EC363843AC53444639AC3A0800680039644001B4C7C0009A015280B08981FDFF000", 549)
NAV4 = H("FFFFFFFF0000011248E089E25FF7BFE4C100", 141)


@pytest.fixture(scope="module")
def pkr():
    return verify_pkr(DSM_PKR, ROOT)


@pytest.fixture(scope="module")
def kroot(pkr):
    return verify_kroot(DSM_KROOT, NMA, pkr["key"])


def test_crc_generator_is_crc24q():
    # The ICD gives G(X) = (1 + X) P(X). Expanded, it must be the CRC-24Q polynomial.
    assert CRC24_G == 0x1864CFB


def test_nma_header_a3():
    h = NMAHeader.parse(NMA)
    assert (h.nmas, h.cid, h.cpks) == (2, 0, 1)


def test_dsm_pkr_merkle_and_padding_a7(pkr):
    assert pkr["merkle_ok"] and pkr["pdp_ok"]
    assert (pkr["nbdp"], pkr["mid"], pkr["npkt"], pkr["npkid"]) == (7, 1, 1, 2)
    assert pkr["key"].point.hex().upper() == \
        "0303B2CE64BC207BDD8BC4DF859187FCB686320D63FFA091410FC158FBB77980EA"


def test_dsm_pkr_against_another_root_fails():
    assert not verify_pkr(DSM_PKR, bytes(32))["merkle_ok"]


def test_dsm_kroot_interpretation_signature_and_padding_a4(kroot):
    assert kroot["signature_ok"] and kroot["pdk_ok"]
    assert (kroot["pkid"], kroot["hf"], kroot["mf"], kroot["lk"], kroot["lt"], kroot["maclt"],
            kroot["wnk"], kroot["towhk"]) == (2, 0, 0, 128, 40, 34, 1248, 96)
    assert kroot["chain"].gst0 == gst_seconds(1248, 345600)


@pytest.mark.parametrize("flip", [200, 104 + 5, 104 + 128 + 10])   # alpha, KROOT, DS
def test_dsm_kroot_altered_anywhere_fails(pkr, flip):
    bad = DSM_KROOT[:flip] + ("1" if DSM_KROOT[flip] == "0" else "0") + DSM_KROOT[flip + 1:]
    assert not verify_kroot(bad, NMA, pkr["key"])["signature_ok"]


def test_dsm_kroot_under_a_different_header_fails(pkr):
    # The header is inside the signed message: a KROOT cannot be replayed under
    # a changed status.
    assert not verify_kroot(DSM_KROOT, "11000010", pkr["key"])["signature_ok"]


def test_tesla_keys_chain_to_kroot_a5(kroot):
    ch = kroot["chain"]
    for tow, k in KEYS.items():
        assert ch.verify_key(H(k), gst_seconds(1248, tow)), tow


def test_a_key_claimed_at_another_time_fails(kroot):
    # The property the time witness rests on: a key cannot be moved in time.
    ch = kroot["chain"]
    k2 = H(KEYS[345630])
    for tow in (345600, 345660, 345630 + 3600):
        assert not ch.verify_key(k2, gst_seconds(1248, tow))


def test_an_altered_key_fails(kroot):
    k = H(KEYS[345690])
    assert not kroot["chain"].verify_key(k[:-1] + ("1" if k[-1] == "0" else "0"),
                                         gst_seconds(1248, 345690))


def test_mack_interpretation_a6_1():
    m = parse_mack(MACK, 40, 128)
    got = [(t["ctr"], t["prnd"], t["adkd"], t["cop"], hex(u(t["tag"]))) for t in m["tags"]]
    assert got == [(1, None, 0, 15, "0xe37bc4f858"), (2, 18, 0, 5, "0x726a9000c"),
                   (3, 2, 4, 15, "0x7bb238c883"), (4, 5, 0, 15, "0xc8fb247323"),
                   (5, 2, 12, 15, "0x91f230fe4d"), (6, 34, 0, 15, "0x2f1c4d28c1")]
    assert hex(u(m["macseq"])) == "0xb08"
    assert m["key"] == H("2E9C651C410CFF23D370497D28AB4B14")


def test_macseq_tag0_and_adkd4_a6():
    t = gst_seconds(1248, 345660)
    k4 = H(KEYS[345690])
    m = parse_mack(MACK, 40, 128)
    flex = m["tags"][1]["info"] + m["tags"][3]["info"]
    assert trunc(12, mac(0, k4, ubits(2, 8) + gst32(t) + flex)) == m["macseq"]
    tag0 = trunc(40, mac(0, k4, ubits(2, 8) + gst32(t) + ubits(1, 8) + NMA[:2] + NAV0))
    assert tag0 == m["tags"][0]["tag"]
    m4 = ubits(2, 8) + ubits(2, 8) + gst32(t) + ubits(3, 8) + NMA[:2] + NAV4
    assert bits_to_bytes(m4).hex().upper() == "02024E05463C03BFFFFFFFC00000449238227897FDEFF93040"
    assert trunc(40, mac(0, k4, m4)) == m["tags"][2]["tag"]


def test_a_tag_under_the_wrong_key_does_not_match():
    t = gst_seconds(1248, 345660)
    k = H(KEYS[345630])
    tag0 = trunc(40, mac(0, k, ubits(2, 8) + gst32(t) + ubits(1, 8) + NMA[:2] + NAV0))
    assert tag0 != parse_mack(MACK, 40, 128)["tags"][0]["tag"]


# ---- Annex B official test vectors --------------------------------------------------

VEC = Path(os.environ.get("TW_OSNMA_VECTORS",
                          Path(__file__).resolve().parents[1] / "vectors" / "osnma-official"))
TV = VEC / "Test_vectors"
needs_vectors = pytest.mark.skipif(not TV.is_dir(), reason=(
    "official OSNMA test vectors not present; run scripts/fetch_osnma_vectors.py"))

# Merkle tree per scenario, from Receiver Guidelines Annex B (B.3, B.4).
TREE = {"configuration_1": 1, "nmt_step3": 3, "oam_step1": 3, "oam_step2": 3}
# What must happen, per scenario. usable = keys that count toward a time bound.
EXPECT = {
    "configuration_1": dict(usable=2171, excluded={}),
    "configuration_2": dict(usable=1981, excluded={}),
    "crev_step1": dict(usable=0, excluded={"CHAIN_REVOKED": 1170, "DONT_USE": 1195}),
    "crev_step2": dict(usable=1176, excluded={}),
    "crev_step3": dict(usable=2347, excluded={}),
    "eoc_step1": dict(usable=2363, excluded={}),
    "eoc_step2": dict(usable=2360, excluded={}),
    "nmt_step1": dict(usable=2370, excluded={}),
    "nmt_step2": dict(usable=2350, excluded={}),
    "nmt_step3": dict(usable=2264, excluded={}),
    "npk_step1": dict(usable=2225, excluded={}),
    "npk_step2": dict(usable=2350, excluded={}),
    "npk_step3": dict(usable=2330, excluded={}),
    "oam_step1": dict(usable=1157, excluded={"AFTER_ALERT": 1195}),
    "oam_step2": dict(usable=0, excluded={"AFTER_ALERT": 1139, "AFTER_ALERT_UNVERIFIED": 20}),
    "pkrev_step1": dict(usable=0, excluded={"PUBLIC_KEY_REVOKED": 1174, "DONT_USE": 1167}),
    "pkrev_step2": dict(usable=1184, excluded={}),
    "pkrev_step3": dict(usable=2364, excluded={}),
}


def _tree(n):
    root, keys = None, []
    for x in sorted(glob.glob(str(TV / "cryptographic_material" / f"Merkle_tree_{n}"
                                  / "MerkleTree" / "*.xml"))):
        r, ks = keys_from_gsc_xml(Path(x).read_text(encoding="utf-8"))
        assert root in (None, r)
        root, keys = r, keys + ks
    return root, keys


def _pages(scenario):
    (f,) = glob.glob(str(TV / "osnma_test_vectors" / scenario / "*.csv"))
    out = []
    with open(f, newline="") as fh:
        for row in csv.DictReader(fh):
            bits = hex_to_bits(row["NavBitsHEX"], int(row["NumNavBits"]))
            start = page_time_from_word5(pages_from_bits(int(row["SVID"]), bits, 0))
            if start is not None:          # a satellite sending only dummy words has no time
                out += pages_from_bits(int(row["SVID"]), bits, start)
    return out


@needs_vectors
@pytest.mark.parametrize("scenario", sorted(EXPECT))
def test_official_vector(scenario):
    root, keys = _tree(TREE.get(scenario, 2))
    rep = verify_stream(_pages(scenario), root, extra_keys=keys)
    assert rep.kroots and all(k["signature_ok"] and k["pdk_ok"] for k in rep.kroots)
    assert rep.key_failures == []
    assert not any(rep.tags.get(k) for k in ("TAG_MISMATCH", "MACSEQ_MISMATCH",
                                             "MACLT_MISMATCH"))
    assert rep.tags.get("TAG_CONSISTENT", 0) > 5000
    assert len(rep.keys) == EXPECT[scenario]["usable"]
    assert dict(Counter(e[3] for e in rep.excluded)) == EXPECT[scenario]["excluded"]


@needs_vectors
def test_every_page_of_the_official_vectors_passes_crc():
    for scenario in ("configuration_1", "pkrev_step1"):
        ps = _pages(scenario)
        assert ps and all(p.crc_ok for p in ps)


@needs_vectors
def test_a_corrupted_page_is_rejected_not_used():
    ps = _pages("configuration_2")
    p = ps[100]
    bad = Page(p.sv, p.start, p.even, p.odd[:30] + ("1" if p.odd[30] == "0" else "0") + p.odd[31:])
    assert p.crc_ok and not bad.crc_ok


@needs_vectors
def test_lower_bound_is_the_latest_usable_key_and_absent_when_all_are_withdrawn():
    root, keys = _tree(1)
    rep = verify_stream(_pages("configuration_1"), root, extra_keys=keys, check_tags=False)
    b = galileo_lower_bound(rep)
    # 16 Aug 2023 is a Wednesday: 3 days + 05:59:30 into GST week 1251
    assert (b["wn"], b["tow"]) == (1251, 3 * 86400 + 5 * 3600 + 59 * 60 + 30)
    root, keys = _tree(2)
    rep = verify_stream(_pages("crev_step1"), root, extra_keys=keys, check_tags=False)
    assert galileo_lower_bound(rep) is None
