# Changelog

## 0.1.1 — 2026-11-05

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
