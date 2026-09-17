"""Humanoid rig: build the node hierarchy and turn drive parameters into
skinning matrices.

The rig is pure numpy; it holds the rest local transforms, applies small
world-space rotations for the driven bones (converted into each bone's
local frame using its rest orientation), recomputes global transforms, and
produces ``global[joint] @ inverseBind`` matrices for the GPU/CPU skinning.
"""

from __future__ import annotations

import math

import numpy as np

from app.core.vrm.model import VRMModel


def _rx(deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)


def _ry(deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def _rz(deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float32)


def _to4(rot3: np.ndarray) -> np.ndarray:
    out = np.eye(4, dtype=np.float32)
    out[:3, :3] = rot3
    return out


def _axis_rot(axis: tuple[float, float, float], deg: float) -> np.ndarray:
    """Rotation matrix (3x3) about a world/local axis by degrees."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    x, y, z = axis
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=np.float32)
    return np.eye(3, dtype=np.float32) + s * K + (1 - c) * (K @ K)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _unit(vec: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vec))
    if norm < 1e-9:
        return None
    return vec / norm


def _rotation_between(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """把单位向量 ``src`` 转到单位向量 ``dst`` 的最小旋转（3x3）。"""
    cos = max(-1.0, min(1.0, float(np.dot(src, dst))))
    if cos > 1.0 - 1e-9:
        return np.eye(3, dtype=np.float64)
    if cos < -1.0 + 1e-9:
        # 正好反向：最小旋转不唯一，任取一根与 src 垂直的轴转 180°
        helper = np.array([1.0, 0.0, 0.0])
        if abs(float(src[0])) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])
        axis = _unit(np.cross(src, helper))
        if axis is None:
            return np.eye(3, dtype=np.float64)
        return _axis_rot(tuple(axis), 180.0).astype(np.float64)
    axis = _unit(np.cross(src, dst))
    if axis is None:
        return np.eye(3, dtype=np.float64)
    return _axis_rot(tuple(axis), math.degrees(math.acos(cos))).astype(np.float64)


def _orient(axis: np.ndarray | None, base: np.ndarray, toward: np.ndarray) -> np.ndarray | None:
    """把旋转轴定号，使绕它正向旋转会把 ``base`` 转向 ``toward``。"""
    if axis is None:
        return None
    if float(np.dot(np.cross(axis, base), toward)) < 0.0:
        return -axis
    return axis


class VRMRig:
    """Drives the humanoid bones of a :class:`VRMModel`."""

    #: 四指（食/中/无名/小）各骨节在「完全握起」时绕**弯曲轴**折多少度。
    #: 近节 85°、中节 90°、远节 55°；真人握拳约 90/110/70，取略小一点，
    #: 免得指尖穿过掌心。
    _FINGER_CURL = {"Proximal": 85.0, "Intermediate": 90.0, "Distal": 55.0}
    #: 拇指只驱动 Proximal / Distal：Metacarpal 埋在掌心里，转它会把整根拇指
    #: 从掌侧掀出去；拇指的活动范围也比四指小。
    _THUMB_CURL = {"Proximal": 50.0, "Distal": 50.0}
    #: 四指命名与骨节链（VRM 0.x / 1.0 都是这套名字）。
    _FINGERS = ("Index", "Middle", "Ring", "Little")
    _FINGER_SEGMENTS = ("Proximal", "Intermediate", "Distal")

    def __init__(self, model: VRMModel) -> None:
        self.model = model
        # base local matrices per node index
        self._base_local = {n.index: n.matrix for n in model.nodes}
        # extra local rotation (4x4) per driven node
        self._pose_delta: dict[int, np.ndarray] = {}
        # children / parents
        self._children = {n.index: n.children for n in model.nodes}
        self._parent = {n.index: n.parent for n in model.nodes}
        # rest global transforms (4x4) and orientations (3x3), computed once.
        # The translations are what the arm axes are measured from.
        self._rest_global = self._compute_globals(self._base_local)
        self._rest_global_rot = {idx: g[:3, :3] for idx, g in self._rest_global.items()}
        # anatomical axes of the arms, derived from the rest pose (lazy)
        self._anatomy_cache: dict | None = None
        # per-bone finger bend axes, also derived from the rest pose (lazy)
        self._finger_cache: dict[str, np.ndarray] | None = None
        # current drive params
        self._drive = self._default_drive()
        self._globals_ok = False
        self._global: dict[int, np.ndarray] = {}
        self._skinning_cache: dict[int, np.ndarray] = {}

    # ------------------------------------------------------------------
    @staticmethod
    def _default_drive() -> dict:
        d = {
            "angle_x": 0.0, "angle_y": 0.0, "angle_z": 0.0,
            "body_angle_x": 0.0, "body_angle_y": 0.0,
            "arm_l": 0.0, "arm_r": 0.0,
            "arm_l_x": 0.0, "arm_r_x": 0.0,
            # 上臂摆角（度，相对"手臂自然下垂"）与肘部弯曲（度）——
            # 这才是骨骼真正吃的两路信号，见 _apply_arms。
            "arm_swing_l": 0.0, "arm_swing_r": 0.0,
            "elbow_l": 0.0, "elbow_r": 0.0,
            # 整条手臂的前倾角（度，绕身体左右轴）。单目动捕看不到深度，
            # 手伸到躯干轮廓里时只能靠它把手臂摆到身体前方，见 _apply_arms。
            "arm_fwd_l": 0.0, "arm_fwd_r": 0.0,
            "eye_x": 0.0, "eye_y": 0.0,
            "eye_open_l": 1.0, "eye_open_r": 1.0,
            "mouth_open": 0.0,
        }
        for side in ("l", "r"):
            for i in range(5):
                d[f"finger_{side}_{i}"] = 0.0
        # full-body (from YOLO pose)
        for side in ("l", "r"):
            d[f"thigh_{side}"] = 0.0      # side-swing degrees
            d[f"thigh_lift_{side}"] = 0.0  # forward-lift 0..1
            d[f"knee_{side}"] = 0.0        # knee bend degrees
        return d

    def _compute_globals(self, local: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        out: dict[int, np.ndarray] = {}

        def visit(node_idx: int, parent_global: np.ndarray) -> None:
            eff = local[node_idx]
            g = parent_global @ eff
            out[node_idx] = g
            for c in self._children.get(node_idx, []):
                visit(c, g)

        for root in self.model.root_nodes:
            visit(root, np.eye(4, dtype=np.float32))
        # handle any node not reachable from roots (shouldn't happen)
        for node in self.model.nodes:
            if node.index not in out:
                visit(node.index, np.eye(4, dtype=np.float32))
        return out

    # ------------------------------------------------------------------
    def set_drive(self, **kwargs) -> None:
        self._drive.update({k: v for k, v in kwargs.items() if k in self._drive})
        self._globals_ok = False

    def reset(self) -> None:
        self._drive = self._default_drive()
        self._pose_delta.clear()
        self._globals_ok = False

    def expressions_for_look(self) -> dict[str, float]:
        """When no eye bones exist, drive look via VRM expressions.

        ``eye_x``/``eye_y`` arrive in degrees from motion capture; normalise to
        [-1, 1] before turning them into expression weights.
        """
        d = self._drive
        ex = max(-1.0, min(1.0, d["eye_x"] / 18.0))
        ey = max(-1.0, min(1.0, d["eye_y"] / 18.0))
        return {
            "lookLeft": max(0.0, -ex),
            "lookRight": max(0.0, ex),
            "lookUp": max(0.0, -ey),
            "lookDown": max(0.0, ey),
        }

    # ------------------------------------------------------------------
    # 手臂解剖轴
    #
    # VRM 的**绑定姿态各模型差别极大**：仓库里的 AliciaSolid 是标准 T-pose
    # （手臂沿 ±X 水平伸出），Seed-san 的手臂则朝 +Z 前伸。以前按 T-pose 假设
    # 写死 `_rz(70)` 想把手臂拉下来，对 AliciaSolid 勉强能用（70° ≈ 从水平转到
    # 下垂所需的 72°），对 Seed-san 就完全是乱转；肘部更是从固定轴给一个常量
    # 20° 左右，表现就是用户说的"胳膊只能伸直和放下，不能像现实一样弯曲旋转"。
    #
    # 这里改成三步，全部由模型自己的静息骨骼**位置**量出来：
    #   1. 从肩连线得到左右轴，由它叉乘竖直方向得到模型正面朝向；
    #   2. 量出上臂/前臂的静息方向，算出把这个"绑定姿态"摆到自然下垂所需的
    #      基准旋转（T-pose 模型约 72°，手臂前伸的模型约 95°）；
    #   3. 在自然下垂的姿态上定出摆轴（抬落）和肘轴（弯曲），再叠加动捕增量。
    # 动捕给 0 时手臂就是自然下垂，而不是举着。
    def _anatomy(self) -> dict | None:
        """量出左右轴 / 前后轴、手臂的绑定方向与"自然下垂"基准旋转（结果缓存）。"""
        if self._anatomy_cache is not None:
            return self._anatomy_cache
        hb = self.model.humanoid

        def pos(name: str) -> np.ndarray | None:
            node = hb.get(name)
            if node is None:
                return None
            matrix = self._rest_global.get(node)
            return None if matrix is None else matrix[:3, 3].astype(np.float64)

        shoulder_l, shoulder_r = pos("leftShoulder"), pos("rightShoulder")
        if shoulder_l is None or shoulder_r is None:
            return None
        up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        side_axis = shoulder_l - shoulder_r
        side_axis[1] = 0.0  # 肩连线取水平分量，避免模型本身歪着站时带进倾斜
        side_axis = _unit(side_axis)
        if side_axis is None:
            return None
        fwd_axis = _unit(np.cross(side_axis, up))
        if fwd_axis is None:
            return None

        #: 自然下垂时手臂相对竖直方向的外张角（A-pose 大约 15~20°）
        splay = 0.30
        arms: dict[str, dict[str, np.ndarray]] = {}
        for side, key in (("left", "l"), ("right", "r")):
            upper_arm = pos(f"{side}UpperArm")
            lower_arm = pos(f"{side}LowerArm")
            hand = pos(f"{side}Hand")
            if upper_arm is None or lower_arm is None:
                continue
            upper = _unit(lower_arm - upper_arm)
            if upper is None:
                continue
            fore = _unit(hand - lower_arm) if hand is not None else None
            if fore is None:
                fore = upper

            outward = side_axis if key == "l" else -side_axis
            idle = _unit(-up + splay * outward)
            if idle is None:
                idle = upper
            # 基准旋转：把绑定姿态摆成"自然下垂"。这是每个模型自己的量，
            # 不是写死的角度——这正是旧代码出错的地方。
            baseline = _rotation_between(upper, idle)
            fore_idle = _unit(baseline @ fore)
            if fore_idle is None:
                fore_idle = idle

            # 摆轴：绕它正向转能把手臂从"自然下垂"抬向正上方。
            raise_axis = _orient(_unit(np.cross(idle, up)), idle, up)
            if raise_axis is None:
                # 手臂正好竖着，退化用左右轴（变成向外张开）
                raise_axis = _orient(_unit(np.cross(idle, outward)), idle, up)
            if raise_axis is None:
                raise_axis = fwd_axis
            # 肘轴：垂直前臂与模型正面。绕它正向转，小臂朝模型正面折——手臂
            # 下垂时是"小臂向前抬"，手臂前伸时是"小臂向上折"，两种情况都对。
            bend_idle = _orient(_unit(np.cross(fore_idle, fwd_axis)), fore_idle, fwd_axis)
            if bend_idle is None:
                bend_idle = _orient(_unit(np.cross(fore_idle, up)), fore_idle, up)
            if bend_idle is None:
                bend_idle = raise_axis
            arms[key] = {
                "upper": upper,
                "fore": fore,
                "idle": idle,
                "baseline": baseline,
                "raise": raise_axis,
                # 肘部的旋转是挂在（已经转过的）上臂下面执行的，所以轴向要
                # 先换算回绑定姿态那一帧，链条上才会跟着上臂一起转。
                "bend": baseline.T @ bend_idle,
            }

        cache = {
            "side": side_axis,
            "fwd": fwd_axis,
            "up": up,
            "arms": arms,
            # 手臂前倾轴：绕它正向转，下垂的手臂会朝模型正面抬起来（肩前屈）。
            # 手伸到身体前方时用它把整条手臂从躯干里挪出来。
            "tilt": _orient(side_axis, -up, fwd_axis),
        }
        self._anatomy_cache = cache
        return cache

    # ------------------------------------------------------------------
    # 手指弯曲轴
    #
    # 旧实现让每根指骨绕**自己的局部 Z 轴**转固定角度，这是「手指撇到外翻一圈」
    # 的直接原因：各指骨（尤其拇指）的局部坐标系朝向互不相同，局部 Z 轴有的
    # 指向掌心、有的指向手背、有的指向侧面，统统一转就拧成了外翻/侧撇。
    #
    # 正确做法是从静息姿态里量出**掌心指向**，再取
    #     弯曲轴 = 指骨方向 × 掌心方向
    # 由右手定则，绕这个轴正向旋转一定把指尖折向掌心。
    #
    # 掌心指向的符号不能看单根手指（静息姿态略直时两解分量接近，会翻），改用
    # 四指投票：每根手指都算一次「指尖应绕轴朝手腕折」，四指的弯曲方向之和就是
    # 稳定的掌心方向；拇指再沿用它——拇指自己的静息朝向常和四指差很多，拿它
    # 自己那一票定号反而会翻。
    def _finger_axes(self) -> dict[str, np.ndarray]:
        """量出每根指骨的弯曲轴（世界坐标），键是 humanoid 骨骼名。"""
        if self._finger_cache is not None:
            return self._finger_cache
        hb = self.model.humanoid

        def pos(name: str) -> np.ndarray | None:
            node = hb.get(name)
            if node is None:
                return None
            matrix = self._rest_global.get(node)
            return None if matrix is None else matrix[:3, 3].astype(np.float64)

        out: dict[str, np.ndarray] = {}
        for side in ("left", "right"):
            wrist = pos(f"{side}Hand")
            mcp = {name: pos(f"{side}{name}Proximal") for name in self._FINGERS}
            distal = {name: pos(f"{side}{name}Distal") for name in self._FINGERS}
            if wrist is None or any(p is None for p in mcp.values()):
                continue
            palm_fwd = _unit(mcp["Middle"] - wrist)
            palm_side = _unit(mcp["Little"] - mcp["Index"])
            if palm_fwd is None or palm_side is None:
                continue
            normal = _unit(np.cross(palm_fwd, palm_side))
            if normal is None:
                continue

            flex_sum = np.zeros(3, dtype=np.float64)
            axes: dict[str, np.ndarray] = {}
            for name in self._FINGERS:
                tip = distal[name]
                base = mcp[name]
                if tip is None:
                    continue
                direction = _unit(tip - base)
                if direction is None:
                    continue
                axis = _orient(
                    _unit(np.cross(direction, normal)), tip - base, wrist - tip)
                if axis is None:
                    continue
                axes[name] = axis
                flex_sum += np.cross(axis, direction)
            flex = _unit(flex_sum)
            if flex is None:
                continue

            for name, axis in axes.items():
                for seg in self._FINGER_SEGMENTS:
                    key = f"{side}{name}{seg}"
                    if key in hb:
                        out[key] = axis

            thumb_base = pos(f"{side}ThumbProximal")
            if thumb_base is None:
                thumb_base = pos(f"{side}ThumbMetacarpal")
            thumb_tip = pos(f"{side}ThumbDistal")
            if thumb_base is not None and thumb_tip is not None:
                thumb_dir = _unit(thumb_tip - thumb_base)
                if thumb_dir is not None:
                    thumb_axis = _unit(np.cross(thumb_dir, flex))
                    if thumb_axis is not None:
                        for seg in self._THUMB_CURL:
                            key = f"{side}Thumb{seg}"
                            if key in hb:
                                out[key] = thumb_axis

        self._finger_cache = out
        return out

    # ------------------------------------------------------------------
    def _drive_bone(self, name: str, world_rot: np.ndarray) -> None:
        """给某根骨骼叠加一个**世界坐标系**下的旋转。

        世界旋转要换算到骨骼自己的局部坐标系（``restᵀ · R · rest``）才能和
        glTF 的局部矩阵相乘；直接把世界旋转当局部用会变成绕骨骼自身轴向的
        扭转——肘部这样调就只会原地打转，一点弯都不出来。
        """
        node = self.model.humanoid.get(name)
        if node is None:
            return
        rest = self._rest_global_rot.get(node)
        if rest is None:
            return
        self._pose_delta[node] = _to4(rest.T @ world_rot @ rest)

    def _apply_arms(self, d: dict) -> None:
        """上臂抬落 + 肘部弯曲 + 整臂前倾。

        - ``arm_swing_l/r``：上臂摆角（度），相对"手臂自然下垂"。0 表示自然
          下垂（T-pose 模型会被归位），正值绕摆轴把手臂抬向正上方。
        - ``elbow_l/r``：肘部弯曲（度），0 = 伸直。
        - ``arm_fwd_l/r``：整条手臂前倾（度，肩前屈）。单目动捕看不到深度，
          手伸到躯干轮廓里时靠它把手臂摆到身体前方，否则模型的小臂会插进肚子。
        """
        anatomy = self._anatomy()
        if anatomy is None:
            return
        tilt = anatomy.get("tilt")
        for side, key in (("left", "l"), ("right", "r")):
            arm = anatomy["arms"].get(key)
            if arm is None:
                continue
            swing = _clamp(float(d.get(f"arm_swing_{key}", 0.0) or 0.0), -45.0, 175.0)
            elbow = _clamp(float(d.get(f"elbow_{key}", 0.0) or 0.0), 0.0, 150.0)
            fwd = _clamp(float(d.get(f"arm_fwd_{key}", 0.0) or 0.0), -25.0, 80.0)
            # 先归位到自然下垂，再按摆角抬起。swing=0 时就是 baseline 本身。
            world = _axis_rot(tuple(arm["raise"]), swing) @ arm["baseline"]
            if abs(fwd) > 0.01 and tilt is not None:
                # 前倾是「整条手臂」一起转：上臂转过去以后，小臂/手作为子节点
                # 自然跟着走，肘部的弯曲轴也一并被带转，所以只驱动上臂就够。
                world = _axis_rot(tuple(tilt), fwd) @ world
            self._drive_bone(f"{side}UpperArm", world)
            if elbow > 0.01:
                self._drive_bone(
                    f"{side}LowerArm", _axis_rot(tuple(arm["bend"]), elbow))

    # ------------------------------------------------------------------
    def _apply_drive(self) -> None:
        """Build pose deltas for the driven bones."""
        d = self._drive
        hb = self.model.humanoid
        self._pose_delta.clear()

        def clamp(value: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, value))

        # Motion capture reports head/eye angles in degrees (up to ±90 or more).
        # Clamp everything into a sane range so nothing spins, and turn the eye
        # signal into a normalised [-1,1] value scaled to a small eye-bone turn.
        ax = clamp(d["angle_x"], -30.0, 30.0)
        ay = clamp(d["angle_y"], -30.0, 30.0)
        az = clamp(d["angle_z"], -30.0, 30.0)
        bx = clamp(d["body_angle_x"], -30.0, 30.0)
        by = clamp(d["body_angle_y"], -30.0, 30.0)
        ex = clamp(d["eye_x"] / 18.0, -1.0, 1.0)
        ey = clamp(d["eye_y"] / 18.0, -1.0, 1.0)

        def drive(name: str, world_rot: np.ndarray) -> None:
            self._drive_bone(name, world_rot)

        # head yaw / pitch / roll
        drive("head", _rz(az) @ _ry(ax) @ _rx(ay))
        drive("neck", _rz(az * 0.4) @ _ry(ax * 0.4) @ _rx(ay * 0.4))
        # body lean
        drive("spine", _rz(bx) @ _rx(by))
        drive("chest", _rz(bx * 0.6) @ _rx(by * 0.6))
        drive("hips", _rz(bx * -0.2))
        # arms: 见 _apply_arms（以模型静息姿态为锚点，不再写死欧拉角）
        self._apply_arms(d)

        # fingers: curl each finger from the hand-keypoint signal.
        # 弯曲轴由静息姿态量出（见 _finger_axes），绕它正向转一定是「折向掌心」；
        # 旧代码绕每根指骨自己的局部 Z 轴转，各指骨朝向不同，拇指和小指会被拧
        # 成外翻——用户说的「手指都能撇到外翻一圈」。
        finger_axes = self._finger_axes()
        if finger_axes:
            finger_names = {0: "Index", 1: "Middle", 2: "Ring", 3: "Little", 4: "Thumb"}
            for side in ("left", "right"):
                fkey = f"finger_{side[0]}_"
                for fi in range(5):
                    curl = clamp(d.get(f"{fkey}{fi}", 0.0), 0.0, 1.0)
                    if curl <= 0.01:
                        continue
                    name = finger_names[fi]
                    segments = self._THUMB_CURL if name == "Thumb" else self._FINGER_CURL
                    for seg, angle in segments.items():
                        bone = f"{side}{name}{seg}"
                        axis = finger_axes.get(bone)
                        if axis is None:
                            continue
                        self._drive_bone(bone, _axis_rot(tuple(axis), curl * angle))
        # eyes (only if eye bones exist) — small turn, never spins
        if "leftEye" in hb and "rightEye" in hb:
            eye_rot = _rx(-ey * 15.0) @ _ry(-ex * 15.0)
            drive("leftEye", eye_rot)
            drive("rightEye", eye_rot)

        # legs (from YOLO pose, confidence-gated): thigh side-swing about world Z
        # and knee bend about world X.  Forward hip-flexion is not reliably
        # measurable in a 2D frontal pose, so we keep it at 0 to avoid flailing;
        # when keypoints are missing the drive is zeroed upstream -> hold still.
        legs = (("left", "l"), ("right", "r"))
        for side, key in legs:
            thigh_deg = clamp(d.get(f"thigh_{key}", 0.0), -60.0, 60.0)
            knee_deg = clamp(d.get(f"knee_{key}", 0.0), 0.0, 120.0)
            if hb.get(f"{side}UpperLeg") is not None:
                drive(f"{side}UpperLeg", _rz(thigh_deg))
            if hb.get(f"{side}LowerLeg") is not None:
                self._pose_delta[hb[f"{side}LowerLeg"]] = _to4(_axis_rot((1, 0, 0), -knee_deg))

    # ------------------------------------------------------------------
    def update(self) -> None:
        """Recompute global transforms and skinning matrices."""
        self._apply_drive()
        local = {}
        for idx in self._base_local:
            delta = self._pose_delta.get(idx)
            local[idx] = (self._base_local[idx] @ delta) if delta is not None else self._base_local[idx]
        self._global = self._compute_globals(local)
        self._skinning_cache.clear()
        for si, skin in enumerate(self.model.skins):
            mats = np.repeat(np.eye(4, dtype=np.float32)[None], len(skin.joints), axis=0)
            for j, node in enumerate(skin.joints):
                g = self._global.get(node)
                if g is not None:
                    mats[j] = g @ skin.inv_bind[j]
            self._skinning_cache[si] = mats
        self._globals_ok = True

    # ------------------------------------------------------------------
    def global_of(self, node: int) -> np.ndarray:
        if not self._globals_ok:
            self.update()
        return self._global.get(node, np.eye(4, dtype=np.float32))

    def skin_matrices(self, skin_index: int) -> np.ndarray:
        if not self._globals_ok:
            self.update()
        return self._skinning_cache.get(skin_index, np.zeros((0, 4, 4), dtype=np.float32))

    def has_eye_bones(self) -> bool:
        hb = self.model.humanoid
        return "leftEye" in hb and "rightEye" in hb

    # convenience: bounding box of the whole model in rest pose (approx)
    def rest_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (min, max) over node global translations and base vertices."""
        pts = []
        for node in self.model.nodes:
            g = self.global_of(node.index)
            pts.append(g[:3, 3])
        arr = np.asarray(pts, dtype=np.float32)
        return arr.min(0), arr.max(0)
