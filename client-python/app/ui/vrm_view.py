"""VRM 模型视图实现（完整可动皮套）。

使用 pygltflib + numpy 解析 VRM/GLB，构建 humanoid 骨骼，把动捕驱动参数
施加到骨骼/表情上，并在 CPU 完成蒙皮 + 形态键后上传到 GPU 渲染。
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import glViewport, glClear, glClearColor, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT

from app.core.vrm.model import build as build_model
from app.core.vrm.rig import VRMRig
from app.core.vrm.renderer import VRMRenderer

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

        # 动画计时
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

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
        self._params.clear()
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
            self._rig.set_drive(**all_drive)
        self._drive = dict(
            eye_x=eye_x, eye_y=eye_y,
            eye_open_l=eye_open_l, eye_open_r=eye_open_r,
            mouth_open=mouth_open,
        )
        self._update_morph()
        self.update()

    def play_motion(self, group: str = "Tap") -> None:
        # 简单挥手/摆头动作
        if self._rig is None:
            return
        self._rig.set_drive(arm_l=0.6, arm_r=-0.4)
        # 之后恢复由动捕参数决定，这里不强制复位
        self.update()

    # ---- internal ----
    def _update_morph(self) -> None:
        morph: dict[str, float] = {}
        model = self._model
        if model is None:
            self._morph = morph
            return
        mouth = max(0.0, min(1.0, self._drive.get("mouth_open", 0.0)))
        if mouth > 0.01:
            for preset in _MOUTH_PRESETS:
                if preset in model.expressions:
                    morph[preset] = mouth
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
        self._params["eye_x"] = ModelParam("eye_x", "眼球左右", "eye", -1.0, 1.0, 0.0)
        self._params["eye_y"] = ModelParam("eye_y", "眼球上下", "eye", -1.0, 1.0, 0.0)
        self._params["eye_open_l"] = ModelParam("eye_open_l", "左眼开合", "eye", 0.0, 1.0, 1.0)
        self._params["eye_open_r"] = ModelParam("eye_open_r", "右眼开合", "eye", 0.0, 1.0, 1.0)
        self._params["mouth_open"] = ModelParam("mouth_open", "嘴巴开合", "mouth", 0.0, 1.0, 0.0)

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
