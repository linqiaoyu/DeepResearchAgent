from __future__ import annotations

import importlib.metadata
import site
import subprocess
import sys
from pathlib import Path


def _editable_pth_files() -> list[Path]:
    return [path for directory in site.getsitepackages() for path in Path(directory).glob("__editable__*.pth")]


def main() -> None:
    repaired: list[str] = []
    for path in _editable_pth_files():
        subprocess.run(["chflags", "nohidden", str(path)], check=True)
        repaired.append(str(path))
        source_path = path.read_text(encoding="utf-8").strip()
        if source_path and source_path not in sys.path:
            sys.path.insert(0, source_path)
    import deepresearch_agent

    print(f"executable={sys.executable}")
    print(f"package={deepresearch_agent.__file__}")
    print(f"pth_repaired={repaired}")
    for name in ("fastapi", "langgraph", "litellm", "pypdf", "ruff"):
        print(f"{name}={importlib.metadata.version(name)}")

    hook_installer = Path(__file__).with_name("install_hooks.py")
    completed = subprocess.run([sys.executable, str(hook_installer)], check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
