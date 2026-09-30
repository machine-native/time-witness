"""Authenticating the OSNMA trust anchor: the Merkle tree file from the GSC.

The Merkle root is the one OSNMA secret-free input that is not broadcast by the
satellites; it comes from the European GNSS Service Centre (Galileo OSNMA IDD ICD,
Issue 1.1, section 3). Everything `tw.osnma` concludes rests on it, so it is never
taken because a file said so. This module performs the check the IDD ICD asks of
manufacturers (section 4.3):

  1. the end-entity Merkle-tree certificate chains to the EUSPA Root CA through
     the Galileo SCA and the OSNMA ICA, with every certificate checked against its
     issuer's CRL (openssl verify -crl_check_all);
  2. the end-entity certificate is the Merkle-tree role, not some other EUSPA key;
  3. its key's ECDSA P-256/SHA-256 signature (the `.xml.p256` file, hex r||s)
     covers the Merkle-tree XML byte for byte;
  4. the Root CA is the one pinned below, by SHA-256 fingerprint.

The Root CA is self-signed; its only authentication is the channel it came from.
The fingerprint below is what https://pki.euspa.europa.eu/rca_001_01.crt served on
2026-09-30. Pinning it means a later substitution is detected; it does not make the
first fetch more than trust on first use, and anyone relying on it should compare
it through a second channel.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from .osnma import _der_int, _der_len, keys_from_gsc_xml

EUSPA_RCA_001_01_SHA256 = ("63AE2D3EE75A3A8C5D05F68F18DBD67E058282104A4604E7CD962BCCB0E933D4")
EE_MERKLE_CN = "EUSPA OSNMA EE MERKLE TREE"

_PEM = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


def _pem_certs(b: bytes) -> list[bytes]:
    return [m.group(0) + b"\n" for m in _PEM.finditer(b)]


def _to_pem(b: bytes, kind: str) -> bytes:
    """Accept PEM or DER for a certificate ('x509') or CRL ('crl')."""
    # OpenSSL on Windows writes CRLF; normalise so the stored bytes are the same on
    # every platform (the pin is over DER and is unaffected either way).
    if b.lstrip().startswith(b"-----BEGIN"):
        b = b.replace(b"\r\n", b"\n")
        return b if b.endswith(b"\n") else b + b"\n"
    r = subprocess.run(["openssl", kind, "-inform", "DER"], input=b, capture_output=True)
    if r.returncode:
        raise ValueError(f"not a PEM or DER {kind}")
    return r.stdout.replace(b"\r\n", b"\n")


def cert_fingerprint(pem: bytes) -> str:
    der = subprocess.run(["openssl", "x509", "-outform", "DER"], input=pem,
                         capture_output=True, check=True).stdout
    return hashlib.sha256(der).hexdigest().upper()


def _subject_cn(pem: bytes) -> str:
    out = subprocess.run(["openssl", "x509", "-noout", "-subject", "-nameopt", "multiline"],
                         input=pem, capture_output=True, check=True).stdout.decode()
    m = re.search(r"commonName\s*=\s*(.+)", out)
    return m.group(1).strip() if m else ""


def verify_merkle_tree(xml: bytes, sig_hex: str, ee_bundle: bytes, *, rca: bytes, sca: bytes,
                       crls: list[bytes], at_unix: int | None = None,
                       pinned_rca_sha256: str = EUSPA_RCA_001_01_SHA256) -> dict:
    """Authenticate a GSC Merkle-tree XML. Returns every check, and the root and
    keys only if all of them pass. `at_unix` validates the certificates at that
    time instead of now (for re-checking a past decision)."""
    checks: dict[str, bool] = {}
    rca_pem, sca_pem = _to_pem(rca, "x509"), _to_pem(sca, "x509")
    bundle = _pem_certs(ee_bundle)
    checks["BUNDLE_HAS_EE_AND_ICA"] = len(bundle) >= 2
    if not checks["BUNDLE_HAS_EE_AND_ICA"]:
        return {"checks": checks, "ok": False}
    ee, icas = bundle[0], b"".join(bundle[1:])

    checks["RCA_PINNED"] = cert_fingerprint(rca_pem) == pinned_rca_sha256.upper()
    checks["EE_IS_MERKLE_TREE_ROLE"] = _subject_cn(ee) == EE_MERKLE_CN

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "rca.pem").write_bytes(rca_pem)
        (d / "untrusted.pem").write_bytes(sca_pem + icas)
        (d / "ee.pem").write_bytes(ee)
        args = ["openssl", "verify", "-crl_check_all", "-x509_strict",
                "-CAfile", str(d / "rca.pem"), "-untrusted", str(d / "untrusted.pem")]
        for i, c in enumerate(crls):
            (d / f"crl{i}.pem").write_bytes(_to_pem(c, "crl"))
            args += ["-CRLfile", str(d / f"crl{i}.pem")]
        if at_unix is not None:
            args += ["-attime", str(at_unix)]
        r = subprocess.run(args + [str(d / "ee.pem")], capture_output=True)
        checks["CHAIN_AND_CRLS"] = r.returncode == 0
        chain_error = (r.stdout + r.stderr).decode(errors="replace").strip()

        sig = bytes.fromhex(sig_hex.strip())
        body = _der_int(sig[:len(sig) // 2]) + _der_int(sig[len(sig) // 2:])
        (d / "sig.der").write_bytes(b"\x30" + _der_len(len(body)) + body)
        pub = subprocess.run(["openssl", "x509", "-pubkey", "-noout", "-in", str(d / "ee.pem")],
                             capture_output=True).stdout
        (d / "pub.pem").write_bytes(pub)
        (d / "tree.xml").write_bytes(xml)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(d / "pub.pem"),
                            "-signature", str(d / "sig.der"), str(d / "tree.xml")],
                           capture_output=True)
        checks["XML_SIGNATURE"] = r.returncode == 0

    ok = all(checks.values())
    out = {"checks": checks, "ok": ok, "chain_detail": chain_error,
           "xml_sha256": hashlib.sha256(xml).hexdigest()}
    if ok:
        root, keys = keys_from_gsc_xml(xml.decode("utf-8"))
        out.update(root=root, keys=keys)
    return out
