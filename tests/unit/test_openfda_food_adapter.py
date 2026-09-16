# tests/unit/test_openfda_food_adapter.py
import json
from datetime import datetime
from pathlib import Path

import pytest

from adapters.base import RawRecord
from adapters.openfda_food import OpenFDAFoodAdapter

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "openfda_food"


def load_fixture(name: str) -> RawRecord:
    payload = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    return RawRecord(source_id=payload["recall_number"], payload=payload)


@pytest.fixture
def adapter():
    return OpenFDAFoodAdapter()


def test_normalize_with_multiple_upcs(adapter):
    raw = load_fixture("H-1258-2026")
    result = adapter.normalize(raw)

    assert result.source_id == "H-1258-2026"
    assert result.brand == "H & U Inc. dba Sun Noodle"
    assert result.status == "terminated"
    assert result.hazard_classification == "Class I"
    assert result.date_initiated == datetime(2026, 8, 4)
    assert result.date_terminated == datetime(2026, 8, 27)
    assert sorted(result.upcs) == ["085315054105", "085315054108"]


def test_normalize_with_no_upc(adapter):
    raw = load_fixture("H-1219-2026")
    result = adapter.normalize(raw)

    assert result.source_id == "H-1219-2026"
    assert result.status == "ongoing"
    assert result.upcs == []
    assert result.date_terminated is None  # field absent in this record


def test_normalize_with_single_upc(adapter):
    raw = load_fixture("H-1259-2026")
    result = adapter.normalize(raw)

    assert result.upcs == ["6908791000053"]
    assert result.hazard_description == "Undeclared peanuts."