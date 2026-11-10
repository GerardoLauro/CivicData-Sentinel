# Air acquisition incident — 10 November 2026

Status: **partial operational recovery, not an upstream API repair**. The changes
retain failures and their evidence. A release/CI success does not establish that
all three external services are available. Final run links/results are in release notes.

## Complete historical review

Downloaded metadata, full logs and artifacts for all thirteen failed scheduled
runs (7–10 November), plus the successful scheduled run on 6 November. Every failed
run accepted fountains/parking, retained state and uploaded its artifact. The first
air failure parsed JSON but could not find the configured records/total path;
the remaining twelve failures were three exhausted 35-second ReadTimeout attempts.
The older collector did not retain failed-response bodies/status/headers, so the
7 November envelope cannot be reconstructed. An error envelope versus a changed
JSON schema cannot be resolved retrospectively. No synthetic fixture is presented
as the recovered historical response.

| GitHub run | Created UTC | Air | Observation | Job queue | Job duration |
| --- | --- | --- | --- | --- | --- |
| [42278520158](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42278520158) | 2026-11-06T19:18:54Z | success | accepted | 2s | 35s |
| [42315961948](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42315961948) | 2026-11-07T00:04:36Z | failed | schema/envelope mismatch | 2s | 24s |
| [42344652201](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42344652201) | 2026-11-07T05:54:07Z | failed | ReadTimeout | 3s | 128s |
| [42374458886](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42374458886) | 2026-11-07T12:53:28Z | failed | ReadTimeout | 2s | 123s |
| [42399087587](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42399087587) | 2026-11-07T18:00:34Z | failed | ReadTimeout | 3s | 127s |
| [42417298590](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42417298590) | 2026-11-07T21:44:39Z | failed | ReadTimeout | 3s | 129s |
| [42433995040](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42433995040) | 2026-11-08T01:22:43Z | failed | ReadTimeout | 2s | 131s |
| [42464981476](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42464981476) | 2026-11-08T08:55:40Z | failed | ReadTimeout | 3s | 130s |
| [42497269168](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42497269168) | 2026-11-08T15:55:49Z | failed | ReadTimeout | 2s | 125s |
| [42520059445](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42520059445) | 2026-11-08T20:25:37Z | failed | ReadTimeout | 3s | 126s |
| [42542170119](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42542170119) | 2026-11-09T00:48:26Z | failed | ReadTimeout | 3s | 128s |
| [42582172365](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42582172365) | 2026-11-09T07:53:38Z | failed | ReadTimeout | 3s | 128s |
| [42676365190](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42676365190) | 2026-11-09T18:42:21Z | failed | ReadTimeout | 4s | 131s |
| [42739839383](https://github.com/GerardoLauro/CivicData-Sentinel/actions/runs/42739839383) | 2026-11-10T02:01:28Z | failed | ReadTimeout | 2s | 131s |

The latest historical backup has 54 attempts. Air's trusted head remains run 13
from 6 November, digest `2d3ede75b6216734a10ddab5136088ac41c643796d1cdac9c6f91e88ea2e588d`.
All thirteen air failures have digest=null, no semantic changes and no accepted
snapshot. Fountains/parking heads advance independently. No history was rewritten.

## Direct source investigation

The [official air catalog](https://datos.madrid.es/dataset/212531-0-calidad-aire-tiempo-real)
still publishes the configured `calair_tiemporeal` JSON/CSV API. The catalog answers
HTTP 200, but JSON probes with page sizes 1/500/4500/5000 and the CSV distribution
time out. A separate single 120-second read probe also times out (122.3 seconds
including overhead). Increasing the timeout is therefore not evidence of a repair.
ReadTimeout means network inactivity while receiving, not a confirmed HTTP error
status or proof that SQL/schema alone caused the outage.

Alternatives reviewed: same-service CSV shares the failure; accumulated-day API
has a different rolling publication contract and the same host; the officially
linked legacy mambiente endpoint fails DNS resolution; the integrated municipal
viewer returns HTTP 403 to this client. Regional Community of Madrid data are not
the same municipal station network and are not silently substituted. No currently
available equivalent, fresh air fallback was validated.

The [municipal file interpreter](https://datos.madrid.es/dataset/212531-0-calidad-aire-tiempo-real/resource/212531-4-calidad-aire-tiempo-real/download/212531-4-calidad-aire-tiempo-real.pdf)
defines the same hourly sample identity, H01–H24 values and V01–V24 validity flags.
Keys, normalization, validity filters, time zone/DST handling and four-hour freshness
checks are unchanged. Stale or unverified alternative data are not accepted.

An additional current issue was observed: fountains DataStore now returns HTTP 404
with a municipal maintenance page; `resource_show` says datastore_active=false.
The current official CSV of resource `300051-26-fuentes` is available. Its complete
normalized snapshot equals the prior trusted DataStore snapshot: **2,313 records**,
same digest `5dbb530558a0773caca9830205eb722d454d2bf0bb94d6c1528d8f9cdfc1f8f3`,
zero additions/removals/modifications. This is an observed same-resource equivalence,
not a claim that a currently unavailable second format was re-downloaded successfully.
The CSV was discovered from live metadata, not a stale hardcoded filename.

## Changes and invariants

- Validated root-level acquisition policy: connect/read/write/pool timeouts,
  attempt limit, full-jitter exponential backoff, Retry-After seconds/HTTP dates,
  retry elapsed budget and redirect cap. Retry only transport/transient HTTP errors;
  deterministic JSON/schema errors fail immediately. Excessive Retry-After causes
  deferral, not an early request that ignores the provider's delay.
- HTTPX timeouts bound inactivity/individual operations. The retry budget is checked
  before attempts, on redirect hops, between body chunks and before sleeps; it is
  not a hard real-time cancellation primitive. The workflow's 20-minute limit remains.
- Request hooks reject insecure/credential-bearing redirects before following them.
  Reject HTTP partial responses, uncompressed Content-Length mismatches, HTML and
  explicit JSON error flags even if a records list is present.
- Persist each attempt's URL, HTTP status, selected non-secret headers, error kind,
  retry decision/delay, timings and payload hashes. Diagnostic response bodies/prefixes
  are bounded to eight × 64 KiB, with explicit truncation/retention flags and hashes.
  Transport timeouts with no bytes do not invent a response body/status.
- Errors remain failed runs. Received prefixes/error envelopes cannot become empty
  accepted datasets. Successful retries retain the failed-attempt trace/evidence.
- Opt-in fountains recovery requires a retired endpoint (404/410) or explicit CKAN
  failure, metadata naming the **same resource ID**, inactive DataStore and same
  HTTPS authority. Schema/quality/trust checks still run. Structural/pagination faults
  and rate limiting cannot be bypassed via this path. Recovery adds a source warning
  and keeps the original failure/body; it does not pretend the DataStore succeeded.
- Acquisition policy is outside the semantic comparison identity. Actual signatures
  for all three contracts were compared with the archived trusted reports and remain
  equal. The local real fountains recovery used the existing head with baseline=false
  and passes all supported replay levels.
- Artifacts gain a safe runner-context JSON (event, cron expression, run ID/attempt,
  source SHA and UTC recording time), never the full environment/event payload.

## Scheduler diagnosis

Fourteen visible scheduled runs from 6–10 November, including one success. Gaps
between creation times: 3.63–10.81 hours, median 5.83.
Jobs queue for 2–4 seconds and last 24–131 seconds, far shorter than those gaps.
There are no observed overlapping/cancelled jobs explaining missing hourly runs.
Cron `7 * * * *`, default branch, active status and unchanged source SHA are correct;
60-day inactivity deactivation does not apply to this recently active repository.

This locates the observed gap before runner execution, not in the data download or
the state-writer concurrency lock. The API does not expose every intended cron fire
or internal scheduling decision. We cannot prove which slots were delayed/dropped,
or exclude deleted runs from API results. [GitHub documents best-effort scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
including delays/dropped jobs under load. This is consistent with the observations;
it is not proof of a specific backend incident or an hourly SLA. The cron remains
unchanged; an independent scheduler/watchdog is required if cadence must be guaranteed.
No external scheduler, credentials or unrequested notifications were provisioned.

## Reproduction and tests

```bash
sentinel run-all --db reports/new-check.sqlite --output-dir reports/new-check
python -m pytest --cov=civicdata_sentinel --cov-fail-under=85
python -m ruff check src tests scripts dashboard
python -m ruff format --check src tests scripts dashboard
python -m pip check
python -m pip_audit --skip-editable
gh run list --repo GerardoLauro/CivicData-Sentinel --workflow monitor.yml --limit 100
```

Use new output paths. Regression bodies, timeouts, partial transfers, retries and
fallback faults are synthetic. Historical logs/artifacts and live probes are separate.
The independent-format verifier now refuses to claim independence if the primary
acquisition already used the same CSV fallback. Integrity/replay still have their
documented exclusions; hashes alone are not a provenance attestation.
