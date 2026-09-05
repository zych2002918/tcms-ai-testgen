"""P2 真实执行器测试：编译逻辑（纯离线）+ 真实执行（上游可用时）。

编译断言不依赖上游仓库；真实执行用例在 tcms-can-test 存在时跑
（不存在自动 skip，CI 本仓库不强制依赖上游）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tcms_ai_testgen.executor_real import (
    RealExecResult,
    _compile_simulator,
    compile_case,
    run_real,
)
from tcms_ai_testgen.models import GeneratedCase


def _case(name: str, purpose: str, expected: str, **kw) -> GeneratedCase:
    return GeneratedCase(name=name, purpose=purpose, expected=expected, **kw)


class TestCompileEncodeBound:
    def test_reject_speed_over_max(self) -> None:
        c = _case("test_speed_over_max_rejected", "车速越界应被编码拒绝", "编码抛出 EncodeError")
        src = compile_case(c)
        assert src is not None
        assert "pytest.raises(EncodeError)" in src
        assert "SpeedKmh=200.1" in src

    def test_accept_speed_physical_max(self) -> None:
        c = _case("test_speed_max_encodes", "物理上限可编码", "编码成功且长度 8")
        src = compile_case(c)
        assert src is not None
        assert "assert len(data) == 8" in src
        assert "SpeedKmh=200.0" in src

    def test_handle_over_max_rejected(self) -> None:
        c = _case("test_handle_over_max", "手柄级位越界", "编码拒绝")
        src = compile_case(c)
        assert src is not None
        assert "HandlePosition=17" in src

    def test_soc_reject(self) -> None:
        c = _case("test_soc_over_100", "SOC 越界", "拒绝编码")
        src = compile_case(c)
        assert src is not None
        assert "SocPercent=101" in src

    def test_unmatched_returns_none(self) -> None:
        c = _case("test_unknown_thing", "一些无关需求", "无明确动作")
        assert compile_case(c) is None

    def test_broken_name_not_compiled(self) -> None:
        c = _case("gen_1", "车速越界", "拒绝")
        assert compile_case(c) is None


class TestCompileSimulator:
    def test_overspeed_inject(self) -> None:
        c = _case("test_overspeed_alarm", "超速触发报警", "总线出现超速报警")
        src = _compile_simulator(c)
        assert src is not None
        assert "set_speed(165.0)" in src
        assert "simulator" in src

    def test_door_fault(self) -> None:
        c = _case("test_door_fault_blocks", "车门故障禁止发车", "门状态 Fault")
        src = _compile_simulator(c)
        assert src is not None
        assert '"Fault"' in src  # 真实解码为 VAL_ 枚举字符串

    def test_heartbeat_loss(self) -> None:
        c = _case("test_heartbeat_loss", "心跳丢失应检测", "0 帧心跳")
        src = _compile_simulator(c)
        assert src is not None
        assert "stop_message" in src

    def test_unmatched_simulator_returns_none(self) -> None:
        c = _case("test_whatever", "任意无关", "无关预期")
        assert _compile_simulator(c) is None


class TestRealExec:
    """真实执行：上游 tcms-can-test 存在时才跑（成本受控、CI 不依赖）。"""

    def _curated(self) -> list[GeneratedCase]:
        return [
            _case("test_speed_over_max_rejected", "车速越界应被编码拒绝", "编码抛出 EncodeError"),
            _case("test_speed_max_encodes", "物理上限可编码", "编码成功且长度 8"),
            _case("test_handle_over_max_rejected", "手柄级位越界应被拒绝", "编码抛出 EncodeError"),
        ]

    def test_real_exec_pass_on_upstream(self) -> None:
        from tcms_ai_testgen.asset_loader import default_upstream_root

        root = default_upstream_root()
        if not (root / "tests" / "conftest.py").is_file():
            pytest.skip(f"上游仓库不可用: {root}")
        res = run_real(self._curated(), root)
        assert isinstance(res, RealExecResult)
        assert res.total == 3
        assert res.compiled == 3
        assert res.passed == 3
        assert res.failed == 0
        assert res.exec_pass_rate == 1.0

    def test_run_real_uncompiled_all(self) -> None:
        # 无一条可编译：不触发上游执行，纯逻辑返回
        cases = [_case("test_abc", "无关", "无关预期")]
        res = run_real(cases, Path("."))
        assert res.total == 1
        assert res.compiled == 0
        assert res.exec_pass_rate == 0.0

    def test_run_real_bad_root_raises(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(FileNotFoundError, match="非 tcms-can-test"):
                run_real(self._curated(), td)
