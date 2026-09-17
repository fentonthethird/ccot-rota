import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccot.store import Store  # noqa: E402
from ccot import roster as R  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc")
REAL_WORKBOOK = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Downloads/Outreach Cons Rota v2.xlsx"


@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path / "data")
    st.init()
    s = st.settings()
    s["site_url"] = "https://example.github.io/ccot-rota/"
    st.save_settings(s)
    return st


def add_people(st, spec, year="2026-27"):
    """spec: {initials: (name, weekday quota, weekend quota)}"""
    for ini, (name, qw, qe) in spec.items():
        R.add(st, ini, name, year=year, weekday=qw, weekend=qe)


def D(s):
    return dt.date.fromisoformat(s)
