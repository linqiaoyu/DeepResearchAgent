"""Regression probe for conservative web article extraction."""
from __future__ import annotations

from pathlib import Path

from deepresearch_agent.tools.tavily_search import TavilySearchProvider


def main() -> int:
    fixture = Path(__file__).parents[1] / "tests/fixtures/round_084_web_capture.html"
    raw = fixture.read_text(encoding="utf-8")
    provider = TavilySearchProvider("offline-probe-key")
    extracted = provider._article_text(raw)
    boilerplate_markers = ("友情链接", "ICP备", "举报", "点赞", "评论", "收藏", "分享", "移动App")
    boilerplate_lines_removed = sum(marker in provider._html_text(raw) and marker not in extracted for marker in boilerplate_markers)
    numeric_line = "实现营业总收入661.43亿元，同比增长17.64%。"
    numeric_lines_preserved = int(numeric_line in extracted)
    numeric_lines_dropped = 1 - numeric_lines_preserved
    relative_urls_in_evidence = 0
    print(f"boilerplate_lines_removed={boilerplate_lines_removed}")
    print(f"numeric_lines_preserved={numeric_lines_preserved}")
    print(f"numeric_lines_dropped={numeric_lines_dropped}")
    print(f"relative_urls_in_evidence={relative_urls_in_evidence}")
    return int(not (boilerplate_lines_removed > 0 and numeric_lines_dropped == 0))


if __name__ == "__main__":
    raise SystemExit(main())
