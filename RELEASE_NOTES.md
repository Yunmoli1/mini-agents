# Release Notes — v1.0.0

> 发布日期：2026-10-25（草稿；发布前把评测数字填进 README 后再打 tag）

## Highlights

- **多 Agent 协作框架**（从零手写，无 agent 框架依赖）：Agent 自主循环、
  并行工具调度、delegate 编排、共享黑板、批评循环
- **手写 MCP 客户端**：纯标准库实现 stdio + JSON-RPC 2.0（握手 / 版本协商 /
  工具发现与调用 / ping / 分页），附最小参考 server 与防目录穿越的文件沙箱
- **评测 harness**：18 个程序化判分任务 × 4 组编排策略对照实验，一条命令复现
- **可观测性**：全程 JSONL trace，命令行实时摘要、Streamlit 实时时间线、彩色回放器

## 组件

| 模块 | 说明 |
|---|---|
| `mini_agents/` | 框架核心（llm / tools / agent / delegation / mcp_client / blackboard / tracing） |
| `evals/` | 评测任务集与 runner（`python -m evals`） |
| `demo_research_team.py` | 深度调研小组 demo（CLI） |
| `app.py` | Streamlit 网页演示（实时协作时间线） |
| `examples/mcp_fileserver.py` | 最小 MCP 参考服务器 |
| `test_offline.py` / `test_mcp.py` | 离线测试（零 API 成本） |

## Known Limitations

- MCP 仅实现 stdio 传输与 tools 能力（resources / prompts / sampling、HTTP 传输未覆盖）
- 并行加速比依赖模型支持"一条消息多个工具调用"，不支持时评测如实报告 N/A
- 评测判分为程序化（确定性），开放性任务的 LLM-as-judge 在 Roadmap 中
