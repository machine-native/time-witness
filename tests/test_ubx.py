"""The UBX codec, pinned against bytes this repository did not produce.

The reference frames below were serialised by pyubx2 1.3.8 (commit 993f37d4), an
independent implementation, on 2026-09-30 — see docs/SOURCES.md. If this codec's
reading of a layout, a scale or a bit position drifts, these fail. They are still
not receiver bytes; there are none yet.
"""
import pytest

from tw import synth, ubx

# pyubx2 1.3.8: UBXMessage(..., GET, <fields>).serialize().hex()
PYUBX2 = {
    # towMS=345600000 towSubMS=0.5ms qErr=-1234 week=2386 timeBase=0 utc=1 timeRefGnss=0 utcStandard=3
    "TIM-TP": "b5620d01100000709914000000802efbffff520902306f82",
    # count=65530 wnR=2386 towMsR=345600999 towSubMsR=999950 accEst=12 run=1 timeBase=1 time=1 newRisingEdge=1
    "TIM-TM2": "b5620d031c0000cafaff52090000e77399140e420f0000000000000000000c000000bcc8",
    # iTOW=345599000 fTOW=-250 week=2386 leapS=18 all valid tAcc=7
    "NAV-TIMEGPS": "b56201201000186c991406ffffff5209120707000000e06e",
    # iTOW=345599000 galTow=345599 fGalTow=120 galWno=1362 leapS=18 all valid tAcc=9
    "NAV-TIMEGAL": "b56201251400186c9914ff450500780000005205120709000000a564",
    # gpsFix=3 gpsFixOk=1 wknSet=1 towSet=1 spoofDetState=2 ttff=30000 msss=1000000
    "NAV-STATUS": "b56201031000186c9914030d00103075000040420f009b7d",
}


def test_checksum_matches_the_published_mon_ver_poll():
    # "B5 62 0A 04 00 00 0E 34" is the MON-VER poll quoted throughout u-blox material.
    assert ubx.encode(0x0A, 0x04, b"") == bytes.fromhex("b5620a0400000e34")


def test_tim_tp_decodes_the_independent_frame():
    d = ubx.tim_tp(ubx.parse_frame(bytes.fromhex(PYUBX2["TIM-TP"])))
    assert (d["tow_ms"], d["tow_sub_ms_2p32"], d["qerr_ps"], d["week"]) == \
        (345600000, 1 << 31, -1234, 2386)
    assert (d["time_base"], d["utc_available"], d["qerr_invalid"]) == (0, 1, 0)
    assert (d["time_ref_gnss"], d["utc_standard"]) == (0, 3)


def test_tim_tm2_decodes_the_independent_frame():
    d = ubx.tim_tm2(ubx.parse_frame(bytes.fromhex(PYUBX2["TIM-TM2"])))
    assert (d["count"], d["wn_r"], d["tow_ms_r"], d["tow_sub_ns_r"], d["acc_est_ns"]) == \
        (65530, 2386, 345600999, 999950, 12)
    assert (d["run"], d["time_base"], d["time_valid"], d["new_rising"]) == (1, 1, 1, 1)


def test_nav_time_and_status_decode_the_independent_frames():
    g = ubx.nav_timegps(ubx.parse_frame(bytes.fromhex(PYUBX2["NAV-TIMEGPS"])))
    assert (g["itow_ms"], g["ftow_ns"], g["week"], g["leap_s"], g["tacc_ns"]) == \
        (345599000, -250, 2386, 18, 7)
    assert g["tow_valid"] and g["week_valid"] and g["leap_valid"]
    e = ubx.nav_timegal(ubx.parse_frame(bytes.fromhex(PYUBX2["NAV-TIMEGAL"])))
    assert (e["tow_s"], e["ftow_ns"], e["week"], e["leap_s"], e["tacc_ns"]) == \
        (345599, 120, 1362, 18, 9)
    s = ubx.nav_status(ubx.parse_frame(bytes.fromhex(PYUBX2["NAV-STATUS"])))
    assert (s["gps_fix"], s["fix_ok"], s["spoof_det_state"]) == (3, 1, 2)


def test_synthetic_encoder_reproduces_the_independent_frames_byte_for_byte():
    assert synth.tim_tp(345600000, 1 << 31, -1234, 2386, utc_standard=3).hex() == PYUBX2["TIM-TP"]
    assert synth.tim_tm2(65530, 2386, 345600999, 999950, 12).hex() == PYUBX2["TIM-TM2"]
    assert synth.nav_timegps(345599000, -250, 2386, 18, 7).hex() == PYUBX2["NAV-TIMEGPS"]
    assert synth.nav_timegal(345599000, 345599, 120, 1362, 18, 9).hex() == PYUBX2["NAV-TIMEGAL"]
    assert synth.nav_status(itow_ms=345599000, spoof=2).hex() == PYUBX2["NAV-STATUS"]


@pytest.mark.parametrize("mutate", [
    lambda b: b[:-1] + bytes([b[-1] ^ 1]),       # checksum
    lambda b: b + b"\x00",                       # trailing byte
    lambda b: b[:-3] + b[-2:],                   # truncated payload
    lambda b: b"\xb5\x63" + b[2:],               # sync
])
def test_parse_is_strict(mutate):
    with pytest.raises(ubx.UBXError):
        ubx.parse_frame(mutate(bytes.fromhex(PYUBX2["TIM-TP"])))


def test_wrong_payload_length_for_the_message_is_refused():
    f = ubx.Frame(*ubx.TIM_TP, bytes(15))
    with pytest.raises(ubx.UBXError):
        ubx.tim_tp(f)


def test_stream_skips_nmea_and_corrupt_frames_and_keeps_offsets():
    good = bytes.fromhex(PYUBX2["NAV-TIMEGPS"])
    bad = bytearray(bytes.fromhex(PYUBX2["TIM-TP"])); bad[-1] ^= 0xFF
    nmea = b"$GNRMC,120000.00,A,,,,,,,,,,*00\r\n"
    data = nmea + bytes(bad) + good + nmea
    got = ubx.split_stream(data)
    assert [(off, f.name) for off, f in got] == [(len(nmea) + len(bad), "NAV-TIMEGPS")]
