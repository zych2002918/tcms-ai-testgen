"""30 秒自检：离线跑通核心链路（导入/流水线/CLI）。CI 与面试演示共用。"""

from __future__ import annotations

import sys


def main() -> int:
    ok = True
    try:
        from tcms_ai_testgen import GenReport  # noqa: F401
        from tcms_ai_testgen.pipeline import demo_default

        report = demo_default()
        s = report.summary()
        print(f"[1/2] 流水线 OK: parsed={s['parsed']} parse_rate={s['parse_rate']} "
              f"quality={s['quality_score']} exec_pass={s['exec_pass_rate']}")
    except Exception as exc:  # pragma: no cover
        print(f"[1/2] 流水线 FAIL: {exc!r}")
        ok = False

    try:
        from tcms_ai_testgen.cli import main as cli_main  # noqa: F401
        print("[2/2] CLI 导入 OK")
    except Exception as exc:  # pragma: no cover
        print(f"[2/2] CLI FAIL: {exc!r}")
        ok = False

    print("selfcheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
