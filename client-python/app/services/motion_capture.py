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
        self._hand_points: list = []
        self._hand_detected = False
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
        self.status_changed.emit("动捕已停止")

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
            "body_angle_x": 0.0,
            "body_angle_y": 0.0,
            "arm_l": 0.0,
            "arm_r": 0.0,
            "eye_x": 0.0,
            "eye_y": 0.0,
        }

        if self._face_landmarker is not None and self._use_face:
            self._apply_face(frame, drive)

        if self._hand_landmarker is not None:
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
        drive = self._apply_drive_params(drive)

        return drive

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
                    "arm_l", "arm_r", "arm_l_x", "arm_r_x", "eye_x", "eye_y",
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
        self._hand_points = []
        self._hand_detected = False
        landmarker = self._hand_landmarker
        if landmarker is None or self._mp is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            result = landmarker.detect_for_video(mp_image, int(time.time() * 1000))
        except Exception:
            return
        if not result.hand_landmarks:
            return
        height, width = frame.shape[:2]
        center_y = height / 2.0
        center_x = width / 2.0
        for index, hand in enumerate(result.hand_landmarks):
            points = [(float(lm.x) * width, float(lm.y) * height) for lm in hand]
            self._hand_points.append(points)
            label = "Right"
            if result.handedness and index < len(result.handedness) and result.handedness[index]:
                label = result.handedness[index][0].category_name
            # wrist position (two DOF) and finger curls
            wx, wy = points[0]
            nx = (wx - center_x) / max(width / 2.0, 1e-6)          # left/right, -1..1
            ny = (center_y - wy) / max(height / 2.0, 1e-6)         # up/down, +up
            is_left = label == "Left"
            base = "arm_l" if is_left else "arm_r"
            drive[base] = _clamp(ny, -1.0, 1.0)
            drive[base + "_x"] = _clamp(nx, -1.0, 1.0)
            # per-finger curl (0..1) from the PIP-joint angle
            fingers = [self._finger_curl(points, a, b, c) for (a, b, c) in
                       [(5, 6, 7), (9, 10, 11), (13, 14, 15), (17, 18, 19), (2, 3, 4)]]
            key = "finger_l" if is_left else "finger_r"
            for fi, curl in enumerate(fingers):
                drive[f"{key}_{fi}"] = curl
        self._hand_detected = True

    @staticmethod
    def _finger_curl(points, a: int, b: int, c: int) -> float:
        """Curl (0=straight .. 1=bent) from the joint angle at point ``b``."""
        v1 = np.array([points[a][0] - points[b][0], points[a][1] - points[b][1]], dtype=np.float32)
        v2 = np.array([points[c][0] - points[b][0], points[c][1] - points[b][1]], dtype=np.float32)
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        cosang = float(np.dot(v1, v2) / (n1 * n2))
        cosang = max(-1.0, min(1.0, cosang))
        ang = math.degrees(math.acos(cosang))
        return max(0.0, min(1.0, (180.0 - ang) / 180.0))

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
                self._body_points = None
                self._body_detected = False
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
            return 0.0, 0.0

    def _smooth_value(self, key: str, value: float, alpha: float = 0.35) -> float:
        previous = self._smooth.get(key, value)
        smoothed = previous * (1 - alpha) + value * alpha
        self._smooth[key] = smoothed
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
        tag = f"FACE {'on' if self._face_detected else 'off'}  BODY {'on' if self._body_detected else 'off'}"
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
        return frame
