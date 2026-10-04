"""Vercel entry point: Vercel's FastAPI preset looks for `app` in a root-level main.py.

Everything lives in the package; this file only re-exports it. Locally use
`uv run uvicorn docpilot.api.main:app --port 7861` instead (docs/setup.md).
"""

from docpilot.api.main import app

__all__ = ["app"]
