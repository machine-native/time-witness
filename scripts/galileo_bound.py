#!/usr/bin/env python3
"""The Galileo lower bound a galmon capture supports, against the authenticated anchor.

    python scripts/galileo_bound.py live/galmon-<label>

Uses the authenticated Merkle tree in trust/merkle-tree/ (scripts/authenticate_
merkle_tree.py), re-running its authentication now against trust/euspa/, then
reads <capture>/e1b-frames.bert, rebuilds and CRC-checks every page, and runs every
OSNMA check (tw.osnma.verify_stream). Writes <capture>/galileo-bound.json.

What it reports, and only that:
  - the Merkle root used, and whether every trust-anchor check passed;
  - whether a DSM-PKR broadcast by the satellites in this capture reaches the same
    root (the independent second channel for the anchor), if one was captured;
  - verified KROOTs, usable and excluded keys, tag consistency counts;
  - the bound: the GST at the start of the sub-frame of the latest usable key.
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

from tw import osnma  # noqa: E402
from tw.galmon_feed import pages_from_stream  # noqa: E402
from tw.gsc_pki import verify_merkle_tree  # noqa: E402

PKI = ROOT / "trust" / "euspa"
MT = ROOT / "trust" / "merkle-tree"


def authenticated_tree():
    recs = sorted(MT.glob("*.authenticated.json"))
    if not recs:
        raise SystemExit("no authenticated Merkle tree; run scripts/authenticate_merkle_tree.py")
    rec = json.loads(recs[-1].read_text(encoding="utf-8"))
    xml = MT / rec["xml"]
    r = verify_merkle_tree(xml.read_bytes(), Path(str(xml) + ".p256").read_text(),
                           xml.with_suffix(".crt").read_bytes(),
                           rca=(PKI / "rca_001_01.crt").read_bytes(),
                           sca=(PKI / "sca_001_01.crt").read_bytes(),
                           crls=[(PKI / n).read_bytes() for n in
                                 ("rca_001_01.crl", "sca_001_01.crl", "ica_001_01.crl")])
    if not r["ok"]:
        raise SystemExit(f"trust anchor no longer authenticates: {r['checks']}")
    return r, rec


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    cap = Path(argv[0])
    auth, rec = authenticated_tree()
    pages, stats = pages_from_stream((cap / "e1b-frames.bert").read_bytes())
    rep = osnma.verify_stream(pages, auth["root"], extra_keys=auth["keys"])

    # The satellites' own DSM-PKRs, against the website's root.
    sfs = osnma.subframes(pages)
    pkrs = []
    for d in osnma.collect_dsms(sfs):
        if d["dsm_id"] >= 12:
            v = osnma.verify_pkr(d["bits"], auth["root"])
            pkrs.append({"npkid": v["npkid"], "npkt": v["npkt"], "merkle_ok": v["merkle_ok"],
                         "pdp_ok": v["pdp_ok"], "completed_at_gst": d["completed_at"]})
    excluded: dict[str, int] = {}
    for e in rep.excluded:
        excluded[e[3]] = excluded.get(e[3], 0) + 1
    t = lambda s: {"wn": s // osnma.WEEK_S, "tow": s % osnma.WEEK_S}  # noqa: E731
    out = {
        "type": "TW-GALILEO-BOUND-REPORT/v1",
        "capture": cap.name,
        "merkle_root": auth["root"].hex().upper(), "trust_anchor_checks": auth["checks"],
        "trust_anchor_record": rec["xml"],
        "pages": stats,
        "page_span_gst": ({"first": t(pages[0].start), "last": t(pages[-1].start)}
                          if pages else None),
        "satellites": sorted({p.sv for p in pages}),
        "dsm_pkr_from_satellites": pkrs,
        "kroots": [{**k, "gst0": t(k["gst0"])} for k in rep.kroots],
        "usable_keys": len(rep.keys), "excluded": excluded,
        "key_failures": len(rep.key_failures), "alerts": len(rep.alerts),
        "tags": rep.tags,
        "bound": osnma.galileo_lower_bound(rep),
    }
    (cap / "galileo-bound.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if out["bound"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
