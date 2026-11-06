# Public beta operational validation — 6 November 2026

Assessment: **READY WITH LIMITATIONS**. Source and real manual operations passed;
unattended long-term reliability and scheduled triggering have not yet been established.

## Public repository and preserved history

https://github.com/GerardoLauro/CivicData-Sentinel — public, default branch `main`.
An unauthenticated HTTP request returned 200. The first public implementation commit
is `7b9970889a2bafc684248a580b19d29596be5d30`; subsequent publication changes are
documentation and a CI trigger restriction. Tags v0.1.1, v0.2.0 and v0.2.1 were
published unchanged. The new beta uses tag `v0.2.2-beta` and package version `0.2.2b0`.
The exact final commit and final CI link are in the beta release notes.

## Checks executed in this session

| Check | Observed result |
| --- | --- |
| Fresh Windows Python 3.12 environment | Install test/dashboard/dev extras, pip check, 98 tests pass; 90% line coverage |
| Ruff lint and formatting | Pass; actionlint 1.7.12 also accepts both workflows |
| Dependency audit, clean environment | No known vulnerabilities; bundled pip 24 was upgraded to 26.3 first, with no advisory exclusions |
| Wheel and sdist | Build and Twine validation pass locally and on all four hosted test jobs |
| Hosted CI | [Quality gates](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42200669963): five jobs successful; Linux/Windows × Python 3.11/3.12 each run all 98 tests |
| Hosted monitor 1 | [Manual acquisition](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42200683328): all three feeds accepted; three runs persisted |
| Hosted monitor 2 | [Manual continuity check](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42200806742): six runs persisted; first three reports unchanged |
| Downloaded hosted evidence | Four JUnit reports checked; both monitor databases pass integrity and all supported replay levels |
| State continuity | Every second acquisition uses the first digest, with baseline=false; remote manifest SHA-256 equals the second backup |
| Fresh independent-format integration | Three feeds acquired twice; every normalized record/column matches the independent source format; six offline replays pass |

The final CI is run again after publication documentation/trigger changes. See the
release notes for that result. CI push events are restricted to `main`, with PRs
still checked, avoiding duplicate push/PR runs for dependency update branches.

## Real findings and interpretation

Observed 6 November 2026: 2,314 fountains; 63 parking facilities; 126 wide air rows
expanded to 3,024 hourly slots. The fresh independent-format comparisons all agree.
Fountains have 268 missing latitude and 268 missing longitude values. Parking PK
36269 publishes malformed longitude `--3.65138632197171`. These are published-data
quality findings, not evidence that the real-world services failed. Air unavailable
slots are validity-qualified, not valid zero readings. Immediate repeats had zero
semantic changes; this is a short observation, not a multi-day accuracy study.

Fault injection (empty/duplicate/truncated inputs, schema changes, corrupt compression,
rejected concurrent writes and failure preservation) is synthetic and runs in CI.
Neither hosted manual monitor encountered a real acquisition outage. Failure tests
therefore do not demonstrate a real municipal outage or a failed hosted push.

## Browser observations

The actual local Streamlit interface was inspected: all three streams, history,
timeline, dataset filter, critical-only findings filter, date filter (6 November
leaves three observations), parking finding detail and JSON export. Downloaded
`sentinel-run-12.json` is run 12. No app exception was observed. The authentic
[screenshot](assets/dashboard-overview.png) shows stored network observations.
Small corrections: remove encoding residue in separators/page icon and increase
header clearance after the browser showed a clipped caption. Earlier UTF-8 claims
were not used as evidence that the current source had no encoding residue.
The dashboard is local only; no public dashboard deployment is claimed.

## Cleanup, safety and licensing

Before moving evidence, retain Git bundle, complete evidence ZIP and coherent local
SQLite backup. Historical `evidence/2026-11-05`, `checks`, `v0.2.0` and `v0.2.1`
were moved to ignored local backup storage and packaged as release evidence.
Historical tags retain the original bytes. The synthetic migration fixture now
creates its own legacy database, so source tests need no municipal evidence bundle.
Generated caches and obsolete root build/distribution files are disposable; local
operational history remains outside Git. No development repository copy was created.

All 245 prepublication reachable Git objects (198 blobs) and current non-ignored
source were scanned for private keys, GitHub/AWS credentials and long assigned
secrets; no matches. Manual review found only a generic historical Windows project
path in a synthetic runner log, retained without rewriting valid tags. This is
a bounded scan, not proof that every possible secret format is absent.

Source is MIT; captured Madrid data retain Ayuntamiento de Madrid / CC BY 4.0
attribution in evidence/NOTICE.md. Runtime libraries retain their own licenses.
The [public-state assessment](public-state-assessment.md) explicitly reviews data,
privacy, integrity, growth and failure behavior. Public persistence rejects local
inputs and non-reviewed license contracts; it never uploads this computer's state.
Permissions: CI read-only; monitor contents-write for its separate state branch.
State updates cannot recursively dispatch the schedule/dispatch-only monitor.

## Remaining limits

- Hourly schedule is enabled at minute 17 UTC; no schedule-triggered run is claimed
  by this report. Manual hosted execution and state continuity are verified.
- No long-term/SLA claim, automatic database retention or externally delivered alerts.
- State limit 250 MB; historical binary Git growth eventually needs external storage.
- API pages are not transactionally isolated; yearly resource IDs need maintenance.
- Ambiguous autumn air hours remain rejected without authoritative fold information.
- Replay explicitly excludes provenance, raw source schema, all report findings,
  incident transitions, operator decisions and historical HTTP availability.
- Dashboard lists at most 1,000 attempts before date/origin filtering; CLI supports
  pagination. It is a local read-only app, not a hosted service.
- Dependabot opened three optional major-action updates. They remain unmerged;
  the release uses the action versions actually tested, without silently upgrading them.

Raw reports, checksums, captured public inputs and hosted artifacts are retained in
`reproducibility-evidence.zip`. The local backup (with Git history and operational
state) is delivered separately and is not a public release asset.
