"""agent.py 反思闭环测试：分类/diff 门禁/状态机/Mock 自愈闭环。

离线部分（分类/diff/状态机）不依赖上游；真实闭环（MockReflector 修 class1
失败 → round2 PASS）在上游可用时跑。
"""

from __future__ import annotations

import pytest

from tcms_ai_testgen.agent import (
    CaseOutcome,
    MockReflector,
    ReflectReport,
    _failed_names,
    _transition,
    classify_failure,
    execution_diff,
    reflect_loop,
)
from tcms_ai_testgen.asset_loader import default_upstream_root
from tcms_ai_testgen.execution import ExecutionIntent
from tcms_ai_testgen.models import GeneratedCase


def _case(name: str, execution: dict) -> GeneratedCase:
    return GeneratedCase(name=name, purpose=name, expected=name,
                         execution=ExecutionIntent.model_validate(execution))


class TestClassify:
    def test_encode_error_is_class1(self) -> None:
        out = ('EncodeError: Expected signal "AlarmLevel" value greater than or equal to 0 '
               'in message "AlarmEvent", but got -1.')
        c = _case("test_x", {"kind": "encode_bound", "setup": [], "expect": []})
        info = classify_failure(c, out)
        assert info.kind == "class1"
        assert info.signal == "AlarmLevel"
        assert info.message == "AlarmEvent"

    def test_assertion_is_class2(self) -> None:
        c = _case("test_x", {"kind": "simulate_inject", "setup": [], "expect": []})
        info = classify_failure(c, "AssertionError: assert 'Fault' == 2")
        assert info.kind == "class2"

    def test_unknown(self) -> None:
        c = _case("test_x", {"kind": "simulate_inject", "setup": [], "expect": []})
        assert classify_failure(c, "KeyboardInterrupt") .kind == "unknown"


class TestDiffGate:
    def test_identical_is_not_diff(self) -> None:
        ex = ExecutionIntent.model_validate(
            {"kind": "encode_bound", "setup": [], "expect": [
                {"op": "expect_encode_error", "args": {"message": "VehicleSpeed", "signal": "SpeedKmh", "value": 200.1}}]})
        assert execution_diff(ex, ex.model_copy(deep=True)) is False

    def test_changed_value_is_diff(self) -> None:
        a = ExecutionIntent.model_validate(
            {"kind": "encode_bound", "setup": [], "expect": [
                {"op": "expect_encode_error", "args": {"message": "VehicleSpeed", "signal": "SpeedKmh", "value": 200.1}}]})
        b = ExecutionIntent.model_validate(
            {"kind": "encode_bound", "setup": [], "expect": [
                {"op": "expect_encode_error", "args": {"message": "VehicleSpeed", "signal": "SpeedKmh", "value": 201.0}}]})
        assert execution_diff(a, b) is True

    def test_deleted_assert_is_not_diff(self) -> None:
        a = ExecutionIntent.model_validate(
            {"kind": "encode_bound", "setup": [], "expect": [
                {"op": "expect_encode_error", "args": {"message": "VehicleSpeed", "signal": "SpeedKmh", "value": 200.1}}]})
        b = ExecutionIntent.model_validate(
            {"kind": "encode_bound", "setup": [], "expect": []})  # 删断言 = 不算修
        assert execution_diff(a, b) is False

    def test_none_semantics(self) -> None:
        assert execution_diff(None, None) is False
        ex = ExecutionIntent.model_validate(
            {"kind": "simulate_inject", "setup": [], "expect": []})
        assert execution_diff(None, ex) is True


class TestTransition:
    def test_transitions(self) -> None:
        assert _transition("PASS", "PASS") == "stable"
        assert _transition("FAIL", "PASS") == "healed"
        assert _transition("FAIL", "FAIL") == "not_progressed"
        assert _transition("PASS", "FAIL") == "regressed"
        assert _transition("FAIL", None) == "skipped"


