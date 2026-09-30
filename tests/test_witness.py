"""Derivation, observation building and verification, end to end on SYNTHETIC frames.

These frames come from tw.synth, whose encoder is pinned to pyubx2 in test_ubx.
Passing here shows that the derivation, the chronology-protocol observation and
the verifier agree with one another. It shows nothing about a receiver.
"""
import pytest

from ctp import cbor
from ctp.hashsuite import digest_pair, DOM_STATE
from ctp.interval import Interval, consensus
from ctp.model import SourceObservation, UnsignedObservation

from tw import synth
from tw.holdover import drift_bound_ps
from tw.timescale import PS, gnss_to_abs_utc_ps, gnss_week_ps
from tw.verify import verify_observation
from tw.witness import (AUTH_OSC, AUTH_OSNMA_REPORTED, AUTH_OSNMA_VERIFIED, AUTH_RECEIVER,
                        AUTH_SPOOF, CONSISTENT, DISAGREE, NO_ANCHOR, EvidenceError, derive,
                        device_profile, evidence_blob, evidence_digest, observation)

GENESIS = digest_pair(DOM_STATE, b"test genesis")
WEEK, TOW_MS, LEAP = 2386, 345_600_000, 18
PROFILE = device_profile("bench-1", tacc_k=3, cable_unc_ps=1_000, calib_unc_ps=2_000,
                         timescale_unc_ps=50_000, osc_y_ppq=10_000, osc_aging_ppq_day=5_000,
                         host_ppm=50, firmware="SYNTHETIC")
MONO0 = 1_000_000_000_000


def _gps_abs(tow_ms, sub_ps=0):
    return gnss_to_abs_utc_ps(gnss_week_ps("GPS", WEEK) + tow_ms * 1_000_000_000 + sub_ps, LEAP)


def pps_blob(*, spoof=1, qerr=-1234, extra=(), tp_kw=None, nav_ok=True, seq=0):
    frames = [synth.tim_tp(TOW_MS, 0, qerr, WEEK, **(tp_kw or {})),
              synth.nav_timegps(TOW_MS - 1000, -250, WEEK, LEAP, 7,
                                valid=0b111 if nav_ok else 0b011),
              synth.nav_status(spoof=spoof), *extra]
    return evidence_blob("PPS", PROFILE, frames, MONO0, seq)


def osc_blob(count, tow_ms, sub_ns, mono, *, anchor=None, seq=0, profile=PROFILE):
    frames = [synth.tim_tm2(count, WEEK, tow_ms, sub_ns, 12),
              synth.nav_timegps(tow_ms - 500, 0, WEEK, LEAP, 7), synth.nav_status()]
    return evidence_blob("OSC", profile, frames, mono, seq,
                         anchor=None if anchor is None else evidence_digest(anchor))


# ---- PPS mode ---------------------------------------------------------------
def test_pps_derivation_is_exact():
    d = derive(pps_blob())
    (s,) = d["sources"]
    assert s["type"] == "GNSS-PPS/v1" and s["auth"] == AUTH_RECEIVER
    assert s["claimed_abs_ps"] == _gps_abs(TOW_MS)
    # 3 * tAcc(7 ns) + |qErr| + cable + calibration + timescale + rounding residue
    assert s["uncertainty_ps"] == 3 * 7_000 + 1_234 + 1_000 + 2_000 + 50_000 + 0
    assert d["consistency"] == NO_ANCHOR


def test_receiver_spoof_flag_and_osnma_report_are_recorded_as_receiver_claims():
    assert derive(pps_blob(spoof=2))["sources"][0]["auth"] == AUTH_SPOOF
    # OSNMA is Galileo-only; on a GPS time frame the receiver's report is not used.
    assert derive(pps_blob(extra=[synth.sec_osnma()]))["sources"][0]["auth"] == AUTH_RECEIVER


