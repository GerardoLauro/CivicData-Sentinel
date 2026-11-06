# Reproducibility evidence

Full municipal snapshots, captured responses, historical logs and test reports are
retained in the beta release asset `reproducibility-evidence.zip`, rather than the
current source tree. They remain available in earlier Git tags as well. No history
was rewritten. Data attribution is in NOTICE.md.

Generate new results with `scripts/verify_catalog_live.py --output reports/live-check`.
Unit tests use synthetic inputs and do not require archived municipal databases.
Session-specific publication checks and GitHub run links are documented in the
release notes and operational validation report.
