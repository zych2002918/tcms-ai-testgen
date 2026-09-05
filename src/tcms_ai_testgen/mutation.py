"""变异杀毒实验（P3 质量证据）—— 无需真 LLM 也能证明生成用例有效。

审查裁定（docs/decisions.md D1-E）：compile_rate / pass_rate 本身是幸存者
偏差——用例若只是「回声 spec」会全过但毫无杀毒力。**变异杀毒**才是质量证据：
把被测对象（上游 tcms-can-test 的 simulator/faultlevel 行为）翻转成「带 bug 的
实现」，再跑同一批生成用例。能识别出变异的用例 = 有真实断言力（kills the
mutant）；测不出变异的用例 = 断言太弱或根本没测到该行为。

方法（不改上游一行源码）：
    生成 pytest 文件时，在文件头部注入一个 conftest 级 fixture 把目标类方法
    monkeypatch 成变异版；变异版本与原始版本用**同一批生成用例**跑，
    统计：
        killed  = 在变异版上 FAIL 的用例数（成功杀毒）
        survived = 在变异版上仍 PASS 的用例数（漏网）
        kill_rate = killed / (killed + survived)
    注意：只有「原始版 PASS」的用例才纳入杀毒统计（本来就失败的用例在变异
    版上也失败不构成杀毒——它没有证明任何东西）。

设计：
    - mutation 描述 = {name, patch_lines}：patch_lines 是注入文件的 python
      代码（monkeypatch fixture），编译期校验只允许 import 上游 + 赋值。
    - 安全：变异代码只存在于**生成的临时 pytest 文件**，由 subprocess 在
      上游 venv 跑；tcms-ai-testgen 仓库与上游源码均不被修改。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from tcms_ai_testgen.executor_real import _HEADER, RealExecResult, compile_case
from tcms_ai_testgen.models import GeneratedCase

#: 变异定义：patch 代码 + 相关用例判定（字符串匹配 execution/自然语言）。
#: 相关 = 该变异翻转的行为被此用例断言覆盖（应被杀）。
MutationSpec = dict[str, object]


def _relevant_door(case: GeneratedCase) -> bool:
    if not case.execution:
        return False
    return any(
        "DoorControl" in str(s.args) for s in case.execution.setup + case.execution.expect
    ) or "车门" in (case.purpose + case.expected)


def _relevant_encode(case: GeneratedCase) -> bool:
    if not case.execution:
        return False
    return any(
        s.op == "expect_encode_error" or s.op == "expect_encode_ok" for s in case.execution.expect
    )


def _relevant_overspeed(case: GeneratedCase) -> bool:
    if not case.execution:
        return False
    return case.execution.fault == "overspeed" or "overspeed" in (case.purpose + case.expected).lower()


#: 内置变异库：每个 = 对上游一个真实行为做「安全翻转」（有意引入 bug）。
#: patch 代码用 autouse fixture 在测试前替换类方法（test 文件 import 上游类）。
MUTATIONS: dict[str, MutationSpec] = {
    # M1: 车门故障不再置 Fault（门状态 2 被吞成 Closed 0）→ 车门故障断言应 fail
    "door_fault_ignored": {
        "desc": "车门故障被吞成 Closed（set_door_state 变异）",
        "targets": "DoorControl 信号断言（Fault）",
        "patch": """
import tcms.simulator as _sim
_orig_set_door = _sim.TCMSNodeSimulator.set_door_state

def _buggy_set_door(self, door_index, state):
    if state == 2:
        state = 0  # 变异：Fault 被吞成 Closed
    _orig_set_door(self, door_index, state)

_sim.TCMSNodeSimulator.set_door_state = _buggy_set_door
""",
        "relevant": _relevant_door,
    },
    # M2: 编码不再拒绝越界（db.encode_message 直通不校验）→ 越界拒绝断言应 fail
    "encode_never_rejects": {
        "desc": "越界编码不再抛 EncodeError",
        "targets": "expect_encode_error / expect_encode_ok",
        "patch": """
import cantools.database.can as _can

def _lax_encode_factory(self, message_name_or_tree, data, scaling=True, padding=False):
    # 变异：无条件返回零填充帧，永不抛 EncodeError
    msg = self.get_message_by_name(message_name_or_tree) if isinstance(message_name_or_tree, str) else message_name_or_tree
    return b"\\x00" * msg.length

_can.Database.encode_message = _lax_encode_factory
""",
        "relevant": _relevant_encode,
    },
    # M3: overspeed 处置动作被改成 emergency_brake（本应 derate）→ 故障场景断言应 fail
    "overspeed_action_flipped": {
        "desc": "overspeed 处置动作被翻转（derate→emergency_brake）",
        "targets": "expect_action(overspeed)",
        "patch": """
import tcms.faultlevel as _fl
_orig_action = _fl.action_for

def _flipped_action(fault_name, mode="auto"):
    if fault_name == "overspeed":
        return "emergency_brake"  # 变异：处置动作被翻转
    return _orig_action(fault_name, mode)

