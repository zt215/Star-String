"""VRM 模型视图实现。

使用 pyglet 进行 3D 渲染，pyvrmlib 加载 VRM 模型。
支持全身骨骼动画和表情。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import pyglet
    from pyglet.gl import *
    _PYGLET_AVAILABLE = True
except Exception:
    pyglet = None
    _PYGLET_AVAILABLE = False

try:
    import pyvrmlib
    _VRMLIB_AVAILABLE = True
except Exception:
    pyvrmlib = None
    _VRMLIB_AVAILABLE = False

from PySide6.QtCore import Qt, QTimer
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from app.ui.model_view_base import (
    ModelParam,
    ModelType,
    ModelViewInterface,
    ModelViewSignals,
)


class VRMView(QOpenGLWidget, ModelViewInterface):
    """VRM 模型视图，支持 3D 全身渲染和骨骼动画"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._signals = ModelViewSignals()
        self._model = None
        self._model_path: str | None = None
        self._gl_ready = False
        self._params: dict[str, ModelParam] = {}
        self._bone_transforms: dict[str, Any] = {}

    # ---- ModelViewInterface 实现 ----

    def model_type(self) -> ModelType:
        return ModelType.VRM

    def load_model(self, path: str | Path) -> None:
        """加载 VRM 模型"""
        if not _PYGLET_AVAILABLE or not _VRMLIB_AVAILABLE:
            self._signals.model_error.emit("VRM 依赖未安装，请安装 pyglet 和 pyvrmlib")
            return

        try:
            path_str = str(path)
            self._model_path = path_str
            self._model = pyvrmlib.load(path_str)
            self._detect_params()
            self._signals.model_loaded.emit(True)
            self.update()
        except Exception as e:
            self._signals.model_error.emit(f"加载 VRM 模型失败: {e}")

    def clear_model(self) -> None:
        """清除模型"""
        self._model = None
        self._model_path = None
        self._params.clear()
        self._bone_transforms.clear()
        self._signals.model_loaded.emit(False)
        self.update()

    def get_supported_params(self) -> list[ModelParam]:
        """获取模型支持的参数列表"""
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
        """设置动捕驱动参数，映射到 VRM 骨骼"""
        if self._model is None:
            return

        # 头部旋转
        self._set_bone_rotation("head", angle_x, angle_y, angle_z)

        # 身体旋转
        self._set_bone_rotation("spine", body_angle_x, body_angle_y, 0.0)
        self._set_bone_rotation("chest", body_angle_x * 0.5, body_angle_y * 0.5, 0.0)

        # 手臂旋转
        self._set_bone_rotation("leftUpperArm", arm_l * 30.0, 0.0, 0.0)
        self._set_bone_rotation("rightUpperArm", arm_r * 30.0, 0.0, 0.0)

        # 眼睛移动
        self._set_blend_shape("eyeLookUpLeft", eye_y)
        self._set_blend_shape("eyeLookUpRight", eye_y)
        self._set_blend_shape("eyeLookDownLeft", -eye_y)
        self._set_blend_shape("eyeLookDownRight", -eye_y)
        self._set_blend_shape("eyeLookInLeft", eye_x)
        self._set_blend_shape("eyeLookInRight", eye_x)
        self._set_blend_shape("eyeLookOutLeft", -eye_x)
        self._set_blend_shape("eyeLookOutRight", -eye_x)

        # 眼睛开合
        self._set_blend_shape("eyeBlinkLeft", 1.0 - eye_open_l)
        self._set_blend_shape("eyeBlinkRight", 1.0 - eye_open_r)

        # 嘴巴开合
        self._set_blend_shape("mouthOpen", mouth_open)

        self.update()

    def play_motion(self, group: str = "Tap") -> None:
        """播放动作（VRM 动画支持待实现）"""
        # VRM 动画播放需要更复杂的实现
        pass

    # ---- 内部方法 ----

    def _detect_params(self) -> None:
        """检测模型支持的参数"""
        self._params.clear()

        if self._model is None:
            return

        # 检测骨骼
        if hasattr(self._model, "humanoid_bones"):
            bones = self._model.humanoid_bones
            # 添加身体参数
            if "head" in bones:
                self._params["head_angle_x"] = ModelParam(
                    id="head_angle_x",
                    name="头部左右旋转",
                    category="body",
                    min_value=-30.0,
                    max_value=30.0,
                    default_value=0.0,
                )
                self._params["head_angle_y"] = ModelParam(
                    id="head_angle_y",
                    name="头部上下旋转",
                    category="body",
                    min_value=-30.0,
                    max_value=30.0,
                    default_value=0.0,
                )
            if "spine" in bones or "chest" in bones:
                self._params["body_angle_x"] = ModelParam(
                    id="body_angle_x",
                    name="身体左右倾斜",
                    category="body",
                    min_value=-30.0,
                    max_value=30.0,
                    default_value=0.0,
                )
                self._params["body_angle_y"] = ModelParam(
                    id="body_angle_y",
                    name="身体前后倾斜",
                    category="body",
                    min_value=-30.0,
                    max_value=30.0,
                    default_value=0.0,
                )
            if "leftUpperArm" in bones or "rightUpperArm" in bones:
                self._params["arm_l"] = ModelParam(
                    id="arm_l",
                    name="左臂角度",
                    category="arm",
                    min_value=-1.0,
                    max_value=1.0,
                    default_value=0.0,
                )
                self._params["arm_r"] = ModelParam(
                    id="arm_r",
                    name="右臂角度",
                    category="arm",
                    min_value=-1.0,
                    max_value=1.0,
                    default_value=0.0,
                )

        # 检测表情（BlendShapes）
        if hasattr(self._model, "blend_shapes"):
            shapes = self._model.blend_shapes
            # 添加眼睛参数
            if any("eye" in s.lower() for s in shapes):
                self._params["eye_x"] = ModelParam(
                    id="eye_x",
                    name="眼球左右",
                    category="eye",
                    min_value=-1.0,
                    max_value=1.0,
                    default_value=0.0,
                )
                self._params["eye_y"] = ModelParam(
                    id="eye_y",
                    name="眼球上下",
                    category="eye",
                    min_value=-1.0,
                    max_value=1.0,
                    default_value=0.0,
                )
                self._params["eye_open_l"] = ModelParam(
                    id="eye_open_l",
                    name="左眼开合",
                    category="eye",
                    min_value=0.0,
                    max_value=1.0,
                    default_value=1.0,
                )
                self._params["eye_open_r"] = ModelParam(
                    id="eye_open_r",
                    name="右眼开合",
                    category="eye",
                    min_value=0.0,
                    max_value=1.0,
                    default_value=1.0,
                )
            # 添加嘴巴参数
            if any("mouth" in s.lower() for s in shapes):
                self._params["mouth_open"] = ModelParam(
                    id="mouth_open",
                    name="嘴巴开合",
                    category="mouth",
                    min_value=0.0,
                    max_value=1.0,
                    default_value=0.0,
                )

    def _set_bone_rotation(self, bone_name: str, x: float, y: float, z: float) -> None:
        """设置骨骼旋转"""
        if self._model is None or not hasattr(self._model, "set_bone_rotation"):
            return
        try:
            self._model.set_bone_rotation(bone_name, x, y, z)
        except Exception:
            pass

    def _set_blend_shape(self, shape_name: str, value: float) -> None:
        """设置表情混合权重"""
        if self._model is None or not hasattr(self._model, "set_blend_shape"):
            return
        try:
            self._model.set_blend_shape(shape_name, value)
        except Exception:
            pass

    # ---- OpenGL 渲染 ----

    def initializeGL(self) -> None:
        """初始化 OpenGL"""
        self._gl_ready = True
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glClearColor(0.0, 0.0, 0.0, 0.0)

    def paintGL(self) -> None:
        """渲染场景"""
        if not self._gl_ready or self._model is None:
            return

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        # 相机设置
        gluLookAt(0, 1.5, 3, 0, 1.5, 0, 0, 1, 0)

        # 渲染模型
        if hasattr(self._model, "render"):
            self._model.render()

    def resizeGL(self, w: int, h: int) -> None:
        """窗口大小改变"""
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, w / h if h > 0 else 1, 0.1, 100.0)
        glMatrixMode(GL_MODELVIEW)

    # ---- 信号访问 ----

    @property
    def model_loaded(self):
        return self._signals.model_loaded

    @property
    def model_error(self):
        return self._signals.model_error