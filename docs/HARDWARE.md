# Hardware — reference architecture

**Status: nothing purchased, nothing measured.** This is the shape of the
appliance and the questions each part must answer before it is bought. No part
below is claimed to work until it has produced bytes on the bench.

## Architecture

```
  GNSS antenna ──► GNSS timing receiver ──┬── UBX over serial ──► host
                   (TIM-TP, TIM-TM2,       │
                    NAV-TIME*, SFRBX)      └── EXTINT ◄── 1 PPS ◄── oscillator
                                                                     (Rb, free-running)
```

- The receiver time-marks the oscillator's 1 PPS on its external-interrupt input
  (UBX-TIM-TM2). That single message gives the GNSS time of the oscillator's edge,
  which is all mode `OSC` needs. No time-interval counter is required for v1.
- The oscillator is **not** disciplined by GNSS inside a chain. A GPSDO that
  steers itself to GNSS cannot be the independent source this profile needs; if a
  GPSDO is used, its steering must be disabled (true holdover) for the chain.
- The host records the receiver's evidence frames byte-exact (`scripts/capture_ubx.py`;
  NMEA and any position output are dropped as they arrive) and signs
  observations with chronology-protocol's PQ-5 keys.

## Parts, and the question each must answer first

| role | candidates | must be confirmed before purchase |
|---|---|---|
| timing receiver | u-blox timing-grade modules (e.g. the M8T or F9T generation) | exposes **RXM-SFRBX with complete Galileo I/NAV pages**, including the OSNMA field; supports TIM-TM2 on an EXTINT pin; which firmware reports SEC-OSNMA |
| oscillator | surplus rubidium frequency standard; chip-scale atomic clock | has a 1 PPS output, or a 10 MHz output that can be divided (a small FPGA or divider IC can divide 10 MHz to 1 PPS); datasheet `|y|` and aging figures to declare |
| antenna | active multi-band GNSS antenna with clear sky view | band match with the receiver; cable length and delay for the calibration term |
| time-interval counter | optional (e.g. a TAPR TICC) | only needed to correct `qErr` or to reach below TIM-TM2's resolution; not in v1 |

The first row decides the rest: if no affordable receiver exposes raw
Galileo pages, the OSNMA evidence of SPEC §10 cannot be produced by it, and the
appliance would be a better-instrumented clock rather than a new witness class.

The verifier needs the **raw pages**, not the receiver's own OSNMA verdict. A
receiver that verifies OSNMA internally but will not output the pages is no use to
it; a receiver that outputs the pages but does no OSNMA itself is enough.

EUSPA's list of receivers implementing OSNMA (gsc-europa.eu, "Receivers
implementing Galileo OSNMA", read 2026-09-30) includes, among others, the u-blox
ZED-F9P, NEO-M9L and ZED-X20 series; the Septentrio mosaic G5 T (timing) and
mosaic-X5; Furuno GF-10x and GT-series timing receivers; and the Quectel LC99T
(timing). EUSPA states that the list is manufacturer-supplied and unverified. Being
on it says nothing about raw-page output, which must be confirmed separately for
any candidate.

What is known without a receiver (docs/SOURCES.md):

- **u-blox.** RXM-SFRBX for Galileo E1-B (gnssId 2, sigId 1) carries the full page,
  OSNMA field included: galmon, a public monitoring network built largely on u-blox
  receivers, extracts the OSNMA field and checks the page CRC from exactly these
  frames. `tw/ubx_inav.py` implements the same mapping. Firmware matters: u-blox
  states the ZED-F9P supports OSNMA from its 1.5x firmware; raw SFRBX output predates
  that and does not depend on it.
- **Septentrio.** The mosaic-G5 T documents an SBF block, `GALRawINAV`, carrying the
  raw I/NAV bits, SVID and receiver GST. No adapter for it exists here yet.

## The low-cost route

A first physical-edge measurement does not need a timing receiver or an atomic
clock. It needs a receiver that time-marks an edge on EXTINT and outputs Galileo
pages, and an edge from a clock the receiver does not steer.

