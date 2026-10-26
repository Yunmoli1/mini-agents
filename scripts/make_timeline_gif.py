"""把 trace.jsonl 重放渲染成 GIF —— 多 Agent 协作过程的可视化导出器。

    python scripts/make_timeline_gif.py runs/<目录>/trace.jsonl -o docs/demo.gif

- 每条事件渲染一帧：时间线窗口显示最近 N 行（深色终端风格，按角色着色），
  stage 事件作为标题行；复用 mini_agents.tracing.describe_event 的"事件→人话"转换
- 连续相同的画面自动合并（静止段压缩为更长帧时长）；帧数超限时均匀抽样
- 依赖：Pillow（评测/演示环境已带）。字体用微软雅黑（Windows 自带），
  缺失时退回 PIL 默认字体
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont

from mini_agents.tracing import describe_event

DARK, FG, STAGE = "#0d1117", "#c9d1d9", "#79c0ff"
AGENT_COLORS = [("Planner", "#58a6ff"), ("Researcher", "#7ee787"),
                ("Writer", "#f2cc60"), ("Reviewer", "#d2a8ff"),
                ("黑板", "#8b949e"), ("driver", "#ff7b72"), ("MCP", "#79c0ff")]
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
KEPT_TYPES = {"stage", "llm_response", "tool_call", "tool_result", "blackboard_write"}


def agent_color(agent):
    for prefix, color in AGENT_COLORS:
        if agent.startswith(prefix):
            return color
    return FG


def load_events(path):
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") in KEPT_TYPES:
            events.append(e)
    return events


def pick_font(size):
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_frames(events, window, width, height, font, stage_font):
    """逐事件累积时间线，产出 [(frames 画面行, stage 标题, 事件数)] 的去重序列。"""
    frames, lines, stage = [], [], ""
    for e in events:
        agent, type = e["agent"], e["type"]
        if type == "stage":
            stage = e.get("title", "")
        lines.append((agent, ANSI_RE.sub("", describe_event(agent, type, e))))
        lines = lines[-window:]
        view = (list(lines), stage)
        if frames and frames[-1][0] == view[0] and frames[-1][1] == view[1]:
            frames[-1][2] += 1          # 画面相同：合并为更长帧
        else:
            frames.append([view[0], stage, 1])
    return frames


def rasterize(view_lines, stage, width, height, font, stage_font):
    img = Image.new("RGB", (width, height), DARK)
    draw = ImageDraw.Draw(img)
    draw.text((16, 10), stage or "mini-agents", font=stage_font, fill=STAGE)
    draw.line([(12, 34), (width - 12, 34)], fill="#30363d", width=1)
    y = 44
    for agent, text in view_lines:
        draw.text((16, y), agent, font=font, fill=agent_color(agent))
        draw.text((130, y), text, font=font, fill=FG)
        y += int(font.size * 1.5)
    return img


def main():
    parser = argparse.ArgumentParser(description="trace.jsonl → 协作过程 GIF")
    parser.add_argument("trace", help="trace.jsonl 路径")
    parser.add_argument("-o", "--output", default="docs/demo.gif", help="输出 GIF 路径")
    parser.add_argument("--window", type=int, default=15, help="每帧显示最近 N 行")
    parser.add_argument("--width", type=int, default=960, help="画布宽度")
    parser.add_argument("--frame-ms", type=int, default=420, help="每帧时长（毫秒）")
    parser.add_argument("--max-frames", type=int, default=110, help="最大帧数（超限均匀抽样）")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    events = load_events(args.trace)
    if not events:
        sys.exit(f"trace 里没有可渲染的事件：{args.trace}")

    font = pick_font(15)
    stage_font = pick_font(19)
    height = 46 + int(15 * 1.5) * (args.window + 1) + 10

    frames = build_frames(events, args.window, args.width, height, font, stage_font)
    if len(frames) > args.max_frames:
        step = len(frames) / args.max_frames
        frames = [frames[int(i * step)] for i in range(args.max_frames)]

    total_ms = sum(f[2] for f in frames) * args.frame_ms
    images = [rasterize(view, stage, args.width, height, font, stage_font)
              for view, stage, _ in frames]
    durations = [f[2] * args.frame_ms for f in frames]

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, save_all=True, append_images=images[1:],
                   duration=durations, loop=0, optimize=True)

    size_kb = out.stat().st_size / 1024
    print(f"✔ {out} ｜ {len(images)} 帧 ｜ 播放约 {total_ms / 1000:.0f}s ｜ {size_kb:.0f} KB")
    print(f"  源 trace：{args.trace}（{len(events)} 条事件）")


if __name__ == "__main__":
    main()
