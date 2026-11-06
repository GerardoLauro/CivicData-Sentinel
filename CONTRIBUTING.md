# Contributing

Use Python 3.11 or newer and a virtual environment. Install `.[test,dashboard,dev]`.
Run Ruff check/format, pytest with coverage, pip check and pip-audit before opening
a pull request. CI validates Linux and Windows. Keep changes focused and add tests
for behavioral changes; mark synthetic scenarios explicitly.

Dataset contracts belong in configs/. Include publisher/license attribution, stable
keys, realistic freshness bounds and reproducible source URLs without credentials.
Never commit operational state, tokens, local paths, raw private data or generated
caches. Live checks are opt-in and must not be confused with offline tests.

Describe the trigger, changed behavior and checks actually performed. The code is
MIT licensed; retain third-party notices and municipal data licensing separately.
