from __future__ import annotations
from typing import Literal, Optional, TypedDict
from pydantic import BaseModel, Field

class ContextChunk(BaseModel):
    title: str
    text: str

class QAExample(BaseModel):
    qid: str
    difficulty: Literal["easy", "medium", "hard"]
    question: str
    gold_answer: str
    context: list[ContextChunk]

class JudgeResult(BaseModel):
    """Kết quả chấm điểm một câu trả lời của Actor.

    score: 1 nếu đúng, 0 nếu sai (exact match sau khi normalize).
    reason: lý do chấm điểm (vì sao đúng/sai).
    missing_evidence: các bằng chứng/bước suy luận còn thiếu (dùng cho reflection).
    spurious_claims: các khẳng định sai/thừa trong câu trả lời.
    """
    score: Literal[0, 1]
    reason: str
    missing_evidence: list[str] = Field(default_factory=list)
    spurious_claims: list[str] = Field(default_factory=list)

class ReflectionEntry(BaseModel):
    """Một mục tự phản chiếu sau khi trả lời sai.

    attempt_id: lần thử đã sai.
    failure_reason: vì sao lần thử đó sai (lấy từ evaluator).
    lesson: bài học rút ra.
    next_strategy: chiến thuật cụ thể cho lần thử kế tiếp.
    """
    attempt_id: int
    failure_reason: str
    lesson: str
    next_strategy: str

class AttemptTrace(BaseModel):
    attempt_id: int
    answer: str
    score: int
    reason: str
    reflection: Optional[ReflectionEntry] = None
    token_estimate: int = 0
    latency_ms: int = 0

class RunRecord(BaseModel):
    qid: str
    question: str
    gold_answer: str
    agent_type: Literal["react", "reflexion"]
    predicted_answer: str
    is_correct: bool
    attempts: int
    token_estimate: int
    latency_ms: int
    failure_mode: Literal["none", "entity_drift", "incomplete_multi_hop", "wrong_final_answer", "looping", "reflection_overfit"]
    reflections: list[ReflectionEntry] = Field(default_factory=list)
    traces: list[AttemptTrace] = Field(default_factory=list)

class ReportPayload(BaseModel):
    meta: dict
    summary: dict
    failure_modes: dict
    examples: list[dict]
    extensions: list[str]
    discussion: str

class ReflexionState(TypedDict):
    question: str
    context: list[str]
    trajectory: list[str]
    reflection_memory: list[str]
    attempt_count: int
    success: bool
    final_answer: str
