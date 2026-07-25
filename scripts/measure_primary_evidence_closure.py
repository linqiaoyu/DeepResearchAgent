from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.orchestration.research_loop import (
    build_replan_query,
)
from deepresearch_agent.schemas import (
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.settings import project_root
from deepresearch_agent.tools import (
    DeterministicCapabilitySelector,
    FixtureStructuredDataProvider,
    TavilySearchProvider,
    build_capability_registry,
)


QUERY_DIRECTIONS = {
    "Q01": ("年度报告", "分产品收入 年报", "年度报告摘要 公司公告"),
    "Q04": ("年度报告", "原材料价格 毛利率 业绩说明", "年度报告 公司公告"),
    "Q16": (
        "SNE Research 年度统计",
        "中国汽车动力电池产业创新联盟 年度数据",
        "装机量 市占率 第一 第二",
    ),
    "Q19": ("行业统计 年度报告", "恒瑞医药 公司公告 GLP-1", "代表交易 公司公告"),
    "Q26": ("2022 项目公告", "2024 2025 建设进展 公司披露", "官方 投产 产能"),
    "Q28": ("中国光伏行业协会 倡议", "反内卷 座谈会", "企业公告 减产执行"),
}

REQUIREMENTS = {
    "Q01": {
        "营业总收入及同比": (("营业总收入",), ("1741.44", "1,741.44"), ("15.66",)),
        "归母净利润及同比": (("归属于上市公司股东的净利润", "归母净利润"), ("862.28",), ("15.38",)),
        "茅台酒与系列酒收入拆分": (("茅台酒",), ("系列酒",), ("1459.28",), ("246.84",)),
    },
    "Q04": {
        "营业收入及同比方向": (("营业收入",), ("3620.13", "3,620.13"), ("9.70",), ("下降", "减少")),
        "归母净利润及同比方向": (("归属于上市公司股东的净利润", "归母净利润"), ("507.45", "507.44"), ("15.01",), ("增长", "增加")),
        "公司口径成因": (("原材料",), ("价格", "成本"), ("下降", "下行"), ("毛利", "售价", "产品价格")),
    },
    "Q16": {
        "宁德时代装机量与份额": (("宁德时代", "CATL"), ("339.3",), ("37.9",)),
        "比亚迪装机量份额与排序": (("比亚迪", "BYD"), ("153.7",), ("17.2",), ("第一",), ("第二",)),
    },
    "Q19": {
        "趋势量级": (("License-out", "授权"), ("2024",), ("500亿美元", "500 亿美元")),
        "代表交易一金额结构": (("恒瑞",), ("GLP-1", "GLP 1"), ("60亿美元", "60 亿美元"), ("首付款",)),
        "代表交易二金额结构": (("荣昌",), ("Vor Bio", "Vorbio"), ("40亿美元", "40 亿美元"), ("首付款", "预付款")),
        "潜在总额与首付款区分": (("潜在总", "总金额"), ("首付款",), ("里程碑",)),
    },
    "Q26": {
        "公告启动或开工": (("宁德时代", "CATL"), ("2022",), ("公告", "正式启动"), ("开工", "破土")),
        "截至2025年底进展": (("匈牙利", "Debrecen", "德布勒森"), ("2025",), ("建设", "投产", "产线")),
        "规划与已建成产能区分": (("100GWh", "100 GWh"), ("规划", "全部建成"), ("已建成", "产线", "投产")),
    },
    "Q28": {
        "协会倡议": (("中国光伏行业协会",), ("自律",), ("倡议", "防止内卷")),
        "重点会议节点": (("座谈会",), ("2024",), ("内卷", "自律")),
        "企业实际执行": (("企业",), ("减产", "控制产能"), ("执行", "落实", "实际")),
    },
}

QUESTION_PRIMARY_HINTS = {
    "Q01": ("moutaichina.com",),
    "Q04": ("catl.com",),
    "Q16": ("sneresearch.com",),
    "Q19": ("hrs.com.cn", "remegen",),
    "Q26": ("catl.com",),
    "Q28": ("chinapv.org.cn",),
}
GENERIC_PRIMARY_HINTS = (
    "cninfo.com.cn",
    "sse.com.cn",
    "szse.cn",
    ".gov.cn",
)


def _questions() -> dict[str, SubQuestion]:
    return {
        "Q01": SubQuestion(
            id="Q01",
            question="贵州茅台2024年度营业总收入、归母净利润、同比及产品收入结构。",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    company_name="贵州茅台",
                    symbol="600519",
                    periods=["2024"],
                    metrics=["营业总收入", "归母净利润"],
                )
            ],
        ),
        "Q04": SubQuestion(
            id="Q04",
            question="宁德时代2024年度营业收入、归母净利润同比方向与利润增长成因。",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    company_name="宁德时代",
                    symbol="300750",
                    periods=["2024"],
                    metrics=["营业收入", "归母净利润"],
                )
            ],
        ),
        "Q16": SubQuestion(
            id="Q16",
            question="2024年宁德时代与比亚迪全球动力电池装机量、市场份额与排名。",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(capability="symbol_resolve", company_name="宁德时代"),
                StructuredDataRequest(capability="symbol_resolve", company_name="比亚迪"),
            ],
        ),
        "Q19": SubQuestion(
            id="Q19",
            question="2024至2025年中国创新药License-out交易事件、代表交易与金额结构。",
            search_queries=[],
        ),
        "Q26": SubQuestion(
            id="Q26",
            question="宁德时代匈牙利工厂截至2025年底公告、开工、进展与产能。",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="symbol_resolve",
                    company_name="宁德时代",
                    symbol="300750",
                )
            ],
        ),
        "Q28": SubQuestion(
            id="Q28",
            question="2024年光伏行业减产挺价与自律事件线、协会倡议及企业执行。",
            search_queries=[],
        ),
    }


