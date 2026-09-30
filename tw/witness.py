"""The TW-GNSS/v1 evidence blob and its deterministic derivation.

An evidence blob is canonical CBOR (chronology-protocol's restricted subset). It
carries the receiver's raw UBX frames byte-for-byte, the device's declared
error budget, and the host monotonic time of acquisition. Everything the witness
claims is DERIVED from those bytes by `derive`, and a verifier runs the same
function — so the claim can be recomputed, not merely read.

Two modes:

  PPS  the event is the receiver's own time pulse. One source: GNSS-PPS/v1,
       from UBX-TIM-TP. For a receiver with no external reference.

  OSC  the event is the external oscillator's 1 PPS edge, time-marked by the
       receiver (UBX-TIM-TM2). Two SEPARABLE sources for the same edge:
         GNSS-EXTINT/v1   what GNSS says the edge's time was
         OSC-HOLDOVER/v1  what the oscillator alone predicts, from an earlier
                          anchor edge plus a declared drift bound
       and a verdict on whether they overlap.

The observation interval is the HULL of its sources' intervals. That is the
conservative choice: if either source is honest, the hull contains the truth.
Intersecting them would be tighter and would be wrong exactly when it matters —
a GNSS source spoofed within the holdover bound would drag the intersection off
the true time without either interval looking unusual.

Blob keys (integer, canonical CBOR map):
   1 "TW-GNSS/v1"        2 mode "PPS"|"OSC"      3 device profile (map)
   4 [raw UBX frames]    5 host monotonic ns     6 anchor evidence digest | null
   9 sequence           10 challenge q | null   11 B0 hash | null   12 session | null

Device profile keys:
   1 "TW-DEVICE/v1"   2 device name      3 tAcc coverage factor k
   4 cable delay uncertainty ps          5 PPS calibration uncertainty ps
   6 GNSS-to-UTC timescale uncertainty ps
   7 oscillator |y| bound, ppq           8 oscillator aging bound, ppq/day
   9 host monotonic clock bound, ppm    10 receiver firmware (declared text)
"""
from __future__ import annotations

from ctp import cbor
from ctp.hashsuite import (DigestPair, digest_pair, DOM_EVIDENCE, DOM_STATE,
                           DOM_WITNESS)
from ctp.interval import Interval
from ctp.model import SourceObservation, UnsignedObservation

from . import ubx
from .holdover import drift_bound_ps, resolve_edges
from .timescale import (PS, PS_PER_MS, PS_PER_NS, day_origin, frame_for_origin,
                        gnss_to_abs_utc_ps, gnss_week_ps, tp_sub_ms_to_ps)

BLOB_TYPE = "TW-GNSS/v1"
PROFILE_TYPE = "TW-DEVICE/v1"
# Frames that corroborate but do not enter the time derivation. Raw Galileo pages
# (RXM-SFRBX) are kept for an offline OSNMA verifier (SPEC §10).
PASSIVE = {ubx.RXM_SFRBX, ubx.SEC_OSNMA}
NAV_SANITY_PS = 2 * PS

# auth_state vocabulary. None of these asserts OSNMA verification: that value is
# reserved until an offline verifier exists (VERIFIED_OSNMA, SPEC §10).
AUTH_RECEIVER = "RECEIVER_ASSERTED"
AUTH_OSNMA_REPORTED = "RECEIVER_ASSERTED_OSNMA_REPORTED"
AUTH_SPOOF = "RECEIVER_ASSERTED_SPOOFING_INDICATED"
AUTH_OSC = "LOCAL_OSCILLATOR_MODEL"
AUTH_OSNMA_VERIFIED = "VERIFIED_OSNMA"

CONSISTENT = "CONSISTENT"
DISAGREE = "GNSS_OSCILLATOR_DISAGREE"
NO_ANCHOR = "NO_ANCHOR"


class EvidenceError(ValueError):
    pass


