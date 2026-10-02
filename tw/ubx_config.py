"""Receiver configuration for a time-witness capture.

u-blox 9 and 10 receivers (UBX-CFG-VALSET) are configured in the RAM layer only. u-blox 8
receivers are configured per message, also in RAM, except one setting the M8
specification makes persistent: enabling Galileo (see the u-blox 8 section below).

NOT HARDWARE-TESTED. Every key below was taken from the u-blox ZED-F9P Interface
Description (UBX-18010854 R04, digest in reference/SHA256SUMS) and agrees with
pyubx2 1.3.8's configuration database, an independent transcription of u-blox's
tables. The two disagreed on nothing once the PDF table was read in order. Keys the
document does not list (the receiver's own OSNMA status message, for one) are left
out on purpose: nothing here relies on the receiver's OSNMA verdict.

For VALSET receivers only the RAM layer is written: a power cycle returns the receiver
to its stored configuration, so a capture session never leaves it changed for good.

VALSET layout (ID §5.9.27): version U1 = 0, layers X1 (bit 0 = RAM), reserved U1[2],
then key (U4, little-endian) and value pairs; a value's size is bits 30..28 of its key
(1 = one bit stored in a byte, 2 = 1 byte, 3 = 2, 4 = 4, 5 = 8 bytes). The receiver
answers UBX-ACK-ACK (0x05 0x01) or UBX-ACK-NAK (0x05 0x00) with the acknowledged
class and id as payload; a NAK means nothing was applied.
"""
from __future__ import annotations

import re

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


# --- u-blox 8 / M8 (protocol 15-23.01): no VALSET, the older per-message configuration.
#
# Source: u-blox 8 / u-blox M8 Receiver Description incl. Protocol Specification,
# UBX-13003221 R28 (digest in reference/SHA256SUMS). Every frame below is reproduced
# byte-for-byte by pyubx2 1.3.8, and the GNSS block list is galmon's (ubxtool.cc), which
# volunteer stations run on M8 receivers; the three agree.
#
# On M8, Galileo is not a RAM-only change. The specification (CFG-GNSS notes) requires
# that enabling Galileo be followed by saving the configuration to battery-backed RAM
# (UBX-CFG-CFG) and a hardware reset (UBX-CFG-RST). Only sub-section 4 (RXM, which holds
# CFG-GNSS) is saved, and only to BBR, never to flash: removing backup power undoes it.
# Message rates stay RAM-only and are set per capture, after the reset.

MON_VER = (0x0A, 0x04)
CFG_MSG = (0x06, 0x01)
CFG_GNSS = (0x06, 0x3E)
CFG_CFG = (0x06, 0x09)
CFG_RST = (0x06, 0x04)

M8_PORTS = {"DDC": 0, "UART1": 1, "UART2": 2, "USB": 3, "SPI": 4}
M8_MESSAGE_IDS = {"RXM_SFRBX": (0x02, 0x13), "TIM_TM2": (0x0D, 0x03), "TIM_TP": (0x0D, 0x01),
                  "NAV_TIMEGAL": (0x01, 0x25), "NAV_TIMEGPS": (0x01, 0x20),
                  "NAV_STATUS": (0x01, 0x03)}
SECTION_RXM = 1 << 4             # holds UBX-CFG-GNSS (spec §3.2)
# The NMEA sentences an M8 outputs by default (spec, NMEA protocol; same ids in pyubx2):
# GGA, GLL, GSA, GSV, RMC, VTG. Turned off for a capture: at 9600 baud they crowd out the
# evidence, and GGA, GLL and RMC state the antenna's position.
M8_NMEA_DEFAULT = ((0xF0, 0x00), (0xF0, 0x01), (0xF0, 0x02), (0xF0, 0x03), (0xF0, 0x04),
                   (0xF0, 0x05))
DEVICE_BBR = 0x01

# gnssId, reserved channels, max channels, enabled; signal mask 0x01 (L1C/A, E1, ...) each.
# galmon's block list, with GPS and Galileo on and the rest off. The specification
# recommends enabling QZSS whenever GPS is enabled (cross-correlation); galmon's list,
# proven on volunteer M8 stations, does not, and it is kept as proven. Noted, not hidden.
M8_GNSS_BLOCKS = ((0, 4, 8, 1), (1, 3, 4, 0), (3, 4, 8, 0), (5, 4, 8, 0), (2, 8, 10, 1),
                  (6, 6, 8, 0))


