"""从明确列出的学习文件生成可复现的下载包；不打包缓存或凭据。"""

from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ".gitignore", "README.md", "LEARNING_METHODS.md", "AGENTS.md", "START_HERE.md",
    "topics/agent-systems/README.md", "topics/agent-systems/ROADMAP.md",
    "projects/ai-town/README.md", "projects/ai-town/world.json",
    "projects/ai-town/town.py", "projects/ai-town/main.py", "projects/ai-town/server.py",
    "projects/ai-town/model.py", "projects/ai-town/test_model.py",
    "projects/ai-town/start-deepseek-mac.command",
    "projects/ai-town/start-mac.command", "projects/ai-town/start-windows.bat",
    "projects/ai-town/test_town.py", "projects/ai-town/web/index.html",
    "projects/ai-town/web/styles.css", "projects/ai-town/web/app.js",
    "assets/ai-town-preview.png", "assets/ai-learning-methods.png",
    "scripts/build_learning_bundle.py",
]


def main():
    for name in FILES:
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"无法打包，文件缺失或为符号链接：{name}")
    destination = ROOT / "dist" / "ai-town-learning.zip"
    destination.parent.mkdir(exist_ok=True)
    temporary = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, f"my-codex-learning/{name}")
    with zipfile.ZipFile(temporary) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise SystemExit(f"压缩包校验失败：{bad_file}")
    temporary.replace(destination)
    print(f"已生成：{destination}")
    print(f"文件数：{len(FILES)}；大小：{destination.stat().st_size} 字节")


if __name__ == "__main__":
    main()
