from __future__ import annotations

import json
from pathlib import Path

from app.services.model_store import (
    ACCOUNTS_DATA_DIR,
    LOCAL_PROFILE,
    LOCAL_PROFILE_DIR,
    _safe_account_name,
)
from app.services.pose_gesture import sanitize_profiles


DEFAULT_MOTION_SETTINGS = {
    "camera_index": 0,
    "mirror": True,
    "sensitivity": 1.0,
    "drive_enabled": True,
    "engine": "hybrid",
    "hand_enabled": True,
    "gesture_enabled": True,
    # 手部检测抽帧间隔：1 = 每帧都跑（最跟手），2~4 更省 CPU
    "hand_every": 1,
    # 手势 -> 动作，取值见 app/services/gesture.py 的 ACTION_LABELS
    "gesture_actions": {
        "open_palm": "wave",
        "peace": "motion_tap",
        "thumb_up": "expression_smile",
        "ok": "expression_smile",
        "fist": "expression_angry",
        "point": "none",
        "rock": "none",
    },
    # 每个模型各存一套手势配置：{模型key: {"gestures": [手势行, ...]}}
    #
    # 模型 key 形如 ``live2d:hiyori_pro`` / ``vrm:AliciaSolid``。手势行既包含
    # 默认的七个手势（可以删掉），也包含用户录制的自定义姿势手势，所以这个
    # 字段是「有哪些手势、各自绑什么动作、自定义手势长什么样」的唯一来源；
    # 上面的 ``gesture_actions`` 退化成模型还没加载时的兜底映射与迁移来源。
    "gesture_profiles": {},
    "params": {
        "angle_x": {"mult": 1.6, "invert": True},
        "angle_y": {"mult": 1.6, "invert": False},
        "angle_z": {"mult": 1.6, "invert": False},
        "body_angle_x": {"mult": 1.6, "invert": False},
        "body_angle_y": {"mult": 1.6, "invert": False},
        "arm_l": {"mult": 1.2, "invert": False},
        "arm_r": {"mult": 1.2, "invert": False},
        "arm_l_x": {"mult": 1.0, "invert": False},
        "arm_r_x": {"mult": 1.0, "invert": False},
        # 上臂摆动 / 肘部弯曲（度）——VRM 骨骼真正消费的两路手臂信号，
        # arm_l / arm_l_x 只是手在画面里的归一化位置，给不了关节角度。
        "arm_swing_l": {"mult": 1.0, "invert": False},
        "arm_swing_r": {"mult": 1.0, "invert": False},
        "elbow_l": {"mult": 1.0, "invert": False},
        "elbow_r": {"mult": 1.0, "invert": False},
        # 整臂前倾（肩前屈，度）：手伸到躯干轮廓里时补的深度，避免手臂插进肚子
        "arm_fwd_l": {"mult": 1.0, "invert": False},
        "arm_fwd_r": {"mult": 1.0, "invert": False},
        "hand_l": {"mult": 1.0, "invert": False},
        "hand_r": {"mult": 1.0, "invert": False},
        "wrist_l": {"mult": 0.8, "invert": False},
        "wrist_r": {"mult": 0.8, "invert": False},
        "mouth_form": {"mult": 1.0, "invert": False},
        "eye": {"mult": 1.0},
        "mouth": {"mult": 1.0},
        "eye_x": {"mult": 1.0, "invert": False},
        "eye_y": {"mult": 1.0, "invert": False},
    },
}

DEFAULT_LIPSYNC_SETTINGS = {
    # 语音驱动口型：让嘴型跟着声音走，而不是跟着摄像头
    "enabled": False,
    "gain": 1.4,
    "form_enabled": True,
}

DEFAULT_RVC_SETTINGS = {
    "pitch_shift": 0,
    "f0_method": "pm",
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

DEFAULT_MIXER_SETTINGS: dict = {
    # 调音台通道: [{"id":..., "kind":"input"|"loopback", "index":..., "name":...}, ...]
    "channels": [],
}


def _merge_motion(user: dict) -> dict:
    """把用户保存的 motion 配置合并到默认值上。

    必须**逐层**合并：``params`` / ``gesture_actions`` / ``gesture_profiles``
    是嵌套字典，老版本存下来的配置里没有后加的键（例如 hand_l / arm_l_x /
    wrist_l，或者 gesture_profiles 这个字段本身），整块覆盖会让这些新参数
    悄悄退回内置默认值，界面上也读不到对应的调节项——表现就是「手指灵敏度
    调不了、调了也没反应」，以及「自定义手势存了却读不出来」。

    ``gesture_profiles`` 还要按**模型 key 逐层**合并：用户在 live2d 模型上配的
    手势不能被 vrm 模型那份顶掉，反之亦然。这里不能写成 ``{**default,
    **user}``——那样只是把整个顶层字典换掉，但每个模型内部的 ``gestures``
    列表是「用户自己的完整意图」，必须以用户那份为准（包括空列表 = 全删光），
    所以只做清洗，不做与默认值的拼接。
    """
    merged = dict(DEFAULT_MOTION_SETTINGS)
    if not isinstance(user, dict):
        return merged
    merged.update(user)

    params = dict(DEFAULT_MOTION_SETTINGS["params"])
    user_params = user.get("params")
    if isinstance(user_params, dict):
        for key, value in user_params.items():
            base = params.get(key)
            if isinstance(base, dict) and isinstance(value, dict):
                params[key] = {**base, **value}
            else:
                params[key] = value
    merged["params"] = params

    actions = dict(DEFAULT_MOTION_SETTINGS["gesture_actions"])
    user_actions = user.get("gesture_actions")
    if isinstance(user_actions, dict):
        actions.update(user_actions)
    merged["gesture_actions"] = actions

    merged["gesture_profiles"] = sanitize_profiles(user.get("gesture_profiles"))
    return merged


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
        return _merge_motion(settings.get("motion", {}))

    def save_motion(self, motion: dict) -> None:
        settings = self._load_all()
        settings["motion"] = _merge_motion(motion)
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

    def load_lipsync(self) -> dict:
        settings = self._load_all()
        return dict(DEFAULT_LIPSYNC_SETTINGS, **settings.get("lipsync", {}))

    def save_lipsync(self, lipsync: dict) -> None:
        settings = self._load_all()
        settings["lipsync"] = dict(DEFAULT_LIPSYNC_SETTINGS, **lipsync)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_mixer(self, channels: list) -> None:
        settings = self._load_all()
        settings["mixer"] = {"channels": list(channels)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_mixer(self) -> list:
        settings = self._load_all()
        mixer = settings.get("mixer", {})
        channels = mixer.get("channels")
        return list(channels) if isinstance(channels, list) else []

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
