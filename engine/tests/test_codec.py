import json
import random
import subprocess
import datetime as dt

import pytest

from ccot import codec
from conftest import DOCS, JSC


def make(seed=0, start=dt.date(2027, 1, 1), length=90, initials="AWB", token="7f3a9c"):
    rnd = random.Random(seed)
    days = [1 if rnd.random() < 0.4 else 0 for _ in range(length)]
    slots = codec.pair_slots(start, length)
    pairs = [s for s in slots if days[s] and days[s + 1] and rnd.random() < 0.5]
    return dict(initials=initials, start=start, days=days, pairs=pairs, token=token)


def test_round_trip_many_seeds():
    for seed in range(60):
        v = make(seed, length=1 + seed * 7 % 400, initials=random.Random(seed).choice(["A", "AW", "AWB", "LDC", "ZZZ"]))
        code = codec.encode(**v)
        p = codec.decode(code, v["token"])
        assert p.initials == v["initials"]
        assert p.start == v["start"] and p.length == len(v["days"])
        assert p.days == v["days"]
        assert p.pairs == v["pairs"]


def test_quarter_code_is_short():
    code = codec.encode(**make(length=92), max_shifts=6)
    prefix, body = code.split("-")
    assert prefix == "AWB" and len(body) == 35 and len(code) == 39  # 92 days with a limit; 90 days gives 38
    year = codec.encode(**make(length=365, start=dt.date(2026, 4, 1)))
    assert len(year) <= 105  # a whole year still fits in a message


def test_decode_is_forgiving_about_case_spacing_and_lookalikes():
    v = make(3)
    code = codec.encode(**v)
    prefix, body = code.split("-")
    messy = prefix.lower() + " – " + " ".join(body[i:i + 4] for i in range(0, len(body), 4)).lower().replace("0", "o").replace("1", "l")
    assert codec.decode(messy, v["token"]).days == v["days"]
    assert codec.decode(body, v["token"]).initials == "AWB"  # bare body without the prefix


def test_truncated_code_is_rejected():
    code = codec.encode(**make(4))
    for cut in (1, 2, 5, 10):
        with pytest.raises(codec.CodeError, match="truncated|too short"):
            codec.decode(code[:-cut], "7f3a9c")


def test_every_single_character_corruption_is_detected():
    v = make(5)
    code = codec.encode(**v)
    prefix, body = code.split("-")
    for i in range(len(body)):
        for repl in codec.ALPHABET[:3]:
            if repl == body[i]:
                continue
            bad = prefix + "-" + body[:i] + repl + body[i + 1:]
            with pytest.raises(codec.CodeError):
                codec.decode(bad, v["token"])


def test_wrong_token_and_wrong_prefix():
    v = make(6)
    code = codec.encode(**v)
    with pytest.raises(codec.CodeError, match="checksum"):
        codec.decode(code, "000000")
    with pytest.raises(codec.CodeError, match="prefix"):
        codec.decode("XW-" + code.split("-")[1], v["token"])
    assert codec.peek_initials(code) == "AWB"


def test_extract_codes_from_pasted_messages():
    a = codec.encode(**make(7, initials="AW"))
    b = codec.encode(**make(8, initials="JPL"))
    text = "Hi Adam, here's mine: %s thanks!\n\nAnd James says %s.\nSent from my iPhone" % (a, b)
    assert codec.extract_codes(text) == [a, b]


def test_pair_slots_only_include_saturdays_with_a_sunday_inside():
    start = dt.date(2027, 1, 1)  # Friday
    slots = codec.pair_slots(start, 90)
    assert slots[0] == 1 and all((start + dt.timedelta(days=s)).weekday() == 5 for s in slots)
    assert codec.pair_slots(dt.date(2027, 1, 2), 1) == []  # a lone Saturday has no pair


@pytest.mark.skipif(not JSC.exists(), reason="JavaScriptCore not available")
def test_javascript_encoder_and_decoder_match_python(tmp_path):
    vectors = []
    for seed in range(25):
        v = make(seed, length=(seed * 13) % 200 + 1, start=dt.date(2026, 4, 1) + dt.timedelta(days=seed * 11), initials=["AW", "AWB", "Q"][seed % 3], token=["7f3a9c", "", "00ff"][seed % 3])
        mx = [None, 4, 90][seed % 3]
        vectors.append({"initials": v["initials"], "start": v["start"].isoformat(), "len": len(v["days"]), "days": v["days"], "pairs": v["pairs"], "token": v["token"], "max": mx, "python": codec.encode(**v, max_shifts=mx)})
    js = """
load(%r);
const C = globalThis.CCOTCodec;
const vectors = %s;
const out = [];
for (const v of vectors) {
  const code = C.encode({ initials: v.initials, start: v.start, len: v.len, days: v.days, pairs: v.pairs, max: v.max, token: v.token });
  const d = C.decode(v.python, { token: v.token });
  let err = null;
  try { C.decode(v.python.slice(0, -2), { token: v.token }); } catch (e) { err = e.message; }
  let err2 = null;
  try { C.decode(v.python, { token: 'abcd' }); } catch (e) { err2 = e.message; }
  out.push({ js: code, days: d.days, pairs: d.pairs, initials: d.initials, start: d.start, max: d.max, truncated: err, wrongToken: err2 });
}
print(JSON.stringify(out));
""" % (str(DOCS / "codec.js"), json.dumps(vectors))
    script = tmp_path / "t.js"
    script.write_text(js)
    res = subprocess.run([str(JSC), str(script)], capture_output=True, text=True, check=True)
    out = json.loads(res.stdout.strip().splitlines()[-1])
    for v, o in zip(vectors, out):
        assert o["js"] == v["python"], "JS and Python encoders differ for %s" % v
        assert o["days"] == v["days"] and o["pairs"] == v["pairs"] and o["initials"] == v["initials"] and o["start"] == v["start"]
        assert o["max"] == v["max"]
        assert "truncated" in (o["truncated"] or "") or "too short" in (o["truncated"] or "")
        if v["token"] != "abcd":
            assert "checksum" in (o["wrongToken"] or "")


def test_most_shifts_wanted_round_trips_and_blank_means_no_limit():
    v = make(11)
    assert codec.decode(codec.encode(**v), v["token"]).max_shifts is None
    for mx in (1, 6, 90, codec.MAX_LEN):
        p = codec.decode(codec.encode(**v, max_shifts=mx), v["token"])
        assert p.max_shifts == mx and p.days == v["days"] and p.pairs == v["pairs"]
    with pytest.raises(codec.CodeError):
        codec.encode(**v, max_shifts=codec.MAX_LEN + 1)


def test_version_1_codes_are_still_read():
    # Made on the live site in September 2026, before the limit existed.
    p = codec.decode("AWB-23E4490PGRR000000000000000000Q360", "715268")
    assert p.version == 1 and p.max_shifts is None
    assert [d.isoformat() for d in p.available_dates()] == ["2027-01-04", "2027-01-05", "2027-01-09", "2027-01-10"]
    with pytest.raises(codec.CodeError):
        codec.decode("AWB-23E4490PGRR000000000000000000Q361", "715268")


def test_a_corrupted_limit_is_detected():
    v = make(12)
    code = codec.encode(**v, max_shifts=6)
    prefix, body = code.split("-")
    # characters 9-10 of the body carry the limit bits
    for i in (8, 9, 10):
        bad = prefix + "-" + body[:i] + ("2" if body[i] != "2" else "3") + body[i + 1:]
        with pytest.raises(codec.CodeError):
            codec.decode(bad, v["token"])
