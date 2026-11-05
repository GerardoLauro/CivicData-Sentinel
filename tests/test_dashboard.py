"""AppTest executes the dashboard with isolated synthetic run history."""

from pathlib import Path

import pytest

from civicdata_sentinel.monitor import run

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.dashboard


def test_empty_and_local_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=20).run()
    assert not app.exception and "No monitoring history" in app.info[0].value
    run(
        ROOT / "configs/madrid_fountains.yaml",
        tmp_path / "state/sentinel.sqlite",
        input_file=ROOT / "tests/fixtures/fountains_base.csv",
    )
    app.run()
    assert not app.exception and app.metric[0].value == "1"
    assert "Local file input" in app.warning[0].value
    assert len(app.dataframe[0].value) == 1


def test_invalid_database_is_explained(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state/sentinel.sqlite").write_bytes(b"not a database")
    app = AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=20).run()
    assert not app.exception and "Unable to read" in app.error[0].value
