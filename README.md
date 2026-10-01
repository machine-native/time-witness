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

It also verifies **Galileo OSNMA offline** (SPEC §10): from raw navigation pages it
checks the public key against Galileo's Merkle root, the signed chain root, and each
TESLA key back to it. A verified key is bound to its own 30-second sub-frame and was
secret until then, so evidence containing one is no older than that sub-frame: a
lower bound on time that comes from the Galileo constellation, not from any server.
It reproduces every value in the official worked examples and passes all 18
official test vectors. The Merkle root it rests on is itself authenticated through
the EUSPA PKI (certificate chain, CRLs, signature, pinned root), and the whole
capture can travel inside the evidence, so the bound re-derives from the bytes of a
chronology-protocol sandwich (SPEC §10.5, §11).

## Try it

Requires Python 3.10+ and a chronology-protocol checkout (installed, or cloned as a
sibling directory `../chronology-protocol`). No other dependencies.

```bash
python scripts/fetch_osnma_vectors.py        # official OSNMA vectors, digest-checked (optional)
python -m pytest -q                          # zero failures is the result
python scripts/make_synthetic_vectors.py     # regenerates vectors/synthetic/ identically
```

The `openssl` command is needed for ECDSA. Without the fetched vectors, the tests
that need them report SKIPPED rather than passing.

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
| `tw/osnma.py` | offline Galileo OSNMA verifier and the lower bound it supports |
| `tw/gsc_pki.py` | authenticates the OSNMA Merkle tree through the EUSPA PKI |
| `tw/ubx_inav.py` | Galileo E1-B pages out of u-blox RXM-SFRBX, timed from the navigation data |
| `tw/sandwich_ext.py` | the chronology-protocol sandwich extension for this profile |
| `tw/galmon_feed.py` | Galileo E1-B pages from the public galmon stream, rebuilt and CRC-checked |
| `scripts/capture_galmon.py`, `scripts/galileo_bound.py` | capture live Galileo pages; turn a capture into a bound |
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
  implementation (pyubx2), not yet against a receiver, and the mapping from a
  receiver's raw-subframe output to I/NAV pages is not yet pinned.
- The operational Merkle tree has not been downloaded: it is published to
  registered GSC users. `scripts/authenticate_merkle_tree.py` authenticates it
  once it is.
- OSNMA tags are checked for consistency only: a recording cannot show it was
  received before the keys were disclosed, so navigation data is never called
  authenticated. A receiver's own OSNMA report is recorded as the receiver's claim.
- Device profile values are declarations. No oscillator has been characterised.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
