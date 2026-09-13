from __future__ import annotations

import json
from pathlib import Path

from app.services.model_store import (
    ACCOUNTS_DATA_DIR,
    LOCAL_PROFILE,
    LOCAL_PROFILE_DIR,
    _safe_account_name,
)


DEFAULT_MOTION_SETTINGS = {
    "camera_index": 0,
    "mirror": True,
    "sensitivity": 1.0,
    "drive_enabled": True,
    "engine": "hybrid",
    "params": {
        "angle_x": {"mult": 1.6, "invert": True},
        "angle_y": {"mult": 1.6, "invert": False},
        "angle_z": {"mult": 1.6, "invert": False},
        "body_angle_x": {"mult": 1.6, "invert": False},
        "body_angle_y": {"mult": 1.6, "invert": False},
        "arm_l": {"mult": 1.2, "invert": False},
        "arm_r": {"mult": 1.2, "invert": False},
        "eye": {"mult": 1.0},
        "mouth": {"mult": 1.0},
        "eye_x": {"mult": 1.0, "invert": False},
        "eye_y": {"mult": 1.0, "invert": False},
    },
}

DEFAULT_RVC_SETTINGS = {
    "pitch_shift": 0,
    "f0_method": "rmvpe",
    "index_rate": 75,
    "filter_radius": 3,
    "rms_mix_rate": 25,
    "resample_sr": "0",
    "protect_voiceless": True,
    "is_half": True,
    "gate_threshold": 0,
    "denoise": False,
    "input_device_name": "",
    "output_device_name": "",
}

DEFAULT_SYSTEM_SETTINGS = {
    "scheme_name": "日常直播",
    "video_resolution": "1080P",
    "video_fps": 60,
    "audio_sample_rate": "48000 Hz",
    "audio_engine": "RVC",
}


class SettingsStore:
    """Per-account application settings persisted under accounts_data/<account>/.

    If ``account`` is :data:`LOCAL_PROFILE`, the store is the separate offline/local
    profile and never touches any account data.
    """

    def __init__(self, account: str | None = None) -> None:
        if account == LOCAL_PROFILE:
            self.path = LOCAL_PROFILE_DIR / "settings.json"
        else:
            base = ACCOUNTS_DATA_DIR / _safe_account_name(account or "default")
            self.path = base / "settings.json"

    def load_motion(self) -> dict:
        settings = self._load_all()
        return dict(DEFAULT_MOTION_SETTINGS, **settings.get("motion", {}))

    def save_motion(self, motion: dict) -> None:
        settings = self._load_all()
        settings["motion"] = dict(DEFAULT_MOTION_SETTINGS, **motion)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_rvc(self) -> dict:
        settings = self._load_all()
        return dict(DEFAULT_RVC_SETTINGS, **settings.get("rvc", {}))

    def save_rvc(self, rvc: dict) -> None:
        settings = self._load_all()
        settings["rvc"] = dict(DEFAULT_RVC_SETTINGS, **rvc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_system(self) -> dict:
        settings = self._load_all()
        return dict(DEFAULT_SYSTEM_SETTINGS, **settings.get("system", {}))

    def save_system(self, system: dict) -> None:
        settings = self._load_all()
        settings["system"] = dict(DEFAULT_SYSTEM_SETTINGS, **system)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_all(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
