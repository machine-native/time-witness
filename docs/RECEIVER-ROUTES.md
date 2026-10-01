# Getting Galileo pages: four routes

The Galileo lower bound (SPEC §10) needs raw E1-B I/NAV pages and nothing else. Any
of these routes provides them; every one ends in the same command and the same
checks, and none of them is trusted for anything but delivering bits — pages are
CRC-checked, and the bound rests on keys no source can produce early.

| route | your own antenna | cost | status |
|---|---|---|---|
| galmon public relay | no | none | **working** — first real-sky bound 2026-10-01 |
| Android phone (GnssLogger) | yes | none | reader built and tested on synthetic logs; depends on the phone |
| RTL-SDR + GNSS-SDR | yes | a USB SDR dongle and an active L1 antenna | reader built and tested on synthetic data; not yet run |
| u-blox receiver (RXM-SFRBX) | yes | a timing-capable receiver board | reader built; needed only for ns timing and the oscillator design |

## Before any route: the trust anchor

    python scripts/refresh_euspa_pki.py
    python scripts/authenticate_merkle_tree.py <GSC OSNMA_MerkleTree .xml>

## 1. galmon relay

    python scripts/capture_galmon.py --minutes 16 --out live/galmon-<label>
    python scripts/galileo_bound.py live/galmon-<label>

Capture at least ~16 minutes: a complete DSM-KROOT must be in it.

## 2. Android phone

Only some phones report Galileo navigation messages (EUSPA's smartphone OSNMA
guidelines name certain chipsets); a 20-minute test is the only way to know.

1. Install **GnssLogger** (Google) from the Play Store.
2. Optional but helpful: Developer options -> **Force full GNSS measurements**.
3. In GnssLogger settings enable logging of **navigation messages** (and raw
   measurements, which supply the arrival times).
4. Outdoors or at an open window with sky view, start logging; leave it 20 minutes.
5. Stop, and copy the `gnss_log_*.txt` file to this computer.
6. `python scripts/galileo_bound.py path/to/gnss_log_<...>.txt`

If the report says `NO_USABLE_GALILEO_PAGES` with `galileo_inav: 0`, the phone does
not expose Galileo pages and this route is closed for it. If pages appear but many
are `ambiguous_placement`, the phone's message timing is looser than the reader
assumes — keep the log; it is what tunes the reader for that phone.

## 3. RTL-SDR + GNSS-SDR

Hardware: an RTL-SDR dongle with a TCXO and software bias-tee (RTL-SDR Blog V3 or V4)
and an active GPS/Galileo L1 antenna with an SMA connector. The bias-tee powers the
antenna; no other parts.

GNSS-SDR runs on Linux. On Windows, use WSL2 (Ubuntu) and pass the dongle through
with usbipd-win:

    winget install usbipd                    # Windows, once
    usbipd list                              # find the RTL2832U's BUSID
    usbipd bind --busid <BUSID>              # admin, once
    usbipd attach --wsl --busid <BUSID>      # each session

Then in Ubuntu: install GNSS-SDR (`sudo apt install gnss-sdr`, or build from source
for the newest OSNMA support), and follow GNSS-SDR's RTL-SDR tutorial for a Galileo E1
configuration, enabling the bias-tee (`SignalSource.osmosdr_args=rtl,bias=1`) and the
navigation data monitor:

    NavDataMonitor.enable_monitor=true
    NavDataMonitor.client_addresses=127.0.0.1
    NavDataMonitor.port=1237

With GNSS-SDR running and tracking Galileo, in the same machine:

    python scripts/capture_gnsssdr.py --minutes 16 --out live/sdr-<label>
    python scripts/galileo_bound.py live/sdr-<label>

GNSS-SDR's own OSNMA processing can stay on; this repository does not use its
verdict, only the decoded half-pages, and checks them itself.

## 4. u-blox receiver

See docs/HARDWARE.md. Raw RXM-SFRBX frames are read by tw/ubx_inav.py; this is the
route the full time-witness design (PPS, oscillator, TIM-TM2) is built on.
