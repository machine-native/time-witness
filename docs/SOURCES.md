# Sources

Every external fact this repository depends on, where it came from, and how it
was checked. Nothing here is taken from a single source where a second exists.

## UBX message layouts

- **Primary:** u-blox receiver interface descriptions (per product generation).
  Not yet pinned against a specific document version: the receiver has not been
  chosen (docs/HARDWARE.md). The version matching the fitted receiver will be pinned
  when it is.
- **Independent cross-check:** pyubx2 1.3.8, BSD-3-Clause, by semuadmin (Steve Smith),
  github.com/semuconsulting/pyubx2, commit `993f37d47a3c3289c6d908a1afabcd7dcbddf95e`
  (2026-09-28). Files read: `src/pyubx2/ubxtypes_get.py`
  (sha256 `f990af6eca604d2bee7b3275bd53664f7e2a800503597c34b029fb922b1442de`),
  `src/pyubx2/ubxtypes_core.py`
  (sha256 `51fa88db0904eecd443b78a5f2d1d3b5bddee96e1c489773157e34493503a9ce`).
  Field order, types, bitfield positions and message ids for TIM-TP, TIM-TM2,
  NAV-STATUS, NAV-TIMEGPS, NAV-TIMEGAL, RXM-SFRBX and SEC-OSNMA agree with
  `tw/ubx.py`. Five reference frames serialised by pyubx2 on 2026-09-30 are pinned
  in `tests/test_ubx.py`; this repository's encoder reproduces them byte-for-byte.
  pyubx2 takes TIM-TP `towSubMS` in milliseconds scaled by 2⁻³², confirming that
  unit independently. No pyubx2 code is included in this repository.
- **Receiver configuration keys** (`tw/ubx_config.py`): every UBX-CFG-VALSET key ID
  and the VALSET layout (§5.9.27) were read from the u-blox ZED-F9P Interface
  Description UBX-18010854 R04 (sha256 below) and agree with pyubx2 1.3.8's
  `ubxtypes_configdb.py` (sha256
  `d25fb9107fc63968ad63f4fd2ef3429aa524ac59d56f9cb57665b2d0b353028b`) for all fifteen
  keys used. A VALSET frame serialised by pyubx2 is pinned in
  `tests/test_ubx_config.py` and reproduced byte-for-byte. Still to pin on hardware:
  that a timing receiver's firmware (ZED-F9T) accepts the same keys.
- **u-blox 8 / M8** (`tw/ubx_config.py`, M8 section): u-blox 8 / u-blox M8 Receiver
  Description incl. Protocol Specification UBX-13003221 R28 (sha256
  `241b6bce16f27fa754f3ef13a082ebf9a42e32ecf3ec9f3544df8a2c439702a2`): CFG-GNSS,
  CFG-MSG, CFG-CFG, CFG-RST and MON-VER layouts; Galileo E1 needs protocol 18; enabling
  Galileo must be followed by a BBR save and a hardware reset; CFG-GNSS sits in
  configuration sub-section 4 (RXM); TIM-TM2 on every M8 protocol version; RXM-SFRBX
  version 2 from protocol 18. Every M8 frame is reproduced byte-for-byte by pyubx2 1.3.8,
  and the CFG-GNSS block list is byte-identical to galmon's `ubxtool.cc` (commit
  `9bd22436`, sha256
  `5005f14b5c602be543e1bd01eccb7ff67f90103ccc722c5deb89ba2d65ebdfd7`). The specification prints no signal-identifier
  table, so the M8 value for Galileo E1-B is **still to pin** on a first M8 capture
  (`tw/ubx_inav.py` accepts 0 and 1). NEO-M8 data sheet UBX-15031086 R14 (sha256
  `5dc7a6c044873a04e2dcc08a7f54e9e7374c5c69dcce694054ac4730c81a04a5`): EXTINT pin 4,
  TIMEPULSE pin 3, time pulse 30 ns RMS / 60 ns 99 %, VIH 0.7 × VCC.
