# TW-GNSS/v1 — hardware time witness profile

Status: **draft.** Specified and implemented in software against
synthetic frames. No receiver has produced evidence under this profile yet.

This is a witness profile of chronology-protocol (SPEC v0.1.0). It defines how a
GNSS receiver and a local oscillator produce `UnsignedObservation`s. It defines no
consensus, checkpoint, anchor or signature rule; those are chronology-protocol's.

## 1. What an observation claims

An observation claims: *this physical edge occurred inside this UTC interval,
according to these separable sources, as derived from these bytes.*

- The **event** is a physical 1 PPS edge: the receiver's own time pulse (mode
  `PPS`) or an external oscillator's edge time-marked by the receiver (mode `OSC`).
- Each **source** is one independent account of when that edge occurred.
- The **interval** is the hull of the source intervals (§6).

It does not claim the receiver was honest, that GNSS was not spoofed, or that the
declared device profile is accurate. Integrity is checkable; truth is bounded.

## 2. Evidence blob

Canonical CBOR, chronology-protocol's restricted subset (no floats, no tags,
deterministic key order). Integer keys:

| key | value |
|---:|---|
| 1 | `"TW-GNSS/v1"` |
| 2 | mode: `"PPS"` or `"OSC"` |
| 3 | device profile (§3) |
| 4 | array of raw UBX frames, each byte-exact including sync and checksum |
| 5 | host monotonic time of acquisition, ns |
| 6 | anchor: evidence digest pair of an earlier `OSC` blob, or null |
| 9 | sequence number |
| 10, 11, 12 | sandwich challenge `q`, `B0` hash, session id — or null |

Keys 10–12 follow chronology-protocol's sandwich evidence convention. Evidence
digests are `digest_pair("CHRONOLOGY/SOURCE-EVIDENCE/v1", blob)`.

## 3. Device profile

Declared per device, carried in every blob, and required to be **identical**
between an `OSC` blob and its anchor (an oscillator swap starts a new chain).

| key | meaning | unit |
|---:|---|---|
| 1 | `"TW-DEVICE/v1"` | |
| 2 | device name (witness identity derives from it) | text |
| 3 | coverage factor `k` applied to receiver `tAcc` | integer ≥ 1 |
| 4 | antenna cable delay uncertainty | ps |
| 5 | PPS / time-mark calibration uncertainty | ps |
| 6 | GNSS-to-UTC timescale uncertainty (unmodelled A0/GGTO terms) | ps |
| 7 | oscillator fractional frequency offset bound `|y|` | parts per 10¹⁵ |
| 8 | oscillator aging bound | parts per 10¹⁵ per day |
| 9 | host monotonic clock bound | ppm |
| 10 | receiver firmware | declared text |

A declared value is a declaration. Values taken from a datasheet must say so in
the release record that uses them; only a measurement of this unit is evidence.

## 4. Frames

UBX layouts as in the u-blox interface description; cross-checked against pyubx2
1.3.8 (docs/SOURCES.md); not yet pinned against receiver bytes.

| mode | required, exactly one each | optional (passive) |
|---|---|---|
| PPS | TIM-TP, NAV-STATUS, NAV-TIMEGPS **or** NAV-TIMEGAL | RXM-SFRBX, SEC-OSNMA (≤ 1) |
| OSC | TIM-TM2, NAV-STATUS, NAV-TIMEGPS **or** NAV-TIMEGAL | RXM-SFRBX, SEC-OSNMA (≤ 1) |

Any other frame, a duplicate, a bad checksum or a wrong payload length rejects the
blob. The navigation-time message selects the GNSS time frame (GPS or Galileo).

Required validity: NAV-TIME tow, week and leap-second flags all valid; NAV-STATUS
`gpsFixOk`; TIM-TP on a GNSS time base with valid `qErr` and `timeRefGnss` matching
the navigation frame; TIM-TM2 rising edge on the GNSS time base with the time-valid
flag. The pulse or mark must lie within 2 s of the navigation epoch.

## 5. Derivation (integer picoseconds throughout)

Time scale: GPS time from 1980-01-06T00:00:00Z; Galileo week `w` is GPS week
`w + 1024`; UTC = GNSS − `leapS` from the navigation message. Absolute UTC
picoseconds are intermediate only; stored values are relative to the declared
origin `UTC-PS-ORIGIN-<unix-s>/v1`, the same frame the NTP and Roughtime profiles
use, so all can share one quorum.

**GNSS-PPS/v1** (mode PPS), from TIM-TP:

    t = week + towMS·10⁹ + floor(towSubMS·10⁹ / 2³²)                       [ps]
    u = k·tAcc·10³ + |qErr| + cable + calib + timescale + r

