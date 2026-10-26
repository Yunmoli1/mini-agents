# 学习手册：按顺序读懂 mini-agents

> 本手册面向"想理解每一行"的读者。产品功能见根目录 README，设计取舍见 DECISIONS.md。

## 学习路径：建议按这个顺序读代码

1. **`mini_agents/llm.py`（40 行）** —— 最底层。所谓"调模型"就是把对话历史发给
   `chat.completions`，拿回一条消息：要么是文字（任务完成），要么是工具调用请求。
2. **`mini_agents/tools.py`** —— 两个关键点：`schema()` 生成发给模型的"能力说明书"
   （JSON Schema）；`call()` 里模型**永远只是点名**，真正执行代码的是我们。
   这就是 agent 的安全边界。`calculator` 特意用 ast 白名单求值而不用 `eval()`——
   工具参数来自模型输出，eval 等于把代码注入漏洞开在工具层。
3. **`mini_agents/agent.py`** —— 大心脏，逐行读懂 `run()` 里的循环。
   注意 `asyncio.gather` 那一行：**多 Agent 的"并行"不是什么神秘机制，
   就是并发执行一条消息里的多个工具调用**（`parallel_tool_calls=False` 时退化为
   串行——这是评测对照实验的开关）。每个工具调用里现场 new 一个子 Agent，
   子 Agent 的对话历史从零开始——这就是"上下文隔离"。
4. **`mini_agents/blackboard.py`（30 行）** —— 为什么不让 agents 自由聊天？
   因为消息会越滚越长（token 爆炸）、数据流向说不清。黑板模式让每份产出
   有名字、可持久化、可回放。
5. **`mini_agents/mcp_client.py`** —— 手写的 MCP 客户端（纯标准库）。重点看：
   initialize 握手与版本协商、`_read_loop` 如何把响应按请求 id 分发给等待中的
   Future、`_send` 如何保证一行一消息的帧完整（这是并发调用安全的前提）。
   配套的 `examples/mcp_fileserver.py` 是最小参考 server——读客户端前先读它，
   协议两端一起看才完整。
6. **`mini_agents/delegation.py`** —— "派活"只是一个工具：每次调用现场创建
   全新子 Agent。模型在同一条消息里发多个 delegate 调用 = 并行多 Agent 编排。
7. **`demo_research_team.py`** —— 完整编排。三个阶段怎么串起来，以及
   `build_research_tool` 里"工具调用 = 派子 Agent"的写法。注意
   `research_pipeline()` 是命令行与 Streamlit 网页版共用的单一事实源。
8. **`evals/`** —— 学习"怎么科学地证明自己的优化有效"：任务集怎么保证判分
   确定性、对照实验怎么控制变量、报告怎么做到一条命令复现。
   先跑 `python -m evals --offline` 看管线全貌（免费）。
9. **`test_offline.py` / `test_mcp.py`** —— 学习"怎么不花钱测 agent"：
   Agent 只依赖 `llm.chat()` 这一个接口，换成按脚本出牌的 FakeLLM 就能离线验证；
   MCP 协议层则用一个真实子进程 server 做端到端测试。

## 关键设计决策（也是常见踩坑点）

- **上下文隔离 vs 上下文污染**：子 Agent 只拿到任务文本和返回值，看不到主 Agent
  的历史。若把所有对话共享给所有人，token 成本平方级增长，且互相干扰。
- **工具结果截断**（`agent.py` 的 `MAX_TOOL_RESULT_CHARS`）：一次搜索结果可能
  几万字符，不截断会瞬间撑爆上下文。
- **批评循环要有上限**（`MAX_REVISIONS = 2`）：Writer⇄Reviewer 若无上限，
  苛刻的审查员可能永远打回。
- **优雅降级**：搜索不可用时返回提示文字而不是抛异常，流程能跑完
  （agent 收到错误信息会自己调整策略）。
- **审查员被要求只输出 JSON**：机器可判定的结论（pass/revise）不要让人话表达，
  驱动方才能程序化地决定循环走向。
- **并行加速的前提**：模型要支持在一条消息里发多个工具调用。个别模型不支持时
  会退化成串行——功能仍正确，只是慢。这也是评测里加速比可能为 N/A 的原因。

## 进阶练习（按难度递增）

1. 给调研员加 `fetch_page(url)` 工具，让它能读搜索结果的原文
   （提示：httpx + 截断策略，注意反爬与编码）。
2. 实现 RAG 工具：先 BM25 本地检索（rank-bm25），再接 embedding 做混合检索，
   并在评测里对比两者的召回差异（对应 Roadmap 里的 M2）。
3. 给评测加 LLM-as-judge：开放性任务（如"写摘要"）用强模型打分，
   与程序化判分互补（注意评委偏差：多跑几次、报告里写清评委提示词）。
4. 给 MCP 客户端加 Streamable HTTP 传输（当前只有 stdio），支持远程 server 与鉴权。
5. 实现 Handoffs 流水线模式（控制权接力），与黑板模式做 token 成本对比。
6. 多模型混编：Planner 用强模型、Researcher 用便宜模型
   （提示：让 `LLM` 接受 per-agent 覆盖配置），再在评测里对比成本/质量曲线。

## 常见问题

- **报模型不存在**：改 `.env` 里的 `LLM_MODEL`，去模型列表页确认可用型号；
  模型需支持 function calling。
- **并行没生效（调研员一个接一个跑）**：部分模型不支持在一条消息里发多个工具
  调用，会一轮只发一个——功能仍正确，只是退化成串行。换新一些的模型即可。
- **搜索报错/无结果**：`web_search` 用的是免费的 DuckDuckGo（`ddgs`），
  网络受限时会自动降级提示模型凭已有知识作答。也可自行替换成任意搜索 API。
- **评测要花多少钱**：默认配置 4 组 × 18 任务，GLM 免费模型零成本；
  强模型跑全量前先 `--configs single` 试水估算单任务开销。

## 延伸阅读

- [Choosing the Right Multi-Agent Architecture — LangChain](https://www.langchain.com/blog/choosing-the-right-multi-agent-architecture)：subagents / skills / handoffs / routers 四模式
- [AI Agent Orchestration Patterns — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)：orchestrator-worker、blackboard 等编排模式
- [Model Context Protocol 规范](https://modelcontextprotocol.io)：MCP 官方文档
