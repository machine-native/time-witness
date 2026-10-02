"""The capture and setup scripts against a simulated receiver that talks too much.

The stand-in serial port behaves like a u-blox receiver at factory settings: it streams
NMEA sentences that state a position, answers configuration with ACKs and MON-VER, and
sends Galileo sub-frames. Neither script may write that position anywhere.
"""
import json
import runpy
import sys
import time
import types
from pathlib import Path

import pytest

from tw.ubx import RXM_SFRBX, encode

ROOT = Path(__file__).resolve().parents[1]
GGA = b"$GNGGA,101530.00,4807.03812,N,01131.00012,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
SFRBX = encode(*RXM_SFRBX, bytes([2, 11, 1, 0, 8, 0, 2, 0]) + bytes(range(32)))


def _monver(*ext):
    pad = lambda s, n: s.encode().ljust(n, b"\x00")
    return encode(0x0A, 0x04, pad("EXT CORE 3.01 (107888)", 30) + pad("00080000", 10)
                  + b"".join(pad(e, 30) for e in ext))


class FakeReceiver:
    def __init__(self, *a, **k):
        self.pending = GGA

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def reset_input_buffer(self):
        pass

    def write(self, frame):
        if frame[2:4] == b"\x0a\x04":
            self.pending += GGA + _monver("FWVER=SPG 3.01", "PROTVER=18.00", "GPS;GLO;GAL;BDS")
        elif frame[2] == 0x06 and frame[3] != 0x04:
            self.pending += GGA[:20] + encode(0x05, 0x01, frame[2:4]) + GGA[20:]

    def flush(self):
        pass

    def read(self, n):
        time.sleep(0.02)                         # a serial port delivers at its own pace
        out, self.pending = self.pending + GGA + SFRBX, b""
        return out


def _run(script, args, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=FakeReceiver))
    monkeypatch.setattr(sys, "argv", [script] + args)
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(ROOT / "scripts" / script), run_name="__main__")
    return e.value.code, capsys.readouterr().out


@pytest.mark.parametrize("receiver", ["valset", "m8"])
def test_capture_keeps_evidence_and_acks_and_no_position(tmp_path, monkeypatch, capsys,
                                                         receiver):
    out = tmp_path / "cap"
    code, text = _run("capture_ubx.py", ["--port", "X", "--seconds", "1", "--out", str(out),
                                         "--configure", "UART1", "--receiver", receiver],
                      monkeypatch, capsys)
    assert code == 0 and "configuration ACKed" in text
    written = b"".join(p.read_bytes() for p in tmp_path.iterdir())
    for leak in (b"4807.03812", b"01131.00012", b"GNGGA", GGA.hex().encode()[:40]):
        assert leak not in written
    assert SFRBX in out.with_suffix(".ubx").read_bytes()
    summary = json.loads(out.with_suffix(".capture.json").read_text(encoding="utf-8"))
    assert summary["dropped"]["non_ubx_bytes"] > 0 and summary["kept"]["02-13"] > 0


def test_setup_record_holds_the_replies_and_no_position(tmp_path, monkeypatch, capsys):
    rec = tmp_path / "setup.json"
    code, text = _run("setup_receiver.py", ["--port", "X", "--out", str(rec)],
                      monkeypatch, capsys)
    assert code == 0 and "Galileo enabled" in text
    raw = rec.read_bytes()
    for leak in (b"4807.03812", b"01131.00012", b"GNGGA", GGA.hex().encode()[:40]):
        assert leak not in raw
    steps = json.loads(raw)["steps"]
    assert [s["ack"] for s in steps[:2]] == [[True], [True]]