_fl.action_for = _flipped_action
""",
        "relevant": _relevant_overspeed,
    },
}

#: 兼容旧引用（MUTATION_TARGETS 由 desc/targets 取代）
MUTATION_TARGETS: dict[str, str] = {
    name: str(spec["targets"]) for name, spec in MUTATIONS.items()
}


def mutation_patch(name: str) -> str:
    """取内置变异 patch 代码；未知变异抛 KeyError。"""
    if name not in MUTATIONS:
        raise KeyError(f"未知变异: {name}（可用 {list(MUTATIONS)}）")
    return str(MUTATIONS[name]["patch"])


def mutation_relevant(name: str) -> Callable[[GeneratedCase], bool]:
    """取变异的「相关用例」判定函数。"""
    spec = MUTATIONS[name]
    fn = spec.get("relevant")
    if fn is None:
        return lambda case: True
    return fn  # type: ignore[return-value]


def list_mutations() -> list[str]:
    return list(MUTATIONS)


@dataclass
class MutationResult:
    """一批用例对单个变异的杀毒统计。

    口径（docs/metrics.md）：kill_rate 只对「与该变异相关的用例」计算——
    把无关用例放进分母会让杀毒率虚低（它们本就该 survive）。
    """

    mutation: str
    total: int  # 原始版 PASS 的用例数
    relevant: int  # 与变异相关的用例数（应被杀）
    killed: int  # 相关用例中被杀的数（变异版 FAIL）
    survived: int  # 相关用例中漏网的数（变异版仍 PASS）
    stdout: str = ""

    @property
    def kill_rate(self) -> float:
        return self.killed / self.relevant if self.relevant else 0.0

    @property
    def overall_kill_rate(self) -> float:
        """朴素杀毒率（分母=全部用例）——文档对比用。"""
        return self.killed / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "mutation": self.mutation,
            "total": self.total,
            "relevant": self.relevant,
            "killed": self.killed,
            "survived": self.survived,
            "kill_rate": round(self.kill_rate, 3),
            "overall_kill_rate": round(self.overall_kill_rate, 3),
        }


def _counts_from_stdout(stdout: str) -> tuple[int, int]:
    passed = 0
    failed = 0
    for ln in stdout.splitlines():
        m = re.search(r"(\d+) passed", ln)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", ln)
        if m:
            failed = int(m.group(1))
    return passed, failed


def _compile_with_patch(cases: list[GeneratedCase], patch_code: str) -> str:
    """把用例编译为 pytest 文件，并在头部注入变异 patch fixture。"""
    bodies: list[str] = []
    for case in cases:
        body = compile_case(case)
        if body is not None:
            bodies.append(body)
    code = _HEADER + "\n"
    code += """
import pytest


@pytest.fixture(autouse=True)
def _mutate(monkeypatch):
    # 注入变异：替换被测对象行为（见 mutation 库）
"""
    # patch 代码缩进进 fixture 体
    for ln in patch_code.strip().splitlines():
        code += "    " + ln + "\n"
    code += "\n\n" + "\n\n".join(bodies) + "\n"
    return code


def run_mutation(
    cases: list[GeneratedCase],
    mutation: str,
    upstream_root: str | Path,
    *,
    keep_artifacts: bool = False,
    baseline: Optional[RealExecResult] = None,
) -> MutationResult:
    """跑单个变异：生成变异版 pytest 并在上游执行，返回杀毒统计。

    口径：kill_rate 分母 = 相关用例（relevant），非全部用例。
    baseline 传原始版结果可跳过重复跑原始版（默认自动跑一遍拿 total）。
    """
    root = Path(upstream_root)
    patch = mutation_patch(mutation)
    relevant_fn = mutation_relevant(mutation)
    relevant_names = {c.name for c in cases if relevant_fn(c) and compile_case(c) is not None}

    # 先跑原始版（拿 baseline total = 原始 PASS 数）
    if baseline is None:
        from tcms_ai_testgen.executor_real import run_real

        baseline = run_real(cases, root)

    if not (root / "tests" / "conftest.py").is_file():
        raise FileNotFoundError(f"非 tcms-can-test 仓库根: {root}")
    tests_dir = root / "tests"
    gen_path = tests_dir / "test_ai_generated_mutant.py"
    gen_path.write_text(_compile_with_patch(cases, patch), encoding="utf-8")

    py = root / ".venv" / "Scripts" / "python.exe"
    cmd = [str(py) if py else "python", "-m", "pytest", str(gen_path), "-q", "--no-header"]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    stdout = proc.stdout
    # 变异版统计：passed（survived）/ failed（killed）
    mut_passed, mut_failed = _counts_from_stdout(stdout)
    baseline_failed = baseline.failed if baseline else 0
    total = baseline.passed if baseline else 0
    # 变异版上失败数 - 原始版就失败的 = 真正被变异杀死的用例
    killed_all = max(0, mut_failed - baseline_failed)
    # 但精准 kill_rate 只算相关用例：相关用例数 <= total
    # 防御：变异版收集为 0 时无法统计（如 patch 语法错），如实返回 0
    if mut_passed + mut_failed == 0:
        killed_all = 0

    if not keep_artifacts:
        try:
            gen_path.unlink()
        except OSError:
            pass

    return MutationResult(
        mutation=mutation,
        total=total,
        relevant=len(relevant_names),
        killed=killed_all,
        survived=max(0, len(relevant_names) - killed_all),
        stdout=stdout,
    )


__all__ = [
    "MUTATIONS",
    "MUTATION_TARGETS",
    "MutationResult",
    "list_mutations",
    "mutation_patch",
    "run_mutation",
]