def device_profile(name: str, *, tacc_k: int, cable_unc_ps: int, calib_unc_ps: int,
                   timescale_unc_ps: int, osc_y_ppq: int, osc_aging_ppq_day: int,
                   host_ppm: int, firmware: str) -> dict:
    vals = (tacc_k, cable_unc_ps, calib_unc_ps, timescale_unc_ps, osc_y_ppq,
            osc_aging_ppq_day, host_ppm)
    if any((not isinstance(v, int)) or v < 0 for v in vals) or tacc_k < 1:
        raise EvidenceError("profile values must be non-negative integers, k >= 1")
    return {1: PROFILE_TYPE, 2: name, 3: tacc_k, 4: cable_unc_ps, 5: calib_unc_ps,
            6: timescale_unc_ps, 7: osc_y_ppq, 8: osc_aging_ppq_day, 9: host_ppm,
            10: firmware}


def evidence_blob(mode: str, profile: dict, frames: list[bytes], mono_ns: int, seq: int,
                  anchor: DigestPair | None = None, q: bytes | None = None,
                  b0_hash: bytes | None = None, session: bytes | None = None) -> bytes:
    return cbor.dumps({
        1: BLOB_TYPE, 2: mode, 3: profile, 4: list(frames), 5: mono_ns,
        6: None if anchor is None else anchor.as_obj(),
        9: seq, 10: q, 11: b0_hash, 12: session})


def evidence_digest(blob: bytes) -> DigestPair:
    return digest_pair(DOM_EVIDENCE, blob)


def _one(by, key, what):
    xs = by.get(key, [])
    if len(xs) != 1:
        raise EvidenceError(f"{what}: expected exactly one {ubx.NAMES[key]}, found {len(xs)}")
    return xs[0]


def _load(blob: bytes):
    o = cbor.loads(blob)
    if o.get(1) != BLOB_TYPE:
        raise EvidenceError("not a TW-GNSS/v1 blob")
    prof = o[3]
    if prof.get(1) != PROFILE_TYPE:
        raise EvidenceError("unknown device profile type")
    by = {}
    for raw in o[4]:
        try:
            f = ubx.parse_frame(raw)
        except ubx.UBXError as e:
            raise EvidenceError(f"frame rejected: {e}") from e
        if f.key not in ubx.DECODERS:
            raise EvidenceError(f"unexpected frame {f.name}")
        by.setdefault(f.key, []).append(ubx.DECODERS[f.key](f))
    return o, prof, by


def _nav_time(by):
    gps, gal = by.get(ubx.NAV_TIMEGPS, []), by.get(ubx.NAV_TIMEGAL, [])
    if len(gps) + len(gal) != 1:
        raise EvidenceError("expected exactly one NAV-TIMEGPS or NAV-TIMEGAL")
    system, nav = ("GPS", gps[0]) if gps else ("GAL", gal[0])
    if not (nav["tow_valid"] and nav["week_valid"] and nav["leap_valid"]):
        raise EvidenceError(f"{system} navigation time not fully valid")
    if system == "GPS":
        t = gnss_week_ps("GPS", nav["week"]) + nav["itow_ms"] * PS_PER_MS
    else:
        t = gnss_week_ps("GAL", nav["week"]) + nav["tow_s"] * PS
    return system, nav, t + nav["ftow_ns"] * PS_PER_NS


def _receiver_auth(by, system) -> tuple[str, dict]:
    status = _one(by, ubx.NAV_STATUS, "receiver status")
    if not status["fix_ok"]:
        raise EvidenceError("receiver reports no valid fix")
    osnma = by.get(ubx.SEC_OSNMA, [])
    if len(osnma) > 1:
        raise EvidenceError("more than one SEC-OSNMA frame")
    info = {"spoof_det_state": status["spoof_det_state"],
            "osnma_header": osnma[0] if osnma else None}
    if status["spoof_det_state"] >= 2:
        return AUTH_SPOOF, info
    if osnma and system == "GAL" and osnma[0]["osnma_enabled"]:
        return AUTH_OSNMA_REPORTED, info
    return AUTH_RECEIVER, info


