"""Receiver configuration for a time-witness capture: UBX-CFG-VALSET, RAM layer only.

NOT HARDWARE-TESTED. Every key below was taken from the u-blox ZED-F9P Interface
Description (UBX-18010854 R04, digest in reference/SHA256SUMS) and agrees with
pyubx2 1.3.8's configuration database, an independent transcription of u-blox's
tables. The two disagreed on nothing once the PDF table was read in order. Keys the
document does not list (the receiver's own OSNMA status message, for one) are left
out on purpose: nothing here relies on the receiver's OSNMA verdict.

Only the RAM layer is written. A power cycle returns the receiver to its stored
configuration, so a capture session can never leave a receiver changed for good.

VALSET layout (ID §5.9.27): version U1 = 0, layers X1 (bit 0 = RAM), reserved U1[2],
then key (U4, little-endian) and value pairs; a value's size is bits 30..28 of its key
(1 = one bit stored in a byte, 2 = 1 byte, 3 = 2, 4 = 4, 5 = 8 bytes). The receiver
answers UBX-ACK-ACK (0x05 0x01) or UBX-ACK-NAK (0x05 0x00) with the acknowledged
class and id as payload; a NAK means nothing was applied.
"""
from __future__ import annotations

from .ubx import encode, split_stream

VALSET = (0x06, 0x8A)
ACK_ACK = (0x05, 0x01)
ACK_NAK = (0x05, 0x00)
LAYER_RAM = 0x01

# name: key id. Interface Description R04 == pyubx2 1.3.8 for every entry.
KEYS = {
    "CFG-MSGOUT-UBX_RXM_SFRBX_UART1": 0x20910232,
    "CFG-MSGOUT-UBX_RXM_SFRBX_USB": 0x20910234,
    "CFG-MSGOUT-UBX_TIM_TM2_UART1": 0x20910179,
    "CFG-MSGOUT-UBX_TIM_TM2_USB": 0x2091017B,
    "CFG-MSGOUT-UBX_TIM_TP_UART1": 0x2091017E,
    "CFG-MSGOUT-UBX_TIM_TP_USB": 0x20910180,
    "CFG-MSGOUT-UBX_NAV_TIMEGAL_UART1": 0x20910057,
    "CFG-MSGOUT-UBX_NAV_TIMEGAL_USB": 0x20910059,
    "CFG-MSGOUT-UBX_NAV_TIMEGPS_UART1": 0x20910048,
    "CFG-MSGOUT-UBX_NAV_TIMEGPS_USB": 0x2091004A,
    "CFG-MSGOUT-UBX_NAV_STATUS_UART1": 0x2091001B,
    "CFG-MSGOUT-UBX_NAV_STATUS_USB": 0x2091001D,
    "CFG-SIGNAL-GAL_ENA": 0x10310021,
    "CFG-SIGNAL-GAL_E1_ENA": 0x10310007,
    "CFG-UART1-BAUDRATE": 0x40520001,
}

_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}

# What a capture needs, per output port: every navigation sub-frame (the Galileo
# pages), the time mark of the external edge, the receiver's own time pulse data,
# and enough status to see whether the receiver had a fix. One message per epoch.
CAPTURE_MESSAGES = ("RXM_SFRBX", "TIM_TM2", "TIM_TP", "NAV_TIMEGAL", "NAV_TIMEGPS", "NAV_STATUS")


def value_size(key: int) -> int:
    code = (key >> 28) & 0x7
    if code not in _SIZE:
        raise ValueError(f"key 0x{key:08x} has no valid size code ({code})")
    return _SIZE[code]


def valset(items: list[tuple[str, int]], layers: int = LAYER_RAM) -> bytes:
    """A UBX-CFG-VALSET frame (version 0, no transaction) setting the named keys."""
    if not items or len(items) > 64:
        raise ValueError("VALSET carries 1..64 key-value pairs")
    if layers != LAYER_RAM:
        raise ValueError("only the RAM layer is written; see the module docstring")
    body = bytearray([0, layers, 0, 0])
    for name, value in items:
        key = KEYS[name]
        body += key.to_bytes(4, "little") + int(value).to_bytes(value_size(key), "little")
    return encode(*VALSET, bytes(body))


def capture_config(port: str = "USB") -> list[tuple[str, int]]:
    """Galileo E1 on, and every capture message once per navigation epoch on `port`."""
    if port not in ("USB", "UART1"):
        raise ValueError("port is USB or UART1")
    return ([("CFG-SIGNAL-GAL_ENA", 1), ("CFG-SIGNAL-GAL_E1_ENA", 1)]
            + [(f"CFG-MSGOUT-UBX_{m}_{port}", 1) for m in CAPTURE_MESSAGES])


def ack_for(data: bytes, cls_id: tuple[int, int] = VALSET):
    """True for ACK-ACK, False for ACK-NAK, None if neither acknowledges `cls_id`."""
    for _, f in split_stream(data):
        if f.key in (ACK_ACK, ACK_NAK) and tuple(f.payload[:2]) == cls_id:
            return f.key == ACK_ACK
    return None
