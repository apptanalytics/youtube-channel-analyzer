"""Unit tests for apify_channel_analyzer.

These exercise the pure-Python helpers that don't need network or the Apify SDK.
The YouTube API call path is not unit-tested here — it would require either
mocking googleapiclient.discovery.build or hitting the real API, and neither
belongs in a fast unit test loop.

Runs under pytest (preferred) or via `python run_tests.py` from the project
root when pytest isn't installed.
"""
try:
    import pytest
except ImportError:  # pragma: no cover - standalone runner path
    pytest = None


# --- normalize_channel_input -----------------------------------------------

NORMALIZE_CASES = [
    # (input, expected_kind, expected_value)
    # IDs (24 chars: "UC" + 22 of [A-Za-z0-9_-])
    ("UC-3IZKseVpdzPSBaWxBxundA", "id", "UC-3IZKseVpdzPSBaWxBxundA"),
    ("UC_x" + "x" * 20, "id", "UC_x" + "x" * 20),  # exactly 24 chars
    # Bare handles
    ("@MrBeast", "handle", "mrbeast"),
    ("mrbeast", "handle", "mrbeast"),
    ("MrBeast", "handle", "mrbeast"),
    ("@MrBeast  ", "handle", "mrbeast"),
    ("@mr_beast_2024", "handle", "mr_beast_2024"),
    ("@Mr.Beast", "handle", "mr.beast"),
    # URLs
    ("https://www.youtube.com/@MrBeast", "handle", "mrbeast"),
    ("https://www.youtube.com/channel/UC-3IZKseVpdzPSBaWxBxundA", "id", "UC-3IZKseVpdzPSBaWxBxundA"),
    ("https://youtube.com/c/MrBeastCustom", "handle", "mrbeastcustom"),
    ("https://youtu.be/@SomeHandle", "handle", "somehandle"),  # youtu.be is YouTube-owned
]


NORMALIZE_REJECT_CASES = [
    ("  ", "channelId is required"),
    ("", "channelId is required"),
    (None, "channelId is required"),
    ("not a channel", "Invalid channel input"),
    ("https://evil.com/@foo", "Not a YouTube URL"),
    ("UC_tooshort", "wrong length"),  # ID prefix but not the right shape
    ("@a", "Invalid channel input"),  # handle too short
]


@pytest.mark.parametrize("raw,exp_kind,exp_val", NORMALIZE_CASES)
def test_normalize_channel_input_accepts(analyzer, raw, exp_kind, exp_val):
    kind, val = analyzer.normalize_channel_input(raw)
    assert (kind, val) == (exp_kind, exp_val)


@pytest.mark.parametrize("raw,needle", NORMALIZE_REJECT_CASES)
def test_normalize_channel_input_rejects(analyzer, raw, needle):
    with pytest.raises(ValueError, match=needle):
        analyzer.normalize_channel_input(raw)


# --- parse_duration ---------------------------------------------------------

PARSE_DURATION_CASES = [
    ("PT4M30S", 270),
    ("PT1H2M3S", 3723),
    ("PT10S", 10),
    ("PT45M", 45 * 60),
    ("PT0S", 0),
    ("", 0),
    (None, 0),
    ("garbage", 0),
]


@pytest.mark.parametrize("iso,seconds", PARSE_DURATION_CASES)
def test_parse_duration(analyzer, iso, seconds):
    assert analyzer.parse_duration(iso) == seconds


# --- format_duration --------------------------------------------------------

FORMAT_DURATION_CASES = [
    (270, "04:30"),
    (3723, "01:02:03"),
    (0, "00:00"),
    (59, "00:59"),
    (60, "01:00"),
    (3600, "01:00:00"),
]


@pytest.mark.parametrize("seconds,formatted", FORMAT_DURATION_CASES)
def test_format_duration(analyzer, seconds, formatted):
    assert analyzer.format_duration(seconds) == formatted


# --- calculate_engagement_rate ----------------------------------------------

ENGAGEMENT_CASES = [
    (1000, 30, 20, 5.0),  # (30+20)/1000 * 100
    (0, 1, 1, 0),  # zero views
    (None, 1, 1, 0),  # None views
    (100, None, None, 0.0),  # None likes/comments
    (1000, 0, 0, 0.0),  # zero likes/comments
    (1_000_000, 45000, 12000, 5.7),  # README example
]


@pytest.mark.parametrize("views,likes,comments,expected", ENGAGEMENT_CASES)
def test_calculate_engagement_rate(analyzer, views, likes, comments, expected):
    assert analyzer.calculate_engagement_rate(views, likes, comments) == expected
