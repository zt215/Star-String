"""自定义姿势手势：录下当前动捕姿势 -> 起名保存 -> 再做同样的姿势自动触发。

这是「手势」之外的第二条识别链路，和 ``gesture.py`` 分工明确：

* ``gesture.py`` 认的是**手指形状**（握拳 / 比耶 / 点赞……），判据是手部 21 个
  关键点的几何关系，和手臂在哪无关；
* 本模块认的是**整条手臂的姿势**（上臂摆角、肘弯、前倾、手在画面里的位置、
  手腕朝向、手指弯曲度）。「双手举过头」「单手叉腰」「手放胸前」这类姿势，
  手指多半就是普通张开手掌，光看手型区分不出来，只有手臂角度能区分。

判据是**特征向量 + 归一化加权 RMS 距离**，不是机器学习，论文里好解释：

1. 特征向量 = 录制那一帧动捕解出的手臂 / 手部驱动值，见 :data:`POSE_KEYS`。
   每个键自带量程 ``(下界, 上界)`` 与权重——量程不同（角度是 0~180，弯曲度是
   0~1），必须先按量程归一化，否则量纲大的键（角度）会独占距离；
2. 两个姿势的距离 = ``sqrt(Σ w·d² / Σ w)``，``d`` 是归一化后的逐键差。因为
   两个姿势都先被夹进量程，每个 ``d`` 都落在 ``[-1, 1]``，所以距离天然是
   **0~1 的相似度刻度**（0 = 完全一样，1 = 每个键都顶到量程两端）；
3. 但**加权 RMS 会把手型摊薄**：手型是稀疏特征，「伸出一根食指」和「握拳」
   只差一根手指，24 个维度平均下来只剩 0.153（实测），落在默认容差 0.16 以内，
   于是两个动作互相触发。所以距离取「加权 RMS」与「单根手指最大差异 ×
   :data:`_PEAK_FINGER_WEIGHT`」的**较大值**——详见 :func:`distance`；
4. 距离小于该条手势自己的 ``tolerance`` 就算同一个姿势；多条同时命中取最近的。

权重是按「这个量有多能代表姿势」定的：上臂摆角、肘弯最能说明手臂摆成什么样，
给 2.0；前倾是深度补偿，1.5；手在画面里的位置和手腕朝向 1.0；逐根手指的
弯曲度只作辅助（同一姿势下手指难免有差异），压到 0.5，免得「手指差一点点」
把整个姿势判成不一样。

⚠️ 但「手指只作辅助」这条**不能走到另一个极端**：手指是**稀疏**特征，伸出
一根食指和握拳只差一根手指，权重 0.5 摊到二十多个维度里就只剩 0.153（实测），
比默认容差还小 —— 于是「录了单指，做单指和握拳都会触发」。所以距离里另加一项
「单根手指最大差异」，见 :func:`distance` 与 :data:`_PEAK_FINGER_WEIGHT`。

纯函数模块 + 一个纯状态机 :class:`PoseTracker`，都不碰 Qt / OpenGL / 摄像头，
所以可以在没有 GPU、没有摄像头的环境里直接单元测试。
"""

from __future__ import annotations

import math
from typing import Iterable

from app.services.gesture import GESTURE_NAMES

