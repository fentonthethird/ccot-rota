"""Build the dashboard payload and encrypt it for the static site.

Envelope: JSON {v, kdf, iter, salt, iv, ct} with base64 fields. Key = PBKDF2-HMAC-SHA256(passphrase,
salt, iter) 32 bytes; ciphertext = AES-256-GCM(iv, payload JSON). docs/rota/index.html decrypts the
same envelope with WebCrypto.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import calendar as cal
from . import costing
from . import roster as R
from . import years as Y
from .store import Store

PBKDF2_ITER = 600000


def year_metrics(store: Store, label: str) -> Dict[str, Any]:
    y = store.year(label)
    ys, ye = cal.year_bounds(label)
    settings = store.settings()
    shifts = y.get("shifts", {})
    unfilled = set(y.get("unfilled", []))
    per_type: Dict[str, Dict[str, int]] = {}
    for t in (cal.WEEKDAY, cal.WEEKEND, cal.BH):
        per_type[t] = {"total": 0, "decided": 0, "filled": 0, "jp": 0, "locum": 0}
    for d in cal.daterange(ys, ye):
        t = cal.day_type(d)
        k = d.isoformat()
        per_type[t]["total"] += 1
        s = shifts.get(k)
        if s:
            per_type[t]["decided"] += 1
            per_type[t]["filled"] += 1
            if s["kind"] == Y.JP:
                per_type[t]["jp"] += 1
            else:
                per_type[t]["locum"] += 1
        elif k in unfilled:
            per_type[t]["decided"] += 1
    qw = qe = 0
    for c in R.consultants(store):
        a, b = R.quota(c, label)
        qw += a
        qe += b

    def rate(t: str) -> Optional[float]:
        p = per_type[t]
        return round(p["filled"] / p["decided"], 3) if p["decided"] else None

    def above(t: str) -> Optional[float]:
        p = per_type[t]
        denom = p["decided"] - p["jp"]
        return round(p["locum"] / denom, 3) if denom > 0 else None

    w = costing.wli(store, label)
    return {
        "jp_weekday_quota": qw, "jp_weekend_quota": qe, "jp_bank_holiday": 0,
        "budget": w["budget"],
        "weekday_fill_rate": rate(cal.WEEKDAY), "weekend_fill_rate": rate(cal.WEEKEND), "bank_holiday_fill_rate": rate(cal.BH),
        "weekday_fill_rate_above_jp": above(cal.WEEKDAY), "weekend_fill_rate_above_jp": above(cal.WEEKEND),
        "total_wli_bill": w["committed"], "wli": w, "per_type": per_type,
        "decided_through": max((k for k in list(shifts) + list(unfilled)), default=None),
    }


def build_payload(store: Store, label: str) -> Dict[str, Any]:
    y = store.year(label)
    counts = Y.counts(y)
    consultants = []
    for c in R.consultants(store):
        ini = c["initials"]
        qw, qe = R.quota(c, label)
        k = counts.get(ini, {"jp_weekday": 0, "jp_weekend": 0, "locum_weekday": 0, "locum_weekend": 0, "bh": 0, "total": 0})
        consultants.append({
            "initials": ini, "name": c["name"], "active": c.get("active", True),
            "quota": {"weekday": qw, "weekend": qe},
            "jp": {"weekday": k["jp_weekday"], "weekend": k["jp_weekend"]},
            "locum": {"weekday": k["locum_weekday"], "weekend": k["locum_weekend"], "bh": k["bh"], "total": k["locum_weekday"] + k["locum_weekend"] + k["bh"]},
            "complete": {"weekday": k["jp_weekday"] >= qw, "weekend": k["jp_weekend"] >= qe},
            "shifts": k["total"],
        })
    windows = []
    for wid in store.window_ids():
        w = store.window(wid)
        if w.get("year") == label:
            windows.append({"id": wid, "start": w["start"], "end": w["end"], "deadline": w.get("deadline"), "status": w.get("status")})
    changes = [e for e in y.get("log", []) if e.get("event") in ("swap", "override", "reclassify", "credit")]
    history = store.history().get("years", {})
    return {
        "version": 1, "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "year": label, "year_long": cal.year_label_long(label),
        "admin": store.settings().get("admin", {}),
        "consultants": consultants,
        "rota": {k: {"c": s["c"], "kind": s["kind"]} for k, s in sorted(y.get("shifts", {}).items())},
        "unfilled": sorted(y.get("unfilled", [])),
        "notes": y.get("notes", {}),
        "bank_holidays": {d.isoformat(): n for d, n in cal.BANK_HOLIDAYS.items() if cal.year_bounds(label)[0] <= d <= cal.year_bounds(label)[1]},
        "windows": windows,
        "changes": changes,
        "summary": {"current": year_metrics(store, label), "history": history},
    }


def derive_key(passphrase: str, salt: bytes, iterations: int = PBKDF2_ITER) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=32)


def encrypt(plaintext: bytes, passphrase: str) -> Dict[str, str]:
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(passphrase, salt)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(envelope: Dict[str, Any], passphrase: str) -> bytes:
    key = derive_key(passphrase, base64.b64decode(envelope["salt"]), int(envelope.get("iter", PBKDF2_ITER)))
    return AESGCM(key).decrypt(base64.b64decode(envelope["iv"]), base64.b64decode(envelope["ct"]), None)


def publish(store: Store, label: str, passphrase: str, out: Path, sw_path: Optional[Path] = None) -> Dict[str, Any]:
    payload = build_payload(store, label)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    env = encrypt(data, passphrase)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(env), encoding="utf-8")
    if sw_path and sw_path.exists():
        bump_service_worker(sw_path)
    return payload


def bump_service_worker(sw_path: Path) -> str:
    """Give the service worker a new version string so installed copies refresh."""
    text = sw_path.read_text(encoding="utf-8")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    new = re.sub(r"const VERSION = PREFIX \+ '[^']*';", "const VERSION = PREFIX + '%s';" % stamp, text, count=1)
    sw_path.write_text(new, encoding="utf-8")
    return stamp
