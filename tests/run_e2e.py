"""E2E 测试入口。

用法：
    uv run python tests/run_e2e.py
    uv run python tests/run_e2e.py greeting knowledge_pe
    uv run python tests/run_e2e.py single_stock_name --output .local/my_run
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))  # 让 tests.e2e.* 可被导入

from tests.e2e.runner import run_all


def main():
    parser = argparse.ArgumentParser(description="A股投研助手 E2E 场景测试")
    parser.add_argument(
        "scenarios",
        nargs="*",
        help="指定场景 ID（不填则跑全部）",
    )
    parser.add_argument(
        "--output",
        default=".local/e2e_runs",
        help="输出目录（默认 .local/e2e_runs）",
    )
    args = parser.parse_args()

    summary = run_all(
        scenario_ids=args.scenarios or None,
        output_base=args.output,
    )

    failed = [s for s in summary if not s["ok"]]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
