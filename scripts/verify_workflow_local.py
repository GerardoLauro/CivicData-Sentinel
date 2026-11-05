"""Execute monitor workflow shell blocks against a LOCAL bare Git remote.

Synthetic CSV inputs replace the live request only. No GitHub account is used.
This tests state persistence, fresh runners and failure retention, not GitHub's
scheduler, credentials, branch permissions or upload-artifact service.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", default="bash", help="Bash-compatible executable")
    parser.add_argument("--output", type=Path, required=True, help="New disposable directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    logs = []

    def execute(command, cwd, env=None, expected=0):
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        logs.append({"command": command, "exit_code": result.returncode,
                     "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != expected:
            raise RuntimeError(result.stderr or result.stdout)
        return result

    remote = output / "remote.git"
    execute(["git", "init", "--bare", "--initial-branch=main", str(remote)], output)
    seed = output / "seed"
    seed.mkdir()
    for name in (".github", "configs", "tests", "src"):
        shutil.copytree(root / name, seed / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(root / ".gitignore", seed / ".gitignore")
    execute(["git", "init", "--initial-branch=main"], seed)
    execute(["git", "add", "."], seed)
    execute(["git", "-c", "user.name=Local verification", "-c", "user.email=local@example.invalid",
             "commit", "-m", "synthetic workflow verification"], seed)
    execute(["git", "remote", "add", "origin", str(remote)], seed)
    execute(["git", "push", "-u", "origin", "main"], seed)
    steps = yaml.safe_load((root / ".github/workflows/monitor.yml").read_text())["jobs"]["check"]["steps"]
    blocks = {step["name"]: step["run"] for step in steps if "name" in step and "run" in step}
    observed = []
    baseline = None
    for index, fixture in enumerate(("fountains_base.csv", "fountains_changed.csv", "fountains_invalid.csv"), 1):
        runner = output / f"runner-{index}"
        execute(["git", "clone", str(remote), str(runner)], output)
        env = dict(os.environ, GITHUB_ENV=(runner / "github-env").as_posix())
        execute([args.shell, "-ec", blocks["Refresh persisted state before acquisition"]], runner, env)
        command = blocks["Run monitor and retain outcome"].replace(
            "sentinel run", f'"{Path(sys.executable).as_posix()}" -m civicdata_sentinel.cli run --input tests/fixtures/{fixture}')
        execute([args.shell, "-ec", command], runner, env)
        code = int((runner / "github-env").read_text().strip().split("=")[1])
        assert code == (1 if index == 3 else 0)
        execute([args.shell, "-ec", blocks["Save history and latest report in repository"]], runner, env)
        # The final workflow condition is evaluated by GitHub; emulate that branch.
        if code:
            execute([args.shell, "-ec", blocks["Fail workflow when ingestion failed"]], runner, env, expected=1)
        report = json.loads((runner / "reports/latest.json").read_text(encoding="utf-8"))
        with sqlite3.connect(runner / "state/sentinel.sqlite") as con:
            assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == index
            snapshot_count = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        if index == 1:
            assert report["stats"]["baseline"]
        if index == 2:
            assert (report["stats"]["added"], report["stats"]["removed"], report["stats"]["modified"]) == (1, 1, 1)
            baseline = report["digest"]
        if index == 3:
            assert report["status"] == "failed" and report["stats"] is None and report["events"] == []
            from civicdata_sentinel.storage import connect, load_previous
            with connect(runner / "state/sentinel.sqlite") as con:
                assert load_previous(con, "madrid_fountains")[0] == baseline
            assert snapshot_count == 2
        observed.append({"synthetic_input": fixture, "exit_code": code,
                         "status": report["status"], "stored_runs": index, "snapshots": snapshot_count})
    summary = {"kind": "local_workflow_simulation_synthetic_inputs", "observed": observed,
               "github_execution": False, "artifact_upload_tested": False,
               "shell_blocks_source": ".github/workflows/monitor.yml"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "execution-log.json").write_text(json.dumps(logs, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
