"""Receiver configuration frames, checked against an independent serialiser.

The reference frame was produced by pyubx2 1.3.8 (BSD-3-Clause; no code included):
    UBXMessage.config_set(SET_LAYER_RAM, TXN_NONE,
        [("CFG_MSGOUT_UBX_RXM_SFRBX_USB", 1), ("CFG_MSGOUT_UBX_TIM_TM2_USB", 1),
         ("CFG_SIGNAL_GAL_ENA", 1), ("CFG_UART1_BAUDRATE", 460800)]).serialize()
It covers all three value sizes used here: a one-bit key, one-byte keys and a
four-byte key.
"""
import pytest

from tw import ubx_config as uc
from tw.ubx import encode, parse_frame

PYUBX2_VALSET = bytes.fromhex(
    "b562068a1b000001000034029120017b0191200121003110010100524000080700c7df")


def test_valset_matches_pyubx2_byte_for_byte():
    got = uc.valset([("CFG-MSGOUT-UBX_RXM_SFRBX_USB", 1), ("CFG-MSGOUT-UBX_TIM_TM2_USB", 1),
                     ("CFG-SIGNAL-GAL_ENA", 1), ("CFG-UART1-BAUDRATE", 460800)])
    assert got == PYUBX2_VALSET


def test_value_sizes_follow_the_key():
    assert uc.value_size(uc.KEYS["CFG-SIGNAL-GAL_ENA"]) == 1            # one bit, in a byte
    assert uc.value_size(uc.KEYS["CFG-MSGOUT-UBX_TIM_TM2_USB"]) == 1    # U1
    assert uc.value_size(uc.KEYS["CFG-UART1-BAUDRATE"]) == 4            # U4
    with pytest.raises(ValueError):
        uc.value_size(0x00910001)


def test_only_the_ram_layer_is_ever_written():
    with pytest.raises(ValueError):
        uc.valset([("CFG-SIGNAL-GAL_ENA", 1)], layers=0x04)              # flash
    f = parse_frame(uc.valset(uc.capture_config("UART1")))
    assert f.key == uc.VALSET and f.payload[:4] == b"\x00\x01\x00\x00"


def test_capture_config_enables_galileo_and_every_capture_message_on_the_port():
    names = [n for n, _ in uc.capture_config("USB")]
    assert names[:2] == ["CFG-SIGNAL-GAL_ENA", "CFG-SIGNAL-GAL_E1_ENA"]
    assert all(n.endswith("_USB") for n in names[2:])
    assert len(names) == 2 + len(uc.CAPTURE_MESSAGES)
    with pytest.raises(ValueError):
        uc.capture_config("SPI")


def test_ack_and_nak_are_told_apart_and_matched_to_the_request():
    ack = encode(0x05, 0x01, bytes([0x06, 0x8A]))
    nak = encode(0x05, 0x00, bytes([0x06, 0x8A]))
    other = encode(0x05, 0x01, bytes([0x06, 0x01]))
    assert uc.ack_for(b"noise" + ack) is True
    assert uc.ack_for(nak) is False
    assert uc.ack_for(other) is None
    assert uc.ack_for(b"") is None


# --- u-blox 8. Reference frames serialised by pyubx2 1.3.8; the CFG-GNSS block list is
# also byte-identical to galmon's ubxtool.cc (commit 9bd22436) with GPS and Galileo on.
PYUBX2_M8 = {
    "CFG-GNSS": "b562063e34000000ff06000408000100010001030400000001000304080000000100"
                "050408000000010002080a00010001000606080000000100e1a9",
    "CFG-CFG save RXM to BBR": "b56206090d00000000001000000000000000012d4a",
    "CFG-RST hardware hot": "b56206040400000000000e64",
    "MON-VER poll": "b5620a0400000e34",
    "CFG-MSG TIM-TM2 UART1": "b562060108000d030001000000002025",
}


