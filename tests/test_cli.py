import json

from civicdata_sentinel.cli import main


def test_cli_audit_export_replay_and_failures(tmp_path, contract, csv_file, capsys):
    db, output = tmp_path / "state.sqlite", tmp_path / "latest.json"
    cfg = contract()

    def call(*args, expected=0):
        result = main(list(args))
        captured = capsys.readouterr()
        assert result == expected, captured.err
        return json.loads(captured.out) if captured.out else None

    a = call(
        "run",
        "--config",
        str(cfg),
        "--input",
        str(csv_file([{"ID": "1", "v": "a"}])),
        "--db",
        str(db),
        "--output",
        str(output),
    )
    b = call(
        "run",
        "--config",
        str(cfg),
        "--input",
        str(csv_file([{"ID": "1", "v": "b"}])),
        "--db",
        str(db),
        "--output",
        str(output),
    )
    common = ["--db", str(db)]
    assert len(call("history", *common, "--dataset", "synthetic")) == 2
    assert call("show", *common, "--run", str(b["run_id"]))["run_id"] == b["run_id"]
    assert call("replay", *common, "--run", str(b["run_id"]))["reproduced"]
    assert call("verify", *common)["ok"]
    assert call("diff", *common, "--before", str(a["run_id"]), "--after", str(b["run_id"]))["stats"]["modified"] == 1
    for format in ("json", "csv", "jsonl"):
        path = tmp_path / ("export." + format)
        assert (
            call("export", *common, "--run", str(b["run_id"]), "--format", format, "--output", str(path))[
                "events_exported"
            ]
            == 1
        )
        assert path.is_file()
    assert call("incidents", *common) == [] and call("alerts", *common) == []
    assert call("backup", *common, "--output", str(tmp_path / "backup.sqlite"))["bytes"] > 0
    assert call("migrate", *common)["schema_version"] == 2
    call("history", *common, "--limit", "0", expected=1)
    call("show", *common, "--run", "999", expected=1)
    call("approve", *common, "--run", str(b["run_id"]), "--reason", "Not a quarantined run", expected=1)


def test_run_all_validates_catalog_and_continues_failed_source(tmp_path, contract, monkeypatch):
    import civicdata_sentinel.monitor as monitor
    from civicdata_sentinel.monitor import run_catalog

    cfg = contract(dataset_id="a")
    contract(dataset_id="b")

    def fetch(config):
        if config["dataset_id"] == "a":
            from civicdata_sentinel.ingestion import IngestionError

            raise IngestionError("synthetic source failure")
        return b"ID\n1\n", {}

    monkeypatch.setattr(monitor, "fetch_csv", fetch)
    report = run_catalog(cfg.parent, tmp_path / "state.sqlite", tmp_path / "reports")
    assert report["total"] == 2 and report["successful"] == 1
    assert {r["status"] for r in report["datasets"]} == {"failed", "success"}


def test_cli_catalog_schema_and_quarantine_exit_codes(tmp_path, contract, csv_file, capsys):
    cfg = contract()
    assert main(["catalog", "--configs", str(cfg.parent)]) == 0
    assert main(["config-schema", "--output", str(tmp_path / "schema.json")]) == 0
    db, report = tmp_path / "state.sqlite", tmp_path / "r.json"
    args = ["run", "--config", str(cfg), "--db", str(db), "--output", str(report)]
    assert main([*args, "--input", str(csv_file([{"ID": "1"}, {"ID": "2"}]))]) == 0
    assert main([*args, "--input", str(csv_file([{"ID": "1"}]))]) == 2
    candidate = json.loads(report.read_text())["run_id"]
    assert (
        main(
            [
                "approve",
                "--db",
                str(db),
                "--run",
                str(candidate),
                "--reason",
                "Confirmed intentional synthetic deletion",
            ]
        )
        == 0
    )
    assert main([*args, "--input", str(csv_file([], ["ID"]))]) == 1
    rule = contract(checks=[{"id": "domain", "kind": "domain", "column": "v", "values": ["ok"]}])
    assert (
        main(
            [*args, "--config", str(rule), "--input", str(csv_file([{"ID": "1", "v": "bad"}])), "--fail-on", "warning"]
        )
        == 3
    )
