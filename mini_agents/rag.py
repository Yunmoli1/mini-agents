"""轻量 RAG：BM25 本地知识库 + knowledge_search 工具（v1.2 / 原 M2 第一版）。

设计要点：
- 检索用 rank-bm25 + jieba 中文分词，**纯本地、零 API 成本**，可离线测试
- 知识库 = 目录下的 .md/.txt，按段落切块，每块带来源（文件名#段落号）
- 向量混合检索留了接入口（见 DECISIONS.md #19）：BM25 先行，embedding 混合
  等确定可用的 embedding 端点后再接（score = α·bm25 归一 + (1-α)·向量相似）
"""
import re
from pathlib import Path

from mini_agents.tools import tool

_TEXT_SUFFIXES = {".md", ".txt"}


def _split_chunks(text: str, size: int = 400):
    """按空行分段；超长段落硬切到 size，保证块不爆炸。"""
    chunks = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        if para:
            chunks.append(para)
    return chunks


class KnowledgeBase:
    """BM25 知识库：ingest 一个目录，search 返回带来源的相关片段。"""

    def __init__(self, chunk_size: int = 400):
        self.chunk_size = chunk_size
        self.chunks = []      # [{"source": "文件名#pN", "text": ...}]
        self._tokenized = []
        self._bm25 = None

    def ingest(self, folder):
        paths = sorted(Path(folder).rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for i, chunk in enumerate(_split_chunks(text, self.chunk_size)):
                self.chunks.append({"source": f"{path.name}#p{i + 1}", "text": chunk})
        self._reindex()
        return len(self.chunks)

    def _tokenize(self, text: str):
        try:
            import jieba
            return [t for t in jieba.lcut(text) if t.strip()]
        except ImportError:
            # 未装 jieba 的兜底：二字切片，中文检索依然可用（精度略降）
            return [text[i:i + 2] for i in range(0, len(text), 2)] or [""]

    def _reindex(self):
        from rank_bm25 import BM25Okapi
        self._tokenized = [self._tokenize(c["text"]) for c in self.chunks]
        # 过滤空分词块（纯符号段落会让 BM25 的 IDF 除零）
        pairs = [(c, t) for c, t in zip(self.chunks, self._tokenized) if t]
        self.chunks = [c for c, _ in pairs]
        self._tokenized = [t for _, t in pairs]
        self._bm25 = BM25Okapi(self._tokenized) if self.chunks else None

    def search(self, query: str, top_k: int = 3):
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(self._tokenize(query))
        ranked = sorted(zip(scores, self.chunks), key=lambda pair: -pair[0])
        return [{"source": c["source"], "score": round(float(s), 3), "text": c["text"]}
                for s, c in ranked[:top_k] if s > 0]


def make_knowledge_tool(kb: KnowledgeBase):
    """把知识库包装成 Agent 工具：返回带来源标记的相关片段。"""

    @tool(description="在本地知识库中检索与查询最相关的资料片段（带来源标记）。"
                     "回答知识库相关的问题前，先用本工具检索。")
    def knowledge_search(query: str, top_k: int = 3) -> str:
        hits = kb.search(query, top_k=top_k)
        if not hits:
            return "知识库中没有检索到相关内容。"
        return "\n\n".join(f"[来源 {h['source']} | 相关度 {h['score']}]\n{h['text']}"
                           for h in hits)

    return knowledge_search