def mon_ver_poll() -> bytes:
    return encode(*MON_VER, b"")


def parse_mon_ver(payload: bytes) -> dict:
    """swVersion CH[30], hwVersion CH[10], then extension CH[30] lines."""
    def text(b):
        return b.split(b"\x00", 1)[0].decode("ascii", "replace")
    ext = [text(payload[i:i + 30]) for i in range(40, len(payload) - 29, 30)]
    joined = " ".join(ext)
    m = re.search(r"PROTVER[= ]\s*(\d+)\.(\d+)", joined)
    protver = (int(m.group(1)), int(m.group(2))) if m else None
    gnss = sorted({g for line in ext if ";" in line or line in ("GPS", "GAL")
                   for g in line.split(";")})
    return {"sw_version": text(payload[:30]), "hw_version": text(payload[30:40]),
            "extensions": ext, "protver": protver, "gnss": gnss,
            "galileo": "GAL" in gnss or "GAL" in joined.split(),
            # protocol 27+ (u-blox 9, 10) is configured by VALSET; 15-23.01 (u-blox 8) is not
            "config_interface": ("VALSET" if protver and protver >= (27, 0)
                                 else "M8" if protver else None)}


def m8_galileo_capable(info: dict) -> tuple[bool, str]:
    """Galileo E1 needs protocol >= 18 (firmware 3.01). Older genuine NEO-M8N parts
    (ordering code -0-10) ship with 2.01 and can be upgraded; counterfeits look the same
    and cannot. Either way nothing is changed here: refuse by name, say what to try."""
    if info["protver"] is None:
        return False, "no PROTVER in MON-VER: cannot tell what this receiver is"
    if info["protver"] < (18, 0):
        return False, (f"protocol {info['protver'][0]}.{info['protver'][1]:02d} has no Galileo "
                       "(firmware 3.01 / protocol 18 needed). A genuine NEO-M8N has flash and "
                       "can be upgraded to 3.01 with u-blox u-center; a ROM part or a "
                       "counterfeit cannot, and the upgrade failing is the test")
    if not info["galileo"]:
        return False, "MON-VER does not list GAL among supported systems"
    return True, "ok"


def m8_gnss_frame() -> bytes:
    body = bytearray([0, 0, 0xFF, len(M8_GNSS_BLOCKS)])
    for gnss, res, mx, on in M8_GNSS_BLOCKS:
        body += bytes([gnss, res, mx, 0, on, 0, 0x01, 0])
    return encode(*CFG_GNSS, bytes(body))


def m8_save_rxm_to_bbr() -> bytes:
    return encode(*CFG_CFG, (0).to_bytes(4, "little") + SECTION_RXM.to_bytes(4, "little")
                  + (0).to_bytes(4, "little") + bytes([DEVICE_BBR]))


def m8_hardware_reset() -> bytes:
    """Hot start (no BBR section cleared), hardware reset immediately. Not acknowledged."""
    return encode(*CFG_RST, bytes([0, 0, 0x00, 0]))


def m8_capture_frames(port: str = "USB") -> list[bytes]:
    """UBX-CFG-MSG frames (RAM): the default NMEA sentences off on every port, then each
    capture message at rate 1 on `port` and 0 elsewhere. One ACK is expected per frame."""
    if port not in ("USB", "UART1"):
        raise ValueError("port is USB or UART1")
    out = [encode(*CFG_MSG, bytes(nmea) + bytes(6)) for nmea in M8_NMEA_DEFAULT]
    for name in CAPTURE_MESSAGES:
        rates = [0] * 6
        rates[M8_PORTS[port]] = 1
        out.append(encode(*CFG_MSG, bytes(M8_MESSAGE_IDS[name]) + bytes(rates)))
    return out


def acks(data: bytes, cls_id: tuple[int, int]) -> list[bool]:
    """Every ACK (True) / NAK (False) for `cls_id` in `data`, in order."""
    return [f.key == ACK_ACK for _, f in split_stream(data)
            if f.key in (ACK_ACK, ACK_NAK) and tuple(f.payload[:2]) == cls_id]