#: 姿势特征键表：``(键名, 量程下界, 量程上界, 权重)``。
#:
#: 键名全部来自 ``MotionCapture._extract_drive`` 的输出。这里**按记录时的原始
#: 量取值**（还没乘用户调的灵敏度倍率），所以录制和匹配永远在同一把尺子上，
#: 用户改「驱动数值」里的倍率不会让已录的姿势失效。
POSE_KEYS: tuple[tuple[str, float, float, float], ...] = (
    # 手臂物理角（度）——最能说明「手臂摆成什么形状」
    ("arm_swing_l", 0.0, 180.0, 2.0),
    ("arm_swing_r", 0.0, 180.0, 2.0),
    ("elbow_l", 0.0, 140.0, 2.0),
    ("elbow_r", 0.0, 140.0, 2.0),
    ("arm_fwd_l", 0.0, 60.0, 1.5),
    ("arm_fwd_r", 0.0, 60.0, 1.5),
    # 手在画面里的位置（归一化 -1~1，+y 向上、+x 向右）
    ("arm_l", -1.0, 1.0, 1.0),
    ("arm_r", -1.0, 1.0, 1.0),
    ("arm_l_x", -1.0, 1.0, 1.0),
    ("arm_r_x", -1.0, 1.0, 1.0),
    # 手腕朝向与四指聚合弯曲度
    ("wrist_l", -1.0, 1.0, 1.0),
    ("wrist_r", -1.0, 1.0, 1.0),
    ("hand_l", 0.0, 1.0, 1.0),
    ("hand_r", 0.0, 1.0, 1.0),
    # 逐指弯曲度（只作辅助）
    ("finger_l_0", 0.0, 1.0, 0.5),
    ("finger_l_1", 0.0, 1.0, 0.5),
    ("finger_l_2", 0.0, 1.0, 0.5),
    ("finger_l_3", 0.0, 1.0, 0.5),
    ("finger_l_4", 0.0, 1.0, 0.5),
    ("finger_r_0", 0.0, 1.0, 0.5),
    ("finger_r_1", 0.0, 1.0, 0.5),
    ("finger_r_2", 0.0, 1.0, 0.5),
    ("finger_r_3", 0.0, 1.0, 0.5),
    ("finger_r_4", 0.0, 1.0, 0.5),
)

#: 键名 -> (量程下界, 量程上界, 权重)
_KEY_TABLE: dict[str, tuple[float, float, float]] = {
    key: (lo, hi, weight) for key, lo, hi, weight in POSE_KEYS
}

#: 所有特征键的名字（按 :data:`POSE_KEYS` 的顺序）
POSE_KEY_NAMES: tuple[str, ...] = tuple(key for key, _lo, _hi, _w in POSE_KEYS)

#: 自定义姿势的默认容差。0.16 的直观含义：特征向量各维平均偏离约 16% 量程
#: 以内算同一个姿势（上臂摆角 ±29°、肘弯 ±22°、手指 ±0.16）。
DEFAULT_TOLERANCE = 0.16

#: 容差的允许区间。太小（0.04 以下）会灵敏到「同一姿势摆两次都判不出来」；
#: 上限 0.35 是按**误触发余量**定的：「举右手」和「举左手」这种完全反过来的
#: 姿势，归一化距离是 0.42（24 维里 12 维全反），所以上限压在 0.35 以下，
#: 左右手就永远不会互相误触发。再往上放，用户把容差拉满就会变成
#: 「做什么动作都算这个手势」。
TOLERANCE_MIN = 0.04
TOLERANCE_MAX = 0.35

#: 单根手指差异在距离里的「下限作用力」系数，见 :func:`distance`。
#:
#: 手型是**稀疏**特征：伸出一根食指和握拳只差一根手指，加权 RMS 摊到二十多个
#: 维度里只剩 0.153（实测），比默认容差 0.16 还小 —— 用户录了「单指」，之后做
#: 单指和握拳都会触发它。所以距离里补一项「单根手指最大差异 × 0.6」并与 RMS
#: 取较大值，两个数字都是量出来的：
#:
#: * 单根手指完全反过来 -> ``0.6 × 1.0 = 0.60``，高于容差上限 0.35，
#:   **任何档位都拦得住**（用户把容差拉到最大也不会把单指和握拳混起来）；
#: * 同一个姿势重摆两次时手指的正常误差（±0.25）-> ``0.6 × 0.25 = 0.15``，
#:   仍落在标准容差 0.16 之内，不会灵敏到「录完就再也触发不了」。
_PEAK_FINGER_WEIGHT = 0.6

#: 自定义手势 id 的前缀
CUSTOM_PREFIX = "custom_"

#: 没有可归属的模型时用的公共配置键。
#:
#: 用户可能在一个模型都没启用（甚至一个模型都没导入）的时候就在动捕页录手势。
#: 这时如果把配置丢掉，录完一看列表里没有，就成了「功能坏了」。所以统一落到
#: 公共档：任何模型自己还没存过配置时，都先拿公共档当初始值。
FALLBACK_PROFILE_KEY = "__default__"

#: 手势名字的长度上限（界面上是一行小字，太长会挤爆布局）
NAME_MAX_LEN = 12

#: 默认手势（``gesture.py`` 的固定手势）在界面上的显示顺序
BUILTIN_GESTURE_ORDER: tuple[str, ...] = (
    "open_palm", "peace", "thumb_up", "ok", "fist", "point", "rock",
)

