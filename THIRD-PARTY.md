# Third-party material

What this repository contains or relies on that it did not create, and on what terms.

## Values quoted from the Galileo OSNMA Receiver Guidelines

`tests/test_osnma.py` quotes a number of hexadecimal values from Annex A ("Examples
of OSNMA Verifications") of the Galileo OSNMA Receiver Guidelines, Issue 1.3, January
2024, © European Union 2024, ISBN 978-92-9206-066-4, doi 10.2878/256023, published at
https://www.gsc-europa.eu. They are reproduced unaltered, under that document's Terms
of Use and Disclaimers, which require the terms to accompany any partial
reproduction. They are reproduced here in full and unmodified:

> **Terms of Use and Disclaimers**
>
> **Authorised Use and Scope of Use**
>
> The European GNSS (Galileo) Open Service Navigation Message Authentication (OSNMA)
> Receiver Guidelines Issue 1.3 (hereinafter referred to as OSNMA Receiver Guidelines)
> and the information contained herein is made available to the public by the European
> Union (hereinafter referred to as Publishing Authority) for information,
> standardisation, research and development and commercial purposes for the benefit and
> the promotion of the European Global Navigation Satellite Systems programmes (European
> GNSS Programmes) and according to terms and conditions specified thereafter. The
> disclaimers contained in this document apply to the extent permitted by applicable law.
>
> **General Disclaimer of Liability**
>
> With respect to the OSNMA Receiver Guidelines and any information contained in the
> OSNMA Receiver Guidelines, neither the EU as the Publishing Authority nor the generator
> of such information make any warranty, express or implied, including the warranty of
> fitness for a particular purpose, or assumes any legal liability or responsibility for
> the accuracy, completeness, or usefulness of any information hereby disclosed or for
> any product developed based on this information, or represents that the use of this
> information would not cause damages or would not infringe any intellectual property
> rights. No liability is hereby assumed for any direct, indirect, incidental, special or
> consequential damages, including but not limited to, damages for interruption of
> business, loss of profits, goodwill or other intangible losses, resulting from the use
> of the OSNMA Receiver Guidelines or of the information contained herein. Liability is
> excluded as well for consequences of the use and/or abuse of the OSNMA Receiver
> Guidelines or the information contained herein.
>
> **Copyright**
>
> The OSNMA Receiver Guidelines is protected by copyright. Any alteration or translation
> in any language of the OSNMA Receiver Guidelines as a whole or parts of it is
> prohibited unless the Publishing Authority provides a specific written prior
> permission. The OSNMA Receiver Guidelines may only be partly or wholly reproduced
> and/or transmitted to a third party in accordance with the herein described permitted
> use and under the following conditions:
>
> - the present "Terms of Use and Disclaimers" are accepted, reproduced and transmitted
>   entirely and unmodified together with the reproduced and/or transmitted information;
> - the copyright notice "© European Union 2024" is not removed from any page.
>
> **Miscellaneous**
>
> No failure or delay in exercising any right in relation to the OSNMA Receiver
> Guidelines or the information contained therein shall operate as a waiver thereof,
> nor shall any single or partial exercise preclude any other or further exercise of
> such rights.
>
> **Updates**
>
> The OSNMA Receiver Guidelines could be subject to modification, update and variations.
>
> The publication of updates will be subject to the same terms as stated herein unless
> otherwise evidenced. Although the Publishing Authority will deploy its efforts to give
> notice to the public for further updates of OSNMA Receiver Guidelines, it does not
> assume any obligation to advise on further developments and updates of the OSNMA
> Receiver Guidelines, nor to take into account any inputs, comments proposed by
> interested persons or entities, involved in the updating process.

The Guidelines' official test vectors (Annex B) are **not** redistributed;
`scripts/fetch_osnma_vectors.py` downloads them from the publisher and checks their
digest.

## Galileo specifications

This repository implements the Galileo OSNMA SIS ICD and the Galileo OS SIS ICD (©
European Union) and contains no copy of either. The OSNMA SIS ICD's Annex E is a
royalty-free authorisation to practise the listed rights in software that uses the
signal, on condition that the source is acknowledged and that no endorsement by the
European Union is stated or implied. The source is acknowledged in docs/SOURCES.md;
nothing in this repository is developed, used, approved or endorsed by the European
Union.

## pyubx2

`tests/test_ubx.py` pins five UBX frames, and `tests/test_ubx_config.py` one
configuration frame, serialised by pyubx2 1.3.8 (BSD-3-Clause, © semuadmin / Steve
Smith, github.com/semuconsulting/pyubx2). No pyubx2 code is included.

## Formats followed, no code included

- galmon transport and message schema (github.com/berthubert/galmon) — `tw/galmon_feed.py`
- Android `GnssNavigationMessage` packing (AOSP) and GnssLogger's log layout
  (github.com/google/gps-measurement-tools) — `tw/android_nav.py`
- GNSS-SDR's NavDataMonitor message (gnss-sdr.org) — `tw/gnsssdr_nav.py`
- u-blox receiver protocol specifications and data sheets (u-blox AG) — `tw/ubx*.py`,
  `docs/HARDWARE.md`; message layouts and pin numbers only, no text reproduced
- Digilent's Cmod A7 master constraints (github.com/Digilent/digilent-xdc) — package pin
  numbers in `hardware/cmod-a7-pps/pps_gen.xdc`

## Data in `live/`

- `galmon-*`: Galileo navigation frames relayed by the public galmon network; frames
  carry galmon's own station numbers and station clock readings, as galmon publishes
  them. All other galmon message types — including station positions — were dropped at
  capture.
- `android-*`: a position-free extract of a phone's GnssLogger log (see
  scripts/extract_android_galileo.py): navigation pages and arrival times only.
- `*.ots`: OpenTimestamps proofs; they name the public calendars that issued them.

## EUSPA PKI certificates

`trust/euspa/` holds public certificates and revocation lists of the EUSPA PKI, as
published at pki.euspa.europa.eu and gsc-europa.eu, unmodified except for line endings.
