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
- OSNMA receiver guidelines v1.1: time synchronisation requirement `T_L` = 30 s
  (as reported by the sources above; the guideline document itself is to be pinned
  by version before any OSNMA code is written).
- H. Wang, Y. Zhang, Y. Tan, J. He, S. Zhao, N. Xi, Y. Shen, *Practical Spoofing
  Attacks against Galileo OSNMA with Time-Synchronization Manipulation*,
  arXiv:2501.09246 (2025). Replay, forgery and dual-frequency attacks passing OSNMA
  on two commercial and two SDR receivers by manipulating the local reference time
  within the synchronisation requirement.
- The OSNMA SIS ICD and its official test vectors will be recorded here, by version
  and digest, before any OSNMA verification code is written.
