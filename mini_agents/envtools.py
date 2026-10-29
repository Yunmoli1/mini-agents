"""极简 .env 写回：控制台「模型设置」面板用。

为什么写回 .env 而不是只存 session：CLI demo、启动器、评测 runner 共用同一份
.env 配置，网页里改一次，到处生效。规则：
- 只替换给出的键，其余行（含注释、空行与顺序）原样保留
- 值为 None / 空串的键跳过——防止空输入把已有配置抹掉
- 文件不存在则创建
"""
from pathlib import Path


def update_env_file(path, updates: dict) -> list:
    """把 updates 合并进 .env 文件，返回实际写入的键名列表（按写入顺序）。"""
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    pending = {k: str(v) for k, v in updates.items() if v not in (None, "")}
    out = []
    written = []
    for line in lines:
        stripped = line.strip()
        key = (line.split("=", 1)[0].strip()
               if "=" in line and stripped and not stripped.startswith("#") else None)
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
            written.append(key)
        else:
            out.append(line)
    written += list(pending)
    out += [f"{k}={v}" for k, v in pending.items()]
    path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    return written
