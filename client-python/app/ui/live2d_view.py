"""Live2D model viewer built on top of live2d-py (Cubism 3+)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from OpenGL.GL import glViewport
from PySide6.QtCore import QTimerEvent, Qt, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QMouseEvent

try:
    import live2d.v3 as live2d
    _LIVE2D_AVAILABLE = True
except Exception:
    live2d = None
    _LIVE2D_AVAILABLE = False

from app.ui.model_view_base import (
    ModelParam,
    ModelType,
    ModelViewInterface,
    ModelViewSignals,
)

_INIT_DONE = False


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


class Live2DView(QOpenGLWidget, ModelViewInterface):
    """Render a Cubism 3+ Live2D model inside a Qt widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(280, 320)

        self._model = None
        self._pending_path: str | None = None
        self._current_path: str | None = None
        self._gl_ready = False
        self._frames = 0
        self._fps = 60
        self._dragging = False
        self._param_ids: set[str] | None = None
        self._warned_missing: set[str] = set()
        self._signals = ModelViewSignals()
        self._params: dict[str, ModelParam] = {}

    # ---- ModelViewInterface 实现 ----

    def model_type(self) -> ModelType:
        return ModelType.LIVE2D

    def get_supported_params(self) -> list[ModelParam]:
        """获取模型支持的参数列表"""
        if self._param_ids is None and self._model is not None:
            try:
                self._param_ids = set(self._model.GetParamIds())
            except Exception:
                self._param_ids = set()

        self._params.clear()
        if self._param_ids is None:
            return []

        # 映射 Live2D 参数到标准参数格式
        param_map = {
            "ParamAngleX": ModelParam("angle_x", "头部左右旋转", "body", -30.0, 30.0, 0.0),
            "ParamAngleY": ModelParam("angle_y", "头部上下旋转", "body", -30.0, 30.0, 0.0),
            "ParamAngleZ": ModelParam("angle_z", "头部倾斜", "body", -30.0, 30.0, 0.0),
            "ParamBodyAngleX": ModelParam("body_angle_x", "身体左右倾斜", "body", -30.0, 30.0, 0.0),
            "ParamBodyAngleY": ModelParam("body_angle_y", "身体前后倾斜", "body", -30.0, 30.0, 0.0),
            "ParamArmLA": ModelParam("arm_l", "左臂角度", "arm", -1.0, 1.0, 0.0),
            "ParamArmRA": ModelParam("arm_r", "右臂角度", "arm", -1.0, 1.0, 0.0),
            "ParamArmLB": ModelParam("arm_l_b", "左臂角度B", "arm", -1.0, 1.0, 0.0),
            "ParamArmRB": ModelParam("arm_r_b", "右臂角度B", "arm", -1.0, 1.0, 0.0),
            "ParamEyeBallX": ModelParam("eye_x", "眼球左右", "eye", -1.0, 1.0, 0.0),
            "ParamEyeBallY": ModelParam("eye_y", "眼球上下", "eye", -1.0, 1.0, 0.0),
            "ParamEyeLOpen": ModelParam("eye_open_l", "左眼开合", "eye", 0.0, 1.0, 1.0),
            "ParamEyeROpen": ModelParam("eye_open_r", "右眼开合", "eye", 0.0, 1.0, 1.0),
            "ParamMouthOpenY": ModelParam("mouth_open", "嘴巴开合", "mouth", 0.0, 1.0, 0.0),
        }

        for param_id, param in param_map.items():
            if param_id in self._param_ids:
                self._params[param.id] = param

        return list(self._params.values())

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
        """设置动捕驱动参数（ModelViewInterface 接口方法）"""
        self.apply_drive(
            angle_x=angle_x,
            angle_y=angle_y,
            angle_z=angle_z,
            body_angle_x=body_angle_x,
            body_angle_y=body_angle_y,
            arm_l=arm_l,
            arm_r=arm_r,
            eye_x=eye_x,
            eye_y=eye_y,
            eye_open_l=eye_open_l,
            eye_open_r=eye_open_r,
            mouth_open=mouth_open,
        )

    # ---- public API ----

    def model_path(self) -> str | None:
        return self._pending_path

    def load_model(self, path: str | Path | None) -> None:
        """Queue a model to be loaded once the OpenGL context exists."""
        self._pending_path = str(path) if path else None
        if self._gl_ready:
            self._reload()
        self.update()

    def shutdown(self) -> None:
        """Release live2d GL resources bound to this view's context."""
        if not self._gl_ready or not _LIVE2D_AVAILABLE:
            return
        try:
            self.makeCurrent()
            if self._model is not None:
                try:
                    self._model.DestroyRenderer()
                except Exception:
                    pass
                self._model = None
            live2d.glRelease()
            self.doneCurrent()
        except Exception:
            pass
        self._gl_ready = False

    def clear_model(self) -> None:
        self._pending_path = None
        self._current_path = None
        self._warned_missing.clear()
        if self._model is not None:
            self.makeCurrent()
            try:
                self._model.DestroyRenderer()
                self._model = None
            except Exception:
                self._model = None
            finally:
                self.doneCurrent()
            self._param_ids = None
        self._params.clear()
        self.update()
        self._signals.model_loaded.emit(False)

    def play_motion(self, group: str = "Tap") -> None:
        if self._model is not None and hasattr(self._model, "StartRandomMotion"):
            try:
                self._model.StartRandomMotion(
                    group,
                    live2d.MotionPriority.FORCE,
                )
            except Exception:
                pass

    def stop_motions(self) -> None:
        if self._model is not None and hasattr(self._model, "StopAllMotions"):
            try:
                self._model.StopAllMotions()
            except Exception:
                pass

    def start_idle(self) -> None:
        if self._model is not None and hasattr(self._model, "StartRandomMotion"):
            try:
                self._model.StartRandomMotion("Idle", live2d.MotionPriority.IDLE)
            except Exception:
                pass

    def set_auto_features(self, blink: bool = True, breath: bool = True) -> None:
        if self._model is None:
            return
        try:
            self._model.SetAutoBlinkEnable(blink)
            self._model.SetAutoBreathEnable(breath)
        except Exception:
            pass

    def apply_drive(
        self,
        *,
        angle_x: float = 0.0,
        angle_y: float = 0.0,
        angle_z: float = 0.0,
        eye_open_l: float = 1.0,
        eye_open_r: float = 1.0,
        mouth_open: float = 0.0,
        body_angle_x: float = 0.0,
        body_angle_y: float = 0.0,
        arm_l: float = 0.0,
        arm_r: float = 0.0,
        eye_x: float = 0.0,
        eye_y: float = 0.0,
        **kwargs: Any,
    ) -> None:
        if self._model is None or not hasattr(self._model, "SetParameterValue"):
            return
        if self._param_ids is None:
            try:
                self._param_ids = set(self._model.GetParamIds())
            except Exception:
                self._param_ids = set()
        try:
            self._set_param("ParamAngleX", _clamp(angle_x, -30.0, 30.0))
            self._set_param("ParamAngleY", _clamp(angle_y, -30.0, 30.0))
            self._set_param("ParamAngleZ", _clamp(angle_z, -30.0, 30.0))
            self._set_param("ParamBodyAngleX", _clamp(body_angle_x, -30.0, 30.0))
            self._set_param("ParamBodyAngleY", _clamp(body_angle_y, -30.0, 30.0))
            self._set_param("ParamArmLA", _clamp(arm_l * 40.0, -30.0, 30.0))
            self._set_param("ParamArmRA", _clamp(arm_r * 40.0, -30.0, 30.0))
            self._set_param("ParamArmLB", _clamp(arm_l * 30.0, -30.0, 30.0))
            self._set_param("ParamArmRB", _clamp(arm_r * 30.0, -30.0, 30.0))
            self._set_param("ParamEyeBallX", _clamp(eye_x / 18.0, -1.0, 1.0))
            self._set_param("ParamEyeBallY", _clamp(eye_y / 18.0, -1.0, 1.0))
            self._set_param("ParamEyeLOpen", _clamp(eye_open_l, 0.0, 1.0))
            self._set_param("ParamEyeROpen", _clamp(eye_open_r, 0.0, 1.0))
            self._set_param("ParamMouthOpenY", _clamp(mouth_open, -1.0, 1.0))
        except Exception:
            pass

    def _set_param(self, param_id: str, value: float) -> None:
        if self._param_ids is None:
            try:
                self._param_ids = set(self._model.GetParamIds())
                print(f"[Live2D] 模型支持的参数: {sorted(self._param_ids)}")
            except Exception:
                self._param_ids = set()
        if self._param_ids is not None and param_id not in self._param_ids:
            # 每个不支持的参数只提示一次，避免动捕每帧重复打印刷屏
            if param_id not in self._warned_missing:
                self._warned_missing.add(param_id)
                print(f"[Live2D] 参数 {param_id} 不在模型支持的参数列表中，跳过设置")
            return
        try:
            self._model.SetParameterValue(param_id, value)
        except Exception as e:
            print(f"[Live2D] 设置参数 {param_id} 失败: {e}")

    def reset_drive(self) -> None:
        if self._model is not None and hasattr(self._model, "ResetParameters"):
            try:
                self._model.ResetParameters()
            except Exception:
                pass

    # ---- OpenGL lifecycle ----

    def initializeGL(self) -> None:
        global _INIT_DONE
        if not _LIVE2D_AVAILABLE:
            self._signals.model_error.emit("未安装 live2d-py，无法渲染虚拟形象")
            return
        if not _INIT_DONE:
            live2d.init()
            _INIT_DONE = True
        live2d.glInit()
        self._gl_ready = True
        self.startTimer(int(1000 / self._fps))
        self._reload()

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, w, h)
        if self._model is not None:
            try:
                self._model.Resize(w, h)
            except Exception:
                pass

    def paintGL(self) -> None:
        if not _LIVE2D_AVAILABLE:
            return
        # Clear to the panel navy so the view blends with cards (no black/transparent artefact).
        live2d.clearBuffer(0.04, 0.08, 0.16, 1.0)
        if self._model is not None:
            try:
                self._model.Update()
                self._model.Draw()
            except Exception:
                pass

    # ---- internal ----

    def _reload(self) -> None:
        self.makeCurrent()
        try:
            path = self._pending_path
            if not path or not Path(path).exists():
                if self._model is None:
                    self._signals.model_loaded.emit(False)
                else:
                    # Keep the current model visible if the requested one is missing.
                    self._pending_path = self._current_path
                    self._signals.model_error.emit(f"模型文件不存在：{path}")
                return

            new_model = None
            try:
                model = live2d.LAppModel()
                model.LoadModelJson(str(path))
                if hasattr(model, "SetAutoBreathEnable"):
                    model.SetAutoBreathEnable(True)
                if hasattr(model, "SetAutoBlinkEnable"):
                    model.SetAutoBlinkEnable(True)
                if hasattr(model, "StartRandomMotion"):
                    try:
                        model.StartRandomMotion("Idle", live2d.MotionPriority.IDLE)
                    except Exception:
                        pass
                model.Resize(max(1, self.width()), max(1, self.height()))
                new_model = model
            except Exception as error:
                self._signals.model_loaded.emit(False)
                self._signals.model_error.emit(str(error))
                return

            if self._model is not None:
                try:
                    self._model.DestroyRenderer()
                except Exception:
                    pass
            self._model = new_model
            self._param_ids = None
            self._warned_missing.clear()
            self._current_path = str(path)
            self._signals.model_loaded.emit(True)
        finally:
            self.doneCurrent()
        self.update()

    def timerEvent(self, event: QTimerEvent) -> None:
        if self.isVisible():
            self._frames += 1
            self.update()
        super().timerEvent(event)

    # ---- interaction ----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._dragging = True
        x, y = event.position().x(), event.position().y()
        if self._model is not None:
            try:
                self._model.Drag(x, y)
            except Exception:
                pass
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x, y = event.position().x(), event.position().y()
        if self._model is not None:
            try:
                self._model.Drag(x, y)
            except Exception:
                pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._dragging = False
            self.play_motion("Tap")
        super().mouseReleaseEvent(event)

    # ---- 信号访问 ----

    @property
    def model_loaded(self):
        return self._signals.model_loaded

    @property
    def model_error(self):
        return self._signals.model_error
