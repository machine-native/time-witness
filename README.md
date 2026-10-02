# time-witness

Physical-time evidence for [chronology-protocol](https://github.com/machine-native/chronology-protocol)
from Galileo satellite signals: what a GNSS receiver actually received, byte for
byte, re-derivable by anyone — not a server's statement of the time.

## What is claimed

**A lower bound on time from the Galileo constellation, verified offline.** Galileo's
navigation-message authentication (OSNMA) releases a TESLA chain key every 30
seconds, after keeping it secret, and the chain is signed by a key the European GNSS
Service Centre publishes. Bytes that contain a verified key were therefore assembled
**no earlier than** that key's 30-second sub-frame. No relay, receiver or operator can
produce a key early, so the bound holds whoever carried the bytes.

Shown on real signals, 2026-10-01, every result re-derivable from this repository:

| evidence (in `live/`) | source of the pages | pages | bound (GST) |
|---|---|---|---|
| `galmon-2026-10-01-a` | public galmon relay, 16 min | 10,513, all CRC-valid | 09:18:30 |
| `galmon-2026-10-01-pkr` | public galmon relay, 35 min | 25,283, all CRC-valid | 12:32:30 |
| `android-m56-2026-10-01` | a Samsung Galaxy M56 phone, 20 min | 1,378, all CRC-valid | 13:50:30 |
| `galmon-2026-10-01-epoch8` | public galmon relay, 17 min | 12,574, all CRC-valid | 15:13:00 |

In each, Galileo's signed DSM-KROOT verifies under the trust anchor and every usable
TESLA key chains to it. The trust anchor — the OSNMA Merkle root — is authenticated two
independent ways: through the EUSPA PKI (certificate chain, revocation lists, signature,
pinned root; `trust/`), and by the satellites themselves, whose 12:00 GST public-key
broadcast in `galmon-2026-10-01-pkr` reaches the same root.

The last capture is chronology-protocol's **epoch 8**: recorded after that epoch's
opening block, committed by its checkpoint, and anchored in block 1270 of its chain.
`scripts/verify_galileo_epoch.py` checks both halves from the published bytes and
reports `GALILEO_BOUND`:

    Galileo key release (GST 15:13:00)  <  capture  <  anchor block 1270

Each evidence file is also stamped with OpenTimestamps, which brackets the same bytes
**between a Galileo key release and a public Bitcoin block** — neither bound depends on
anything this project operates (`scripts/bracket.py`, reports in `*.bracket.json`). The
first three are attested in Bitcoin block 969456, the epoch-8 capture from block
969461.

The verifier is checked against the official material, not against itself: every
worked example in the Galileo OSNMA Receiver Guidelines (Annex A) reproduces exactly,
and all 18 official test vectors (Annex B) pass with no key, tag or sequence mismatch.

## What is not claimed

- **Not an instant, only a lower bound.** The bound says "no earlier than"; the upper
  side comes from an anchor (a Bitcoin block, or a chronology-protocol sandwich).
- **Not when or where anything was received.** A relay's or phone's timestamps and
  identifiers are recorded and never used for a claim.
- **Not authenticated navigation data.** OSNMA tags only authenticate data received
  before their key was disclosed, which a recording cannot show; they are reported as
  *consistent*, never as authenticated.
- **Not unconditional.** The bound assumes the TESLA chain was not revoked after the
  recording; revocations inside a recording are detected and those keys excluded.
- **No nanosecond timing yet.** The receiver/oscillator design in `SPEC.md` (a PPS
  receiver with a free-running atomic reference, two separable time sources per edge)
  is specified and implemented in software, tested on synthetic frames only, and
  claims nothing until real hardware produces evidence for it.

## Privacy of the evidence

Phone GNSS logs record where they were taken. Only a position-free extract is
published (`scripts/extract_android_galileo.py`): navigation pages and arrival times,
no fixes, no pseudoranges, and not the original file name (GnssLogger names logs by
local clock time). The extract records the original's digest and is proven to yield
the same pages. Galmon captures keep only Galileo navigation frames; galmon's other
messages, including station positions, are dropped at capture. What remains is
broadcast data: which satellites were in view at a given time, which places a
recording on a continent-sized region, no finer.

## Verify it

Requires Python 3.10+, the `openssl` command, and a chronology-protocol checkout
(installed, or cloned as a sibling directory `../chronology-protocol`). No other
Python dependencies.

```bash
python scripts/fetch_osnma_vectors.py      # the official OSNMA test vectors, digest-checked
python -m pytest -q                        # zero failures is the result
python scripts/bracket.py live/android-m56-2026-10-01/galileo-extract.txt --offline
```

Without the official vectors the tests that need them report SKIPPED, not passed.
On Windows, clone to a short path: the official vectors' deepest file names exceed the
260-character path limit from a deeply nested directory, and OpenSSL cannot open them.
The real-sky tests use only public data: the satellites' own key broadcast and the
committed Merkle root.

## Getting Galileo pages yourself

`docs/RECEIVER-ROUTES.md`: the public galmon relay, an Android phone that reports
navigation messages, an RTL-SDR dongle with GNSS-SDR, or a u-blox receiver. Every
route ends in `scripts/galileo_bound.py` and the same checks.

## What is here

| path | what |
|---|---|
| `SPEC.md` | the TW-GNSS/v1 profile, and §10 the Galileo lower bound |
| `THREAT-MODEL.md` | attacks, responses, and the residuals, stated as such |
| `tw/osnma.py` | offline Galileo OSNMA verifier and the bound it supports |
| `tw/gsc_pki.py` | authenticates the OSNMA Merkle tree through the EUSPA PKI |
| `tw/galmon_feed.py`, `tw/android_nav.py`, `tw/gnsssdr_nav.py`, `tw/ubx_inav.py` | page readers: galmon relay, Android GnssLogger, GNSS-SDR, u-blox |
| `tw/sandwich_ext.py` | the chronology-protocol sandwich extension for this evidence |
| `tw/ubx.py`, `tw/timescale.py`, `tw/holdover.py`, `tw/witness.py`, `tw/verify.py` | the receiver/oscillator profile (software only) |
| `tw/ubx_config.py`, `tw/oscillator.py` | receiver configuration (u-blox 9/10 and u-blox 8), and the oscillator measurement from time marks |
| `hardware/cmod-a7-pps/` | a free-running 1 PPS edge from a Cmod A7 FPGA board's own crystal (simulated, not yet built) |
| `scripts/` | capture, bound, bracket, trust-anchor and vector tools |
| `live/` | real-sky evidence and its reports and proofs |
| `trust/` | EUSPA PKI snapshot and the authenticated Merkle-tree record |
| `docs/SOURCES.md` | every external fact, its source and digest, and how it was checked |
| `THIRD-PARTY.md` | third-party material and its terms |

chronology-protocol owns consensus, checkpoints, signatures, anchoring and the sandwich
construction; this repository redefines none of them. Its sandwich verifier checks this
repository's evidence through the extension in `tw/sandwich_ext.py`.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`. This project is not developed, endorsed or
approved by the European Union, EUSPA, or any GNSS operator.
