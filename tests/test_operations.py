import importlib.util
from pathlib import Path

import pytest


@pytest.mark.integration
def test_local_runner_persistence_and_concurrent_rejection(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/verify_workflow_local.py"
    spec = importlib.util.spec_from_file_location("runner_verification", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify(tmp_path / "check")
    assert result["source_branch_unchanged"] and result["concurrent_update_rejected"]


def test_public_state_gate_rejects_local_history(tmp_path, contract, csv_file):
    from civicdata_sentinel.monitor import run

    path = Path(__file__).resolve().parents[1] / "scripts/state_branch.py"
    spec = importlib.util.spec_from_file_location("public_state_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = tmp_path / "local.sqlite"
    run(contract(), db, input_file=csv_file([{"ID": "fictional"}]))
    with pytest.raises(ValueError, match="network acquisitions only"):
        module.assert_public_state(db)


def test_compressed_limit_preserves_history_before_creating_git_objects(tmp_path, contract, csv_file, monkeypatch):
    from civicdata_sentinel.monitor import run
    from civicdata_sentinel.storage import backup

    path = Path(__file__).resolve().parents[1] / "scripts/state_branch.py"
    spec = importlib.util.spec_from_file_location("bounded_state", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source.sqlite"
    run(contract(), source, input_file=csv_file([{"ID": "fictional"}]))
    frozen = tmp_path / "checkpoint.sqlite"
    backup(source, frozen)
    before = frozen.read_bytes()
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = repo / ".sentinel-state-parent"
    marker.write_text("", encoding="ascii")
    monkeypatch.setattr(module, "remote_head", lambda repo: "")
    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", 1)

    def forbidden(*args, **kwargs):
        raise AssertionError("No Git object/ref may change when the compressed limit is exceeded")

    monkeypatch.setattr(module, "git", forbidden)
    with pytest.raises(ValueError, match="Compressed state exceeds"):
        module.persist(repo, frozen)
    assert marker.read_text(encoding="ascii") == "" and frozen.read_bytes() == before