def test_m8_frames_match_pyubx2_byte_for_byte():
    assert uc.m8_gnss_frame().hex() == PYUBX2_M8["CFG-GNSS"]
    assert uc.m8_save_rxm_to_bbr().hex() == PYUBX2_M8["CFG-CFG save RXM to BBR"]
    assert uc.m8_hardware_reset().hex() == PYUBX2_M8["CFG-RST hardware hot"]
    assert uc.mon_ver_poll().hex() == PYUBX2_M8["MON-VER poll"]
    tm2 = [f for f in uc.m8_capture_frames("UART1") if f[6:8] == b"\x0d\x03"]
    assert tm2[0].hex() == PYUBX2_M8["CFG-MSG TIM-TM2 UART1"]


def test_m8_saves_only_the_gnss_section_and_only_to_bbr():
    p = parse_frame(uc.m8_save_rxm_to_bbr()).payload
    assert int.from_bytes(p[0:4], "little") == 0             # clear nothing
    assert int.from_bytes(p[4:8], "little") == 1 << 4        # save RXM (holds CFG-GNSS)
    assert int.from_bytes(p[8:12], "little") == 0            # load nothing
    assert p[12] == 0x01                                     # BBR, not flash


def _mon_ver(sw, hw, *ext):
    pad = lambda s, n: s.encode().ljust(n, b"\x00")
    return pad(sw, 30) + pad(hw, 10) + b"".join(pad(e, 30) for e in ext)


def test_mon_ver_tells_a_galileo_m8_from_a_stuck_one_and_from_a_valset_receiver():
    # Strings in the forms u-blox receivers print (firmware 2.01, 3.01, and a ZED-F9P).
    old = uc.parse_mon_ver(_mon_ver("2.01 (75350)", "00080000", "PROTVER 15.00",
                                    "GPS;SBAS;GLO;BDS;QZSS"))
    new = uc.parse_mon_ver(_mon_ver("EXT CORE 3.01 (107888)", "00080000",
                                    "ROM BASE 2.01 (75331)", "FWVER=SPG 3.01",
                                    "PROTVER=18.00", "GPS;GLO;GAL;BDS", "SBAS;IMES;QZSS"))
    f9 = uc.parse_mon_ver(_mon_ver("EXT CORE 1.00 (fbd843)", "00190000", "ROM BASE 0x118B2060",
                                   "FWVER=HPG 1.51", "PROTVER=27.50", "MOD=ZED-F9P",
                                   "GPS;GLO;GAL;BDS", "SBAS;QZSS"))
    assert old["config_interface"] == "M8" and old["protver"] == (15, 0)
    ok, why = uc.m8_galileo_capable(old)
    assert not ok and "counterfeit" in why
    assert new["config_interface"] == "M8" and new["galileo"]
    assert uc.m8_galileo_capable(new) == (True, "ok")
    assert f9["config_interface"] == "VALSET" and f9["galileo"]
    assert uc.parse_mon_ver(_mon_ver("x", "y"))["config_interface"] is None


def test_acks_counts_every_answer_for_the_asked_message():
    ack = encode(0x05, 0x01, bytes(uc.CFG_MSG))
    nak = encode(0x05, 0x00, bytes(uc.CFG_MSG))
    assert uc.acks(ack + b"junk" + ack + nak, uc.CFG_MSG) == [True, True, False]
    assert uc.acks(ack, uc.VALSET) == []


def test_an_m8_galileo_page_with_signal_id_zero_is_read_as_e1b():
    from tw import ubx_inav
    from tw.ubx import RXM_SFRBX
    raw = ubx_inav.page_sfrbx(11, "0" * 119 + "1", "1" + "0" * 119)
    m8 = bytearray(parse_frame(raw).payload)
    m8[2] = 0                                                 # what an M8 may report
    assert ubx_inav.sfrbx_page(parse_frame(encode(*RXM_SFRBX, bytes(m8))))[0] == 11
    m8[2] = 5                                                 # E5b: different layout
    assert ubx_inav.sfrbx_page(parse_frame(encode(*RXM_SFRBX, bytes(m8)))) is None
