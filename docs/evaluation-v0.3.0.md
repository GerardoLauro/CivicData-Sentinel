# v0.3.0-beta evaluation — 11 November 2026

## Scope and reference

The baseline is v0.2.4-beta, commit
`087893758b9d3fd80866bed09e642e36bcb46bc1`. All existing monitoring tests are
retained. Work occurs on `feat/contract-proposals-v0.3.0`; no automatic merge or
production contract activation is part of this release.

`examples/contracts/` contains actual official PDF, catalog HTML, CKAN metadata
and data captures for fountains (2,313 rows) and parking (63 rows). The manifest
records source URLs, hashes and acquisition context. Data/documents are
attributed to Ayuntamiento de Madrid, CC BY 4.0. They are observations from this
capture window, not promises that the endpoints will remain available.

Five documentary rules were manually transcribed and **explicitly confirmed by
the user** in this development conversation on 11 November. This is a small
human-confirmed reference of documentary meaning; it does not certify current
applicability or approve production deployment. The machine-readable reference
and its qualification are in `examples/contracts/human-reference.json`.

| Dataset / rule | Reference | Deterministic result | Sample impact / existing contract |
| --- | --- | --- | --- |
| Fountains UBICACION | ZV / VP | Proposed with PDF page 2 citation | 9/2,313 rows fail; inspect missing/other published values. New check. |
| Fountains ESTADO | OPERATIVO / NO OPERATIVO / CERRADA TEMPORALMENTE | Abstained: wrapped enum | Published labels differ from this document; existing exact observed-label policy retained. |
| Fountains USO | PERSONAS / MASCOTAS / PERSONAS_Y_MASCOTAS | Abstained: PDF line wrapping | Manual transcription needed; no population invariant inferred from the sample. |
| Parking PK | Field key / uniqueness | Proposed with PDF page 1 citation | 63/63 pass; existing primary-key gate already enforces uniqueness. |
| Parking ACCESIBILIDAD | Codes 0–6 | Proposed with PDF page 1 citation | 63/63 pass; current manually authored check is narrower (0–2) and remains in force. |

Measured on those five statements: **3 proposals, 3 documentary matches,
precision 3/3 (100%), supported-rule coverage 3/5 (60%), 2 documentary
abstentions, 0 false proposals, 0 normative provenance gaps**. These denominators
are intentionally shown: this tiny selected test is not evidence of broad NLP
accuracy or a measured improvement over manual authoring. Catalog/metadata
retention is tested, but they yielded no additional normative rules here.
Tentative statistical suggestions are a separate opt-in mode and are not scored
as human-confirmed rules. Model quality is not measured; only mock safety and
transport behavior are tested. Processing errors abort instead of yielding an
empty successful proposal.

All three real proposals remain **pending**, even when a sample passes. The
fountains verification also preserves existing coordinate-completeness warnings
and district findings. Parking retains the existing longitude warning on PK
36269. These are observed published-data/contract findings, not independent
claims about municipal infrastructure defects. An old generic parking document
is explicitly flagged for applicability review.

Reproduction, without network or production writes:

```bash
python scripts/contract_examples.py --output reports/contract-examples --proposal-db state/example-proposals.sqlite
python -m pytest tests/test_proposals.py
```

The script checks every retained source-file digest first. Proposal IDs and
processing timestamps are intentionally new; rule identities, sample evidence
and benchmark counts are reproducible. Synthetic tests cover incomplete,
ambiguous, contradictory, obsolete and hostile text; wrapped enums; PDF/HTML
extraction; invalid/corrupted citations; invalid/empty/duplicate-key samples;
unknown freshness; edit invalidation; stale approvals; create-only activation;
monitor-DB rejection; mock-model consent, privacy, malformed/oversized responses;
CLI end-to-end and the Streamlit review workspace. No synthetic defect is
presented as an observed municipal defect.

## Independent accumulated-air experiment

