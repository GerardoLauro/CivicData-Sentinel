# Evidence and data attribution

`2026-11-05/official.csv` is an unmodified download of **Ayuntamiento de Madrid,
Fuentes de agua para beber. 2026**, resource `300051-26-fuentes`, retrieved on
2026-11-05. CKAN result files contain records from that same municipal resource,
saved as pretty-printed JSON from actual API responses. The SQLite database
contains derived canonical snapshots. These are real observations, not fixtures.

- Publisher/catalog: https://datos.madrid.es/dataset/300051-0-fuentes
- Resource: https://datos.madrid.es/dataset/300051-0-fuentes/resource/300051-26-fuentes
- License: **CC BY 4.0**, https://creativecommons.org/licenses/by/4.0/
- Actual dated CSV URL, download hash and original metadata: `2026-11-05/summary.json`
  and `resource-before.json`.
- Transformations: DataStore nulls become empty strings; surrounding whitespace
  is trimmed for configured semantic comparisons; `_id` is used for pagination
  and excluded from canonical dataset fields. No coordinate imputation.
- No endorsement by Ayuntamiento de Madrid is implied.

The code's MIT license does not replace the municipal data license.
`tests/fixtures/` contains separate, fictional records. The workflow-local check
uses only these synthetic fixtures; it is not evidence of live municipal changes.

`sha256.json` covers all files in the live acquisition directory except itself.
`checks/` contains local verification results, not GitHub-hosted workflow runs.
