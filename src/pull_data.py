"""Data Golf API client — pulls raw data and caches it to data/.

The notebook reads the cached files, never the API directly, so the analysis is
reproducible offline and the API key is only needed at pull time.
"""

from __future__ import annotations

import os


def get_api_key() -> str:
    """Return the Data Golf API key from the environment.

    Reads the DATAGOLF_API_KEY env var (loaded from .env by load_dotenv() at the
    program's entry point). Raises RuntimeError if it's missing rather than
    calling sys.exit(), so callers — including tests — can catch the failure
    instead of the whole process dying.
    """
    key = os.environ.get("DATAGOLF_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DATAGOLF_API_KEY is not set. Copy .env.example to .env, add your key, "
            "and make sure load_dotenv() has run."
        )
    return key
