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
