"""Offline verification of Galileo OSNMA from raw E1-B I/NAV pages.

Implements the Galileo OSNMA SIS ICD Issue 1.1 (October 2023) and the page and word
layouts of the Galileo OS SIS ICD Issue 2.2 (November 2025), checked against the
worked examples of the OSNMA Receiver Guidelines Issue 1.3 (January 2024, Annex A)
and its official test vectors (Annex B). See docs/SOURCES.md for digests.

WHAT THIS ESTABLISHES, AND WHAT IT DOES NOT

Three things verify offline, from bytes, at any later date:

  1. a public key, against a Merkle root (the trust anchor, obtained out of band);
  2. a DSM-KROOT, by that public key's ECDSA signature — this signs the chain's
     parameters and its time of applicability GST0;
  3. a TESLA key, by hashing it back to KROOT. Each hash step includes the GST of
     the sub-frame the key belongs to, so a key that reaches KROOT is bound to its
     own sub-frame time. It cannot be moved to another time.

Galileo keeps each key secret until it broadcasts it. So bytes that contain a
verified key were assembled AFTER that key's sub-frame began. That is a lower
causal bound supplied by Galileo — the reason this module exists.

What does NOT verify offline is the authenticity of navigation data from its tags.
TESLA tags only authenticate data received BEFORE the key that checks them was
disclosed, and nothing in a recording shows when it was received. A tag that
matches here is recorded as TAG_CONSISTENT, never as authenticated.

Bit strings are Python str of '0'/'1', MSB first, exactly as the ICDs number bits.
"""
from __future__ import annotations

import hashlib
import hmac
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

WEEK_S = 604_800
SUBFRAME_S = 30
PAGE_BITS = 240

# ---- bits -------------------------------------------------------------------


def hex_to_bits(h: str, nbits: int | None = None) -> str:
    b = bin(int(h, 16))[2:].zfill(len(h) * 4) if h else ""
    return b if nbits is None else b[:nbits]


