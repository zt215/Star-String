"""模型能力探测：当前模型到底支持哪些动作和表情。

手势菜单的可选项必须是**按模型探测出来的**，不能写死。写死的列表对不上模型——
Live2D 的表情叫「生气」「爱心」「F01」，VRM 的预设叫 happy/angry，动作组名每个
模型都不一样（hiyori 有 Tap/Flick，云吞kumo 只有 IDLE/红温）。用户在下拉框里
选了一个模型根本没有的东西，自然「选完没用」。

这里把两边的能力统一成三种动作 id，触发时直接用模型自己的名字：

    none                 不响应
    motion:<动作组名>     播放该动作组
    expression:<表情名>   设置该表情

Live2D 的能力有两个来源，缺一不可：

1. ``.model3.json`` 里登记的 ``FileReferences.Motions`` / ``Expressions``；
2. 同目录下散落的 ``*.motion3.json`` / ``*.exp3.json``——VTube Studio 导出的模型
   （云吞kumo、玳瑁猫、nekoN）**根本不往 model3.json 里登记**，文件单独摆着，
   运行时要用 ``LoadExtraMotion`` / ``LoadExtraExpression`` 补进去。

VRM 没有动作组，动作由程序生成（见 ``VRM_BUILTIN_MOTIONS``）；表情取
``model.expressions`` 里的情绪类，口型/眨眼/视线那几个 morph 由动捕和语音链路
驱动，放进手势菜单只会和它们打架。

本模块是纯函数式的：只读模型文件、不碰 OpenGL，因此可以在无 GPU 的环境里
直接单元测试。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: 动作 id
ACTION_NONE = "none"
PREFIX_MOTION = "motion:"
PREFIX_EXPRESSION = "expression:"

#: VRM 内置动作：(动作名, 菜单显示名)。VRM 没有动作组，这些由 vrm_view 用
#: 骨骼动画现场生成。
VRM_BUILTIN_MOTIONS: tuple[tuple[str, str], ...] = (
    ("wave", "挥手打招呼"),
    ("nod", "点头"),
    ("shake", "摇头"),
    ("bow", "鞠躬"),
    ("clap", "鼓掌"),
)

#: 功能性开关类表情的名字特征。手势触发它们没意义（藏起兽耳、切发卡、恢复默认），
#: 但仍然允许选，只是排在情绪表情后面、显示成「切换：」以示区别。
#:
#: 后半段是「身体部位 / 饰品」类词：Live2D 模型常把「露出肉球」「高光消失」
#: 「兽耳隐藏」这类显示开关做成独立表情，光靠「隐藏 / 开关」两个字认不全
#: （玳瑁猫的「发卡1..4」就一个提示词都不带）。
UTILITY_HINTS = (
    "隐藏", "开关", "切换", "水印", "一键取消", "关闭", "提示", "物理",
    "宽度", "透明", "阈值", "显示", "尺寸", "位置", "缩放", "角度", "大小",
    "抓手", "手柄", "禁用", "打开", "特效",
    "发卡", "手套", "肉球", "高光", "瞳孔", "兽耳", "尾巴", "脖子",
    "腿部", "袖子", "铃铛", "领子", "耳朵",
)

#: 情绪类表情的名字特征，用于自动选择默认动作时优先挑这些
EMOTION_HINTS = (
    "happy", "joy", "fun", "smile", "angry", "anger", "sad", "sorrow",
    "surprise", "relax", "shy", "blush", "wink", "cry", "love", "excited",
    "微笑", "笑", "开心", "高兴", "生气", "愤怒", "怒", "伤心", "悲伤",
    "哭", "泪", "惊讶", "吃惊", "爱心", "脸红", "害羞", "流汗", "无语",
    "问号", "脸黑", "呆呆", "晕", "无语", "挑眉", "得意",
)

#: VRM 里由口型/眨眼/视线链路驱动的 morph，不该出现在手势菜单里
_VRM_DRIVEN_MORPHS = {
    "aa", "ih", "ou", "ee", "oh",
    "a", "i", "u", "e", "o",
    "blink", "blink_l", "blink_r", "blinkleft", "blinkright",
    "lookup", "lookdown", "lookleft", "lookright",
    "neutral",
}

#: 旧版写死的动作 id -> (类型, 候选真实名)。候选名按优先级排列，
#: 在模型能力里逐个找第一个存在的。保留它是为了不丢用户已经存下来的映射。
LEGACY_ACTION_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "wave": ("motion", ("wave", "Flick", "Tap", "挥手", "打招呼", "Idle")),
    "motion_tap": ("motion", ("Tap", "Flick", "Tap@Body", "TapBody", "Idle")),
    "motion_idle": ("motion", ("Idle", "idle", "IDLE", "待机")),
    "expression_smile": ("expression", ("smile", "happy", "joy", "微笑", "笑", "开心")),
    "expression_surprised": ("expression", ("surprised", "surprise", "惊讶", "吃惊")),
    "expression_angry": ("expression", ("angry", "anger", "生气", "愤怒")),
}

#: 自动兜底时，每种手势优先用哪类动作
_GESTURE_KIND_PREFERENCE: dict[str, tuple[str, ...]] = {
    "open_palm": ("motion",),
    "peace": ("motion",),
    "rock": ("motion",),
    "point": ("expression", "motion"),
    "thumb_up": ("expression",),
    "ok": ("expression",),
    "fist": ("expression", "motion"),
}

#: 自动兜底时优先挑的动作组名。通用待机排最后——「Idle」本身看不太出来，
#: 但它是所有模型都有的安全选择，只有别的动作组都挑完了才用它。
_MOTION_PREFERENCE = (
    "wave", "Flick", "挥手", "打招呼", "Tap", "Tap@Body", "FlickUp",
    "nod", "点头", "摇头", "bow", "鞠躬", "Idle", "IDLE", "待机",
)

#: 自动兜底时优先挑的表情名，按手势分组（命中不了就用通用情绪表）。
#: 正向手势都带上 relaxed/smile 这类温和选项，否则 happy 被点赞占走后，
#: OK 就只能去捡 sad，看着莫名其妙。
_GESTURE_EMOTION_HINTS: dict[str, tuple[str, ...]] = {
    "point": ("surprised", "惊讶", "问号", "无语", "晕"),
    "thumb_up": ("happy", "joy", "smile", "微笑", "笑", "开心", "爱心", "脸红"),
    "ok": ("relaxed", "relax", "fun", "smile", "微笑", "笑", "开心", "爱心"),
    "fist": ("angry", "anger", "生气", "愤怒", "脸黑", "怒"),
}

#: 自动兜底时优先挑的动作组名，按手势分组。「挥手」最挑——用户举起手掌
#: 本来就是在打招呼，拿不到挥手类动作这个手势的默认值就是错的。
_GESTURE_MOTION_HINTS: dict[str, tuple[str, ...]] = {
    "open_palm": ("wave", "Flick", "挥手", "打招呼", "FlickUp", "Tap"),
    "peace": ("Tap", "Tap@Body", "Flick", "红温", "呆毛旋转", "害怕"),
    "rock": ("呆毛旋转", "害怕", "bow", "摇头", "shake", "clap"),
    "point": ("Tap", "Tap@Body", "nod", "点头"),
    "fist": ("bow", "鞠躬", "clap", "nod", "点头"),
}

#: 兜底分配顺序：语义最明确的先挑，泛指的（比耶/摇滚）捡剩下的
_GESTURE_DEFAULT_ORDER = (
    "open_palm", "thumb_up", "ok", "fist", "point", "peace", "rock",
)


@dataclass
class ModelCapabilities:
    """当前模型实际支持的动作组与表情名。"""

    kind: str = ""
    motions: list[str] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.motions and not self.expressions

    def has(self, kind: str, name: str) -> bool:
        pool = self.motions if kind == "motion" else self.expressions
        return any(str(item).lower() == str(name).lower() for item in pool)


def _append_unique(items: list[str], value: str) -> None:
    value = str(value).strip()
    if value and value not in items:
        items.append(value)


def _load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


#: 常见表情名的中文显示名。模型内部名（happy / Fcl_ALL_Joy / 生气）直接用
#: 也能跑，但菜单里全是英文对中文用户不友好。查不到就原样显示。
DISPLAY_NAMES: dict[str, str] = {
    "happy": "高兴", "joy": "开心", "fun": "有趣", "smile": "微笑",
    "angry": "生气", "anger": "愤怒", "sad": "难过", "sorrow": "悲伤",
    "surprised": "惊讶", "surprise": "惊讶", "relaxed": "放松",
    "relax": "放松", "shy": "害羞", "blush": "脸红", "wink": "眨眼",
    "cry": "哭泣", "love": "爱心", "excited": "兴奋", "bored": "无聊",
}


def is_utility_expression(name: str) -> bool:
    """判断表情是不是功能性开关（藏部件、切发卡之类），而不是情绪。"""
    return any(hint in str(name) for hint in UTILITY_HINTS)


def is_emotion_expression(name: str) -> bool:
    return not is_utility_expression(name) and any(
        hint in str(name).lower() for hint in EMOTION_HINTS
    )


def display_expression(name: str) -> str:
    """把 ``Fcl_ALL_Joy`` 这类内部命名收拾成人能读的样子。"""
    text = str(name)
    for prefix in ("Fcl_ALL_", "Fcl_", "Exp_", "exp_"):
        if text.startswith(prefix):
            text = text[len(prefix):] or text
            break
    return DISPLAY_NAMES.get(text.lower(), text)


def live2d_extra_assets(
    model_json_path: str | Path | None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """列出需要运行时补注册的资源：``(表情, 动作)``，每项是 ``(名字, 文件路径)``。

    VTube Studio 导出的模型（云吞kumo、玳瑁猫、nekoN）**不往 model3.json 里登记**
    表情和动作，文件就散在模型目录里，Cubism 加载完只有一副躯壳。要用手势触发
    它们，得先用 ``LoadExtraExpression`` / ``LoadExtraMotion`` 补进去。

    已经在 model3.json 里登记过的一律跳过——重复注册会把模型自带的动作组覆盖掉。
    """
    expressions: list[tuple[str, str]] = []
    motions: list[tuple[str, str]] = []
    if not model_json_path:
        return expressions, motions
    path = Path(model_json_path)
    if not path.exists():
        return expressions, motions
    base = path.parent

    registered_motions, registered_exprs = _registered_live2d(path)

    for file in sorted(base.glob("*.exp3.json")):
        name = file.name[: -len(".exp3.json")]
        if name and name not in registered_exprs:
            expressions.append((name, str(file)))

    if not registered_motions:
        seen: set[str] = set()
        for file in sorted(base.glob("**/*.motion3.json")):
            name = file.name[: -len(".motion3.json")]
            if name and name not in seen:
                seen.add(name)
                motions.append((name, str(file)))
    return expressions, motions


def _registered_live2d(path: Path) -> tuple[list[str], list[str]]:
    """读出 model3.json 里正式登记过的动作组名与表情名。"""
    refs = _load_json(path).get("FileReferences") or {}
    motions: list[str] = []
    raw_motions = refs.get("Motions") or {}
    if isinstance(raw_motions, dict):
        for group in raw_motions:
            _append_unique(motions, str(group))
    expressions: list[str] = []
    raw_exprs = refs.get("Expressions") or []
    if isinstance(raw_exprs, list):
        for entry in raw_exprs:
            if isinstance(entry, dict) and entry.get("Name"):
                _append_unique(expressions, str(entry["Name"]))
    return motions, expressions


def scan_live2d_capabilities(model_json_path: str | Path | None) -> ModelCapabilities:
    """从 ``.model3.json`` 及其所在目录探测 Live2D 能力。

    磁盘扫描只在 ``model3.json`` **没有登记**该类资源时才做：hiyori 这类正规
    模型把 10 个 motion 文件登记成 7 个动作组，再去按文件名扫一遍会凭空多出
    ``hiyori_m01`` 这种假动作组，反而把菜单搞乱。
    """
    caps = ModelCapabilities(kind="live2d")
    if not model_json_path:
        return caps
    path = Path(model_json_path)
    if not path.exists():
        return caps

    motions, expressions = _registered_live2d(path)
    caps.motions = motions
    caps.expressions = list(expressions)

    # VTS 系模型散落在目录里的表情 / 动作文件也要算进能力，否则菜单里
    # 一条都显示不出来，用户只会看到「不响应」。
    for name, _ in live2d_extra_assets(path)[0]:
        _append_unique(caps.expressions, name)
    if not caps.motions:
        for name, _ in live2d_extra_assets(path)[1]:
            _append_unique(caps.motions, name)
    return caps


def vrm_capabilities(expression_names: list[str] | None) -> ModelCapabilities:
    """VRM 能力：内置动作 + 模型里真正能当表情用的 morph。"""
    caps = ModelCapabilities(kind="vrm")
    caps.motions = [name for name, _ in VRM_BUILTIN_MOTIONS]
    for raw in expression_names or []:
        name = str(raw).strip()
        if not name or name.lower() in _VRM_DRIVEN_MORPHS:
            continue
        # VRM 0.x 的 Fcl_EYE_* / Fcl_MTH_* / Fcl_HAIR_* 是功能子簇，不是情绪；
        # 但 Fcl_ALL_Joy 这种整体表情要留下。
        low = name.lower()
        if low.startswith("fcl_") and not is_emotion_expression(name):
            continue
        _append_unique(caps.expressions, name)
    return caps


def build_menu(caps: ModelCapabilities) -> list[tuple[str, str]]:
    """把能力转成下拉框数据 ``[(动作 id, 显示名), ...]``。

    顺序：不响应 -> 动作 -> 情绪表情 -> 功能切换。功能性表情排在最后，
    免得「隐藏兽耳」压在「生气」前面，找起来费劲。
    """
    menu: list[tuple[str, str]] = [(ACTION_NONE, "不响应")]
    builtin = dict(VRM_BUILTIN_MOTIONS)
    for motion in caps.motions:
        label = builtin.get(motion, motion) if caps.kind == "vrm" else motion
        menu.append((PREFIX_MOTION + motion, f"动作：{label}"))

    emotions = [e for e in caps.expressions if not is_utility_expression(e)]
    utilities = [e for e in caps.expressions if is_utility_expression(e)]
    for name in emotions:
        menu.append((PREFIX_EXPRESSION + name, f"表情：{display_expression(name)}"))
    for name in utilities:
        menu.append((PREFIX_EXPRESSION + name, f"切换：{display_expression(name)}"))
    return menu


def split_action(action: str | None) -> tuple[str, str | tuple[str, ...]]:
    """拆解动作 id，兼容旧版写死的 ``wave`` / ``expression_smile`` 等。

    返回 ``(类型, 名字)``；类型为空表示不响应。名字是元组时表示一组候选，
    交给 :func:`resolve_action` 在模型能力里挑。
    """
    if not action or action == ACTION_NONE:
        return "", ""
    text = str(action)
    if text.startswith(PREFIX_MOTION):
        return "motion", text[len(PREFIX_MOTION):]
    if text.startswith(PREFIX_EXPRESSION):
        return "expression", text[len(PREFIX_EXPRESSION):]
    legacy = LEGACY_ACTION_MAP.get(text)
    if legacy:
        return legacy
    return "", text


def _pick(candidates: tuple[str, ...], pool: list[str]) -> str | None:
    """在 ``pool`` 里按优先级找候选名，先精确（忽略大小写）再模糊包含。"""
    if not pool:
        return None
    lowered = {str(name).lower(): str(name) for name in pool}
    for candidate in candidates:
        hit = lowered.get(str(candidate).lower())
        if hit is not None:
            return hit
    for candidate in candidates:
        key = str(candidate).lower()
        if not key:
            continue
        for low, real in lowered.items():
            if key in low:
                return real
    return None


def resolve_action(action: str | None, caps: ModelCapabilities) -> tuple[str, str] | None:
    """把动作 id 落到当前模型的真实名字上；解析不出来返回 ``None``。"""
    kind, name = split_action(action)
    if not kind:
        return None
    pool = caps.motions if kind == "motion" else caps.expressions
    candidates = name if isinstance(name, tuple) else (name,)
    hit = _pick(tuple(candidates), pool)
    if hit is None:
        return None
    return kind, hit


def default_action_for(
    gesture: str,
    caps: ModelCapabilities,
    exclude: set[str] | None = None,
    strong_only: bool = False,
) -> str:
    """给某个手势挑一个当前模型真能执行的默认动作。

    换模型时旧映射十有八九失效（Live2D 的表情名和 VRM 的预设名毫无交集），
    与其让用户对着一个点了没反应的选项，不如按新模型的能力重新给个能用的。

    ``exclude`` 里放已经被别的动手势占掉的动作名，优先避开——否则七个手势
    全指向同一个动作，看起来就像「选什么都没区别」。
    ``strong_only`` 为真时只认「语义明确对得上」的名字（如挥手手势配 Flick），
    不命中就返回 ``none``，由调用方在第二轮用泛匹配捡漏。
    """
    taken = {str(item).lower() for item in (exclude or ())}
    for kind in _GESTURE_KIND_PREFERENCE.get(gesture, ("expression", "motion")):
        if kind == "motion":
            strong: tuple[str, ...] = _GESTURE_MOTION_HINTS.get(gesture, ())
            generic: tuple[str, ...] = _MOTION_PREFERENCE
            pool = caps.motions
        else:
            strong = _GESTURE_EMOTION_HINTS.get(gesture, ())
            generic = EMOTION_HINTS
            pool = [e for e in caps.expressions if is_emotion_expression(e)]
            if not pool:
                pool = [e for e in caps.expressions if not is_utility_expression(e)]
        free = [name for name in pool if name.lower() not in taken]
        hit = _pick(strong, free)
        if hit is None and not strong_only:
            hit = _pick(generic, free) or (free[0] if free else None)
        if hit is None and not strong_only:
            # 空闲的名字都挑完了就允许复用，总比退化成「不响应」强。
            # 这一条绝不能在强匹配阶段跑：否则第二个手势会把第一个刚占下的
            # 名字抢回来（点赞和 OK 双双指向「爱心」就是这么来的）。
            # 复用时仍按「语义明确 -> 通用偏好 -> 模型自带顺序」挑，不能写成
            # `strong or generic`——非空的 strong 会把通用偏好整个顶掉，
            # 于是 peace 这类没有强暗示的手势会白白退化。
            hit = _pick(strong, pool) or _pick(generic, pool) or (pool[0] if pool else None)
        if hit is not None:
            return PREFIX_MOTION + hit if kind == "motion" else PREFIX_EXPRESSION + hit
    return ACTION_NONE


def default_actions(
    caps: ModelCapabilities,
    gestures: tuple[str, ...] | list[str] | None = None,
) -> dict[str, str]:
    """给所有手势一次性分配默认动作，尽量不重复且语义贴合。

    分两轮：第一轮只认语义明确对上的名字（挥手->Flick、握拳->生气…），
    这些名字被占住；第二轮剩下的手势再从空闲的名字里泛匹配捡漏。
    """
    order = [g for g in _GESTURE_DEFAULT_ORDER if not gestures or g in tuple(gestures)]
    for gesture in tuple(gestures or ()):
        if gesture not in order and gesture in _GESTURE_KIND_PREFERENCE:
            order.append(gesture)
    for gesture in tuple(gestures or ()):
        if gesture not in order:
            order.append(gesture)

    assigned: dict[str, str] = {}
    used: set[str] = set()
    for strong_only in (True, False):
        for gesture in order:
            if gesture in assigned:
                continue
            action = default_action_for(gesture, caps, exclude=used, strong_only=strong_only)
            if action == ACTION_NONE:
                continue
            assigned[gesture] = action
            _, name = split_action(action)
            if name:
                used.add(str(name))
    for gesture in order:
        assigned.setdefault(gesture, ACTION_NONE)
    return assigned
