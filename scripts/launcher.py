"""mini-agents 一键启动器（全中文引导）。

由 启动.bat 调起（bat 只负责 ASCII 引导壳），也可直接运行：
    .venv\\Scripts\\python scripts/launcher.py

职责：依赖自检 → .env 引导 → 菜单（控制台 / 离线测试）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mini_agents.i18n import init_from_env, set_lang, t

ROOT = Path(__file__).resolve().parent.parent
TESTS = ["test_offline.py", "test_mcp.py", "test_checkpoint.py",
         "test_rag.py", "test_cost_routing.py"]

BANNER_LINE = "══════════════════════════════════════════"


def banner():
    return f"{BANNER_LINE}\n{t('l.banner')}\n{BANNER_LINE}"


def sh(cmd):
    """运行命令并透传退出码；所有输出实时显示。"""
    return subprocess.run(cmd, cwd=ROOT).returncode


def load_env_lang():
    """把 .env 里的 MINI_LANG 读进进程环境（显式设置的环境变量优先）。"""
    if "MINI_LANG" in os.environ:
        init_from_env()
        return
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.strip().startswith("MINI_LANG="):
            os.environ["MINI_LANG"] = line.split("=", 1)[1].strip()
            init_from_env()
            return


def persist_lang(lang):
    """把语言选择持久化到 .env（追加或替换 MINI_LANG 行）。"""
    env_file = ROOT / ".env"
    lines = (env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
             if env_file.exists() else [])
    lines = [l for l in lines if not l.strip().startswith("MINI_LANG=")]
    lines.append(f"MINI_LANG={lang}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def switch_language():
    lang = input(t("r.lang_switch_prompt")).strip()
    if lang not in ("zh", "en"):
        print("zh / en")
        return
    set_lang(lang)
    os.environ["MINI_LANG"] = lang
    persist_lang(lang)
    print(t("r.lang_set", lang=lang))


def ensure_dependencies():
    """缺依赖就自动安装（首次运行 / 新克隆时自动触发）。"""
    try:
        import streamlit  # noqa: F401
        import openai  # noqa: F401
        import rank_bm25  # noqa: F401
        return
    except ImportError:
        pass
    print(t("l.init"))
    if sh([sys.executable, "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        pass  # pip 自升级失败不致命
    if sh([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]) != 0:
        print(t("l.install_fail"))
        sys.exit(1)
    print(t("l.init_done"))


def ensure_env_file():
    """引导用户完成 .env 配置；未配好则退出等待用户填 Key。"""
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_path.exists():
        if (ROOT / ".env.example").exists():
            shutil.copy(ROOT / ".env.example", env_path)
        print(t("l.env_generated"))
        print(t("l.env_howto1"))
        print(t("l.env_howto2"))
        sys.exit(0)
    if "粘贴" in env_path.read_text(encoding="utf-8-sig", errors="replace"):
        print(t("l.env_placeholder"))
        sys.exit(0)


def run_console():
    print(t("l.starting_console"))
    sh([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py")])


def run_tests():
    print(t("l.running_tests"))
    failed = 0
    for test in TESTS:
        code = sh([sys.executable, test])
        if code != 0:
            failed += 1
        print()
    if failed:
        print(t("l.test_fail", n=failed))
    else:
        print(t("l.test_ok", n=len(TESTS)))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env_lang()
    init_from_env()

    ensure_dependencies()
    ensure_env_file()

    print(banner())
    while True:
        print("\n" + t("l.menu0"))
        print(t("l.menu1"))
        print(t("l.menu2"))
        print(t("l.menu3") + "\n")
        try:
            choice = input(t("l.prompt")).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if choice == "0":
            switch_language()
        elif choice == "1":
            run_console()
        elif choice == "2":
            run_tests()
        elif choice == "3":
            return


if __name__ == "__main__":
    main()