#: 姿势匹配的去抖参数：连续多少帧命中才上报、连续多少帧落空才解除
POSE_STABLE_FRAMES = 3
POSE_RELEASE_FRAMES = 6


def _clamp(value: float, lower: float, upper: float) -> float:
    return lower if value < lower else (upper if value > upper else value)


def _as_float(value, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(number) or math.isinf(number):
        return fallback
    return number


# ----------------------------------------------------------------------
# 抓取 / 比较
# ----------------------------------------------------------------------


def capture(drive: dict | None) -> dict:
    """从一帧驱动值里抓出姿势特征向量。

    只取 :data:`POSE_KEYS` 里的键，缺的按 0 补（``_extract_drive`` 的初值就是
    全 0），并把每个值夹进自己的量程——这样存下来的模板永远是一把固定的尺子，
    匹配时逐键差一定落在 ``[-1, 1]``。
    """
    source = drive if isinstance(drive, dict) else {}
    pose: dict[str, float] = {}
    for key, lo, hi, _weight in POSE_KEYS:
        pose[key] = _clamp(_as_float(source.get(key, 0.0)), lo, hi)
    return pose


def is_blank(pose: dict | None) -> bool:
    """判断姿势是不是「什么都没动」（没检测到手时会是这样）。

    只有所有手臂角都近乎为 0 才算空白。用来自查：没手的时候录下来的模板会把
    「手不在画面」当成一个手势，之后模型静止不动就会一直触发它。
    """
    if not isinstance(pose, dict):
        return True
    for key in ("arm_swing_l", "arm_swing_r", "elbow_l", "elbow_r",
                "hand_l", "hand_r"):
        if abs(_as_float(pose.get(key, 0.0))) > 1e-6:
            return False
    # 手在画面里但手臂角度全 0（退化路径）时，位置量还有值
    for key in ("arm_l", "arm_r", "arm_l_x", "arm_r_x"):
        if abs(_as_float(pose.get(key, 0.0))) > 1e-6:
            return False
    return True


def _peak_finger_delta(a: dict, b: dict) -> float:
    """逐指弯曲度里差得**最厉害**的那一根（按各自量程归一化后，0~1）。

    只覆盖 ``finger_*``。其余特征天然被多个维度一起约束（上臂摆角一动，
    肘弯、手的位置往往跟着动），不需要峰值项；而手型是「一根手指定形状」的
    稀疏特征，平均值恰恰分不出来。
    """
    peak = 0.0
    for key, lo, hi, _weight in POSE_KEYS:
        if not key.startswith("finger_"):
            continue
        if key not in a or key not in b:
            continue
        span = max(hi - lo, 1e-6)
        diff = abs(_as_float(a[key]) - _as_float(b[key])) / span
        if diff > peak:
            peak = diff
    return peak


def distance(a: dict | None, b: dict | None) -> float:
    """两个姿势的距离，0（完全一样）~ 1（每一维都顶到两端）。

    取两个量的**较大值**：

    * **加权 RMS** ``sqrt(Σ w·d² / Σ w)`` —— 整体像不像，主判据；
    * **单根手指最大差异 × :data:`_PEAK_FINGER_WEIGHT`** —— 手型的兜底判据。

    为什么要有第二项：手型是稀疏特征，且逐指权重只有 0.5（24 维里 10 维、
    权重和 5），单根手指全反过来也只把 RMS 抬到 0.153 —— 比默认容差 0.16 还
    小，于是「录了单指，做单指和握拳都会触发同一个自定义手势」（用户实测）。
    峰值项让「差一根手指」这件事不再被其它维度摊薄，理由见
    :data:`_PEAK_FINGER_WEIGHT`。

    只比较两边都有的键——某一维在记录时不存在（换个版本的配置、换了模型）
    就跳过它，而不是拿 0 去和真值比。
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 1.0
    total = 0.0
    weight_sum = 0.0
    for key, lo, hi, weight in POSE_KEYS:
        if key not in a or key not in b:
            continue
        span = max(hi - lo, 1e-6)
        diff = (_as_float(a[key]) - _as_float(b[key])) / span
        total += weight * diff * diff
        weight_sum += weight
    if weight_sum <= 0.0:
        return 1.0
    rms = math.sqrt(total / weight_sum)
    peak = _peak_finger_delta(a, b) * _PEAK_FINGER_WEIGHT
    return rms if rms > peak else peak


def match(
    pose: dict | None,
    templates: Iterable[dict],
    tolerance: float | None = None,
) -> tuple[str | None, float]:
    """在模板里找最像 ``pose`` 的那一条。

    ``templates`` 里每一项要有 ``id`` / ``pose``，可选 ``tolerance``
    （没有就用 ``tolerance`` 参数，再没有就用 :data:`DEFAULT_TOLERANCE`）。
    返回 ``(命中的 id 或 None, 最近的距离)``——**距离无论命中与否都返回**，
    界面上可以直接显示「现在离最近的手势差多少」，用户调容差时有依据。
    """
    best_id: str | None = None
    best_distance = 1.0
    nearest = 1.0
    fallback = DEFAULT_TOLERANCE if tolerance is None else float(tolerance)
    for entry in templates or ():
        if not isinstance(entry, dict):
            continue
        template = entry.get("pose")
        if not isinstance(template, dict) or not template:
            continue
        limit = _clamp(
            _as_float(entry.get("tolerance", fallback), fallback),
            TOLERANCE_MIN,
            TOLERANCE_MAX,
        )
        current = distance(pose, template)
        nearest = min(nearest, current)
        if current <= limit and current < best_distance:
            best_distance = current
            best_id = str(entry.get("id") or "") or None
    return best_id, (best_distance if best_id else nearest)


def summarize(pose: dict | None) -> str:
    """一句话概括姿势，给界面做副标题用（如「左臂 162° / 右臂 12°」）。"""
    if not isinstance(pose, dict) or is_blank(pose):
        return "空姿势"
    left = _as_float(pose.get("arm_swing_l", 0.0))
    right = _as_float(pose.get("arm_swing_r", 0.0))
    return f"左臂 {left:.0f}° / 右臂 {right:.0f}°"


# ----------------------------------------------------------------------
# 自定义手势条目
# ----------------------------------------------------------------------


def clean_name(name) -> str:
    """收拾用户输入的名字：去空白、限长、空名给个默认。"""
    text = " ".join(str(name or "").split())
    if not text:
        return "未命名手势"
    return text[:NAME_MAX_LEN]


def new_gesture_id(existing: Iterable[str] = ()) -> str:
    """生成一个不与现有 id 冲突的自定义手势 id（``custom_1`` / ``custom_2``…）。

    不用 uuid：id 会写进配置文件给人看，``custom_3`` 比 ``custom_9f2a1c`` 好读，
    排查「哪个手势触发了」的时候省事。
    """
    used = {str(item) for item in existing or ()}
    index = 1
    while f"{CUSTOM_PREFIX}{index}" in used:
        index += 1
    return f"{CUSTOM_PREFIX}{index}"


def make_custom_gesture(
    name,
    pose: dict,
    action: str = "none",
    existing_ids: Iterable[str] = (),
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict:
    """造一条自定义手势条目。

    姿势为空（没检测到手）时抛 :class:`ValueError`——这种模板存下去会变成
    「模型不动就触发」的鬼手势，必须在入口拦住。
    """
    snapshot = capture(pose)
    if is_blank(snapshot):
        raise ValueError("当前没有检测到手部，无法录制姿势")
    return {
        "id": new_gesture_id(existing_ids),
        "name": clean_name(name),
        "kind": "custom",
        "pose": snapshot,
        "tolerance": _clamp(_as_float(tolerance, DEFAULT_TOLERANCE),
                            TOLERANCE_MIN, TOLERANCE_MAX),
        "action": str(action or "none"),
    }


def builtin_rows(actions: dict | None = None) -> list[dict]:
    """默认的七条手势行。

    ``actions`` 是旧配置里的 ``gesture_actions``（``{手势: 动作 id}``），
    拿来做**迁移来源**：老版本只存了「手势 -> 动作」这一张表，没有「有哪些
    手势行」的概念，第一次按模型取配置时用它把动作填进去，用户原来配好的
    映射不会丢。
    """
    source = actions if isinstance(actions, dict) else {}
    rows: list[dict] = []
    for key in BUILTIN_GESTURE_ORDER:
        rows.append({
            "id": key,
            "name": GESTURE_NAMES.get(key, key),
            "kind": "builtin",
            "pose": None,
            "tolerance": DEFAULT_TOLERANCE,
            "action": str(source.get(key, "none") or "none"),
        })
    return rows


def default_rows(actions: dict | None = None) -> list[dict]:
    """没有为当前模型存过配置时用的初始行（= 七条默认手势）。"""
    return builtin_rows(actions)


# ----------------------------------------------------------------------
# 配置清洗 / 读写
# ----------------------------------------------------------------------


def sanitize_row(raw) -> dict | None:
    """把一条存下来的手势行收拾干净；实在不成样子就丢掉（返回 ``None``）。"""
    if not isinstance(raw, dict):
        return None
    gesture_id = str(raw.get("id") or "").strip()
    if not gesture_id:
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind not in ("builtin", "custom"):
        kind = "custom" if gesture_id.startswith(CUSTOM_PREFIX) else "builtin"

    row = {
        "id": gesture_id,
        "name": clean_name(raw.get("name") or GESTURE_NAMES.get(gesture_id)
                           or gesture_id),
        "kind": kind,
        "tolerance": _clamp(
            _as_float(raw.get("tolerance", DEFAULT_TOLERANCE), DEFAULT_TOLERANCE),
            TOLERANCE_MIN,
            TOLERANCE_MAX,
        ),
        "action": str(raw.get("action") or "none"),
        "pose": None,
    }
    pose = raw.get("pose")
    if kind == "custom":
        if not isinstance(pose, dict):
            # 自定义手势没有姿势模板就永远不可能被触发，没有保留价值
            return None
        snapshot = capture(pose)
        if is_blank(snapshot):
            return None
        row["pose"] = snapshot
    elif isinstance(pose, dict) and not is_blank(capture(pose)):
        # 默认手势理论上不走姿势匹配，但万一存了就留着，不影响
        row["pose"] = capture(pose)
    return row


def sanitize_gestures(raw) -> list[dict]:
    """清洗「某个模型的手势行列表」，顺便去重（同 id 只留第一条）。"""
    if not isinstance(raw, list):
        return []
    rows: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        row = sanitize_row(item)
        if row is None or row["id"] in seen:
            continue
        seen.add(row["id"])
        rows.append(row)
    return rows


def sanitize_profiles(raw) -> dict:
    """清洗 ``gesture_profiles``：``{模型 key: {"gestures": [...]}}``。

    模型 key 由 :func:`model_key` 生成，逐模型各存一份，换模型不会互相顶掉。
    """
    if not isinstance(raw, dict):
        return {}
    profiles: dict[str, dict] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        if not isinstance(value, dict):
            continue
        rows = sanitize_gestures(value.get("gestures"))
        profiles[name] = {"gestures": rows}
    return profiles


def model_key(kind: str | None, name: str | None) -> str:
    """当前模型的配置键，如 ``live2d:hiyori_pro`` / ``vrm:AliciaSolid``。

    用「类型 + 名字」而不是模型文件路径：路径随导入位置变，用户重装一次模型
    配置就找不回来了；名字是用户自己起的、稳定的标识。
    """
    kind_text = str(kind or "").strip()
    name_text = str(name or "").strip()
    if not kind_text or not name_text:
        return ""
    return f"{kind_text}:{name_text}"


def rows_for(profiles: dict | None, key: str, actions: dict | None = None) -> list[dict]:
    """取某个模型的手势行；没存过就退回公共档，再没存过就用默认七条。

    「存过但是空列表」是**明确意图**（用户把默认手势全删了），要原样返回空，
    不能拿默认值把它填回去——这就是「删除默认手势」这个功能本身。
    """
    if isinstance(profiles, dict):
        for candidate in (key, FALLBACK_PROFILE_KEY):
            if not candidate:
                continue
            profile = profiles.get(candidate)
            if not isinstance(profile, dict):
                continue
            if isinstance(profile.get("gestures"), list):
                rows = sanitize_gestures(profile.get("gestures"))
                return rows
    return default_rows(actions)


def set_rows(profiles: dict | None, key: str, rows: list[dict]) -> dict:
    """不可变地写入某个模型的手势行，返回新的 ``gesture_profiles``。"""
    if not key:
        return sanitize_profiles(profiles)
    updated = sanitize_profiles(profiles)
    updated[key] = {"gestures": sanitize_gestures(rows)}
    return updated


def builtin_actions(rows: Iterable[dict]) -> dict:
    """从手势行里抽出「默认手势 -> 动作」，用于回写旧字段 ``gesture_actions``。

    老版本只认 ``gesture_actions``（没有按模型分表），把它保持最新，等于给
    「模型还没加载出来」的时刻留一份兜底映射。
    """
    actions: dict[str, str] = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if str(row.get("kind") or "builtin") == "builtin":
            actions[str(row.get("id"))] = str(row.get("action") or "none")
    return actions


# ----------------------------------------------------------------------
# 姿势匹配去抖（纯状态机，可单测）
# ----------------------------------------------------------------------


class PoseTracker:
    """把逐帧的「像不像某个自定义姿势」变成触发 / 解除事件。

    和 ``MotionCapture._update_gestures`` 的手势去抖同构：连续
    :data:`POSE_STABLE_FRAMES` 帧命中同一个才上报一次，连续
    :data:`POSE_RELEASE_FRAMES` 帧不命中才解除——只隔一帧的抖动不会让动作
    在「触发 / 解除」之间抽搐。

    :meth:`update` 返回本次要上报的事件：命中的 id、``""``（解除）或 ``None``
    （状态没变，不用发信号）。这样做的好处是整个去抖逻辑是纯函数式的，
    不依赖 Qt 信号，可以在没有摄像头、没有 QApplication 的环境里直接测。
    """

    def __init__(
        self,
        stable_frames: int = POSE_STABLE_FRAMES,
        release_frames: int = POSE_RELEASE_FRAMES,
        tolerance: float = DEFAULT_TOLERANCE,
    ) -> None:
        self.stable_frames = max(1, int(stable_frames))
        self.release_frames = max(1, int(release_frames))
        self.tolerance = _clamp(float(tolerance), TOLERANCE_MIN, TOLERANCE_MAX)
        self._templates: list[dict] = []
        self._pending_id = ""
        self._pending_count = 0
        self._release_count = 0
        self._active = ""

    # ---- 配置 ----

    def set_templates(self, entries: Iterable[dict] | None) -> None:
        """设置参与匹配的模板（只有带 ``pose`` 的条目会被用上）。"""
        templates: list[dict] = []
        for entry in entries or ():
            if not isinstance(entry, dict):
                continue
            pose = entry.get("pose")
            if not isinstance(pose, dict) or is_blank(capture(pose)):
                continue
            templates.append({
                "id": str(entry.get("id") or ""),
                "pose": capture(pose),
                "tolerance": _clamp(
                    _as_float(entry.get("tolerance", self.tolerance), self.tolerance),
                    TOLERANCE_MIN,
                    TOLERANCE_MAX,
                ),
            })
        self._templates = [item for item in templates if item["id"]]
        if self._active and self._active not in {t["id"] for t in self._templates}:
            self._active = ""
            self._pending_id = ""
            self._pending_count = 0
            self._release_count = 0

    @property
    def has_templates(self) -> bool:
        return bool(self._templates)

    @property
    def active(self) -> str:
        return self._active

    # ---- 逐帧 ----

    def update(self, pose: dict | None, available: bool = True) -> str | None:
        """喂一帧姿势，返回要上报的事件（``id`` / ``""`` / ``None``）。

        ``available`` 为假表示这帧压根没有可用的姿势（手不在画面里、模型还没
        起来）：直接按「落空」处理，别拿全 0 的姿势去和模板比。
        """
        found: str | None = None
        if available and self._templates:
            found, _distance = match(pose, self._templates, self.tolerance)

        if not found:
            self._pending_id = ""
            self._pending_count = 0
            if not self._active:
                self._release_count = 0
                return None
            self._release_count += 1
            if self._release_count >= self.release_frames:
                self._active = ""
                self._release_count = 0
                return ""
            return None

        self._release_count = 0
        if self._pending_id == found:
            self._pending_count += 1
        else:
            self._pending_id = found
            self._pending_count = 1
        if self._pending_count >= self.stable_frames and self._active != found:
            self._active = found
            return found
        return None

    def reset(self) -> None:
        """清空全部去抖状态（停止动捕 / 换模型时调用）。"""
        self._pending_id = ""
        self._pending_count = 0
        self._release_count = 0
        self._active = ""
