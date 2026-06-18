"""Runtime LLM thật (thay cho mock_runtime) — gọi OpenRouter qua HTTP.

Bật bằng: REFLEXION_USE_LLM=1 (xem agents.py).
Cần biến môi trường:
  - OPENROUTER_API_KEY : API key OpenRouter
  - REFLEXION_LLM_MODEL: model (mặc định 'openai/gpt-4.1-mini')

Chỉ dùng thư viện chuẩn (urllib, json) để không phải thêm dependency.
Giữ đúng chữ ký hàm như mock_runtime để agents.py dùng thay thế trực tiếp.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from .prompts import ACTOR_SYSTEM, EVALUATOR_SYSTEM, REFLECTOR_SYSTEM
from .schemas import JudgeResult, QAExample, ReflectionEntry

# Cùng bảng failure-mode với mock để agents import được nếu cần.
FAILURE_MODE_BY_QID: dict[str, str] = {}

_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
_MODEL = os.getenv("REFLEXION_LLM_MODEL", "openai/gpt-4.1-mini")

# Tổng token của attempt hiện tại; reset mỗi lần actor_answer được gọi.
_accum_tokens: int = 0


def last_token_usage() -> int | None:
    """Tổng token thật của lượt vừa rồi (actor + evaluator). None nếu chưa có."""
    return _accum_tokens or None


def _chat(system: str, user: str, temperature: float = 0.0) -> str:
    """Gọi 1 lượt chat completion, cộng dồn token vào _accum_tokens, trả về text."""
    global _accum_tokens
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu OPENROUTER_API_KEY để chạy LLM thật.")

    payload = json.dumps({
        "model": _MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    _accum_tokens += int(data.get("usage", {}).get("total_tokens", 0))
    return data["choices"][0]["message"]["content"].strip()


def _extract_json(text: str) -> dict:
    """Bóc tách JSON từ output LLM (gỡ code fence, lấy object đầu tiên)."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            return json.loads(m.group())
        raise


def _context_block(example: QAExample) -> str:
    return "\n".join(f"- {c.title}: {c.text}" for c in example.context)


def actor_answer(example: QAExample, attempt_id: int, agent_type: str, reflection_memory: list[str]) -> str:
    global _accum_tokens
    _accum_tokens = 0  # bắt đầu attempt mới
    notes = ""
    if reflection_memory:
        notes = "\n\nREFLECTION NOTES (từ các lần thử trước):\n" + "\n".join(reflection_memory)
    user = (
        f"CONTEXT:\n{_context_block(example)}\n\n"
        f"QUESTION: {example.question}{notes}\n\n"
        "Đáp án cuối cùng (ngắn gọn):"
    )
    return _chat(ACTOR_SYSTEM, user)


def evaluator(example: QAExample, answer: str) -> JudgeResult:
    user = (
        f"QUESTION: {example.question}\n"
        f"GOLD ANSWER: {example.gold_answer}\n"
        f"PREDICTED ANSWER: {answer}\n\n"
        "Chấm điểm và trả về JSON theo schema."
    )
    raw = _chat(EVALUATOR_SYSTEM, user)
    try:
        data = _extract_json(raw)
        return JudgeResult(
            score=1 if int(data.get("score", 0)) == 1 else 0,
            reason=str(data.get("reason", "")),
            missing_evidence=list(data.get("missing_evidence", []) or []),
            spurious_claims=list(data.get("spurious_claims", []) or []),
        )
    except Exception:
        # Fallback an toàn nếu LLM trả sai định dạng.
        from .utils import normalize_answer
        ok = normalize_answer(example.gold_answer) == normalize_answer(answer)
        return JudgeResult(score=1 if ok else 0, reason="Fallback exact-match (JSON parse lỗi).")


def reflector(example: QAExample, attempt_id: int, judge: JudgeResult) -> ReflectionEntry:
    user = (
        f"QUESTION: {example.question}\n"
        f"WRONG ANSWER (attempt {attempt_id})\n"
        f"FAILURE REASON: {judge.reason}\n"
        f"MISSING EVIDENCE: {judge.missing_evidence}\n\n"
        "Phân tích và trả về JSON reflection theo schema."
    )
    raw = _chat(REFLECTOR_SYSTEM, user)
    try:
        data = _extract_json(raw)
        return ReflectionEntry(
            attempt_id=int(data.get("attempt_id", attempt_id)),
            failure_reason=str(data.get("failure_reason", judge.reason)),
            lesson=str(data.get("lesson", "")),
            next_strategy=str(data.get("next_strategy", "")),
        )
    except Exception:
        return ReflectionEntry(
            attempt_id=attempt_id,
            failure_reason=judge.reason,
            lesson="Cần hoàn tất đầy đủ các bước suy luận multi-hop.",
            next_strategy="Làm rõ từng hop và kiểm chứng thực thể cuối với context.",
        )