- **M8 default NMEA output** (`tw/ubx_config.py`, turned off for a capture): GGA, GLL,
  GSA, GSV, RMC and VTG are class 0xF0, ids 0x00-0x05, in the M8 specification's NMEA
  message list and in pyubx2 1.3.8; the CFG-MSG frame that turns GGA off is reproduced
  byte-for-byte by pyubx2 (`tests/test_ubx_config.py`).
- **M8 time base**: TIM-TM2 stamps on GNSS or UTC time per the time-pulse configuration;
  standard M8 firmware defaults to a UTC grid (specification, default settings,
  `gridUtcGnss` 0), so `tw/oscillator.py` accepts either, one base per capture.
- **M8 firmware 3.01** (docs/HARDWARE.md, upgrade): `UBX_M8_301_SPG.911f2b77b649eb90f4be14ce56717b49.bin`
  from content.u-blox.com; its MD5 equals the hex in its name (checked), sha256
  `c91968fbd3e593872933c22269597bf3eed75fda1d5f51eeb3fb44efe3092caf`; named, with FW ID
  `EXT CORE 3.01 (107900)` and NEO-M8N among supported variants, by the release notes
  UBX-16000319, which also state Galileo is off by default and enabled with UBX-CFG-GNSS.
- **Cmod A7 pins** (`hardware/cmod-a7-pps/pps_gen.xdc`): Digilent `Cmod-A7-Master.xdc`,
  digilent-xdc commit `00a3404901f35aa9567b01ecb3f2c233b6efe9f4` (sha256
  `56568df3868ef359e938ef8defab33e1814fe4153435e99e13da9260d9db4eaf`): 12 MHz clock L17,
  pio1 M3, LED 1 A17 -- the clock and LED pins agree with chronology-protocol's
  `fpga/constraints/cmod_a7.xdc`, which has run on this board.
- **Checksum:** the 8-bit Fletcher algorithm, checked against the MON-VER poll
  frame `B5 62 0A 04 00 00 0E 34` quoted widely in u-blox material.
- **Still to pin against receiver bytes:** the unit of TIM-TM2 `towSubMsR` (ns) and `accEst`
  (ns), the SEC-OSNMA bitfields beyond the first three bytes, and how a receiver
  selects the GNSS for the TIM-TM2 time base. pyubx2 records field types, not units.

## Time scales

- GPS time origin 1980-01-06T00:00:00Z; Galileo System Time week 0 = GPS week 1024
  (the 1999-08-22 rollover). Both are checked in `tests/test_timescale_holdover.py`
  against Python's `datetime`, not against constants in the module under test.

## Galileo OSNMA

- European GNSS Service Centre, *Galileo Open Service Navigation Message
  Authentication*: https://www.gsc-europa.eu/galileo/services/galileo-open-service-navigation-message-authentication-osnma
- OSNMA receiver guidelines: time synchronisation requirement 30 s (first seen as
  reported by the sources above; now pinned below in Issue 1.3).
- H. Wang, Y. Zhang, Y. Tan, J. He, S. Zhao, N. Xi, Y. Shen, *Practical Spoofing
  Attacks against Galileo OSNMA with Time-Synchronization Manipulation*,
  arXiv:2501.09246 (2025). Replay, forgery and dual-frequency attacks passing OSNMA
  on two commercial and two SDR receivers by manipulating the local reference time
  within the synchronisation requirement.

## Documents `tw/osnma.py` implements (all fetched 2026-09-30 from gsc-europa.eu)

Each was the "in force" version on the GSC reference-document pages that day.

| document | sha256 |
|---|---|
| Galileo OSNMA SIS ICD, Issue 1.1, October 2023 (`Galileo-OSNMA-SIS-ICD_in_force.pdf`, byte-identical to `Galileo_OSNMA_SIS_ICD_v1.1.pdf`) | `0f8e385af744924cd64cea476684d399f63af0d65384d368b0765ea94d6176c3` |
| Galileo OSNMA Receiver Guidelines, Issue 1.3, January 2024 (`Galileo-OSNMA-RX-Guidelines_in_force.pdf`) | `4b005862f5d1fbb53e9f51ae3f182cee1c7b890ea8236578669b56abc7d3b651` |
| Galileo OS SIS ICD, Issue 2.2, November 2025 (`Galileo_OS_SIS_ICD_in_force.pdf`) | `1ca51b26c970140d2a5fd932fdf6086e5dcf945cbe216ccb081c300136504671` |
| OSNMA test vectors, Receiver Guidelines 1.3 Annex B (`Test_vectors.zip`) | `ef9b9afc6ef9e1c57393415cf2a1dc80c4035e7c06123907ea0bb97dd3ccf370` |