| part | what | source of the facts |
|---|---|---|
| receiver | a **genuine** u-blox M8 module (e.g. a NEO-M8N board), firmware 3.01 | M8 protocol specification UBX-13003221 R28: TIM-TM2 on every M8 protocol version; RXM-SFRBX with Galileo from protocol 18 (firmware 3.01). NEO-M8 data sheet UBX-15031086 R14: EXTINT is pin 4, TIMEPULSE pin 3, time-pulse accuracy 30 ns RMS / 60 ns 99 %, logic high from 0.7 × VCC |
| edge | a Cmod A7 running `hardware/cmod-a7-pps/` (its own 12 MHz crystal, divided to 1 PPS on DIP pin 1) | Digilent Cmod-A7-Master.xdc; design simulated in `tb_pps_gen.v` |
| serial | the board's USB port, or a CP2102 USB-serial adapter on UART1 | — |

**The purchase check comes first.** Many inexpensive "NEO-M8N" boards carry
counterfeit parts, or old ones, at firmware 2.01 (protocol 15), which has no Galileo.
Old genuine parts can be upgraded; counterfeits cannot. On the day a board arrives,
before anything else:

    python scripts/setup_receiver.py --port COMn --baud 9600 --dry-run

It polls UBX-MON-VER and refuses anything below protocol 18 by name.

**If it reports firmware 2.01 (protocol 15).** A genuine NEO-M8N stores its firmware
in flash and takes u-blox's standard-precision firmware 3.01; a counterfeit or ROM part
does not, so the upgrade is also the genuineness test. The image is
`UBX_M8_301_SPG.911f2b77b649eb90f4be14ce56717b49.bin` from u-blox (its MD5 is the hex in
its name; release notes UBX-16000319 name it, FW ID `EXT CORE 3.01 (107900)`, for
NEO-M8N). Install u-center (u-blox, Windows), connect, then *Tools → Firmware Update*:
the image above, the `flash.xml` that ships with u-center as the flash information
file, "enter safeboot before update" ticked. Keep the board powered until it finishes:
a genuine module interrupted mid-write can only be recovered through its SAFEBOOT pin.
Then run the `--dry-run` check again: `PROTVER=18.00` and `GAL` mean go ahead. If the
update fails or the check still says 15, the part is not a genuine NEO-M8N.

**Wiring.** Cmod A7 DIP pin 1 to the module's EXTINT (pin 4), grounds joined, both
sides at 3.3 V logic. Inexpensive boards often bring out only power, TX, RX and the
time-pulse LED; EXTINT may need a fine wire soldered to pin 4 of the module itself.

**Then.**

    python scripts/setup_receiver.py --port COMn --baud 9600 --out live/<label>.setup.json
    python scripts/capture_ubx.py --port COMn --baud 9600 --seconds 1800 \
        --out live/<label> --configure UART1 --receiver m8
    python scripts/oscillator_report.py live/<label>.ubx --out live/<label>.oscillator.json
    python scripts/galileo_bound.py live/<label>.ubx      # the same capture's Galileo pages

The first command enables Galileo (saved to battery-backed RAM only, then a reset;
see `tw/ubx_config.py`). The capture keeps only an allowlist of UBX frames
(`tw/ubx_filter.py`): a receiver's default NMEA output states where its antenna is, and
it is dropped as it arrives, so a capture can be published without saying where it was
taken. The setup record likewise keeps only the receiver's replies. The report measures the crystal against the receiver: its
frequency offset, the jitter of its edge, and its Allan deviation. Expect parts per
million and tens of nanoseconds: an inexpensive crystal and a 30 ns receiver. The
measurement is real either way, and an atomic reference later uses the same wiring,
the same capture and the same report.

What this route cannot give: a timing receiver's 5 ns time pulse, a quantisation-error
correction, or an oscillator good enough to bound time through a GNSS outage longer
than a few seconds. Those are what the full kit is for.

## Bring-up order

1. Receiver alone, mode `PPS`: configure and capture in one step
   (`python scripts/capture_ubx.py --port COMn --seconds 1200 --out live/<label>
   --configure USB`; RAM layer only, the ACK is checked in the capture), then
   confirm every layout in docs/SOURCES.md "still to pin" against real frames and
   commit the capture.
2. Oscillator on EXTINT, mode `OSC`: confirm TIM-TM2 units and edge counting
   against the host clock over an hour.
3. Declare the device profile from the parts actually fitted, stating which
   values are datasheet figures and which were measured.
4. First chain with a verdict, then an observation inside a chronology-protocol sandwich.