def _src(typ, claimed, unc, auth):
    return {"type": typ, "claimed_abs_ps": claimed, "uncertainty_ps": unc, "auth": auth}


def _extint_edge(o, prof, by):
    system, nav, nav_t = _nav_time(by)
    tm = _one(by, ubx.TIM_TM2, "OSC mode")
    if tm["time_base"] != 1 or not tm["time_valid"] or not tm["new_rising"]:
        raise EvidenceError("TIM-TM2 rising edge not a valid GNSS-time mark")
    edge = (gnss_week_ps(system, tm["wn_r"]) + tm["tow_ms_r"] * PS_PER_MS
            + tm["tow_sub_ns_r"] * PS_PER_NS)
    if abs(edge - nav_t) > NAV_SANITY_PS:
        raise EvidenceError("time mark and navigation epoch are more than 2 s apart")
    unc = (prof[3] * nav["tacc_ns"] * PS_PER_NS + tm["acc_est_ns"] * PS_PER_NS
           + prof[4] + prof[5] + prof[6])
    return system, gnss_to_abs_utc_ps(edge, nav["leap_s"]), unc, tm["count"]


_ALLOWED = {"PPS": {ubx.TIM_TP, ubx.NAV_STATUS, ubx.NAV_TIMEGPS, ubx.NAV_TIMEGAL},
            "OSC": {ubx.TIM_TM2, ubx.NAV_STATUS, ubx.NAV_TIMEGPS, ubx.NAV_TIMEGAL}}


def _check_mode(o, by) -> str:
    mode = o[2]
    if mode not in _ALLOWED:
        raise EvidenceError(f"unknown mode {mode!r}")
    extra = set(by) - _ALLOWED[mode] - PASSIVE
    if extra:
        raise EvidenceError("frames not used by this mode: "
                            + ", ".join(sorted(ubx.NAMES[k] for k in extra)))
    return mode


