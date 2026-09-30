# time-witness

A hardware time witness for [chronology-protocol](https://github.com/machine-native/chronology-protocol):
a GNSS timing receiver and a free-running atomic oscillator whose observations
carry **raw physical evidence** — the receiver's own timing messages, byte for
byte, and the oscillator's independent account of the same edge — not a server's
statement of the time.

**Status: specified, implemented in software, never run on hardware.** Every test
here runs on synthetic frames. No receiver has produced evidence under this
profile, and nothing in this repository claims otherwise.

## Why another witness

chronology-protocol already accepts NTP, signed Roughtime and photographic
witnesses. Each of them reports a time that something else asserted. This profile
is different in two ways:

1. **Two separable sources for one physical edge.** The oscillator's 1 PPS edge is
   timed by GNSS *and* predicted by the oscillator alone from an earlier anchor.
   If GNSS time is spoofed or delayed beyond the oscillator's holdover bound, the
   two stop overlapping and the witness says so. The observation interval is their
   hull, so it contains the true time as long as either source is honest.
2. **Raw evidence, re-derivable.** A verifier re-parses the receiver's frames and
   recomputes every number in the observation. A claim that is wider *or* narrower
   than the evidence supports fails.

It also carries raw Galileo navigation pages, reserved for an offline OSNMA
verifier that does not exist yet (SPEC §10).

## Try it

Requires Python 3.10+ and a chronology-protocol checkout (installed, or cloned as a
sibling directory `../chronology-protocol`). No other dependencies.

```bash
python -m pytest -q                          # zero failures is the result; synthetic frames only
python scripts/make_synthetic_vectors.py     # regenerates vectors/synthetic/ identically
```

`vectors/synthetic/` holds four cases — a receiver pulse, an oscillator anchor, an
honest follow-up, and one with GNSS delayed by 50 µs — each with its expected
verdict. They are labelled SYNTHETIC in every filename because they are not
evidence: chronology-protocol's invariant 14 applies.

## What is here

| path | what |
|---|---|
| `SPEC.md` | the TW-GNSS/v1 profile: evidence blob, derivation, interval rule, verdicts |
| `THREAT-MODEL.md` | attacks, responses, and the residuals, stated as such |
| `tw/ubx.py` | strict UBX codec for the seven messages the profile reads |
| `tw/timescale.py` | GPS/Galileo time to the shared UTC picosecond frame, integer only |
| `tw/holdover.py` | the oscillator drift bound and edge counting |
| `tw/witness.py` | evidence blob, deterministic derivation, chronology-protocol observation |
| `tw/verify.py` | offline verifier: PASS / FAIL / INDETERMINATE |
| `scripts/capture_ubx.py` | raw serial capture with host monotonic times (not hardware-tested) |
| `docs/HARDWARE.md` | reference architecture and what each part must prove before purchase |
| `docs/SOURCES.md` | every external fact, its source, and how it was cross-checked |

## Boundaries

chronology-protocol owns consensus, checkpoints, signatures, anchoring and the
sandwich construction; this repository redefines none of them. It produces
`UnsignedObservation`s that chronology-protocol already accepts in a checkpoint.
chronology-protocol's sandwich verifier does not yet recognise this profile's
evidence blobs; that change belongs in chronology-protocol.

## Not yet done

- No hardware capture. UBX layouts are cross-checked against an independent
  implementation (pyubx2), not yet against a receiver.
- No OSNMA verification. A receiver's OSNMA report is recorded as the receiver's
  claim; `VERIFIED_OSNMA` is reserved and never emitted.
- Device profile values are declarations. No oscillator has been characterised.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
