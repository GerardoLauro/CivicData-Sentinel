"""Persist portable, integrity-checked state on a dedicated Git branch.

No working-tree switch or force push. A rejected concurrent update fails closed.
Only run against a remote you intend to update. Automated tests use LOCAL remotes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from civicdata_sentinel.storage import backup, integrity, readonly

BRANCH = "refs/heads/sentinel-state"
MAX_STATE_BYTES = 250_000_000


def git(repo, *args, data=None, env=None):
    result = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def remote_head(repo):
    output = git(repo, "ls-remote", "--heads", "origin", BRANCH).decode().strip()
    return output.split()[0] if output else ""


def restore(repo, db):
    if db.exists():
        raise ValueError("Refusing to overwrite an existing local history database")
    head = remote_head(repo)
    (repo / ".sentinel-state-parent").write_text(head, encoding="ascii")
    if not head:
        return {"restored": False, "reason": "state branch does not exist; first acquisition"}
    git(repo, "fetch", "--depth=1", "origin", BRANCH)
    if git(repo, "rev-parse", "FETCH_HEAD").decode().strip() != head:
        raise ValueError("State changed during restore; retry without starting a new baseline")
    manifest = json.loads(git(repo, "show", "FETCH_HEAD:state/manifest.json"))
    packed = git(repo, "show", "FETCH_HEAD:state/history.sqlite.gz")
    if hashlib.sha256(packed).hexdigest() != manifest["compressed_sha256"]:
        raise ValueError("Downloaded state archive hash mismatch")
    import io

    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        content = stream.read(MAX_STATE_BYTES + 1)
    if len(content) > MAX_STATE_BYTES or hashlib.sha256(content).hexdigest() != manifest["database_sha256"]:
        raise ValueError("Downloaded state database hash/size mismatch")
    db.parent.mkdir(parents=True, exist_ok=True)
    temporary = db.with_suffix(".restore.tmp")
    try:
        temporary.write_bytes(content)
        with readonly(temporary) as con:
            result = integrity(con)
        if not result["ok"]:
            raise ValueError("Restored state failed internal integrity checks")
        os.replace(temporary, db)
    finally:
        temporary.unlink(missing_ok=True)
    return {"restored": True, "source_commit": head, "runs": result["runs"]}


def persist(repo, db):
    marker = repo / ".sentinel-state-parent"
    if not marker.is_file():
        raise ValueError("Restore must run before persist, even for an empty remote")
    parent = marker.read_text(encoding="ascii").strip()
    if remote_head(repo) != parent:
        raise ValueError("State branch changed after restore; refusing to overwrite newer history")
    with tempfile.TemporaryDirectory(prefix=".sentinel-op-", dir=repo) as directory:
        temporary = Path(directory)
        if not temporary.resolve().is_relative_to(repo.resolve()):
            raise ValueError("Temporary state directory escaped repository")
        portable = temporary / "history.sqlite"
        backup(db, portable)
        with readonly(portable) as con:
            result = integrity(con)
        if not result["ok"]:
            raise ValueError("Refusing to persist inconsistent history")
        if portable.stat().st_size > MAX_STATE_BYTES:
            raise ValueError("State exceeds the 250 MB MVP limit; move to external storage")
        content = portable.read_bytes()
    packed = gzip.compress(content, mtime=0)
    manifest = {
        "schema_version": 2,
        "runs": result["runs"],
        "database_sha256": hashlib.sha256(content).hexdigest(),
        "compressed_sha256": hashlib.sha256(packed).hexdigest(),
    }

    def blob(content):
        return git(repo, "hash-object", "-w", "--stdin", data=content).decode().strip()

    data_blob = blob(packed)
    meta_blob = blob((json.dumps(manifest, indent=2) + "\n").encode())
    state_tree = (
        git(
            repo,
            "mktree",
            data=f"100644 blob {data_blob}\thistory.sqlite.gz\n100644 blob {meta_blob}\tmanifest.json\n".encode(),
        )
        .decode()
        .strip()
    )
    tree = git(repo, "mktree", data=f"040000 tree {state_tree}\tstate\n".encode()).decode().strip()
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="CivicData Sentinel",
        GIT_AUTHOR_EMAIL="sentinel@example.invalid",
        GIT_COMMITTER_NAME="CivicData Sentinel",
        GIT_COMMITTER_EMAIL="sentinel@example.invalid",
    )
    args = ["commit-tree", tree, *(["-p", parent] if parent else [])]
    commit = (
        git(repo, *args, data=f"state: retain {result['runs']} monitoring attempts\n".encode(), env=env)
        .decode()
        .strip()
    )
    # The parent is the restored commit; ordinary push rejects concurrent writers.
    git(repo, "push", "origin", f"{commit}:{BRANCH}")
    marker.write_text(commit, encoding="ascii")
    return {"persisted": True, "commit": commit, "runs": result["runs"]}


def assert_public_state(db):
    """Deployment gate: never publish local/demo/private-contract history."""
    with readonly(db) as con:
        rows = con.execute("SELECT report_json FROM runs").fetchall()
    for (text,) in rows:
        report = json.loads(text)
        contract = report.get("config", {})
        if report.get("source", {}).get("input_kind") != "network":
            raise ValueError("Public state must contain network acquisitions only")
        if not contract.get("license", "").startswith("CC BY 4.0"):
            raise ValueError("Public state requires reviewed CC BY 4.0 contracts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["restore", "persist"])
    parser.add_argument(
        "--public-state", action="store_true", help="Require reviewed public-only state before persistence"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path, default=Path("state/sentinel.sqlite"))
    args = parser.parse_args()
    repo = args.repo.resolve()
    db = (args.db if args.db.is_absolute() else repo / args.db).resolve()
    if args.operation == "persist" and args.public_state:
        assert_public_state(db)
    print(json.dumps(restore(repo, db) if args.operation == "restore" else persist(repo, db), indent=2))
