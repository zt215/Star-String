from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_ACCOUNT_FILE = Path.home() / ".star_string" / "accounts.json"


@dataclass
class Account:
    username: str
    password: str = ""
    remember_password: bool = False
    auto_login: bool = False


class AccountStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_ACCOUNT_FILE

    def load(self) -> list[Account]:
        if not self.path.exists():
            return []

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        accounts = data if isinstance(data, list) else data.get("accounts", [])
        result: list[Account] = []
        for item in accounts:
            if isinstance(item, dict) and item.get("username"):
                result.append(
                    Account(
                        username=str(item["username"]),
                        password=str(item.get("password", "")),
                        remember_password=bool(item.get("remember_password", False)),
                        auto_login=bool(item.get("auto_login", False)),
                    )
                )
        return result

    def load_last_username(self) -> str:
        if not self.path.exists():
            return ""

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""

        if isinstance(data, dict):
            return str(data.get("last_username", ""))
        return ""

    def save(self, accounts: list[Account], last_username: str = "") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_username": last_username,
            "accounts": [asdict(account) for account in accounts],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
