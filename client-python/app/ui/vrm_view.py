"""VRM 模型视图实现（完整可动皮套）。

使用 pygltflib + numpy 解析 VRM/GLB，构建 humanoid 骨骼，把动捕驱动参数
施加到骨骼/表情上，并在 CPU 完成蒙皮 + 形态键后上传到 GPU 渲染。
"""

from __future__ import annotations

import math
import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QElapsedTimer, QTimer, Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import glViewport, glClear, glClearColor, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT

from app.core.vrm.model import build as build_model
from app.core.vrm.rig import VRMRig
from app.core.vrm.renderer import VRMRenderer
from app.services import model_actions

from app.ui.model_view_base import (
    ModelParam,
    ModelType,
    ModelViewInterface,
    ModelViewSignals,
)

# 常用表情（按偏好顺序，取模型里存在的那一个）
_MOUTH_PRESETS = ("aa", "A", "a", "oh", "O", "ou", "u")
_BLINK_PRESETS = ("blink", "Blink")
_LOOK_PRESETS = ("lookLeft", "lookRight", "lookUp", "lookDown")

# 口型形状：形状值偏正（亮、扁）用张口元音，偏负（暗、圆）用圆唇元音
_WIDE_MOUTH_PRESETS = ("aa", "A", "a", "ih", "I", "i")
_ROUND_MOUTH_PRESETS = ("ou", "O", "o", "oh", "u")

# 手势触发的表情 -> 候选表情名（兼容 VRM 1.0 与 VRM 0.x 命名）
_EXPRESSION_PRESETS = {
    "smile": ("happy", "Happy", "joy", "Joy", "fun", "Fun"),
    "surprised": ("surprised", "Surprised", "surprise", "Surprise"),
    "angry": ("angry", "Angry", "anger", "Anger"),
}


# ---------------------------------------------------------------------------
# 内置动作：VRM 没有动作文件，动作只能现场生成骨骼动画。
#
# 每个动作是一个 ``phase -> {驱动键: 值}`` 的函数，phase 从 0 走到 1。
# 键名就是 ``VRMRig`` 吃的那几路信号（见 rig._apply_arms / _apply_drive）：
# 上臂摆角、肘弯曲、整臂前倾，以及头颈和躯干的三个旋转角。
# 所有动作都被 ``_envelope`` 在首尾压到 0（起手收手都是静息姿态），
# 这样动画结束时撤掉覆盖层不会「啪」地弹回原位。
# ---------------------------------------------------------------------------


def _smooth(value: float) -> float:
    """0..1 的平滑曲线（smoothstep），两端导数为 0，关节不会顿一下。"""
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _envelope(phase: float, rise: float = 0.15, fall: float = 0.20) -> float:
    """动作的整体包络：开头 ``rise`` 段淡入，结尾 ``fall`` 段淡出。"""
    if phase <= 0.0 or phase >= 1.0:
        return 0.0
    up = min(1.0, phase / rise) if rise > 0 else 1.0
    down = min(1.0, (1.0 - phase) / fall) if fall > 0 else 1.0
    return _smooth(min(up, down))


def _pulse(phase: float, peak_at: float = 0.30, down_at: float = 0.62) -> float:
    """先升到 1、保持一段、再降回 0，用于「弯下去停一下再起来」这类动作。"""
    if phase <= 0.0 or phase >= 1.0:
        return 0.0
    if phase < peak_at:
        return _smooth(phase / peak_at)
    if phase < down_at:
        return 1.0
    return _smooth((1.0 - phase) / (1.0 - down_at))


def _wave_pose(phase: float) -> dict[str, float]:
    """右手举过肩左右摆两次。"""
    amp = _envelope(phase, 0.15, 0.20)
    swing = 135.0 + 25.0 * math.sin(2.0 * math.pi * 2.0 * phase)
    return {
        "arm_swing_r": swing * amp,
        "elbow_r": 70.0 * amp,
        "arm_fwd_r": 25.0 * amp,
        "body_angle_x": -5.0 * amp,
        "angle_z": -6.0 * amp,
    }


def _nod_pose(phase: float) -> dict[str, float]:
    """低头两次（(1-cos)/2 保证每个循环都从 0 出发，不会先仰头）。"""
    amp = _envelope(phase, 0.15, 0.20)
    beat = (1.0 - math.cos(2.0 * math.pi * 2.0 * phase)) / 2.0
    return {"angle_y": 22.0 * beat * amp}


