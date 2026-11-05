# CivicData Sentinel

**Evidence-first monitoring for public data. Version 0.2.0.**

Track meaningful record changes, validate dataset contracts and keep replayable
evidence. Suspicious publications can be quarantined without replacing trusted
history. Local experiments are isolated from live monitoring.

## What is different

- Complete record events, not just samples, linked to runs and content-addressed snapshots.
- Explicit numeric equivalence, tolerances and ignored metadata reduce avoidable noise.
- Rolling-window expiry distinguishes expected expiration from unexpected removals.
- Versioned YAML contracts cover composite keys, schema drift, completeness, uniqueness,
  domains, regex, numeric limits, numeric revisions, median shifts and timestamp freshness.
- Quarantine and audited approval preserve the last trusted baseline.
- Original parser inputs and JSON responses are retained for offline replay.
- Incident lifecycle and cursor-based outbox prevent repeated findings becoming repeated alerts.
- Read-only Streamlit observatory: overview, history, changes, incident filters and complete exports.
- Hourly GitHub workflow restores and persists verified state on a separate branch.

## Verified real datasets

| Dataset | Published rows | Normalized records | Independent comparison |
| --- | ---: | ---: | --- |
| Madrid drinking fountains | 2,314 | 2,314 | CKAN vs official CSV |
| Madrid hourly air measurements | 126 | 3,024 | JSON vs CSV |
| Madrid municipal parking inventory | 63 | 63 | CSV vs CKAN |

Six live acquisitions on 5 November 2026 matched independent formats record for
record and replayed offline. Their immediate second acquisitions showed no changes;
this is not a multi-day stability result. Air validity flags exclude unavailable
slots from numeric/freshness checks. Parking is an inventory, not live occupancy.

Observed findings: 268 missing latitudes and longitudes in the fountains data;
parking record `36269` publishes longitude `--3.65138632197171`. Values are preserved,
not silently corrected. See [live evidence](evidence/v0.2.0/live/summary.json).

## Run locally

Requires **Python 3.11+**. From this repository root:

```bash
python -m venv .venv
# Windows: .venv/Scripts/Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e '.[test,dashboard,dev]'
sentinel catalog
sentinel run-all
streamlit run dashboard/app.py
```

On Windows, double-click `Start-Dashboard.cmd` after installing dependencies.
The Desktop directory is the canonical development repository. No GitHub remote
has been configured or published. To inspect bundled clean live checks, select
`evidence/v0.2.0/live/history.sqlite` in the dashboard history-file field.

## Operations

```bash
sentinel run --config configs/madrid_air.yaml
sentinel history --dataset madrid_air --limit 30 --offset 0
sentinel show --run 1
sentinel export --run 1 --format json --output reports/full.json
sentinel export --run 1 --format csv --output reports/events.csv
sentinel replay --run 1
sentinel verify
sentinel backup --output backups/history.sqlite
sentinel incidents --state open
sentinel alerts --after 0
sentinel approve --run 7 --reason 'Reviewed source publication and confirmed intentional change'
```

Only valid quarantined candidates can be approved; newer trusted heads cannot be
overwritten. Approval is an additional audit decision, not a rewrite of the original
run. Exit codes: 0 accepted, 1 acquisition/operation failed, 2 quarantined, 3 an
explicit `--fail-on` threshold was reached. Warnings normally remain accepted.

Local `--input` CSV checks use a separate comparison stream. Keep synthetic demos
in a separate database too. `sentinel migrate --db old.sqlite` additively upgrades
v0.1 history; back it up first. Legacy sampled events cannot be reconstructed.

## Reproduce checks

```bash
python -m pytest --cov=civicdata_sentinel
python -m ruff check src tests dashboard scripts
python -m ruff format --check src tests dashboard scripts
python -m pip check
python -m pip_audit --skip-editable
python scripts/verify_catalog_live.py --output evidence/new-live-check
python scripts/verify_workflow_local.py --output reports/new-runner-check
python scripts/benchmark_semantics.py --output reports/benchmark.json
```

Live and runner-verification output directories must be new. Live failures or
cross-format disagreements fail explicitly. Synthetic benchmark results validate
constructed cases only, not a general real-world false-positive rate.

## Automation

The monitor runs at minute 17 of every hour (UTC). Scheduling and repository token
permissions still require a first GitHub-hosted run after publication. State lives
on `sentinel-state`, separate from source commits. Restore verifies compressed and
database hashes. Persistence uses SQLite backup and ordinary Git push; concurrent
updates are rejected. Artifacts retain reports and a portable database even if push
fails. Do not manually edit the state branch. See [operations](docs/operations.md).

No external notifications are sent. The deduplicated outbox supports future Issues
or webhook integrations without coupling the engine to an account or spamming
repeated findings. CI includes Windows/Linux, Python 3.11/3.12, lint, tests and audit;
only Windows/Python 3.12.2 has been executed locally.

## Documentation and licensing

- [Architecture and trust model](docs/architecture.md)
- [Critical analysis and alternatives](docs/design-decisions.md)
- [Verification and limitations](docs/verification-v0.2.0.md)
- [Configuration JSON Schema](docs/config.schema.json)
- [Changelog](CHANGELOG.md)

Code: MIT. Madrid data: Ayuntamiento de Madrid, CC BY 4.0; see
[data attribution](evidence/NOTICE.md). Independent of CivicWater. No AI is needed
for these deterministic checks, and no scientific novelty is claimed for the algorithms.
