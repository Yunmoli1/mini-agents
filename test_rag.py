"""RAG 离线测试：不花一分钱验证 BM25 知识库的检索正确性。

    python test_rag.py
"""
import sys
import tempfile
from pathlib import Path

from mini_agents.rag import KnowledgeBase, make_knowledge_tool

_DOCS = {
    "protocol.md": "# 通信协议\n\nmini-agents 的 MCP 客户端支持三种消息：请求、响应、通知。"
                   "传输层目前只有 stdio。\n\nJSON-RPC 的请求必须带 id。\n",
    "evals.md": "# 评测体系\n\n评测 harness 包含 18 个任务，判分全部程序化，"
                "覆盖数学、知识与文件操作三类。\n\n并行加速比的分母是串行耗时。\n",
    "license.txt": "本项目采用 MIT 许可证发布，允许商用与修改。\n",
}

_QUESTIONS = [
    ("MCP 客户端支持哪三种消息？", "protocol.md"),
    ("评测任务一共多少个？", "evals.md"),
    ("项目用的什么许可证？", "license.txt"),
]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(tempfile.mkdtemp(prefix="mini_rag_"))
    for name, text in _DOCS.items():
        (root / name).write_text(text, encoding="utf-8")

    kb = KnowledgeBase()
    n = kb.ingest(root)
    assert n >= 3, f"切块数量异常：{n}"

    # 1. 检索命中正确来源
    for query, expected_file in _QUESTIONS:
        hits = kb.search(query, top_k=1)
        assert hits, f"查询无结果：{query}"
        assert expected_file in hits[0]["source"], (
            f"「{query}」期望命中 {expected_file}，实际 {hits[0]['source']}")

    # 2. 无关查询不硬凑结果
    assert kb.search("量子纠缠薛定谔方程", top_k=1) == [] or \
        kb.search("量子纠缠薛定谔方程", top_k=1)[0]["score"] < 1.0, "无关查询不应高分命中"

    # 3. 工具包装：返回带来源标记的字符串
    knowledge_search = make_knowledge_tool(kb)
    import asyncio
    out = asyncio.run(knowledge_search.call({"query": "评测任务一共多少个？"}))
    assert "来源" in out and "evals.md" in out, out

    print(f"✓ 知识库切块正常（{n} 块，来源带文件名#段落号）")
    print("✓ 检索命中正确：3/3 查询命中预期来源文件")
    print("✓ 无关查询不硬凑：低分/无结果")
    print("✓ 工具包装正常：输出带来源标记")
    print("\nRAG 离线测试全部通过 ✔")


if __name__ == "__main__":
    main()
