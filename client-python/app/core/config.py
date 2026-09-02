from __future__ import annotations

from pathlib import Path


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_SERVER_BASE_URL = "http://127.0.0.1:8080"


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_server_base_url() -> str:
    return _load_dotenv(ENV_FILE).get("SERVER_BASE_URL", DEFAULT_SERVER_BASE_URL).rstrip("/")
