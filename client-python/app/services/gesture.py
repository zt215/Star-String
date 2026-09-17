"""静态手势识别（Static hand gesture recognition）。

输入是 MediaPipe HandLandmarker 的 21 个手部关键点，输出一个手势标识，
用于触发虚拟形象的动作 / 表情。

判定思路：先算每根手指的伸展程度（用指节夹角，与手的远近、朝向无关），
再按「伸直了哪几根手指 + 拇指与食指的距离」区分手势。不做机器学习，
规则法在单手静态手势上足够稳定，也便于在论文里解释判据。

**为什么要同时吃世界坐标（3D）**：单目图像只有两个自由度，手指**正对摄像头**
时，伸出的那根手指在画面里被压成一小段，另外三根卷起的手指又和它投影重叠，
于是「伸直了几根」这个判据完全失真——侧面看能认出指向，正对镜头却会认成
握拳 / 点赞。HandLandmarker 同时输出 ``hand_world_landmarks``（以手掌几何
中心为原点的米制三维坐标），它的指节夹角是**真正的三维夹角**，不受投影方向
影响，所以只要能拿到就用它算几何量；拿不到再退回二维像素坐标。
"""

from __future__ import annotations

import math

#: 中指 MCP 到手腕的距离，作为手的尺度基准，用于做尺度归一化
_WRIST = 0
_MIDDLE_MCP = 9
_INDEX_MCP = 5
_INDEX_PIP = 6
_MIDDLE_PIP = 10

#: 四指 (MCP, PIP, TIP)
_FINGERS = {
    "index": (5, 6, 8),
    "middle": (9, 10, 12),
    "ring": (13, 14, 16),
    "pinky": (17, 18, 20),
}

#: 拇指 (MCP, IP, TIP)
_THUMB = (2, 3, 4)

#: 指节接近伸直 / 弯曲的夹角阈值（度）
_STRAIGHT_DEG = 145.0
_CURLED_DEG = 115.0

#: 「单独伸出一根手指」的**相对**判据（指向的兜底）。
#:
#: 上面的绝对阈值有个死区：指节状态落在 0.35~0.6 之间时既不算伸直也不算弯曲，
#: 四根手指全落进去就会数出 ``count == 0`` → 判成握拳。真实的手做「单指」时
#: 食指常常只伸到 130° 上下（世界坐标本身也带抖动），正好落进死区，于是
#: **单指被认成握拳**（用户实测）。而握拳时四指是**齐平**的，指向时有一根
#: 明显比其余三根直——看「最直的一根领先第二名多少」就能兜住：
#: 单指实测领先 0.47、握拳只剩 0.05。
_SOLO_GAP = 0.30
_SOLO_MIN = 0.35

#: 拇指「张开」判据——看拇指尖离**食指近端指骨**有多远（除以手掌尺度）。
#: 不能看拇指自己的指节夹角：握拳时拇指往往是**直**的，只是搭在四指上，
#: IP 夹角接近 180° 会把握拳读成点赞。实测握拳 ≈ 0.2、点赞 ≈ 0.8。
_THUMB_TUCK = 0.34
_THUMB_SPREAD = 0.64

#: 手势标识 -> 中文名
GESTURE_NAMES = {
    "fist": "握拳",
    "open_palm": "张开手掌",
    "peace": "比耶",
    "point": "指向",
    "thumb_up": "点赞",
    "ok": "OK",
    "rock": "摇滚",
}

#: 默认的手势 -> 动作 映射。这里的动作 id 是**旧格式**（``wave`` /
#: ``expression_smile``），只作为首次运行的起点：界面构建时会拿它去当前模型
#: 的能力清单里解析（见 ``model_actions.resolve_action``），解不出来就换成按
#: 模型实际支持的动作 / 表情推导出的默认值。
DEFAULT_GESTURE_ACTIONS = {
    "open_palm": "wave",
    "peace": "motion_tap",
    "thumb_up": "expression_smile",
    "ok": "expression_smile",
    "fist": "expression_angry",
    "point": "none",
    "rock": "none",
}

