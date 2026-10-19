"""Admin data lives in plain JSON files in one folder, outside the public repository."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DIR = Path.home() / "Documents" / "Claude" / "CCOT Rota App" / "CCOT Rota Data"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "admin": {"name": "Adam", "email": "a.woodman-bailey@nhs.net"},
    "site_url": "https://YOUR-GITHUB-USER.github.io/ccot-rota/",
    "rates": [
        {"effective": "2024-04-01", "weekday": {"hourly": 125, "hours": 12}, "weekend": {"hourly": 150, "hours": 10}}
    ],
    "budgets": {},
}


class Store:
    def __init__(self, root: Optional[os.PathLike] = None):
        self.root = Path(root or os.environ.get("CCOT_DATA") or DEFAULT_DIR).expanduser()

    # ---- files
    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def exists(self) -> bool:
        return self.path("settings.json").exists()

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "windows").mkdir(exist_ok=True)
        (self.root / "years").mkdir(exist_ok=True)
        if not self.path("settings.json").exists():
            self.save("settings.json", json.loads(json.dumps(DEFAULT_SETTINGS)))
        if not self.path("roster.json").exists():
            self.save("roster.json", {"consultants": []})
        if not self.path("history.json").exists():
            self.save("history.json", {"years": {}})

    def load(self, name: str, default: Any = None) -> Any:
        p = self.path(name)
        if not p.exists():
            if default is None:
                raise FileNotFoundError("missing %s in %s (run `ccot init` first?)" % (name, self.root))
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, name: str, obj: Any) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=False)
            f.write("\n")
        os.replace(tmp, p)

    # ---- typed accessors
    def settings(self) -> Dict[str, Any]:
        return self.load("settings.json")

    def save_settings(self, s: Dict[str, Any]) -> None:
        self.save("settings.json", s)

    def roster(self) -> Dict[str, Any]:
        return self.load("roster.json")

    def save_roster(self, r: Dict[str, Any]) -> None:
        self.save("roster.json", r)

    def window_ids(self) -> List[str]:
        d = self.path("windows")
        return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []

    def window(self, wid: str) -> Dict[str, Any]:
        p = "windows/%s.json" % wid
        if not self.path(p).exists():
            raise FileNotFoundError("no window called %r (known: %s)" % (wid, ", ".join(self.window_ids()) or "none"))
        return self.load(p)

    def save_window(self, w: Dict[str, Any]) -> None:
        self.save("windows/%s.json" % w["id"], w)

    def year_labels(self) -> List[str]:
        d = self.path("years")
        return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []

    def year(self, label: str) -> Dict[str, Any]:
        return self.load("years/%s.json" % label, {"year": label, "shifts": {}, "unfilled": [], "log": [], "allocated_windows": []})

    def save_year(self, y: Dict[str, Any]) -> None:
        self.save("years/%s.json" % y["year"], y)

    def history(self) -> Dict[str, Any]:
        return self.load("history.json", {"years": {}})

    def save_history(self, h: Dict[str, Any]) -> None:
        self.save("history.json", h)
