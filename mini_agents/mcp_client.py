"""MCP（Model Context Protocol）客户端 —— 手写实现，零第三方依赖。

只实现学习框架需要的最小子集：stdio 传输 + JSON-RPC 2.0 +
initialize 握手 + tools/list（含分页）+ tools/call。协议文档：modelcontextprotocol.io

设计要点（完整决策记录见 DECISIONS.md）：
- 手写协议而非用官方 SDK：MCP 的消息只有三种（请求/响应/通知），手写一遍才真正理解
- 版本协商取"宽松"策略：发送支持的最高版本，接受服务器的任何回应并记日志
- 服务器发来的请求（如 ping）照常回应，通知一律忽略，保证与真实 server 兼容
"""
import asyncio
import itertools
import json
import re
from collections import deque

from .i18n import t
from .tools import Tool

SUPPORTED_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18"]


class MCPError(RuntimeError):
    """协议级错误：握手失败、请求超时、服务器返回 JSON-RPC error 或进程退出。"""


class McpTool(Tool):
    """把 MCP server 上的一个远程工具包装成本地 Tool：模型调用方式完全一致。"""

    def __init__(self, client, descriptor, name):
        super().__init__(name=name,
                         description=descriptor.get("description", ""),
                         parameters=descriptor.get("inputSchema")
                         or {"type": "object", "properties": {}})
        self._client = client
        self._remote_name = descriptor["name"]

    async def call(self, args):
        return await self._client.call_tool(self._remote_name, args)


class McpStdioClient:
    """通过子进程的 stdin/stdout 与一个 MCP server 通信（每行一条 JSON 消息）。"""

    def __init__(self, command, trace=None, request_timeout=30.0, tool_timeout=120.0):
        self.command = list(command)
        self.trace = trace
        self.request_timeout = request_timeout
        self.tool_timeout = tool_timeout
        self.server_info = None
        self.negotiated_version = None
        self._proc = None
        self._pending = {}  # 请求 id -> Future
        self._ids = itertools.count(1)
        self._stderr_tail = deque(maxlen=5)  # server 崩溃时用于诊断

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ── 生命周期 ────────────────────────────────────────────────
    async def connect(self):
        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        reader = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._drain_stderr())

        # 握手：initialize 请求 → 服务器回能力与版本 → 发 initialized 通知
        result = await self._request("initialize", {
            "protocolVersion": SUPPORTED_VERSIONS[-1],
            "capabilities": {},
            "clientInfo": {"name": "mini-agents", "version": "0.1.0"},
        })
        self.negotiated_version = result.get("protocolVersion")
        self.server_info = result.get("serverInfo", {})
        await self._notify("notifications/initialized")
        self._log(t("m.handshake",
                    server=self.server_info.get("name"),
                    version=self.negotiated_version))
        return reader

    async def close(self):
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                self._proc.kill()
            self._proc = None

    # ── 对上层（Agent / Tool）的接口 ────────────────────────────
    async def list_tools(self):
        tools, cursor = [], None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = await self._request("tools/list", params)
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, name, arguments):
        result = await self._request("tools/call",
                                     {"name": name, "arguments": arguments},
                                     timeout=self.tool_timeout)
        texts = [c.get("text", "") for c in result.get("content", [])
                 if isinstance(c, dict) and c.get("type") == "text"]
        output = "\n".join(texts).strip()
        if not output:
            output = json.dumps(result.get("structuredContent") or result,
                                ensure_ascii=False)
        if result.get("isError"):
            # 工具级错误透传给模型（agent 需要看到错误才能自我纠错），
            # 只有协议级错误才抛 MCPError
            output = f"[MCP 工具报告出错] {output}"
        return output

    async def as_tools(self, prefix=None):
        """把 server 的全部工具包装成 Tool 列表。

        prefix 默认取 serverInfo.name（非法字符替换为 _），避免多个 server
        工具重名；模型看到的名字形如 <prefix>_<tool_name>。
        """
        if prefix is None:
            raw = (self.server_info or {}).get("name", "mcp")
            prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
        descriptors = await self.list_tools()
        self._log(t("m.found", n=len(descriptors),
                    names=", ".join(d["name"] for d in descriptors)))
        return [McpTool(self, d, f"{prefix}_{d['name']}") for d in descriptors]

    # ── 协议层 ─────────────────────────────────────────────────
    async def _request(self, method, params=None, timeout=None):
        if not self._proc:
            raise MCPError(t("m.not_connected"))
        req_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                          **({"params": params} if params is not None else {})})
        try:
            return await asyncio.wait_for(future, timeout or self.request_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise MCPError(t("m.timeout", method=method,
                             timeout=timeout or self.request_timeout)) from None

    async def _notify(self, method, params=None):
        await self._send({"jsonrpc": "2.0", "method": method,
                          **({"params": params} if params is not None else {})})

    async def _send(self, message):
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _read_loop(self):
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:  # EOF：server 退出
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(MCPError(
                                t("m.dead", tail=" | ".join(self._stderr_tail))))
                    self._pending.clear()
                    return
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(msg.get("id"), None)
                    if fut and not fut.done():
                        if "error" in msg:
                            err = msg["error"]
                            fut.set_exception(MCPError(
                                t("m.server_error", code=err.get("code"),
                                  message=err.get("message"))))
                        else:
                            fut.set_result(msg["result"])
                elif msg.get("method") == "ping" and "id" in msg:
                    # 服务器的心跳请求必须回应，否则部分 server 会断开连接
                    await self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                else:
                    self._log(t("m.ignore", method=msg.get("method")))
        except asyncio.CancelledError:
            pass

    async def _drain_stderr(self):
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    return
                self._stderr_tail.append(line.decode("utf-8", "replace").strip())
        except (asyncio.CancelledError, AttributeError):
            pass

    def _log(self, detail):
        if self.trace:
            self.trace.log("MCP", "mcp_event", detail=detail)
