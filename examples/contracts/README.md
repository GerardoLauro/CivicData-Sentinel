# Retained official Madrid contract examples

These are actual network captures from 11 November 2026, **not synthetic
fixtures**. Original PDFs, catalog HTML, metadata and public records come from
Ayuntamiento de Madrid under CC BY 4.0. Attribution and exact source URLs/digests
are retained in `capture-manifest.json`; the code is licensed separately under
MIT. No municipal endorsement is implied. Raw provider errors, historical data
and previously observed outages elsewhere in the project are not removed.

Run `python scripts/contract_examples.py` from the repository root after
installing `.[contracts]`. It uses these retained files only, checks hashes and
writes a **separate** proposal SQLite workspace and pending proposals. It does
not approve rules or touch the monitor's database. Output includes candidate
YAML, sample impact, exact citations, Table Schema subset exports and benchmark.

`human-reference.json` records documentary statements confirmed by the user,
including the generic/outdated parking PDF limitation. That confirmation is
for the benchmark only. See `docs/evaluation-v0.3.0.md` for denominators, current
data mismatches, abstentions and why no production contract was activated.
