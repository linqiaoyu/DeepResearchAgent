from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from deepresearch_agent.provenance.prompt_guard import load_registry, verify_prompt_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail when prompt content drifts without a version bump.")
    parser.add_argument("--prompt-dir", default="prompts")
    parser.add_argument("--registry", default="prompts/registry.json")
    parser.add_argument("--base-ref", default="")
    args = parser.parse_args()
    registry_path = Path(args.registry)
    current = load_registry(registry_path)
    previous = _registry_at_ref(args.base_ref, registry_path) if args.base_ref else None
    errors = verify_prompt_registry(Path(args.prompt_dir), current, previous_registry=previous)
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print(f"prompt drift guard passed: {len(current)} prompts")


def _registry_at_ref(ref: str, path: Path) -> dict[str, dict[str, str]] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path.as_posix()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    prompts = payload.get("prompts", {})
    return {
        str(name): {"version": str(entry["version"]), "sha256": str(entry["sha256"])}
        for name, entry in prompts.items()
    }


if __name__ == "__main__":
    main()
