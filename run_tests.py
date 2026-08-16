"""Standalone test runner. Works without pytest (just prints pass/fail per case).
Use `python -m pytest tests/` once pytest is available in the project env."""
import sys
import traceback
from pathlib import Path

# Ensure the tests dir is on path so we can import the conftest (which installs stubs)
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
import conftest  # installs apify + googleapiclient stubs

analyzer = conftest._load_analyzer()
nc = analyzer.normalize_channel_input
pd_ = analyzer.parse_duration
fd = analyzer.format_duration
cer = analyzer.calculate_engagement_rate

passed = 0
failed = 0
errors = []


def case(label, fn):
    global passed, failed
    try:
        fn()
        print(f"  PASS  {label}")
        passed += 1
    except AssertionError as e:
        print(f"  FAIL  {label}: {e}")
        failed += 1
        errors.append((label, traceback.format_exc()))
    except Exception:
        print(f"  ERROR {label}")
        failed += 1
        errors.append((label, traceback.format_exc()))


print("== normalize_channel_input (accepts) ==")
for raw, exp_kind, exp_val in [
    ("UC-3IZKseVpdzPSBaWxBxundA", "id", "UC-3IZKseVpdzPSBaWxBxundA"),
    ("UC_x" + "x" * 20, "id", "UC_x" + "x" * 20),
    ("@MrBeast", "handle", "mrbeast"),
    ("mrbeast", "handle", "mrbeast"),
    ("MrBeast", "handle", "mrbeast"),
    ("@MrBeast  ", "handle", "mrbeast"),
    ("@mr_beast_2024", "handle", "mr_beast_2024"),
    ("@Mr.Beast", "handle", "mr.beast"),
    ("https://www.youtube.com/@MrBeast", "handle", "mrbeast"),
    ("https://www.youtube.com/channel/UC-3IZKseVpdzPSBaWxBxundA", "id", "UC-3IZKseVpdzPSBaWxBxundA"),
    ("https://youtube.com/c/MrBeastCustom", "handle", "mrbeastcustom"),
    ("https://youtu.be/@SomeHandle", "handle", "somehandle"),
]:
    case(
        f"normalize({raw!r}) == ({exp_kind!r}, {exp_val!r})",
        lambda r=raw, k=exp_kind, v=exp_val: (lambda got: (got == (k, v) or (_ for _ in ()).throw(AssertionError(f"got {got}"))))(nc(r)),
    )

print()
print("== normalize_channel_input (rejects) ==")
for raw, needle in [
    ("  ", "channelId is required"),
    ("", "channelId is required"),
    (None, "channelId is required"),
    ("not a channel", "Invalid channel input"),
    ("https://evil.com/@foo", "Not a YouTube URL"),
    ("UC_tooshort", "wrong length"),
    ("@a", "Invalid channel input"),
]:
    def rejects(r=raw, n=needle):
        try:
            got = nc(r)
        except ValueError as e:
            assert n in str(e), f"expected needle {n!r} in {str(e)!r}"
            return
        raise AssertionError(f"expected ValueError, got ({got!r})")
    case(f"normalize({raw!r}) raises containing {needle!r}", rejects)

print()
print("== parse_duration ==")
for iso, seconds in [
    ("PT4M30S", 270),
    ("PT1H2M3S", 3723),
    ("PT10S", 10),
    ("PT45M", 45 * 60),
    ("PT0S", 0),
    ("", 0),
    (None, 0),
    ("garbage", 0),
]:
    case(
        f"parse_duration({iso!r}) == {seconds}",
        lambda i=iso, s=seconds: (pd_(i) == s or (_ for _ in ()).throw(AssertionError(f"got {pd_(i)}"))),
    )

print()
print("== format_duration ==")
for seconds, formatted in [
    (270, "04:30"),
    (3723, "01:02:03"),
    (0, "00:00"),
    (59, "00:59"),
    (60, "01:00"),
    (3600, "01:00:00"),
]:
    case(
        f"format_duration({seconds}) == {formatted!r}",
        lambda s=seconds, f=formatted: (fd(s) == f or (_ for _ in ()).throw(AssertionError(f"got {fd(s)!r}"))),
    )

print()
print("== calculate_engagement_rate ==")
for views, likes, comments, expected in [
    (1000, 30, 20, 5.0),
    (0, 1, 1, 0),
    (None, 1, 1, 0),
    (100, None, None, 0.0),
    (1000, 0, 0, 0.0),
    (1_000_000, 45000, 12000, 5.7),
]:
    case(
        f"engagement({views},{likes},{comments}) == {expected}",
        lambda v=views, l=likes, c=comments, e=expected: (cer(v, l, c) == e or (_ for _ in ()).throw(AssertionError(f"got {cer(v,l,c)}"))),
    )

print()
print(f"== {passed} passed, {failed} failed ==")
if failed:
    print()
    print("--- failures ---")
    for label, tb in errors:
        print(label)
        print(tb)
sys.exit(1 if failed else 0)
