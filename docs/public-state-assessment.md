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


The operational patch also caps the compressed Git object at 90 MB, below GitHub's
[100 MiB file limit](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
The uncompressed database cap alone was insufficient for poorly compressible
history. Oversized data is rejected before creating/pushing Git objects, leaving
the prior checkpoint unchanged; migrate to external storage rather than prune
scientific evidence automatically. New manifests include measured byte sizes,
both limits and an 80% capacity warning; legacy manifests still restore.