How each part was checked:

- **Field layouts** (NMA header, DSM header, DSM-KROOT, DSM-PKR, MACK, Tag-Info) and
  the equations for the signature message, the chain step, MACSEQ and tags were read
  from the rendered pages of the OSNMA SIS ICD. The text layer loses both figures
  and symbols, so nothing was taken from extracted text alone.
- **I/NAV page and word layouts** (word types 1-6, 10) and the CRC were read from
  OS SIS ICD Issue 2.2 and are unchanged from Issue 2.1. The CRC generator is given
  factored, as (1 + X)P(X); expanded in `tests/test_osnma.py` it equals the CRC-24Q
  polynomial `0x1864CFB`. Its coverage (even part bits 0-113, odd part bits 0-81)
  was confirmed on every page of the official vectors tested.
- **Word type 5 TOW** is the start time of the page carrying it: established on the
  official vectors, not assumed.
- **Worked examples**: every value in Receiver Guidelines Annex A (DSM-PKR and
  Merkle path, DSM-KROOT, ECDSA signature, PDK, PDP, TESLA chain steps, MACK, MACSEQ,
  Tag0, ADKD 4) reproduces exactly; the values are quoted in `tests/test_osnma.py`.
- **Official vectors**: all 18 Annex B scenarios verify with zero key failures and
  zero tag, MACSEQ or MACLT mismatches; P-256 and P-521 signatures both verify.
  Expected counts per scenario are pinned in `tests/test_osnma.py`.

Two things found in the official material, recorded so nobody rediscovers them:

- Receiver Guidelines 1.3, Annex A.5.1, prints key index 2's time of week as
  `34630`. The sub-frame sequence and A.5.2 make it `345630`, which is what verifies.
- The Annex B vectors include a satellite transmitting only dummy words (type 63)
  whose OSNMA field is nevertheless non-zero. The OSNMA SIS ICD section 2 requires
  data in dummy pages to be discarded; `tw/osnma.py` does, and did not before the
  vectors showed it.

## Trust anchor and receiver mapping (fetched 2026-09-30)

| item | source | sha256 |
|---|---|---|
| Galileo OSNMA IDD ICD, Issue 1.1, January 2024 | gsc-europa.eu | `fdac67715901f7b8ace211658e61251478106a1a3261b2bd62032dfc46b93679` |
| EUSPA Root CA `rca_001_01.crt` (pinned by DER fingerprint `63AE2D3E…E933D4`) | https://pki.euspa.europa.eu | stored PEM `883614859b421a59988d0ec72a464164ea32a8b587df5b59a0949b5694d5c6e1` |
| EUSPA Galileo SCA `sca_001_01.crt` | http://pki.euspa.europa.eu | `f6e91a4639672f14975f84bf27b027e31b48fe0f60ec7010badc4a5a7bda9376` |
| EUSPA OSNMA ICA `ica_001_01.crt` | gsc-europa.eu gsc-products/pki path | `ce618fa2df142021cea644d5d46ccb437807ff29b3ebc9ed97dd2ee5b43838b1` |
| CRLs of the three | same | in `trust/euspa/`; re-fetched by `scripts/refresh_euspa_pki.py` |
| galmon `ubx.cc` (SFRBX -> I/NAV page), commit `9bd224369b45e440424980b769fe3feb2d654f33` | github.com/berthubert/galmon | `61a690298c49faff685de13ee8303fd22502009206d574c57d11c5c4074e4553` |
| u-blox ZED-F9P Interface Description UBX-18010854 R04 (UBX 27.00), "Signal Identifiers": Galileo E1 B = gnssId 2, sigId 1 | copy hosted by SparkFun | `8d088b6109569dca5ef23c883f21d8f5a48507095bb4699ad49b442abf0f4af9` |

