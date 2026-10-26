"""工具系统：把普通 Python 函数变成 Agent 可调用的工具。

核心只有两件事：
1. schema()   —— 生成函数的 JSON Schema，作为“能力说明书”发给模型
2. call(args) —— 模型点名调用时，真正执行函数并返回结果

模型本身不会执行任何代码：它只能“说出想调用的工具名和参数”，
执行永远发生在我们这边（这正是安全边界所在）。
"""
import ast
import asyncio
import inspect
import json
import operator

_TYPE_MAP = {str: "string", int: "integer", float: "number",
             bool: "boolean", list: "array", dict: "object"}


class Tool:
    def __init__(self, fn=None, name="", description="", parameters=None):
        self.fn = fn
        self.name = name
        self.description = description
        if parameters is not None:  # 外部提供的 schema（如 MCP 远程工具）直接采用
            self.parameters = parameters
        elif fn is not None:
            self.parameters = self._schema_from_signature(fn)
        else:
            self.parameters = {"type": "object", "properties": {}}

    @staticmethod
    def _schema_from_signature(fn):
        """从类型注解自动生成 JSON Schema（够用的简化版）。"""
        properties, required = {}, []
        for pname, p in inspect.signature(fn).parameters.items():
            properties[pname] = {"type": _TYPE_MAP.get(p.annotation, "string")}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        return {"type": "object", "properties": properties, "required": required}

    def schema(self):
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}

    async def call(self, args: dict):
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(**args)
        # 同步工具丢进线程池执行，避免阻塞同一回合里其他并行工具
        return await asyncio.to_thread(self.fn, **args)


def tool(name=None, description=None):
    """装饰器：@tool(description="...") 把一个函数注册为工具。"""
    def deco(fn):
        return Tool(fn, name or fn.__name__, description or (fn.__doc__ or "").strip())
    return deco


@tool(description="联网搜索，返回标题、链接和摘要组成的列表。")
def web_search(query: str, max_results: int = 5):
    try:
        from ddgs import DDGS
    except ImportError:
        return [{"error": "未安装 ddgs（pip install ddgs），无法联网搜索"}]
    try:
        hits = DDGS().text(query, max_results=max_results)
        return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                for r in hits]
    except Exception as exc:
        # 网络受限时优雅降级：不抛异常中断流程，但用 "error" 键标记失败——
        # Agent 层的 fail_fast 早停靠它识别"连续搜索失败"，否则调研员会烧满轮数上限
        return [{"error": f"搜索不可用（{exc}）",
                 "note": "可换关键词重试；若始终不可用，请基于已有知识回答并注明“未经联网核实”。"}]


# calculator 用 ast 白名单求值而不是 eval()：工具参数来自模型输出，
# eval() 等于把代码注入漏洞开在工具层。代价是只支持四则/幂/取模/正负号。
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("只支持数字与 + - * / // % ** 运算")


@tool(description="精确计算算术表达式，输入必须是合法数学表达式，如 (37*89+124)/3 或 2**20。")
def calculator(expression: str) -> str:
    try:
        return str(_safe_eval(ast.parse(expression.strip(), mode="eval")))
    except Exception as exc:
        return f"计算失败：{exc}"
