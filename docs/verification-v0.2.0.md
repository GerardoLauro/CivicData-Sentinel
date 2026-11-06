# v0.2.0 verification and limits

> Historical report. Its original `evidence/` paths are preserved inside the
> beta release asset `reproducibility-evidence.zip` and in earlier Git tags.
> These observations are not new publication-session results.

Machine-readable evidence is in `evidence/v0.2.0/`. Original 0.1.1 evidence remains
under its original directories and is not presented as a new test result.

The live verifier acquired each of three official resources twice on 5 November
2026, compared every normalized record and column with an independent format,
replayed six stored observations offline and verified database/artifact integrity.
All comparisons and replays passed. The six observations comprise three baselines
and three immediate repetitions; they are not a multi-day study.

Observed records: 2,314 fountains, 63 parking facilities, 126 wide air rows expanded
into 3,024 hourly records. Findings: 268 missing values in each geographic coordinate
column of the fountains and longitude `--3.65138632197171` at parking PK 36269.
No coordinate imputation or arbitrary source correction was performed.

The synthetic benchmark compares the old and new semantic engines on five explicitly
constructed 1,000-record cases. New semantics suppress numeric-format, declared
tolerance and ignored-metadata changes while retaining all 100 injected updates.
This is not an empirical real-world precision/recall estimate.

See `tests.xml`, `coverage.json`, dependency audit, dashboard and runner summaries
for final executed checks. Unit fixtures and runner simulations are synthetic;
the live database and independent reference files contain municipal observations.
The runner test uses fresh LOCAL Git clones and checks state restoration, failure
retention, unchanged source branch and rejection of stale concurrent updates.

## Remaining limitations

- GitHub-hosted scheduling, tokens, branch policies and artifact upload remain untested.
- Local tests use Windows/Python 3.12.2. Linux and Python 3.11 are configured in CI,
  not claimed as locally executed.
- Dashboard is checked with AppTest and HTTP; no final visual browser review claimed.
- CKAN/JSON APIs provide no transaction across pages. First-page recheck and exact
  counts cannot detect every possible concurrent edit. Independent format checks
  are opt-in verification, not part of every hourly collection.
- Single-host writer serialization; no distributed locks, authentication or hosted API.
- 20 MB source/100,000 normalized-row bounds; 250 MB portable state-branch limit.
- No retention pruning: SQLite and binary Git history grow. Use external durable
  storage for larger/long-lived deployments; never expose this local UI publicly
  without an appropriate access boundary.
- Dashboard history is bounded to the latest 1,000 attempts before date/origin
  filtering. CLI history is paginated; complete events are exported for each run.
- DST folds cannot recover information omitted by the publisher. Air values are
  provisional; numeric sanity bounds are not legal pollution thresholds.
- Resource identifiers may roll over each year; automatic yearly selection is absent.
- Schema types are inferred from observed lexical values, not authoritative types.
- Rule changes can resolve incidents without a change at the source; inspect the
  stored contract hashes before interpreting recovery as a municipal data repair.
- Hashes detect accidental corruption, not an administrator who can rewrite both
  evidence and hashes. No independent signed timestamp authority is used.
