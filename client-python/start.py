"""星弦客户端启动入口。

用法：
  - IDE：打开本文件，按 F5 或点击运行
  - 命令行：python start.py
  - 脚本：start.bat
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_VENV_PYTHON = _ROOT / ".venv" / "Scripts" / "python.exe"


def _ensure_venv_python() -> None:
    """优先使用项目虚拟环境 .venv，确保原生依赖（如 live2d）可用。"""
    if not _VENV_PYTHON.is_file():
        return
    if Path(sys.executable).resolve() == _VENV_PYTHON.resolve():
        return
    print(f"使用项目虚拟环境启动：{_VENV_PYTHON}")
    raise SystemExit(
        subprocess.call([str(_VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    )


if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ensure_venv_python()

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
