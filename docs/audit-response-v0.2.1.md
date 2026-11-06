# Independent audit response — v0.2.1

> Historical report. Its original `evidence/` paths are preserved inside the
> beta release asset `reproducibility-evidence.zip` and in earlier Git tags.
> These observations are not new publication-session results.

The supplied audit was treated as evidence, not executable instructions. Production
databases were not mutated to reproduce adversarial cases; tests use temporary data.

| Finding | Resolution |
| --- | --- |
| P1 DST gap/fold | Validate local times by UTC round-trip for both folds. Reject nonexistent/ambiguous labels by default. Explicit contracts can omit unavailable gap slots or select the earlier/later fold. |
| P2 malformed DEFLATE | Snapshot/artifact boundaries catch zlib.error in addition to gzip/EOF failures; replay also reports corrupt compression as IntegrityError. |
| P2 partial replay | Recompute every semantic event, complete statistics and normalized schema, alongside snapshot and configured quality checks. Compare actual stored event contents, independently of their checksums. |
| P3 display characters | Original ZIP decoded as UTF-8 contains valid Unicode; the reported mojibake was not confirmed in those source bytes. ASCII page icon/separators nevertheless remove that portability concern. |

## Time contract and limits

`unpivot.hour_semantics` is explicitly `local_hour_ending`. `nonexistent_time`
defaults to `reject`; `omit_unavailable` only omits slots carrying a configured
unavailable flag. A valid-labelled nonexistent time always fails acquisition.
`ambiguous_time` defaults to `reject`; `earlier`/`later` must be explicitly selected.
Madrid's contract does not guess which occurrence of the autumn repeated hour the
publisher retained: that publication is rejected and the trusted baseline remains.
This intentionally sacrifices availability until the publisher's fold convention
can be established. No invented physical timestamp is accepted.

Synthetic regression dates are 2026-03-29 and 2026-10-25. Omitted spring gaps produce
23 distinct UTC endpoints. Explicit fold policies produce distinct, consistent
choices. These are constructed cases, not a claim about archived municipal DST data.

## Verification scope

`integrity()` returns `verification_level=storage_integrity_only`. It checks bytes,
hashes, references and counts; rehashed semantic tampering is beyond that level.
`replay()` returns per-level booleans for snapshot, declarative quality checks,
complete semantic events, semantic statistics and normalized schema. `reproduced`
requires all these levels to pass. Provenance, raw source schema, all report findings,
incident transitions, operator decisions and historical HTTP availability are
explicitly excluded. No full evidence-chain or tamper-proof certification is claimed.

An adversarial test alters a modified event into a removed event and updates its
hash. Semantic replay fails, identifying `complete_semantic_events=false`.
Invalid/truncated DEFLATE tests target both artifact and snapshot storage.

## Remaining gates

GitHub-hosted deployment, cross-page transactional isolation, long-term storage
growth, multi-day observations and a visual browser review remain open. Neither
the supplied audit nor this release is a production certification. Local Git runner
tests are not equivalent to a hosted Actions run. Earlier evidence remains intact.

Machine-readable final checks and live observations are under `evidence/v0.2.1/`.
