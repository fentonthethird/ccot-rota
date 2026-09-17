"""Availability code: reference encoder and decoder.

Mirrors docs/codec.js exactly. The format is documented at the top of that file.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
EPOCH = dt.date(2024, 1, 1)
VERSION = 1
MAX_LEN = 511
HEADER_BITS = 4 + 15 + 14 + 9
_DASHES = "‐‑‒–—―−"


class CodeError(ValueError):
    """The code cannot be read. The message is written for the administrator."""


def day_number(d: dt.date) -> int:
    return (d - EPOCH).days


def date_from_day_number(n: int) -> dt.date:
    return EPOCH + dt.timedelta(days=n)


def pair_slots(start: dt.date, length: int) -> List[int]:
    """Indices of Saturdays whose Sunday is also inside the window."""
    return [i for i in range(length - 1) if (start + dt.timedelta(days=i)).weekday() == 5]


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _token_bytes(token: str) -> bytes:
    t = (token or "").strip().lower()
    if not re.fullmatch(r"([0-9a-f]{2})*", t):
        raise CodeError("token must be an even-length hex string")
    return bytes.fromhex(t)


def _bits_to_bytes(bits: Sequence[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        v = 0
        for j in range(8):
            v = (v << 1) | (bits[i + j] if i + j < len(bits) else 0)
        out.append(v)
    return bytes(out)


def _push(bits: List[int], value: int, n: int) -> None:
    bits.extend((value >> b) & 1 for b in range(n - 1, -1, -1))


def _read(bits: Sequence[int], pos: int, n: int) -> int:
    v = 0
    for i in range(n):
        v = v * 2 + bits[pos + i]
    return v


def normalise_body(s: str) -> str:
    s = re.sub(r"[^0-9A-Z]", "", s.upper())
    return s.replace("O", "0").replace("I", "1").replace("L", "1")


def split_code(code: str) -> Tuple[str, str]:
    """Return (prefix letters, raw body). The prefix is '' when there is no dash."""
    raw = re.sub("[%s]" % _DASHES, "-", str(code or "")).strip()
    if "-" in raw:
        prefix, _, body = raw.rpartition("-")
        return re.sub(r"[^A-Za-z]", "", prefix).upper(), body
    return "", raw


@dataclass
class Payload:
    initials: str
    start: dt.date
    length: int
    days: List[int]
    pairs: List[int]  # indices of flagged Saturdays
    version: int = VERSION

    @property
    def end(self) -> dt.date:
        return self.start + dt.timedelta(days=self.length - 1)

    @property
    def pair_slots(self) -> List[int]:
        return pair_slots(self.start, self.length)

    def available_dates(self) -> List[dt.date]:
        return [self.start + dt.timedelta(days=i) for i, v in enumerate(self.days) if v]

    def paired_saturdays(self) -> List[dt.date]:
        return [self.start + dt.timedelta(days=i) for i in self.pairs]


def encode(initials: str, start: dt.date, days: Sequence[int], pairs: Iterable[int] = (), token: str = "") -> str:
    ini = (initials or "").upper()
    if not re.fullmatch(r"[A-Z]{1,3}", ini):
        raise CodeError("initials must be 1 to 3 letters")
    length = len(days)
    if not 1 <= length <= MAX_LEN:
        raise CodeError("window length must be 1 to %d days" % MAX_LEN)
    sn = day_number(start)
    if not 0 <= sn < 16384:
        raise CodeError("window start out of range")
    slots = pair_slots(start, length)
    pairset = set(pairs)
    bad = pairset - set(slots)
    if bad:
        raise CodeError("pair flag %s is not a Saturday inside the window" % sorted(bad)[0])
    bits: List[int] = []
    _push(bits, VERSION, 4)
    for i in range(3):
        _push(bits, ord(ini[i]) - 64 if i < len(ini) else 0, 5)
    _push(bits, sn, 14)
    _push(bits, length, 9)
    bits.extend(1 if v else 0 for v in days)
    bits.extend(1 if s in pairset else 0 for s in slots)
    crc = crc16(_bits_to_bytes(bits) + _token_bytes(token))
    _push(bits, crc, 16)
    while len(bits) % 5:
        bits.append(0)
    body = "".join(ALPHABET[_read(bits, i, 5)] for i in range(0, len(bits), 5))
    return "%s-%s" % (ini, body)


def _header(code: str):
    prefix, raw = split_code(code)
    body = normalise_body(raw)
    if len(body) < -(-HEADER_BITS // 5):
        raise CodeError("code is too short to be valid")
    bits: List[int] = []
    for ch in body:
        v = ALPHABET.find(ch)
        if v < 0:
            raise CodeError("invalid character %r" % ch)
        _push(bits, v, 5)
    pos = 0
    version = _read(bits, pos, 4)
    pos += 4
    if version != VERSION:
        raise CodeError("unknown code version %d (expected %d)" % (version, VERSION))
    initials = ""
    for _ in range(3):
        v = _read(bits, pos, 5)
        pos += 5
        if v > 26:
            raise CodeError("corrupt code (initials)")
        if v:
            initials += chr(64 + v)
    if not initials:
        raise CodeError("corrupt code (no initials)")
    start = _read(bits, pos, 14)
    pos += 14
    length = _read(bits, pos, 9)
    pos += 9
    if length < 1:
        raise CodeError("corrupt code (window length is zero)")
    return prefix, body, bits, pos, initials, date_from_day_number(start), length


def peek_initials(code: str) -> str:
    """Initials carried inside the code, read without checking the checksum."""
    return _header(code)[4]


def decode(code: str, token: str = "") -> Payload:
    prefix, body, bits, pos, initials, start, length = _header(code)
    slots = pair_slots(start, length)
    total = pos + length + len(slots) + 16
    expect = -(-total // 5)
    if len(body) < expect:
        raise CodeError("code is truncated: expected %d characters after the dash but got %d" % (expect, len(body)))
    if len(body) > expect:
        raise CodeError("code is too long: expected %d characters after the dash but got %d" % (expect, len(body)))
    days = [bits[pos + i] for i in range(length)]
    pos += length
    pairs = []
    for s in slots:
        if bits[pos]:
            pairs.append(s)
        pos += 1
    crc = _read(bits, pos, 16)
    want = crc16(_bits_to_bytes(bits[:pos]) + _token_bytes(token))
    pos += 16
    if any(bits[pos:]):
        raise CodeError("corrupt code (padding)")
    if crc != want:
        raise CodeError("checksum failed: the code was damaged in transit or was made from a different link")
    if prefix and prefix != initials:
        raise CodeError("prefix %s does not match the initials inside the code (%s)" % (prefix, initials))
    return Payload(initials=initials, start=start, length=length, days=days, pairs=pairs)


_CODE_RE = re.compile(r"(?<![0-9A-Za-z])([A-Za-z]{1,3})\s*[-%s]\s*([0-9A-Za-z]{9,120})(?![0-9A-Za-z])" % _DASHES)


def extract_codes(text: str) -> List[str]:
    """Pull anything that looks like a code out of pasted messages."""
    return ["%s-%s" % (m.group(1).upper(), m.group(2)) for m in _CODE_RE.finditer(text or "")]
