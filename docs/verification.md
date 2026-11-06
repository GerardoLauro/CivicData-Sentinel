# Verification — 5 November 2026

> Historical report. Its original `evidence/` paths are preserved inside the
> beta release asset `reproducibility-evidence.zip` and in earlier Git tags.
> These observations are not new publication-session results.

## Starting point

Work continued from the supplied `CivicData-Sentinel-v0.1.0.zip`, SHA-256
`ef87e52ed2ea8cbaae02c81c128bcc8f7562e31ab54f6c777ed4e23e61d2628c`.
The original sources were extracted and inspected, not recreated. The original
16 tests passed. Running the unmodified configuration against the downloaded real
CSV produced 106 `invalid_values` warnings because two status names were wrong.

## Observed live acquisition

Evidence: [`summary.json`](https://github.com/GerardoLauro/CivicData-Sentinel/blob/v0.2.1/evidence/2026-11-05/summary.json),
[`requests.json`](https://github.com/GerardoLauro/CivicData-Sentinel/blob/v0.2.1/evidence/2026-11-05/requests.json),
[`CSV discovery`](https://github.com/GerardoLauro/CivicData-Sentinel/blob/v0.2.1/evidence/checks/csv-discovery.json).

At 10:13:07–10:13:18 UTC (11:13:07–11:13:18 Rome), the verifier downloaded current
resource metadata and the official CSV, performed two network-based monitor runs,
and re-read the metadata. No synthetic fixtures were used in this integration.

| Check | Observed result |
| --- | --- |
| Resource | `300051-26-fuentes`, CSV, 2026 |
| Rows / data columns | 2,314 / 24 |
| Pages in each monitor run | 500 + 500 + 500 + 500 + 314 |
| Additional consistency request | First 500 rows re-read after each run |
| Exact total / primary keys | Exact reported total; no duplicate or blank `ID` |
| CSV bytes | 649,120 |
| Published MD5 equals downloaded CSV | `4d35b8361ed207f589bf77db07edd65f` |
| CSV SHA-256 | `1f45a5c0770a755c55546ed8975491787f7b08cec3047bff5551502d2e87da1f` |
| Canonical content SHA-256 | `ea727904cb86311e4250f1c697ffe6f7b2abd315a08201ceb6f6bef36abd5751` |
| CSV vs CKAN canonical record maps | Identical for every record and field |
| First run | Baseline, no inferred change events |
| Second run | 2,314 unchanged; 0 added, 0 removed, 0 modified |
| Persistence | Two audit runs and one immutable snapshot |

The separate production `ckan_resource` discovery/download path also returned an
identical CSV. The CSV begins with UTF-8 BOM, uses semicolons and quoted fields;
the parser accepts it with `utf-8-sig`. ID strings and leading zeros are preserved.

Observed `ESTADO` values were `OPERATIVO` (2,208), `FUERA_DE_SERVICIO` (103), and
`CERRADA_TEMPORALMENT` (3). The latter spelling is preserved exactly. These are
publisher labels, not independent field inspections of the fountains.

Latitude was absent in 268 records and longitude was absent in 268. The configured
validator now reports these completeness counts, accepts the rows and does not
impute geographic coordinates. No other quality-rule warnings were produced by
this accepted snapshot. That only covers the implemented checks, not every
possible defect in the municipal dataset.

The metadata modification string `2026-11-05T06:53:58.311808` lacks a timezone.
DataStore responses supply no source modification timestamp. We do not infer a
freshness guarantee or assume a timezone. Two immediate identical snapshots are
not evidence of multi-day stability. Later-page-only concurrent edits can escape
the first-page consistency recheck; CKAN provides no transaction across requests.

## Automated tests and Streamlit

**35 local tests passed**, covering the core, malformed CSV, stable pagination
ordering, changing schemas, duplicate/null internal IDs, estimated totals, empty
intermediate pages, overcounts, nested values, missing-coordinate counts, baseline
preservation and dashboard behavior. Protocol faults and record modifications in
unit tests are synthetic scenarios and are not municipal findings.

Streamlit **1.66.1** was checked with AppTest against the real two-run database:
no app exceptions, two displayed history rows, no local-input warning and no
change to the SQLite bytes. A temporary headless server returned HTTP **200** for
both `/_stcore/health` (`ok`) and the frontend page, then was stopped. This is not
a visual browser review. See [`dashboard.json`](https://github.com/GerardoLauro/CivicData-Sentinel/blob/v0.2.1/evidence/checks/dashboard.json).

Local Python was **3.12.2**, HTTPX **0.28.1**, PyYAML **6.0.3**, pytest **9.2.0**.
The CI matrix specifies Python 3.10 and 3.12; Python 3.10 was not run locally.
The recorded Windows dependency versions are an environment trace, not a universal
cross-platform lockfile.

The restricted local execution environment blocked DNS and Windows event-loop
socket setup. Network/Streamlit checks succeeded with normal host execution.
Those initial environment errors were not treated as source-data anomalies.

## GitHub Actions: verified and pending

Both YAML workflows passed **actionlint 1.7.12**, without an installed shellcheck.
The monitor's actual shell blocks were executed locally against a disposable bare
Git remote. Each attempt started in a fresh clone:

1. Fictional base CSV: success, 1 stored run and 1 snapshot.
2. Fictional changed CSV: success, 2 stored runs and 2 snapshots; 1 addition,
   1 removal and 1 modification.
3. Fictional duplicate-ID CSV: failure exit code 1, 3 stored runs and still
   2 snapshots; the last successful baseline remained unchanged.

The failure report and history were committed locally before the failure status
was surfaced. See [`workflow-local.json`](https://github.com/GerardoLauro/CivicData-Sentinel/blob/v0.2.1/evidence/checks/workflow-local.json)
and run `scripts/verify_workflow_local.py` to reproduce this isolated simulation.

**Pending:** actual GitHub-hosted execution, scheduler timing, token permissions,
branch protection, and artifact-upload service. No GitHub repository or release
has been published. To close that gate after the owner publishes: run `Test`,
run `Daily Madrid data check` manually, verify its bot commit and retained
artifact, run it again, and confirm the database retained both attempts. The
repository policy must allow the workflow's state commit. No force-push is used.

## Reproduction and artifact integrity

From the repository root, install `.[test,dashboard]`, then:

```bash
python -m pytest
python scripts/verify_live.py --output evidence/new-live-check
python scripts/verify_dashboard.py --db evidence/new-live-check/history.sqlite --output evidence/new-dashboard.json
python scripts/verify_workflow_local.py --output ../new-workflow-check
# With actionlint installed:
actionlint .github/workflows/ci.yml .github/workflows/monitor.yml
```

Output directories for the live and workflow checks must be new. A mismatch,
network failure or partial publication fails the live verifier explicitly. Saved
DataStore result files are actual returned result objects serialized as JSON,
not the original wire bytes. `official.csv` and resource metadata responses retain
the downloaded bytes. The live `sha256.json` lists their stored-file hashes.

Dataset attribution and transformations are in [evidence/NOTICE.md](https://github.com/GerardoLauro/CivicData-Sentinel/blob/v0.2.1/evidence/NOTICE.md).
