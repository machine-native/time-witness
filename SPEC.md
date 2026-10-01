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
| `VERIFIED_OSNMA` | **invalid** for any timing source: OSNMA authenticates navigation data, never signal arrival time. An observation claiming it fails. What OSNMA does prove is a separate claim (§10) |

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
| `INDETERMINATE` | no failures, but a check could not run: anchor blob not supplied |

## 10. Galileo as a lower causal bound

Implemented in `tw/osnma.py` against the Galileo OSNMA SIS ICD Issue 1.1, the OS
SIS ICD Issue 2.2 page and word layouts, the OSNMA Receiver Guidelines Issue 1.3
Annex A worked examples, and all 18 of its Annex B official test vectors
(docs/SOURCES.md). Input is raw E1-B I/NAV pages (240 bits each: even part, odd
part), from any number of satellites.

### 10.1 What verifies offline

| step | checked against | property |
|---|---|---|
| page CRC-24Q | the page itself | pages are received as transmitted |
| public key | a Merkle root obtained out of band (GSC OSNMA server), via the DSM-PKR or a GSC key file | the key is Galileo's |
| DSM-KROOT | that key's ECDSA signature (P-256/SHA-256 or P-521/SHA-512), over the NMA header and chain parameters | chain parameters and GST0 are Galileo's |
| TESLA key | hashing back to KROOT; every step includes the GST of its sub-frame | the key belongs to exactly one sub-frame time |

A TESLA key is secret until Galileo broadcasts it. So bytes that contain a verified
key were assembled no earlier than the start of that key's sub-frame. That is the
claim, `GALILEO-TESLA-LOWER-BOUND/v1`, stated in GST at the start of the sub-frame
of the latest usable key (`tw.osnma.galileo_lower_bound`). The key's bits arrive
over the sub-frame's 30 s; nothing tighter than the sub-frame start is claimed.

### 10.2 Keys that verify but do not count

A key is **usable** for the bound only if its secrecy until disclosure can still be
assumed. Verified keys are excluded, with the reason recorded, when:

| reason | condition (NMA header, OSNMA SIS ICD §3.1, §5.4–5.7) |
|---|---|
| `DONT_USE` | broadcast under NMAS = Don't Use |
| `CHAIN_REVOKED` | its chain is revoked anywhere in the recording (CPKS = CREV) — including keys from before the revocation |
| `PUBLIC_KEY_REVOKED` | the public key that signed its chain is revoked (CPKS = PKREV) |
| `AFTER_ALERT` | at or after a verified OSNMA Alert Message |

Excluding a revoked chain's earlier keys is deliberate: revocation means the keys
may have been known before their disclosure, which is precisely what a time bound
cannot tolerate. Revocations published **after** the recording cannot be seen in
its bytes; the bound is stated as conditional on the chain not having been revoked
later, and a verifier checks that against the GSC's published status.

### 10.3 What does not verify offline

Tags authenticate navigation data only if the data was received **before** the key
that checks it was disclosed — TESLA's time-synchronisation assumption. A recording
does not show when it was received. Tags and MACSEQ that match are therefore
reported as `TAG_CONSISTENT` / `MACSEQ_CONSISTENT`: integrity of the recording, not
authenticity of its navigation data. In particular the broadcast leap-second count
(word type 6, ADKD 4) is consistent, not authenticated, when checked after the fact.

### 10.4 The trust anchor

The Merkle root is the only OSNMA input the satellites do not broadcast. The GSC
publishes the Merkle-tree file to registered users (OSNMA IDD ICD 1.1, §3). It is
authenticated as that ICD asks of manufacturers (§4.3), by `tw.gsc_pki`:

1. the end-entity certificate chains to the EUSPA Root CA through the Galileo SCA
   and the OSNMA ICA, every certificate checked against its issuer's CRL;
2. the end-entity certificate is the Merkle-tree role;
3. its ECDSA P-256/SHA-256 signature covers the tree file byte for byte;
4. the Root CA matches the SHA-256 fingerprint pinned in `tw/gsc_pki.py`.

