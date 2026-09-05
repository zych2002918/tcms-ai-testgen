"""LLM 调用层：prompt 构造 + 输出解析 + mock 离线实现。

设计要点：
- ``MockLLMClient`` 是确定性假 LLM——不联网、可复现，是 CI/自检/演示的默认；
- ``OpenAICompatClient`` 走 DeepSeek/OpenAI 兼容 chat 接口（需 ``pip install .[llm]``），
  输出仍走同一套结构化解析，保证「真 LLM 结果也可被同一质量管线评估」。
- 解析层用「fence 抽取 + JSON 校验」：LLM 常输出 ```json ... ``` 包裹，
  先剥 fence 再 pydantic 校验，解析失败计数为 failure 而非崩溃。
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from tcms_ai_testgen.models import GeneratedCase, GenRequest

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def extract_json(text: object) -> Optional[dict[str, Any]]:
    """从 LLM 输出中抽取 JSON 对象：剥 fence -> 找首个 { ... } -> parse。"""
    if not isinstance(text, str) or not text:
        return None
    m = JSON_FENCE_RE.search(text)
    candidate = m.group(1) if m else text
    # 若整段不是 JSON，尝试截取首个 { 到末尾
    start = candidate.find("{")
    if start == -1:
        return None
    try:
        return json.loads(candidate[start:])
    except json.JSONDecodeError:
        # 兜底：截取到最后一个 } 再试一次
        end = candidate.rfind("}")
        if end <= start:
            return None
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None


def parse_cases(payload: object) -> tuple[list[GeneratedCase], int]:
    """把 LLM 返回的 JSON 解析为用例列表。

    返回 (成功用例, 失败条数)。payload 须为 dict 且含 cases/items/tests 之一；
    非法输入整体计为 1 次失败并返回空列表（流水线不抛异常）。
    """
    if not isinstance(payload, dict):
        return [], 1
    raw_list: list[Any] = []
    for key in ("cases", "items", "tests"):
        v = payload.get(key)
        if isinstance(v, list):
            raw_list = v
            break
    ok: list[GeneratedCase] = []
    fail = 0
    for raw in raw_list:
        if not isinstance(raw, dict):
            fail += 1
            continue
        try:
            case = GeneratedCase.model_validate(raw)
        except Exception:
            fail += 1
            continue
        if case.is_valid():
            ok.append(case)
        else:
            fail += 1
    return ok, fail


class LLMClient(ABC):
    """LLM 客户端抽象：输入请求，返回可解析的 JSON 文本。"""

    @abstractmethod
    def generate_cases(self, req: GenRequest) -> str:
        """返回 LLM 原始输出（应为 JSON 或 JSON fence 包裹文本）。"""


class MockLLMClient(LLMClient):
    """确定性 mock：根据需求/hints 拼出固定风格用例，离线可复现。

    命名刻意模拟「真实 LLM 会起的语义化用例名」（test_<模块>_<场景>），
    让演示数据的 exec_pass_rate 不为 0，统计口径才真实可讲。
    """

    #: 语义化场景词库（按 i 轮转），对应边界/异常/时序类测试点
    _SCENE_WORDS = ("boundary_max", "boundary_min", "timeout", "disconnect", "recovery", "flap")

    def generate_cases(self, req: GenRequest) -> str:
        cases: list[dict[str, Any]] = []
        n = req.num_cases
        # 每 6 条故意制造 1 条结构残缺样本，用于演示 parse_rate < 1 的统计
        for i in range(1, n + 1):
            if i % 6 == 0:
                cases.append({"name": f"broken_{i}", "purpose": ""})  # 缺 expected -> 解析失败
                continue
            req_src = req.requirements[(i - 1) % len(req.requirements)] if req.requirements else "通用功能"
            scene = self._SCENE_WORDS[(i - 1) % len(self._SCENE_WORDS)]
            cases.append(
                {
                    "name": f"test_{scene}",
                    "purpose": f"验证 {req.target} 在「{req_src}」下的{scene}行为",
                    "preconditions": "系统处于初始状态",
                    "steps": [f"构造输入（第 {i} 组边界）", "执行目标动作", "观察输出"],
                    "expected": "触发紧急制动并报警" if "断线" in req_src else "输出符合预期，无异常告警",
                    "covers": [str(i % max(1, len(req.requirements)))],
                    "tier": req.tier,
                }
            )
        return json.dumps({"cases": cases}, ensure_ascii=False)


class OpenAICompatClient(LLMClient):
    """DeepSeek/OpenAI 兼容 chat 客户端（可选，需 openai>=1.0）。"""

    def __init__(
        self,
        model: str = "deepseek-chat",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.3,
        timeout: float = 60.0,
    ) -> None:
        try:
            from openai import OpenAI  # 延迟导入：离线模式不需要
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("真实 LLM 模式需要 `pip install .[llm]`") from exc
        kwargs: dict[str, Any] = {"api_key": api_key or "EMPTY"}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self._temperature = temperature
        self._timeout = timeout

    def generate_cases(self, req: GenRequest) -> str:  # pragma: no cover - 真实网络路径
        from tcms_ai_testgen.prompt import build_system_prompt, build_user_prompt

        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            timeout=self._timeout,
            messages=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": build_user_prompt(req)},
            ],
        )
        return resp.choices[0].message.content or ""


def build_client(
    *,
    mock: bool = True,
    model: str = "deepseek-chat",
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LLMClient:
    """工厂：默认 mock；mock=False 时走真实兼容接口。"""
    if mock:
        return MockLLMClient()
    return OpenAICompatClient(model=model, base_url=base_url, api_key=api_key)