class TestReport:
    def test_self_heal_rate(self) -> None:
        r = ReflectReport(total=4, outcomes=[
            CaseOutcome(name="a", round1="PASS", round2="PASS", transition="stable"),
            CaseOutcome(name="b", round1="FAIL", round2="PASS", transition="healed"),
            CaseOutcome(name="c", round1="FAIL", round2="FAIL", transition="not_progressed"),
            CaseOutcome(name="d", round1="PASS", round2="FAIL", transition="regressed"),
        ])
        assert r.healed == 1
        assert r.self_heal_rate == 0.5  # 1/(1+1)
        d = r.as_dict()
        assert d["self_heal_rate"] == 0.5

    def test_empty(self) -> None:
        r = ReflectReport(total=0)
        assert r.self_heal_rate == 0.0


class TestFailedNames:
    def test_parse(self) -> None:
        out = "1 failed, 3 passed\nFAILED tests/x.py::test_door - AssertionError\n"
        assert _failed_names(out) == {"test_door"}


class TestMockReflector:
    def test_clamps_out_of_range_value(self) -> None:
        c = _case("test_bad", {"kind": "encode_bound", "setup": [], "expect": [
            {"op": "expect_encode_error", "args": {"message": "AlarmEvent", "signal": "AlarmLevel", "value": -1}}]})
        info = classify_failure(c, 'EncodeError: Expected signal "AlarmLevel" value greater than or equal to 0 '
                                  'in message "AlarmEvent", but got -1.')
        fixer = MockReflector(oracle_facts={("AlarmEvent", "AlarmLevel"): (0.0, 3.0)})
        fixed = fixer.fix(c, info)
        assert fixed is not None
        assert execution_diff(c.execution, fixed.execution) is True
        # value 被钳到 0
        assert fixed.execution.expect[0].args["value"] == 0

    def test_no_facts_returns_none(self) -> None:
        c = _case("test_bad", {"kind": "encode_bound", "setup": [], "expect": [
            {"op": "expect_encode_error", "args": {"message": "AlarmEvent", "signal": "AlarmLevel", "value": -1}}]})
        fixer = MockReflector(oracle_facts={})  # 缺证据
        assert fixer.fix(c, classify_failure(c, "EncodeError AlarmLevel -1")) is None

    def test_class2_not_fixed_by_mock(self) -> None:
        c = _case("test_door", {"kind": "simulate_inject", "setup": [], "expect": [
            {"op": "expect_signal", "args": {"message": "DoorControl", "signal": "Door2State", "equals": 2}}]})
        info = classify_failure(c, "AssertionError: assert 'Fault' == 2")
        fixer = MockReflector()
        assert fixer.fix(c, info) is None  # mock 只修 class1


class TestRealReflectLoop:
    """真实闭环：制造 class1 失败（越界 encode），MockReflector 应自愈。"""

    def _failing_case(self) -> GeneratedCase:
        # 期望 AlarmLevel=-1 编码成功（expect_encode_ok）→ 实际 EncodeError → FAIL
        return _case("test_alarm_level_bad", {"kind": "encode_bound", "setup": [], "expect": [
            {"op": "expect_encode_ok", "args": {"message": "AlarmEvent", "signal": "AlarmLevel", "value": -1}}]})

    def test_mock_heals_class1(self) -> None:
        root = default_upstream_root()
        if not (root / "tests" / "conftest.py").is_file():
            pytest.skip(f"上游仓库不可用: {root}")
        case = self._failing_case()
        facts = {("AlarmEvent", "AlarmLevel"): (0.0, 15.0)}  # 上游 4bit 0-15
        fixer = MockReflector(oracle_facts=facts)

        def reflector(c, info, stdout):
            return fixer.fix(c, info)

        rep = reflect_loop([case], root, reflector)
        assert rep.outcomes[0].round1 == "FAIL"
        assert rep.outcomes[0].transition in ("healed", "not_progressed")
        if rep.outcomes[0].transition == "healed":
            assert rep.self_heal_rate == 1.0

    def test_no_evidence_no_heal(self) -> None:
        """缺证据臂：oracle_facts 为空 → 无法修 → not_progressed（闭环机制诚实）。"""
        root = default_upstream_root()
        if not (root / "tests" / "conftest.py").is_file():
            pytest.skip(f"上游仓库不可用: {root}")
        case = self._failing_case()
        fixer = MockReflector(oracle_facts={})

        def reflector(c, info, stdout):
            return fixer.fix(c, info)

        rep = reflect_loop([case], root, reflector)
        o = rep.outcomes[0]
        assert o.round1 == "FAIL"
        assert o.transition in ("not_progressed", "skipped")  # 无证据修不动
