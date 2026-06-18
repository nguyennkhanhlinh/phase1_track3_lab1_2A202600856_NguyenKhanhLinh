from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Iterable
from .schemas import QAExample, RunRecord

def normalize_answer(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text

def estimate_tokens(*texts: str) -> int:
    """Ước lượng số token theo heuristic ~4 ký tự/token.

    Dùng khi chạy mock (không có LLM thật để lấy usage). Thay cho con số
    hardcode trước đây — vẫn phản ánh độ dài thực của prompt/answer.
    """
    total_chars = sum(len(t) for t in texts if t)
    return max(1, total_chars // 4)

def load_dataset(path: str | Path) -> list[QAExample]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [QAExample.model_validate(item) for item in raw]

def save_jsonl(path: str | Path, records: Iterable[RunRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")