def test_osnma_report_on_galileo_time_is_still_only_receiver_asserted():
    frames = [synth.tim_tp(TOW_MS, 0, 0, 1362, time_ref_gnss=3),
              synth.nav_timegal(TOW_MS - 1000, TOW_MS // 1000 - 1, 0, 1362, LEAP, 9),
              synth.nav_status(), synth.sec_osnma()]
    d = derive(evidence_blob("PPS", PROFILE, frames, MONO0, 0))
    assert d["system"] == "GAL"
    assert d["sources"][0]["auth"] == AUTH_OSNMA_REPORTED != AUTH_OSNMA_VERIFIED
    assert d["sources"][0]["claimed_abs_ps"] == _gps_abs(TOW_MS)   # GST week 1362 == GPS 2386


@pytest.mark.parametrize("blob,match", [
    (lambda: pps_blob(nav_ok=False), "not fully valid"),
    (lambda: pps_blob(tp_kw={"qerr_invalid": 1}), "qErr"),
    (lambda: pps_blob(tp_kw={"time_base": 1}), "GNSS time base"),
    (lambda: pps_blob(tp_kw={"time_ref_gnss": 3}), "reference GNSS"),
    (lambda: pps_blob(extra=[synth.tim_tm2(0, WEEK, TOW_MS, 0, 1)]), "not used by this mode"),
    (lambda: pps_blob(extra=[synth.nav_status()]), "exactly one NAV-STATUS"),
])
def test_pps_refuses_evidence_it_cannot_stand_behind(blob, match):
    with pytest.raises(EvidenceError, match=match):
        derive(blob())


def test_frames_from_different_epochs_are_refused():
    frames = [synth.tim_tp(TOW_MS, 0, 0, WEEK), synth.nav_timegps(TOW_MS - 5000, 0, WEEK, LEAP, 7),
              synth.nav_status()]
    with pytest.raises(EvidenceError, match="2 s apart"):
        derive(evidence_blob("PPS", PROFILE, frames, MONO0, 0))


# ---- OSC mode: the separable-sources case ------------------------------------
TRUE_DRIFT_NS = 1


def _chain(gnss_shift_ns=0):
    a = osc_blob(65530, TOW_MS, 250, MONO0)
    # 100 oscillator seconds later; the counter wraps. At |y| <= 1e-11 the edge can
    # drift at most 1 ns in 100 s, and it does. (This scenario once said 300 ns, and
    # the consistency check rightly called that physically impossible drift a
    # disagreement: 300 ns in 100 s is a 3e-9 oscillator, not the declared one.)
    b = osc_blob(94, TOW_MS + 100_000, 250 + TRUE_DRIFT_NS + gnss_shift_ns, MONO0 + 100_000_020_000,
                 anchor=a, seq=1)
    return a, b


def test_osc_anchor_has_one_source_and_no_verdict():
    a, _ = _chain()
    d = derive(a)
    assert [s["type"] for s in d["sources"]] == ["GNSS-EXTINT/v1"]
    assert d["consistency"] == NO_ANCHOR


def test_osc_honest_gnss_agrees_with_holdover():
    a, b = _chain()
    d = derive(b, {evidence_digest(a): a})
    g, h = d["sources"]
    assert (g["type"], h["type"], h["auth"]) == ("GNSS-EXTINT/v1", "OSC-HOLDOVER/v1", AUTH_OSC)
    a_unc = 3 * 7_000 + 12_000 + 1_000 + 2_000 + 50_000
    assert h["claimed_abs_ps"] == _gps_abs(TOW_MS, 250_000) + 100 * PS
    assert h["uncertainty_ps"] == a_unc + drift_bound_ps(100, 10_000, 5_000)
    assert d["consistency"] == CONSISTENT


def test_osc_shifted_gnss_disagrees_and_the_hull_still_holds_the_true_time():
    a, b = _chain(gnss_shift_ns=50_000)          # a 50 us delay attack on GNSS
    d = derive(b, {evidence_digest(a): a})
    assert d["consistency"] == DISAGREE
    true_edge = _gps_abs(TOW_MS + 100_000, (250 + TRUE_DRIFT_NS) * 1000)
    lo, hi = d["interval_abs"]
    assert lo <= true_edge <= hi
    g = d["sources"][0]
    assert not (g["claimed_abs_ps"] - g["uncertainty_ps"] <= true_edge
                <= g["claimed_abs_ps"] + g["uncertainty_ps"])   # GNSS alone was wrong


def test_a_shift_inside_the_bounds_is_not_detected_but_the_hull_stays_honest():
    # The limitation, stated as a test: 100 ns of delay hides inside ~86 ns + ~87 ns
    # of combined uncertainty, so no disagreement is reported and GNSS alone now
    # excludes the true time. The hull does not, because the holdover source does not.
    a, b = _chain(gnss_shift_ns=100)
    d = derive(b, {evidence_digest(a): a})
    assert d["consistency"] == CONSISTENT
    true_edge = _gps_abs(TOW_MS + 100_000, (250 + TRUE_DRIFT_NS) * 1000)
    g = d["sources"][0]
    assert not (g["claimed_abs_ps"] - g["uncertainty_ps"] <= true_edge)
    lo, hi = d["interval_abs"]
    assert lo <= true_edge <= hi


def test_an_anchor_taken_under_a_spoofing_flag_is_refused():
    frames = [synth.tim_tm2(65530, WEEK, TOW_MS, 250, 12),
              synth.nav_timegps(TOW_MS - 500, 0, WEEK, LEAP, 7), synth.nav_status(spoof=2)]
    a = evidence_blob("OSC", PROFILE, frames, MONO0, 0)
    b = osc_blob(94, TOW_MS + 100_000, 251, MONO0 + 100_000_020_000, anchor=a, seq=1)
    with pytest.raises(EvidenceError, match="indicated spoofing"):
        derive(b, {evidence_digest(a): a})


def test_an_anchor_with_stray_frames_is_refused():
    frames = [synth.tim_tm2(65530, WEEK, TOW_MS, 250, 12), synth.tim_tp(TOW_MS, 0, 0, WEEK),
              synth.nav_timegps(TOW_MS - 500, 0, WEEK, LEAP, 7), synth.nav_status()]
    a = evidence_blob("OSC", PROFILE, frames, MONO0, 0)
    b = osc_blob(94, TOW_MS + 100_000, 251, MONO0 + 100_000_020_000, anchor=a, seq=1)
    with pytest.raises(EvidenceError, match="not used by this mode"):
        derive(b, {evidence_digest(a): a})


def test_osc_anchor_must_be_supplied_and_must_match():
    a, b = _chain()
    with pytest.raises(LookupError):
        derive(b)
    other = device_profile("bench-1", tacc_k=3, cable_unc_ps=1_000, calib_unc_ps=2_000,
                           timescale_unc_ps=50_000, osc_y_ppq=1, osc_aging_ppq_day=0,
                           host_ppm=50, firmware="SYNTHETIC")
    a2 = osc_blob(65530, TOW_MS, 250, MONO0, profile=other)
    b2 = osc_blob(94, TOW_MS + 100_000, 550, MONO0 + 100_000_020_000, anchor=a2, seq=1)
    with pytest.raises(EvidenceError, match="different device profile"):
        derive(b2, {evidence_digest(a2): a2})


# ---- into chronology-protocol, and back out through the verifier -------------
def _obs(blob, anchors=None, previous=None):
    return observation(blob, derive(blob, anchors), GENESIS, previous)


def test_observation_is_a_canonical_ctp_object_in_the_shared_utc_frame():
    blob = pps_blob()
    u = _obs(blob)
    raw = u.canonical()                                   # ctp's own validation
    assert UnsignedObservation.from_obj(cbor.loads(raw)).canonical() == raw
    assert u.reference_frame.startswith("UTC-PS-ORIGIN-")
    assert 0 <= u.interval.lower < u.interval.upper < 86_400 * PS


def test_verifier_passes_what_derive_produced():
    a, b = _chain()
    anchors = {evidence_digest(a): a}
    ua = _obs(a)
    ub = _obs(b, anchors, ua.lineage_id())
    assert verify_observation(ua, a)[1] == "PASS"
    checks, verdict, facts = verify_observation(ub, b, anchors)
    assert verdict == "PASS", checks
    assert facts["consistency"] == CONSISTENT


def test_disagreement_is_a_finding_not_a_verification_failure():
    a, b = _chain(gnss_shift_ns=50_000)
    anchors = {evidence_digest(a): a}
    checks, verdict, facts = verify_observation(_obs(b, anchors), b, anchors)
    assert verdict == "PASS" and facts["consistency"] == DISAGREE


def test_a_tightened_claim_fails():
    blob = pps_blob()
    u = _obs(blob)
    s = u.sources[0]
    u.sources = [SourceObservation(s.source_type, s.claimed_ps, s.uncertainty_ps // 2,
                                   s.auth_state, s.evidence)]
    assert verify_observation(u, blob)[1] == "FAIL"


def test_a_widened_interval_fails_too():
    # Wider is not "safer": the interval must be exactly what the evidence supports.
    blob = pps_blob()
    u = _obs(blob)
    u.interval = Interval(u.interval.lower - 1, u.interval.upper)
    assert verify_observation(u, blob)[1] == "FAIL"


def test_evidence_swapped_for_another_blob_fails():
    u = _obs(pps_blob())
    assert verify_observation(u, pps_blob(qerr=-999))[1] == "FAIL"


def test_missing_anchor_is_indeterminate_not_fail():
    a, b = _chain()
    ub = _obs(b, {evidence_digest(a): a})
    checks, verdict, _ = verify_observation(ub, b, anchors=None)
    assert verdict == "INDETERMINATE"


def test_an_osnma_verified_claim_is_flagged_and_fails_today():
    blob = pps_blob()
    u = _obs(blob)
    s = u.sources[0]
    u.sources = [SourceObservation(s.source_type, s.claimed_ps, s.uncertainty_ps,
                                   AUTH_OSNMA_VERIFIED, s.evidence)]
    checks, verdict, _ = verify_observation(u, blob)
    # The OSNMA check cannot run yet, and says so. But derive never emits that
    # state, so the claim also fails re-derivation — a definite failure, which
    # outranks the unavailable check.
    assert checks["TW_OSNMA"] == "UNAVAILABLE"
    assert checks["TW_SOURCES_REDERIVED"] is False and verdict == "FAIL"


def test_hardware_witness_sits_in_a_quorum_with_other_witnesses():
    u = _obs(pps_blob())
    mid = (u.interval.lower + u.interval.upper) // 2
    ntp_like = [Interval(mid - 50 * 10**9, mid + 80 * 10**9),      # +-tens of ms
                Interval(mid - 30 * 10**9, mid + 60 * 10**9),
                Interval(mid - 90 * 10**9, mid + 20 * 10**9)]
    r = consensus([u.interval, *ntp_like], f=1)
    assert r["verdict"] == "CONSENSUS"
    assert r["interval"].lower <= mid <= r["interval"].upper
