# 决策记录（DECISIONS）

> 记录关键方向决策与子 agent 对抗审查结论，遇阻塞/改范围先记这里再行动。

## D1（2026-09-05）execution DSL 主线 — 采纳对抗审查

**子 agent 审查结论**（A-F 全节）核心：
- A 支持：瓶颈是自然语言↔可执行语义信道；DSL = 最小闭合语义接口。
  产品定位 =「LLM 从资产选场景 + 组合原语，断言由上游编解码语义作 oracle；
  创作归系统，LLM 负责广度选择」。
- B 修正：execution 是**唯一语义源**（purpose/steps 派生，防双轨漂移）；
  枚举双向表示须类型区分（encode 输入 raw 2 / decode 断言 VAL_ 文本 'Fault'）。
- C v1 最小原语：set_speed/set_handle/set_door_state/stop_message/send_alarm +
  expect_encode_error/expect_encode_ok/expect_signal/expect_signal_lost。
- E 两风险：范围失控；「模板填空」质疑 → 用变异杀毒实验应答。
- F 实验范式：**变异杀毒**（翻转 2-3 个 simulator 行为看生成用例能否抓到），
  固定任务=场景子集×金标；指标 parse/compile/pass + 变异杀毒率。

**采纳**：
1. execution 为唯一语义源：mock 的 purpose/steps 由模板 execution 派生（已如此）；
   GeneratedCase 校验要求带 execution 且 is_executable。
2. 枚举类型区分：DSL args 文档化——expect_signal 的 equals 若是字符串=VAL_ 文本，
   数字=raw（由编译层照原样生成，运行期 oracle 判等）。
3. P3 实验采用「场景金标 + 变异杀毒」设计，不只报通过率。
4. 范围控制：单族（车门/车速/心跳）端到端先通，不铺多族。

**驳回**：B 的 stages 线性时序段（setup+wait+assert 已够 v1，虚拟时钟是上游
ScenarioRunner 的事，我们的注入-采集窗口用 wait_ms 已覆盖心跳跨周期）；
full 自由代码生成（P2 实证 + 安全）。

## D2（2026-09-05）P3 无真 LLM 的实验立场

环境无 API key/本地模型（实测）→ P3 用「生成源对照」：规则基线 vs MockLLM vs
手工（上游 777 例抽样金标）。**不声称任何 LLM 质量数字**，结论限定为
「该 DSL+管线能区分生成源、能通过变异杀毒检出 sim 行为翻转」，真 LLM 通道
（OpenAICompatClient）接 key 即用，文档诚实标注。
