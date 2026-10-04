"""Optional LLM judge (`uv run evals --judge`): faithfulness and completeness, 1-5.

Reported separately from the code-based metrics: a judge is itself a model, with its own
biases (it favours long answers, and its own family's style). The deterministic verifier
answers "is every citation real"; the judge estimates "is every claim supported".
"""

from __future__ import annotations

from typing import Any

from llm_kit import Ledger, LLMError
from pydantic import BaseModel, Field

from ..prompts import load_prompt


class JudgeScore(BaseModel):
    faithfulness: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    reasoning: str


def judge_answer(
    engine: Any, question: dict[str, Any], passages: list[dict[str, Any]], answer: str
) -> dict[str, Any] | None:
    system, prompt_id = load_prompt("judge", engine.routing.prompts.get("judge", "v1"))
    context = "\n\n".join(f"[{p['n']}] {p['snippet']}" for p in passages)
    user = (
        f"Question: {question['question']}\n\nReference answer: {question['reference']}\n\n"
        f"<passages>\n{context}\n</passages>\n\n<answer>\n{answer}\n</answer>"
    )
    model = engine.service.model_factory("judge", Ledger(max_usd=0.02))
    try:
        score = model.complete_structured(user, JudgeScore, system=system)
    except LLMError:
        return None
    return {**score.model_dump(), "prompt": prompt_id}
