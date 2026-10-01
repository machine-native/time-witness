#!/usr/bin/env python3
"""Bracket an evidence file between Galileo (below) and Bitcoin (above).

    python scripts/bracket.py live/android-m56-2026-10-01/galileo-extract.txt
    python scripts/bracket.py live/galmon-2026-10-01-a/e1b-frames.bert
    python scripts/bracket.py ... --offline        # no explorer lookup

LOWER bound: the evidence contains Galileo TESLA keys that verify to an authenticated
chain; Galileo kept each secret until its sub-frame, so the bytes are no older than
the latest usable key's sub-frame start (galileo-bound.json beside the evidence,
re-derived by the tests). Expressed in UTC with the GST-UTC leap-second count the
satellites broadcast in word type 6 — read from these same pages, consistent with
their tags, but not authenticated offline (SPEC §10.3); the sub-second GST-UTC terms
are not modelled and do not matter at this resolution.

UPPER bound: the OpenTimestamps proof `<evidence>.ots`. Once a calendar has committed
it to Bitcoin, the bytes existed before that block was mined. The block is
identified by height and hash, and its merkle root is confirmed against a public
explorer, as chronology-protocol's confirm_attestations.py does. The block header's
time is miner-asserted (Bitcoin accepts timestamps up to two hours ahead of network
time); it is reported as metadata with that caveat, never as evidence — the same rule
as chronology-protocol invariant 11.

Neither bound involves a server, chain or clock operated by this project.
Writes <evidence>.bracket.json.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from ctp.ots import parse_file  # noqa: E402

from tw.osnma import WEEK_S, u  # noqa: E402
from tw.timescale import GPS_EPOCH_UNIX_S, GST_WEEK_OFFSET  # noqa: E402

EXPLORER = "https://blockstream.info/api"


def _iso(unix_s: int) -> str:
    return datetime.datetime.fromtimestamp(unix_s, datetime.timezone.utc).isoformat()


def pages_for(evidence: Path):
    if evidence.suffix == ".bert":
        from tw.galmon_feed import pages_from_stream
        return pages_from_stream(evidence.read_bytes())[0]
    from tw.android_nav import pages_from_log
    return pages_from_log(evidence.read_text(encoding="utf-8"))[0]


def broadcast_leap_seconds(pages) -> int | None:
    """ΔtLS from word type 6 (signed 8 bits after A0[32] and A1[24]); the most common
    value if satellites disagree, None if no word 6 is present."""
    vals = []
    for p in pages:
        if p.crc_ok and p.nominal and u(p.word[:6]) == 6:
            v = u(p.word[62:70])
            vals.append(v - 256 if v > 127 else v)
    return max(set(vals), key=vals.count) if vals else None


def bitcoin_block(height: int, explorer: str) -> dict:
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "time-witness/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode()
    h = get(f"{explorer}/block-height/{height}").strip()
    b = json.loads(get(f"{explorer}/block/{h}"))
    return {"hash": h, "merkle_root": b["merkle_root"], "header_time": b["timestamp"]}


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    offline = "--offline" in argv
    evidence = Path([a for a in argv if not a.startswith("--")][0])
    report = (evidence.parent / "galileo-bound.json")
    bound = json.loads(report.read_text(encoding="utf-8"))["bound"]
    pages = pages_for(evidence)
    leap = broadcast_leap_seconds(pages)
    out: dict = {"type": "TW-GALILEO-BITCOIN-BRACKET/v1", "evidence": evidence.name,
                 "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
    lower = {"source": "Galileo OSNMA TESLA key possession", "gst_wn": bound["wn"],
             "gst_tow": bound["tow"], "usable_keys": bound["usable_keys"],
             "condition": bound["condition"]}
    if leap is not None:
        unix = GPS_EPOCH_UNIX_S + GST_WEEK_OFFSET * WEEK_S + bound["gst_seconds"] - leap
        lower.update(utc=_iso(unix), utc_unix_s=unix, gst_minus_utc_s=leap,
                     leap_source="broadcast word type 6 (consistent, not authenticated offline)")
    out["lower"] = lower

    ots = Path(str(evidence) + ".ots")
    proof = parse_file(ots)
    upper: dict = {"source": "OpenTimestamps -> Bitcoin", "proof": ots.name,
                   "proof_commits_to_this_file":
                       proof.file_digest == hashlib.sha256(evidence.read_bytes()).digest()}
    if not proof.bitcoin:
        upper.update(status="PENDING", calendars=proof.pending,
                     note="calendars have not yet committed to Bitcoin; upgrade later "
                          "with chronology-protocol's scripts/ots_upgrade.py")
    else:
        height, root = proof.bitcoin[0]
        upper.update(status="BITCOIN", block_height=height, required_merkle_root=root,
                     all_attestations=[h for h, _ in proof.bitcoin])
        if offline:
            upper["explorer_check"] = "NOT_RUN (--offline)"
        else:
            try:
                blk = bitcoin_block(height, EXPLORER)
                upper.update(block_hash=blk["hash"],
                             explorer_merkle_root_matches=blk["merkle_root"] == root,
                             header_time_metadata=_iso(blk["header_time"]),
                             header_time_caveat="miner-asserted; consensus allows up to "
                                                "2 h ahead of network time; not evidence")
            except OSError as e:
                upper["explorer_check"] = f"INDETERMINATE: {e}"
    out["upper"] = upper
    path = Path(str(evidence) + ".bracket.json")
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=2))
    return 0 if upper["proof_commits_to_this_file"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