`r` is 1 if the sub-millisecond floor discarded a remainder, else 0. `qErr` is not
corrected in v1 (that needs a counter on the pulse); it widens the interval.

**GNSS-EXTINT/v1** (mode OSC), from TIM-TM2 rising edge:

    t = wnR + towMsR·10⁹ + towSubMsR·10³                                    [ps]
    u = k·tAcc·10³ + accEst·10³ + cable + calib + timescale

**OSC-HOLDOVER/v1** (mode OSC with an anchor). The anchor blob must itself satisfy
§4 in mode OSC, carry the identical device profile, be on the same GNSS time frame,
and not have been taken while NAV-STATUS indicated spoofing — everything after it
inherits its time. With the anchor's GNSS-EXTINT result `(t_a, u_a)`:

    n = oscillator edges since the anchor (§5.1)
    t = t_a + n·10¹²
    u = u_a + ceil(n·10¹²·y / 10¹⁵) + ceil(D·n²·10¹² / (2·86400·10¹⁵))

### 5.1 Counting edges

`n` is determined by the receiver's 16-bit TIM-TM2 edge counter (n mod 65536) and
the host monotonic clock, which selects the unique candidate within
`elapsed·ppm/10⁶ + 100 ms`. If that tolerance reaches 0.5 s, or no candidate fits,
the blob is rejected. GNSS timestamps are never used to count edges: that would
let a spoofer choose `n`.

## 6. Interval and consistency

    interval = [ min(tᵢ − uᵢ), max(tᵢ + uᵢ) ]      over the observation's sources

The hull, not the intersection. If either source is honest, the hull contains the
true time; an intersection would be pulled off the truth by a GNSS source spoofed
within the holdover bound, with neither interval looking unusual.

Mode OSC with an anchor also reports `CONSISTENT` if the two source intervals
overlap and `GNSS_OSCILLATOR_DISAGREE` if they do not. Disagreement is a finding
about the world, not a verification failure — the analogue of `TIME_CONFLICT`.

## 7. Authentication states

| `auth_state` | meaning |
|---|---|
| `RECEIVER_ASSERTED` | the receiver's word; nothing independent |
| `RECEIVER_ASSERTED_OSNMA_REPORTED` | Galileo time frame, receiver says OSNMA is enabled (SEC-OSNMA); **not verified** |
| `RECEIVER_ASSERTED_SPOOFING_INDICATED` | NAV-STATUS `spoofDetState` ≥ 2 |
| `LOCAL_OSCILLATOR_MODEL` | holdover prediction under the declared profile |
| `VERIFIED_OSNMA` | **reserved** for an offline OSNMA verifier (§10); never emitted by v1 |

## 8. Observation mapping

- `witness_id` = `digest_pair("CHRONOLOGY/WITNESS/v1", "TW-GNSS:" + device name).sha256`
- `sequence`, `previous`: chronology-protocol's per-witness chain; `sequence` is blob key 9
- `monotonic_ps` = blob key 5 × 1000
- `hardware_state` = `digest_pair("CHRONOLOGY/STATE/v1", canonical(profile))`
- `firmware_state` = `digest_pair("CHRONOLOGY/STATE/v1", canonical({1:"TW-FIRMWARE/v1", 2:firmware}))`
- every source's evidence digest is the blob's evidence digest
- frame origin: 00:00:00Z of the UTC day containing the interval midpoint, unless declared

## 9. Verification

`tw.verify.verify_observation(obs, blob, anchors)` re-derives every source and the
interval from the blob and compares exactly. A **wider** interval than the evidence
supports fails like a narrower one: the claim must be what the evidence says.

| verdict | when |
|---|---|
| `PASS` | every check ran and matched |
| `FAIL` | any check ran and did not match, or the blob is malformed |
| `INDETERMINATE` | no failures, but a check could not run: anchor blob not supplied, or a `VERIFIED_OSNMA` claim |

## 10. Reserved: Galileo as a lower causal bound (NOT IMPLEMENTED)

OSNMA discloses a TESLA chain key in each 30 s subframe. A key is secret until
disclosed and verifiable back to a root that Galileo signs. Evidence containing a
verified key was therefore acquired after that key's disclosure time — a lower
bound supplied by a party unconnected to this project.

The raw material rides in blob key 4 as RXM-SFRBX frames. The verifier that turns
it into a claim (TESLA chain to KROOT, KROOT's ECDSA signature, the public-key
Merkle tree, MACK tag checks) will be implemented against the official OSNMA ICD
test vectors, not from memory, and until it is, no observation claims it.

## 11. Relation to the sandwich verifier

chronology-protocol's `verify_sandwich` does not yet recognise `TW-GNSS/v1` blobs
and would reject a bundle containing one. Teaching it is a change to
chronology-protocol, made there.
