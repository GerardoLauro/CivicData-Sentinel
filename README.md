# CivicData Sentinel

**Explainable quality checks and semantic change detection for public datasets.**

Version **0.1.1**, continued from the original 0.1.0 archive. CivicData Sentinel is
an independent project with no CivicWater dependencies.

Download a public resource, validate its structure, compare records by stable ID,
and keep auditable SQLite snapshots and JSON reports. A failed request or invalid
primary key never becomes a mass-deletion event.

## Verified on real Madrid data

On **5 November 2026**, two complete CKAN acquisitions and an independent official
CSV download agreed on **2,314 records and 24 columns**. Each CKAN run fetched five
data pages (500, 500, 500, 500, 314 rows) and rechecked page one. The second
acquisition produced zero added, removed or modified records. This demonstrates
immediate repeatability, not stability over multiple days.

| Observed field/result | Value |
| --- | --- |
| Resource ID | `300051-26-fuentes` (2026) |
| `ESTADO=OPERATIVO` | 2,208 |
| `ESTADO=FUERA_DE_SERVICIO` | 103 |
| `ESTADO=CERRADA_TEMPORALMENT` | 3 |
| Missing latitude / longitude | 268 / 268 |
| Duplicate or blank primary keys | 0 |
| Official CSV size | 649,120 bytes |
| CSV equals canonical CKAN content | Yes |

The status labels are copied exactly from the publisher, including the truncated
`CERRADA_TEMPORALMENT`. They are observed values, not a claim that the vocabulary
can never change. Missing coordinates are completeness findings, not proof that a
fountain is faulty. The original configuration falsely warned about 106 status
values; 0.1.1 corrects that configuration.

See [verification report](docs/verification.md),
[live summary](evidence/2026-11-05/summary.json),
[second live report](evidence/2026-11-05/run-2.json) and
[data attribution](evidence/NOTICE.md). Published evidence includes actual CSV/API
records and derived snapshots under the municipal **CC BY 4.0** license.

## Install and run

Requires Python 3.10+. Local verification used Python 3.12.2 on Windows.

```bash
python -m venv .venv
# Windows PowerShell:
.venv/Scripts/Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e '.[test,dashboard]'
python -m pytest

# Live acquisition; first run establishes a baseline:
sentinel run --config configs/madrid_fountains.yaml
sentinel history --dataset madrid_fountains
```

Normal state lives in `state/sentinel.sqlite`; the latest report is
`reports/latest.json`. A failed acquisition exits 1 and preserves the previous
successful snapshot. Warning-level quality findings are accepted and exit 0.
Repeated content creates a new audit run but reuses the same immutable snapshot.

## Reproduce the live verification

```bash
python scripts/verify_live.py --output evidence/my-live-check
```

Use a **new output directory** each time. This downloads the current URL from
`resource_show`, checks the CSV against its published MD5 when available, runs
two paginated network acquisitions, compares every normalized record and column,
and checks that the metadata resource did not change during the experiment.
Actual results, reports, a separate SQLite database and SHA-256 manifest are saved.
Network failures and source drift fail this check, rather than being skipped.

A future source update can change counts or cause a mismatch during collection;
inspect the saved reports and rerun in a new directory. No API key is needed.
The 2026 resource is explicit; review resource selection when the year changes.

## Dashboard

```bash
streamlit run dashboard/app.py
```

Select `evidence/2026-11-05/history.sqlite` in the database field to inspect the
bundled **real** checks. The viewer opens SQLite in read-only mode. Local-file
inputs carry a visible warning because they may contain synthetic fixtures.

```bash
python scripts/verify_dashboard.py --db evidence/2026-11-05/history.sqlite --output evidence/my-dashboard.json
```

This checks rendered app elements with Streamlit AppTest and temporarily starts a
local HTTP server. It does not claim a visual browser review.

## Offline example — synthetic data only

Keep demonstration state separate from live history:

```bash
sentinel run --input tests/fixtures/fountains_base.csv --db demo/state.sqlite --output demo/base.json
sentinel run --input tests/fixtures/fountains_changed.csv --db demo/state.sqlite --output demo/changed.json
```

The second fictional input gives **1 added, 1 removed and 1 modified record**.
These events are test scenarios, never observed municipal changes. Do not reuse
this demo database for live monitoring.

## GitHub Actions

- `ci.yml`: offline tests, including Streamlit AppTest, on Python 3.10 and 3.12.
- `monitor.yml`: manual or daily **07:23 UTC** acquisition. On 5 November this is
  08:23 in Rome; schedules may be delayed by GitHub.
- The monitor retains artifacts even on failure, commits SQLite/report state to
  the selected branch and exits unsuccessfully when acquisition failed.
- Repository write permission and branch policies must allow the bot commit.
  Concurrent manual source pushes can reject persistence; the workflow does not
  force-push. Download the retained artifact and resolve the conflict.
- SQLite in git is an MVP storage choice; history grows with binary commits.

Both workflows passed **actionlint 1.7.12**. The monitor shell blocks were also
executed against a local bare Git repository with fresh clones: success, changed
synthetic input and rejected duplicate-ID input all preserved the expected history.
This does **not** verify GitHub scheduling, token permissions or artifact upload.
A GitHub-hosted run remains pending publication by the owner.

To reproduce the local workflow simulation (requires Git and Bash-compatible shell):

```bash
python scripts/verify_workflow_local.py --output ../workflow-verification
# On Windows, add: --shell 'C:/path/to/Git/usr/bin/sh.exe'
```

## Scope and limitations

- HTTPS CSV downloads, CKAN `resource_show` discovery and DataStore pagination.
  No arbitrary JSON/XML import, spatial conversion or municipality-specific code.
- Configurable required columns, unique IDs, allowed values and numeric ranges.
  `allow_blank: true` accepts absent numeric values; `report_blank: true` counts them.
- Fingerprints preserve strings and leading zeros, ignore row order and optionally
  trim surrounding whitespace. Warning-level findings still update the baseline.
- DataStore `_id` is an internal pagination key, excluded from semantic records.
  Sorting and first-page recheck help detect concurrent changes but do not provide
  transactional isolation; edits confined to later pages can escape that check.
- Empty resources are rejected to avoid accidental deletion alarms. Large valid
  removals are warnings, not automatic baseline rejection. Configure policies for
  your own dataset before relying on unattended alerts.
- DataStore replies do not provide source modification timestamps. The separately
  inspected metadata timestamp had no timezone; none is guessed. No change in
  content does not imply staleness.
- Reports include at most 1,000 sampled change events with complete summary counts.
  Single-writer SQLite operation is assumed. The monitor is an experimental MVP.

## Layout

```text
src/civicdata_sentinel/  ingestion, validation, diff engine, storage and CLI
configs/                dataset-specific rules
tests/fixtures/         fictional CSVs only
dashboard/              optional read-only Streamlit viewer
scripts/                opt-in verification tools
evidence/               attributed real acquisition and local check results
docs/                   architecture, verification and known limitations
.github/workflows/      offline CI and scheduled monitor
```

## License and references

Code: [MIT](LICENSE). Municipal data: **Ayuntamiento de Madrid — Fuentes de agua
para beber**, [official catalog](https://datos.madrid.es/dataset/300051-0-fuentes),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See
[evidence attribution and transformations](evidence/NOTICE.md).

The original design cited [Simon Willison's git-history](https://github.com/simonw/git-history)
for the idea of data history. No source code from that repository was copied.
Implementation checks used official [CKAN DataStore documentation](https://docs.ckan.org/en/latest/maintaining/datastore.html),
[Streamlit AppTest documentation](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
and [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
