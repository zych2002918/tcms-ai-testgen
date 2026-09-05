"""mutation 变异杀毒测试：变异库完整性 + 相关用例判定 + 真实杀毒（上游可用时）。"""

from __future__ import annotations

import pytest

from tcms_ai_testgen.execution import ExecutionIntent
from tcms_ai_testgen.models import GeneratedCase
from tcms_ai_testgen.mutation import (
    MUTATION_TARGETS,
    MUTATIONS,
    MutationResult,
    _compile_with_patch,
    _failed_case_names,
    list_mutations,
    mutation_patch,
    mutation_relevant,
    run_mutation,
)


def _case(name: str, execution: dict) -> GeneratedCase:
    return GeneratedCase(name=name, purpose=name, expected=name,
                         execution=ExecutionIntent.model_validate(execution))


_ENCODE = {
    "kind": "encode_bound", "setup": [], "expect": [
        {"op": "expect_encode_error", "args": {"message": "VehicleSpeed", "signal": "SpeedKmh", "value": 200.1}}]}
_DOOR = {
    "kind": "simulate_inject",
    "setup": [{"op": "set_door_state", "args": {"index": 1, "state": 2}}],
    "expect": [{"op": "expect_signal", "args": {"message": "DoorControl", "signal": "Door2State", "equals": "Fault"}}]}
_OVERSPEED = {
    "kind": "fault_scenario", "fault": "overspeed",
    "expect": [{"op": "expect_action", "args": {"fault": "overspeed", "action": "derate"}}]}


class TestMutationLibrary:
    def test_three_mutations(self) -> None:
        assert set(list_mutations()) == {"door_fault_ignored", "encode_never_rejects", "overspeed_action_flipped"}

    def test_patch_present(self) -> None:
        for name in list_mutations():
            patch = mutation_patch(name)
            assert "import" in patch  # patch 至少含 import
            assert len(patch) > 50

    def test_targets_aligned(self) -> None:
        assert set(MUTATION_TARGETS) == set(MUTATIONS)
        for name in MUTATIONS:
            assert MUTATIONS[name]["desc"]
            assert MUTATIONS[name]["targets"]

    def test_relevant_functions(self) -> None:
        assert mutation_relevant("door_fault_ignored")(_case("d", _DOOR)) is True
        assert mutation_relevant("door_fault_ignored")(_case("e", _ENCODE)) is False
        assert mutation_relevant("encode_never_rejects")(_case("e", _ENCODE)) is True
        assert mutation_relevant("encode_never_rejects")(_case("o", _OVERSPEED)) is False
        assert mutation_relevant("overspeed_action_flipped")(_case("o", _OVERSPEED)) is True
        assert mutation_relevant("overspeed_action_flipped")(_case("e", _ENCODE)) is False

    def test_unknown_mutation(self) -> None:
        with pytest.raises(KeyError):
            mutation_patch("nope")
        with pytest.raises(KeyError):
            mutation_relevant("nope")


class TestMutationResult:
    def test_kill_rate_relevant_denominator(self) -> None:
        r = MutationResult(mutation="m", total=10, relevant=2, killed=2, survived=0)
        assert r.kill_rate == 1.0
        assert r.overall_kill_rate == 0.2  # 朴素口径分母=全部

    def test_zero_relevant_kill_rate_zero(self) -> None:
        r = MutationResult(mutation="m", total=0, relevant=0, killed=0, survived=0)
        assert r.kill_rate == 0.0

    def test_as_dict(self) -> None:
        r = MutationResult(mutation="m", total=4, relevant=1, killed=1, survived=0)
        d = r.as_dict()
        assert d["kill_rate"] == 1.0


class TestHelpers:
    def test_failed_case_names_parsing(self) -> None:
        out = "FAILED tests/test_ai_generated_mutant.py::test_door_fault - AssertionError: x\n"
        assert _failed_case_names(out) == {"test_door_fault"}
        assert _failed_case_names("3 passed in 1s") == set()

    def test_compile_with_patch_injects_fixture(self) -> None:
        c = _case("test_door", _DOOR)
        code = _compile_with_patch([c], "import tcms.simulator as _sim\n_orig = 1\n")
        assert "@pytest.fixture(autouse=True)" in code
        assert "_mutate" in code
        assert "test_door" in code
        assert "import tcms.simulator" in code


class TestRealMutation:
    """真实杀毒：上游可用时跑（成本受控）。"""

    def _cases(self) -> list[GeneratedCase]:
        return [
            _case("test_speed_reject", _ENCODE),
            _case("test_speed_ok", {
                "kind": "encode_bound", "setup": [], "expect": [
                    {"op": "expect_encode_ok", "args": {"message": "VehicleSpeed", "signal": "SpeedKmh", "value": 200.0}}]}),
            _case("test_door_fault", _DOOR),
            _case("test_overspeed_act", _OVERSPEED),
        ]

    def test_all_mutations_kill_relevant(self) -> None:
        from tcms_ai_testgen.asset_loader import default_upstream_root
        from tcms_ai_testgen.executor_real import run_real

        root = default_upstream_root()
        if not (root / "tests" / "conftest.py").is_file():
            pytest.skip(f"上游仓库不可用: {root}")
        cases = self._cases()
        base = run_real(cases, root)
        assert base.passed == 4  # baseline 全过
        for m in list_mutations():
            res = run_mutation(cases, m, root, baseline=base)
            assert res.relevant >= 1
            assert res.killed == res.relevant  # 相关用例全被杀
            assert res.kill_rate == 1.0