def derive(blob: bytes, anchors: dict | None = None) -> dict:
    """Re-derive every claim from the blob's bytes.

    `anchors` maps evidence DigestPair -> blob for earlier OSC observations. An
    anchor the caller cannot supply raises LookupError (the verifier reports it as
    UNAVAILABLE: unable to check, which is not the same as checked and failed).
    """
    o, prof, by = _load(blob)
    mode = _check_mode(o, by)

    if mode == "PPS":
        if o[6] is not None:
            raise EvidenceError("PPS mode takes no anchor")
        tp = _one(by, ubx.TIM_TP, "PPS mode")
        if tp["time_base"] != 0 or tp["qerr_invalid"]:
            raise EvidenceError("TIM-TP must be on a GNSS time base with a valid qErr")
        system, nav, nav_t = _nav_time(by)
        want = {"GPS": ubx.GNSS_GPS, "GAL": ubx.GNSS_GALILEO}[system]
        if tp["time_ref_gnss"] != want:
            raise EvidenceError("TIM-TP reference GNSS differs from the navigation time frame")
        sub_ps, residue = tp_sub_ms_to_ps(tp["tow_sub_ms_2p32"])
        pulse = gnss_week_ps(system, tp["week"]) + tp["tow_ms"] * PS_PER_MS + sub_ps
        if abs(pulse - nav_t) > NAV_SANITY_PS:
            raise EvidenceError("time pulse and navigation epoch are more than 2 s apart")
        # qErr is the pulse's quantisation error. v1 does not correct it (that
        # needs a counter on the pulse); it widens the interval by |qErr| instead.
        unc = (prof[3] * nav["tacc_ns"] * PS_PER_NS + abs(tp["qerr_ps"])
               + prof[4] + prof[5] + prof[6] + residue)
        auth, rx = _receiver_auth(by, system)
        sources = [_src("GNSS-PPS/v1", gnss_to_abs_utc_ps(pulse, nav["leap_s"]), unc, auth)]
        consistency = NO_ANCHOR
    else:
        system, edge_abs, unc, count = _extint_edge(o, prof, by)
        auth, rx = _receiver_auth(by, system)
        sources = [_src("GNSS-EXTINT/v1", edge_abs, unc, auth)]
        consistency = NO_ANCHOR
        if o[6] is not None:
            key = DigestPair.from_obj(o[6])
            if anchors is None or key not in anchors:
                raise LookupError("anchor evidence not supplied")
            a_blob = anchors[key]
            ao, aprof, aby = _load(a_blob)
            # The anchor is held to every rule the current blob is: its frames,
            # its fix, and — because everything after it inherits its time — a
            # receiver that was flagging spoofing when it was taken disqualifies it.
            if _check_mode(ao, aby) != "OSC":
                raise EvidenceError("anchor is not an OSC-mode observation")
            if aprof != prof:
                raise EvidenceError("anchor was made under a different device profile")
            a_system, a_abs, a_unc, a_count = _extint_edge(ao, aprof, aby)
            if a_system != system:
                raise EvidenceError("anchor is on a different GNSS time frame")
            if _receiver_auth(aby, a_system)[0] == AUTH_SPOOF:
                raise EvidenceError("anchor was taken while the receiver indicated spoofing")
            n = resolve_edges(a_count, count, o[5] - ao[5], prof[9])
            hold = a_abs + n * PS
            hunc = a_unc + drift_bound_ps(n, prof[7], prof[8])
            sources.append(_src("OSC-HOLDOVER/v1", hold, hunc, AUTH_OSC))
            overlap = (max(edge_abs - unc, hold - hunc) <= min(edge_abs + unc, hold + hunc))
            consistency = CONSISTENT if overlap else DISAGREE

    lo = min(s["claimed_abs_ps"] - s["uncertainty_ps"] for s in sources)
    hi = max(s["claimed_abs_ps"] + s["uncertainty_ps"] for s in sources)
    return {"mode": mode, "system": system, "sources": sources, "interval_abs": (lo, hi),
            "consistency": consistency, "receiver": rx, "mono_ns": o[5], "sequence": o[9],
            "device": prof[2]}


def witness_id(device_name: str) -> bytes:
    return digest_pair(DOM_WITNESS, ("TW-GNSS:" + device_name).encode()).sha256


def observation(blob: bytes, derived: dict, genesis_id: DigestPair,
                previous: DigestPair | None, origin_unix_s: int | None = None
                ) -> UnsignedObservation:
    """Express a derived measurement as a chronology-protocol observation.

    The frame origin defaults to 00:00:00Z of the day containing the interval's
    midpoint, matching the sandwich profiles, so it can share a checkpoint with them.
    """
    lo, hi = derived["interval_abs"]
    origin = day_origin((lo + hi) // 2) if origin_unix_s is None else origin_unix_s
    base = origin * PS
    ev = evidence_digest(blob)
    o = cbor.loads(blob)
    state = digest_pair(DOM_STATE, cbor.dumps(o[3]))
    fw = digest_pair(DOM_STATE, cbor.dumps({1: "TW-FIRMWARE/v1", 2: o[3][10]}))
    srcs = [SourceObservation(s["type"], s["claimed_abs_ps"] - base, s["uncertainty_ps"],
                              s["auth"], ev) for s in derived["sources"]]
    return UnsignedObservation(
        witness_id=witness_id(derived["device"]), genesis_id=genesis_id,
        sequence=derived["sequence"], previous=previous,
        monotonic_ps=derived["mono_ns"] * 1000,
        interval=Interval(lo - base, hi - base), reference_frame=frame_for_origin(origin),
        sources=srcs, hardware_state=state, firmware_state=fw)
