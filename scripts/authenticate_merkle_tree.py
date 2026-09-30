#!/usr/bin/env python3
"""Authenticate an OSNMA Merkle tree downloaded from the GSC, and record the result.

The GSC publishes the tree to registered users (web portal "GSC Products ->
OSNMA_MerkleTree -> Applicable", or its SFTP server). Download three files that
share one name: the .xml, the .xml.p256 signature, and the .crt certificate bundle.
Then:

    python scripts/refresh_euspa_pki.py
    python scripts/authenticate_merkle_tree.py path/to/OSNMA_MerkleTree_<date>_<pkid>.xml

Every check in tw/gsc_pki.py must pass. On success the tree is copied into
trust/merkle-tree/ with a JSON record of what was checked, when, against which
certificates — so a later verifier can see which root a Galileo bound rests on
and re-run the same checks. Nothing is written on failure.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from tw.gsc_pki import verify_merkle_tree  # noqa: E402

PKI = ROOT / "trust" / "euspa"


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    xml = Path(argv[0])
    sig, crt = Path(str(xml) + ".p256"), xml.with_suffix(".crt")
    for f in (xml, sig, crt):
        if not f.exists():
            print(f"missing {f}", file=sys.stderr)
            return 2
    if not (PKI / "rca_001_01.crt").exists():
        print("run scripts/refresh_euspa_pki.py first", file=sys.stderr)
        return 2
    r = verify_merkle_tree(
        xml.read_bytes(), sig.read_text(), crt.read_bytes(),
        rca=(PKI / "rca_001_01.crt").read_bytes(), sca=(PKI / "sca_001_01.crt").read_bytes(),
        crls=[(PKI / n).read_bytes() for n in ("rca_001_01.crl", "sca_001_01.crl",
                                                 "ica_001_01.crl")])
    for k, v in r["checks"].items():
        print(f"  {k:24s} {'PASS' if v else 'FAIL'}")
    if not r["ok"]:
        print("NOT authenticated:", r["chain_detail"], file=sys.stderr)
        return 1
    dest = ROOT / "trust" / "merkle-tree"
    dest.mkdir(parents=True, exist_ok=True)
    for f in (xml, sig, crt):
        shutil.copy2(f, dest / f.name)
    record = {
        "type": "TW-OSNMA-TRUST-ANCHOR/v1",
        "merkle_root": r["root"].hex().upper(),
        "public_keys": [{"pkid": k["npkid"], "leaf": k["mid"]} for k in r["keys"]],
        "xml": xml.name, "xml_sha256": r["xml_sha256"],
        "checks": r["checks"],
        "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "pki_files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(PKI.iterdir())},
    }
    out = dest / (xml.stem + ".authenticated.json")
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"authenticated; Merkle root {record['merkle_root']}\nrecord: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
