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
