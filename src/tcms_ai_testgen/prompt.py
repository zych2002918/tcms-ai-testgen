"""Prompt 构造：把生成请求转成给 LLM 的结构化指令。

Prompt 工程要点（本项目想展示的「工程化 prompt」能力）：
- 系统提示词固定输出契约（JSON Schema 语义），少解释多示例；
- 用户提示词把需求/hints/数量注入，并要求每条用例可追溯到需求；
- 显式要求输出 `````json ... ````` fence，降低解析失败率。
"""

from __future__ import annotations

from tcms_ai_testgen.models import GenRequest

_SYSTEM_PROMPT = """你是一位资深的软件测试工程师，擅长为安全关键系统设计测试用例。
请根据给定的被测对象与需求，生成 JSON 数组（字段见下），不要输出任何解释。

输出 JSON 结构：
{
  "cases": [
    {
      "name": "test_<场景语义名>",        // pytest 风格，小写下划线
      "purpose": "用例目的，对应哪条需求",
      "preconditions": "前置条件",
      "steps": ["步骤1", "步骤2"],
      "expected": "明确可判定的预期结果",
      "covers": ["需求编号或下标"],
      "tier": "smoke | safety | regression"
    }
  ]
}

要求：
1. 每条用例必须能追溯到需求，covers 不能为空；
2. 优先覆盖边界值、异常、时序类场景；
3. expected 必须是可执行断言的语言，禁止模糊表述；
4. 只输出 ```json fence 包裹的 JSON。"""


def build_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_user_prompt(req: GenRequest) -> str:
    lines: list[str] = []
    lines.append(f"被测对象：{req.target}")
    if req.requirements:
        lines.append("需求清单：")
        lines.extend(f"- [{i}] {r}" for i, r in enumerate(req.requirements))
    if req.hints:
        lines.append("重点场景提示：")
        lines.extend(f"- {h}" for h in req.hints)
    lines.append(f"请生成 {req.num_cases} 条用例，tier 统一为 {req.tier}。")
    return "\n".join(lines)