def _api_key() -> str:
    env_path = project_root() / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "TAVILY_API_KEY":
            return value.strip().strip("\"'")
    raise RuntimeError("TAVILY_API_KEY is required in .env")


def _primary(question_id: str, url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    hints = (*GENERIC_PRIMARY_HINTS, *QUESTION_PRIMARY_HINTS[question_id])
    return any(hint in host for hint in hints)


def _match(content: str, groups: tuple[tuple[str, ...], ...]) -> tuple[bool, int]:
    compact = re.sub(r"\s+", "", content).lower()
    positions: list[int] = []
    for alternatives in groups:
        found = [
            compact.find(re.sub(r"\s+", "", token).lower())
            for token in alternatives
        ]
        found = [position for position in found if position >= 0]
        if not found:
            return False, -1
        positions.append(min(found))
    return True, min(positions)


def _excerpt(content: str, position: int) -> tuple[str, int, int]:
    start = max(0, position - 200)
    end = min(len(content), start + 1000)
    return content[start:end], start, end


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=False)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir()
    provider = TavilySearchProvider(
        _api_key(),
        search_depth="basic",
        include_raw_content=False,
        max_retries=1,
        ledger_path=output_dir / "search_ledger.jsonl",
    )
    registry = build_capability_registry(
        search_provider=provider,
        structured_data_provider=FixtureStructuredDataProvider(),
    )
    selector = DeterministicCapabilitySelector(registry)
    researcher = ResearcherAgent(
        search_tool=provider,
        fetch_tool=provider,
        max_searches_per_run=48,
    )
    results: dict[str, object] = {}
    query_count = 0
    fetch_count = 0
    for question_id, sub_question in _questions().items():
        sub_question.search_queries = [
            build_replan_query(sub_question, direction)
            for direction in QUERY_DIRECTIONS[question_id]
        ]
        state = ResearchState(topic=sub_question.question)
        selection = selector.select(state, sub_question)
        if "web_fetch" not in selection.selected_capabilities:
            raise AssertionError(f"{question_id} did not select web_fetch")
        sources, records, _calls, _exhausted, _decisions = researcher.research_with_budget(
            sub_question,
            top_k_per_query=1,
            max_search_calls=6,
            enable_web_search=True,
            enable_web_fetch=True,
        )
        searches = [
            record for record in records
            if not record.query.startswith("[web_fetch]")
        ]
        fetches = [
            record for record in records
            if record.query.startswith("[web_fetch]")
        ]
        query_count += len(searches)
        fetch_count += len(fetches)
        fetched = [source for source in sources if source.source_type == "web_fetch"]
        for index, source in enumerate(fetched):
            (raw_dir / f"{question_id}_{index + 1}.txt").write_text(
                source.content,
                encoding="utf-8",
            )
        primary_sources = [
            source
            for source in fetched
            if _primary(question_id, source.url)
        ]
        requirement_results: list[dict[str, object]] = []
        for name, groups in REQUIREMENTS[question_id].items():
            hit = None
            for source in primary_sources:
                matched, position = _match(source.content, groups)
                if not matched:
                    continue
                excerpt, start, end = _excerpt(source.content, position)
                hit = {
                    "url": source.url,
                    "domain": urlsplit(source.url).netloc.lower(),
                    "position": f"{start}:{end}",
                    "excerpt": excerpt,
                    "sha256": hashlib.sha256(
                        source.content.encode("utf-8")
                    ).hexdigest(),
                }
                break
            requirement_results.append(
                {"requirement": name, "closed": hit is not None, "hit": hit}
            )
        closed = sum(bool(item["closed"]) for item in requirement_results)
        denominator = len(requirement_results)
        results[question_id] = {
            "queries": sub_question.search_queries,
            "capability_selection": selection.model_dump(mode="json"),
            "fetch_success_urls": [source.url for source in fetched],
            "fetch_failure_urls": [
                record.query.removeprefix("[web_fetch] ")
                for record in fetches
                if not record.source_ids
            ],
            "primary_fetch_urls": [source.url for source in primary_sources],
            "requirements": requirement_results,
            "closed": closed,
            "denominator": denominator,
            "closure": round(closed / denominator, 6),
        }
    closures = [
        float(item["closure"])
        for item in results.values()
        if isinstance(item, dict)
    ]
    payload = {
        "metric_version": "APBEC frozen 2026-07-25",
        "query_count": query_count,
        "fetch_count": fetch_count,
        "questions": results,
        "macro_average": round(sum(closures) / len(closures), 6),
        "questions_at_or_above_two_thirds": sum(
            value >= 2 / 3 for value in closures
        ),
    }
    if query_count > 18 or fetch_count > 30:
        raise AssertionError(
            f"measurement budget exceeded: queries={query_count}, fetches={fetch_count}"
        )
    (output_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            project_root()
            / "_collab/019c_instrument_viability/c7_measurement"
        ),
    )
    args = parser.parse_args()
    payload = run(args.output)
    print(
        json.dumps(
            {
                "query_count": payload["query_count"],
                "fetch_count": payload["fetch_count"],
                "macro_average": payload["macro_average"],
                "questions_at_or_above_two_thirds": (
                    payload["questions_at_or_above_two_thirds"]
                ),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
