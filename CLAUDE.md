# CLAUDE.md

本仓库的开发规范以 `AGENTS.md` 为唯一准据，本文件仅补充操作细节。任何流程、纪律、
铁律与协作规则一律去 `AGENTS.md` 查，本文件不复述、不改写、不补充。

## 环境

- 解释器：`.venv/bin/python`（Python 3.12.10）。不要用系统 `python`。
- 每条命令都要带 `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1`。
- Ruff 精确版本 `0.15.15`（`.venv` 与 CI 一致）。注意 `pyproject.toml` 写的是
  `ruff>=0.5`，精确版本只钉在 `.github/workflows/ci.yml`，两处不一致是已知状况。

## 闸门命令（全部本地实测通过，2026-07-25）

```bash
# 全量测试 —— 374 tests
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_SEARCH_PROVIDER=fixture \
DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture DEEPRESEARCH_MODE=deterministic \
.venv/bin/python -m unittest discover -s tests

# Ruff —— All checks passed!
PYTHONPATH=src .venv/bin/python -m ruff check src tests scripts

# prompt 漂移 —— prompt drift guard passed: 5 prompts
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/check_prompt_drift.py

# characterization（两个题面逐字快照）—— Ran 2 tests, OK
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_snapshot_run

# chaos（8 场景端到端故障注入）—— Ran 8 tests, OK
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DEEPRESEARCH_SEARCH_PROVIDER=fixture \
DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture .venv/bin/python -m unittest discover -s tests/chaos

# 静态站构建 —— built site/dist, files 13, validation ok
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_site.py
```

## 目录约定

| 路径 | 用途 | 追踪 |
| --- | --- | --- |
| `src/deepresearch_agent/` | 包源码（84 文件 / 19005 行） | 是 |
| `tests/{unit,integration,evaluation,chaos}/` | 374 个测试；`tests/golden_output/` 是逐字行为快照 | 是 |
| `scripts/` | 29 个 CLI 工具（运行、评测、血统、回放、站点构建） | 是 |
| `docs/decisions/<编号>/` | 对外发布的脱敏决策记录 | 是 |
| `data/golden_set/`、`data/mock_data/`、`data/demo/` | 受管评测与 fixture 资产 | 是 |
| `_collab/<编号>_<短名>/` | 任务提示词、执行报告、本地验证产物 | 否（gitignored） |
| `runs/`、`artifacts/`、`data/runtime/`、`site/dist/`、`*.db` | 运行产物 | 否（gitignored） |

## 陷阱

- **漏 `PYTHONPATH=src` 会产生 import error，不是真实测试失败。** 实测：带上是
  `Ran 374 tests ... OK`，不带是 `Ran 338 tests ... FAILED (errors=17)`。这 17 条是
  模块导入失败，不是断言失败。见到 `errors=17` 先查环境变量再查代码——历史上曾
  因此把一轮合并误判为失败。
- `scripts/replay_trajectory.py` 走的 `replay_trajectory()` 会直接写
  `os.environ["DEEPRESEARCH_MODE"]="deterministic"` 且不还原。同进程内后续代码会
  受影响。
- 全量套件在完全干净的环境（`env -i`，无任何 `DEEPRESEARCH_*`）下同样 374 全绿，
  不依赖 `.env`。未发现 flaky 或时序敏感测试。