The Root CA is self-signed: its pin is trust on first use of
`pki.euspa.europa.eu`, recorded so that later substitution is caught, and should be
compared through a second channel by anyone relying on it. Everything above the
tree except that pin is public (`scripts/refresh_euspa_pki.py`); the tree itself is
authenticated and recorded by `scripts/authenticate_merkle_tree.py`.

### 10.5 In the evidence blob

A blob may carry a Galileo capture (key 13: raw UBX-RXM-SFRBX frames with the host
monotonic time each arrived) and the trust-anchor material (key 14: the tree file,
its signature, the end-entity and ICA bundle, the Root and SCA certificates, the
CRLs). `tw.witness.galileo_facts` re-derives from those bytes alone — with only the
Root CA fingerprint trusted from outside — the pages, their times, the
authentication of the anchor at the capture's own time, every OSNMA check, and the
bound. The facts are reported with the observation; they are not part of its
interval, which must be two-sided.

Page extraction and timing are in `tw/ubx_inav.py`: Galileo E1-B is gnssId 2,
sigId 1; words 0–3 and 4–7 carry the even and odd page parts (the mapping galmon
uses with u-blox receivers); each satellite's pages are timed from its own word-5
WN/TOW and placed 2 s apart by arrival time. Pages are CRC-checked, and a page
placed at the wrong time makes its key fail, so errors here fail closed.

**A capture must contain a complete DSM-KROOT**, or no key has anything to chain
to. Usually that is a few minutes of sky; in the half hour after 00:00, 06:00,
12:00 and 18:00 GST, when the public key is broadcast instead, it takes longer. The
official configuration-2 vector needs 6.5 minutes.

### 10.6 Pages relayed by someone else

The bound rests on possessing keys Galileo kept secret until broadcast, which no
relay can produce early. So pages need not come from our own receiver: `tw/galmon_feed.py`
reads the public galmon stream (a network of mostly u-blox receivers), rebuilds each
E1-B page from the fields galmon carries and checks its CRC-24Q; identical copies from
several receivers collapse to one, and two different valid versions of one slot are
both dropped. `scripts/capture_galmon.py` keeps only the E1-B navigation frames —
galmon's stream also carries volunteer stations' positions, which are dropped — and
`scripts/galileo_bound.py` turns a capture into a bound against the authenticated
trust anchor, also checking any DSM-PKR the satellites broadcast in it against that
anchor's root.

What a relay cannot give is anything about when or where a page was received; the
relay's timestamps and station identifiers are recorded and never used for a claim.
A relayed capture is therefore evidence of the Galileo bound and of nothing about a
local receiver; it is not a substitute for the hardware witness's own observation.

### 10.7 Privacy of evidence

A phone's GnssLogger log records its position (`Fix` lines) and pseudoranges from
which a position can be computed (`Raw` lines), and its file name is local clock time.
Only an extract is published (`scripts/extract_android_galileo.py`): the version header,
arrival times, and Galileo `Nav` lines, with the original's digest; the tool refuses to
write unless the extract yields exactly the pages of the original. Galmon captures keep
only Galileo navigation frames. What a published capture still reveals is which
satellites were in view at which times — broadcast data that places a recording within
a continent-sized region.

### 10.8 Not yet done

- The u-blox SFRBX mapping is independently confirmed (galmon) but not yet pinned
  against bytes from a receiver of this project's.
- The GNSS-SDR reader has not yet seen real GNSS-SDR output.

## 11. Relation to the sandwich verifier

chronology-protocol's `verify_sandwich` accepts extensions for evidence types it
does not implement (its `docs/REALITY-SANDWICH.md` §4b). `tw.sandwich_ext.EXTENSIONS`
is that extension for `TW-GNSS/v1`:

    python scripts/verify_sandwich.py BUNDLE.cbor --extension tw.sandwich_ext:EXTENSIONS

chronology-protocol checks the blob's binding to the session, the signatures, the
chain, the checkpoint and the blocks; the extension checks the observation against
its frames and reports the Galileo facts, including any
`GALILEO-TESLA-LOWER-BOUND/v1`, under `extensions` in the sandwich's facts. Without
the extension the bundle is `INDETERMINATE_UNCHECKED_EVIDENCE`, never a pass.
`tests/test_sandwich_e2e.py` runs this end to end on official Galileo data.
