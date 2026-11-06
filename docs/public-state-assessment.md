# Public monitoring state assessment

The scheduled job starts from a fresh runner and collects only the three openly
licensed Madrid contracts. Its database contains municipal public records, source
URLs, captured public payloads, checks, diffs and incident history. It does not
upload this computer's local operational database or synthetic demonstration state.

Publishing this data is consistent with the catalog CC BY 4.0 licenses, with the
attribution retained in evidence/NOTICE.md. Public municipal contact fields may be
present; this is not a suitable workflow for private datasets. Never add credentials
to URLs or private inputs to a public-state workflow.

State is separated from the source branch, compressed, limited to 250 MB, verified
before restoration and updated without force-push. It has no automatic retention:
binary Git history grows, and the limit is not a scalability guarantee. Artifacts
expire after 30 days; the state branch persists. Move to private external storage
before monitoring non-public data or substantially larger/longer-lived feeds.

Contents-write is restricted to the monitoring job because state persistence needs
it; CI uses read-only access. State-branch pushes do not trigger source CI and
cannot trigger the dispatch/schedule-only monitor recursively.
