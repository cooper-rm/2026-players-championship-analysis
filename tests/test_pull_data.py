"""Tests for the Data Golf data-pull helpers.

Run from the repo root with:  pytest

`monkeypatch` is a built-in pytest fixture that sets/removes things (here, the
DATAGOLF_API_KEY env var) only for the duration of one test, then restores the
original state — so these tests never touch your real key.
"""

import pytest

from src.pull_data import get_api_key


def test_returns_key_when_set(monkeypatch):
    # happy path: env var present -> returns it
    monkeypatch.setenv("DATAGOLF_API_KEY", "abc123")
    assert get_api_key() == "abc123"


def test_strips_surrounding_whitespace(monkeypatch):
    # the guard we added: trailing newline/spaces get trimmed off
    monkeypatch.setenv("DATAGOLF_API_KEY", "  abc123\n")
    assert get_api_key() == "abc123"


def test_raises_when_missing(monkeypatch):
    # unhappy path: var absent -> RuntimeError (raising=False = don't error if already unset)
    monkeypatch.delenv("DATAGOLF_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_api_key()


def test_raises_when_whitespace_only(monkeypatch):
    # whitespace-only is functionally "empty" -> should also raise
    monkeypatch.setenv("DATAGOLF_API_KEY", "   ")
    with pytest.raises(RuntimeError):
        get_api_key()
