# Architecture

Validated YAML -> bounded HTTPS adapter -> parser input -> conservative normalization
-> structural gate -> profile and quality rules -> semantic comparison -> trust
decision -> single SQLite transaction -> atomic report file.

Pydantic validates nested options and rejects unknown fields. CSV, CKAN discovery,
CKAN pagination and flat JSON envelopes share bounded HTTP acquisition with three
attempts for transient failures. Hourly unpivot is configured separately from the
source adapter. Composite identities use JSON tuples to avoid delimiter collisions.

The coordinator holds a native cross-process lock during acquisition and commit.
SQLite stores immutable compressed snapshots, parser inputs, source documents,
complete events, run reports, incidents, outbox transitions and approval decisions.
SHA-256 and SQLite integrity checks detect accidental corruption, not malicious
administrators capable of recomputing hashes. SQLite backup produces portable state.

Network and local-file heads are separate. Source/identity/normalization changes
start a new comparison baseline, visibly; changing a quality threshold does not.
Schema removal and critical findings hold a valid candidate for review. Acquisition
and structural failures have no record diff and cannot advance trust. Candidate
events are retained but explicitly labelled unaccepted in the interface.

Numeric equivalence is opt-in. Original values and representation changes remain
in snapshots even when no semantic event results. Rolling expiry uses an explicit
time column and horizon; unexpected current-window removals remain suspicious.
Freshness uses actual observation timestamps, qualified by validity flags, or
published metadata. Unknown timezone or missing metadata never becomes invented UTC.

Incident identities exclude counts and sample values. Repeated findings increment
occurrences; opening, reopening, severity escalation and recovery create outbox
events. Failed acquisition cannot establish recovery of unexecuted quality checks.
Recovery after editing a contract is a rule outcome, not proof of a source repair.

Reports sample 100 events for convenience; SQLite and exports retain every event.
Replay re-parses stored input using the captured contract and original observation
time, then checks canonical content and declarative rule outcomes. It does not
reproduce historical HTTP availability or replace dependency/code version control.
