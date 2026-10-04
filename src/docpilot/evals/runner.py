"""`uv run evals`: score retrieval configurations and answers on the golden set.

    uv run evals --recorded                  score the saved fixture (no database, no keys; CI)
    uv run evals --config hybrid             live retrieval for all four configs (comparison
                                             table) and writes docs/evals.md
    uv run evals --config all --answers      ... plus a generated answer per question per
                                             config: citation precision, refusal, latency, cost
    uv run evals --answers --judge           ... plus the LLM judge (faithfulness, completeness)
    uv run evals ... --record                save what the live run saw to the fixture

Retrieval metrics always cover all four configurations so the table compares them;
`--config` picks which configurations also get answers. Questions asked during an eval go
to an in-memory question log, not the production `questions` table.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..retrieval.search import CONFIGS, RetrievalError
from ..retrieval.sql import versions_for
from .scorers import answer_metrics, retrieval_metrics

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "evals" / "golden.json"
FIXTURE = ROOT / "evals" / "fixtures" / "retrieval.json"
DOC = ROOT / "docs" / "evals.md"
START, END = "<!-- results:start -->", "<!-- results:end -->"
TOP_K = 10

CONFIG_LABEL = {
    "vector": "vector",
    "fulltext": "full-text",
    "hybrid": "hybrid (RRF k=60 + API boost)",
    "hybrid_rerank": "hybrid + rerank",
}


def load_golden(path: Path = GOLDEN) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class EvalStore:
    """Reads (search, corpora) go to the real store; question writes stay in memory."""

    def __init__(self, inner: Any):
        from ..db.store import MemoryStore

        self.inner = inner
        self.log = MemoryStore()

    def __getattr__(self, name: str) -> Any:
        if name in {
            "create_question",
            "update_question",
            "get_question",
            "set_feedback",
            "count_questions_since",
        }:
            return getattr(self.log, name)
        return getattr(self.inner, name)


def _chunk_row(chunk: Any) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "url": chunk.url,
        "heading_path": chunk.heading_path,
        "version": chunk.version,
    }


def complete_corpora(engine: Any) -> set[tuple[str, str]]:
    """(sdk, version) pairs whose every chunk has a vector."""
    return {
        (c.sdk, c.version)
        for c in engine.store.list_corpora()
        if c.embedded_count is None or c.embedded_count >= c.chunk_count
    }


def vectors_ready(complete: set[tuple[str, str]], sdk: str, version: str) -> bool:
    return all((sdk, v) in complete for v in versions_for(sdk, version))


def run_retrieval(
    engine: Any, questions: list[dict[str, Any]], configs: tuple[str, ...] = CONFIGS
) -> dict[str, dict[str, Any]]:
    """Top-10 chunks per question per config. A vector-based config is not measured on a
    corpus that is only partly embedded (it would silently be scored on a subset)."""
    complete = complete_corpora(engine)
    results: dict[str, dict[str, Any]] = {config: {} for config in configs}
    for question in questions:
        for config in configs:
            if config != "fulltext" and not vectors_ready(
                complete, question["sdk"], question["version"]
            ):
                results[config][question["id"]] = {"chunks": [], "error": "partial_vectors"}
                continue
            started = time.monotonic()
            try:
                result = engine.retriever.retrieve(
                    question["question"],
                    sdk=question["sdk"],
                    version=question["version"],
                    config=config,
                )
            except RetrievalError as exc:
                results[config][question["id"]] = {"chunks": [], "error": exc.code}
                continue
            results[config][question["id"]] = {
                "chunks": [_chunk_row(c) for c in result.chunks[:TOP_K]],
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "effective": result.effective_config,
            }
        print(f"  retrieved {question['id']}", file=sys.stderr, flush=True)
    return results


def run_answers(
    engine: Any, questions: list[dict[str, Any]], configs: list[str], judge: bool = False
) -> dict[str, dict[str, Any]]:
    from ..answer.service import AskService
    from ..api.schemas import AskRequest

    store = EvalStore(engine.store)
    out: dict[str, dict[str, Any]] = {}
    for config in configs:
        service = AskService(
            store=store,
            retriever=engine.retriever,
            model_factory=engine.service.model_factory,
            routing=engine.routing,
            config=config,  # type: ignore[arg-type]
            context_budget=engine.settings.context_token_budget,
        )
        out[config] = {}
        complete = complete_corpora(engine)
        for question in questions:
            if config != "fulltext" and not vectors_ready(
                complete, question["sdk"], question["version"]
            ):
                continue
            request = AskRequest(
                question=question["question"], sdk=question["sdk"], version=question["version"]
            )
            row: dict[str, Any] = {}
            passages: list[dict[str, Any]] = []
            for event in service.ask(request):
                if event["kind"] == "retrieval":
                    passages = event["chunks"]
                elif event["kind"] == "citations":
                    row["answer"] = event["answer"]
                    row["verification"] = event["verification"]
                elif event["kind"] == "done":
                    row["latency_ms"] = event["latency_ms"]
                    row["usage"] = {
                        "usd": event["usage"]["usd"],
                        "prompt_tokens": event["usage"]["prompt_tokens"],
                        "completion_tokens": event["usage"]["completion_tokens"],
                        "served_by": event["usage"]["served_by"],
                    }
                elif event["kind"] == "error":
                    row["error"] = f"{event['code']}: {event['message']}"
            if judge and "answer" in row:
                from .judge import judge_answer

                row["judge"] = judge_answer(engine, question, passages, row["answer"])
            out[config][question["id"]] = row
            status = row.get("error") or row.get("verification", {}).get("status")
            print(f"  [{config}] {question['id']}: {status}", file=sys.stderr, flush=True)
    return out


def coverage(engine: Any) -> list[dict[str, Any]]:
    return [
        {
            "sdk": c.sdk,
            "version": c.version,
            "chunks": c.chunk_count,
            "embedded": c.embedded_count,
            "embedding_model": c.embedding_model,
            "commit": c.commit_sha[:10],
        }
        for c in engine.store.list_corpora()
    ]


def score(golden: dict[str, Any], data: dict[str, Any], sdk: str | None = None) -> dict[str, Any]:
    questions = [q for q in golden["questions"] if not sdk or q["sdk"] == sdk]
    report: dict[str, Any] = {"retrieval": {}, "answers": {}}
    for config, results in data.get("retrieval", {}).items():
        report["retrieval"][config] = retrieval_metrics(questions, results)
    for config, answers in data.get("answers", {}).items():
        report["answers"][config] = answer_metrics(questions, answers)
        judged = [a["judge"] for a in answers.values() if a.get("judge")]
        if judged:
            report["answers"][config]["judge"] = {
                key: round(statistics.mean(j[key] for j in judged), 2)
                for key in ("faithfulness", "completeness")
            }
    return report


def _fmt(value: Any, kind: str = "") -> str:
    if value is None:
        return "n/a"
    if kind == "ms":
        return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"
    if kind == "usd":
        return f"${value:.5f}"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def table(report: dict[str, Any]) -> str:
    lines = [
        "| Config | recall@5 | MRR | citation precision | refusals correct | answer p50 / p95 "
        "| retrieval p50 | $ / question |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for config in CONFIGS:
        r = report["retrieval"].get(config)
        if r is None or not r["n"]:
            skipped = sum((r or {}).get("skipped", {}).values())
            if r is not None:
                lines.append(
                    f"| {CONFIG_LABEL[config]} | not measured ({skipped} questions wait for "
                    "vectors) | | | | | | |"
                )
            continue
        a = report["answers"].get(config, {})
        refusals = (
            f"{a['refusal_correct']}/{a['refusal_total']}" if a.get("refusal_total") else "n/a"
        )
        latency = (
            f"{_fmt(a.get('latency_p50_ms'), 'ms')} / {_fmt(a.get('latency_p95_ms'), 'ms')}"
            if a
            else "n/a"
        )
        lines.append(
            f"| {CONFIG_LABEL[config]} | {_fmt(r['recall@5'])} | {_fmt(r['mrr'])} "
            f"| {_fmt(a.get('citation_precision'))} | {refusals} | {latency} "
            f"| {_fmt(r['retrieval_p50_ms'], 'ms')} | {_fmt(a.get('usd_per_question'), 'usd')} |"
        )
    return "\n".join(lines)


def render_results(golden: dict[str, Any], data: dict[str, Any]) -> str:
    full = score(golden, data)
    parts = [
        START,
        f"_Generated by `uv run evals` from {data.get('source', 'a live run')} recorded "
        f"{data.get('recorded_at', 'n/a')}; golden set `{golden['version']}` "
        f"({len(golden['questions'])} questions)._",
        "",
        "**All questions**",
        "",
        table(full),
    ]
    for sdk in ("expo", "react-native"):
        parts += ["", f"**{sdk}**", "", table(score(golden, data, sdk))]
    judged = {c: a["judge"] for c, a in full["answers"].items() if a.get("judge")}
    if judged:
        parts += [
            "",
            "LLM judge (1-5): "
            + "; ".join(
                f"{c}: faithfulness {j['faithfulness']}, completeness {j['completeness']}"
                for c, j in judged.items()
            ),
        ]
    cov = data.get("coverage") or []
    if cov:
        parts += [
            "",
            "Vector coverage at run time (chunks with an embedding / chunks):",
            "",
            *[
                f"- {c['sdk']}@{c['version']}: {c['embedded']}/{c['chunks']} "
                f"({c['embedding_model']}, commit {c['commit']})"
                for c in cov
            ],
        ]
    served = {c: a.get("served_by") for c, a in full["answers"].items() if a.get("served_by")}
    if served:
        parts += ["", "Answers served by: " + "; ".join(f"{c}: {s}" for c, s in served.items())]
    parts.append(END)
    return "\n".join(parts)


def write_doc(section: str, path: Path = DOC) -> None:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if START in text and END in text:
            before, rest = text.split(START, 1)
            after = rest.split(END, 1)[1]
            path.write_text(before + section + after, encoding="utf-8")
            return
        path.write_text(text.rstrip() + "\n\n" + section + "\n", encoding="utf-8")
        return
    path.write_text("# Evaluation\n\n" + section + "\n", encoding="utf-8")


def merge_fixture(new: dict[str, Any], path: Path = FIXTURE) -> dict[str, Any]:
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = {**old, **{k: v for k, v in new.items() if k not in ("retrieval", "answers")}}
    for key in ("retrieval", "answers"):
        merged[key] = dict(old.get(key, {}))
        for config, rows in new.get(key, {}).items():
            # Per question: a later run (e.g. React Native only) updates its own rows and
            # never erases another subset's.
            merged[key][config] = {**merged[key].get(config, {}), **rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    return merged


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evals", description=__doc__.split("\n")[0])
    parser.add_argument("--config", default="hybrid", choices=[*CONFIGS, "all"])
    parser.add_argument("--answers", action="store_true", help="generate and score answers")
    parser.add_argument("--judge", action="store_true", help="LLM judge (implies --answers)")
    parser.add_argument("--recorded", action="store_true", help="score the saved fixture")
    parser.add_argument("--record", action="store_true", help="save the live run as fixture")
    parser.add_argument("--no-write", action="store_true", help="do not touch docs/evals.md")
    parser.add_argument("--sdk", choices=["expo", "react-native"], help="only these questions")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    args = parser.parse_args(argv)
    golden = load_golden()

    if args.recorded:
        if not FIXTURE.exists():
            print(f"no fixture at {FIXTURE}", file=sys.stderr)
            raise SystemExit(2)
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data.setdefault("source", "the recorded fixture")
    else:
        from ..config import get_settings
        from ..engine import Engine

        settings = get_settings()
        if not settings.dsn():
            print("DATABASE_URL is not set: use --recorded", file=sys.stderr)
            raise SystemExit(2)
        engine = Engine.from_settings(settings)
        questions = [q for q in golden["questions"] if not args.sdk or q["sdk"] == args.sdk]
        if args.limit:
            questions = questions[: args.limit]
        data = {
            "golden_version": golden["version"],
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "source": "a live run against Neon",
            "coverage": coverage(engine),
            "retrieval": run_retrieval(engine, questions),
        }
        if args.answers or args.judge:
            configs = list(CONFIGS) if args.config == "all" else [args.config]
            data["answers"] = run_answers(engine, questions, configs, judge=args.judge)
        if args.record:
            data = merge_fixture(data)
        report = score(golden, data)
        try:
            engine.store.put_eval_run(
                golden["version"],
                {"configs": list(CONFIGS), "answers": list(data.get("answers", {}))},
                {"retrieval": report["retrieval"], "answers": report["answers"]},
            )
        except Exception as exc:  # recording the run is best-effort
            print(f"could not store eval run: {exc}", file=sys.stderr)

    print(table(score(golden, data)))
    if not args.no_write:
        write_doc(render_results(golden, data))
        print(f"wrote {DOC}", file=sys.stderr)


if __name__ == "__main__":
    main()