Official [catalog](https://datos.madrid.es/dataset/300755-0-calidad-aire-tiempo-real-acumula)
declares an expanding window up to the last 30 days and a 20-minute publication
cadence. It also states that these observations await review/validation.

At approximately **10:26–10:30 UTC on 11 November**, independent requests returned
HTTP 200: accumulated JSON in 6.328 s, CSV in 6.453 s. JSON raw SHA-256:
`1274177bbc3dc2ee0ae5f54122771c6657188315047b9ec2c6604449e8dc88ee`;
CSV SHA-256:
`4a8226043d6077e41acd669cdf727796ad8d14884524e7e942c7325e6a70fce7`.

- JSON and CSV match exactly after parsing: **3,906 wide rows, 56 fields**;
  the returned total matches, without duplicate station/magnitude/date keys.
- 23 stations, 11 magnitude codes and a consistent published matrix of 126
  station/magnitude pairs per day. Not every station measures every magnitude.
- **31 calendar dates**, 12 October–11 November inclusive, were actually returned;
  this is an observed provider result, rather than a silently imposed 30-date cap.
- 93,744 hourly slots contain 90,585 `V` and 3,159 `N` flags. `N` slots are not
  treated as valid measurements/zeros. `V` is a provider flag, not certification.
- Latest `V` timestamp is **10:00 UTC**, about 26 minutes before the first capture.
  Timestamp age is derived from the existing local-hour-ending interpretation.
- The current-day endpoint also responded: all **126 current rows match the
  accumulated overlap exactly**, and normalization gives identical **3,024**
  current-day records at this paired observation.
- Full-window normalization correctly rejects **25 October 02:00 local (H02)**
  as ambiguous. The wide resource provides no fold identifier for that local
  hour. Selecting a fold arbitrarily would change the meaning of observations.

Decision: the accumulated feed is a useful independent investigative companion,
but **not deployed as a drop-in replacement** for `madrid_air`. One paired capture
does not prove permanent equivalence, revision behavior or endpoint availability.
No source config, baseline, old failure or operational evidence was rewritten.
The original air endpoint's successful response today does not undo the outage
documented in v0.2.4. External availability remains a residual operational risk.

```bash
# Explicit live experiment, isolated from production history:
python scripts/probe_accumulated_air.py --live --directory reports/air-source-probe
# Re-analyze the retained raw files without a request:
python scripts/probe_accumulated_air.py --directory reports/air-source-probe
```

## Monitoring compatibility observation

A separate live database, outside the Desktop production state, acquired all
three original contracts at 10:56–10:57 UTC: air 3,024 normalized rows (healthy),
fountains 2,313 rows and parking 63 rows (both accepted with quality findings).
Storage integrity and semantic replay passed for all three snapshots. Replay
does not establish historical HTTP availability or authenticate provider origin.
The complete raw experiment and live reports are retained in the release
evidence backup, separately from synthetic unit-test results.

The existing Desktop history was also opened read-only: 12 attempts / 5 stored
snapshots pass storage integrity and the database file digest stays unchanged.
Of 11 replayable attempts, 10 fully reproduce; local run 2 retains a pre-existing
serialized-check mismatch (its historic result omits `missing_count`, which the
current evaluator includes). Snapshot, events, statistics and schema still
match. Running the original v0.2.4 replay implementation gives the same mismatch;
the six replay/monitoring modules are unchanged. This legacy limitation is not
hidden or repaired by rewriting historical evidence.

## Practical value and remaining limits

Final local checks: **165 tests passed**, **93.27% coverage**, Ruff lint and
format checks passed, `pip check` passed, wheel/sdist built and passed Twine
validation. `pip-audit --skip-editable` found no known vulnerabilities in the
installed dependency set on 11 November (a point-in-time database check, not a
guarantee of absence). CLI and dashboard end-to-end approval/export/edit tests
use explicitly synthetic reviewer/data fixtures, not municipal rule approvals.
GitHub matrix results and release artifact digests are retained separately with
the release validation report.

Manual contracts are still the authority for source identity, operational policy,
ambiguous semantics and deployment. The new software reduces repetitive
transcription for supported constraints, makes documentary disagreement visible,
retains traceable rule provenance and lets developers see concrete sample impact
before approval. It is a usable review aid, not autonomous policy generation.

Missing features are deliberate beta boundaries: general PDF table extraction,
OCR, calibrated extraction confidence, automated conflict reconciliation,
independent large-scale human annotation, real-model evaluation, authenticated
reviewer identity and complete ODCS conversion. No paid/model service is needed
for the observed deterministic results. See the proposal architecture document
for persistence/export atomicity, privacy and resource limits.
