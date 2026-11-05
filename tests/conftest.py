"""All generated inputs in this suite are fictional and kept in temporary folders."""

import csv

import pytest
import yaml


@pytest.fixture
def contract(tmp_path):
    def make(**overrides):
        cfg = {
            "dataset_id": "synthetic",
            "primary_key": "ID",
            "source": {"type": "url", "url": "https://example.org/data.csv"},
            **overrides,
        }
        path = tmp_path / f"contract-{len(list(tmp_path.glob('contract*')))}.yaml"
        path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        return path

    return make


@pytest.fixture
def csv_file(tmp_path):
    def make(rows, fields=None):
        path = tmp_path / f"input-{len(list(tmp_path.glob('input*')))}.csv"
        fields = fields or list(rows[0])
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    return make
