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
- The host records the raw stream (`scripts/capture_ubx.py`) and signs
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

## Bring-up order

1. Receiver alone, mode `PPS`: capture, confirm every layout in docs/SOURCES.md
   "still to pin" against real frames, commit the capture.
2. Oscillator on EXTINT, mode `OSC`: confirm TIM-TM2 units and edge counting
   against the host clock over an hour.
3. Declare the device profile from the parts actually fitted, stating which
   values are datasheet figures and which were measured.
4. First chain with a verdict, then an observation inside a chronology-protocol sandwich.
