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
