"""Exercise the actual state-branch protocol with fresh LOCAL runner clones.

All monitoring input is synthetic. No GitHub service, account or token is used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

from civicdata_sentinel.monitor import run
from civicdata_sentinel.storage import integrity, load_previous, readonly


def verify(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("state_branch", root / "scripts/state_branch.py")
    state = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(state)
    log = []

    def git(*args, cwd):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        log.append(
            {"args": list(args), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    with tempfile.TemporaryDirectory(prefix=".runner-test-", dir=output) as folder:
        work = Path(folder)
        assert work.is_relative_to(output)
        remote, seed = work / "remote.git", work / "seed"
        git("init", "--bare", "--initial-branch=main", str(remote), cwd=work)
        seed.mkdir()
        git("init", "--initial-branch=main", cwd=seed)
        git(
            "-c",
            "user.name=Local verification",
            "-c",
            "user.email=local@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "Synthetic runner test",
            cwd=seed,
        )
        git("remote", "add", "origin", str(remote), cwd=seed)
        git("push", "-u", "origin", "main", cwd=seed)
        initial = git("rev-parse", "HEAD", cwd=seed)
        observed, previous = [], None
        for index, fixture in enumerate(("fountains_base.csv", "fountains_changed.csv", "fountains_invalid.csv"), 1):
            runner = work / f"runner-{index}"
            git("clone", str(remote), str(runner), cwd=work)
            db = runner / "state/sentinel.sqlite"
            restored = state.restore(runner, db)
            report = run(root / "configs/madrid_fountains.yaml", db, input_file=root / "tests/fixtures" / fixture)
            if index < 3:
                assert report["status"] == "success"
                previous = report["digest"]
            else:
                assert report["status"] == "failed" and report["events"] == []
            saved = state.persist(runner, db)
            with readonly(db) as con:
                assert integrity(con)["ok"]
                assert load_previous(con, "madrid_fountains")[0] == previous
                count = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                assert count == index
            observed.append(
                {
                    "synthetic_input": fixture,
                    "status": report["status"],
                    "restored": restored["restored"],
                    "runs": count,
                    "persisted": saved["persisted"],
                }
            )
            assert git("rev-parse", "HEAD", cwd=runner) == initial
        # Runner 2 has a stale parent marker after runner 3 pushed its state.
        try:
            state.persist(work / "runner-2", work / "runner-2/state/sentinel.sqlite")
        except ValueError:
            rejected = True
        else:
            rejected = False
        assert rejected
        assert git("ls-remote", "--heads", "origin", "refs/heads/main", cwd=seed).split()[0] == initial
    result = {
        "kind": "synthetic_local_state_branch_integration",
        "observed": observed,
        "source_branch_unchanged": True,
        "concurrent_update_rejected": rejected,
        "github_hosted": False,
        "artifact_upload_tested": False,
        "temporary_clones_removed": True,
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    # Relative Git arguments only; no tokens or account metadata are queried.
    (output / "git-log.json").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), indent=2))
