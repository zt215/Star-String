"""Real-time motion capture that drives a Live2D model.

Face landmarks (MediaPipe) drive head/eyes/mouth; a YOLO-pose ONNX model, if
present under ``client-python/models/``, adds body lean. All output is exposed
as Qt signals so it can safely reach the UI thread.
"""

from __future__ import annotations

import math
import os
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from app.services.gesture import classify as classify_gesture
from app.services.gesture import gesture_name
from app.services import pose_gesture


MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
YOLO_ONNX = MODELS_DIR / "yolo11n-pose.onnx"
YOLO_PT = MODELS_DIR / "yolo11n-pose.pt"

BODY_CONNECTIONS = [
    (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (5, 6), (11, 12),
]

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]

#: 五根手指的 (MCP, PIP, DIP) 关键点索引，顺序与 MediaPipe 的 21 点一致。
#: 大拇指用 (MCP, IP, TIP)，关节名不同但几何关系相同。
_FINGER_JOINTS = ((5, 6, 7), (9, 10, 11), (13, 14, 15), (17, 18, 19), (2, 3, 4))

#: 指节伸展比 -> 弯曲度的标定区间。手指从伸直折到握拳时，
#: 「指尖到指根距离 / 三节指骨总长」大约从 1.00 掉到 0.62，
#: 取 0.36 的跨度让满握拳刚好到 1.0。
_FINGER_SPAN = 0.36

#: PIP 关节角 -> 弯曲度的标定区间（度）。握拳时 PIP 夹角约 75°，
#: 伸直时约 180°。只做辅助判据，权重略低。
_FINGER_PIP_SPAN = 70.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _ascii_model_copy(source: Path) -> Path:
    """Copy a model to an ASCII-only path (mediapipe cannot open CJK paths)."""
    base = Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "star_string_assets"
    base.mkdir(parents=True, exist_ok=True)
    target = base / source.name
    if not target.exists():
        try:
            shutil.copy2(source, target)
        except OSError:
            return source
    return target


def _windows_camera_names() -> list[str]:
    """读取 Windows 上摄像头友好名称；失败时返回空列表。"""
    if os.name != "nt":
        return []
    try:
        import subprocess

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                "Get-CimInstance Win32_PnPEntity -Filter "
                "\"PNPClass='Camera' OR PNPClass='Image'\" "
                "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            timeout=8,
        )
    except Exception:
        return []
    text = (result.stdout or b"").decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


_CAMERA_CACHE: tuple[float, list[tuple[int, str]]] | None = None
_CAMERA_CACHE_TTL = 60.0


def list_camera_devices(force: bool = False, max_index: int = 6) -> list[tuple[int, str]]:
    """探测可用摄像头，返回 [(索引, 显示名)]，索引可直接给 cv2.VideoCapture。"""
    global _CAMERA_CACHE
    now = time.monotonic()
    if not force and _CAMERA_CACHE is not None and now - _CAMERA_CACHE[0] < _CAMERA_CACHE_TTL:
        return list(_CAMERA_CACHE[1])

    # 按索引探测所有能输出真实画面的摄像头，过滤掉静态占位图（如 Intel 标志）。
    found: list[int] = []
    for index in range(max_index):
        if _probe_camera(index):
            found.append(index)

    names = _windows_camera_names()
    devices: list[tuple[int, str]] = []
    for position, index in enumerate(found):
        label = (
            names[position]
            if position < len(names)
            else f"未命名摄像头（索引 {index}）"
        )
        devices.append((index, label))
    # 探测不到（驱动占用等）时退回系统设备名
    if not devices and names:
        for index, name in enumerate(names[:max_index]):
            devices.append((index, name))
    _CAMERA_CACHE = (now, devices)
    return list(devices)


def _probe_camera(index: int) -> bool:
    """判断该索引是否为真实摄像头（过滤静态合成占位图）。"""
    capture = None
    try:
        capture = cv2.VideoCapture(index)
        if capture is None or not capture.isOpened():
            return False
        frames: list[np.ndarray] = []
        for _ in range(3):
            ok, frame = capture.read()
            if ok and frame is not None:
                frames.append(frame.astype(np.float32))
            time.sleep(0.08)
        if len(frames) < 2:
            return False
        diff = max(
            float(np.mean(np.abs(frames[i] - frames[i - 1])))
            for i in range(1, len(frames))
        )
        white_ratio = float(np.mean(frames[-1] > 235))
        # 完全静止且大面积纯白 => Intel 等合成占位图，不是真实摄像头
        return not (diff < 0.1 and white_ratio > 0.5)
    except Exception:
        return False
    finally:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass


