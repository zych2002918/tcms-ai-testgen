# tcms-ai-testgen

**让测试平台学会自己写测试 —— LLM 测试用例生成器（TCMS CAN 版）**

> 从 DBC 信号 / 安全需求 / 场景模板生成结构化测试用例，并对生成质量做
> **确定性量化评估**（解析率 / 执行通过率 / LLM-as-judge 质量分）。
>
> 设计动机：作者此前手写了 [tcms-can-test](https://github.com/zych2002918/tcms-can-test)
> 的 777 个 pytest 用例（语句覆盖率 98.00%）。本项目回答一个问题：
> **如果让 LLM 来写这些用例，我们如何证明它写得"好"？**
> —— 答案是把「质量评估」本身做成一条可复现的工程流水线。

## 特性

- 🧪 **质量可度量**：解析率、确定性执行通过率、judge 质量分（0-100）三指标量化生成结果
- 🔌 **离线可复现**：默认 MockLLM 客户端，不联网即可跑通全链路（CI / 自检 / 演示零依赖）
- 🏭 **可切换真模型**：DeepSeek/OpenAI 兼容接口，同一质量管线评估真实 LLM 输出
- 🛡 **失败不崩溃**：LLM 输出无法解析时计为 failure，流水线永远返回可量化报告
- 📦 **工程同款水准**：29 测试 / 覆盖率 93% / ruff / CI（沿用 tcms-can-test 验收标准）

## 快速开始

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -e ".[test]"

# 30 秒自检（离线 mock）
python scripts/selfcheck.py

# 跑默认演示（EBM 紧急制动场景，mock）
python -m tcms_ai_testgen.cli --num 8

# 真实 LLM（需 pip install .[llm]，配置 DEEPSEEK_API_KEY）
python -m tcms_ai_testgen.cli --llm --target "ATP 超速防护"
```

## 流水线设计

```
需求/信号/场景模板 ──> prompt 构造 ──> LLM（mock/真实）──> 原始文本
                                                        │
                 ┌──────────────────────────────────────┤
                 ▼                                      ▼
        确定性执行器（编译率/通过率）         结构化解析（解析率，失败计数）
                 │                                      │
                 └──────────────┬───────────────────────┘
                                ▼
                LLM-as-judge 质量分（0-100）──> GenReport（JSON 可序列化）
```

- `models.py`  — 数据契约（pydantic）：`GenRequest` / `GeneratedCase` / `GenReport`
- `prompt.py`  — prompt 工程：固定输出契约 + fence + 需求可追溯要求
- `llm.py`     — 客户端抽象：`MockLLMClient`（确定性）/ `OpenAICompatClient`（真实）
- `executor.py`— 确定性执行器：把自然语言用例映射到可执行检查（compile/pass 口径）
- `judge.py`   — 质量评分：结构完整度 + 需求可追溯 + 场景设计（边界/异常）
- `pipeline.py`— 编排：生成 → 解析 → 执行 → 打分，永不抛业务异常

## 质量口径（面试可讲）

| 指标 | 含义 | 现状（mock 演示） |
|---|---|---|
| `parse_rate` | 结构化解析成功率 | ~85%（mock 故意注入残缺样本验证统计） |
| `exec_pass_rate` | 确定性执行器通过率 | 由检查器判定 |
| `quality_score` | judge 质量分 0-100 | ~95 |

## Roadmap（二期）

- [ ] 接入 `tcms-can-test`：解析其 DBC/场景库为生成输入，生成用例跑真实 pytest
- [ ] 真实 LLM 对比实验：DeepSeek 等模型 × 多组需求，输出对比表
- [ ] 真 LLM-as-judge：把 rubric 注入 prompt 替代规则评分
- [ ] Agent 模式：多轮 self-critique 迭代修正生成用例

## License

MIT
