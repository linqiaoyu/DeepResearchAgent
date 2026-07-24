from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_registry(path: Path) -> dict[str, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    prompts = payload.get("prompts")
    if not isinstance(prompts, dict):
        raise ValueError("prompt registry must contain a prompts object")
    return {
        str(name): {"version": str(entry["version"]), "sha256": str(entry["sha256"])}
        for name, entry in prompts.items()
    }


def verify_prompt_registry(
    prompt_dir: Path,
    registry: dict[str, dict[str, str]],
    *,
    previous_registry: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(prompt_dir.glob("*.md"))
    }
    if set(actual) != set(registry):
        errors.append(
            f"registry file set differs: actual={sorted(actual)} registered={sorted(registry)}"
        )
    for name, digest in actual.items():
        entry = registry.get(name)
        if entry and entry["sha256"] != digest:
            errors.append(f"{name}: content hash changed; update registry hash and bump version")
    if previous_registry:
        for name, entry in registry.items():
            previous = previous_registry.get(name)
            if previous and entry["sha256"] != previous["sha256"]:
                if entry["version"] == previous["version"]:
                    errors.append(f"{name}: hash changed without a version bump")
    return errors


def registry_json(registry: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {"prompts": registry}