class MotionCapture(QObject):
    """Capture webcam frames, extract motion signals, and forward them."""

    frame_ready = Signal(QImage)
    drive_changed = Signal(dict)
    status_changed = Signal(str)
    #: 稳定识别到一个手势时发出：(side, gesture)，side 为 "l"/"r"，
    #: gesture 为空串表示该手的手势被解除。
    gesture_changed = Signal(str, str)
    #: 命中一个**自定义姿势手势**时发出：手势 id，空串表示解除。
    #:
    #: 和 ``gesture_changed`` 是两条独立链路：那条认的是手指形状（还得挑左右手），
    #: 这条认的是整条手臂摆出来的姿势，所以不分手、也不和手型互斥——用户拿
    #: 「张开手掌」录一个「双手举高」，两个信号都可能发出来，界面各按各的绑定
    #: 触发动作即可。
    pose_gesture_changed = Signal(str)
    #: 手部状态摘要，用于界面上的实时提示。
    hands_status_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._camera_index = 0
        self._mirror = False
        self._lr_mirror = False
        self._sensitivity = 1.0
        self._drive_enabled = True
        self._running = False
        self._thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None
        self._yolo_net = None
        self._yolo_input_size = 640
        self._use_face = True
        self._use_yolo = False
        self._params: dict = {}
        self._smooth: dict[str, float] = {}
        self._face_points: list[tuple[float, float]] = []
        self._face_detected = False
        self._body_points: list[tuple[float, float, float]] | None = None
        self._body_detected = False
        #: 归一化后的身体几何（肩/腕等，x、y 统一按画面高换算，保证夹角不失真）。
        #: YOLO 只每 ``_yolo_every`` 帧跑一次，中间几帧复用这份缓存，
        #: 好让手臂 IK 用「缓存的肩 + 当帧手部关键点」算出连续的角度。
        self._last_pose: dict | None = None
        #: YOLO 连续几次没检出人（``_yolo_every`` 帧才跑一次，所以单位是"次"）。
        self._pose_miss = 0
        #: 每侧手腕最近一次由手部关键点给出的位置 + 帧号；手部检测偶尔丢一两帧
        #: 时沿用它，避免在「手部模型」和「YOLO 腕点」两条轨迹之间来回跳。
        self._wrist_mem: dict[str, tuple[tuple[float, float], int] | None] = {"l": None, "r": None}
        #: 每侧最近一次的原始手臂解（摆角, 肘弯, 前倾）与「手已丢失多少帧」。
        self._arm_raw: dict[str, tuple[float, float, float] | None] = {"l": None, "r": None}
        self._arm_hold: dict[str, int] = {"l": 0, "r": 0}
        self._hand_points: list = []
        #: 手部关键点的**世界坐标**（米制三维，以手掌几何中心为原点）。手势判据
        #: 用它算指节夹角：手指正对摄像头时二维投影会把伸出的手指压扁、几根手指
        #: 还会重叠，只有三维夹角才认得出「伸的是哪一根」。
        self._hand_world: list = []
        self._hand_norm: list = []
        self._hand_detected = False
        self._hand_enabled = True
        self._gesture_enabled = True
        # 手部检测抽帧间隔：1 = 每帧都跑（响应最快），2 = 隔帧跑（更省算力）。
        # 抽帧会让手指动作滞后一两帧，所以默认拉满。
        self._hand_every = 1
        self._hand_labels: list[str] = []
        # 手势去抖：连续 N 帧识别为同一手势才认为成立，避免抖动误触发
        self._gesture_stable_frames = 3
        self._gesture_pending: dict[str, list] = {"l": ["", 0], "r": ["", 0]}
        self._gesture_active: dict[str, str] = {"l": "", "r": ""}
        #: **这一帧**每只手识别到的手型（``side -> 手势``，判不出就是空串）。
        #: 和 ``_gesture_active`` 是两回事：后者是去抖后的触发状态，判不出手势
        #: 的帧仍然保留上一次的值（那是给「别重复触发」用的），拿它当「当前
        #: 识别结果」显示会骗人。界面要用就用 :meth:`current_hand_shapes`。
        self._hand_shapes: dict[str, str] = {}
        #: **这一帧**每只手的逐指弯曲度是从哪种坐标算出来的（``world`` / ``pixels``）。
        #: ``pixels`` 说明 MediaPipe 这一帧没给世界坐标、退回了二维投影，那手指读数
        #: 可能被压扁（伸直的食指会读成弯曲）——「识别不对」排查时这是第一个要看
        #: 的分支点，所以留给 :meth:`current_hand_geometry` 给界面显示。
        self._hand_geometry_source: dict[str, str] = {}
        #: 自定义姿势手势的匹配器（去抖状态机在 pose_gesture.PoseTracker 里，
        #: 是纯逻辑，可以脱离 Qt 单测）。
        self._pose_tracker = pose_gesture.PoseTracker()
        #: 最近一帧的**原始**姿势快照，供「录制自定义手势」取用。
        #:
        #: 取原始值（还没乘用户调的灵敏度倍率 `_apply_drive_params`）有两个原因：
        #: 录制和匹配必须在同一把尺子上，否则用户改一次倍率、已录的姿势就全都
        #: 对不上了；而且姿势特征表 `pose_gesture.POSE_KEYS` 的量程是按原始角度
        #: 定的（上臂摆角 0~180°），倍率一乘（默认 1.0，但用户可改到 2.0 以上）
        #: 就会溢出量程、被夹平，姿势的差异被抹掉。
        self._pose_snapshot: dict = pose_gesture.capture(None)
        self._min_interval = 1.0 / 15.0
        self._last_process = 0.0
        self._frame_seq = 0
        self._yolo_every = 3
        self._last_body_x = 0.0
        self._last_body_y = 0.0
        self._processed_size = (480, 360)
        self._baseline = None
        self._baseline_sum = [0.0, 0.0, 0.0]
        self._baseline_count = 0
        self._baseline_frames = 12
        self._init_models()

    # ---- configuration ----

    def set_camera_index(self, index: int) -> None:
        self._camera_index = int(index)

    def set_mirror(self, enabled: bool) -> None:
        self._mirror = bool(enabled)

    def set_lr_mirror(self, enabled: bool) -> None:
        """Mirror left/right: swap side signals and flip lateral directions."""
        self._lr_mirror = bool(enabled)

    def set_sensitivity(self, value: float) -> None:
        self._sensitivity = max(0.1, min(3.0, float(value)))

    def set_drive_enabled(self, enabled: bool) -> None:
        self._drive_enabled = bool(enabled)

    def set_engine(self, engine: str) -> None:
        if engine == "face":
            self._use_face = True
            self._use_yolo = False
        elif engine == "yolo":
            self._use_face = False
            self._use_yolo = self._yolo_net is not None
        else:
            self._use_face = True
            self._use_yolo = self._yolo_net is not None

    def set_drive_params(self, params: dict) -> None:
        self._params = params or {}

    def set_hand_enabled(self, enabled: bool) -> None:
        """手部关键点检测总开关（关闭可省一份推理开销）。"""
        self._hand_enabled = bool(enabled)
        if not self._hand_enabled:
            self._hand_points = []
            self._hand_world = []
            self._hand_norm = []
            self._hand_labels = []
            self._hand_detected = False
            self._clear_gestures()

    def set_gesture_enabled(self, enabled: bool) -> None:
        """手势触发动作开关；关闭后仍会做手部驱动，只是不再上报手势。"""
        self._gesture_enabled = bool(enabled)
        if not self._gesture_enabled:
            self._clear_gestures()

    def set_hand_stride(self, stride: int) -> None:
        """手部检测抽帧间隔（1~4）。

        1 表示每帧都跑 HandLandmarker，手指/手腕最跟手；调大可以省 CPU，
        代价是手指动作会滞后若干帧。
        """
        self._hand_every = max(1, min(4, int(stride)))
        # 立刻重新检测一次，避免调整后要等下一轮到点才生效
        self._hand_detected = False

    def gesture_available(self) -> bool:
        return self._hand_landmarker is not None

    # ---- 自定义姿势手势 ----

    def _pose_tracker_or_new(self):
        """取（必要时创建）姿势匹配器。

        用 ``getattr`` 而不是直接读属性：自检里常用 ``MotionCapture.__new__``
        绕开 ``__init__``（不加载任何模型），这时属性不存在。
        """
        tracker = getattr(self, "_pose_tracker", None)
        if tracker is None:
            tracker = pose_gesture.PoseTracker()
            self._pose_tracker = tracker
        return tracker

    def set_pose_gestures(self, rows) -> None:
        """设置参与匹配的自定义手势（``[{"id","pose","tolerance"}, ...]``）。

        只有带非空 ``pose`` 的条目会参与——默认手势（握拳、比耶…）是手型判据
        认出来的，不走姿势匹配，所以传进来也不会生效。
        """
        tracker = self._pose_tracker_or_new()
        was_active = tracker.active
        tracker.set_templates(rows)
        if was_active and not tracker.active:
            # 刚触发的那条手势被删掉 / 换模型换走了：补一个解除事件，界面上的
            # 「当前手势」提示才不会一直挂着已经不存在的手势名。
            self.pose_gesture_changed.emit("")

    def current_pose(self) -> dict:
        """最近一帧的原始姿势特征（录制自定义手势时取它）。"""
        return dict(self._pose_snapshot)

    def hand_detected(self) -> bool:
        """当前帧有没有检测到手（没有就录不出有意义的姿势）。"""
        return bool(self._hand_detected)

    def current_hand_shapes(self) -> dict:
        """**这一帧**每只手识别到的手型（``{"l": "point", "r": ""}``）。

        给「录制自定义手势」的弹窗用：用户能看到这一帧到底认出了什么手型，
        对不上时一眼就知道是手指没被读到、还是判据认错了。

        别改读 ``_gesture_active``：那是去抖后的**触发状态**，判不出手势的帧
        它仍保留上一次的值，拿来当「当前识别结果」显示会骗人（表现为「我一直
        做单指，界面却一直显示握拳」）。
        """
        return dict(getattr(self, "_hand_shapes", {}) or {})

    def current_hand_geometry(self) -> dict:
        """**这一帧**每只手的逐指弯曲度用的是哪种坐标（``{"r": "world"}``）。

        只有两个值：``world``（米制三维，正常）和 ``pixels``（二维投影退化）。
        取到 ``pixels`` 时手指弯曲度可能整体失真——伸直的食指在正对镜头时会
        被压成「握起」——所以它和 :meth:`current_hand_shapes` 一起显示，排查
        「识别不对」时能立刻分清是**数据源坏了**还是**判据错了**。
        """
        return dict(getattr(self, "_hand_geometry_source", {}) or {})

    def is_running(self) -> bool:
        return self._running

    # ---- lifecycle ----

    def start(self) -> bool:
        if self._running:
            return True
        capture = cv2.VideoCapture(self._camera_index)
        if not capture.isOpened():
            self.status_changed.emit("无法打开摄像头，请检查索引或权限")
            return False
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._baseline = None
        self._baseline_sum = [0.0, 0.0, 0.0]
        self._baseline_count = 0
        self._capture = capture
        self._running = True
        self.status_changed.emit("动捕运行中")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        capture = self._capture
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
        self._capture = None
        self._smooth.clear()
        self._wrist_mem = {"l": None, "r": None}
        self._arm_raw = {"l": None, "r": None}
        self._arm_hold = {"l": 0, "r": 0}
        self._clear_gestures()
        self.status_changed.emit("动捕已停止")

    def _clear_gestures(self) -> None:
        """清空手势状态；对已经触发过手势的一侧补发解除通知。"""
        changed = False
        self._hand_shapes = {}
        self._hand_geometry_source = {}
        for side in ("l", "r"):
            self._gesture_pending[side] = ["", 0]
            if self._gesture_active.get(side):
                self._gesture_active[side] = ""
                changed = True
                self.gesture_changed.emit(side, "")
        if changed:
            self.hands_status_changed.emit("手部：未检测到")
        # 姿势手势同理：停止动捕 / 关掉手部检测后要把「正在触发的自定义手势」
        # 解除掉，否则再开动捕时它还挂着，界面以为用户一直保持那个姿势。
        tracker = getattr(self, "_pose_tracker", None)
        if tracker is not None:
            was_active = tracker.active
            tracker.reset()
            if was_active:
                self.pose_gesture_changed.emit("")

    def shutdown(self) -> None:
        self.stop()
        for attr in ("_face_landmarker", "_hand_landmarker"):
            landmarker = getattr(self, attr, None)
            setattr(self, attr, None)
            if landmarker is None:
                continue

            def _close(target=landmarker) -> None:
                try:
                    target.close()
                except Exception:
                    pass

            threading.Thread(target=_close, daemon=True).start()

    # ---- setup ----

    def _init_models(self) -> None:
        self._mp = None
        self._mp_vision = None
        self._face_landmarker = None
        self._hand_landmarker = None
        face_path = MODELS_DIR / "face_landmarker.task"
        hand_path = MODELS_DIR / "hand_landmarker.task"
        if face_path.exists() or hand_path.exists():
            try:
                import mediapipe as mp
                from mediapipe.tasks.python import BaseOptions
                from mediapipe.tasks.python import vision

                self._mp = mp
                self._mp_vision = vision
                if face_path.exists():
                    try:
                        model_path = _ascii_model_copy(face_path)
                        options = vision.FaceLandmarkerOptions(
                            base_options=BaseOptions(model_asset_path=str(model_path)),
                            running_mode=vision.RunningMode.VIDEO,
                            num_faces=1,
                            min_face_detection_confidence=0.5,
                            min_face_presence_confidence=0.5,
                            min_tracking_confidence=0.5,
                            output_face_blendshapes=True,
                            output_facial_transformation_matrixes=True,
                        )
                        self._face_landmarker = vision.FaceLandmarker.create_from_options(options)
                    except Exception:
                        self._face_landmarker = None
                if hand_path.exists():
                    try:
                        model_path = _ascii_model_copy(hand_path)
                        hand_options = vision.HandLandmarkerOptions(
                            base_options=BaseOptions(model_asset_path=str(model_path)),
                            running_mode=vision.RunningMode.VIDEO,
                            num_hands=2,
                            min_hand_detection_confidence=0.4,
                            min_tracking_confidence=0.4,
                        )
                        self._hand_landmarker = vision.HandLandmarker.create_from_options(hand_options)
                    except Exception:
                        self._hand_landmarker = None
            except Exception:
                self._face_landmarker = None
                self._hand_landmarker = None

        self._yolo_net = None
        if YOLO_ONNX.exists():
            try:
                model_path = _ascii_model_copy(YOLO_ONNX)
                self._yolo_net = cv2.dnn.readNetFromONNX(str(model_path))
            except Exception:
                self._yolo_net = None
        self._use_yolo = self._yolo_net is not None

    # ---- main loop ----

    def _loop(self) -> None:
        while self._running and self._capture is not None:
            ok, frame = self._capture.read()
            if not ok:
                self.status_changed.emit("摄像头读取失败")
                break
            if self._mirror:
                frame = cv2.flip(frame, 1)

            now = time.time()
            if now - self._last_process < self._min_interval:
                continue
            self._last_process = now
            self._frame_seq += 1
            frame = cv2.resize(frame, self._processed_size)

            drive = self._extract_drive(frame)
            preview = self._draw_overlay(frame)
            rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb.shape
            image = QImage(
                rgb.data,
                width,
                height,
                3 * width,
                QImage.Format.Format_RGB888,
            ).copy()
            self.frame_ready.emit(image)
            if self._drive_enabled:
                self.drive_changed.emit(drive)

        self._capture = None
        self._running = False

    def _extract_drive(self, frame: np.ndarray) -> dict:
        drive = {
            "angle_x": 0.0,
            "angle_y": 0.0,
            "angle_z": 0.0,
            "eye_open_l": 1.0,
            "eye_open_r": 1.0,
            "mouth_open": 0.0,
            "mouth_form": 0.0,
            "body_angle_x": 0.0,
            "body_angle_y": 0.0,
            "arm_l": 0.0,
            "arm_r": 0.0,
            "arm_l_x": 0.0,
            "arm_r_x": 0.0,
            "hand_l": 0.0,
            "hand_r": 0.0,
            "wrist_l": 0.0,
            "wrist_r": 0.0,
            "eye_x": 0.0,
            "eye_y": 0.0,
            # 手臂物理角（度）：上臂摆角相对「自然下垂」，肘部弯曲角 0=伸直，
            # 前倾角 = 整条手臂朝身体前方倾多少（单目看不到深度，手伸到躯干
            # 轮廓里时靠它把手臂摆到身体前面，不然小臂会插进肚子）。
            # 这几个才是 VRM 骨骼真正消费的量——`arm_l`/`arm_l_x` 是「手在
            # 画面里的归一化位置」，只够 Live2D 那种整体抬落用，给骨骼驱动
            # 会导致小臂永远伸直、上臂只有抬落两态。
            "arm_swing_l": 0.0,
            "arm_swing_r": 0.0,
            "elbow_l": 0.0,
            "elbow_r": 0.0,
            "arm_fwd_l": 0.0,
            "arm_fwd_r": 0.0,
        }
        # 手离开画面时这些键必须显式归零：下游（尤其是 VRM 骨骼）只更新
        # 传进来的键，缺键会保留上一帧的手指姿势，手放下后手指还弯着。
        for _side in ("l", "r"):
            for _fi in range(5):
                drive[f"finger_{_side}_{_fi}"] = 0.0

        if self._face_landmarker is not None and self._use_face:
            self._apply_face(frame, drive)

        self._apply_hands(frame, drive)
        if self._yolo_net is not None and self._use_yolo:
            if self._frame_seq % self._yolo_every == 0:
                body_x, body_y = self._extract_body(frame)
                self._last_body_x = body_x
                self._last_body_y = body_y
            drive["body_angle_x"] = self._last_body_x
            drive["body_angle_y"] = self._last_body_y
            # Hand tracking is more reliable for arm poses than body keypoints, so
            # only fall back to body-derived arms when no hand is detected.
            if not self._hand_detected:
                self._apply_arms(drive)
            # full-body: legs (+ arms as fallback) from the pose keypoints
            self._apply_body(drive)
        # 手臂 IK 放在最后：它要吃当帧的手部关键点（更准的腕位），
        # 也要吃 YOLO 缓存下来的肩位，两条链路都跑完了再算。
        self._apply_arms_ik(drive)
        # 自定义姿势手势要在**倍率之前**匹配：姿势特征的量程按原始角度定，
        # 乘上用户调的灵敏度倍率之后会溢出量程被夹平，差异就抹掉了。
        self._update_pose_gesture(drive)
        drive = self._apply_drive_params(drive)

        return drive

    # ---- 手臂逆运动学 ----
    #
    # 画面只给得到两个自由度，手「伸向镜头 / 收回胸前」这一维无法观测。
    # 所以这里只解画面平面内的姿态：肩-腕距离定肘弯、肩-肘方向定上臂朝向。
    # 好处是完全不需要肘部关键点（YOLO 的肘点质量很差），而且手靠向肩膀时
    # 肘自然就弯了，和真人一致。

    #: 上臂 + 前臂总长相对「肩到髋」长度的比例（人体均值约 0.33 / 0.288）。
    _ARM_TORSO_RATIO = 1.18
    #: 「肩到髋」相对「肩宽」的比例（0.288 / 0.245）。髋看不见时用它从肩宽反推
    #: 躯干长度——只露上半身时 YOLO 仍会外推出一个髋坐标，拿它量躯干能差近一倍。
    _HIP_OVER_SHOULDER = 1.18
    #: 髋点的置信度下限，低于它就不拿髋量躯干。
    _HIP_CONF = 0.30
    #: 肘点（YOLO 7/8 号）的置信度下限。低于它就不用它消歧 IK 的镜像解。
    _ELBOW_HINT_CONF = 0.50
    #: 手折在身前（收在肩内侧、离肩很近）时上臂的摆角：垂在身侧、略偏外。
    #: 见 `_solve_arm` 末尾的「折叠兜底」。
    _ARM_FOLDED_SWING = 8.0
    #: 肘位两条人体先验（「肘在肩下」/「更靠外」）互相切换时的过渡带宽，
    #: 单位 = 上臂长的倍数（见 `_solve_arm` 里那两处 `tanh`）。
    _ELBOW_BLEND_BAND = 0.5
    #: 躯干长度的合理区间（单位 = 画面高）。越界说明髋是外推出来的垃圾坐标。
    _TORSO_MIN = 0.12
    _TORSO_MAX = 1.60
    #: 完全没有身体关键点（只露手）时假设的手臂总长（单位 = 画面高）。
    #: 真人上臂+前臂约 0.33 倍身高；镜头通常取到半身（画面高约 0.65 倍身高），
    #: 臂展就落在 0.5 倍画面高附近。取大了等于判定「手永远够不着」，肘会一直
    #: 伸直；取小了手臂会缩在肩边。只有在手部关键点也量不出尺度时才用它。
    _DEFAULT_ARM_LEN = 0.50
    #: 「上臂 + 前臂」相对「腕 → 中指掌骨」长度的比例（0.332 / 0.055）。
    #: 手和手臂永远在同一个深度上，所以这个**比值**不受远近影响——手伸向镜头
    #: 时两者一起变大。这是没有身体关键点时唯一可靠的尺子。
    _ARM_OVER_PALM = 6.0
    #: 掌骨长度（单位 = 画面高）的合理区间。越界说明手部关键点不合格（分辨率
    #: 太低、手被画面裁掉一半、或者测试塞的假点），那就不要拿它当尺子。
    _PALM_MIN = 0.030
    _PALM_MAX = 0.300
    #: 肩腕距离的下限（相对手臂总长）= 肘弯的上限。低于这个距离两杆解出来的
    #: 肘已经折过头，前臂会插进躯干里——这就是用户说的「手臂贴在肚子上」。
    #: 0.42 对应肘弯约 130°（真人极限约 145°，但视觉上再折就穿模了）。
    _MIN_ARM_RATIO = 0.42
    #: 肘弯驱动的上限（度），与 `_MIN_ARM_RATIO` 同源，作为第二道保险。
    _MAX_ELBOW = 132.0
    #: 手落在躯干轮廓内时，整条手臂最多往前倾多少度。
    _MAX_ARM_TILT = 55.0
    #: 手部关键点丢失后，沿用上一次腕位的帧数（~15fps 下约 0.27s）。
    _WRIST_MEM_FRAMES = 4
    #: 手消失后保持上一帧手臂姿态的帧数，之后再慢慢归零（避免手臂一抽一抽）。
    _WRIST_HOLD_FRAMES = 18
    #: YOLO 连续多少「次」没检出人体才放弃缓存姿态（一次 = _yolo_every 帧）。
    #: 短暂漏检时继续用上一帧的肩位，比切到「只看得见手」的退化路径连续得多。
    _POSE_HOLD_RUNS = 4

    @classmethod
    def _pose_from_body(cls, body: list, width: float, height: float) -> dict | None:
        """把 YOLO 关键点转成归一化几何。

        坐标统一除以**画面高**（而不是分别除以宽、高），否则 x 和 y 尺度不同，
        由它们算出来的夹角会随画面宽高比整体失真。

        肩是唯一的硬性要求，而且**允许只露一侧**：镜头里只剩半边身子时，至少
        要能解出看得见的那条手臂。躯干长度优先用「肩→髋」；髋不可信（只露
        上半身时 YOLO 仍会外推出一个乱飞的髋坐标）就退回「肩宽 × 1.18」；实在
        没有参照才用假设臂长反推。三种来源都给出**同一量级**的尺度，手臂角度
        才不会变成尺度错误的产物。
        """
        if height <= 0 or width <= 0 or len(body) < 17:
            return None
        scale = 1.0 / float(height)
        names = {
            "sh_l": 5, "sh_r": 6, "el_l": 7, "el_r": 8,
            "wr_l": 9, "wr_r": 10, "hip_l": 11, "hip_r": 12,
        }
        pts: dict[str, tuple[float, float]] = {}
        conf: dict[str, float] = {}
        for name, index in names.items():
            x, y, c = body[index]
            pts[name] = (float(x) * scale, float(y) * scale)
            conf[name] = float(c)
        sides = [s for s in ("l", "r") if conf[f"sh_{s}"] >= 0.25]
        if not sides:
            return None

        def _gap(a: str, b: str) -> float:
            return math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])

        torso, torso_src = 0.0, "default"
        if min(conf["hip_l"], conf["hip_r"]) >= cls._HIP_CONF:
            torso = 0.5 * (_gap("sh_l", "hip_l") + _gap("sh_r", "hip_r"))
            if cls._TORSO_MIN <= torso <= cls._TORSO_MAX:
                torso_src = "hip"
            else:
                torso = 0.0
        if torso <= 0.0 and len(sides) == 2:
            shoulder_w = abs(pts["sh_l"][0] - pts["sh_r"][0])
            if shoulder_w > 0.05:
                torso = cls._HIP_OVER_SHOULDER * shoulder_w
                torso_src = "shoulder"
        if torso <= 0.0:
            # 只剩一侧肩、髋也不可信：没有真实的长度参照了，用假设臂长反推一个
            # 躯干长度，总比让整份 pose 作废、掉进「拿画面中心当肩」强。
            # `torso_src` 标记出来，好让下游再试着用手部掌骨换一把真尺子。
            torso = cls._DEFAULT_ARM_LEN / cls._ARM_TORSO_RATIO
            torso_src = "default"
        return {
            "pts": pts,
            "conf": conf,
            "torso": torso,
            "torso_src": torso_src,
            "aspect": float(width) / float(height),
            "sides": sides,
        }

    def _wrist_point(self, side: str, pose: dict) -> tuple[float, float] | None:
        """取该侧手腕的画面坐标（单位 = 画面高）。

        手部关键点（21 点）比 YOLO 的腕关键点准得多，所以优先用它；手部检测
        偶尔丢一两帧时先沿用它上一次的结果（YOLO 腕点系统性地偏一段距离，
        两者来回切换会让手臂在两条轨迹之间跳）；真丢了才退回 YOLO 腕点。
        """
        aspect = pose["aspect"]
        for index, label in enumerate(self._hand_labels):
            if label != side or index >= len(self._hand_norm):
                continue
            hand = self._hand_norm[index]
            if hand:
                point = (float(hand[0][0]) * aspect, float(hand[0][1]))
                self._wrist_mem[side] = (point, self._frame_seq)
                return point
        memory = self._wrist_mem.get(side)
        if memory is not None and self._frame_seq - memory[1] <= self._WRIST_MEM_FRAMES:
            return memory[0]
        if pose["conf"].get(f"wr_{side}", 0.0) >= 0.3:
            return pose["pts"][f"wr_{side}"]
        return None

    def _apply_arms_ik(self, drive: dict) -> None:
        # getattr 兜底：自检脚本用 __new__ 绕过 __init__，拿不到实例字段
        if getattr(self, "_arm_raw", None) is None:
            self._arm_raw = {"l": None, "r": None}
            self._wrist_mem = {"l": None, "r": None}
            self._arm_hold = {"l": 0, "r": 0}
        pose = getattr(self, "_last_pose", None)
        if pose is None:
            self._arms_from_screen(drive)
            return

        pts = pose["pts"]
        t = pose["torso"]
        base_len = self._ARM_TORSO_RATIO * t
        # 躯干长度是「假设值」时没有任何真实参照（只在同时「只露一侧肩」且
        # 「髋不可信」时出现）。记下来，循环里再试着用手部掌骨换一把真尺子。
        needs_palm = pose.get("torso_src") == "default"
        # 哪些侧的肩点是可信的。只露半边身子时另一侧的坐标是垃圾——既不能拿它
        # 定躯干中线，也不能拿它去解那条手臂。
        sides = pose.get("sides") or ["l", "r"]
        if len(sides) == 2:
            # 画面 x 增大的方向对「人自己的左边」是 +1 还是 -1。YOLO 的 5/6 号点
            # 按人体解剖分左右，所以这一比就直接给出画面的手性，不必去追问
            # 镜像开关是怎么设的。
            left_dx = -1.0 if pts["sh_l"][0] < pts["sh_r"][0] else 1.0
            # 躯干轮廓：左右肩中点 + 肩宽的一半
            center_x = 0.5 * (pts["sh_l"][0] + pts["sh_r"][0])
            half_w = max(0.5 * abs(pts["sh_l"][0] - pts["sh_r"][0]), 1e-3)
        else:
            # 只有一侧肩可见：手性只能按镜像开关推，躯干中线由「肩到中线的距离
            # = 肩宽的一半」反推（肩宽 ≈ 躯干 / 1.18）。
            left_dx = self._screen_left_dx()
            s0 = sides[0]
            outward0 = left_dx if s0 == "l" else -left_dx
            half_w = max(0.5 * t / self._HIP_OVER_SHOULDER, 1e-3)
            center_x = pts[f"sh_{s0}"][0] - outward0 * half_w

        for side in ("l", "r"):
            outward = left_dx if side == "l" else -left_dx
            wrist = self._wrist_point(side, pose)
            if wrist is None:
                # 手离开画面时**不要立刻归零**：那样每丢一次手，手臂就从当前
                # 姿势抽回自然下垂，再出现时又抽回去，看着就是「一抽一抽」。
                self._hold_arm(drive, side)
                continue
            if side not in sides:
                # 这一侧的肩在画面外。手腕还在画面里，就用画面中心当肩把它接住；
                # 不接的话这条手臂会僵在上一帧的姿势上。
                self._arm_from_screen(side, drive, wrist, outward)
                continue
            self._arm_hold[side] = 0
            arm_len = base_len
            if needs_palm:
                palm = self._hand_palm_scale(side)
                if palm is not None:
                    arm_len = _clamp(self._ARM_OVER_PALM * palm, 0.20, 1.20)
            sx, sy = pts[f"sh_{side}"]
            # 动捕本来就给了肘关节（7/8 号点）。它比手部关键点粗，所以只当
            # 「两解里选哪一支」的依据，且要求置信度够；到肩的距离还会在
            # `_solve_arm` 里再校验一遍（YOLO 只露上半身时会外推肘点）。
            elbow_hint = None
            if pose["conf"].get(f"el_{side}", 0.0) >= self._ELBOW_HINT_CONF:
                elbow_hint = pts[f"el_{side}"]
            swing, elbow, fwd = self._solve_arm(
                side, sx, sy, wrist[0], wrist[1],
                half=0.5 * arm_len, d_min=self._MIN_ARM_RATIO * arm_len,
                center_x=center_x, half_w=half_w, torso=t, outward=outward,
                elbow_hint=elbow_hint)
            self._write_arm(drive, side, swing, elbow, fwd)

    def _hold_arm(self, drive: dict, side: str) -> None:
        """这一侧没有可用数据时：先保持上一帧的解，超过窗口再慢慢松开。"""
        # getattr 兜底：自检脚本用 __new__ 绕过 __init__，拿不到实例字段
        if getattr(self, "_arm_hold", None) is None:
            self._arm_hold = {"l": 0, "r": 0}
        if getattr(self, "_arm_raw", None) is None:
            self._arm_raw = {"l": None, "r": None}
        hold = self._arm_hold.get(side, 0) + 1
        self._arm_hold[side] = hold
        raw = self._arm_raw.get(side)
        if raw is not None and hold <= self._WRIST_HOLD_FRAMES:
            self._write_arm(drive, side, *raw)
        else:
            self._write_arm(drive, side, 0.0, 0.0, 0.0)

    def _screen_left_dx(self) -> float:
        """画面 x 增大的方向对「人自己的左侧」是 +1 还是 -1。

        有 YOLO 肩点时直接比 5/6 号点的 x（见 `_apply_arms_ik`）；没有身体
        关键点时可比的只有镜像开关——未镜像时人面对镜头，自己的左手落在画面
        **右**侧，镜像（自拍视角）后落到左侧。
        """
        return -1.0 if getattr(self, "_mirror", False) else 1.0

    def _frame_aspect(self) -> float:
        """画面宽高比（宽 / 高）。以「画面高」为单位的 x 坐标都要乘它。"""
        size = getattr(self, "_processed_size", None)
        if size and len(size) == 2 and size[1]:
            return float(size[0]) / float(size[1])
        return 4.0 / 3.0

    def _screen_wrist(self, side: str) -> tuple[float, float] | None:
        """只从当帧手部关键点取腕位（单位 = 画面高），没有身体关键点时的输入。"""
        aspect = self._frame_aspect()
        for index, label in enumerate(getattr(self, "_hand_labels", [])):
            if label != side or index >= len(getattr(self, "_hand_norm", [])):
                continue
            hand = self._hand_norm[index]
            if hand:
                point = (float(hand[0][0]) * aspect, float(hand[0][1]))
                self._wrist_mem[side] = (point, self._frame_seq)
                return point
        # 手部检测偶尔丢一两帧：沿用它上一次的结果，别在两条轨迹之间跳。
        memory = self._wrist_mem.get(side)
        if memory is not None and self._frame_seq - memory[1] <= self._WRIST_MEM_FRAMES:
            return memory[0]
        return None

    def _hand_palm_scale(self, side: str) -> float | None:
        """从当帧手部关键点量「腕 → 中指掌骨」长度（单位 = 画面高）。

        没有身体关键点时手臂 IK 缺一把绝对尺子，而手部关键点自带一把：真人
        「上臂 + 前臂」约是掌骨的 6 倍。量出来的值先过一遍合理性区间，越界
        （手被画面裁掉、分辨率太低、测试塞的假点）就返回 None。
        """
        aspect = self._frame_aspect()
        for index, label in enumerate(getattr(self, "_hand_labels", [])):
            if label != side or index >= len(getattr(self, "_hand_norm", [])):
                continue
            hand = self._hand_norm[index]
            if not hand or len(hand) < 10:
                continue
            dx = (float(hand[9][0]) - float(hand[0][0])) * aspect
            dy = float(hand[9][1]) - float(hand[0][1])
            palm = math.hypot(dx, dy)
            if self._PALM_MIN <= palm <= self._PALM_MAX:
                return palm
        return None

    def _arm_from_screen(self, side: str, drive: dict,
                         wrist: tuple[float, float], outward: float) -> None:
        """没有可信肩位时的兜底：用画面中心当肩 + 假设臂长，照样走两杆 IK。"""
        arm_len = self._DEFAULT_ARM_LEN
        palm = self._hand_palm_scale(side)
        if palm is not None:
            arm_len = _clamp(self._ARM_OVER_PALM * palm, 0.20, 1.20)
        torso_est = arm_len / self._ARM_TORSO_RATIO
        aspect = self._frame_aspect()
        sx, sy = 0.5 * aspect, 0.5
        swing, elbow, fwd = self._solve_arm(
            side, sx, sy, wrist[0], wrist[1],
            half=0.5 * arm_len, d_min=self._MIN_ARM_RATIO * arm_len,
            center_x=sx, half_w=0.5 * torso_est / self._HIP_OVER_SHOULDER,
            torso=torso_est, outward=outward)
        self._arm_hold[side] = 0
        self._write_arm(drive, side, swing, elbow, fwd)

    @staticmethod
    def _limit_tilt(fwd: float, dx: float, dy: float, reach: float) -> float:
        """把前倾角压到「补完深度之后手臂还够得着」的范围内。

        前倾 φ 后，目标点变成 ``(dx, dy/cosφ, dy·tanφ)``，需要的手臂长度是
        ``√(dx² + dy²(1 + tan²φ)·… )``；把 ``(1+sin²φ)/cos²φ = 1 + 2tan²φ``
        代进去就能反解出上限：``tanφ_max = √((reach² - dx² - dy²) / (2·dy²))``。
        """
        d2 = dx * dx + dy * dy
        if dy * dy < 1e-12 or reach * reach <= d2:
            return 0.0
        limit = math.degrees(math.atan(math.sqrt((reach * reach - d2) / (2.0 * dy * dy))))
        return min(fwd, limit)

    def _solve_arm(self, side: str, sx: float, sy: float, wx: float, wy: float, *,
                   half: float, d_min: float, center_x: float, half_w: float,
                   torso: float, outward: float,
                   elbow_hint: tuple[float, float] | None = None
                   ) -> tuple[float, float, float]:
        """两杆 IK：由「肩 + 腕」解出（上臂摆角, 肘弯, 整臂前倾），全部是度。

        `elbow_hint` 是可选的**检测到的肘关节**（画面坐标，单位同 sx/sy）。
        两杆 IK 的镜像解靠人体先验挑不准，有真肘点时优先信它。
        """
        # ---- 深度补正：手落在躯干轮廓里 = 真实手臂一定在身体前方 ----
        # 单目画面给不出这一维，只能按「手越靠里、越往下，往前倾得越多」估一个
        # 前倾角，否则模型的小臂会停在躯干所在的那层深度上，看着就是插进肚子。
        lateral_in = 1.0 - _clamp(abs(wx - center_x) / half_w, 0.0, 1.0)
        vert_in = _clamp((wy - sy) / max(0.9 * torso, 1e-3), 0.0, 1.0)
        fwd = self._MAX_ARM_TILT * lateral_in * vert_in
        if fwd > 1.0:
            # 前倾会让画面上的竖直距离被反向放大（见下），补得越多需要的**三维**
            # 臂展越长；超出臂长时 IK 只能把距离夹到上限、手臂反而被拉直，所以
            # 先按可达性给前倾角封顶。
            fwd = self._limit_tilt(fwd, wx - sx, wy - sy, 0.95 * 2.0 * half)
        if fwd > 1.0:
            # 整条手臂前倾 fwd 之后，画面上竖直方向的投影会缩成 cos(fwd) 倍
            # （水平方向不变）。先把目标竖直距离反向放大，倾完正好落回用户
            # 手的位置——不然「补了深度」会顺带把手的高度也带偏。
            scale = max(math.cos(math.radians(fwd)), 0.55)
            wy = sy + (wy - sy) / scale

        # ---- 肘弯：肩腕距离越短，肘弯越大 ----
        dx, dy = wx - sx, wy - sy
        reach = math.hypot(dx, dy)
        d = _clamp(reach, d_min, 2.0 * half - 1e-4)
        cos_e = (half * half + half * half - d * d) / (2.0 * half * half)
        elbow = 180.0 - math.degrees(math.acos(_clamp(cos_e, -1.0, 1.0)))

        # ---- 肘位：两杆 IK 有两个解（互为镜像），要按解剖学挑一个 ----
        # 两个解是「肘在肩腕连线两侧」的镜像，二维看不出深度。挑选优先级：
        #
        # ① **检测到的肘关节最可靠。** 动捕本来就给出了胳膊（7/8 号肘点）的位置，
        #    先校验它到肩的距离是否接近上臂长（YOLO 在只露上半身时会外推肘点），
        #    通过就选离它更近的那个解。用数据消歧能避免"先验规则在临界姿态下
        #    选错、手臂整支翻过去"造成的突跳。
        # ② 没有可信肘点时退回人体先验：
        #    2a. **手不在肩上方时，肘一定在肩下方。** 人不可能把手放在胸腹前、
        #        还把肘抬到肩膀以上。这一条是必须的：手抬到胸前 / 肩高附近时，
        #        手臂弯得厉害（两解分得很开），而"更靠外"的那一支恰好就是把肘
        #        甩到肩**上方**的解——上臂于是朝上指，表现就是「手在下面、模型
        #        却在举手」。注意左右臂的外侧方向相反，所以这个 bug 只在其中
        #        一侧出现（实测右臂中招、左臂正常）。
        #    2b. 两个解都在肩的同一侧（上下）时，再比外侧程度：真人的肘在身体
        #        外侧；只按「更靠下」挑的话，手伸到身体中线附近会把肘放到身体
        #        另一侧，看着就是胳膊压在肚子上。两解明显打平时（手臂接近伸直，
        #        本来也重合）才退回「更靠下」。
        a = d * 0.5
        hh = math.sqrt(max(half * half - a * a, 0.0))
        # 单位方向用**未裁剪**的 reach 归一化：腕点落在肩上时 reach ≈ 0，若除以
        # 被撑到 d_min 的 d，除出来是零向量，肘位随之坍缩到肩点上，摆角被误判
        # 成 0——表现就是手收到肩前时手臂突然整条垂下。方向不可知时按「手在肩
        # 正下方」处理，那是最接近真实姿态的一支。
        if reach < 1e-6:
            ux, uy = 0.0, 1.0
        else:
            ux, uy = dx / reach, dy / reach
        nx, ny = -uy, ux
        ex1, ey1 = sx + a * ux + hh * nx, sy + a * uy + hh * ny
        ex2, ey2 = sx + a * ux - hh * nx, sy + a * uy - hh * ny

        use_hint = False
        if elbow_hint is not None:
            dh = math.hypot(elbow_hint[0] - sx, elbow_hint[1] - sy)
            # 肘点到肩的距离应当接近上臂长（= half）。偏太远说明那个点不是肘。
            if 0.5 * half <= dh <= 1.6 * half:
                use_hint = True
        if use_hint:
            d1 = (ex1 - elbow_hint[0]) ** 2 + (ey1 - elbow_hint[1]) ** 2
            d2 = (ex2 - elbow_hint[0]) ** 2 + (ey2 - elbow_hint[1]) ** 2
            if d2 < d1:
                ex1, ey1 = ex2, ey2
        else:
            # ---- 两条人体先验 + 连续插值 ----
            # 两支解是「肘在肩腕连线两侧」的镜像，二维看不出深度，只能靠先验挑：
            #
            #   A. **肘在肩下**（手在肩下方时）：人不可能把手放在胸腹前还把肘
            #      举过肩。这一条是必须的——手抬到胸前/肩高附近时手臂弯得厉害
            #      （两解分得很开），而「更靠外」那支恰好就是把肘甩到肩**上方**
            #      的解，上臂于是朝上指，表现就是「手在下面、模型却在举手」。
            #   B. **更靠外**（真人的肘在身体外侧）：手伸到身体中线附近时，
            #      只按「更靠下」挑会把肘放到身体另一侧，看着就是胳膊压在肚子上。
            #
            # 关键是不能硬切。两条先验互相切换的那个点，恰好是两支解的高度之一
            # 与肩同高的时候；切换点附近两支解能差几十甚至上百度，于是手在肩线
            # 旁边轻轻一动（实测手在外侧抬升时 y=188->184 一帧跳 43°，身体中线
            # 外侧抬升时跳 93°）上臂就整条翻过去。所以这里把两个「谁更大」的
            # 判断全部换成 tanh 软判据，再按「分居肩上下 × 手在肩下方」的连续
            # 权重把两支解插值起来：姿态分得越开（正常情况）越接近硬选，正好
            # 在临界点上平滑过渡。有可信肘点时不走这条路——真测到的位置就是
            # 连续数据，直接信它。
            out1 = (ex1 - sx) * outward
            out2 = (ex2 - sx) * outward
            band = self._ELBOW_BLEND_BAND * half

            # 「更靠外」的那支（out 更大）+「更靠下」的那支（ey 更大），
            # 都用同一个尺度软化，避免出现「差 3px 就换一支」的硬边界。
            pick_out = 0.5 * (1.0 + math.tanh((out2 - out1) / band))
            pick_low = 0.5 * (1.0 + math.tanh((ey2 - ey1) / band))
            outer_x = ex1 + (ex2 - ex1) * pick_out
            outer_y = ey1 + (ey2 - ey1) * pick_out
            lower_x = ex1 + (ex2 - ex1) * pick_low
            lower_y = ey1 + (ey2 - ey1) * pick_low

            # 两支解分居肩水平线两侧的程度（1 = 一支在肩上一支在肩下），
            # 以及「手没举过肩」的程度。两者同时成立才用先验 A。
            # 注意后者是**单侧**的：手比肩高几个像素根本不算举手——手越过身体
            # 中线伸到对侧肩前时，高度往往正好与肩齐平甚至高几个像素，那时仍然
            # 该按先验 A 把肘留在肩下。用双侧判据会把这一大类姿势误判成「举手」，
            # 让先验 B 挑出「肘抬到肩以上」的解，上臂于是朝上指（实测手臂指到
            # 267° 被钳成 165°），而且手上下几个像素就在两支解之间来回翻。
            t1 = math.tanh((ey1 - sy) / band)
            t2 = math.tanh((ey2 - sy) / band)
            straddle = 0.5 * (1.0 - t1 * t2)
            raised = _clamp(-dy / (0.6 * 2.0 * half), 0.0, 1.0)
            w = _clamp(straddle * (1.0 - raised), 0.0, 1.0)
            ex1 = lower_x * w + outer_x * (1.0 - w)
            ey1 = lower_y * w + outer_y * (1.0 - w)

        # ---- 手臂折得紧时，肘的「高度」不可辨，按连续量抹平 ----
        # 肘的竖直位置是 sy + a·uy + hh·ny，其中 uy 的符号 = 「手在肩上方还是
        # 下方**几个像素**」。手贴到肩旁边时这点差别在画面上根本分辨不出来，但
        # uy 一翻号，上臂就从 65° 跳到 99°——手在肩线上下轻微晃动，模型的手臂
        # 就跟着一下一下地弹。所以当手臂折得很紧（reach 小）时，按 |dy| 连续地
        # 把肘的高度过渡到「与肩同高」：那正好是两支镜像解的中点，上臂水平朝外，
        # 落在 65° 和 99° 正中间，跳变自然消失。有可信肘点时不抹——真测到的
        # 高度就是连续数据，不需要推。
        if not use_hint and reach < 0.6 * half:
            blend = _clamp(abs(dy) / (0.3 * half), 0.0, 1.0)
            if blend < 1.0:
                ey1 = sy + (ey1 - sy) * blend

        # ---- 上臂摆角：肩到肘的方向，换算成「相对自然下垂偏了多少度」----
        ex, ey = ex1 - sx, ey1 - sy
        length = math.hypot(ex, ey)
        if length < 1e-6:
            return 0.0, 0.0, fwd
        up_comp = -ey / length           # 画面 y 向下，取反才是「朝上」
        out_comp = (ex / length) * outward
        # 0° = 正上方，90° = 正外侧，180° = 正下方
        angle = math.degrees(math.atan2(out_comp, up_comp))
        swing = 180.0 - angle            # 下垂时 angle=180 -> swing=0
        # atan2 出来的是 [0°, 360°)，而「自然下垂、肘略偏内侧」会落在 340° 附近，
        # 下游 `_write_arm` 的钳位是 [-40, 165]——340° 会被直接夹成 165°（= 举手）。
        # 所以先把角度折回 (-180, 180]（340° -> -20°，语义完全一样）。
        if swing > 180.0:
            swing -= 360.0
        # 剩下唯一的歧义是「手举过头顶、继续朝身体内侧」：几何上上臂朝上
        # （up_comp > 0），但角度绕过了 ±180 边界，会解出 -174° 这种值。它等价于
        # +186°（就是举手），必须绕回来；否则会被钳成 -40°——上臂朝内下方，是
        # 人做不出来的姿势，而且 `_write_arm` 会一直贴着下限，手臂永久卡住。
        # 判据用**几何**而不是「离上一帧最近」：上臂朝下时的负角是真的内收，要
        # 保留。旧实现拿「上一帧已钳位」的平滑值当参考，一旦被钳过一次参考值就
        # 偏离 180° 以上，之后每个角度都被绕到错误的一支（实测手举过头顶解出
        # -210°，再钳成 -40°）。
        if swing < 0.0 and up_comp > 0.0:
            swing += 360.0
        # ---- 折叠兜底：手收在肩内侧时，平面解算没有意义 ----
        # 「手在肩**内侧**」且「手离肩很近」同时成立 = 真人把手臂折在身前（手放在
        # 胸口/下巴前）。这时肘其实折在身体侧后方、脱离了成像平面，而平面两杆 IK
        # 只会给出「上臂内收」这种解——既是人做不出的姿势，又会正好撞上
        # `_write_arm` 的下限被钳住，手臂就卡在那儿不动。所以按这两个条件把摆角
        # 平滑过渡到「垂在身侧、略偏外」。
        # 只按「离肩近」判不行：手举过头顶时离肩也近，但那条手臂是伸着的（举手），
        # 不能把它拉回来——加上「内侧」这个条件就分开了。
        arm_len = 2.0 * half
        # 「内侧」要按**身体轮廓**衡量（半肩宽），不能按臂长：手移到躯干中线
        # （离肩 = 半肩宽）就已经折在身前了。以前除以 0.35×臂长，手正好到中线
        # 时只算 0.8——剩下那 20% 仍带着「两支解各自的方向」，而两支解在跨越
        # 肩水平线的那一帧能差上百度的摆角，于是输出会「啪」地跳一下（实测
        # 3.8°->33.4°）。改用半肩宽后手到中线权重正好到 1，两支解都归到同一个
        # 「垂在身侧」的值，跳变自然消失；下限再兜一个 0.2×臂长，免得肩很窄时
        # 过早触发折叠。
        inner_scale = max(half_w, 0.20 * arm_len)
        inner = _clamp(-(dx * outward) / inner_scale, 0.0, 1.0)
        folded = _clamp((1.0 - reach / max(arm_len, 1e-6)) / 0.6, 0.0, 1.0)
        # 只有「手确实折进身体轮廓里」才拉回下垂。**不能**只因为「手离肩近」就
        # 拉回来：手抬到肩上方一点点、肘朝侧面抬平，同样离肩很近，但那条手臂是
        # 抬着的（上臂近水平），硬拉成下垂会在手划过肩水平线时挖出一个 V 形坑
        # （实测 65°->8°->115°）。真正退化的那一小块（reach→0）已经在上面
        # 「保持上一帧」里处理掉了，这里不必再重复兜底。
        weight = inner * folded
        if weight > 0.0:
            swing = swing * (1.0 - weight) + self._ARM_FOLDED_SWING * weight
        return swing, elbow, fwd

    def _write_arm(self, drive: dict, side: str,
                   swing: float, elbow: float, fwd: float) -> None:
        """把一侧手臂的三个角写进 drive（带自适应平滑）。"""
        if abs(swing) > 1e-6 or abs(elbow) > 1e-6 or abs(fwd) > 1e-6:
            self._arm_raw[side] = (swing, elbow, fwd)
        drive[f"arm_swing_{side}"] = self._smooth_value(
            f"aswing_{side}", _clamp(swing, -40.0, 165.0), react=6.0)
        drive[f"elbow_{side}"] = self._smooth_value(
            f"elbow_{side}", _clamp(elbow, 0.0, self._MAX_ELBOW), react=6.0)
        drive[f"arm_fwd_{side}"] = self._smooth_value(
            f"afwd_{side}", _clamp(fwd, 0.0, self._MAX_ARM_TILT), react=8.0)

    def _arms_from_screen(self, drive: dict) -> None:
        """完全没有身体关键点（只露手、YOLO 检不到人）时的退化路径。

        这里以前把 `drive["arm_l"]`（手在画面里的归一化位置）线性映射成摆角，
        而那个量在**手部关键点被检测到时恰恰不会被填充**——`_extract_drive` 只在
        `not self._hand_detected` 时才调 `_apply_arms`，所以手一进画面它就恒为
        初值 0.0，映射出 swing = (0 + 0.76) × 110 = 83.6°：两条手臂同时抬成
        「举手」，而且和手在画面哪个角落完全无关。

        现在改成拿画面中心当肩 + 一个假设臂长，**照样走两杆 IK**，输入换成当帧
        手部关键点里的腕位。没有尺度参照，绝对高度依旧不可信，但「手在下面 ->
        手臂垂下、手抬起来 -> 手臂抬起、手伸到一边 -> 手臂侧摆」这个关系是对的，
        肘弯也一并给得出来。
        """
        left_dx = self._screen_left_dx()
        for side in ("l", "r"):
            outward = left_dx if side == "l" else -left_dx
            wrist = self._screen_wrist(side)
            if wrist is None:
                # 这一侧连手都不在画面里：先保持上一帧的解，再慢慢松开。
                self._hold_arm(drive, side)
                continue
            self._arm_from_screen(side, drive, wrist, outward)

    def _apply_arms(self, drive: dict) -> None:
        if not self._body_points:
            return
        pts = self._body_points
        width = abs(pts[5][0] - pts[6][0])
        if width < 1e-3:
            return
        drive["arm_l"] = (pts[5][1] - pts[9][1]) / width
        drive["arm_r"] = (pts[6][1] - pts[10][1]) / width

    def _apply_body(self, drive: dict) -> None:
        """Map YOLO pose keypoints to full-body joint angles (degrees).

        Only drives motions that are actually visible/reliable in a 2D frontal
        pose (thigh side-swing, knee bend).  Forward hip-flexion can't be
        recovered from a single camera, so it stays at 0.  Every limb is
        confidence-gated: if its keypoints are missing or low-confidence the
        drive is zeroed so the avatar holds still instead of flailing.
        """
        if not self._body_points or not self._body_detected:
            return
        pts = self._body_points

        def P(i: int) -> np.ndarray:
            return np.array([pts[i][0], pts[i][1]], dtype=np.float32)

        def conf(i: int) -> float:
            return float(pts[i][2])

        lsh, rsh = P(5), P(6)
        lhip, rhip = P(11), P(12)
        torso = float(np.linalg.norm((lsh + rsh) / 2.0 - (lhip + rhip) / 2.0)) + 1e-6

        def angle3(a, b, c) -> float:
            v1 = a - b
            v2 = c - b
            cos = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6))
            return math.degrees(math.acos(max(-1.0, min(1.0, cos))))

        for side, (hip_i, knee_i, ankle_i) in (("l", (11, 13, 15)), ("r", (12, 14, 16))):
            drive[f"thigh_{side}"] = 0.0
            drive[f"knee_{side}"] = 0.0
            if min(conf(hip_i), conf(knee_i), conf(ankle_i)) < 0.3:
                continue  # limb not confidently detected -> hold still
            hip, knee, ankle = P(hip_i), P(knee_i), P(ankle_i)
            dk = knee - hip
            side_deg = math.degrees(math.atan2(dk[0], max(abs(dk[1]), 1e-3)))
            knee_deg = max(0.0, 180.0 - angle3(hip, knee, ankle))
            drive[f"thigh_{side}"] = -side_deg * 0.6
            drive[f"knee_{side}"] = knee_deg

    def _apply_drive_params(self, drive: dict) -> dict:
        for key in ("angle_x", "angle_y", "angle_z", "body_angle_x", "body_angle_y",
                    "arm_l", "arm_r", "arm_l_x", "arm_r_x",
                    "arm_swing_l", "arm_swing_r", "elbow_l", "elbow_r",
                    "arm_fwd_l", "arm_fwd_r",
                    "hand_l", "hand_r", "mouth_form",
                    "wrist_l", "wrist_r",
                    "eye_x", "eye_y",
                    "thigh_l", "thigh_r", "thigh_lift_l", "thigh_lift_r", "knee_l", "knee_r"):
            cfg = self._params.get(key, {})
            mult = float(cfg.get("mult", 1.0))
            value = drive.get(key, 0.0) * mult
            if cfg.get("invert", False):
                value = -value
            drive[key] = value
        for key in ("eye_open_l", "eye_open_r", "mouth_open"):
            cfg = self._params.get("eye", {})
            mult = float(cfg.get("mult", 1.0))
            drive[key] = _clamp(drive.get(key, 0.0) * mult, 0.0, 1.0)
        if self._lr_mirror:
            self._swap_lr(drive)
        return drive

    def _swap_lr(self, drive: dict) -> None:
        """Mirror left/right: swap side keys and flip lateral directions."""
        for a, b in (("arm_l", "arm_r"), ("arm_l_x", "arm_r_x"),
                     ("arm_swing_l", "arm_swing_r"), ("elbow_l", "elbow_r"),
                     ("arm_fwd_l", "arm_fwd_r"),
                     ("hand_l", "hand_r"), ("wrist_l", "wrist_r"),
                     ("thigh_l", "thigh_r"), ("thigh_lift_l", "thigh_lift_r"),
                     ("knee_l", "knee_r")):
            va, vb = drive.get(a, 0.0), drive.get(b, 0.0)
            drive[a], drive[b] = vb, va
        for i in range(5):
            kl, kr = f"finger_l_{i}", f"finger_r_{i}"
            vl, vr = drive.get(kl, 0.0), drive.get(kr, 0.0)
            drive[kl], drive[kr] = vr, vl
        # lateral direction flips (side swing / hand horizontal)
        for key in ("arm_l_x", "arm_r_x", "thigh_l", "thigh_r"):
            drive[key] = -drive.get(key, 0.0)

    def _apply_face(self, frame: np.ndarray, drive: dict) -> None:
        landmarker = self._face_landmarker
        if self._mp is None or landmarker is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            result = landmarker.detect_for_video(mp_image, int(time.time() * 1000))
        except Exception:
            return
        if not result.face_landmarks:
            self._face_points = []
            self._face_detected = False
            return

        height, width = frame.shape[:2]
        self._face_points = [
            (float(lm.x) * width, float(lm.y) * height)
            for lm in result.face_landmarks[0]
        ]
        self._face_detected = True
        landmarks = result.face_landmarks[0]
        self._apply_head_pose(result, drive)

        # Iris landmarks (468/473) let us drive the model's eyeballs from the
        # actual gaze direction. If the underlying model only returns the base
        # face mesh, this is a no-op and head pose remains the fallback.
        self._apply_eye_gaze(landmarks, drive)

        ear_l = self._ear_from(landmarks, 159, 145, 133, 33)
        ear_r = self._ear_from(landmarks, 386, 374, 362, 263)
        blink_l = blink_r = 0.0
        jaw = 0.0
        if result.face_blendshapes:
            scores = {c.category_name: c.score for c in result.face_blendshapes[0]}
            blink_l = scores.get("eyeBlinkLeft", 0.0)
            blink_r = scores.get("eyeBlinkRight", 0.0)
            jaw = scores.get("jawOpen", 0.0)
        eye_l = min(1.0 - blink_l, self._map_ear(ear_l))
        eye_r = min(1.0 - blink_r, self._map_ear(ear_r))
        # Eyes and mouth react instantly (no temporal smoothing) so blinks are visible.
        drive["eye_open_l"] = _clamp(eye_l, 0.0, 1.0)
        drive["eye_open_r"] = _clamp(eye_r, 0.0, 1.0)
        drive["mouth_open"] = _clamp(jaw, 0.0, 1.0)

    @staticmethod
    def _ear_from(landmarks, upper: int, lower: int, inner: int, outer: int) -> float:
        def point(index: int) -> np.ndarray:
            lm = landmarks[index]
            return np.array([lm.x, lm.y], dtype=np.float32)

        height = float(np.linalg.norm(point(upper) - point(lower)))
        width = float(np.linalg.norm(point(inner) - point(outer)))
        return height / max(width, 1e-6)

    @staticmethod
    def _map_ear(ear: float) -> float:
        return _clamp((ear - 0.16) / (0.28 - 0.16), 0.0, 1.0)

    @staticmethod
    def _apply_eye_gaze(landmarks, drive: dict) -> bool:
        """Use MediaPipe iris landmarks to move the model eyeballs.

        MediaPipe FaceLandmarker usually returns 478 landmarks; indices 468 and
        473 are the left/right iris centers.  The returned bool tells the caller
        whether gaze really was available (otherwise keep head-pose fallback).
        """
        if len(landmarks) < 474:
            return False
        try:
            def point(index: int) -> np.ndarray:
                lm = landmarks[index]
                return np.array([lm.x, lm.y], dtype=np.float32)

            left_iris = point(468)
            right_iris = point(473)

            # Eye centers are the average of the two corners and upper/lower lids.
            left_center = (point(33) + point(133) + point(159) + point(145)) / 4.0
            right_center = (point(362) + point(263) + point(386) + point(374)) / 4.0

            left_width = float(np.linalg.norm(point(33) - point(133)))
            left_height = float(np.linalg.norm(point(159) - point(145)))
            right_width = float(np.linalg.norm(point(362) - point(263)))
            right_height = float(np.linalg.norm(point(386) - point(374)))
            if min(left_width, right_width, left_height, right_height) < 1e-6:
                return False

            # Normalise iris offset by eye size, then scale to the Live2D eyeball
            # parameter range.  The y axis is flipped because image y grows downward.
            gaze_x = (
                (left_iris[0] - left_center[0]) / left_width
                + (right_iris[0] - right_center[0]) / right_width
            ) * 0.5
            gaze_y = (
                (left_iris[1] - left_center[1]) / left_height
                + (right_iris[1] - right_center[1]) / right_height
            ) * 0.5

            drive["eye_x"] = _clamp(gaze_x / 0.20, -1.0, 1.0) * 18.0
            drive["eye_y"] = _clamp(-gaze_y / 0.25, -1.0, 1.0) * 18.0
            return True
        except Exception:
            return False

    def _apply_hands(self, frame: np.ndarray, drive: dict) -> None:
        """手部驱动：检测按 :attr:`_hand_every` 抽帧，映射每帧都做。

        HandLandmarker 比人脸模型更贵，逐帧跑会拖低动捕帧率；抽帧检测后复用
        上一次的关键点，手臂/手指依然是连续运动的，只是响应略滞后。
        """
        if not self._hand_enabled or self._hand_landmarker is None or self._mp is None:
            if self._hand_detected or any(self._gesture_active.values()):
                self._hand_points = []
                self._hand_world = []
                self._hand_norm = []
                self._hand_labels = []
                self._hand_detected = False
                self._update_gestures([])
            return

        if self._frame_seq % self._hand_every == 0 or not self._hand_detected:
            self._detect_hands(frame)

        self._hands_to_drive(drive)

    def _detect_hands(self, frame: np.ndarray) -> None:
        """跑一次 HandLandmarker，刷新关键点、左右手标签与手势。"""
        self._hand_points = []
        self._hand_world = []
        self._hand_norm = []
        self._hand_labels = []
        self._hand_detected = False
        landmarker = self._hand_landmarker
        if landmarker is None or self._mp is None:
            self._update_gestures([])
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            result = landmarker.detect_for_video(mp_image, int(time.time() * 1000))
        except Exception:
            self._update_gestures([])
            return
        if not result.hand_landmarks:
            self._update_gestures([])
            return
        height, width = frame.shape[:2]
        world_hands = getattr(result, "hand_world_landmarks", None) or []
        for index, hand in enumerate(result.hand_landmarks):
            self._hand_norm.append([(float(lm.x), float(lm.y)) for lm in hand])
            self._hand_points.append(
                [(float(lm.x) * width, float(lm.y) * height) for lm in hand]
            )
            world = world_hands[index] if index < len(world_hands) else None
            if world and len(world) >= 21:
                self._hand_world.append([(float(lm.x), float(lm.y), float(lm.z)) for lm in world])
            else:
                self._hand_world.append(None)
            label = "Right"
            if result.handedness and index < len(result.handedness) and result.handedness[index]:
                label = result.handedness[index][0].category_name
            self._hand_labels.append("l" if label == "Left" else "r")
        self._hand_detected = True
        # 手势判据喂**像素点**（归一化坐标 x/y 尺度不同会让夹角失真），
        # 同时把世界坐标一起带上：手指正对摄像头时二维投影认不出伸的是哪根。
        self._update_gestures(self._hand_points)

    def _hands_to_drive(self, drive: dict) -> None:
        """把手部关键点映射成驱动值（手腕位置、手指弯曲度、手腕旋转）。

        位置的左右/上下用**归一化坐标**（和摄像头分辨率无关）；手指弯曲度用
        **世界坐标**（米制三维）优先，手腕旋转用**像素坐标**——三者的理由不同：

        * 归一化坐标把 x、y 按画面宽高分别缩放，夹角和长度比会整体失真，
          所以纯几何量不能用它；
        * 但纯几何量用**像素**也不够：手指正对摄像头时，伸直的食指在画面里被
          压成一小段，「指尖到指根距离 / 三指节总长」会从 1.00 掉到 0.6 以下，
          弯曲度算成「握起」——这会同时坏掉两件事：模型的食指跟着蜷起来，以及
          姿势特征把「单指」记成「握拳」（用户报的就是这个）。世界坐标是米制
          三维，长度比与朝向无关，所以有就用它，没有才退回像素；
        * 手腕 roll 要表达的是「手腕在**画面里**倾斜多少」，那本来就是屏幕空间
          的量，必须留在像素坐标上。
        """
        # 每帧整份重写：手离开画面后不该留着上一帧的「world」，那会让诊断显示成
        # 「数据源正常」，而其实这一帧根本没读到手指。
        self._hand_geometry_source = {}
        for index, norm_points in enumerate(self._hand_norm):
            if len(norm_points) < 21:
                continue
            if index < len(self._hand_points) and len(self._hand_points[index]) >= 21:
                points = self._hand_points[index]
            else:
                points = norm_points
            # getattr 兜底：自检里用 MotionCapture.__new__ 绕开 __init__ 时这个属性可能不存在
            world_list = getattr(self, "_hand_world", None) or []
            world = world_list[index] if index < len(world_list) else None
            if not isinstance(world, list) or len(world) < 21:
                world = None
            geometry = world if world is not None else points

            is_left = index < len(self._hand_labels) and self._hand_labels[index] == "l"
            side = "l" if is_left else "r"
            self._hand_geometry_source[side] = "world" if world is not None else "pixels"

            wx, wy = norm_points[0]
            nx = (wx - 0.5) * 2.0                                  # left/right, -1..1
            ny = (0.5 - wy) * 2.0                                  # up/down, +up
            base = "arm_l" if is_left else "arm_r"
            drive[base] = _clamp(ny, -1.0, 1.0)
            drive[base + "_x"] = _clamp(nx, -1.0, 1.0)

            # 逐指弯曲度（0=伸直，1=握起），顺序：食/中/无名/小/拇
            fingers = [self._finger_curl(geometry, a, b, c)
                       for (a, b, c) in _FINGER_JOINTS]
            for fi, curl in enumerate(fingers):
                drive[f"finger_{side}_{fi}"] = curl

            # 四指聚合弯曲度：Live2D 每条手臂通常只有一个「手指运动」参数，
            # 拿不到逐指信息时用这个值驱动。
            drive[f"hand_{side}"] = _clamp(sum(fingers[:4]) / 4.0, 0.0, 1.0)

            # 手腕旋转：用食指根部到小指根部的连线倾角估计
            drive[f"wrist_{side}"] = self._wrist_roll(points)

    @staticmethod
    def _wrist_roll(points) -> float:
        """由掌面横轴倾角估计手腕旋转，返回 -1..1。

        食指根（5）到小指根（17）的连线在手掌自然摊开时接近水平，
        手腕内外旋会让它倾斜。这里用像素坐标，保证 x、y 是同一尺度。
        """
        ax, ay = points[5]
        bx, by = points[17]
        dx, dy = bx - ax, by - ay
        if math.hypot(dx, dy) < 1e-6:
            return 0.0
        return _clamp(math.degrees(math.atan2(dy, dx)) / 45.0, -1.0, 1.0)

    def _update_gestures(self, hands: list) -> None:
        """按手维护手势去抖状态，稳定后对外发一次信号。

        去抖的意义：某一帧偶发误判不应该触发动作，所以要求同一手势连续
        :attr:`_gesture_stable_frames` 帧成立才上报；而手一旦离开画面则
        立即解除，避免手势卡在触发状态。
        """
        # 本次检测到的手：side -> 手势（None 表示手在画面上但手势不明确）
        present: dict[str, str | None] = {}
        for index, points in enumerate(hands or []):
            side = self._hand_labels[index] if index < len(self._hand_labels) else "r"
            if side not in present:
                world = self._hand_world[index] if index < len(self._hand_world) else None
                present[side] = classify_gesture(points, world)
        # 存下**这一帧**的识别结果给界面显示（判不出就是空串）。
        self._hand_shapes = {side: (value or "") for side, value in present.items()}

        summary: dict[str, str] = {}
        for side in ("l", "r"):
            if side not in present:
                self._gesture_pending[side] = ["", 0]
                if self._gesture_active.get(side):
                    self._gesture_active[side] = ""
                    self.gesture_changed.emit(side, "")
                continue

            gesture = present[side] if self._gesture_enabled else None
            summary[side] = gesture or ""
            if not gesture:
                # 手还在、只是没识别出手势：保留已触发状态，避免反复重触发
                self._gesture_pending[side] = ["", 0]
                continue

            pending = self._gesture_pending[side]
            if pending[0] == gesture:
                pending[1] += 1
            else:
                pending = [gesture, 1]
                self._gesture_pending[side] = pending
            if (
                pending[1] >= self._gesture_stable_frames
                and self._gesture_active.get(side) != gesture
            ):
                self._gesture_active[side] = gesture
                self.gesture_changed.emit(side, gesture)

        self.hands_status_changed.emit(self._hands_summary(summary))

    def _update_pose_gesture(self, drive: dict) -> None:
        """按姿势匹配自定义手势，命中去抖后对外发一次信号。

        姿势特征用的是**原始驱动值**（本方法在 ``_apply_drive_params`` 之前调用），
        理由见 ``__init__`` 里 ``_pose_snapshot`` 的注释。

        没有可用姿势时必须按「落空」处理，不能拿全 0 的姿势去比：手不在画面
        里的时候手臂角度全是初值 0，一比对就会命中那些「手放下来」的模板，
        动作就会莫名其妙地自己触发。
        """
        snapshot = pose_gesture.capture(drive)
        self._pose_snapshot = snapshot
        # 开关一律用 getattr 读（同 ``_pose_tracker_or_new``）：自检里常用
        # ``MotionCapture.__new__`` 绕开 ``__init__``，那时这些属性不存在；
        # 真实实例永远走 ``__init__``，取值与直接读属性完全一致。
        usable = (
            getattr(self, "_gesture_enabled", True)
            and getattr(self, "_hand_enabled", True)
            and getattr(self, "_hand_detected", False)
            and not pose_gesture.is_blank(snapshot)
        )
        event = self._pose_tracker_or_new().update(snapshot, usable)
        if event is not None:
            self.pose_gesture_changed.emit(event)

    def _hands_summary(self, present: dict) -> str:
        """给界面那一行「手部：…」用的文字。

        只报**这一帧**识别到的结果。以前判不出手势时会回退到 ``_gesture_active``
        （上一次触发的手势），于是「一直做单指、界面一直显示握拳」——用户会
        以为是识别错了，其实只是这一帧没判出来。现在这种情况明确写「手型未识别」。
        """
        if not present:
            return "手部：未检测到"
        parts = []
        for side, label in (("l", "左手"), ("r", "右手")):
            if side not in present:
                continue
            gesture = present[side]
            if gesture:
                parts.append(f"{label} {gesture_name(gesture)}")
            else:
                parts.append(f"{label} 已检测（手型未识别）")
        return "　".join(parts)

    @staticmethod
    def _finger_curl(points, mcp: int, pip: int, dip: int) -> float:
        """单指弯曲度（0 = 完全伸直，1 = 完全握起）。

        ``points`` 由调用方给：优先传**世界坐标**（米制三维），没有才传像素点
        ——手指正对摄像头时二维投影会把伸直的食指压短，比值判据会误判成握起，
        详见 :meth:`_hands_to_drive`。

        两个判据取较大值：

        * **指节伸展比**（主判据）——指尖到指根的实际距离，对比两节可见指骨
          的伸直长度。握拳时指尖折回掌心，这个比值掉得最快也最稳定，
          而且天然不受画面宽高比影响。
        * **PIP 关节夹角**（辅助判据）——兜住「指尖离指根很远但关节已经弯了」
          的退化情形，例如侧面看手。

        之前只用 ``(180 - 夹角) / 180``：真实握拳的 PIP 夹角约 60°~90°，
        换算出来只有 0.5 左右，所以怎么握都「握不紧」。换成伸展比之后
        满握拳能到 1.0，弯曲度才真正反映手指状态。
        """
        try:
            p_mcp = np.array(points[mcp], dtype=np.float64)
            p_pip = np.array(points[pip], dtype=np.float64)
            p_dip = np.array(points[dip], dtype=np.float64)
        except (IndexError, TypeError, ValueError):
            return 0.0

        chain = float(np.linalg.norm(p_pip - p_mcp)) + float(np.linalg.norm(p_dip - p_pip))
        if chain < 1e-6:
            return 0.0
        straight = float(np.linalg.norm(p_dip - p_mcp))
        length_curl = (chain - straight) / (chain * _FINGER_SPAN)

        v1 = p_mcp - p_pip
        v2 = p_dip - p_pip
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-6 or n2 < 1e-6:
            angle_curl = 0.0
        else:
            cosang = float(np.dot(v1, v2) / (n1 * n2))
            cosang = max(-1.0, min(1.0, cosang))
            angle = math.degrees(math.acos(cosang))
            angle_curl = (180.0 - angle) / _FINGER_PIP_SPAN

        return _clamp(max(length_curl, angle_curl * 0.95), 0.0, 1.0)

    def _apply_head_pose(self, result, drive: dict) -> None:
        matrixes = getattr(result, "facial_transformation_matrixes", None)
        if matrixes:
            try:
                rotation = np.array(matrixes[0], dtype=np.float32).reshape(4, 4)[:3, :3]
                sy = math.sqrt(float(rotation[0, 0] ** 2 + rotation[1, 0] ** 2))
                # yaw = rotation about Y (left/right) -> ParamAngleX
                yaw = math.degrees(math.atan2(-rotation[2, 0], sy))
                # pitch = rotation about X (up/down) -> ParamAngleY
                pitch = math.degrees(math.atan2(rotation[2, 1], rotation[2, 2]))
                # roll = rotation about Z (tilt) -> ParamAngleZ
                roll = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
                yaw, pitch, roll = self._neutralize(yaw, pitch, roll)
                drive["eye_x"] = yaw
                drive["eye_y"] = pitch
                drive["angle_x"] = self._smooth_value("ax", yaw * self._sensitivity)
                drive["angle_y"] = self._smooth_value("ay", pitch * self._sensitivity)
                drive["angle_z"] = self._smooth_value("az", roll)
                return
            except Exception:
                pass

        landmarks = result.face_landmarks[0]

        def point(index: int) -> np.ndarray:
            lm = landmarks[index]
            return np.array([lm.x, lm.y], dtype=np.float32)

        left_eye = point(33)
        right_eye = point(263)
        nose = point(1)
        center = (left_eye + right_eye) / 2.0
        width = float(np.linalg.norm(right_eye - left_eye))

        # Lateral nose offset -> left/right (ParamAngleX); vertical nose offset -> up/down (ParamAngleY).
        yaw = (nose[0] - center[0]) / max(width, 1e-6)
        pitch = (center[1] - nose[1]) / max(width, 1e-6)
        roll = math.degrees(math.atan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))
        yaw_v = yaw * 24.0 * self._sensitivity
        pitch_v = pitch * 24.0 * self._sensitivity
        yaw_v, pitch_v, roll_v = self._neutralize(yaw_v, pitch_v, -roll)
        drive["eye_x"] = yaw_v
        drive["eye_y"] = pitch_v

        drive["angle_x"] = self._smooth_value("ax", yaw_v)
        drive["angle_y"] = self._smooth_value("ay", pitch_v)
        drive["angle_z"] = self._smooth_value("az", roll_v)

    def _neutralize(self, yaw: float, pitch: float, roll: float) -> tuple[float, float, float]:
        if self._baseline_count < self._baseline_frames:
            self._baseline_sum[0] += yaw
            self._baseline_sum[1] += pitch
            self._baseline_sum[2] += roll
            self._baseline_count += 1
            if self._baseline_count >= self._baseline_frames:
                self._baseline = [value / self._baseline_frames for value in self._baseline_sum]
            return 0.0, 0.0, 0.0
        if self._baseline is not None:
            return yaw - self._baseline[0], pitch - self._baseline[1], roll - self._baseline[2]
        return yaw, pitch, roll

    def _extract_body(self, frame: np.ndarray) -> tuple[float, float]:
        self._body_points = None
        self._body_detected = False
        try:
            blob = cv2.dnn.blobFromImage(
                frame,
                1 / 255.0,
                (self._yolo_input_size, self._yolo_input_size),
                (0, 0, 0),
                swapRB=True,
                crop=False,
            )
            self._yolo_net.setInput(blob)
            output = self._yolo_net.forward()
            output = np.squeeze(output, 0)
            # Find the highest-confidence person.
            scores = output[4, :]
            idx = int(np.argmax(scores))
            if scores[idx] < 0.35:
                self._drop_pose()
                return 0.0, 0.0

            h, w = frame.shape[:2]
            scale = min(self._yolo_input_size / w, self._yolo_input_size / h)
            pad_x = (self._yolo_input_size - w * scale) / 2.0
            pad_y = (self._yolo_input_size - h * scale) / 2.0
            kp = output[5:, idx]  # 51 floats -> 17 keypoints (x,y,conf)
            body = []
            for i in range(17):
                x = (kp[i * 3] - pad_x) / scale
                y = (kp[i * 3 + 1] - pad_y) / scale
                conf = float(kp[i * 3 + 2])
                body.append((float(x), float(y), conf))
            self._body_points = body
            self._body_detected = True
            # 缓存归一化几何供手臂 IK 使用；YOLO 只每 _yolo_every 帧跑一次，
            # 中间几帧靠这份缓存 + 当帧手部关键点继续算角度。
            self._last_pose = self._pose_from_body(body, w, h)
            self._pose_miss = 0

            left_shoulder = kp[5 * 3 : 5 * 3 + 2]
            right_shoulder = kp[6 * 3 : 6 * 3 + 2]
            left_hip = kp[11 * 3 : 11 * 3 + 2]
            right_hip = kp[12 * 3 : 12 * 3 + 2]
            shoulder_mid = (left_shoulder + right_shoulder) / 2.0
            hip_mid = (left_hip + right_hip) / 2.0
            # Normalise by torso length so a standing person gives ~0 lean and a
            # genuine side-lean gives a bounded value. Forward/back (depth) lean
            # cannot be recovered from a 2D pose, so body_angle_y stays 0.
            torso = float(abs(float(hip_mid[1]) - float(shoulder_mid[1])))
            if torso < 1e-3:
                return 0.0, 0.0
            side = float(float(shoulder_mid[0]) - float(hip_mid[0])) / torso
            return self._smooth_value("bx", side * 45.0 * self._sensitivity), 0.0
        except Exception:
            self._drop_pose()
            return 0.0, 0.0

    def _drop_pose(self) -> None:
        """本「次」YOLO 没拿到人体：短暂漏检时保留上一帧的肩位。

        为什么不清空：`_last_pose` 一旦为 None，手臂就切到 `_arms_from_screen`
        那条完全不同的映射上（拿画面中心当肩、只看得见手的方向），两条路径
        解出来的角度差得很远，YOLO 一帧漏检就会让手臂跳一下。多留几次再清。
        """
        self._pose_miss = getattr(self, "_pose_miss", 0) + 1
        if self._pose_miss > self._POSE_HOLD_RUNS:
            self._last_pose = None

    def _smooth_value(self, key: str, value: float, alpha: float = 0.35,
                      react: float = 0.0) -> float:
        """指数低通。

        ``react`` > 0 时打开「自适应」：先看这一帧相对上一帧变了多少——
        变化小（多半是检测噪声）就慢跟，变化大（真实动作）就快跟。单目动捕
        的抖动几乎全从这里来（手部关键点逐帧漂几像素、YOLO 又每 3 帧才刷一
        次肩位），固定 alpha 只能二选一：要么抖，要么动作发飘、不跟手。
        单位与 ``value`` 相同（度），取「一秒内算真动作」的量级即可。
        """
        # getattr 兜底：自检脚本用 __new__ 绕过 __init__，拿不到实例字段
        smooth = getattr(self, "_smooth", None)
        if smooth is None:
            smooth = {}
            self._smooth = smooth
        previous = smooth.get(key, value)
        gain = alpha
        if react > 0.0:
            delta = abs(value - previous)
            speed = min(1.0, delta / react)
            gain = 0.10 + (0.70 - 0.10) * speed
        smoothed = previous * (1.0 - gain) + value * gain
        smooth[key] = smoothed
        return smoothed

    def _draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        if self._face_detected and self._face_points:
            for (x, y) in self._face_points:
                cv2.circle(frame, (int(x), int(y)), 1, (0, 255, 170), -1, cv2.LINE_AA)
        if self._body_detected and self._body_points:
            for a, b in BODY_CONNECTIONS:
                pa = self._body_points[a]
                pb = self._body_points[b]
                if pa[2] > 0.2 and pb[2] > 0.2:
                    cv2.line(
                        frame,
                        (int(pa[0]), int(pa[1])),
                        (int(pb[0]), int(pb[1])),
                        (0, 165, 255),
                        2,
                        cv2.LINE_AA,
                    )
            for (x, y, conf) in self._body_points:
                if conf > 0.15:
                    cv2.circle(frame, (int(x), int(y)), 3, (0, 165, 255), -1, cv2.LINE_AA)
        if self._hand_detected:
            for hand in self._hand_points:
                for a, b in HAND_CONNECTIONS:
                    pa = hand[a]
                    pb = hand[b]
                    cv2.line(
                        frame,
                        (int(pa[0]), int(pa[1])),
                        (int(pb[0]), int(pb[1])),
                        (255, 80, 200),
                        2,
                        cv2.LINE_AA,
                    )
                for (x, y) in hand:
                    cv2.circle(frame, (int(x), int(y)), 2, (255, 140, 220), -1, cv2.LINE_AA)
            # 在每只手旁边画五根手指的弯曲度柱（食/中/无名/小/拇），
            # 一眼就能看出「实际手型」和「识别结果」对不对得上。
            for hand in self._hand_points:
                if len(hand) < 21:
                    continue
                curls = [self._finger_curl(hand, a, b, c) for (a, b, c) in _FINGER_JOINTS]
                base_x = int(hand[0][0]) - 25
                base_y = int(hand[0][1]) + 16
                for i, curl in enumerate(curls):
                    x0 = base_x + i * 11
                    cv2.rectangle(frame, (x0, base_y), (x0 + 8, base_y + 22), (60, 60, 60), -1)
                    fill = int(22 * max(0.0, min(1.0, curl)))
                    if fill:
                        cv2.rectangle(
                            frame, (x0, base_y + 22 - fill), (x0 + 8, base_y + 22),
                            (80, 220, 255), -1,
                        )
        tag = f"FACE {'on' if self._face_detected else 'off'}  BODY {'on' if self._body_detected else 'off'}"
        if self._hand_enabled and self._hand_landmarker is not None:
            tag += f"  HAND {'on' if self._hand_detected else 'off'}"
        cv2.putText(
            frame,
            tag,
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 160),
            1,
            cv2.LINE_AA,
        )
        for side, name in (("l", "L"), ("r", "R")):
            gesture = self._gesture_active.get(side)
            if gesture:
                cv2.putText(
                    frame,
                    f"{name}:{gesture_name(gesture)}",
                    (10, 50 if side == "l" else 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 200, 80),
                    1,
                    cv2.LINE_AA,
                )
        return frame
