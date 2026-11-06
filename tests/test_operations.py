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
