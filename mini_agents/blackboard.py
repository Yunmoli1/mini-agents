"""共享黑板（Blackboard 模式）：Agent 之间不闲聊，只通过这块结构化“黑板”交换产出。

- 某位 Agent 完成一段工作 → write(key, value) 写上来
- 下一位 Agent 开始工作   → read() / as_markdown() 把需要的内容读进自己的上下文

好处：数据流向一目了然、可持久化（blackboard.json）、可回放，
也避免了把所有人的对话历史搅在一起（上下文污染 + token 浪费）。
"""
import json
from pathlib import Path


class Blackboard:
    def __init__(self, trace=None):
        self._data = {}
        self.trace = trace

    def write(self, key, value):
        self._data[key] = value
        if self.trace:
            self.trace.log("黑板", "blackboard_write", key=key, preview=str(value)[:100])

    def read(self, key, default=None):
        return self._data.get(key, default)

    def as_markdown(self, keys=None):
        """把黑板内容（或指定几块）拼成可注入 prompt 的文本。"""
        parts = []
        for k in (keys or list(self._data)):
            v = self._data.get(k)
            if v is None:
                continue
            body = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1)
            parts.append(f"### {k}\n{body}")
        return "\n\n".join(parts)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path, trace=None):
        """从 blackboard.json 恢复黑板——checkpoint/断点恢复的入口（v1.2）。"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        board = cls(trace)
        board._data = data
        return board
