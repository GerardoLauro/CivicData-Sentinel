# Critical review and engineering choices

The 0.1.1 baseline was re-run: 35 tests passed. Its correct record-order independence
and structural rejection behavior were retained. Its main gaps were sampled-only
event history, weak configuration validation, a passive single-dataset UI, no
composite identities, and warning-level mass removals advancing the baseline.
Local fixtures could also contaminate live history in a shared database.

## Existing solutions reviewed

| Project | Relevant strength | Decision |
| --- | --- | --- |
| [Great Expectations](https://github.com/fivetran/great_expectations) | Extensive expectation ecosystem, schema validation | Avoid a second orchestration framework for this small public-feed monitor |
| [Frictionless](https://github.com/frictionlessdata/frictionless-py) | Tabular descriptions, validation and transformations | Useful reference; existing parser plus explicit small transforms kept integration cost low |
| [Soda Core](https://github.com/sodadata/soda-core) | Declarative contracts across data platforms | Contract approach is useful; database/platform connectors are outside this release |
| [git-history](https://github.com/simonw/git-history) | Historical data exploration | Earlier conceptual inspiration; no source copied |

Reusable runtime components: HTTPX (BSD-3-Clause), PyYAML (MIT), Pydantic (MIT),
filelock (MIT), Streamlit (Apache-2.0). Their distributions retain their licenses;
they are dependencies, not vendored source. No competitor implementation was copied.

The distinctive contribution is the combination of public-feed semantics, explicit
trust decisions, complete temporal evidence and low-cost operation. It is not a new
validation algorithm or a claim to outperform mature observability platforms.

An initial live check caught an overly numeric air technique-code regex and a
parking CSV encoding assumption. Contracts were corrected from observed data;
those development attempts remain in local audit history. A separate clean live
verification records final results. The publisher documents local Madrid hours and
hour-ending H24 in its official air-file interpreter:
https://datos.madrid.es/dataset/201410-0-calidad-aire-diario/resource/201410-63-calidad-aire-diario/download/interprete_ficheros_20calidad_20del_20aire_global.pdf

The dependency audit initially flagged filelock 3.32.7. Upgrading to 4.2.9 eliminated
the reported advisories, without ignore rules. The fixed major version requires
Python 3.11+, so that requirement is explicit in packaging and CI.
