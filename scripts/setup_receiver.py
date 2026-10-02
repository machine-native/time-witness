#!/usr/bin/env python3
"""Identify a u-blox receiver and, if it is a u-blox 8, switch Galileo on. Run once.

NOT HARDWARE-TESTED. Written before any receiver is on the bench.

    pip install pyserial
    python scripts/setup_receiver.py --port COM5 --baud 9600 --out live/<label>.setup.json
    python scripts/setup_receiver.py --port COM5 --dry-run      # identify only, change nothing

Step 1, always: poll UBX-MON-VER and record the answer. That says what the receiver
is. A u-blox 8 below protocol 18 (firmware 2.01) has no Galileo and cannot be
upgraded if it is one of the many counterfeit NEO-M8N parts; the script says so and
stops, changing nothing. That is the purchase check: run it the day a module arrives.

Step 2, u-blox 8 only: Galileo is enabled with UBX-CFG-GNSS, which the M8 specification
requires be followed by a save to battery-backed RAM and a hardware reset
(tw/ubx_config.py has the reasoning and sources). Only the GNSS section is saved, and
only to BBR, never to flash. u-blox 9 and 10 receivers need no persistent setup:
capture_ubx.py --configure sets everything in RAM.

Every byte sent and received is written to the --out record.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tw import ubx_config as uc  # noqa: E402
from tw.ubx import split_stream  # noqa: E402


def exchange(port, frame: bytes, seconds: float) -> bytes:
    """Send a frame and collect whatever arrives for `seconds`."""
    port.reset_input_buffer()
    port.write(frame)
    port.flush()
    got, end = bytearray(), time.monotonic() + seconds
    while time.monotonic() < end:
        got += port.read(4096)
    return bytes(got)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=9600, help="u-blox 8 factory default is 9600")
    ap.add_argument("--out", help="setup record (JSON); required unless --dry-run")
    ap.add_argument("--dry-run", action="store_true", help="identify the receiver only")
    a = ap.parse_args(argv)
    if not a.dry_run and not a.out:
        ap.error("--out is required unless --dry-run")
    if a.out and Path(a.out).exists():
        print(f"refusing to overwrite {a.out}", file=sys.stderr)
        return 2
    try:
        import serial
    except ImportError:
        print("pyserial is required: pip install pyserial", file=sys.stderr)
        return 2

    log = []
    with serial.Serial(a.port, a.baud, timeout=0.2) as port:
        poll = uc.mon_ver_poll()
        got = exchange(port, poll, 2.0)
        log.append({"sent": poll.hex(), "received": got.hex()})
        ver = [f for _, f in split_stream(got) if f.key == uc.MON_VER and f.payload]
        if not ver:
            print("no MON-VER answer: wrong port or baud rate, or not a u-blox receiver")
            return 1
        info = uc.parse_mon_ver(ver[0].payload)
        print(json.dumps({k: info[k] for k in ("sw_version", "hw_version", "extensions")},
                         indent=2))
        verdict, steps, success = None, [], False
        if info["config_interface"] == "VALSET":
            verdict = "VALSET receiver: no persistent setup needed; use capture_ubx.py --configure"
            success = True
        elif info["config_interface"] == "M8":
            ok, why = uc.m8_galileo_capable(info)
            if not ok:
                verdict = f"NOT USABLE for Galileo: {why}"
            elif a.dry_run:
                verdict = "u-blox 8 with Galileo support; run without --dry-run to enable it"
                success = True
            else:
                for name, frame, cls_id, wait in (
                        ("CFG-GNSS", uc.m8_gnss_frame(), uc.CFG_GNSS, 1.5),
                        ("CFG-CFG save RXM to BBR", uc.m8_save_rxm_to_bbr(), uc.CFG_CFG, 1.0)):
                    got = exchange(port, frame, wait)
                    answer = uc.acks(got, cls_id)
                    steps.append({"step": name, "sent": frame.hex(), "received": got.hex(),
                                  "ack": answer[:1]})
                    if answer[:1] != [True]:
                        verdict = f"{name} was not acknowledged; stopped before the reset"
                        break
                else:
                    rst = uc.m8_hardware_reset()
                    port.write(rst)
                    port.flush()
                    steps.append({"step": "CFG-RST hardware reset (not acknowledged by design)",
                                  "sent": rst.hex()})
                    verdict = ("Galileo enabled and saved to BBR; receiver reset. Wait for a fix, "
                               "then capture with capture_ubx.py --configure PORT --receiver m8")
                    success = True
        else:
            verdict = "MON-VER carries no PROTVER: unknown receiver; nothing changed"
        print(verdict)
        if a.out:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(json.dumps({
                "type": "TW-RECEIVER-SETUP/v1", "mon_ver": info, "exchanges": log,
                "steps": steps, "verdict": verdict,
                "utc_host": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "note": "host UTC is this machine's clock, not evidence",
            }, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
