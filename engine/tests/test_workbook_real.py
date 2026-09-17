"""Reads the real workbook when it is present on this machine; skipped elsewhere."""
import pytest

from ccot import xlsx_import
from conftest import REAL_WORKBOOK

pytestmark = pytest.mark.skipif(not REAL_WORKBOOK.exists(), reason="real workbook not present")


def test_2026_27_sheet_matches_the_hand_count():
    data = xlsx_import.read_workbook(str(REAL_WORKBOOK), "2026-27")
    cs = data["consultants"]
    assert len(cs) == 19
    assert sum(c["weekday"] or 0 for c in cs) == 175 and sum(c["weekend"] or 0 for c in cs) == 32
    assert {c["initials"]: (c["weekday"], c["weekend"]) for c in cs}["LDC"] == (None, None)
    kinds = {}
    for k, s in data["shifts"].items():
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    assert kinds == {"JP": 152 + 27, "LOCUM": 35 + 50, "BH": 6}
    assert data["unfilled"] == ["2026-05-27", "2026-12-24", "2026-12-25", "2026-12-26", "2026-12-31"]
    assert data["decided_through"] == "2026-12-31"
    assert data["counts"]["AWB"]["bh"] == 2 and data["counts"]["SA"]["locum_weekend"] == 8
    assert any("SA has 8 green (locum) weekend shifts" in a for a in data["anomalies"])
    assert data["notes"]["2026-04-06"].startswith("DL both IA")
    hist = data["history"]
    assert hist["2025-26"]["total_wli_bill"] == 198000 and hist["2024-25"]["weekend_fill_rate"] == 0.85 and hist["2023-24"]["weekend_fill_rate"] == 0.46
    assert hist["2025-26"]["budget"] == 202500


def test_2025_26_sheet_parses_with_the_same_reader():
    data = xlsx_import.read_workbook(str(REAL_WORKBOOK), "2025-26")
    assert len(data["shifts"]) == 363
    assert sum(1 for s in data["shifts"].values() if s["kind"] == "LOCUM") == 133
    assert sum(1 for s in data["shifts"].values() if s["kind"] == "BH") == 8
