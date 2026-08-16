"""Test config: stub out apify + googleapiclient so the analyzer can be imported
without installing the full dependency tree (the Apify SDK is only meaningful inside
the actor runtime, not on a CI box running unit tests)."""
import sys
import types

# `pytest.fixture` is only meaningful when pytest is running this file. The
# standalone test runner in run_tests.py imports this module to install the
# stubs but doesn't use the fixture, so make the decorator a no-op when pytest
# isn't installed.
try:
    import pytest
except ImportError:  # pragma: no cover - standalone runner path
    class _NoOpFixture:
        def __call__(self, *args, **kwargs):
            # Mimic pytest.fixture(...)(fn) when used as a decorator factory
            if args and callable(args[0]) and not kwargs:
                return args[0]
            def deco(fn):
                return fn
            return deco

    class _PytestStub:
        fixture = staticmethod(_NoOpFixture())

    pytest = _PytestStub()


def _make_apify_stub():
    mod = types.ModuleType("apify")

    class _Actor:
        @staticmethod
        async def __aenter__():
            return None

        @staticmethod
        async def __aexit__(*a):
            return False

        @staticmethod
        async def get_input():
            return None

        @staticmethod
        async def charge(**k):
            pass

        @staticmethod
        async def set_status_message(m):
            pass

        @staticmethod
        async def fail():
            pass

        @staticmethod
        async def push_data(d):
            pass

        @staticmethod
        async def set_value(k, v):
            pass

        log = types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )

    mod.Actor = _Actor
    return mod


def _make_googleapiclient_stub():
    gapi = types.ModuleType("googleapiclient")
    gapi_discovery = types.ModuleType("googleapiclient.discovery")
    gapi_discovery.build = lambda *a, **k: None
    gapi_errors = types.ModuleType("googleapiclient.errors")

    class HttpError(Exception):
        resp = types.SimpleNamespace(status=500, reason="test")

        def __str__(self):
            return "http error"

    gapi_errors.HttpError = HttpError
    return gapi, gapi_discovery, gapi_errors


# Install stubs BEFORE the analyzer imports them. Pytest loads conftest before
# the test modules, so this ordering is safe.
apify_stub = _make_apify_stub()
sys.modules.setdefault("apify", apify_stub)

gapi, gapi_discovery, gapi_errors = _make_googleapiclient_stub()
sys.modules.setdefault("googleapiclient", gapi)
sys.modules.setdefault("googleapiclient.discovery", gapi_discovery)
sys.modules.setdefault("googleapiclient.errors", gapi_errors)


def _load_analyzer():
    """Lazy import of the analyzer module. Re-executes the source with the
    `__main__` block stripped so it imports cleanly as a library."""
    import importlib.util
    import re
    from pathlib import Path

    src_path = Path(__file__).resolve().parent.parent / "apify_channel_analyzer.py"
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    clean = re.sub(r"if __name__ == .__main__.:.*$", "", src, flags=re.DOTALL)
    spec = importlib.util.spec_from_loader("apify_channel_analyzer", loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(clean, str(src_path), "exec"), mod.__dict__)
    return mod


@pytest.fixture(scope="session")
def analyzer():
    return _load_analyzer()
