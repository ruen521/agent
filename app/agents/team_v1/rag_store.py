from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any
import uuid

from app.agents.team_v1.schemas import RagEvidence

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [token.lower() for token in _TOKEN_PATTERN.findall(text)]


class LocalRagStore:
    def __init__(self, run_id: str, root_dir: Path) -> None:
        self.run_id = str(run_id)
        self.run_dir = Path(root_dir) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.run_dir / "evidence_index.jsonl"

    @property
    def index_path(self) -> Path:
        return self._index_path

    def append_evidence(
        self,
        *,
        member_id: str,
        tool_name: str,
        title_cn: str,
        content_text_cn: str,
        raw_json: dict[str, Any] | list[Any] | str | None,
    ) -> dict[str, Any]:
        evidence = RagEvidence(
            evidence_id=f"ev-{uuid.uuid4().hex[:12]}",
            run_id=self.run_id,
            member_id=str(member_id),
            tool_name=str(tool_name),
            title_cn=str(title_cn),
            content_text_cn=str(content_text_cn),
            raw_json=raw_json,
            created_at=_utc_now_iso(),
        )
        payload = evidence.model_dump()
        with self._index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload

    def list_evidence(self) -> list[dict[str, Any]]:
        if not self._index_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self._index_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def search(self, query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
        docs = self.list_evidence()
        if not docs:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        df: dict[str, int] = {}
        doc_tokens: list[list[str]] = []
        for doc in docs:
            text = f"{doc.get('title_cn', '')}\n{doc.get('content_text_cn', '')}"
            tokens = _tokenize(text)
            doc_tokens.append(tokens)
            for token in set(tokens):
                df[token] = df.get(token, 0) + 1

        doc_count = len(docs)
        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, doc in enumerate(docs):
            tokens = doc_tokens[idx]
            if not tokens:
                continue
            tf: dict[str, int] = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
            score = 0.0
            for token in query_tokens:
                if token not in tf:
                    continue
                idf = math.log((doc_count + 1) / (1 + df.get(token, 0))) + 1.0
                score += float(tf[token]) * idf
            if score <= 0:
                continue
            scored.append((score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        hits: list[dict[str, Any]] = []
        for score, doc in scored[: max(1, int(top_k))]:
            hits.append(
                {
                    "score": round(score, 4),
                    "evidence_id": str(doc.get("evidence_id") or ""),
                    "member_id": str(doc.get("member_id") or ""),
                    "tool_name": str(doc.get("tool_name") or ""),
                    "title_cn": str(doc.get("title_cn") or ""),
                    "content_excerpt": str(doc.get("content_text_cn") or "")[:300],
                    "created_at": str(doc.get("created_at") or ""),
                }
            )
        return hits

    def clear_current_run(self) -> None:
        try:
            if self._index_path.exists():
                self._index_path.unlink()
        except Exception:
            pass
        try:
            if self.run_dir.exists() and not any(self.run_dir.iterdir()):
                self.run_dir.rmdir()
        except Exception:
            pass
