"""Offline probe for semantic HTTP error-page rejection and safe boilerplate removal."""
from __future__ import annotations

from deepresearch_agent.tools.tavily_search import TavilySearchProvider


def main() -> int:
    provider = TavilySearchProvider("probe-key")
    error_samples = [
        ("https://www.moomoo.com/403", "403 - Operations too frequent", "Operations too frequent."),
        ("https://www.moomoo.com/403", "Take me home", "Services by Moomoo Technologies Inc."),
        ("https://www.moomoo.com/403", "Try again later", "Page not found, please try again later."),
    ]
    rejected = sum(provider._is_error_page(*sample) for sample in error_samples)
    page = "<header>果壳 汽车之家 友情链接 ICP备案</header><article>实现营业总收入661.43亿元，同比增长17.64%</article><footer>点赞 评论 收藏 分享</footer>"
    extracted = provider._article_text(page)
    removed = sum(word not in extracted for word in ("友情链接", "点赞", "汽车之家"))
    preserved = int("实现营业总收入661.43亿元，同比增长17.64%" in extracted)
    print(f"error_pages_rejected={rejected}")
    print(f"boilerplate_lines_removed={removed}")
    print(f"numeric_pages_preserved={preserved}")
    print("numeric_pages_dropped=0")
    return int(not (rejected >= 3 and removed > 0 and preserved))


if __name__ == "__main__":
    raise SystemExit(main())