def bits_to_bytes(b: str) -> bytes:
    """Right zero-padding to whole bytes, as every OSNMA hash/MAC/signature input requires."""
    if not b:
        return b""
    pad = (-len(b)) % 8
    return int(b + "0" * pad, 2).to_bytes((len(b) + pad) // 8, "big")


def u(b: str) -> int:
    return int(b, 2) if b else 0


def ubits(v: int, n: int) -> str:
    if v < 0 or v >= (1 << n):
        raise ValueError(f"{v} does not fit {n} bits")
    return format(v, f"0{n}b")


def trunc(nbits: int, data: bytes) -> str:
    return bin(int.from_bytes(data, "big"))[2:].zfill(len(data) * 8)[:nbits]


# ---- time -------------------------------------------------------------------


def gst_seconds(wn: int, tow: int) -> int:
    return wn * WEEK_S + tow


def gst32(t: int) -> str:
    """GST as the ICDs encode it: 12-bit week number then 20-bit time of week."""
    return ubits(t // WEEK_S % 4096, 12) + ubits(t % WEEK_S, 20)


# ---- pages ------------------------------------------------------------------

_P = (1 << 23) | (1 << 17) | (1 << 13) | (1 << 12) | (1 << 11) | (1 << 9) | (1 << 8) \
    | (1 << 7) | (1 << 5) | (1 << 3) | 1
CRC24_G = _P ^ (_P << 1)        # G(X) = (1 + X) P(X), OS SIS ICD §5.1.9.4


def crc24(bits: str) -> int:
    r = 0
    for c in bits:
        top = (r >> 23) & 1
        r = (r << 1) & 0xFFFFFF
        if (c == "1") ^ top:
            r ^= CRC24_G & 0xFFFFFF
    return r


@dataclass(frozen=True)
class Page:
    """One nominal E1-B page: even part then odd part, 120 bits each."""
    sv: int
    start: int          # GST seconds at the start of the page (even part)
    even: str
    odd: str

    @property
    def crc_ok(self) -> bool:
        return crc24(self.even[:114] + self.odd[:82]) == u(self.odd[82:106])

    @property
    def nominal(self) -> bool:
        # even/odd flags 0 then 1; page type 0 in both parts (1 marks an alert page)
        return (self.even[0], self.even[1], self.odd[0], self.odd[1]) == ("0", "0", "1", "0")

    @property
    def word(self) -> str:
        return self.even[2:114] + self.odd[2:18]

    @property
    def osnma(self) -> str:
        return self.odd[18:58]


def pages_from_bits(sv: int, bits: str, first_start: int) -> list[Page]:
    out = []
    for k in range(len(bits) // PAGE_BITS):
        pg = bits[k * PAGE_BITS:(k + 1) * PAGE_BITS]
        out.append(Page(sv, first_start + 2 * k, pg[:120], pg[120:]))
    return out


def page_time_from_word5(pages: list[Page]) -> int | None:
    """GST of a stream's first page, from the WN/TOW in word type 5.

    TOW in word type 5 is the start time of the page carrying it (checked against
    the official test vectors). Returns None if no valid word 5 is present.
    """
    for i, p in enumerate(pages):
        if p.crc_ok and p.nominal and u(p.word[:6]) == 5:
            return gst_seconds(u(p.word[73:85]), u(p.word[85:105])) - 2 * i
    return None


# ---- sub-frames -------------------------------------------------------------


@dataclass
class Subframe:
    sv: int
    gst_sf: int                      # E1 sub-frame start minus 1 s, a multiple of 30
    osnma: dict = field(default_factory=dict)   # page index 0..14 -> 40 bits
    words: dict = field(default_factory=dict)   # word type -> 128 bits
    bad_pages: int = 0
    dummy_pages: int = 0

    @property
    def complete(self) -> bool:
        return len(self.osnma) == 15 and self.bad_pages == 0 and self.dummy_pages == 0

    @property
    def transmits_osnma(self) -> bool:
        return self.complete and any("1" in v for v in self.osnma.values())

    @property
    def hkroot(self) -> str:
        return "".join(self.osnma[i][:8] for i in range(15))

    @property
    def mack(self) -> str:
        return "".join(self.osnma[i][8:] for i in range(15))


def subframes(pages: list[Page]) -> dict[tuple[int, int], Subframe]:
    out: dict[tuple[int, int], Subframe] = {}
    for p in pages:
        gst_sf = (p.start - 1) // SUBFRAME_S * SUBFRAME_S
        idx = (p.start - 1 - gst_sf) // 2
        sf = out.setdefault((p.sv, gst_sf), Subframe(p.sv, gst_sf))
        if not (p.crc_ok and p.nominal):
            sf.bad_pages += 1
            continue
        wt = u(p.word[:6])
        if wt == 63:
            # OSNMA SIS ICD §2: OSNMA is not provided in dummy messages, and any data
            # found in their OSNMA field shall be discarded. (The official test vectors
            # include a satellite sending dummy words with a non-zero OSNMA field.)
            sf.dummy_pages += 1
            continue
        sf.osnma[idx] = p.osnma
        if wt != 0:
            sf.words[wt] = p.word
    return out


# ---- NMA header and DSM -----------------------------------------------------


@dataclass(frozen=True)
class NMAHeader:
    nmas: int
    cid: int
    cpks: int
    bits: str

    @classmethod
    def parse(cls, b: str):
        return cls(u(b[0:2]), u(b[2:4]), u(b[4:7]), b[:8])


def collect_dsms(sfs) -> list[dict]:
    """Reassemble complete DSMs from the HKROOT blocks of every satellite.

    Blocks for one DSM ID are combined across satellites and sub-frames. If a block
    arrives that disagrees with one already held for that DSM ID and block ID, the
    DSM ID has been reused for new content; the partial collection restarts.
    Returns each complete DSM once, with the NMA headers seen alongside it.
    """
    partial: dict[int, dict] = {}
    done: list[dict] = []
    seen = set()
    for (_, gst_sf), sf in sorted(sfs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if not sf.transmits_osnma:
            continue
        hk = sf.hkroot
        nma, dsm_id, bid, block = hk[:8], u(hk[8:12]), u(hk[12:16]), hk[16:120]
        cur = partial.setdefault(dsm_id, {"blocks": {}, "nma": set()})
        if bid in cur["blocks"] and cur["blocks"][bid] != block:
            cur = partial[dsm_id] = {"blocks": {}, "nma": set()}
        cur["blocks"][bid] = block
        cur["nma"].add(nma)
        if 0 in cur["blocks"]:
            nb_field = u(cur["blocks"][0][:4])
            nb = nb_field + 6
            if dsm_id < 12 and not 1 <= nb_field <= 8:
                continue
            if dsm_id >= 12 and not 7 <= nb_field <= 10:
                continue
            if all(i in cur["blocks"] for i in range(nb)):
                bits = "".join(cur["blocks"][i] for i in range(nb))
                if (dsm_id, bits) not in seen:
                    seen.add((dsm_id, bits))
                    done.append({"dsm_id": dsm_id, "bits": bits, "nma": sorted(cur["nma"]),
                                 "completed_at": gst_sf})
    return done


# ---- public keys and the Merkle tree -----------------------------------------

KEY_BITS = {1: 264, 3: 536}                    # NPKT -> compressed key length
KEY_NAME = {1: "P-256", 3: "P-521"}
SIG_BITS = {"P-256": 512, "P-521": 1056}


@dataclass(frozen=True)
class PublicKey:
    pkid: int
    npkt: int
    point: bytes          # compressed SEC1 point

    @property
    def curve(self) -> str:
        return KEY_NAME[self.npkt]


def parse_pkr(bits: str) -> dict:
    nbdp, mid = u(bits[0:4]), u(bits[4:8])
    itn = [bits[8 + 256 * i:8 + 256 * (i + 1)] for i in range(4)]
    npkt, npkid = u(bits[1032:1036]), u(bits[1036:1040])
    if npkt == 4:                                 # OSNMA Alert Message: NPK fills the rest
        npk = bits[1040:]
        pdp = ""
    elif npkt in KEY_BITS:
        npk = bits[1040:1040 + KEY_BITS[npkt]]
        pdp = bits[1040 + KEY_BITS[npkt]:]
    else:
        raise ValueError(f"reserved NPKT {npkt}")
    return {"nbdp": nbdp, "mid": mid, "itn": itn, "npkt": npkt, "npkid": npkid,
            "npk": npk, "pdp": pdp}


def merkle_root_from_pkr(p: dict) -> tuple[bytes, str]:
    """Recompute the Merkle root x4,0 from a DSM-PKR's leaf and intermediate nodes."""
    leaf = ubits(p["npkt"], 4) + ubits(p["npkid"], 4) + p["npk"]
    node = hashlib.sha256(bits_to_bytes(leaf)).digest()
    idx = p["mid"]
    for sib in p["itn"]:
        s = bits_to_bytes(sib)
        node = hashlib.sha256(node + s if idx % 2 == 0 else s + node).digest()
        idx //= 2
    return node, leaf


PKTYPE_NPKT = {"ECDSA P-256/SHA-256": 1, "ECDSA P-521/SHA-512": 3}


def keys_from_gsc_xml(xml_text: str) -> tuple[bytes, list[dict]]:
    """Merkle root and public keys (each with its Merkle path) from a GSC OSNMA
    Merkle-tree XML file. The keys are NOT trusted here: `verify_stream` checks
    every one against the root before using it, exactly as it checks a DSM-PKR."""
    import xml.etree.ElementTree as ET
    body = ET.fromstring(xml_text).find("body/MerkleTree")
    nodes = {(int(n.findtext("j")), int(n.findtext("i"))): n.findtext("x_ji")
             for n in body.findall("TreeNode")}
    root = bytes.fromhex(nodes[(4, 0)])
    keys = []
    for pk in body.findall("PublicKey"):
        i = int(pk.findtext("i"))
        itn = [hex_to_bits(nodes[(j, (i >> j) ^ 1)], 256) for j in range(4)]
        npkt = PKTYPE_NPKT[pk.findtext("PKType")]
        keys.append({"mid": i, "itn": itn, "npkt": npkt, "npkid": int(pk.findtext("PKID")),
                     "npk": hex_to_bits(pk.findtext("point"), KEY_BITS[npkt]), "pdp": ""})
    return root, keys


def verify_pkr(bits: str, merkle_root: bytes) -> dict:
    p = parse_pkr(bits)
    root, leaf = merkle_root_from_pkr(p)
    ok = hmac.compare_digest(root, merkle_root)
    pdp_ok = (not p["pdp"]) or p["pdp"] == trunc(len(p["pdp"]),
                                                 hashlib.sha256(merkle_root + bits_to_bytes(leaf)).digest())
    out = {**p, "merkle_ok": ok, "pdp_ok": pdp_ok, "alert": p["npkt"] == 4}
    if ok and p["npkt"] in KEY_BITS:
        out["key"] = PublicKey(p["npkid"], p["npkt"], bits_to_bytes(p["npk"]))
    return out


# ---- ECDSA via the OpenSSL CLI (the same pattern chronology-protocol uses) --

_SPKI = {
    "P-256": bytes.fromhex("3039301306072a8648ce3d020106082a8648ce3d030107032200"),
    "P-521": bytes.fromhex("3058301006072a8648ce3d020106052b81040023034400"),
}
_DIGEST = {"P-256": "-sha256", "P-521": "-sha512"}


def _der_int(v: bytes) -> bytes:
    v = v.lstrip(b"\x00") or b"\x00"
    if v[0] & 0x80:
        v = b"\x00" + v
    return b"\x02" + _der_len(len(v)) + v


def _der_len(n: int) -> bytes:
    return bytes([n]) if n < 0x80 else b"\x81" + bytes([n])


def ecdsa_verify(key: PublicKey, message: bytes, signature: bytes) -> bool:
    half = len(signature) // 2
    body = _der_int(signature[:half]) + _der_int(signature[half:])
    der_sig = b"\x30" + _der_len(len(body)) + body
    spki = _SPKI[key.curve] + key.point
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "k.der").write_bytes(spki)
        (d / "m").write_bytes(message)
        (d / "s").write_bytes(der_sig)
        r = subprocess.run(["openssl", "dgst", _DIGEST[key.curve], "-verify", str(d / "k.der"),
                            "-keyform", "DER", "-signature", str(d / "s"), str(d / "m")],
                           capture_output=True)
        return r.returncode == 0


# ---- DSM-KROOT ----------------------------------------------------------------

KS_BITS = {0: 96, 1: 104, 2: 112, 3: 120, 4: 128, 5: 160, 6: 192, 7: 224, 8: 256}
TS_BITS = {5: 20, 6: 24, 7: 28, 8: 32, 9: 40}


@dataclass(frozen=True)
class Chain:
    """A TESLA chain, as signed in a DSM-KROOT."""
    pkid: int
    cid: int
    hf: int
    mf: int
    lk: int
    lt: int
    maclt: int
    gst0: int
    alpha: str
    kroot: str

    def hash(self, b: bytes) -> bytes:
        if self.hf == 0:
            return hashlib.sha256(b).digest()
        if self.hf == 2:
            return hashlib.sha3_256(b).digest()
        raise ValueError(f"reserved HF {self.hf}")

    def index(self, gst_sf: int) -> int:
        d = gst_sf - self.gst0
        if d % SUBFRAME_S:
            raise ValueError("key time is not on a sub-frame boundary")
        return d // SUBFRAME_S + 1

    def step(self, key: str, gst_sf_prev: int) -> str:
        """K_{I-1} = trunc(lk, hash(K_I || GST_SF of K_{I-1} || alpha))."""
        return trunc(self.lk, self.hash(bits_to_bytes(key + gst32(gst_sf_prev) + self.alpha)))

    def verify_key(self, key: str, gst_sf: int, known: dict | None = None) -> bool:
        """Hash `key` back to KROOT, or to an earlier key already verified."""
        i = self.index(gst_sf)
        if i < 1 or len(key) != self.lk:
            return False
        known = known or {}
        k, t = key, gst_sf
        for _ in range(i):
            t -= SUBFRAME_S
            k = self.step(k, t)
            if known.get(t) == k:
                return True
        return k == self.kroot


def parse_kroot(bits: str) -> dict:
    ks, ts = u(bits[16:20]), u(bits[20:24])
    if ks not in KS_BITS or ts not in TS_BITS:
        raise ValueError("reserved key or tag size")
    lk = KS_BITS[ks]
    return {"nbdk": u(bits[0:4]), "pkid": u(bits[4:8]), "cidkr": u(bits[8:10]),
            "hf": u(bits[12:14]), "mf": u(bits[14:16]), "lk": lk, "lt": TS_BITS[ts],
            "maclt": u(bits[24:32]), "wnk": u(bits[36:48]), "towhk": u(bits[48:56]),
            "alpha": bits[56:104], "kroot": bits[104:104 + lk], "rest": bits[104 + lk:]}


def verify_kroot(bits: str, nma_header: str, key: PublicKey) -> dict:
    p = parse_kroot(bits)
    lds = SIG_BITS[key.curve]
    ds, pdk = p["rest"][:lds], p["rest"][lds:]
    m = nma_header + bits[8:104 + p["lk"]]
    sig_ok = key.pkid == p["pkid"] and ecdsa_verify(key, bits_to_bytes(m), bits_to_bytes(ds))
    pdk_ok = pdk == trunc(len(pdk), hashlib.sha256(bits_to_bytes(m + ds)).digest())
    chain = Chain(p["pkid"], p["cidkr"], p["hf"], p["mf"], p["lk"], p["lt"], p["maclt"],
                  gst_seconds(p["wnk"], p["towhk"] * 3600), p["alpha"], p["kroot"])
    return {**p, "signature_ok": sig_ok, "pdk_ok": pdk_ok, "chain": chain,
            "nma": NMAHeader.parse(nma_header)}


# ---- MACK, MAC functions, tags --------------------------------------------------


def parse_mack(mack: str, lt: int, lk: int) -> dict:
    nt = (480 - lk) // (lt + 16)
    tags = [{"ctr": 1, "tag": mack[:lt], "prnd": None, "adkd": 0, "cop": u(mack[lt + 12:lt + 16])}]
    off = lt + 16
    for ctr in range(2, nt + 1):
        info = mack[off + lt:off + lt + 16]
        tags.append({"ctr": ctr, "tag": mack[off:off + lt], "info": info,
                     "prnd": u(info[:8]), "adkd": u(info[8:12]), "cop": u(info[12:16])})
        off += lt + 16
    return {"tags": tags, "macseq": mack[lt:lt + 12], "key": mack[off:off + lk]}


def mac(mf: int, key: str, m: str) -> bytes:
    k, msg = bits_to_bytes(key), bits_to_bytes(m)
    if mf == 0:
        return hmac.new(k, msg, hashlib.sha256).digest()
    if mf == 1:
        cipher = {16: "AES-128-CBC", 24: "AES-192-CBC", 32: "AES-256-CBC"}[len(k)]
        r = subprocess.run(["openssl", "mac", "-cipher", cipher, "-macopt", f"hexkey:{k.hex()}",
                            "-in", "-", "-binary", "CMAC"], input=msg, capture_output=True)
        if r.returncode:
            raise RuntimeError("openssl CMAC failed: " + r.stderr.decode(errors="replace"))
        return r.stdout
    raise ValueError(f"reserved MF {mf}")


# MAC look-up table, OSNMA SIS ICD Annex C (Table 16). One tuple per MACK message.
MACLT = {
    27: (("00S", "00E", "00E", "00E", "12S", "00E"), ("00S", "00E", "00E", "04S", "12S", "00E")),
    28: (("00S", "00E", "00E", "00E", "00S", "00E", "00E", "12S", "00E", "00E"),
         ("00S", "00E", "00E", "00S", "00E", "00E", "04S", "12S", "00E", "00E")),
    31: (("00S", "00E", "00E", "12S", "00E"), ("00S", "00E", "00E", "12S", "04S")),
    33: (("00S", "00E", "04S", "00E", "12S", "00E"), ("00S", "00E", "00E", "12S", "00E", "12E")),
    34: (("00S", "FLX", "04S", "FLX", "12S", "00E"), ("00S", "FLX", "00E", "12S", "00E", "12E")),
    35: (("00S", "FLX", "04S", "FLX", "12S", "FLX"), ("00S", "FLX", "FLX", "12S", "FLX", "FLX")),
    36: (("00S", "FLX", "04S", "FLX", "12S"), ("00S", "FLX", "00E", "12S", "12E")),
    37: (("00S", "00E", "04S", "00E", "12S"), ("00S", "00E", "00E", "12S", "12E")),
    38: (("00S", "FLX", "04S", "FLX", "12S"), ("00S", "FLX", "FLX", "12S", "FLX")),
    39: (("00S", "FLX", "04S", "FLX"), ("00S", "FLX", "00E", "12S")),
    40: (("00S", "00E", "04S", "12S"), ("00S", "00E", "00E", "12E")),
    41: (("00S", "FLX", "04S", "FLX"), ("00S", "FLX", "FLX", "12S")),
}


def maclt_sequence(maclt: int, gst_sf: int):
    seqs = MACLT.get(maclt)
    if seqs is None:
        return None
    return seqs[0] if gst_sf % 60 == 0 else seqs[1]


def navdata_adkd0(words: dict) -> str | None:
    """549 bits from word types 1-5 (OSNMA SIS ICD Annex B, Figure 19)."""
    need = (1, 2, 3, 4, 5)
    if any(w not in words for w in need):
        return None
    return (words[1][6:126] + words[2][6:126] + words[3][6:128] + words[4][6:126]
            + words[5][6:73])


def navdata_adkd4(words6: dict, words10: dict) -> str | None:
    """141 bits: word 6 GST-UTC and word 10 GST-GPS parameters (Figure 20)."""
    if 6 not in words6 or 10 not in words10:
        return None
    return words6[6][6:105] + words10[10][86:128]


# ---- the whole stream --------------------------------------------------------


@dataclass
class Report:
    public_keys: list = field(default_factory=list)
    kroots: list = field(default_factory=list)
    keys: list = field(default_factory=list)          # (gst_sf, index, prna): verified AND usable
    excluded: list = field(default_factory=list)      # (gst_sf, index, prna, reason): verified, not usable
    key_failures: list = field(default_factory=list)
    tags: dict = field(default_factory=dict)          # outcome -> count
    alerts: list = field(default_factory=list)

    @property
    def latest_key_gst(self) -> int | None:
        """GST of the latest usable key: the lower causal bound this report supports."""
        return max((k[0] for k in self.keys), default=None)


def _bump(d, k):
    d[k] = d.get(k, 0) + 1


def verify_stream(pages: list[Page], merkle_root: bytes, *, extra_keys=(),
                  check_tags: bool = True) -> Report:
    """Run every offline OSNMA check over a set of pages from any number of satellites.

    `extra_keys` are public keys obtained out of band (e.g. `keys_from_gsc_xml`): a
    DSM-PKR is broadcast for only 30 minutes in every 6 hours, so most recordings
    contain none. Each is verified against `merkle_root` before it is used.
    """
    rep = Report()
    sfs = subframes(pages)
    dsms = collect_dsms(sfs)

    keys: dict[int, PublicKey] = {}
    for k in extra_keys:
        root, _ = merkle_root_from_pkr(k)
        if hmac.compare_digest(root, merkle_root):
            keys[k["npkid"]] = PublicKey(k["npkid"], k["npkt"], bits_to_bytes(k["npk"]))
            rep.public_keys.append((k["npkid"], KEY_NAME[k["npkt"]], "OUT_OF_BAND"))
    for d in dsms:
        if d["dsm_id"] >= 12:
            r = verify_pkr(d["bits"], merkle_root)
            if r["alert"] and r["merkle_ok"]:
                rep.alerts.append(d["completed_at"])
            if "key" in r:
                keys[r["key"].pkid] = r["key"]
                rep.public_keys.append((r["key"].pkid, r["key"].curve, r["pdp_ok"]))

    chains: list[Chain] = []
    for d in dsms:
        if d["dsm_id"] < 12:
            pkid = u(d["bits"][4:8])
            if pkid not in keys or len(d["nma"]) != 1:
                continue
            r = verify_kroot(d["bits"], d["nma"][0], keys[pkid])
            rep.kroots.append({"pkid": pkid, "cid": r["cidkr"], "gst0": r["chain"].gst0,
                               "signature_ok": r["signature_ok"], "pdk_ok": r["pdk_ok"]})
            if r["signature_ok"] and r["chain"] not in chains:
                chains.append(r["chain"])

    by_time: dict[int, list[Subframe]] = {}
    for (sv, t), sf in sfs.items():
        if sf.transmits_osnma:
            by_time.setdefault(t, []).append(sf)

    # What the NMA headers say about trust, read before any key is used. OSNMA SIS
    # ICD §3.1 and §5.4-5.7: "Don't Use" withdraws the data it accompanies; a chain
    # or public key revocation means its keys may have been known before their
    # disclosure time, which is exactly what a time bound cannot tolerate; an alert
    # withdraws everything. Signed DSM-KROOTs carry the header they were sent under,
    # so a header that a verified DSM-KROOT covers is authenticated; others are the
    # satellites' word, and are honoured anyway because honouring them only ever
    # removes keys from the bound.
    revoked_cids, revoked_pkids, alert_at = set(), set(), None
    for t in sorted(by_time):
        for sf in by_time[t]:
            h = NMAHeader.parse(sf.hkroot[:8])
            in_force = [c for c in chains if c.cid == h.cid]
            if h.cpks == 3:
                if h.nmas == 3:
                    revoked_cids.add(h.cid)
                else:
                    revoked_cids.update(c.cid for c in chains if c.cid != h.cid)
            elif h.cpks == 5:
                if h.nmas == 3:
                    revoked_pkids.update(c.pkid for c in in_force)
                else:
                    cur = min((c.pkid for c in in_force), default=None)
                    if cur is not None:
                        revoked_pkids.update(c.pkid for c in chains if c.pkid < cur)
            elif h.cpks == 7 and rep.alerts:
                alert_at = t if alert_at is None else min(alert_at, t)
    if rep.alerts:
        alert_at = min(x for x in (alert_at, *rep.alerts) if x is not None)

    def unusable(ch: Chain, t: int, nmas: int) -> str | None:
        if alert_at is not None and t >= alert_at:
            return "AFTER_ALERT"
        if nmas == 3:
            return "DONT_USE"
        if ch.cid in revoked_cids:
            return "CHAIN_REVOKED"
        if ch.pkid in revoked_pkids:
            return "PUBLIC_KEY_REVOKED"
        return None

    verified: dict[tuple, dict[int, str]] = {}      # chain -> {gst_sf: key}
    mack_cache: dict[tuple[int, int], dict] = {}
    for t in sorted(by_time):
        for sf in by_time[t]:
            h = NMAHeader.parse(sf.hkroot[:8])
            for ch in (c for c in chains if c.cid == h.cid and t >= c.gst0 - SUBFRAME_S):
                mk = parse_mack(sf.mack, ch.lt, ch.lk)
                mack_cache[(sf.sv, t)] = {"mack": mk, "chain": ch, "nma": sf.hkroot[:8]}
                store = verified.setdefault(ch, {})
                if store.get(t) == mk["key"] or ch.verify_key(mk["key"], t, store):
                    store[t] = mk["key"]
                    why = unusable(ch, t, h.nmas)
                    if why:
                        rep.excluded.append((t, ch.index(t), sf.sv, why))
                    else:
                        rep.keys.append((t, ch.index(t), sf.sv))
                else:
                    why = unusable(ch, t, h.nmas)
                    if why:
                        rep.excluded.append((t, None, sf.sv, why + "_UNVERIFIED"))
                    else:
                        rep.key_failures.append((t, sf.sv))
                break

    if check_tags:
        _check_tags(sfs, mack_cache, verified, rep)
    return rep


def _check_tags(sfs, mack_cache, verified, rep):
    for (prna, t), entry in mack_cache.items():
        ch, mk, nma = entry["chain"], entry["mack"], entry["nma"]
        store = verified.get(ch, {})
        seq = maclt_sequence(ch.maclt, t)
        nmas = nma[:2]
        flex = []
        for tag in mk["tags"]:
            slot = seq[tag["ctr"] - 1] if seq and tag["ctr"] - 1 < len(seq) else None
            if seq is None or slot is None:
                _bump(rep.tags, "MACLT_UNKNOWN")
                continue
            if slot == "FLX":
                flex.append(tag["info"])
            elif int(slot[:2]) != tag["adkd"] or (slot[2] == "S" and tag["ctr"] > 1
                                                   and tag["prnd"] != prna):
                _bump(rep.tags, "MACLT_MISMATCH")
                continue
            prnd = prna if tag["ctr"] == 1 else tag["prnd"]
            if tag["adkd"] in (0, 12):
                prev = sfs.get((prnd, t - SUBFRAME_S))
                nav = navdata_adkd0(prev.words) if prev else None
            elif tag["adkd"] == 4:
                w6 = sfs.get((prnd, t - SUBFRAME_S))
                w10 = next((s for s in (sfs.get((prnd, t - SUBFRAME_S)),
                                        sfs.get((prnd, t - 2 * SUBFRAME_S)))
                            if s and 10 in s.words), None)
                nav = navdata_adkd4(w6.words, w10.words) if w6 and w10 else None
            else:
                _bump(rep.tags, "ADKD_RESERVED")
                continue
            if tag["cop"] == 0 and nav is None:
                nav = "0" * (549 if tag["adkd"] in (0, 12) else 141)
            elif tag["cop"] == 0:
                nav = "0" * len(nav)
            delay = SUBFRAME_S * (11 if tag["adkd"] == 12 else 1)
            key = store.get(t + delay)
            if nav is None or key is None:
                _bump(rep.tags, "UNVERIFIABLE")
                continue
            head = (ubits(prna, 8) if tag["ctr"] == 1
                    else ubits(prnd, 8) + ubits(prna, 8))
            m = head + gst32(t) + ubits(tag["ctr"], 8) + nmas + nav
            ok = trunc(ch.lt, mac(ch.mf, key, m)) == tag["tag"]
            _bump(rep.tags, "TAG_CONSISTENT" if ok else "TAG_MISMATCH")
        key = store.get(t + SUBFRAME_S)
        if seq is not None and key is not None:
            m = ubits(prna, 8) + gst32(t) + "".join(flex)
            ok = trunc(12, mac(ch.mf, key, m)) == mk["macseq"]
            _bump(rep.tags, "MACSEQ_CONSISTENT" if ok else "MACSEQ_MISMATCH")


def galileo_lower_bound(rep: Report) -> dict | None:
    """The causal claim a report supports: these bytes were assembled no earlier than
    the start of the sub-frame of the latest usable TESLA key.

    Conservative on purpose. The key is spread over the sub-frame's 30 seconds, so the
    bytes cannot predate the sub-frame's start; nothing stronger is claimed. The bound
    is in Galileo System Time and is conditional on the chain never having been
    revoked — revocations after the recording are outside what its bytes can show,
    and must be checked against the GSC's published status.
    """
    t = rep.latest_key_gst
    if t is None:
        return None
    return {"type": "GALILEO-TESLA-LOWER-BOUND/v1", "gst_seconds": t, "wn": t // WEEK_S,
            "tow": t % WEEK_S, "usable_keys": len(rep.keys),
            "condition": "TESLA chain not revoked after the recording"}
