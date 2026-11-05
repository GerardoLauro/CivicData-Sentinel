# Architecture and acceptance criteria

`HTTPS source -> CSV / paginated CKAN -> structural validation -> quality checks -> canonical SHA-256 -> previous successful snapshot -> semantic diff -> SQLite + JSON`

Required columns and nonblank unique primary keys are structural gates. A rejected
snapshot or failed request records a failure with no diff and cannot replace the
last accepted baseline. Missing coordinates and unknown status labels are quality
warnings; accepted records remain available for comparison.

Each run is an audit attempt, successful or failed. Each snapshot is an immutable,
gzipped canonical record map keyed by dataset ID and SHA-256. Repeated content
adds a run but reuses the existing snapshot. Record events explain field-level
changes and are sampled to 1,000 events; aggregate counts remain complete.

CKAN pages use `_id asc` ordering, exact non-estimated totals, identical column
schemas, unique non-null internal row IDs and first-page consistency recheck.
The user-facing `ID` is separately validated as the stable primary key. `_id` is
excluded from semantic fingerprints. Null fields become blank strings and configured
whitespace trimming is conservative; coordinate formats are not rewritten.

Reports distinguish local files from network inputs and record input byte hashes,
canonical hashes, columns, page counts and the known scope of consistency checks.
A baseline contains no inferred additions. A change is not inherently a defect.

The dashboard opens databases using SQLite `mode=ro`, labels local-file inputs,
and handles missing/unreadable history. Bundled real data and fictional fixtures
live in separate directories and verification databases.

| Gate | Observed state |
| --- | --- |
| Core, reordering, failure preservation, idempotence | 35 local tests pass including dashboard tests |
| Live source | 2,314 records, 5 data pages per run; two runs match official CSV |
| Streamlit | AppTest with real history; health/frontend HTTP 200 |
| Workflows | actionlint passes; synthetic local Git persistence simulation passes |
| GitHub-hosted scheduling, credentials, branch policy, artifact upload | Pending publication and first remote run |
| Multi-day real changes and false-positive calibration | Not observed |

Known weaknesses: no CKAN transaction across pages, later-page-only edits can escape
first-page recheck; warning-level mass removals are accepted; stable IDs may be
reassigned by the publisher; automatic year rollover is not implemented; SQLite
assumes one writer; git persistence can be rejected by branch protection or another
push, and binary history grows. Artifact retention reduces loss but is not an
external durable-storage design.
