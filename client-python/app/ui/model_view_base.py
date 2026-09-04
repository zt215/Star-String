"""统一的模型视图接口基类。

定义 Live2D 和 VRM 模型的通用接口，包括：
- 模型加载/卸载
- 参数设置（头、眼、嘴、身体、手臂等）
- 参数列表查询
- 交互（拖拽、点击动作）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget


class ModelType(Enum):
    """模型类型枚举"""
    LIVE2D = "live2d"
    VRM = "vrm"


@dataclass
class ModelParam:
    """模型参数描述"""
    id: str
    name: str
    category: str  # face, body, arm, hand, eye, mouth
    min_value: float
    max_value: float
    default_value: float


class ModelViewInterface:
    """模型视图的统一接口"""

    def model_type(self) -> ModelType:
        """返回模型类型"""
        raise NotImplementedError

    def load_model(self, path: str | Path) -> None:
        """加载模型"""
        raise NotImplementedError

    def clear_model(self) -> None:
        """清除模型"""
        raise NotImplementedError

    def get_supported_params(self) -> list[ModelParam]:
        """获取模型支持的参数列表"""
        raise NotImplementedError

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
        """设置动捕驱动参数"""
        raise NotImplementedError

    def play_motion(self, group: str = "Tap") -> None:
        """播放动作"""
        raise NotImplementedError


class ModelViewSignals(QObject):
    """模型视图的信号定义"""

    model_loaded = Signal(bool)
    model_error = Signal(str)