"""评测任务集：18 个可程序化判分的任务（数学 6 / 知识 4 / 文件操作 8）。

设计原则：
- 判分全部确定性（正则匹配 / 文件比对），不依赖 LLM 评委——可复现、零成本、无裁判偏差
- 文件类任务每次运行获得全新沙箱，互不污染
- 每个任务附带 solve()：离线自检模式下直接执行正确行为，免费验证评测管线本身
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class EvalContext:
    answer: str
    sandbox: Path


@dataclass
class Task:
    id: str
    category: str  # math | knowledge | file
    prompt: str
    note: str      # 期望结果说明（进报告）
    verify: Callable[[EvalContext], tuple[bool, str]]
    prepare: Optional[Callable[[Path], None]] = None   # 播种沙箱
    solve: Optional[Callable[[Path], str]] = None      # 离线自检：直接做对


# ── 判分原语 ────────────────────────────────────────────────────
def _norm(text):
    return " ".join(str(text).replace(",", "").replace("，", "").split())


def _num_pattern(num):
    return re.compile(rf"(?<![\d.]){re.escape(num)}(?!\d)")


def contains_number(num):
    pattern = _num_pattern(num)

    def verify(ctx):
        ok = bool(pattern.search(_norm(ctx.answer)))
        return ok, f"期望回答包含 {num}，实际：{ctx.answer[:80]}"
    return verify


def file_equals(rel, expected):
    def verify(ctx):
        f = ctx.sandbox / rel
        if not f.exists():
            return False, f"{rel} 不存在"
        actual = f.read_text(encoding="utf-8").strip()
        return actual == expected.strip(), f"{rel} 内容不符：{actual[:60]!r}"
    return verify


def file_contains_number(rel, num):
    pattern = _num_pattern(num)

    def verify(ctx):
        f = ctx.sandbox / rel
        if not f.exists():
            return False, f"{rel} 不存在"
        return bool(pattern.search(f.read_text(encoding="utf-8"))), f"{rel} 中期望出现 {num}"
    return verify


def file_contains_text(rel, text):
    def verify(ctx):
        f = ctx.sandbox / rel
        if not f.exists():
            return False, f"{rel} 不存在"
        return text in f.read_text(encoding="utf-8"), f"{rel} 中期望包含 {text!r}"
    return verify


def combine(*verifiers):
    def verify(ctx):
        for v in verifiers:
            ok, detail = v(ctx)
            if not ok:
                return False, detail
        return True, "全部通过"
    return verify


# ── 文件类任务的种子 ────────────────────────────────────────────
REPORT_12_LINES = "\n".join(f"line-{i:02d}" for i in range(1, 13))
WORDS_9_AGENT = "agent AGENT Agent agent AGENT agent Agent agent agent"
NOTES_TEXT = "todo: eval\nnote: mcp\n"
META_JSON = '{"name": "mini-agents", "version": 1, "tags": ["x", "y"]}'


def _put(sandbox: Path, rel: str, text: str):
    p = sandbox / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _get(sandbox: Path, rel: str) -> str:
    return (sandbox / rel).read_text(encoding="utf-8")


# ── 任务定义 ────────────────────────────────────────────────────
TASKS = [
    # 数学（考察 calculator 工具与精确性）
    Task("m1", "math", "用计算器工具计算 (37×89+124)÷3，最终只回答整数结果。",
         "1139", contains_number("1139"), solve=lambda s: "1139"),
    Task("m2", "math", "从 1 一直加到 100，和是多少？只回答数字。",
         "5050", contains_number("5050"), solve=lambda s: "5050"),
    Task("m3", "math", "用计算器计算组合数 C(20,3)（即 20×19×18÷6），只回答整数。",
         "1140", contains_number("1140"), solve=lambda s: "1140"),
    Task("m4", "math", "用计算器计算 2 的 20 次方，只回答数字。",
         "1048576", contains_number("1048576"), solve=lambda s: "1048576"),
    Task("m5", "math", "1234567 的各位数字之和是多少？只回答数字。",
         "28", contains_number("28"), solve=lambda s: "28"),
    Task("m6", "math", "17 支球队进行单循环赛（每两队恰好赛一场），总共多少场？只回答数字。",
         "136", contains_number("136"), solve=lambda s: "136"),

    # 知识（考察参数化知识，判关键词）
    Task("k1", "knowledge", "Python 语言的创始人是谁？只回答名字。",
         "Guido", lambda ctx: (("guido" in ctx.answer.lower()),
                               f"期望包含 Guido，实际：{ctx.answer[:60]}"),
         solve=lambda s: "Guido van Rossum"),
    Task("k2", "knowledge", "HTTP 状态码 404 的标准含义是什么？用不超过 10 个字回答。",
         "未找到 / Not Found",
         lambda ctx: (any(k in ctx.answer.lower() for k in
                          ["not found", "未找到", "找不到", "无法找到", "不存在"]),
                      f"期望含 Not Found/未找到，实际：{ctx.answer[:60]}"),
         solve=lambda s: "未找到（Not Found）"),
    Task("k3", "knowledge", "TCP 和 UDP 中，哪个协议保证可靠传输？只回答协议名。",
         "TCP", lambda ctx: ("tcp" in ctx.answer.lower(),
                             f"期望包含 TCP，实际：{ctx.answer[:60]}"),
         solve=lambda s: "TCP"),
    Task("k4", "knowledge", "JSON 这个缩写对应的英文完整全称是什么？",
         "JavaScript Object Notation",
         lambda ctx: ("javascript object notation" in " ".join(ctx.answer.lower().split()),
                      f"期望含 JavaScript Object Notation，实际：{ctx.answer[:80]}"),
         solve=lambda s: "JavaScript Object Notation"),

    # 文件操作（考察 MCP 文件工具，沙箱隔离）
    Task("f1", "file", "沙箱中 report.txt 一共有多少行？把行数（只写数字）写入 count.txt。",
         "count.txt == 12",
         file_contains_number("count.txt", "12"),
         prepare=lambda s: _put(s, "report.txt", REPORT_12_LINES),
         solve=lambda s: (_put(s, "count.txt", "12"), "report.txt 共 12 行")[1]),
    Task("f2", "file", "把沙箱中 a.txt 与 b.txt 的内容按 a 在前、b 在后的顺序合并，写入 ab.txt。",
         "ab.txt == a+b",
         file_equals("ab.txt", "alpha\nbeta\ngamma\ndelta"),
         prepare=lambda s: (_put(s, "a.txt", "alpha\nbeta\n"), _put(s, "b.txt", "gamma\ndelta\n")),
         solve=lambda s: (_put(s, "ab.txt", "alpha\nbeta\ngamma\ndelta\n"), "已合并")[1]),
    Task("f3", "file", "把沙箱中的 notes.txt 复制一份到 backup 目录下（backup/notes.txt），原文件保留。",
         "backup/notes.txt 与原文件一致",
         file_equals("backup/notes.txt", NOTES_TEXT),
         prepare=lambda s: _put(s, "notes.txt", NOTES_TEXT),
         solve=lambda s: (_put(s, "backup/notes.txt", NOTES_TEXT), "已备份")[1]),
    Task("f4", "file", "统计 words.txt 中 agent 一词出现的次数（不区分大小写），把数字写入 result.txt。",
         "result.txt == 9",
         file_contains_number("result.txt", "9"),
         prepare=lambda s: _put(s, "words.txt", WORDS_9_AGENT),
         solve=lambda s: (_put(s, "result.txt", "9"), "共 9 次")[1]),
    Task("f5", "file", "读取 secrets/flag.txt 中的数字，把它乘以 3，结果（只写数字）写入 answer.txt。",
         "answer.txt == 63",
         file_contains_number("answer.txt", "63"),
         prepare=lambda s: _put(s, "secrets/flag.txt", "access code: 21"),
         solve=lambda s: (_put(s, "answer.txt", "63"), "已写入 63")[1]),
    Task("f6", "file", "在沙箱中创建目录 dir1，并在其中创建 data.txt，内容恰好为 hello-eval。",
         "dir1/data.txt == hello-eval",
         file_equals("dir1/data.txt", "hello-eval"),
         solve=lambda s: (_put(s, "dir1/data.txt", "hello-eval"), "已创建")[1]),
    Task("f7", "file", "读取沙箱中的 meta.txt（JSON 格式），把其中 name 字段的值写入 name.txt。",
         "name.txt 含 mini-agents",
         file_contains_text("name.txt", "mini-agents"),
         prepare=lambda s: _put(s, "meta.txt", META_JSON),
         solve=lambda s: (_put(s, "name.txt", json.loads(META_JSON)["name"]), "已提取")[1]),
    Task("f8", "file", "数一数沙箱根目录下有多少个文件（不含子目录），把数量（只写数字）写入 files.txt。",
         "files.txt == 4",
         file_contains_number("files.txt", "4"),
         prepare=lambda s: [_put(s, name, "x") for name in ("x1.txt", "x2.txt", "x3.txt", "y.md")],
         solve=lambda s: (_put(s, "files.txt", "4"), "共 4 个文件")[1]),
]
