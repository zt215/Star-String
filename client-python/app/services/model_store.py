from __future__ import annotations

import json
import hashlib
import re
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


STAR_STRING_DIR = Path.home() / ".star_string"
ACCOUNTS_DATA_DIR = STAR_STRING_DIR / "accounts_data"

# Legacy global model storage (used before per-account isolation).
LEGACY_MODELS_DIR = STAR_STRING_DIR / "models"
LEGACY_REGISTRY_FILE = STAR_STRING_DIR / "models.json"

_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _safe_account_name(account: str) -> str:
    """Turn a username into a filesystem-safe directory name."""
    original = account or "default"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original)
    safe = re.sub(r"\s+", "_", safe).strip().rstrip(".")
    if not safe:
        safe = "user"
    if safe.lower() in _WINDOWS_RESERVED:
        safe = f"user_{safe}"
    if safe != original:
        safe = f"{safe}_{hashlib.sha1(original.encode('utf-8')).hexdigest()[:8]}"
    return safe


@dataclass
class ModelEntry:
    kind: str
    name: str
    path: str
    extra_path: str = ""
    active: bool = False
    created_at: str = ""


class ModelStore:
    """Per-account model store; each account owns its own models.json and models/ dir."""

    def __init__(self, account: str | None = None, registry_file: Path | None = None) -> None:
        self.account = account or "default"
        if registry_file is not None:
            self.registry_file = Path(registry_file)
            self.models_dir = self.registry_file.parent / "models"
        else:
            base = ACCOUNTS_DATA_DIR / _safe_account_name(self.account)
            self.registry_file = base / "models.json"
            self.models_dir = base / "models"
            if not self.registry_file.exists():
                self._migrate_legacy()

    # ---- persistence ----

    def load(self) -> list[ModelEntry]:
        if not self.registry_file.exists():
            return []

        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        entries: list[ModelEntry] = []
        for item in data if isinstance(data, list) else data.get("models", []):
            if isinstance(item, dict) and item.get("kind"):
                entries.append(ModelEntry(**item))
        return entries

    def save(self, entries: list[ModelEntry]) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            json.dumps(
                {"models": [asdict(entry) for entry in entries]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ---- import ----

    def import_live2d(self, source: Path) -> ModelEntry:
        source = source.resolve()
        target_dir = self.models_dir / "live2d" / uuid.uuid4().hex[:8]
        target_dir.mkdir(parents=True, exist_ok=True)

        if source.is_dir():
            self._copy_dir(source, target_dir)
        elif source.suffix.lower() == ".zip":
            self._extract_zip(source, target_dir)
        elif source.suffix.lower() == ".json":
            self._copy_dir(source.parent, target_dir)
        else:
            shutil.copy2(source, target_dir / source.name)

        json_files = list(target_dir.rglob("*.model3.json"))
        primary = str(json_files[0]) if json_files else str(target_dir / source.name)
        name = self._normalize_name(source.stem)

        entry = ModelEntry(
            kind="live2d",
            name=name,
            path=primary,
            active=False,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        entries = self.load()
        entries.append(entry)
        self.save(entries)
        return entry

    def import_rvc(self, sources: list[Path]) -> ModelEntry:
        target_dir = self.models_dir / "rvc" / uuid.uuid4().hex[:8]
        target_dir.mkdir(parents=True, exist_ok=True)

        for source in sources:
            source = source.resolve()
            if source.is_dir():
                self._copy_dir(source, target_dir)
            else:
                shutil.copy2(source, target_dir / source.name)

        pth_file = next(target_dir.glob("*.pth"), None)
        index_file = next(target_dir.glob("*.index"), None)
        config_file = next(target_dir.glob("*.json"), None)

        name = self._normalize_name(pth_file.stem if pth_file else sources[0].stem)
        entry = ModelEntry(
            kind="rvc",
            name=name,
            path=str(pth_file) if pth_file else str(target_dir),
            extra_path=str(index_file) if index_file else (str(config_file) if config_file else ""),
            active=False,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        entries = self.load()
        entries.append(entry)
        self.save(entries)
        return entry

    # ---- selection / removal ----

    def set_active(self, kind: str, name: str) -> list[ModelEntry]:
        entries = self.load()
        for entry in entries:
            if entry.kind == kind:
                entry.active = entry.name == name
        self.save(entries)
        return entries

    def remove(self, name: str) -> list[ModelEntry]:
        entries = [entry for entry in self.load() if entry.name != name]
        self.save(entries)
        return entries

    # ---- helpers ----

    def _migrate_legacy(self) -> None:
        """One-time move of the old global model storage into this account."""
        if LEGACY_MODELS_DIR.exists() and not self.models_dir.exists():
            try:
                self.models_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(LEGACY_MODELS_DIR), str(self.models_dir))
            except OSError:
                pass
        if not LEGACY_REGISTRY_FILE.exists():
            return
        try:
            data = json.loads(LEGACY_REGISTRY_FILE.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("models", [])
            old_prefix = str(LEGACY_MODELS_DIR)
            new_prefix = str(self.models_dir)
            for item in items:
                if isinstance(item, dict):
                    for key in ("path", "extra_path"):
                        value = item.get(key)
                        if isinstance(value, str) and value:
                            item[key] = value.replace(old_prefix, new_prefix)
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            self.registry_file.write_text(
                json.dumps({"models": items}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                LEGACY_REGISTRY_FILE.rename(LEGACY_REGISTRY_FILE.with_suffix(".json.migrated"))
            except OSError:
                pass
        except (OSError, json.JSONDecodeError):
            pass

    @staticmethod
    def _normalize_name(value: str) -> str:
        return value.strip() or "未命名模型"

    @staticmethod
    def _copy_dir(source: Path, target: Path) -> None:
        for item in source.iterdir():
            target_item = target / item.name
            if item.is_dir():
                shutil.copytree(item, target_item, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target_item)

    @staticmethod
    def _extract_zip(source: Path, target: Path) -> None:
        with zipfile.ZipFile(source) as archive:
            archive.extractall(target)
