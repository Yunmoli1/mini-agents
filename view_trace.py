"""回放一次多 Agent 协作的全过程：不同 Agent 用不同颜色区分。

    python view_trace.py runs/<时间戳>/trace.jsonl
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from mini_agents.i18n import get_lang, init_from_env, t
from mini_agents.tracing import describe_event


def agent_display(name: str) -> str:
    """英文模式下展示翻译后的角色名（trace 里存储的是中文角色名）。"""
    if get_lang() == "en":
        return {"黑板": "Blackboard", "driver": "Driver"}.get(name, name)
    return name

_PALETTE = ["\033[36m", "\033[33m", "\033[35m", "\033[32m", "\033[34m", "\033[96m"]
_RESET = "\033[0m"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    init_from_env()

    if len(sys.argv) < 2 or not Path(sys.argv[1]).exists():
        sys.exit(t("vt.usage"))

    colors, latest = {}, None
    for path in sys.argv[1:]:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e["agent"] not in colors:
                colors[e["agent"]] = _PALETTE[len(colors) % len(_PALETTE)]
            clock = datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
            who = f"{agent_display(e['agent']):<13}"
            print(f"{colors[e['agent']]}[{clock}] {who}{_RESET} {describe_event(e['agent'], e['type'], e)}")
            latest = path
    print(t("vt.roles_tail", n=len(colors), path=latest))


if __name__ == "__main__":
    main()