#: 旧格式动作 id 的中文名。
#:
#: **手势菜单的选项不再来自这里**——选项由 ``model_actions.build_menu`` 按当前
#: 模型实际支持的动作组和表情名动态生成（Live2D 的表情叫「生气」「爱心」，
#: VRM 叫 happy/angry，动作组名每个模型都不一样，写死的列表必然对不上）。
#: 保留这张表只是为了让旧 id 在日志、迁移提示里还能显示成人话。
ACTION_LABELS = {
    "none": "不响应",
    "wave": "挥手 / 打招呼",
    "motion_tap": "播放动作（Tap）",
    "motion_idle": "播放动作（Idle）",
    "expression_smile": "表情：微笑",
    "expression_surprised": "表情：惊讶",
    "expression_angry": "表情：生气",
}


def _point(points, index: int) -> tuple:
    """取一个关键点。二维点会被补成 z=0，好让同一条向量代码同时吃 2D / 3D。"""
    raw = points[index]
    if len(raw) >= 3:
        return float(raw[0]), float(raw[1]), float(raw[2])
    return float(raw[0]), float(raw[1]), 0.0


def _sub(a, b) -> tuple:
    return tuple(ai - bi for ai, bi in zip(a, b))


def _norm(v) -> float:
    return math.sqrt(sum(c * c for c in v))


def _distance(a, b) -> float:
    return _norm(_sub(a, b))


def _angle_deg(a, b, c) -> float:
    """顶点在 ``b`` 处的夹角（度）。二维、三维点都能算。"""
    v1, v2 = _sub(a, b), _sub(c, b)
    n1, n2 = _norm(v1), _norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 180.0
    cosang = max(-1.0, min(1.0, sum(x * y for x, y in zip(v1, v2)) / (n1 * n2)))
    return math.degrees(math.acos(cosang))


def _segment_distance(p, a, b) -> float:
    """点 ``p`` 到线段 ``a``-``b`` 的距离。"""
    ab = _sub(b, a)
    length2 = sum(c * c for c in ab)
    if length2 < 1e-12:
        return _distance(p, a)
    t = sum((pi - ai) * abi for pi, ai, abi in zip(p, a, ab)) / length2
    t = max(0.0, min(1.0, t))
    closest = tuple(ai + abi * t for ai, abi in zip(a, ab))
    return _distance(p, closest)


def _world(points, world) -> list | None:
    """世界坐标可用就返回它，否则返回 ``None``（退回二维点）。"""
    if world is None or len(world) < 21 or len(points) < 21:
        return None
    try:
        return [_point(world, i) for i in range(21)]
    except (TypeError, ValueError, IndexError):
        return None


