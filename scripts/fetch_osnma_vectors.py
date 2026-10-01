#!/usr/bin/env python3
"""Fetch the official Galileo OSNMA test vectors, and refuse any other bytes.

The vectors are Annex B of the OSNMA Receiver Guidelines Issue 1.3 (c) European
Union 2024, published by the European GNSS Service Centre. They are not
redistributed in this repository: the guidelines' terms forbid altering them, and
there is no reason to hold a copy that could drift from the published one.

The digest below was recorded when this verifier was first run against them on
2026-09-30. If the GSC ever republishes the file, this refuses it until the new
digest is reviewed and recorded here, with the reason, in docs/SOURCES.md.

    python scripts/fetch_osnma_vectors.py          # -> vectors/osnma-official/
"""
from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://www.gsc-europa.eu/sites/default/files/sites/all/files/Test_vectors.zip"
SHA256 = "ef9b9afc6ef9e1c57393415cf2a1dc80c4035e7c06123907ea0bb97dd3ccf370"
DEST = Path(__file__).resolve().parents[1] / "vectors" / "osnma-official"


LOCAL = Path(__file__).resolve().parents[1] / "reference" / "galileo" / "Test_vectors.zip"


def main() -> int:
    # The workspace keeps its own copy (reference/, digest-checked like any other
    # source); the network is only the fallback.
    if LOCAL.exists():
        data = LOCAL.read_bytes()
        print(f"using local copy {LOCAL}")
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "time-witness/0.1"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != SHA256:
        print(f"refusing: sha256 {got} != recorded {SHA256}", file=sys.stderr)
        return 1
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(DEST)
    print(f"verified {len(data)} bytes, extracted to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
