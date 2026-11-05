# Changelog

## 0.2.1 — 2026-11-05

- Reject nonexistent and ambiguous local hours by default; explicit omission of unavailable gap slots or fold selection requires a contract.
- Madrid air omits only unavailable spring-gap slots and rejects ambiguous autumn slots pending authoritative fold information.
- Catch invalid gzip/DEFLATE failures in snapshot, artifact and replay diagnostics.
- Replay all semantic events, aggregate counts and normalized schema; expose verification levels and exclusions.
- Label storage integrity scope explicitly; hashes alone are not semantic attestation.
- Use ASCII dashboard icon/separators for encoding portability.
- Add eight audit regression cases; retain original evidence and history.

## 0.2.0 — 2026-11-05

- Three independent Madrid contracts: fountains, hourly air, parking inventory.
- Validated configuration schema, composite IDs and configurable hourly unpivot.
- Schema/profile tracking and explainable conditional quality/freshness rules.
- Explicit numeric equivalence, tolerances and rolling-window classification.
- Candidate quarantine, audited approval and separate live/local trusted heads.
- Complete stored events, hashed artifacts, integrity checks and offline replay.
- Incident lifecycle, deduplicated outbox, structured logs and operational CLI.
- Read-only observatory with filters, timeline, record details and full exports.
- Separate state branch, verified SQLite backups and concurrent-update rejection.
- Extended failure/property/CLI/local-runner tests, lint and dependency audit.
- Python 3.11+ required for the corrected filelock dependency.
- No GitHub publication or external notifications.


## 0.1.1 â€” 2026-11-05

Continues the supplied 0.1.0 archive (SHA-256
`ef87e52ed2ea8cbaae02c81c128bcc8f7562e31ab54f6c777ed4e23e61d2628c`).

- Verified the full live Madrid resource through CKAN pagination and official CSV.
- Corrected observed status labels: `FUERA_DE_SERVICIO`, `CERRADA_TEMPORALMENT`.
  The original configuration wrongly warned on 106 published records.
- Count missing coordinate values without rejecting otherwise usable snapshots.
- Request deterministic `_id asc` ordering and exact totals; reject schema drift,
  null/repeated internal IDs, estimated totals, nested values and incomplete pages.
- Strict CSV quoting checks; include input kind, payload SHA-256, column schema,
  row/page counts and consistency limitations in reports.
- Open dashboard databases in read-only mode; handle unreadable history and label
  local inputs and initial baselines. Update deprecated Streamlit table sizing.
- Extend tests and add opt-in live, dashboard and local workflow verification scripts.
- Add CI Python matrix and dashboard checks; preserve failed monitor artifacts,
  refresh persisted state before collection and set a job timeout.
- Bundle attributed municipal evidence and reproducible verification instructions.

No GitHub repository has been published or remote Actions run claimed.
