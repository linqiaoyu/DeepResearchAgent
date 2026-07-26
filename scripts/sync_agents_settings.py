from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path

from deepresearch_agent.provenance.manifest import FLAG_CLASSIFICATIONS
from deepresearch_agent.settings import Settings, boolean_setting_defaults


BEGIN_MARKER = "<!-- BEGIN GENERATED SETTINGS DEFAULTS -->"
END_MARKER = "<!-- END GENERATED SETTINGS DEFAULTS -->"
ENV_BEGIN_MARKER = "# BEGIN GENERATED SETTINGS DEFAULTS"
ENV_END_MARKER = "# END GENERATED SETTINGS DEFAULTS"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env.example"
DEFAULT_README_PATH = PROJECT_ROOT / "README.md"


def _validated_defaults() -> dict[str, bool]:
    defaults = boolean_setting_defaults()
    classified = set(FLAG_CLASSIFICATIONS)
    documented = set(defaults)
    if classified != documented:
        missing = sorted(documented - classified)
        unknown = sorted(classified - documented)
        raise ValueError(
            "Settings/manifest flag sets differ: "
            f"missing classifications={missing}; unknown classifications={unknown}"
        )
    return defaults


def render_generated_block() -> str:
    defaults = _validated_defaults()
    rows = [
        BEGIN_MARKER,
        "| 环境变量 | 默认值 | manifest 分类 |",
        "|---|---:|---|",
    ]
    rows.extend(
        f"| `{name}` | `{str(defaults[name]).lower()}` | "
        f"`{FLAG_CLASSIFICATIONS[name]}` |"
        for name in sorted(defaults)
    )
    rows.append(END_MARKER)
    return "\n".join(rows)


def render_environment_block() -> str:
    defaults = _validated_defaults()
    runtime_defaults = Settings(storage_path=Path("settings-default-probe.db"))
    rows = [
        ENV_BEGIN_MARKER,
        "# Generated from deepresearch_agent.settings.Settings; do not edit by hand.",
    ]
    rows.extend(
        f"{name}={str(defaults[name]).lower()}"
        for name in sorted(defaults)
    )
    rows.append(
        "DEEPRESEARCH_DYNAMIC_CAPABILITY_RULES_JSON="
        f"{runtime_defaults.dynamic_capability_rules_json}"
    )
    rows.append(ENV_END_MARKER)
    return "\n".join(rows)


def _replace_marked_block(
    document: str,
    block: str,
    *,
    begin_marker: str,
    end_marker: str,
    label: str,
) -> str:
    if document.count(begin_marker) != 1 or document.count(end_marker) != 1:
        raise ValueError(
            f"{label} must contain exactly one generated Settings block"
        )
    start = document.index(begin_marker)
    end = document.index(end_marker, start) + len(end_marker)
    if end <= start:
        raise ValueError(f"{label} generated Settings markers are out of order")
    return document[:start] + block + document[end:]


def replace_generated_block(document: str, block: str) -> str:
    return _replace_marked_block(
        document,
        block,
        begin_marker=BEGIN_MARKER,
        end_marker=END_MARKER,
        label="AGENTS.md",
    )


def expected_document(path: Path) -> str:
    current = path.read_text(encoding="utf-8")
    return replace_generated_block(current, render_generated_block())


def expected_environment_document(path: Path) -> str:
    current = path.read_text(encoding="utf-8")
    return _replace_marked_block(
        current,
        render_environment_block(),
        begin_marker=ENV_BEGIN_MARKER,
        end_marker=ENV_END_MARKER,
        label=".env.example",
    )


def expected_readme_document(path: Path) -> str:
    current = path.read_text(encoding="utf-8")
    defaults = _validated_defaults()
    names = "|".join(re.escape(name) for name in sorted(defaults, key=len, reverse=True))
    pattern = re.compile(rf"\b(?P<name>{names})=(?P<value>true|false)\b")
    return pattern.sub(
        lambda match: (
            f"{match.group('name')}="
            f"{str(defaults[match.group('name')]).lower()}"
        ),
        current,
    )


def _check_expected(path: Path, expected: str, *, label: str) -> bool:
    current = path.read_text(encoding="utf-8")
    if current == expected:
        return True
    print(f"{label} Settings defaults are stale:")
    print(
        "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=str(path),
                tofile="generated from Settings",
            )
        ),
        end="",
    )
    return False


def check_document(path: Path) -> bool:
    return _check_expected(
        path,
        expected_document(path),
        label="AGENTS.md generated",
    )


def check_environment_document(path: Path) -> bool:
    return _check_expected(
        path,
        expected_environment_document(path),
        label=".env.example generated",
    )


def check_readme_document(path: Path) -> bool:
    return _check_expected(
        path,
        expected_readme_document(path),
        label="README.md documented",
    )


def check_all_documents(
    agents_path: Path = DEFAULT_AGENTS_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    readme_path: Path = DEFAULT_README_PATH,
) -> bool:
    results = [
        check_document(agents_path),
        check_environment_document(env_path),
        check_readme_document(readme_path),
    ]
    return all(results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or verify Settings defaults in AGENTS.md, .env.example, "
            "and README.md."
        )
    )
    parser.add_argument("--agents-path", type=Path, default=DEFAULT_AGENTS_PATH)
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--readme-path", type=Path, default=DEFAULT_README_PATH)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()

    agents_path = args.agents_path.resolve()
    env_path = args.env_path.resolve()
    readme_path = args.readme_path.resolve()
    if args.write:
        agents_path.write_text(expected_document(agents_path), encoding="utf-8")
        env_path.write_text(
            expected_environment_document(env_path),
            encoding="utf-8",
        )
        readme_path.write_text(
            expected_readme_document(readme_path),
            encoding="utf-8",
        )
        print(
            "updated Settings defaults: "
            f"{agents_path}, {env_path}, {readme_path}"
        )
        return
    if not check_all_documents(agents_path, env_path, readme_path):
        raise SystemExit(1)
    print(
        "Settings defaults check passed for AGENTS.md, .env.example, "
        f"and README.md: {len(boolean_setting_defaults())} flags"
    )


if __name__ == "__main__":
    main()
