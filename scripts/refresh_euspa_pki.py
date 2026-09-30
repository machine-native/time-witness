#!/usr/bin/env python3
"""Fetch the public EUSPA PKI material above the OSNMA Merkle tree into trust/euspa/.

Root CA and Galileo SCA certificates and CRLs come from pki.euspa.europa.eu (listed
on EUSPA's PKI products page); the OSNMA ICA certificate and CRL from the GSC's
public gsc-products/pki path named in the OSNMA IDD ICD section 3.2.3. None of these
needs a login. The Root CA must match the fingerprint pinned in tw/gsc_pki.py, or
nothing is written.

CRLs are re-issued yearly; run this again before authenticating a Merkle tree, and
the checks will use current revocation lists.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from tw.gsc_pki import EUSPA_RCA_001_01_SHA256, _to_pem, cert_fingerprint  # noqa: E402

DEST = ROOT / "trust" / "euspa"
FILES = {
    "rca_001_01.crt": "https://pki.euspa.europa.eu/rca_001_01.crt",
    "rca_001_01.crl": "http://pki.euspa.europa.eu/rca_001_01.crl",
    "sca_001_01.crt": "http://pki.euspa.europa.eu/sca_001_01.crt",
    "sca_001_01.crl": "http://pki.euspa.europa.eu/sca_001_01.crl",
    "ica_001_01.crt": "https://www.gsc-europa.eu/sites/default/files/sites/all/files/ica_001_01.crt",
    "ica_001_01.crl": "https://www.gsc-europa.eu/sites/default/files/sites/all/files/ica_001_01.crl",
}


def main() -> int:
    got = {}
    for name, url in FILES.items():
        req = urllib.request.Request(url, headers={"User-Agent": "time-witness/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            got[name] = _to_pem(r.read(), "crl" if name.endswith(".crl") else "x509")
    fp = cert_fingerprint(got["rca_001_01.crt"])
    if fp != EUSPA_RCA_001_01_SHA256:
        print(f"refusing: Root CA fingerprint {fp} != pinned {EUSPA_RCA_001_01_SHA256}",
              file=sys.stderr)
        return 1
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in got.items():
        (DEST / name).write_bytes(data)
    print(f"Root CA fingerprint matches the pin; {len(got)} files written to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