def _shake_pose(phase: float) -> dict[str, float]:
    """左右摇头两次半。"""
    amp = _envelope(phase, 0.15, 0.20)
    return {"angle_x": 22.0 * math.sin(2.0 * math.pi * 2.5 * phase) * amp}


def _bow_pose(phase: float) -> dict[str, float]:
    """躯干前倾鞠躬，停一下再起来。"""
    shape = _pulse(phase, 0.30, 0.62)
    return {
        "body_angle_y": 34.0 * shape,
        "angle_y": 14.0 * shape,
        "arm_fwd_l": 18.0 * shape,
        "arm_fwd_r": 18.0 * shape,
    }


def _clap_pose(phase: float) -> dict[str, float]:
    """双臂抬到身前、肘部开合三次。"""
    amp = _envelope(phase, 0.18, 0.22)
    beat = (1.0 - math.cos(2.0 * math.pi * 3.0 * phase)) / 2.0
    return {
        "arm_swing_l": (108.0 + 14.0 * beat) * amp,
        "arm_swing_r": (108.0 + 14.0 * beat) * amp,
        "elbow_l": (55.0 + 50.0 * beat) * amp,
        "elbow_r": (55.0 + 50.0 * beat) * amp,
        "arm_fwd_l": 42.0 * amp,
        "arm_fwd_r": 42.0 * amp,
    }


#: 动作名 -> (姿态函数, 时长毫秒)。键必须与
#: ``model_actions.VRM_BUILTIN_MOTIONS`` 完全一致，否则菜单里会出现点了没反应
#: 的选项（自检里有断言守着）。
_VRM_MOTIONS: dict[str, tuple[Any, int]] = {
    "wave": (_wave_pose, 2200),
    "nod": (_nod_pose, 1500),
    "shake": (_shake_pose, 1800),
    "bow": (_bow_pose, 2100),
    "clap": (_clap_pose, 2200),
}