**The operational trust anchor**, authenticated 2026-10-01 with every check passing
(`trust/merkle-tree/*.authenticated.json`): GSC `OSNMA_MerkleTree_20251210100000_newPKID_2`,
applicable from 2025-12-10T10:00:00Z, xml sha256
`ed6092f600058ca382ecac4fa92047bc96500235e3318d617ebf40c4e5b0638f`, Merkle root
`832E15EDE55655EAC6E399A539477B7C034CCE24C3C93FFC904ACD9BF842F04E`, one public key
(PKID 2, ECDSA P-256, leaf 1). The tree file is from the GSC's registered-access portal
and is not committed; its record is, and `tests/test_gsc_pki.py` re-runs every check
wherever the file is present. The root's channel is the GSC website plus the EUSPA
PKI. **Second, independent channel, confirmed 2026-10-01:** in the 12:00 GST window
the satellites broadcast a DSM-PKR for PKID 2 (complete at 12:03:30 GST,
`live/galmon-2026-10-01-pkr`) whose Merkle path reaches this same root, PDP included.
Website and constellation agree; the real-sky tests now use the broadcast key and the
committed root only, nothing from registered access.

**The galmon feed** (`tw/galmon_feed.py`): stream served openly at 86.82.68.237, TCP
10000, as documented by galileo-osnma for this use. Transport format from galmon's
README "Internals" (`bert` magic, 2-byte big-endian length, protobuf), confirmed on the
live stream; message schema `navmon.proto` at galmon commit 9bd22436 (sha256
`6d74b382ba4704b3bac4aefa0e8617528cd7a5d357873176a9333fddbe305e1f`); field semantics
from galmon's `ubx.cc` and `ubxtool.cc` at the same commit (E1-B `gnssTOW` is the page
start, matching the convention established on the official vectors). On a 20-second
live sample every one of 241 E1-B pages rebuilt from those fields passed CRC-24Q, and
both word-5 times present matched galmon's page times. Copies of all four galmon files
are in `reference/cross-check/`.

**Android and GNSS-SDR formats.** Android `GnssNavigationMessage.getData()` for
Galileo I/NAV: even and odd page parts, 2 x 114 bits, sync and tail excluded, MSB
first in 29 bytes (AOSP `location/java/android/location/GnssNavigationMessage.java`,
sha256 `887d4681b944022886f6c0128d66da3acb6d906d27538d26ddba38cdecea7519`). GnssLogger's
`Nav` line layout: google/gps-measurement-tools `FileLogger.java` at commit
`93c638701abc5fce573fe0acf930784f4e555a96` (sha256
`b9131c3a96b8c4862abf48e94bb5d11d4b3866ea79f38991f6d85dfab9cc45d0`). GNSS-SDR's
NavDataMonitor `navMsg`: `docs/protobuf/nav_message.proto` at gnss-sdr commit
`15c3c812c6274c83df0c4d074d963d3d93e4f6a4` (Galileo I/NAV: one 120-bit half page per
message). Copies in `reference/cross-check/`. Neither reader has yet seen real
output; both are tested on official-vector pages in those formats.

The operational chain Root -> SCA -> ICA verifies with all three CRLs
(`tests/test_gsc_pki.py`). The test-phase Merkle trees in the official vectors are
signed validly, but their bundled ICA is self-issued and does not chain to the
test-phase root; the verifier refuses them for that reason. The end-to-end test
therefore signs the official tree file with a PKI it makes and labels itself.

Terms: the OSNMA SIS ICD's Annex E is a royalty-free covenant not to assert the
listed rights against software products that use the signal, provided the source is
acknowledged and no endorsement by the EU is stated or implied. None is. The
Receiver Guidelines and their test vectors may not be altered, so they are not
redistributed here: `scripts/fetch_osnma_vectors.py` downloads the vectors from the
GSC and refuses any bytes whose digest differs from the one above.
