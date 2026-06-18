from __future__ import annotations
import os
import time
from dataclasses import dataclass
from typing import Literal

from .mock_runtime import FAILURE_MODE_BY_QID
from .schemas import AttemptTrace, QAExample, ReflectionEntry, RunRecord
from .utils import estimate_tokens

# --- Chọn runtime: mock (deterministic, cho autograde) hoặc LLM thật ---
# Bật LLM thật bằng biến môi trường: REFLEXION_USE_LLM=1
_USE_LLM = os.getenv("REFLEXION_USE_LLM", "0") == "1"
if _USE_LLM:
    from .llm_runtime import actor_answer, evaluator, last_token_usage, reflector
else:
    from .mock_runtime import actor_answer, evaluator, reflector

    def last_token_usage() -> int | None:  # mock không có usage thật
        return None


def _context_text(example: QAExample) -> str:
    return "\n".join(f"{c.title}: {c.text}" for c in example.context)


@dataclass
class BaseAgent:
    agent_type: Literal["react", "reflexion"]
    max_attempts: int = 1

    def run(self, example: QAExample) -> RunRecord:
        reflection_memory: list[str] = []
        reflections: list[ReflectionEntry] = []
        traces: list[AttemptTrace] = []
        final_answer = ""
        final_score = 0
        ctx = _context_text(example)

        for attempt_id in range(1, self.max_attempts + 1):
            # Đo latency thật của 1 lượt (actor + evaluator)
            t0 = time.perf_counter()
            answer = actor_answer(example, attempt_id, self.agent_type, reflection_memory)
            judge = evaluator(example, answer)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            # Token: dùng usage thật từ LLM nếu có, ngược lại ước lượng theo độ dài text
            usage = last_token_usage()
            token_estimate = (
                usage if usage is not None
                else estimate_tokens(example.question, ctx, "\n".join(reflection_memory), answer, judge.reason)
            )

            trace = AttemptTrace(
                attempt_id=attempt_id,
                answer=answer,
                score=judge.score,
                reason=judge.reason,
                token_estimate=token_estimate,
                latency_ms=latency_ms,
            )
            final_answer = answer
            final_score = judge.score

            if judge.score == 1:
                traces.append(trace)
                break

            # --- Logic Reflexion ---
            # Nếu là agent 'reflexion' và vẫn còn lượt thử: tự phản chiếu,
            # lưu vào reflection_memory để Actor dùng cho lần sau.
            if self.agent_type == "reflexion" and attempt_id < self.max_attempts:
                reflection = reflector(example, attempt_id, judge)
                trace.reflection = reflection
                reflections.append(reflection)
                reflection_memory.append(
                    f"[Attempt {reflection.attempt_id}] Lỗi: {reflection.failure_reason} "
                    f"| Bài học: {reflection.lesson} | Chiến thuật: {reflection.next_strategy}"
                )

            traces.append(trace)

        total_tokens = sum(t.token_estimate for t in traces)
        total_latency = sum(t.latency_ms for t in traces)
        failure_mode = "none" if final_score == 1 else FAILURE_MODE_BY_QID.get(example.qid, "wrong_final_answer")
        return RunRecord(
            qid=example.qid,
            question=example.question,
            gold_answer=example.gold_answer,
            agent_type=self.agent_type,
            predicted_answer=final_answer,
            is_correct=bool(final_score),
            attempts=len(traces),
            token_estimate=total_tokens,
            latency_ms=total_latency,
            failure_mode=failure_mode,
            reflections=reflections,
            traces=traces,
        )


class ReActAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(agent_type="react", max_attempts=1)


class ReflexionAgent(BaseAgent):
    def __init__(self, max_attempts: int = 3) -> None:
        super().__init__(agent_type="reflexion", max_attempts=max_attempts)