class VRMView(QOpenGLWidget, ModelViewInterface):
    """VRM 模型视图：3D 全身渲染 + 骨骼动画 + 表情。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 360)
        self._signals = ModelViewSignals()
        self._model = None          # VRMModel (parsed)
        self._rig: VRMRig | None = None
        self._renderer: VRMRenderer | None = None
        self._pending_path: str | None = None
        self._current_path: str | None = None
        self._gl_ready = False
        self._params: dict[str, ModelParam] = {}
        self._morph: dict[str, float] = {}
        self._drive: dict[str, float] = {}
        self._key_background = False
        self._expression: str | None = None

        # 动画计时
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

        # 内置动作：``_motion_drive`` 是当前帧动画要写的驱动键，播放期间由它
        # 压过动捕值（否则动作刚设上就被下一帧 set_drive_params 全量冲掉）。
        self._motion_pose: Any = None
        self._motion_drive: dict[str, float] = {}
        self._motion_duration = 0
        self._last_drive: dict[str, float] = {}
        self._motion_clock = QElapsedTimer()
        self._motion_timer = QTimer(self)
        self._motion_timer.timeout.connect(self._advance_motion)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(33)  # ~30 FPS

    def set_transparent_background(self, enabled: bool) -> None:
        """开启后使用透明背景，虚拟摄像头可直接输出带 Alpha 的画面。"""
        self._key_background = bool(enabled)
        self.update()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        self._motion_timer.stop()
        self._motion_pose = None
        self._motion_drive = {}
        super().hideEvent(event)

    # ---- ModelViewInterface ----
    def model_type(self) -> ModelType:
        return ModelType.VRM

    def get_supported_params(self) -> list[ModelParam]:
        return list(self._params.values())

    def load_model(self, path: str | Path) -> None:
        """加载 VRM 模型（解析 + 构建骨骼）。"""
        self._pending_path = str(path) if path else None
        if self._pending_path is None:
            self.clear_model()
            return
        try:
            model = build_model(self._pending_path)
            rig = VRMRig(model)
            rig.update()
            self._model = model
            self._rig = rig
            self._detect_params()
        except Exception as error:
            traceback.print_exc()
            self._model = None
            self._rig = None
            self._signals.model_loaded.emit(False)
            self._signals.model_error.emit(f"解析 VRM 模型失败: {error}")
            return

        # 换了骨架，上一模型正在播的动作必须丢掉，否则驱动键会写到新骨架上
        self._motion_timer.stop()
        self._motion_pose = None
        self._motion_drive = {}
        self._last_drive = {}
        self._expression = None
        if self._gl_ready:
            self._setup_renderer()
        self._signals.model_loaded.emit(True)
        self.update()

    def clear_model(self) -> None:
        self._pending_path = None
        self._current_path = None
        self._model = None
        self._rig = None
        self._morph.clear()
        self._drive.clear()
        if self._gl_ready and self._renderer is not None and self.isVisible():
            self.makeCurrent()
            try:
                self._renderer.release()
            except Exception:
                pass
            finally:
                self.doneCurrent()
        self._renderer = None
        self._expression = None
        self._params.clear()
        self._motion_timer.stop()
        self._motion_pose = None
        self._motion_drive = {}
        self._last_drive = {}
        self._signals.model_loaded.emit(False)
        self.update()

    def set_drive_params(
        self,
        angle_x: float = 0.0,
        angle_y: float = 0.0,
        angle_z: float = 0.0,
        body_angle_x: float = 0.0,
        body_angle_y: float = 0.0,
        arm_l: float = 0.0,
        arm_r: float = 0.0,
        eye_x: float = 0.0,
        eye_y: float = 0.0,
        eye_open_l: float = 1.0,
        eye_open_r: float = 1.0,
        mouth_open: float = 0.0,
        mouth_form: float = 0.0,
        **kwargs: Any,
    ) -> None:
        if self._rig is not None:
            # Forward every drive signal (including the full-body / hand keys that
            # arrive via **kwargs) to the rig; VRMRig.set_drive filters to known keys.
            all_drive = dict(
                angle_x=angle_x, angle_y=angle_y, angle_z=angle_z,
                body_angle_x=body_angle_x, body_angle_y=body_angle_y,
                arm_l=arm_l, arm_r=arm_r, eye_x=eye_x, eye_y=eye_y,
            )
            all_drive.update(kwargs)
            self._last_drive = all_drive
            self._rig.set_drive(**self._merged_drive(all_drive))
        self._drive = dict(
            eye_x=eye_x, eye_y=eye_y,
            eye_open_l=eye_open_l, eye_open_r=eye_open_r,
            mouth_open=mouth_open, mouth_form=mouth_form,
        )
        self._update_morph()
        self.update()

    # ---- 口型 / 表情（语音驱动口型与手势触发用） ----

    def set_mouth(self, mouth_open: float, mouth_form: float | None = None) -> None:
        """只更新嘴部形态键，不影响动捕正在驱动的骨骼。"""
        self._drive["mouth_open"] = max(0.0, min(1.0, float(mouth_open)))
        if mouth_form is not None:
            self._drive["mouth_form"] = max(-1.0, min(1.0, float(mouth_form)))
        self._update_morph()
        self.update()

    def expression_names(self) -> list[str]:
        model = self._model
        if model is None:
            return []
        return [str(name) for name in model.expressions]

    def available_actions(self) -> list[tuple[str, str]]:
        """内置动作 + 模型里真正能当表情用的 morph，供手势菜单动态生成。"""
        return model_actions.build_menu(model_actions.vrm_capabilities(self.expression_names()))

    def set_expression(self, name: str) -> bool:
        """按表情名设置表情。

        菜单给的名字是 ``model.expressions`` 里的真名，先用它精确匹配——
        旧版只认 smile/surprised/angry 三个语义名，模型的自定义表情
        （``Fcl_ALL_Joy``、``生气``）一个也匹配不上，看起来就是「选完没用」。
        精确匹配失败再退回语义候选表，兼容老配置里存下的 ``smile``。
        """
        model = self._model
        if model is None or not name:
            return False
        names = [str(item) for item in model.expressions]
        lowered = {item.lower(): item for item in names}
        resolved = lowered.get(str(name).lower())
        if resolved is None:
            for preset in _EXPRESSION_PRESETS.get(str(name).lower(), ()):
                if preset in model.expressions:
                    resolved = str(preset)
                    break
        if resolved is None:
            return False
        self._expression = resolved
        self._update_morph()
        self.update()
        return True

    def clear_expression(self) -> None:
        if self._expression is None:
            return
        self._expression = None
        self._update_morph()
        self.update()

    # ---- 内置动作 ----

    def play_motion(self, group: str = "wave") -> None:
        """播放内置动作（挥手 / 点头 / 摇头 / 鞠躬 / 鼓掌）。

        动作由定时器逐帧写驱动键，并在播放期间**压过动捕**（见
        ``_merged_drive``）。旧实现只 ``set_drive`` 一次就被下一帧动捕全量
        覆盖，一帧都看不到——这正是用户说的「选完功能模型根本没用」。
        """
        if self._rig is None:
            return
        spec = _VRM_MOTIONS.get(str(group)) or _VRM_MOTIONS.get(str(group).lower())
        if spec is None:
            return
        pose, duration = spec
        self._motion_pose = pose
        self._motion_duration = max(200, int(duration))
        self._motion_drive = {}
        self._motion_clock.restart()
        if not self._motion_timer.isActive():
            self._motion_timer.start(33)  # ~30 FPS
        self._advance_motion()

    def stop_motion(self) -> None:
        """立刻结束内置动作，把手脚交还给动捕。"""
        if self._motion_pose is None:
            return
        self._motion_timer.stop()
        self._motion_pose = None
        self._motion_drive = {}
        self._apply_rig_drive()

    def _advance_motion(self) -> None:
        pose = self._motion_pose
        if pose is None or self._motion_duration <= 0:
            self._motion_timer.stop()
            return
        phase = self._motion_clock.elapsed() / self._motion_duration
        if phase >= 1.0:
            self.stop_motion()
            return
        self._motion_drive = {k: float(v) for k, v in pose(phase).items()}
        self._apply_rig_drive()

    def _merged_drive(self, incoming: dict) -> dict:
        """把动画层叠在动捕值上。动作播放期间它说话，其余时间原样放行。"""
        if not self._motion_drive:
            return dict(incoming)
        merged = dict(incoming)
        merged.update(self._motion_drive)
        return merged

    def _apply_rig_drive(self) -> None:
        if self._rig is None:
            return
        self._rig.set_drive(**self._merged_drive(self._last_drive))
        self.update()

    # ---- internal ----
    def _update_morph(self) -> None:
        morph: dict[str, float] = {}
        model = self._model
        if model is None:
            self._morph = morph
            return
        # 手势触发的表情先占位，嘴型/眨眼在其之上叠加
        if self._expression and self._expression in model.expressions:
            morph[self._expression] = 1.0

        mouth = max(0.0, min(1.0, self._drive.get("mouth_open", 0.0)))
        if mouth > 0.01:
            form = float(self._drive.get("mouth_form", 0.0))
            if form > 0.15:
                candidates = _WIDE_MOUTH_PRESETS + _MOUTH_PRESETS
            elif form < -0.15:
                candidates = _ROUND_MOUTH_PRESETS + _MOUTH_PRESETS
            else:
                candidates = _MOUTH_PRESETS
            for preset in candidates:
                if preset in model.expressions:
                    morph[preset] = max(morph.get(preset, 0.0), mouth)
                    break
        blink_l = 1.0 - max(0.0, min(1.0, self._drive.get("eye_open_l", 1.0)))
        blink_r = 1.0 - max(0.0, min(1.0, self._drive.get("eye_open_r", 1.0)))
        blink = max(blink_l, blink_r)
        if blink > 0.01:
            for preset in _BLINK_PRESETS:
                if preset in model.expressions:
                    morph[preset] = blink
                    break
        # 无眼骨时用 look 表情驱动眼球
        if self._rig is not None and not self._rig.has_eye_bones():
            for preset, value in self._rig.expressions_for_look().items():
                if preset in model.expressions and abs(value) > 0.01:
                    morph[preset] = value
        self._morph = morph
        if self._renderer is not None:
            self._renderer.set_morph(morph)

    def _detect_params(self) -> None:
        self._params.clear()
        self._params["head_angle_x"] = ModelParam("head_angle_x", "头部左右旋转", "body", -30.0, 30.0, 0.0)
        self._params["head_angle_y"] = ModelParam("head_angle_y", "头部上下旋转", "body", -30.0, 30.0, 0.0)
        self._params["body_angle_x"] = ModelParam("body_angle_x", "身体左右倾斜", "body", -30.0, 30.0, 0.0)
        self._params["body_angle_y"] = ModelParam("body_angle_y", "身体前后倾斜", "body", -30.0, 30.0, 0.0)
        self._params["arm_l"] = ModelParam("arm_l", "左臂角度", "arm", -1.0, 1.0, 0.0)
        self._params["arm_r"] = ModelParam("arm_r", "右臂角度", "arm", -1.0, 1.0, 0.0)
        # 骨骼实际吃的是关节角（度）：上臂摆动 0 = 自然下垂，肘部 0 = 伸直
        self._params["arm_swing_l"] = ModelParam("arm_swing_l", "左上臂摆动", "arm", -45.0, 170.0, 0.0)
        self._params["arm_swing_r"] = ModelParam("arm_swing_r", "右上臂摆动", "arm", -45.0, 170.0, 0.0)
        self._params["elbow_l"] = ModelParam("elbow_l", "左肘弯曲", "arm", 0.0, 150.0, 0.0)
        self._params["elbow_r"] = ModelParam("elbow_r", "右肘弯曲", "arm", 0.0, 150.0, 0.0)
        # 整条手臂前倾（肩前屈）：手伸到躯干轮廓里时用它把手臂摆到身体前方，
        # 否则模型的小臂会停在躯干那一层深度上，看着就是插进肚子。
        self._params["arm_fwd_l"] = ModelParam("arm_fwd_l", "左臂前倾", "arm", 0.0, 80.0, 0.0)
        self._params["arm_fwd_r"] = ModelParam("arm_fwd_r", "右臂前倾", "arm", 0.0, 80.0, 0.0)
        self._params["eye_x"] = ModelParam("eye_x", "眼球左右", "eye", -1.0, 1.0, 0.0)
        self._params["eye_y"] = ModelParam("eye_y", "眼球上下", "eye", -1.0, 1.0, 0.0)
        self._params["eye_open_l"] = ModelParam("eye_open_l", "左眼开合", "eye", 0.0, 1.0, 1.0)
        self._params["eye_open_r"] = ModelParam("eye_open_r", "右眼开合", "eye", 0.0, 1.0, 1.0)
        self._params["mouth_open"] = ModelParam("mouth_open", "嘴巴开合", "mouth", 0.0, 1.0, 0.0)
        self._params["mouth_form"] = ModelParam("mouth_form", "嘴巴形状", "mouth", -1.0, 1.0, 0.0)
        self._params["arm_l_x"] = ModelParam("arm_l_x", "左臂侧摆", "arm", -1.0, 1.0, 0.0)
        self._params["arm_r_x"] = ModelParam("arm_r_x", "右臂侧摆", "arm", -1.0, 1.0, 0.0)
        self._params["hand_l"] = ModelParam("hand_l", "左手张开度", "hand", 0.0, 1.0, 0.0)
        self._params["hand_r"] = ModelParam("hand_r", "右手张开度", "hand", 0.0, 1.0, 0.0)

    def _setup_renderer(self) -> None:
        """在 GL 上下文中创建/更新渲染器资源。"""
        if self._model is None or self._rig is None:
            return
        self.makeCurrent()
        try:
            if self._renderer is not None:
                self._renderer.release()
            self._renderer = VRMRenderer()
            self._renderer.initialize(self._model, self._rig)
            self._renderer.set_morph(self._morph)
            self._renderer.resize(max(1, self.width()), max(1, self.height()))
            self._current_path = self._pending_path
        except Exception as error:
            traceback.print_exc()
            self._renderer = None
            self._signals.model_error.emit(f"初始化 VRM 渲染器失败: {error}")
        finally:
            self.doneCurrent()

    # ---- OpenGL lifecycle ----
    def initializeGL(self) -> None:
        self._gl_ready = True
        if self._model is not None and self._rig is not None:
            self._setup_renderer()

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, w, h)
        if self._renderer is not None:
            try:
                self._renderer.resize(w, h)
            except Exception:
                pass

    def paintGL(self) -> None:
        if self._renderer is not None and self._model is not None:
            try:
                if self._rig is not None:
                    self._rig.update()
                self._renderer.set_background(
                    *( (0.0, 0.0, 0.0, 0.0) if self._key_background
                       else (0.06, 0.08, 0.14, 1.0) )
                )
                self._renderer.render()
                return
            except Exception:
                traceback.print_exc()
                self._renderer = None
        # 渲染器不可用时的降级背景
        if self._key_background:
            glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            glClearColor(0.06, 0.08, 0.14, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    # ---- 信号访问 ----
    @property
    def model_loaded(self):
        return self._signals.model_loaded

    @property
    def model_error(self):
        return self._signals.model_error
