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

from app.services import model_actions
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
        self._key_background = False
        # 参数 id -> (最小值, 最大值, 默认值)，用于把 -1..1 / 0..1 的驱动值
        # 映射到模型自己声明的取值范围（不同模型的手臂参数范围并不统一）
        self._param_meta: dict[str, tuple[float, float, float]] = {}
        # 每条手臂上的参数绑定，按模型实际拥有的 id 推断
        self._hand_binding: dict[str, dict[str, str]] = {}
        self._expression: str | None = None
        # 从模型目录里补注册进来的表情 / 动作（VTS 系模型不往 model3.json
        # 登记，得靠 LoadExtraExpression / LoadExtraMotion 手动加）
        self._extra_expressions: list[str] = []
        self._extra_motions: list[str] = []

    def set_transparent_background(self, enabled: bool) -> None:
        """开启后使用透明背景，虚拟摄像头可直接输出带 Alpha 的画面。"""
        self._key_background = bool(enabled)
        self.update()

    # ---- ModelViewInterface 实现 ----

    def model_type(self) -> ModelType:
        return ModelType.LIVE2D

    def get_supported_params(self) -> list[ModelParam]:
        """获取模型支持的参数列表"""
        self._ensure_param_meta()
        self._ensure_hand_binding()

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
            "ParamArmLB": ModelParam("arm_l_x", "左臂侧摆", "arm", -1.0, 1.0, 0.0),
            "ParamArmRB": ModelParam("arm_r_x", "右臂侧摆", "arm", -1.0, 1.0, 0.0),
            "ParamEyeBallX": ModelParam("eye_x", "眼球左右", "eye", -1.0, 1.0, 0.0),
            "ParamEyeBallY": ModelParam("eye_y", "眼球上下", "eye", -1.0, 1.0, 0.0),
            "ParamEyeLOpen": ModelParam("eye_open_l", "左眼开合", "eye", 0.0, 1.0, 1.0),
            "ParamEyeROpen": ModelParam("eye_open_r", "右眼开合", "eye", 0.0, 1.0, 1.0),
            "ParamMouthOpenY": ModelParam("mouth_open", "嘴巴开合", "mouth", 0.0, 1.0, 0.0),
            "ParamMouthForm": ModelParam("mouth_form", "嘴巴形状", "mouth", -1.0, 1.0, 0.0),
        }
        # 手部参数各模型命名不统一，用推断出来的绑定反查是否可用
        left = self._hand_binding.get("l", {})
        right = self._hand_binding.get("r", {})
        for key, param_id, entry, side in (
            ("arm_l", left.get("arm_a"), left, "左"),
            ("arm_r", right.get("arm_a"), right, "右"),
        ):
            if param_id and param_id not in ("ParamArmLA", "ParamArmRA"):
                # 没有独立侧摆参数时，侧摆是在写入阶段并进这个参数的
                label = f"{side}臂角度" if entry.get("arm_b") else f"{side}臂（抬落+侧摆）"
                param_map[param_id] = ModelParam(key, label, "arm", -1.0, 1.0, 0.0)
        for key, entry, side in (
            ("arm_l_x", left, "左"),
            ("arm_r_x", right, "右"),
        ):
            param_id = entry.get("arm_b")
            if param_id:
                param_map[param_id] = ModelParam(key, f"{side}臂侧摆", "arm", -1.0, 1.0, 0.0)
        for key, param_id, side in (
            ("hand_l", left.get("fingers"), "左"),
            ("hand_r", right.get("fingers"), "右"),
        ):
            if param_id:
                param_map[param_id] = ModelParam(
                    key, f"{side}手手指（握拳）", "hand", 0.0, 1.0, 0.0
                )
        for key, entry, side in (("wrist_l", left, "左"), ("wrist_r", right, "右")):
            param_id = entry.get("wrist")
            if param_id:
                param_map[param_id] = ModelParam(key, f"{side}手腕旋转", "hand", -1.0, 1.0, 0.0)

        for param_id, param in param_map.items():
            if param_id in self._param_ids:
                self._params[param.id] = param

        return list(self._params.values())

    # ---- 参数元数据 / 手部绑定 ----

    def _ensure_param_meta(self) -> None:
        """缓存模型参数 id 及其取值范围（只做一次）。"""
        if self._param_meta or self._model is None:
            return
        try:
            count = int(self._model.GetParameterCount())
        except Exception:
            return
        for index in range(count):
            try:
                param = self._model.GetParameter(index)
            except Exception:
                continue
            param_id = getattr(param, "id", None)
            if not param_id:
                continue
            self._param_meta[param_id] = (
                float(getattr(param, "min", -1.0)),
                float(getattr(param, "max", 1.0)),
                float(getattr(param, "default", 0.0)),
            )
        if self._param_ids is None:
            self._param_ids = set(self._param_meta)

    def _ensure_hand_binding(self) -> None:
        """推断每条手臂上的参数绑定。

        两套命名都要兼容：Cubism 标准的 ``ParamArmL*/ParamHandL*``，以及
        很多中文模型用的 ``syHand1..5{L,R}``（上臂/小臂/手腕/手指/其他）。

        注意：syHand 系列每条手臂只有 5 个参数，也就是说**手臂只有上臂旋转
        一个自由度**，手指只有一个聚合参数，没有逐指参数。所以对这类模型：

        * 左右侧摆没有专用参数可写，只能在写入时并进上臂旋转；
        * 五指无法逐指还原，只能整体张开 / 握起。
        """
        self._ensure_param_meta()
        if self._hand_binding or self._param_ids is None:
            return
        ids = self._param_ids
        binding: dict[str, dict[str, str]] = {}
        for side, suffix in (("l", "L"), ("r", "R")):
            entry: dict[str, str] = {}
            if f"ParamArm{suffix}A" in ids:
                entry["arm_a"] = f"ParamArm{suffix}A"
            elif f"syHand1{suffix}" in ids:
                entry["arm_a"] = f"syHand1{suffix}"
            if f"ParamArm{suffix}B" in ids:
                entry["arm_b"] = f"ParamArm{suffix}B"
            if f"syHand2{suffix}" in ids:
                entry["forearm"] = f"syHand2{suffix}"
            # 手腕旋转：syHand3 是「手腕旋转」；Cubism 里对应 ParamHandLB/RB
            for candidate in (f"syHand3{suffix}", f"ParamHand{suffix}B"):
                if candidate in ids:
                    entry["wrist"] = candidate
                    break
            for candidate in (f"syHand4{suffix}", f"ParamHand{suffix}"):
                if candidate in ids:
                    entry["fingers"] = candidate
                    break
            if f"syHand5{suffix}" in ids:
                entry["extra"] = f"syHand5{suffix}"
            # 少数模型带逐指参数（ParamFinger*），有的话就能逐指还原
            per_finger: list[str] = []
            for name in ("Index", "Middle", "Ring", "Little", "Thumb"):
                for candidate in (
                    f"ParamFinger{name}{suffix}",
                    f"Param{name}Finger{suffix}",
                ):
                    if candidate in ids:
                        per_finger.append(candidate)
                        break
            if len(per_finger) >= 4:
                entry["per_finger"] = per_finger  # type: ignore[assignment]
            binding[side] = entry
        self._hand_binding = binding

    def _write_param(self, param_id: str | None, value: float, mode: str = "signed") -> None:
        """把归一化驱动值写进参数，必要时换算到模型声明的取值范围。

        换算一律**以参数的默认值为静息锚点**，这一点很关键：很多手部参数的
        范围是 -1..1 而默认值是 0，如果按「0 -> 最小值、1 -> 最大值」整段映射，
        手指在静息位就会被拉到最小值（过度伸直），握拳又只能走到量程的
        一小部分，表现就是「怎么握都握不紧」。

        ``mode="signed"``：``value`` 取 -1..1，0 表示静息（默认值），
        ±1 分别走到离默认值最近的那个极端；
        ``mode="unit"``：``value`` 取 0..1，0 表示静息，1 走向数值更大的一端；
        ``mode="unit_low"``：同上，但 1 走向数值更小的一端。
        """
        if not param_id:
            return
        meta = self._param_meta.get(param_id)
        if meta is None:
            self._set_param(param_id, value)
            return
        low, high, default = meta
        if mode == "signed":
            if value >= 0.0:
                target = default + (high - default) * min(value, 1.0)
            else:
                target = default - (default - low) * min(-value, 1.0)
        elif mode == "unit_low":
            target = default - (default - low) * _clamp(value, 0.0, 1.0)
        else:  # unit：走向数值更大的一端
            target = default + (high - default) * _clamp(value, 0.0, 1.0)
        self._set_param(param_id, target)

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
            **kwargs,
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
        self._extra_expressions = []
        self._extra_motions = []
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
        self._param_meta = {}
        self._hand_binding = {}
        self._expression = None
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
        mouth_form: float = 0.0,
        body_angle_x: float = 0.0,
        body_angle_y: float = 0.0,
        arm_l: float = 0.0,
        arm_r: float = 0.0,
        arm_l_x: float = 0.0,
        arm_r_x: float = 0.0,
        hand_l: float = 0.0,
        hand_r: float = 0.0,
        wrist_l: float = 0.0,
        wrist_r: float = 0.0,
        eye_x: float = 0.0,
        eye_y: float = 0.0,
        **kwargs: Any,
    ) -> None:
        if self._model is None or not hasattr(self._model, "SetParameterValue"):
            return
        self._ensure_param_meta()
        self._ensure_hand_binding()
        try:
            self._set_param("ParamAngleX", _clamp(angle_x, -30.0, 30.0))
            self._set_param("ParamAngleY", _clamp(angle_y, -30.0, 30.0))
            self._set_param("ParamAngleZ", _clamp(angle_z, -30.0, 30.0))
            self._set_param("ParamBodyAngleX", _clamp(body_angle_x, -30.0, 30.0))
            self._set_param("ParamBodyAngleY", _clamp(body_angle_y, -30.0, 30.0))
            self._set_param("ParamEyeBallX", _clamp(eye_x / 18.0, -1.0, 1.0))
            self._set_param("ParamEyeBallY", _clamp(eye_y / 18.0, -1.0, 1.0))
            self._set_param("ParamEyeLOpen", _clamp(eye_open_l, 0.0, 1.0))
            self._set_param("ParamEyeROpen", _clamp(eye_open_r, 0.0, 1.0))
            self._set_param("ParamMouthOpenY", _clamp(mouth_open, 0.0, 1.0))
            self._set_param("ParamMouthForm", _clamp(mouth_form, -1.0, 1.0))
            self._apply_arm("l", arm_l, arm_l_x, hand_l, wrist_l, kwargs)
            self._apply_arm("r", arm_r, arm_r_x, hand_r, wrist_r, kwargs)
        except Exception:
            pass

    def _apply_arm(
        self,
        side: str,
        arm_v: float,
        arm_h: float,
        hand_open: float,
        wrist: float,
        kwargs: dict,
    ) -> None:
        """把一条手臂的驱动值写进模型实际拥有的手部参数。

        手腕的位置提供两个自由度：``arm_v`` 是抬手高度，``arm_h`` 是左右侧摆；
        ``hand_open`` 是四指聚合弯曲度；``wrist`` 是掌心横轴倾角。

        只有 ``ParamArmL*/R*`` 这种 A/B 双参数的模型才有独立的侧摆通道。
        syHand 系列每条手臂只有「上臂旋转」一个参数，这时把侧摆按权重并进去，
        否则用户左右移动手掌时模型完全不动，看起来就是「手只能前后晃」。
        """
        entry = self._hand_binding.get(side) or {}
        vertical = _clamp(arm_v, -1.0, 1.0)
        lateral = _clamp(arm_h, -1.0, 1.0)
        wrist_v = _clamp(wrist, -1.0, 1.0)
        # 手指弯曲度：勾了「反转」时上层会把值取负，这里用符号决定写向哪一端。
        # 直接取绝对值再夹到 0..1 会让反转后的负值全被夹成 0，等于开关失效。
        raw_curl = float(hand_open)
        curl = _clamp(abs(raw_curl), 0.0, 1.0)
        curl_mode = "unit" if raw_curl >= 0.0 else "unit_low"

        if entry.get("arm_b"):
            self._write_param(entry.get("arm_a"), vertical, "signed")
            self._write_param(entry.get("arm_b"), lateral, "signed")
        else:
            # 单参数手臂：抬落为主，侧摆并进去，至少让左右也有反应
            self._write_param(entry.get("arm_a"), _clamp(vertical * 0.78 + lateral * 0.45, -1.0, 1.0), "signed")
        self._write_param(entry.get("forearm"), vertical * 0.7, "signed")
        self._write_param(entry.get("wrist"), wrist_v, "signed")

        # 手指：有逐指参数就逐指还原，否则退化成整体张开/握起
        per_finger = entry.get("per_finger")
        if isinstance(per_finger, list) and per_finger:
            for index, param_id in enumerate(per_finger):
                value = float(kwargs.get(f"finger_{side}_{index}", 0.0))
                if raw_curl < 0.0:
                    value = -value
                if value < 0.0:
                    self._write_param(param_id, _clamp(-value, 0.0, 1.0), "unit_low")
                else:
                    self._write_param(param_id, _clamp(value, 0.0, 1.0), "unit")
        else:
            self._write_param(entry.get("fingers"), curl, curl_mode)

        # syHand5「其他」语义不透明（常见是袖口/装饰），保持默认位不驱动，
        # 免得模型出现来路不明的抽动。有拇指信息的模型可在这里另行扩展。

    # ---- 口型 / 表情（语音驱动口型与手势触发用） ----

    def set_mouth(self, mouth_open: float, mouth_form: float | None = None) -> None:
        """只更新嘴部参数，不影响动捕正在写的头部/身体参数。"""
        if self._model is None:
            return
        self._ensure_param_meta()
        self._set_param("ParamMouthOpenY", _clamp(mouth_open, 0.0, 1.0))
        if mouth_form is not None:
            self._set_param("ParamMouthForm", _clamp(mouth_form, -1.0, 1.0))

    def expression_names(self) -> list[str]:
        """当前可设置的表情名：运行时查到的 + 加载时补注册成功的。"""
        return self._merge_names(self._runtime_expressions(), self._extra_expressions)

    def motion_groups(self) -> list[str]:
        """当前可播放的动作组名：运行时查到的 + 加载时补注册成功的。"""
        return self._merge_names(self._runtime_motion_groups(), self._extra_motions)

    @staticmethod
    def _merge_names(*sources) -> list[str]:
        names: list[str] = []
        for source in sources:
            for name in source:
                text = str(name).strip()
                if text and text not in names:
                    names.append(text)
        return names

    def _runtime_expressions(self) -> list[str]:
        if self._model is None or not hasattr(self._model, "GetExpressionIds"):
            return []
        try:
            return [str(name) for name in self._model.GetExpressionIds()]
        except Exception:
            return []

    def _runtime_motion_groups(self) -> list[str]:
        if self._model is None or not hasattr(self._model, "GetMotionGroups"):
            return []
        try:
            raw = self._model.GetMotionGroups()
            return [str(name) for name in (raw.keys() if hasattr(raw, "keys") else raw)]
        except Exception:
            return []

    def set_expression(self, name: str) -> bool:
        """设置表情；模型没有该表情时返回 ``False`` 由调用方决定降级方式。"""
        if self._model is None or not name:
            return False
        known = self.expression_names()
        if name not in known:
            # 菜单给的就是模型里的真名，大小写差异不该让表情设不上
            lowered = {str(item).lower(): str(item) for item in known}
            resolved = lowered.get(str(name).lower())
            if resolved is None:
                return False
            name = resolved
        try:
            self._model.SetExpression(name)
            self._expression = name
            return True
        except Exception:
            return False

    def clear_expression(self) -> None:
        self._expression = None
        if self._model is not None and hasattr(self._model, "ResetExpression"):
            try:
                self._model.ResetExpression()
            except Exception:
                pass

    def available_actions(self) -> list[tuple[str, str]]:
        """当前模型真正能执行的动作组与表情，供手势菜单动态生成。

        只报**确实注册成功**的资源：运行时接口查得到的，加上加载时补注册
        成功的（``_extra_*``）。不直接拿磁盘上的文件名充数——万一某个
        ``.exp3.json`` 注册失败，菜单里就会多出一条「点了没反应」的选项，
        那正是用户抱怨的问题。
        """
        caps = model_actions.ModelCapabilities(
            kind="live2d",
            motions=self.motion_groups(),
            expressions=self.expression_names(),
        )
        return model_actions.build_menu(caps)

    def _register_extra_assets(self) -> None:
        """把模型目录里散落的 .exp3.json / .motion3.json 补注册进模型。

        Cubism 只加载 model3.json 里登记过的资源，VTS 导出的模型把表情和动作
        单独摆着不登记，加载完就是「有身子没表情」。这里按文件名把它们补进去，
        手势菜单里选中的名字才对得上模型里真有的东西。

        必须在 ``makeCurrent()`` 的 GL 上下文里调用（由 ``_reload`` 保证）。
        注册失败的**不记进** ``_extra_*``，于是也不会出现在菜单里。
        """
        model = self._model
        path = self._current_path
        self._extra_expressions = []
        self._extra_motions = []
        if model is None or not path:
            return

        expressions, motions = model_actions.live2d_extra_assets(path)
        for name, file in expressions:
            try:
                model.LoadExtraExpression(name, file)
            except Exception:
                continue
            self._extra_expressions.append(name)
        for group, file in motions:
            try:
                loaded = model.LoadExtraMotion(group, file)
            except Exception:
                continue
            # 返回值是实际加载进来的动作条数，-1 表示出错；0 条等于没加进去
            if isinstance(loaded, int) and loaded <= 0:
                continue
            self._extra_motions.append(group)

        if self._extra_motions:
            # LAppModel 把 GetMotions() 的结果缓存了，不失效的话刚补进去的
            # 动作组在 GetMotionGroups() 里查不到。
            try:
                model._motions_cache = None
                model._sound_cache = {}
            except Exception:
                pass

    def _set_param(self, param_id: str, value: float) -> None:
        if self._param_ids is None:
            self._ensure_param_meta()
            if self._param_ids is None:
                try:
                    self._param_ids = set(self._model.GetParamIds())
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
        if self._key_background:
            live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        else:
            # Clear to the panel navy so the view blends with cards.
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
            self._param_meta = {}
            self._hand_binding = {}
            self._expression = None
            self._warned_missing.clear()
            self._current_path = str(path)
            self._ensure_param_meta()
            self._ensure_hand_binding()
            self._register_extra_assets()
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
