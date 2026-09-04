"""Humanoid rig: build the node hierarchy and turn drive parameters into
skinning matrices.

The rig is pure numpy; it holds the rest local transforms, applies small
world-space rotations for the driven bones (converted into each bone's
local frame using its rest orientation), recomputes global transforms, and
produces ``global[joint] @ inverseBind`` matrices for the GPU/CPU skinning.
"""

from __future__ import annotations

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


class VRMRig:
    """Drives the humanoid bones of a :class:`VRMModel`."""

    def __init__(self, model: VRMModel) -> None:
        self.model = model
        # base local matrices per node index
        self._base_local = {n.index: n.matrix for n in model.nodes}
        # extra local rotation (4x4) per driven node
        self._pose_delta: dict[int, np.ndarray] = {}
        # children / parents
        self._children = {n.index: n.children for n in model.nodes}
        self._parent = {n.index: n.parent for n in model.nodes}
        # rest global orientation (3x3) per node, computed once
        self._rest_global_rot = self._compute_rest_rotations()
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

    def _compute_rest_rotations(self) -> dict[int, np.ndarray]:
        glob = self._compute_globals(self._base_local)
        return {idx: g[:3, :3] for idx, g in glob.items()}

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
        al = clamp(d["arm_l"], -1.0, 1.0)
        ar = clamp(d["arm_r"], -1.0, 1.0)
        alx = clamp(d["arm_l_x"], -1.0, 1.0)
        arx = clamp(d["arm_r_x"], -1.0, 1.0)

        def drive(name: str, world_rot: np.ndarray) -> None:
            node = hb.get(name)
            if node is None:
                return
            rest = self._rest_global_rot.get(node)
            if rest is None:
                return
            local = rest.T @ world_rot @ rest
            self._pose_delta[node] = _to4(local)

        # head yaw / pitch / roll
        drive("head", _rz(az) @ _ry(ax) @ _rx(ay))
        drive("neck", _rz(az * 0.4) @ _ry(ax * 0.4) @ _rx(ay * 0.4))
        # body lean
        drive("spine", _rz(bx) @ _rx(by))
        drive("chest", _rz(bx * 0.6) @ _rx(by * 0.6))
        drive("hips", _rz(bx * -0.2))
        # arms: VRM bind pose is a T-pose, so first bring them down to the
        # sides (natural idle), then follow the hand: forward/up from arm_l,
        # sideways from arm_l_x, and flex the elbow from the hand closeness.
        drive("leftUpperArm", _ry(alx * 35.0) @ _rx(al * 95.0) @ _rz(70.0))
        drive("rightUpperArm", _ry(-arx * 35.0) @ _rx(ar * 95.0) @ _rz(-70.0))

        # natural relaxed elbow: flex the forearm forward + slightly inward,
        # more when the hand is raised (closer to the shoulder).
        flex = (20.0 + max(0.0, al) * 25.0)
        if hb.get("leftLowerArm") is not None:
            self._pose_delta[hb["leftLowerArm"]] = _to4(
                _axis_rot((0, 1, 0), -flex) @ _axis_rot((0, 0, 1), 15.0))
        if hb.get("rightLowerArm") is not None:
            self._pose_delta[hb["rightLowerArm"]] = _to4(
                _axis_rot((0, 1, 0), flex) @ _axis_rot((0, 0, 1), -15.0))

        # fingers: curl each finger from the hand-keypoint signal.
        # Proximal gets most of the curl, Distal least.
        for side in ("left", "right"):
            fkey = f"finger_{side[0]}_"
            for fi in range(5):
                curl = clamp(d.get(f"{fkey}{fi}", 0.0), 0.0, 1.0)
                if curl <= 0.01:
                    continue
                segs = (("Proximal", 0.45), ("Intermediate", 0.35), ("Distal", 0.2))
                finger_name = {0: "Index", 1: "Middle", 2: "Ring", 3: "Little", 4: "Thumb"}[fi]
                for seg, frac in segs:
                    bone = hb.get(f"{side}{finger_name}{seg}")
                    if bone is not None:
                        self._pose_delta[bone] = _to4(_axis_rot((0, 0, 1), curl * 55.0 * frac))
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
