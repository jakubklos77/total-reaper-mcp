"""Shared pytest options: live REAPER tests only run with --live."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run live tests against a running REAPER")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip = pytest.mark.skip(reason="live REAPER tests need --live")
        for it in items:
            if "tests/live" in str(it.fspath).replace("\\", "/"):
                it.add_marker(skip)
