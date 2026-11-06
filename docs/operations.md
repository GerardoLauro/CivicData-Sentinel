# Operation and recovery

Run from the repository root. Contracts live in `configs/`; adding a compatible
dataset requires YAML, not changes to the engine. Export `sentinel config-schema`
for editor validation. Never store credentials in public source URLs.

`state/sentinel.sqlite` is the local source of truth. Back it up with `sentinel
backup`; do not copy a live WAL database by itself. Verify before restoring, and
retain the original backup before `sentinel migrate`. Legacy full events were not
stored and cannot be recovered. Report-file delivery can fail after the database
transaction commits: use `sentinel show`/`export` to recover that successful audit.

Review quarantined source records, schema changes, thresholds and the previous head
before explicit approval. Approval preserves the original report and records a
reason. No automatic acceptance after a timeout or repeated suspicious publication.

GitHub uses `scripts/state_branch.py restore` before collection and `persist` after.
The `sentinel-state` branch is created on first use. It contains a compressed SQLite
backup and integrity manifest. Source checkout is untouched. Missing branch means
first acquisition; failed restore is an error, never a silent fresh baseline.
Concurrent state changes reject persistence rather than overwrite history. Download
the retained artifact and investigate before manually restoring any checkpoint.

Allow workflow contents-write permission and branch creation/push according to your
repository policy. The hourly schedule is best effort, not a continuous SLA.
First run CI and a manual monitor, inspect artifacts/state commit, then run again
and confirm history survives. See the release operational validation report for observed remote runs and remaining gates.

External notifications are intentionally not enabled. Consume `sentinel alerts
--after CURSOR`, deliver transitions, then durably retain the last delivered cursor.
Use the fingerprint as an idempotency key in a future Issues/webhook integration.
The outbox alone does not provide exactly-once third-party delivery.

Public persistence uses `persist --public-state` and rejects local inputs or
contracts outside the reviewed CC BY 4.0 set. This guard does not anonymize data;
review [public-state implications](public-state-assessment.md) before extending it.
