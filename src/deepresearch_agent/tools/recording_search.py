from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import Source
from deepresearch_agent.settings import project_root
from deepresearch_agent.tools.provider import SearchProvider


class RecordingReplayMiss(RuntimeError):
    """Raised when replay mode cannot find an exact recorded query key."""


def normalize_query_key(query: str, top_k: int = 3, source_type: str | None = None) -> str:
    normalized_query = re.sub(r"\s+", " ", query.strip().lower())
    payload = {
        "query": normalized_query,
        "source_type": source_type or "",
        "top_k": top_k,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class RecordingMetadata:
    key: str
    query: str
    top_k: int
    source_type: str | None
    as_of: str
    recorded_at: str
    status: str = "complete"
    error_type: str | None = None


class RecordingSearchProvider:
    """Record/replay wrapper for deterministic Golden Set retrieval."""

    def __init__(
        self,
        mode: str,
        recording_dir: Path | None = None,
        live_provider: SearchProvider | None = None,
        as_of: date | None = None,
    ) -> None:
        if mode not in {"record", "replay"}:
            raise ValueError("RecordingSearchProvider mode must be record or replay.")
        if mode == "record" and live_provider is None:
            raise ValueError("record mode requires a live_provider.")
        if mode == "record" and as_of is None:
            raise ValueError("record mode requires an explicit as_of date.")
        self.mode = mode
        self.recording_dir = recording_dir or project_root() / "data" / "recordings" / "golden_v1"
        self.live_provider = live_provider
        self.as_of = as_of
        self.recording_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        key = normalize_query_key(query, top_k=top_k, source_type=source_type)
        path = self._recording_path(key)
        if self.mode == "replay":
            if not path.exists():
                raise RecordingReplayMiss(f"Recording replay miss for key={key}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [Source.model_validate(item) for item in payload.get("sources", [])]
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [Source.model_validate(item) for item in payload.get("sources", [])]

        assert self.live_provider is not None
        sources = self.live_provider.search(query, top_k=top_k, source_type=source_type)
        error_type = getattr(self.live_provider, "last_error_type", None)
        metadata = RecordingMetadata(
            key=key,
            query=query,
            top_k=top_k,
            source_type=source_type,
            as_of=self.as_of.isoformat() if self.as_of else "",
            recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            status="partial" if error_type else "complete",
            error_type=error_type,
        )
        payload = {
            "metadata": metadata.__dict__,
            "sources": [source.model_dump(mode="json") for source in sources],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return sources

    def _recording_path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.recording_dir / f"{digest}.json"
