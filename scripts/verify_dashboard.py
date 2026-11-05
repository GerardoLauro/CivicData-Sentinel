"""Check Streamlit with an existing observed-live DB and a real HTTP server."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from streamlit.testing.v1 import AppTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    db = args.db.resolve()
    root = Path(__file__).resolve().parents[1]
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    app = AppTest.from_file(str(root / "dashboard/app.py"), default_timeout=20).run()
    app.sidebar.text_input[0].set_value(str(db)).run()
    assert not app.exception
    assert app.metric[0].value == "2" and len(app.dataframe[0].value) == 2
    assert not app.warning, "Network inputs must not be labelled synthetic/local"
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before, "Dashboard modified the DB"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
               "--server.headless=true", "--server.address=127.0.0.1",
               f"--server.port={port}", "--browser.gatherUsageStats=false"]
    log_path = args.output.with_suffix(".server.log")
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                        health = response.read().decode()
                        assert response.status == 200 and health == "ok"
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Streamlit server failed to become healthy")
                    time.sleep(0.25)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                assert response.status == 200 and "streamlit" in response.read().decode().lower()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    result = {"kind": "dashboard_verification", "apptest_live_history_rows": 2,
              "apptest_exceptions": 0, "database_unchanged": True,
              "server_health_http": 200, "frontend_http": 200,
              "browser_visual_review": False, "server_stopped_after_check": True}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
