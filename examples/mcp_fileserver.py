"""一个最小的 MCP stdio server —— 教学参考实现（约百行，纯标准库）。

用法：python examples/mcp_fileserver.py <沙箱根目录>

它实现了一个客户端需要的全部协议面：
    initialize 握手 / notifications/initialized / ping / tools/list / tools/call
工具集是一个受限文件沙箱：list_dir / read_file / write_file（拒绝越出根目录）。

路径安全：resolve() 先解析符号链接再做包含性检查，因此沙箱内指向外部的
symlink 同样会被拒绝——防目录穿越与防 symlink 逃逸是同一段代码。

注意：stdout 只允许输出协议消息，任何日志都必须走 stderr。
"""
import json
import sys
from pathlib import Path

SUPPORTED_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18"]

TOOLS = [
    {"name": "list_dir",
     "description": "列出沙箱内某个目录的内容（默认根目录）。",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "相对沙箱根目录的路径，可省略"}},
         "required": []}},
    {"name": "read_file",
     "description": "读取沙箱内一个文本文件的完整内容。",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "相对沙箱根目录的文件路径"}},
         "required": ["path"]}},
    {"name": "write_file",
     "description": "把文本写入（或覆盖）沙箱内的一个文件，自动创建父目录。",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]}},
]


def resolve(root: Path, rel: str) -> Path:
    """把相对路径解析到沙箱内；越出根目录一律拒绝（防目录穿越）。"""
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes sandbox root: {rel}")
    return target


def handle_tool(name, args, root: Path):
    """返回 (is_error, text)。业务错误也走 isError 通道，让调用方（模型）自行处理。"""
    if name == "list_dir":
        d = resolve(root, args.get("path") or ".")
        if not d.is_dir():
            raise ValueError(f"not a directory: {args.get('path', '.')}")
        lines = sorted(("dir  " + e.name) if e.is_dir()
                       else (f"file {e.name} ({e.stat().st_size}B)")
                       for e in d.iterdir())
        return False, "\n".join(lines) or "(empty directory)"
    if name == "read_file":
        f = resolve(root, args["path"])
        if not f.is_file():
            raise ValueError(f"not a file: {args['path']}")
        return False, f.read_text(encoding="utf-8")
    if name == "write_file":
        f = resolve(root, args["path"])
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(args["content"], encoding="utf-8")
        return False, f"written {len(args['content'])} chars -> {args['path']}"
    raise ValueError(f"unknown tool: {name}")


def send(msg):
    sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    root.mkdir(parents=True, exist_ok=True)
    print(f"[mini-fs] 沙箱已就绪：{root}", file=sys.stderr, flush=True)

    for raw in sys.stdin.buffer:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        method, req_id = msg.get("method"), msg.get("id")

        if method == "initialize" and req_id is not None:
            wanted = (msg.get("params") or {}).get("protocolVersion")
            version = wanted if wanted in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[-1]
            if wanted != version:
                print(f"[mini-fs] 客户端请求 {wanted!r}，回应 {version!r}",
                      file=sys.stderr, flush=True)
            send({"jsonrpc": "2.0", "id": req_id,
                  "result": {"protocolVersion": version,
                             "capabilities": {"tools": {}},
                             "serverInfo": {"name": "mini-fs", "version": "0.1.0"}}})
        elif method == "ping" and req_id is not None:
            send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            try:
                is_err, text = handle_tool(params.get("name"),
                                           params.get("arguments") or {}, root)
            except Exception as exc:
                is_err, text = True, f"error: {exc}"
            send({"jsonrpc": "2.0", "id": req_id,
                  "result": {"content": [{"type": "text", "text": text}],
                             "isError": is_err}})
        elif req_id is not None:
            send({"jsonrpc": "2.0", "id": req_id,
                  "error": {"code": -32601, "message": f"method not found: {method}"}})
        # 其余均为无 id 的通知（initialized / cancelled…），忽略即可


if __name__ == "__main__":
    main()
