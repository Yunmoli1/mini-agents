"""mini-agents 一键启动器（全中文引导）。

由 启动.bat 调起（bat 只负责 ASCII 引导壳），也可直接运行：
    .venv\\Scripts\\python scripts/launcher.py

职责：依赖自检 → .env 引导 → 菜单（控制台 / 离线测试）。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ["test_offline.py", "test_mcp.py", "test_checkpoint.py",
         "test_rag.py", "test_cost_routing.py"]

BANNER = "══════════════════════════════════════════\n   mini-agents 多 Agent 协作控制台\n══════════════════════════════════════════"


def sh(cmd):
    """运行命令并透传退出码；所有输出实时显示。"""
    return subprocess.run(cmd, cwd=ROOT).returncode


def ensure_dependencies():
    """缺依赖就自动安装（首次运行 / 新克隆时自动触发）。"""
    try:
        import streamlit  # noqa: F401
        import openai  # noqa: F401
        import rank_bm25  # noqa: F401
        return
    except ImportError:
        pass
    print("[初始化] 首次运行：安装依赖（约 2~5 分钟，请保持网络畅通）...")
    if sh([sys.executable, "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        pass  # pip 自升级失败不致命
    if sh([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]) != 0:
        print("[错误] 依赖安装失败。请检查网络后重新运行本程序。")
        sys.exit(1)
    print("[初始化] 完成。")


def ensure_env_file():
    """引导用户完成 .env 配置；未配好则退出等待用户填 Key。"""
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_path.exists():
        if example.exists():
            shutil.copy(example, env_path)
        print("[提示] 已生成 .env 配置文件。")
        print("       请用记事本打开 .env，把 LLM_API_KEY 换成你的真实 Key，")
        print("       然后重新运行本程序。")
        sys.exit(0)
    if "粘贴" in env_path.read_text(encoding="utf-8-sig", errors="replace"):
        print("[提示] .env 里还是示例占位符。请填入真实 API Key 后重新运行。")
        sys.exit(0)


def run_console():
    print("[启动] 控制台将在浏览器打开（停止：在页面/终端按 Ctrl+C）...")
    sh([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py")])


def run_tests():
    print("[测试] 运行全部离线测试（零 API 成本）...\n")
    failed = 0
    for test in TESTS:
        code = sh([sys.executable, test])
        if code != 0:
            failed += 1
        print()
    if failed:
        print(f"[结果] {failed} 个测试套件未通过，请查看上方输出。")
    else:
        print(f"[结果] 全部 {len(TESTS)} 套测试通过 ✔")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ensure_dependencies()
    ensure_env_file()

    print(BANNER)
    while True:
        print("\n  [1] 启动控制台（网页版：实时协作时间线 + 评测看板）")
        print("  [2] 运行全部离线测试（不花钱、不联网，约 40 秒）")
        print("  [3] 退出\n")
        try:
            choice = input("请输入序号后回车：").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if choice == "1":
            run_console()
        elif choice == "2":
            run_tests()
        elif choice == "3":
            return


if __name__ == "__main__":
    main()
