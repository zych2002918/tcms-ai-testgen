# 质量指标口径（Metrics Definition）

> 权威定义：一切实验报告的指标口径以此为准。**分母含残缺样本**，禁止挑
> 对自己有利的样本集凑指标——「质量可度量」的前提是口径诚实可复现。

## 1. parse_rate —— 结构化解析率

LLM 生成侧（GenReport）：
```
parse_rate = 成功结构化解析的用例数 / (解析成功 + 解析失败)
```
- 失败 = LLM 输出无法解析成 GeneratedCase（含缺 name/purpose/expected、
  非 dict、JSON 提取失败）。整批提取失败计 1 次失败。
- mock 客户端故意注入残缺样本，使该指标有区分度（实测 ~0.875，非 1.0）。

真实资产侧（AssetBundle.stats）：
```
parse_rate = (parsed_yaml + parsed_dbc) / (parsed + bad)
```
- bad = 文件不存在 / 空 / YAML 语法错 / 编码错 / 目录缺失（计 1）；
- **空目录 ≠ 坏文件**（合法空集），不参与分母；
- 行级坏行（DBC raw_line_errors / 场景 skipped_steps）不降文件解析状态，
  但必须在报告里显式可见（demo_assets 打印清单）。

## 2. exec_pass_rate —— 真实执行通过率

一期（mock）：确定性执行器口径（compile/pass 判定，见 executor.py）。
二期（P1 后）：真实 pytest —— 生成用例在 tcms-can-test 上真实执行：
```
exec_pass_rate = 真实执行的通过用例数 / 实际可执行用例总数
```
- 分母 = 生成用例中能映射到真实 pytest（可编译）的用例数；
- 无法编译/无法映射的用例记 fail，不剔除（口径一致：生成质量含"能不能跑"）；
- LLM 非确定性：CI 用 mock/录播，真实执行实验固定 seed/temperature。

## 3. quality_score —— judge 质量分（0-100）

规则 rubric 评分（judge.py）：结构完整度 + 需求可追溯 + 场景设计
（边界/异常/否定）。一期实测 ~94。二期 P4 与真 LLM-as-judge 交叉验证：
一致性 ≥0.7（或给出差异分析），届时口径在此追加。

## 4. 通用纪律

- 每个数字必须能复现：对应命令/文件写进 docs/experiments/ 或本节；
- 实验一律控制变量：一次只改一个变量，其余固定并记录；
- 覆盖率口径：pytest-cov `--cov-fail-under=90`（branch=true，source=tcms_ai_testgen）。

## 5. 一期实测基线（P0/P1 完成时点）

| 指标 | 值 | 复现命令 |
|---|---|---|
| parse_rate（mock 生成） | 0.875 | `python scripts/selfcheck.py` |
| quality_score（mock） | 94.3 | 同上 |
| exec_pass_rate（mock） | 1.0 | 同上 |
| parse_rate（真实资产） | 1.0（1 DBC + 13 场景） | `python examples/demo_assets.py` |
| 测试门禁 | 64 passed / 92.16% / ruff 过 | `pytest tests --cov=tcms_ai_testgen -q` |