def finger_states(points, world=None) -> dict:
    """返回四指的伸展程度与拇指是否伸展。

    ``states`` 里每个值是 0.0（完全弯曲）~ 1.0（完全伸直）。
    有世界坐标（``world``，米制三维）时几何量全部用它算——二维投影在
    「手指正对摄像头」时会把指节夹角压扁，三维夹角才是真值。
    """
    source = _world(points, world) or [_point(points, i) for i in range(21)]

    states: dict[str, float] = {}
    span = _STRAIGHT_DEG - _CURLED_DEG
    for name, (mcp, pip, tip) in _FINGERS.items():
        angle = _angle_deg(_point(source, mcp), _point(source, pip), _point(source, tip))
        # 145° 以上算伸直，115° 以下算弯曲，中间线性过渡
        states[name] = max(0.0, min(1.0, (angle - _CURLED_DEG) / span))

    mcp, ip, tip = _THUMB
    straight = _angle_deg(_point(source, mcp), _point(source, ip), _point(source, tip))
    straight_score = (straight - _CURLED_DEG) / span

    # 「张开」看拇指尖离食指近端指骨有多远，而不是拇指自己弯不弯：
    # 握拳时拇指常常是直的、只是搭在四指上（IP 夹角接近 180°），
    # 只看指节夹角会把握拳读成点赞。握拳时拇指尖贴着食指（或中指）指骨，
    # 距离很小；点赞时拇指伸到一边，距离接近手掌尺度。
    scale = max(_distance(_point(source, _WRIST), _point(source, _MIDDLE_MCP)), 1e-9)
    tip_point = _point(source, tip)
    gap = min(
        _segment_distance(tip_point, _point(source, _INDEX_MCP), _point(source, _INDEX_PIP)),
        _segment_distance(tip_point, _point(source, _MIDDLE_MCP), _point(source, _MIDDLE_PIP)),
    ) / scale
    spread_score = (gap - _THUMB_TUCK) / (_THUMB_SPREAD - _THUMB_TUCK)

    # 两个条件取较小值：既要有离开掌心的距离，也要拇指本身不是蜷着的。
    states["thumb"] = max(0.0, min(1.0, min(straight_score, spread_score)))
    return states


def classify(points, world=None) -> str | None:
    """识别单手手势，无法确定时返回 ``None``。

    ``points`` 是二维像素坐标（也用于判断拇指尖是否朝上，那是画面里的方向）；
    ``world`` 是可选的世界坐标，几何量优先用它算，见模块开头说明。
    """
    if points is None or len(points) < 21:
        return None
    image_scale = _distance(_point(points, _WRIST), _point(points, _MIDDLE_MCP))
    world_points = _world(points, world)
    if world_points is None and image_scale < 1e-3:
        # 没有世界坐标时，画面里手完全没有宽度就没法估尺度了；有世界坐标的话
        # 只是画面侧过来了而已，几何量照样算得出来。
        return None

    source = world_points or [_point(points, i) for i in range(21)]
    scale = _distance(_point(source, _WRIST), _point(source, _MIDDLE_MCP))
    if scale < 1e-9:
        return None

    states = finger_states(points, world)
    extended = {name: states[name] > 0.6 for name in _FINGERS}
    curled = {name: states[name] < 0.35 for name in _FINGERS}
    thumb_out = states["thumb"] > 0.55

    count = sum(1 for value in extended.values() if value)

    # OK：拇指与食指尖捏在一起，其余三指伸直
    pinch = _distance(_point(source, 4), _point(source, 8)) / scale
    if pinch < 0.45 and all(extended[n] for n in ("middle", "ring", "pinky")):
        return "ok"

    # 点赞：只有拇指伸出，且拇指尖明显高于手腕（图像上方）
    if (
        thumb_out
        and count == 0
        and _point(points, 4)[1] < _point(points, _WRIST)[1] - 0.3 * image_scale
    ):
        return "thumb_up"

    # 四指全伸就算张开手掌，不强制要求拇指也在画面里判定为伸出
    if count == 4:
        return "open_palm"

    if count == 0:
        # 先排除「单独伸出一根手指」：握拳时四指齐平，而指向时有一根明显
        # 领先——绝对阈值会把半伸的食指漏进死区，落到这里就变成握拳了。
        ranked = sorted(((states[name], name) for name in _FINGERS), reverse=True)
        top_state, top_name = ranked[0]
        if top_state - ranked[1][0] >= _SOLO_GAP and top_state >= _SOLO_MIN:
            if top_name == "index":
                return "point"
        return "fist"

    if count == 2 and extended["index"] and extended["middle"] and curled["ring"] and curled["pinky"]:
        return "peace"

    if count == 2 and extended["index"] and extended["pinky"] and curled["middle"] and curled["ring"]:
        return "rock"

    if count == 1 and extended["index"]:
        return "point"

    return None


def gesture_name(gesture: str | None) -> str:
    if not gesture:
        return "—"
    return GESTURE_NAMES.get(gesture, gesture)
