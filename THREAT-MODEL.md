# Threat model — TW-GNSS/v1

What an attacker can do to a hardware time witness, what the profile does about
it, and — mostly — what it does not.

## Assets

The claim that a physical edge occurred inside a stated UTC interval, and the
integrity of the bytes that support it.

## Attacks and responses

| attack | effect | response in v1 | residual |
|---|---|---|---|
| **GNSS spoofing** (forged signals) | receiver reports a false time | OSC mode: holdover source is independent of GNSS; disagreement is reported; the interval is the hull, so it still contains the truth if the oscillator is honest | a shift inside the combined bounds is not detected (tested: `test_a_shift_inside_the_bounds_is_not_detected_but_the_hull_stays_honest`) |
| **Meaconing / replay** (genuine signals, delayed) | receiver time lags truth; OSNMA still verifies | same as spoofing: delay shows up against holdover | same |
| **Slow pull-off** (drift GNSS below the oscillator's drift rate) | receiver time walks away gradually | holdover is anchored once and never re-disciplined inside a chain, so the pull-off accumulates against it and is detected once it exceeds the holdover bound | undetected while inside the bound; the bound grows quadratically with aging, so long chains weaken detection |
| **Anchor taken under spoofing** | holdover inherits a false anchor | none within one chain; the anchor is itself a GNSS-EXTINT source with `RECEIVER_ASSERTED` state | the anchor's truth rests on the receiver at anchor time; quorum with other witness classes (NTP, Roughtime) is the check |
| **Time-sync manipulation of OSNMA** (Wang et al. 2025) | receiver's local reference time moved while meeting OSNMA's 30 s requirement; forged/replayed data passes | OSNMA is never treated as verified in v1; an OSNMA verifier must take its time reference from an independent signed bound (Roughtime, ±2–4 s, inside 30 s), never from the receiver's own GNSS time | open until that verifier exists |
| **False device profile** (declaring a better oscillator than fitted) | holdover bound too tight | declared values are labelled declarations; they cannot be verified from the bytes | a lying operator can narrow the holdover interval; mitigations are an independently measured Allan deviation and quorum with other witnesses |
| **Compromised receiver firmware** | arbitrary frames with valid checksums | none: UBX checksums are integrity against line noise, not authentication | the receiver is trusted for its own messages, as stated by every `RECEIVER_ASSERTED` state |
| **Compromised host** | fabricated blobs, false monotonic times | observation signatures (chronology-protocol PQ-5) bind the host key; edge counting refuses monotonic time inconsistent with the counter | a host key holder can fabricate a self-consistent chain; that is why no single witness is a quorum |
| **Frames composed after the fact** | blob assembled from unrelated epochs | epoch sanity (≤ 2 s between pulse/mark and navigation epoch); raw capture keeps offsets so frames can be traced to the stream | a fully fabricated capture is the compromised-host case |
| **Edge miscount** | holdover off by whole seconds | counter mod 65536 plus host monotonic, refusal at ≥ 0.5 s tolerance | a host clock outside its declared ppm could select a wrong candidate; the declared bound is a declaration |

## What OSNMA does and does not give

OSNMA authenticates Galileo navigation **data** (ephemeris, clock and time
parameters) using TESLA, with a root key signed by Galileo. It does **not**
authenticate signal **timing**, so it cannot detect a delayed replay of genuine
signals, and its own security requires the receiver to know Galileo System Time to
within 30 s (OSNMA receiver guidelines v1.1). Both gaps are why the oscillator
source exists and why any OSNMA verifier here needs an independent time bound.

## Out of scope

- Physical attacks on the oscillator (temperature, vibration, magnetic fields).
  These are the oscillator's error sources; the declared bounds must include them.
- Relativistic corrections below the ns level for a fixed ground station.
- Availability: jamming stops observations, which is visible as their absence.
