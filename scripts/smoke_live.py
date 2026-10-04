"""One real question through the full stack (Neon + embeddings + Groq/Gemini); prints the
event stream compactly and the stored record. Usage:

    uv run python scripts/smoke_live.py "How do I keep the splash screen visible?" v58.0.0
    uv run python scripts/smoke_live.py "What changed in expo-clipboard?" v58.0.0 --diff v57.0.0
"""

from __future__ import annotations

import argparse
import json
import sys

from docpilot.api.schemas import AskRequest
from docpilot.config import get_settings
from docpilot.engine import Engine


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("version", nargs="?", default="v58.0.0")
    parser.add_argument("--sdk", default="expo")
    parser.add_argument("--diff", metavar="COMPARE_VERSION")
    args = parser.parse_args()
    engine = Engine.from_settings(get_settings())
    request = AskRequest(
        question=args.question,
        sdk=args.sdk,
        version=args.version,
        mode="diff" if args.diff else "answer",
        compare_version=args.diff,
    )
    tokens = []
    for event in engine.service.ask(request):
        kind = event["kind"]
        if kind == "token":
            tokens.append(event["text"])
            continue
        if kind == "retrieval":
            print(f"retrieval ({event['config']}):")
            for chunk in event["chunks"]:
                print(f"  [{chunk['n']}] {chunk['version']} {chunk['url']}")
        elif kind == "citations":
            print("\nanswer:\n" + event["answer"])
            print("\nverification:", json.dumps(event["verification"]))
        else:
            print(f"{kind}:", json.dumps(event, default=str)[:600])


if __name__ == "__main__":
    main()
