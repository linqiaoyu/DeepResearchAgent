from __future__ import annotations

import importlib.util
import re
from typing import Any, Protocol


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int:
        """Return a deterministic upper-level estimate for a text block."""


class HeuristicTokenEstimator:
    _CJK_RE = re.compile(r"[\u3400-\u9fff]")

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        cjk = len(self._CJK_RE.findall(text))
        non_cjk = len(text) - cjk
        return cjk + (non_cjk + 3) // 4


class TiktokenEstimator:
    def __init__(self, module: Any) -> None:
        self._encoding = module.get_encoding("cl100k_base")

    def estimate(self, text: str) -> int:
        return len(self._encoding.encode(text))


def build_token_estimator() -> TokenEstimator:
    if importlib.util.find_spec("tiktoken") is not None:
        import tiktoken

        return TiktokenEstimator(tiktoken)
    return HeuristicTokenEstimator()
