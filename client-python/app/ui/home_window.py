from __future__ import annotations

import os
import threading
import time
import numpy as np
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionSpinBox,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.auth_service import LoginError, get_profile, update_profile
from app.services.cloud_service import (
    CloudApiError,
    check_server,
    delete_cloud_model,
    delete_cloud_preset,
    download_cloud_model,
    list_cloud_models,
    list_cloud_presets,
    upload_cloud_model,
    upload_cloud_preset,
)
from app.services.model_store import (
    LOCAL_PROFILE,
    LOCAL_PROFILE_DISPLAY,
    ModelStore,
)
from app.services.rvc_service import RVCEngine, _gram_sample_length
from app.services.motion_capture import MotionCapture, list_camera_devices
from app.services.gesture import DEFAULT_GESTURE_ACTIONS, GESTURE_NAMES, gesture_name
from app.services import model_actions
from app.services import pose_gesture
from app.services.settings_store import SettingsStore
from app.services.voice_lipsync import VoiceLipSync
from app.services.virtual_camera import (
    VIRTUAL_CAMERA_NAME,
    VirtualCameraError,
    VirtualCameraOutput,
    driver_files_present,
    install_driver,
)
from app.ui.dialogs import show_info, show_warning
from app.ui.live2d_view import Live2DView
from app.ui.vrm_view import VRMView


RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
LOGO_PATH = RESOURCES_DIR / "images" / "star_logo.png"
ICON_PATH = RESOURCES_DIR / "images" / "star_logo.ico"

NAV_ITEMS = ["首页", "视频动捕", "音频变声", "虚拟形象", "直播互动", "模型管理", "系统设置", "云端管理"]


STYLE_SHEET = """
QWidget {
    font-family: "Microsoft YaHei";
    color: #EAF6FF;
    font-size: 14px;
}

QPushButton {
    color: #EAF6FF;
}

QWidget#homeRoot {
    background-color: #0A1020;
}

QFrame#topBar {
    background-color: #0D1730;
    border-bottom: 1px solid #284064;
}

QFrame#sidebar {
    background-color: #0D1730;
    border-right: 1px solid #284064;
}

QLabel#brandTitle {
    font-size: 20px;
    font-weight: 600;
    color: #EAF6FF;
    letter-spacing: 2px;
}

QPushButton#linkButton {
    background: transparent;
    border: none;
    color: rgba(160, 210, 255, 210);
    font-size: 13px;
    padding: 6px;
}

QPushButton#linkButton:hover {
    color: #7EE7FF;
}

QPushButton#navButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #9DB5D8;
    font-size: 14px;
    padding: 12px 14px;
    text-align: left;
}

QPushButton#navButton:hover {
    color: #EAF6FF;
    background-color: rgba(255, 255, 255, 10);
}

QPushButton#navButton:checked {
    color: #7EE7FF;
    background-color: rgba(62, 145, 230, 26);
}

QLabel#pageTitle {
    font-size: 22px;
    font-weight: 600;
    color: #EAF6FF;
}

QFrame#panel {
    background-color: #111B33;
    border: 1px solid #284064;
    border-radius: 10px;
}

QLabel#panelTitle {
    font-size: 15px;
    font-weight: 600;
    color: #EAF6FF;
}

QLabel#panelBody {
    color: #9DB5D8;
    font-size: 13px;
}

QListWidget#modelList {
    background-color: #0A142A;
    border: 1px solid #284064;
    border-radius: 8px;
    color: #EAF6FF;
    padding: 6px;
}

QListWidget#modelList::item {
    padding: 10px;
}

QListWidget#modelList::item:selected {
    background-color: rgba(62, 145, 230, 70);
    color: #7EE7FF;
}

QTabWidget#modelTabs::pane {
    border: none;
}

QTabWidget#modelTabs QTabBar::tab {
    background: transparent;
    color: #9DB5D8;
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}

QTabWidget#modelTabs QTabBar::tab:selected {
    color: #7EE7FF;
    border-bottom: 2px solid #7EE7FF;
}

QTabWidget#modelTabs QTabBar::tab:hover {
    color: #EAF6FF;
}

QTabBar#avatarTypeTabs::tab {
    background: #111B33;
    color: #9DB5D8;
    padding: 7px 22px;
    border: 1px solid #284064;
    border-right: none;
}

QTabBar#avatarTypeTabs::tab:first {
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
}

QTabBar#avatarTypeTabs::tab:last {
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    border-right: 1px solid #284064;
}

QTabBar#avatarTypeTabs::tab:selected {
    color: #7EE7FF;
    background-color: rgba(62, 145, 230, 26);
    border-color: #4AA9E8;
}

QTabBar#avatarTypeTabs::tab:hover {
    color: #EAF6FF;
}

QPushButton#actionButton {
    background-color: #1E6FD9;
    color: #FFFFFF;
    border: 1px solid #3580E8;
    border-radius: 8px;
    padding: 6px 18px;
    min-height: 32px;
    min-width: 96px;
    font-weight: 600;
}

QPushButton#actionButton:hover {
    background-color: #2F80E6;
}

QPushButton#actionButton:pressed {
    background-color: #1A60C2;
}

QProgressBar#volumeBar {
    background-color: #0A142A;
    border: 1px solid #284064;
    border-radius: 4px;
    text-align: center;
}

QProgressBar#volumeBar::chunk {
    background-color: #4AA9E8;
    border-radius: 3px;
}

QFrame#stagePanel {
    background-color: #0A142A;
    border: 1px solid #284064;
    border-radius: 10px;
}

QLabel#sectionTitle {
    font-size: 14px;
    font-weight: 600;
    color: #EAF6FF;
}

QLabel#infoValue {
    color: #C9DCF5;
    font-size: 13px;
}

QLabel#hintText {
    color: #A9C3E2;
    font-size: 12px;
}

QLineEdit#inputBox {
    background-color: #0A142A;
    border: 1px solid #284064;
    border-radius: 8px;
    color: #EAF6FF;
    padding: 8px 12px;
    selection-background-color: #2F80E6;
}

QLineEdit#inputBox:focus {
    border-color: #4AA9E8;
}

QComboBox#inputBox,
QSpinBox#inputBox,
QDoubleSpinBox#inputBox {
    background-color: #0A142A;
    border: 1px solid #284064;
    border-radius: 8px;
    color: #EAF6FF;
    padding: 4px 8px;
    min-height: 26px;
}

QSpinBox#inputBox,
QDoubleSpinBox#inputBox {
    padding-right: 4px;
}

QSpinBox#inputBox::up-button,
QDoubleSpinBox#inputBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    border-left: 1px solid #284064;
    background-color: #111B33;
    border-top-right-radius: 7px;
}

QSpinBox#inputBox::down-button,
QDoubleSpinBox#inputBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 28px;
    border: none;
    border-left: 1px solid #284064;
    background-color: #111B33;
    border-bottom-right-radius: 7px;
}

QSpinBox#inputBox::up-button:hover,
QDoubleSpinBox#inputBox::up-button:hover,
QSpinBox#inputBox::down-button:hover,
QDoubleSpinBox#inputBox::down-button:hover {
    background-color: #1A2748;
}

QSpinBox#inputBox::up-arrow,
QDoubleSpinBox#inputBox::up-arrow,
QSpinBox#inputBox::down-arrow,
QDoubleSpinBox#inputBox::down-arrow,
QComboBox#inputBox::down-arrow {
    image: none;
    width: 16px;
    height: 16px;
}

QComboBox#inputBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
}

QComboBox#inputBox QAbstractItemView {
    background-color: #111B33;
    color: #EAF6FF;
    selection-background-color: #2F80E6;
}

QDoubleSpinBox#paramSpin {
    min-height: 24px;
    padding-right: 14px;
}

QDoubleSpinBox#paramSpin::up-button,
QDoubleSpinBox#paramSpin::down-button {
    background: transparent;
    border: none;
    width: 14px;
}

QDoubleSpinBox#paramSpin::up-button:hover,
QDoubleSpinBox#paramSpin::down-button:hover {
    background: rgba(255, 255, 255, 18);
}

QCheckBox#toggle {
    color: #C9DCF5;
    spacing: 8px;
    font-size: 13px;
}

QCheckBox#toggle::indicator {
    width: 18px;
    height: 18px;
}

QPushButton#ghostButton {
    background: transparent;
    border: 1px solid #284064;
    border-radius: 8px;
    color: #9DB5D8;
    padding: 6px 18px;
    min-height: 32px;
    min-width: 96px;
}

QPushButton#ghostButton:hover {
    color: #EAF6FF;
    border-color: #4AA9E8;
}

QPushButton#rowRemoveButton {
    background: transparent;
    border: 1px solid #284064;
    border-radius: 6px;
    color: #9DB5D8;
    padding: 0;
    min-width: 0;
    min-height: 0;
    font-size: 14px;
}

QPushButton#rowRemoveButton:hover {
    color: #EAF6FF;
    border-color: #4AA9E8;
    background: rgba(255, 255, 255, 18);
}

QPushButton#smallGhostButton {
    background: transparent;
    border: 1px solid #284064;
    border-radius: 6px;
    color: #9DB5D8;
    padding: 3px 10px;
    min-width: 0;
}

QPushButton#smallGhostButton:hover {
    color: #EAF6FF;
    border-color: #4AA9E8;
}

QPushButton#smallActionButton {
    background-color: #1E6FD9;
    color: #FFFFFF;
    border: 1px solid #3580E8;
    border-radius: 6px;
    padding: 3px 12px;
    min-height: 26px;
    min-width: 0;
    font-weight: 600;
}

QPushButton#smallActionButton:hover {
    background-color: #2F80E6;
}

QPushButton#smallActionButton:pressed {
    background-color: #1A60C2;
}

QSlider#rvcSlider {
    min-height: 20px;
}

QSlider#rvcSlider::groove:horizontal {
    height: 6px;
    background: #1A2A4A;
    border-radius: 3px;
}

QSlider#rvcSlider::handle:horizontal {
    background: #4AA9E8;
    border: none;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}

QSlider#rvcSlider::handle:horizontal:hover {
    background: #6BB8F0;
}

QSlider#rvcSlider::sub-page:horizontal {
    background: #4AA9E8;
    border-radius: 3px;
}
"""


_ARROW_COLOR = QColor("#EAF6FF")


def _draw_triangle(painter: QPainter, rect: QRect, up: bool) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(_ARROW_COLOR)
    cx = rect.center().x()
    cy = rect.center().y()
    half_w = min(5.0, rect.width() * 0.3)
    half_h = min(3.5, rect.height() * 0.3)
    if up:
        points = [
            QPointF(cx, cy - half_h),
            QPointF(cx + half_w, cy + half_h),
            QPointF(cx - half_w, cy + half_h),
        ]
    else:
        points = [
            QPointF(cx - half_w, cy - half_h),
            QPointF(cx + half_w, cy - half_h),
            QPointF(cx, cy + half_h),
        ]
    painter.drawPolygon(QPolygonF(points))
    painter.restore()


class ArrowSpinBox(QSpinBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        up = self.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, self)
        down = self.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self)
        _draw_triangle(painter, up, True)
        _draw_triangle(painter, down, False)
        painter.end()


class ArrowDoubleSpinBox(QDoubleSpinBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        up = self.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, self)
        down = self.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self)
        _draw_triangle(painter, up, True)
        _draw_triangle(painter, down, False)
        painter.end()


class ArrowComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, self
        )
        _draw_triangle(painter, arrow, False)
        painter.end()


def _make_panel(title: str) -> QFrame:
    panel = QFrame()
    panel.setObjectName("panel")
    panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    layout = QVBoxLayout(panel)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title_label = QLabel(title)
    title_label.setObjectName("panelTitle")
    layout.addWidget(title_label)

    body = QLabel("...")
    body.setObjectName("panelBody")
    layout.addWidget(body)
    layout.addStretch()
    return panel


def _make_card(title: str):
    panel = QFrame()
    panel.setObjectName("panel")
    panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    title_label = QLabel(title)
    title_label.setObjectName("panelTitle")
    layout.addWidget(title_label)
    return panel, layout


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


def _make_simple_page(title: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    layout.addWidget(title_label)
    layout.addWidget(_make_panel(title), 1)
    return page


class PoseGestureDialog(QDialog):
    """录制自定义手势时的命名 / 宽紧对话框。

    弹窗里给三样东西：**这一帧到底抓到了什么**（姿势摘要，让用户确认手是
    在画面里的、抓的不是一个空姿势）、**名字**、**判定宽紧**。

    为什么要给「宽紧」而不是一个数字容差：容差是归一化距离，用户没法凭
    0.16 这个数判断松紧。这里换成三档人话，映射到
    ``pose_gesture.DEFAULT_TOLERANCE`` 附近——严（0.10，要求摆得很准）、
    标准（0.16）、松（0.24，动作幅度不定时用）。松档也不能再往上放：
    「举右手」和「举左手」的距离是 0.42，拉过这个数就会互相误触发。
    """

    #: 档位 -> (容差, 说明)
    LEVELS: tuple[tuple[float, str], ...] = (
        (0.10, "严：动作要摆得比较准"),
        (0.16, "标准"),
        (0.24, "松：差不多就行（适合幅度不稳定 / 衣着宽松）"),
    )

    def __init__(self, parent, pose: dict, summary: str, default_name: str,
                 hand_text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("录制自定义手势")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        captured = QLabel(f"已抓取当前动捕姿势：{summary}")
        captured.setObjectName("hintText")
        captured.setWordWrap(True)
        layout.addWidget(captured)

        # 「手势对不对得上」最容易在这里出错：用户做的是单指，界面上却是
        # 握拳（手指没被读到 / 判据认错）。把**这一帧识别到的手型和逐指
        # 弯曲度**直接打出来，对不上时一眼能看出是哪一环，不用猜。
        if hand_text:
            hands = QLabel(f"手型：{hand_text}")
            hands.setObjectName("hintText")
            hands.setWordWrap(True)
            layout.addWidget(hands)

        name_caption = QLabel("手势名称")
        name_caption.setObjectName("hintText")
        layout.addWidget(name_caption)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("inputBox")
        self.name_edit.setText(default_name)
        self.name_edit.selectAll()
        self.name_edit.returnPressed.connect(self.accept)
        layout.addWidget(self.name_edit)

        level_caption = QLabel("识别宽紧")
        level_caption.setObjectName("hintText")
        layout.addWidget(level_caption)
        self.level_combo = ArrowComboBox()
        self.level_combo.setObjectName("inputBox")
        for index, (value, label) in enumerate(self.LEVELS):
            self.level_combo.addItem(label, value)
        default_index = 1
        for index, (value, _label) in enumerate(self.LEVELS):
            if abs(value - pose_gesture.DEFAULT_TOLERANCE) < 1e-6:
                default_index = index
        self.level_combo.setCurrentIndex(default_index)
        layout.addWidget(self.level_combo)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("actionButton")
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def result_payload(self) -> dict:
        """``{"name": ..., "tolerance": ...}``。"""
        name = self.name_edit.text().strip() or self.name_edit.placeholderText()
        return {
            "name": pose_gesture.clean_name(name),
            "tolerance": float(self.level_combo.currentData()
                               or pose_gesture.DEFAULT_TOLERANCE),
        }


class HomeWindow(QMainWindow):
    logout_requested = Signal()
    profile_loaded = Signal(dict)
    profile_load_error = Signal(str)
    profile_saved = Signal(dict)
    profile_save_error = Signal(str)
    cloud_models_loaded = Signal(list)
    cloud_models_error = Signal(str)
    cloud_action_done = Signal(str)
    cloud_action_error = Signal(str)
    cloud_presets_loaded = Signal(list)
    cloud_presets_error = Signal(str)
    rvc_status_changed = Signal(str, bool)
    rvc_volume_updated = Signal(int, int)
    server_status_changed = Signal(bool, str)
    camera_devices_loaded = Signal(list, bool)
    vcam_install_done = Signal(bool, str)

    def __init__(self, account: str | None = None, offline: bool = False) -> None:
        super().__init__()
        self.offline = bool(offline)
        # Offline mode uses a dedicated local profile and never displays/reads
        # the selected account's cloud content or per-account data.
        self.account = LOCAL_PROFILE_DISPLAY if self.offline else (account or "")
        self.setWindowTitle("星弦")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 800)
        self.setStyleSheet(STYLE_SHEET)
        store_account = LOCAL_PROFILE if self.offline else self.account
        self.model_store = ModelStore(store_account)
        self.model_entries = self.model_store.load()
        self.settings_store = SettingsStore(store_account)
        self.motion_settings = self.settings_store.load_motion()
        self.system_settings = self.settings_store.load_system()
        self.motion_capture = MotionCapture()
        self.motion_capture.frame_ready.connect(self._on_motion_frame)
        self.motion_capture.drive_changed.connect(self._on_motion_drive)
        self.motion_capture.status_changed.connect(self._on_motion_status)
        self.motion_capture.gesture_changed.connect(self._on_gesture_changed)
        self.motion_capture.pose_gesture_changed.connect(self._on_pose_gesture_changed)
        self.motion_capture.hands_status_changed.connect(self._on_hands_status_changed)
        self.motion_capture.set_engine(self.motion_settings.get("engine", "hybrid"))
        self.motion_capture.set_drive_params(self.motion_settings.get("params", {}))
        self.motion_capture.set_hand_enabled(bool(self.motion_settings.get("hand_enabled", True)))
        self.motion_capture.set_gesture_enabled(bool(self.motion_settings.get("gesture_enabled", True)))
        self.motion_capture.set_hand_stride(int(self.motion_settings.get("hand_every", 1)))
        #: 手势 -> 动作 id（``none`` / ``motion:<动作组>`` / ``expression:<表情>``）。
        #: 可选项按当前模型动态生成，见 _rebuild_gesture_menus。
        self.gesture_actions = dict(DEFAULT_GESTURE_ACTIONS)
        saved_actions = self.motion_settings.get("gesture_actions")
        if isinstance(saved_actions, dict):
            for key, value in saved_actions.items():
                if key in self.gesture_actions:
                    self.gesture_actions[key] = value
        #: 每个模型各一套手势配置：``{模型key: {"gestures": [手势行, ...]}}``。
        #: 手势行既含默认手势（可删）也含用户录制的自定义姿势手势，是列表界面的
        #: 唯一数据源；``gesture_actions`` 只作模型未加载时的兜底与迁移来源。
        self.gesture_profiles = self.motion_settings.get("gesture_profiles")
        if not isinstance(self.gesture_profiles, dict):
            self.gesture_profiles = {}
        #: 当前手势列表的呈现行（每个模型一套，见 _gesture_rows）
        self._gesture_rows_cache: list[dict] = []
        #: 手势 id -> 界面控件（下拉框与整行容器），重建列表时复用
        self.gesture_combos: dict[str, ArrowComboBox] = {}
        self._gesture_row_widgets: dict[str, dict] = {}
        #: 姿势手势的实时状态（当前命中的自定义手势 id），只用于提示
        self._pose_gesture_state = {"id": ""}
        #: 最近一次识别到的内置手势（「左手 比耶」这样的文案），和姿势手势一起显示
        self._gesture_active_label = ""
        #: 动捕线程最近报来的**手型**文案（「左手 握拳」/「手部：未检测到」）。
        #: 只是原材料，真正显示的文字由 ``_hands_status_line()`` 合成。
        self._hand_status_text = ""
        self._gesture_expression = {"kind": "", "until": 0.0}
        self._gesture_menu_model: list[str] = []
        self.lipsync_settings = self.settings_store.load_lipsync()
        self._voice_lipsync = VoiceLipSync()
        self._voice_lipsync.set_gain(float(self.lipsync_settings.get("gain", 1.4)))
        self._lipsync_timer = QTimer(self)
        self._lipsync_timer.setInterval(50)  # 20 FPS，口型不需要跟动捕同频
        self._lipsync_timer.timeout.connect(self._on_lipsync_tick)
        self.profile_data: dict = {}
        self.personal_page_index = 0
        self._avatar_running = False  # 模型预览是否处于启动（显示）状态
        self._avatar_running_before_capture = False  # 动捕开始前模型是否已启动
        self._avatar_kind = "live2d"  # 虚拟形象页当前模型类型（live2d / vrm）

        self._closing = False
        self._camera_devices: list = []
        self._motion_running = False
        self._rvc_gate_threshold = 0
        self._rvc_denoise = False
        self.virtual_camera = VirtualCameraOutput()
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(33)  # ~30 FPS
        self._stream_timer.timeout.connect(self._push_stream_frame)
        self._smooth_in = 0.0
        self._smooth_out = 0.0
        self._last_volume_emit = 0.0
        icon_path = ICON_PATH if ICON_PATH.exists() else LOGO_PATH
        self.setWindowIcon(QIcon(str(icon_path)))
        self.setCentralWidget(self._build_ui())
        self._place_live2d_for_page(self.pages.currentIndex())
        self._sync_preview_views()
        self.profile_loaded.connect(self._on_profile_loaded)
        self.profile_load_error.connect(self._on_profile_load_error)
        self.profile_saved.connect(self._on_profile_saved)
        self.profile_save_error.connect(self._on_profile_save_error)
        self.cloud_models_loaded.connect(self._on_cloud_models_loaded)
        self.cloud_models_error.connect(self._on_cloud_models_error)
        self.cloud_action_done.connect(self._on_cloud_action_done)
        self.cloud_action_error.connect(self._on_cloud_action_error)
        self.cloud_presets_loaded.connect(self._on_cloud_presets_loaded)
        self.cloud_presets_error.connect(self._on_cloud_presets_error)
        self.rvc_status_changed.connect(self._on_rvc_status_changed)
        self.rvc_volume_updated.connect(self._on_rvc_volume_updated)
        self._mixer_dialog = None
        self.server_status_changed.connect(self._on_server_status_changed)
        self.camera_devices_loaded.connect(self._on_camera_devices_loaded)
        self.vcam_install_done.connect(self._on_vcam_install_done)
        self._start_server_monitor()
        self._refresh_camera_devices()

        # 语音驱动口型：启用后一直跑定时器，读到的口型直接写进当前模型视图
        if bool(self.lipsync_settings.get("enabled", False)):
            self._voice_lipsync.set_enabled(True)
            self._set_lipsync_controls(enabled=True)
            self._lipsync_timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        timer = getattr(self, "_server_timer", None)
        if timer is not None:
            timer.stop()
        lipsync_timer = getattr(self, "_lipsync_timer", None)
        if lipsync_timer is not None:
            lipsync_timer.stop()
        stream_timer = getattr(self, "_stream_timer", None)
        if stream_timer is not None:
            stream_timer.stop()
        camera = getattr(self, "virtual_camera", None)
        if camera is not None:
            camera.stop()
        self._save_rvc_settings()
        self._save_system_settings()
        self._shutdown_mixer()
        self._shutdown_live2d()
        self.motion_capture.shutdown()
        super().closeEvent(event)

    def _shutdown_live2d(self) -> None:
        view = getattr(self, "live2d_view", None)
        if view is not None:
            view.shutdown()

    def _build_ui(self) -> QWidget:
        root = QWidget()
        root.setObjectName("homeRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_pages(), 1)
        root_layout.addLayout(body, 1)
        return root

    def _build_topbar(self) -> QFrame:
        topbar = QFrame()
        topbar.setObjectName("topBar")
        topbar.setFixedHeight(64)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        brand = QLabel("✦ 星弦 · 虚拟主播工作台")
        brand.setObjectName("brandTitle")
        layout.addWidget(brand)
        layout.addStretch()

        profile_button = QPushButton("个人中心")
        profile_button.setObjectName("linkButton")
        profile_button.clicked.connect(lambda: self._open_page(self.personal_page_index))
        settings_button = QPushButton("设置")
        settings_button.setObjectName("linkButton")
        settings_button.clicked.connect(lambda: self._open_page(6))
        logout_button = QPushButton("退出登录")
        logout_button.setObjectName("linkButton")
        logout_button.clicked.connect(self.logout_requested.emit)

        layout.addWidget(profile_button)
        layout.addWidget(settings_button)
        layout.addWidget(logout_button)

        avatar = QLabel(self.account[:1] or "星")
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setToolTip(self.account)
        avatar.setStyleSheet(
            "border-radius: 19px; background: #4AA9E8; color: #FFFFFF; font-weight: 600;"
        )
        layout.addWidget(avatar)
        return topbar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(6)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.pages = QStackedWidget()
        for index, name in enumerate(NAV_ITEMS):
            if index == 0:
                page = self._build_home_page()
            elif index == 1:
                page = self._build_motion_page()
            elif index == 2:
                page = self._build_rvc_page()
            elif index == 3:
                page = self._build_live2d_page()
            elif index == 5:
                page = self._build_model_management_page()
            elif index == 6:
                page = self._build_system_settings_page()
            elif index == 7:
                page = self._build_cloud_management_page()
            else:
                page = _make_simple_page(name)
            self.pages.addWidget(page)

            button = QPushButton(name)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, i=index: self._open_page(i)
            )
            self.nav_group.addButton(button)
            layout.addWidget(button)

        self.personal_page_index = self.pages.count()
        self.pages.addWidget(self._build_personal_center_page())

        self.nav_group.buttons()[0].setChecked(True)
        layout.addStretch()

        self.scheme_label = QLabel(
            f"配置：{self.system_settings.get('scheme_name', '日常直播')}"
        )
        self.scheme_label.setStyleSheet("color: #9DB5D8; font-size: 12px;")
        layout.addWidget(self.scheme_label)

        self.server_status_label = QLabel("服务器：检测中")
        self.server_status_label.setStyleSheet("color: #9DB5D8; font-size: 12px;")
        layout.addWidget(self.server_status_label)
        return sidebar

    def _build_pages(self) -> QStackedWidget:
        return self.pages

    def _open_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        # 切页时按当前状态重画一遍启停入口：别处已经启动的动捕 / 形象，在这一页
        # 的按钮上也得是「已启动」的样子（用户报的就是切到形象页停在「启动」）
        self._refresh_runtime_controls()
        self.nav_group.setExclusive(False)
        for button in self.nav_group.buttons():
            button.setChecked(False)
        if index < len(NAV_ITEMS):
            self.nav_group.buttons()[index].setChecked(True)
        self.nav_group.setExclusive(True)
        self._place_live2d_for_page(index)
        self._sync_preview_views()
        if index == 0:
            self._sync_home_devices_from_page()
        if index in (1, 6):
            self._refresh_camera_devices(force=False)
        if index == 2:  # RVC页面
            self._refresh_audio_devices()
            self._refresh_rvc_model_list()
        if index == 7:
            self._refresh_cloud_models()
            self._refresh_cloud_presets()
        if index == self.personal_page_index:
            self._load_profile()

    def _place_live2d_for_page(self, index: int) -> None:
        view = getattr(self, "live2d_view", None)
        if view is None:
            return
        if index == 0:
            holder = getattr(self, "home_preview_holder", None)
            vrm_host = holder
        elif index == 1:
            holder = getattr(self, "motion_avatar_holder", None)
            vrm_host = getattr(self, "motion_avatar_holder", None)
        elif index == 3:
            holder = getattr(self, "avatar_preview_holder", None)
            vrm_host = getattr(self, "avatar_preview_holder", None)
        else:
            return
        if holder is None:
            return
        self._move_view_to(view, holder)
        vrm_view = getattr(self, "avatar_vrm_view", None)
        if vrm_view is not None:
            self._move_view_to(vrm_view, vrm_host)

    @staticmethod
    def _move_view_to(view, holder) -> None:
        """把一个模型视图移到指定预览容器，保证只在该容器内显示。"""
        if view is None or holder is None:
            return
        current = view.parentWidget()
        if current is holder:
            return
        if current is not None and current.layout() is not None:
            current.layout().removeWidget(view)
        view.setParent(holder)
        holder.layout().addWidget(view, 1)
        view.update()

    def _sync_preview_views(self) -> None:
        """保证每个预览区域同一时刻只展示一个模型视图，避免两种模型叠显。"""
        index = self.pages.currentIndex() if hasattr(self, "pages") else -1
        shared = getattr(self, "live2d_view", None)  # 全局唯一的 Live2D 渲染器
        running = getattr(self, "_avatar_running", False)

        if index == 0:
            # 首页预览区：Live2D / VRM 二选一
            shared_vrm = getattr(self, "avatar_vrm_view", None)
            if shared is None or shared_vrm is None:
                return
            if not running:
                shared.hide()
                shared_vrm.hide()
                return
            model_type = "live2d"
            if hasattr(self, "home_type_tabs"):
                model_type = "vrm" if self.home_type_tabs.currentIndex() >= 1 else "live2d"
            if model_type == "vrm":
                shared.hide()
                shared_vrm.show()
            else:
                shared.show()
                shared_vrm.hide()
        elif index == 1:
            # 动捕页：按当前模型类型显示 Live2D / VRM 二选一
            avatar_vrm = getattr(self, "avatar_vrm_view", None)
            if shared is None:
                return
            if not running:
                shared.hide()
                if avatar_vrm is not None:
                    avatar_vrm.hide()
                return
            model_type = self._current_avatar_kind()
            if model_type == "vrm" and avatar_vrm is not None:
                avatar_vrm.show()
                shared.hide()
            else:
                shared.show()
                if avatar_vrm is not None:
                    avatar_vrm.hide()
        elif index == 3:
            # 虚拟形象页：Live2D / VRM 二选一；本页的 avatar_live2d_view 无模型，始终隐藏
            avatar_live2d = getattr(self, "avatar_live2d_view", None)
            avatar_vrm = getattr(self, "avatar_vrm_view", None)
            if avatar_vrm is None:
                return
            if avatar_live2d is not None:
                avatar_live2d.hide()
            if not running:
                avatar_vrm.hide()
                if shared is not None:
                    shared.hide()
                return
            model_type = self._current_avatar_kind()
            if model_type == "vrm":
                avatar_vrm.show()
                if shared is not None:
                    shared.hide()
            else:
                avatar_vrm.hide()
                if shared is not None:
                    shared.show()

    def _build_motion_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("视频动捕")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.motion_focus_key = None

        preview_card, preview_box = self._make_clickable_card("动捕画面", "camera")
        self.motion_preview = QLabel("摄像头未开启")
        self.motion_preview.setAlignment(Qt.AlignCenter)
        self.motion_preview.setStyleSheet(
            "background-color: #0A142A; border: 1px solid #284064; border-radius: 10px; color: #A9C3E2;"
        )
        self.motion_preview.setMinimumSize(180, 120)
        self.motion_preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        preview_box.addWidget(self.motion_preview, 1)
        self.motion_status = QLabel("就绪")
        self.motion_status.setObjectName("panelBody")
        preview_box.addWidget(self.motion_status)
        self.motion_camera_card = preview_card

        avatar_card, avatar_box = self._make_clickable_card("虚拟形象驱动", "avatar")
        self.motion_avatar_holder = QFrame()
        self.motion_avatar_holder.setObjectName("stagePanel")
        motion_holder_layout = QVBoxLayout(self.motion_avatar_holder)
        motion_holder_layout.setContentsMargins(8, 8, 8, 8)
        motion_holder_layout.setSpacing(0)
        avatar_box.addWidget(self.motion_avatar_holder, 1)
        self.motion_avatar_card = avatar_card

        controls_card, controls_box = self._make_clickable_card("动捕控制", "controls")
        cam_row = QHBoxLayout()
        cam_row.addWidget(self._form_label("摄像头设备"))
        self.motion_camera_combo = ArrowComboBox()
        self.motion_camera_combo.setObjectName("inputBox")
        self._configure_device_combo(self.motion_camera_combo, 160, 320)
        self.motion_camera_combo.currentIndexChanged.connect(self._on_motion_camera_changed)
        cam_row.addWidget(self.motion_camera_combo, 1)
        cam_refresh = QPushButton("刷新")
        cam_refresh.setObjectName("smallGhostButton")
        cam_refresh.clicked.connect(lambda: self._refresh_camera_devices(force=True))
        cam_row.addWidget(cam_refresh)
        controls_box.addLayout(cam_row)
        self._populate_camera_combo(self.motion_camera_combo)

        self.motion_mirror = QCheckBox("镜像画面")
        self.motion_mirror.setObjectName("toggle")
        self.motion_mirror.setChecked(bool(self.motion_settings.get("mirror", True)))
        self.motion_mirror.toggled.connect(self._on_motion_mirror_changed)
        controls_box.addWidget(self.motion_mirror)

        self.motion_lr_mirror = QCheckBox("左右反转")
        self.motion_lr_mirror.setObjectName("toggle")
        self.motion_lr_mirror.setChecked(bool(self.motion_settings.get("lr_mirror", False)))
        self.motion_lr_mirror.toggled.connect(self._on_motion_lr_mirror_changed)
        controls_box.addWidget(self.motion_lr_mirror)

        sens_row = QHBoxLayout()
        sens_row.addWidget(self._form_label("灵敏度"))
        self.motion_sensitivity = ArrowDoubleSpinBox()
        self.motion_sensitivity.setObjectName("inputBox")
        self.motion_sensitivity.setRange(0.1, 3.0)
        self.motion_sensitivity.setSingleStep(0.1)
        self.motion_sensitivity.setValue(float(self.motion_settings.get("sensitivity", 1.0)))
        self.motion_sensitivity.valueChanged.connect(self._on_motion_sensitivity_changed)
        sens_row.addWidget(self.motion_sensitivity, 1)
        controls_box.addLayout(sens_row)

        self.motion_drive_checkbox = QCheckBox("开启动捕驱动 Live2D")
        self.motion_drive_checkbox.setObjectName("toggle")
        self.motion_drive_checkbox.setChecked(bool(self.motion_settings.get("drive_enabled", True)))
        self.motion_drive_checkbox.toggled.connect(self._on_motion_drive_toggle)
        controls_box.addWidget(self.motion_drive_checkbox)

        start_stop = QHBoxLayout()
        self.motion_start_button = QPushButton("开始动捕")
        self.motion_start_button.setObjectName("actionButton")
        self.motion_start_button.clicked.connect(self._on_motion_start)
        self.motion_stop_button = QPushButton("停止")
        self.motion_stop_button.setObjectName("ghostButton")
        self.motion_stop_button.clicked.connect(self._on_motion_stop)
        self.motion_stop_button.hide()  # 未开始动捕只显示“开始动捕”
        start_stop.addWidget(self.motion_start_button)
        start_stop.addWidget(self.motion_stop_button)
        start_stop.addStretch()
        controls_box.addLayout(start_stop)

        # ---- 手部与手势（手势可触发动作/表情） ----
        hand_title = QLabel("手部与手势")
        hand_title.setObjectName("panelTitle")
        controls_box.addWidget(hand_title)

        self.hand_enabled_checkbox = QCheckBox("手部驱动（手臂/手指跟随）")
        self.hand_enabled_checkbox.setObjectName("toggle")
        self.hand_enabled_checkbox.setChecked(bool(self.motion_settings.get("hand_enabled", True)))
        self.hand_enabled_checkbox.toggled.connect(self._on_hand_enabled_changed)
        controls_box.addWidget(self.hand_enabled_checkbox)

        self.gesture_enabled_checkbox = QCheckBox("手势触发动作 / 表情")
        self.gesture_enabled_checkbox.setObjectName("toggle")
        self.gesture_enabled_checkbox.setChecked(bool(self.motion_settings.get("gesture_enabled", True)))
        self.gesture_enabled_checkbox.toggled.connect(self._on_gesture_enabled_changed)
        controls_box.addWidget(self.gesture_enabled_checkbox)

        # 手部检测抽帧间隔：直接决定手指/手腕有多「跟手」
        stride_row = QHBoxLayout()
        stride_row.setSpacing(8)
        stride_caption = QLabel("跟手速度")
        stride_caption.setObjectName("hintText")
        stride_row.addWidget(stride_caption)
        self.hand_stride_combo = ArrowComboBox()
        self.hand_stride_combo.setObjectName("inputBox")
        for value, label in (
            (1, "每帧（最跟手）"),
            (2, "隔帧"),
            (3, "每 3 帧"),
            (4, "每 4 帧（省算力）"),
        ):
            self.hand_stride_combo.addItem(label, value)
        stride_index = self.hand_stride_combo.findData(int(self.motion_settings.get("hand_every", 1)))
        self.hand_stride_combo.setCurrentIndex(max(stride_index, 0))
        self.hand_stride_combo.currentIndexChanged.connect(self._on_hand_stride_changed)
        stride_row.addWidget(self.hand_stride_combo, 1)
        controls_box.addLayout(stride_row)

        self.hands_status_label = QLabel("手部：未检测到")
        self.hands_status_label.setObjectName("hintText")
        self.hands_status_label.setWordWrap(True)
        controls_box.addWidget(self.hands_status_label)

        # 手势列表：默认的七条 + 用户录制的自定义姿势手势，按当前模型各存一套。
        # 行是动态的（可删默认手势、可加自定义手势），所以只在这里建一个空网格，
        # 内容交给 _rebuild_gesture_menus() 填。
        gesture_grid = QGridLayout()
        gesture_grid.setContentsMargins(0, 0, 0, 0)
        gesture_grid.setHorizontalSpacing(8)
        gesture_grid.setVerticalSpacing(4)
        head = QLabel("手势")
        head.setObjectName("hintText")
        gesture_grid.addWidget(head, 0, 0)
        head_action = QLabel("触发动作")
        head_action.setObjectName("hintText")
        gesture_grid.addWidget(head_action, 0, 1)
        self.gesture_grid = gesture_grid
        controls_box.addLayout(gesture_grid)
        self.gesture_menu_hint = QLabel("")
        self.gesture_menu_hint.setObjectName("hintText")
        self.gesture_menu_hint.setWordWrap(True)
        controls_box.addWidget(self.gesture_menu_hint)

        # 手势设置：录当前动捕姿势当手势、把默认手势恢复回来
        gesture_tools = QHBoxLayout()
        gesture_tools.setSpacing(8)
        self.gesture_record_button = QPushButton("＋ 录制自定义手势")
        self.gesture_record_button.setObjectName("ghostButton")
        self.gesture_record_button.clicked.connect(self._on_record_pose_gesture)
        self.gesture_reset_button = QPushButton("恢复默认手势")
        self.gesture_reset_button.setObjectName("ghostButton")
        self.gesture_reset_button.clicked.connect(self._on_reset_gesture_rows)
        gesture_tools.addWidget(self.gesture_record_button)
        gesture_tools.addWidget(self.gesture_reset_button)
        gesture_tools.addStretch()
        controls_box.addLayout(gesture_tools)

        # 选项来自当前模型实际支持的动作 / 表情，不是写死的列表
        self._rebuild_gesture_menus()
        self._refresh_gesture_ui()

        controls_box.addStretch()
        self.motion_controls_card = controls_card

        values_card, values_box = self._make_clickable_card("驱动数值", "values")
        self.motion_value_labels: dict[str, QLabel] = {}
        for cap, key in (
            ("头部左右", "angle_x"),
            ("头部上下", "angle_y"),
            ("头部翻转", "angle_z"),
            ("左手抬落", "arm_l"),
            ("右手抬落", "arm_r"),
            ("左手侧摆", "arm_l_x"),
            ("右手侧摆", "arm_r_x"),
            ("左上臂摆动", "arm_swing_l"),
            ("右上臂摆动", "arm_swing_r"),
            ("左肘弯曲", "elbow_l"),
            ("右肘弯曲", "elbow_r"),
            ("左臂前倾", "arm_fwd_l"),
            ("右臂前倾", "arm_fwd_r"),
            ("左手弯曲", "hand_l"),
            ("右手弯曲", "hand_r"),
            ("嘴型开合", "mouth_open"),
        ):
            row = QHBoxLayout()
            name = QLabel(cap)
            name.setObjectName("hintText")
            value = QLabel("0.0")
            value.setObjectName("infoValue")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(name)
            row.addWidget(value, 1)
            values_box.addLayout(row)
            self.motion_value_labels[key] = value

        gesture_row = QHBoxLayout()
        gesture_caption = QLabel("识别手势")
        gesture_caption.setObjectName("hintText")
        self.gesture_value_label = QLabel("—")
        self.gesture_value_label.setObjectName("infoValue")
        self.gesture_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gesture_row.addWidget(gesture_caption)
        gesture_row.addWidget(self.gesture_value_label, 1)
        values_box.addLayout(gesture_row)
        self.motion_values_card = values_card

        self.motion_area = QWidget()
        self.motion_card_pos = {
            "camera": (0, 0),
            "avatar": (0, 1),
            "controls": (1, 0),
            "values": (1, 1),
        }
        layout.addWidget(self.motion_area, 1)
        self.motion_focus_layer = QWidget(self.motion_area)
        self.motion_focus_layer.setStyleSheet("background-color: #0A1020;")
        self.motion_focus_layer.setVisible(False)
        self._rebuild_motion_area(None)
        return page

    def _make_clickable_card(self, title: str, key: str):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        header = ClickableLabel(title)
        header.setObjectName("panelTitle")
        header.setCursor(Qt.PointingHandCursor)
        header.setToolTip("点击放大，再次点击还原")
        header.clicked.connect(lambda: self._toggle_motion_focus(key))
        layout.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        return panel, inner

    def _make_home_card(self, title: str, key: str):
        """首页卡片：标题可点击放大，内容放进滚动区避免压缩变形。"""
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        header = ClickableLabel(title)
        header.setObjectName("panelTitle")
        header.setCursor(Qt.PointingHandCursor)
        header.setToolTip("点击放大，再次点击还原")
        header.clicked.connect(lambda: self._toggle_home_focus(key))
        layout.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        scroll.setWidget(content)
        self.home_card_scrolls[key] = scroll
        layout.addWidget(scroll, 1)
        return panel, inner

    def _toggle_motion_focus(self, key: str) -> None:
        if self.motion_focus_key == key:
            self._exit_motion_focus(key)
        elif self.motion_focus_key is not None:
            self._exit_motion_focus(self.motion_focus_key, immediate=True)
            self._enter_motion_focus(key)
        else:
            self._enter_motion_focus(key)

    def _rebuild_motion_area(self, focus_key: str | None) -> None:
        area_layout = getattr(self, "_area_layout", None)
        if area_layout is None:
            area_layout = QVBoxLayout(self.motion_area)
            area_layout.setContentsMargins(0, 0, 0, 0)
            area_layout.setSpacing(0)
            self._area_layout = area_layout
        self._clear_layout(area_layout)

        keys = ("camera", "avatar", "controls", "values")
        panels = {key: getattr(self, f"motion_{key}_card") for key in keys}
        if focus_key is None:
            grid = QGridLayout()
            grid.setSpacing(14)
            for key, (row, col) in self.motion_card_pos.items():
                grid.addWidget(panels[key], row, col)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            grid.setRowStretch(0, 1)
            grid.setRowStretch(1, 1)
            self._motion_grid = grid
            area_layout.addLayout(grid, 1)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.layout():
                HomeWindow._clear_layout(item.layout())

    def _enter_motion_focus(self, key: str) -> None:
        keys = ("camera", "avatar", "controls", "values")
        layer = self.motion_focus_layer
        layer.setGeometry(self.motion_area.rect())
        rect = self.motion_area.rect()
        focused_rect, others_rects = self._focus_geometry(key, rect)
        self._focus_to_grid = {}
        self._focus_to_grid[key] = card_geom = getattr(self, f"motion_{key}_card").geometry()
        for k in keys:
            card = getattr(self, f"motion_{k}_card")
            if k != key:
                self._focus_to_grid[k] = card.geometry()
            card.setParent(layer)
            card.show()

        self.motion_focus_key = key
        layer.show()
        layer.raise_()
        for k in keys:
            card = getattr(self, f"motion_{k}_card")
            start = self._focus_to_grid.get(k, card.geometry())
            target = focused_rect if k == key else others_rects[k]
            self._animate_card_geometry_once(card, start, target)

    def _exit_motion_focus(self, key: str, immediate: bool = False) -> None:
        if immediate:
            self._restore_after_focus(key)
            return
        card = getattr(self, f"motion_{key}_card")
        start = card.geometry()
        end = self._focus_to_grid.get(key, start)
        self._animate_card_geometry_once(card, start, end, lambda: self._restore_after_focus(key))
        self.motion_focus_key = None

    def _restore_after_focus(self, key: str) -> None:
        self.motion_focus_layer.hide()
        for k in ("camera", "avatar", "controls", "values"):
            card = getattr(self, f"motion_{k}_card")
            card.setParent(self.motion_area)
            row, col = self.motion_card_pos[k]
            self._motion_grid.addWidget(card, row, col)
            card.show()
        self.motion_focus_key = None

    def _focus_geometry(self, key: str, rect: QRect):
        keys = ("camera", "avatar", "controls", "values")
        others = [k for k in keys if k != key]
        if key in ("camera", "controls"):
            big = QRect(0, 0, int(rect.width() * 0.62), rect.height())
            side = QRect(int(rect.width() * 0.62), 0, int(rect.width() * 0.38), rect.height())
        else:
            big = QRect(int(rect.width() * 0.38), 0, int(rect.width() * 0.62), rect.height())
            side = QRect(0, 0, int(rect.width() * 0.38), rect.height())
        count = len(others)
        cell_h = side.height() // count
        others_rects = {}
        for index, other in enumerate(others):
            others_rects[other] = QRect(
                side.x() + 8,
                side.y() + 8 + index * cell_h,
                max(60, side.width() - 16),
                max(60, cell_h - 16),
            )
        return big, others_rects

    def _animate_card_geometry_once(self, card, start: QRect, end: QRect, on_finish=None) -> None:
        animation = QPropertyAnimation(card, b"geometry", self)
        animation.setDuration(320)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)
        if on_finish is not None:
            animation.finished.connect(on_finish)
        animation.start()
        self._motion_card_animation = animation

    def _toggle_home_focus(self, key: str) -> None:
        if self.home_focus_key == key:
            self._exit_home_focus(key)
        elif self.home_focus_key is not None:
            self._exit_home_focus(self.home_focus_key, immediate=True)
            self._enter_home_focus(key)
        else:
            self._enter_home_focus(key)

    def _enter_home_focus(self, key: str) -> None:
        keys = tuple(self.home_cards.keys())
        layer = self.home_focus_layer
        layer.setGeometry(self.home_area.rect())
        focused_rect, others_rects = self._home_focus_geometry(
            key, self.home_area.rect()
        )
        self._home_focus_to_grid = {}
        for k in keys:
            card = self.home_cards[k]
            self._home_focus_to_grid[k] = card.geometry()
            scroll = self.home_card_scrolls.get(k)
            if scroll is not None:
                scroll.setVerticalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                    if k == key
                    else Qt.ScrollBarPolicy.ScrollBarAsNeeded
                )
            card.setParent(layer)
            card.show()
        self.home_focus_key = key
        layer.show()
        layer.raise_()
        for k in keys:
            card = self.home_cards[k]
            start = self._home_focus_to_grid.get(k, card.geometry())
            target = focused_rect if k == key else others_rects[k]
            self._animate_card_geometry_once(card, start, target)

    def _exit_home_focus(self, key: str, immediate: bool = False) -> None:
        if immediate:
            self._restore_after_home_focus(key)
            return
        card = self.home_cards[key]
        start = card.geometry()
        end = self._home_focus_to_grid.get(key, start)
        self._animate_card_geometry_once(
            card, start, end, lambda: self._restore_after_home_focus(key)
        )
        self.home_focus_key = None

    def _restore_after_home_focus(self, key: str) -> None:
        self.home_focus_layer.hide()
        for scroll in self.home_card_scrolls.values():
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for k, card in self.home_cards.items():
            card.setParent(self.home_area)
            self._home_grid.addWidget(card, *self.home_card_pos[k])
            card.show()
        self.home_focus_key = None

    def _home_focus_geometry(self, key: str, rect: QRect):
        keys = tuple(self.home_cards.keys())
        others = [k for k in keys if k != key]
        big = QRect(0, 0, int(rect.width() * 0.62), rect.height())
        side = QRect(
            int(rect.width() * 0.62), 0, int(rect.width() * 0.38), rect.height()
        )
        count = max(1, len(others))
        cell_h = side.height() // count
        others_rects = {}
        for index, other in enumerate(others):
            others_rects[other] = QRect(
                side.x() + 8,
                side.y() + 8 + index * cell_h,
                max(60, side.width() - 16),
                max(60, cell_h - 16),
            )
        return big, others_rects

    def _apply_motion_settings(self) -> None:
        self.motion_capture.set_camera_index(int(self.motion_settings.get("camera_index", 0)))
        self.motion_capture.set_mirror(bool(self.motion_settings.get("mirror", True)))
        self.motion_capture.set_lr_mirror(bool(self.motion_settings.get("lr_mirror", False)))
        self.motion_capture.set_sensitivity(float(self.motion_settings.get("sensitivity", 1.0)))
        self.motion_capture.set_drive_enabled(bool(self.motion_settings.get("drive_enabled", True)))
        self.motion_capture.set_hand_enabled(bool(self.motion_settings.get("hand_enabled", True)))
        self.motion_capture.set_gesture_enabled(
            bool(self.motion_settings.get("gesture_enabled", True))
        )
        self.motion_capture.set_hand_stride(int(self.motion_settings.get("hand_every", 1)))

    def _save_motion_settings(self) -> None:
        self.settings_store.save_motion(self.motion_settings)

    def _on_motion_camera_changed(self, index: int) -> None:
        camera_index = self.motion_camera_combo.currentData()
        if camera_index is None:
            return
        self.motion_settings["camera_index"] = int(camera_index)
        self.motion_capture.set_camera_index(int(camera_index))
        self._save_motion_settings()
        self._sync_camera_combos()

    def _on_home_motion_camera_changed(self, index: int) -> None:
        combo = getattr(self, "home_motion_camera_combo", None)
        if combo is None:
            return
        camera_index = combo.currentData()
        if camera_index is None:
            return
        self.motion_settings["camera_index"] = int(camera_index)
        self.motion_capture.set_camera_index(int(camera_index))
        self._save_motion_settings()
        self._sync_camera_combos()

    def _populate_camera_combo(self, combo, devices: list | None = None) -> None:
        """填充摄像头设备下拉，并选中已保存的设备。"""
        if combo is None:
            return
        saved = int(self.motion_settings.get("camera_index", 0))
        if devices is None:
            devices = getattr(self, "_camera_devices", None) or [
                (saved, "点击「刷新」扫描摄像头")
            ]
        combo.blockSignals(True)
        combo.clear()
        for index, label in devices:
            combo.addItem(str(label), int(index))
        if combo.count() == 0:
            combo.addItem("点击「刷新」扫描摄像头", saved)
        target = combo.findData(saved)
        combo.setCurrentIndex(target if target >= 0 else 0)
        combo.blockSignals(False)

    def _refresh_camera_devices(self, force: bool = False) -> None:
        """刷新摄像头列表。

        默认只读取已保存的列表，不会打开摄像头；只有点击“刷新”
        （``force=True``）时才真正探测一次并保存结果。
        """
        if not force:
            saved = self.system_settings.get("camera_devices")
            devices: list = []
            if isinstance(saved, list):
                for item in saved:
                    try:
                        devices.append((int(item[0]), str(item[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
            if devices:
                self._on_camera_devices_loaded(devices, persist=False)
            return

        def worker() -> None:
            try:
                devices = list_camera_devices(force=True)
            except Exception:
                devices = []
            self.camera_devices_loaded.emit(devices, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_camera_devices_loaded(self, devices: list, persist: bool = False) -> None:
        if getattr(self, "_closing", False):
            return
        self._camera_devices = list(devices)
        self._populate_camera_combo(getattr(self, "motion_camera_combo", None), devices)
        self._populate_camera_combo(getattr(self, "cfg_camera_combo", None), devices)
        self._populate_camera_combo(
            getattr(self, "home_motion_camera_combo", None), devices
        )
        if persist and devices:
            self.system_settings["camera_devices"] = [
                [int(index), str(name)] for index, name in devices
            ]
            self._save_system_settings()

    def _sync_camera_combos(self) -> None:
        """按当前 camera_index 同步两处摄像头下拉的选中项。"""
        saved = int(self.motion_settings.get("camera_index", 0))
        for combo in (
            getattr(self, "motion_camera_combo", None),
            getattr(self, "cfg_camera_combo", None),
            getattr(self, "home_motion_camera_combo", None),
        ):
            if combo is None:
                continue
            target = combo.findData(saved)
            if target >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(target)
                combo.blockSignals(False)

    def _on_motion_mirror_changed(self, checked: bool) -> None:
        self.motion_settings["mirror"] = checked
        self.motion_capture.set_mirror(checked)
        self._save_motion_settings()

    def _on_motion_lr_mirror_changed(self, checked: bool) -> None:
        self.motion_settings["lr_mirror"] = checked
        self.motion_capture.set_lr_mirror(checked)
        self._save_motion_settings()

    def _on_motion_sensitivity_changed(self, value: float) -> None:
        self.motion_settings["sensitivity"] = value
        self.motion_capture.set_sensitivity(value)
        self._save_motion_settings()

    def _on_motion_drive_toggle(self, checked: bool) -> None:
        self.motion_settings["drive_enabled"] = checked
        self.motion_capture.set_drive_enabled(checked)
        self._save_motion_settings()
        if not checked and getattr(self, "live2d_view", None) is not None:
            self.live2d_view.reset_drive()

    # ------------------------------------------------------------------
    # 手部驱动与手势触发
    # ------------------------------------------------------------------

    def _on_hand_enabled_changed(self, checked: bool) -> None:
        self.motion_settings["hand_enabled"] = bool(checked)
        self.motion_capture.set_hand_enabled(bool(checked))
        self._save_motion_settings()
        self._refresh_gesture_ui()

    def _on_gesture_enabled_changed(self, checked: bool) -> None:
        self.motion_settings["gesture_enabled"] = bool(checked)
        self.motion_capture.set_gesture_enabled(bool(checked))
        self._save_motion_settings()
        self._refresh_gesture_ui()

    def _on_hand_stride_changed(self) -> None:
        """手部检测抽帧间隔：越小越跟手，越大越省算力。"""
        combo = getattr(self, "hand_stride_combo", None)
        if combo is None:
            return
        stride = int(combo.currentData() or 1)
        self.motion_settings["hand_every"] = stride
        self.motion_capture.set_hand_stride(stride)
        self._save_motion_settings()

    def _on_gesture_action_changed(self, gesture: str, combo) -> None:
        action = combo.currentData() or model_actions.ACTION_NONE
        self._set_row_action(gesture, action)

    # ------------------------------------------------------------------
    # 手势列表：每个模型各一套（默认手势可删，可加自定义姿势手势）
    # ------------------------------------------------------------------

    def _current_model_key(self) -> str:
        """当前手势配置挂在哪个模型名下（``live2d:hiyori_pro`` 这样的键）。

        优先用「已启用」的那个模型；还没有启用的就用列表里第一个同类型模型
        ——用户刚导入还没点「使用」时也得能配手势，否则录下来的自定义手势
        无处可存。一个模型都没有时退回公共档 ``__default__``。
        """
        kind = self._current_avatar_kind()
        entries = [entry for entry in getattr(self, "model_entries", []) if entry.kind == kind]
        active = next((entry for entry in entries if entry.active), None)
        entry = active or (entries[0] if entries else None)
        if entry is None:
            return pose_gesture.FALLBACK_PROFILE_KEY
        key = pose_gesture.model_key(kind, entry.name)
        return key or pose_gesture.FALLBACK_PROFILE_KEY

    def _gesture_rows(self) -> list[dict]:
        """当前模型的手势行（列表界面的唯一数据源）。

        三条来源，优先级从高到低：

        1. 当前模型自己那份配置（用户删过默认手势、加过自定义手势，以它为准）；
        2. 公共档 ``__default__``（还没绑定到具体模型时录的手势）；
        3. 内置的七条默认手势（动作从老字段 ``gesture_actions`` 迁移过来）。
        """
        profiles = getattr(self, "gesture_profiles", None)
        key = self._current_model_key()
        actions = getattr(self, "gesture_actions", None) or {}
        rows = pose_gesture.rows_for(profiles, key, actions)
        if rows:
            rows = [dict(row) for row in rows]
            # 默认手势的动作以 ``gesture_actions`` 为准：它是默认手势动作的镜像
            # （每次落盘都会同步），也是模型未加载时的兜底。两边万一不同步
            # （老配置、外部改过），以这份老字段为准，免得用户觉得配置丢了。
            for row in rows:
                if str(row.get("kind") or "builtin") != "builtin":
                    continue
                gesture_id = str(row.get("id"))
                if gesture_id in actions:
                    row["action"] = str(actions[gesture_id] or model_actions.ACTION_NONE)
            return rows
        # 空列表是「用户把默认手势全删了」的明确意图，只有真的没配过才用兜底
        if isinstance(profiles, dict) and key in profiles:
            return []
        combos = getattr(self, "gesture_combos", None)
        if combos:
            # 自检 / 老代码里手工塞过下拉框：以那些键为准造行，别把它们丢掉
            return self._rows_from_keys(list(combos.keys()), actions)
        return pose_gesture.default_rows(actions)

    def _rows_from_keys(self, keys: list[str], actions: dict) -> list[dict]:
        """按给定的手势 id 列表造行（顺序先按内置顺序，多余的排后面）。"""
        ordered = [key for key in pose_gesture.BUILTIN_GESTURE_ORDER if key in keys]
        ordered += [key for key in keys if key not in ordered]
        rows: list[dict] = []
        for key in ordered:
            rows.append({
                "id": key,
                "name": GESTURE_NAMES.get(key, key),
                "kind": "builtin",
                "pose": None,
                "tolerance": pose_gesture.DEFAULT_TOLERANCE,
                "action": str(actions.get(key, model_actions.ACTION_NONE) or "none"),
            })
        return rows

    def _action_for_gesture(self, gesture_id: str) -> str:
        """取某个手势此刻绑定的动作。

        规则和 :meth:`_gesture_rows` 对齐：

        * 自定义手势只有手势行里存着它，直接读行；
        * 默认手势的动作以 ``gesture_actions`` 为准（模型未加载时的兜底；
          用户把某条默认手势从列表里删了，就不在这里了 —— 返回「不响应」，
          **这样「删掉默认手势」才是真的删掉**，否则手一比划还会触发）。
        """
        row = None
        for item in getattr(self, "_gesture_rows_cache", []) or []:
            if item.get("id") == gesture_id:
                row = item
                break
        if row is not None and str(row.get("kind") or "builtin") == "custom":
            return str(row.get("action") or model_actions.ACTION_NONE)
        actions = getattr(self, "gesture_actions", None) or {}
        if row is not None:
            return str(actions.get(gesture_id, row.get("action"))
                       or model_actions.ACTION_NONE)
        if getattr(self, "_gesture_rows_cache", None):
            # 列表是加载过的，里面没有它 = 用户删掉了这条手势
            return model_actions.ACTION_NONE
        return str(actions.get(gesture_id, model_actions.ACTION_NONE))

    def _gesture_display_name(self, gesture_id: str) -> str:
        for row in getattr(self, "_gesture_rows_cache", []) or []:
            if row.get("id") == gesture_id:
                return str(row.get("name") or gesture_id)
        return GESTURE_NAMES.get(gesture_id, gesture_id)

    def _set_row_action(self, gesture_id: str, action: str) -> None:
        """改某条手势绑定的动作并落盘。"""
        for row in getattr(self, "_gesture_rows_cache", []) or []:
            if row.get("id") == gesture_id:
                row["action"] = str(action or model_actions.ACTION_NONE)
                break
        self._persist_gesture_rows()

    def _persist_gesture_rows(self, rebuild: bool = False) -> None:
        """把手势行写进「当前模型」那份配置，并同步旧字段 ``gesture_actions``。

        ``gesture_actions`` 只保留默认手势那部分，作用是给「模型还没加载出来」
        的时刻兜底（那时没有模型能力可言，只能照搬上次的动作）。
        """
        rows = getattr(self, "_gesture_rows_cache", None)
        if rows is None:
            return
        key = self._current_model_key()
        profiles = pose_gesture.set_rows(getattr(self, "gesture_profiles", None), key, rows)
        self.gesture_profiles = profiles
        self.motion_settings["gesture_profiles"] = profiles
        # 默认手势的动作镜像回老字段：模型还没加载出来的时候没有能力清单可查，
        # 只能照搬这份映射。**整份替换**而不是 update——被删掉的那条默认手势
        # 必须从映射里消失，否则手一比划又会触发它。
        builtin = pose_gesture.builtin_actions(rows)
        self.gesture_actions = {
            name: str(builtin.get(name, model_actions.ACTION_NONE) or model_actions.ACTION_NONE)
            for name in pose_gesture.BUILTIN_GESTURE_ORDER
        }
        self.motion_settings["gesture_actions"] = dict(self.gesture_actions)
        self._sync_pose_gestures()
        self._save_motion_settings()
        if rebuild:
            self._rebuild_gesture_menus()

    def _sync_pose_gestures(self) -> None:
        """把自定义姿势手势模板推给动捕线程（只有带 pose 的才会参与匹配）。"""
        capture = getattr(self, "motion_capture", None)
        setter = getattr(capture, "set_pose_gestures", None)
        if setter is None:
            return
        try:
            setter([row for row in getattr(self, "_gesture_rows_cache", []) or []
                    if row.get("pose")])
        except Exception:
            pass

    def _hand_shape_text(self, pose: dict) -> str:
        """录制弹窗里的「手型」一行：这一帧识别到的手型 + 逐指弯曲度。

        「做的是单指、界面却抓到握拳」这种问题没法靠看画面判断（到底是手指
        没被读到，还是判据把它认成握拳了），所以把三样原始数据都打出来：

        * 识别出的手型名——:meth:`MotionCapture.current_hand_shapes`（**这一帧**
          的结果，不是去抖后的触发状态）；
        * 逐指弯曲度——这一帧的姿势快照（0 = 伸直、1 = 握起）；
        * 弯曲度是**从哪种坐标**算出来的——``current_hand_geometry``。写着
          「二维像素」就说明 MediaPipe 这一帧没给世界坐标、退回了投影，读数是
          被压扁的（伸直的食指会读成弯曲），那要先解决数据源而不是调判据。
        """
        shapes: dict = {}
        sources: dict = {}
        capture = getattr(self, "motion_capture", None)
        getter = getattr(capture, "current_hand_shapes", None)
        if getter is not None:
            try:
                shapes = dict(getter() or {})
            except Exception:
                shapes = {}
        source_getter = getattr(capture, "current_hand_geometry", None)
        if source_getter is not None:
            try:
                sources = dict(source_getter() or {})
            except Exception:
                sources = {}
        parts: list[str] = []
        for side, who in (("l", "左手"), ("r", "右手")):
            # pose 来自 pose_gesture.capture()，值一定是 float
            curls = [float(pose.get(f"finger_{side}_{index}") or 0.0)
                     for index in range(5)]
            shape = shapes.get(side) or ""
            if not shape and max(curls) <= 1e-6:
                # 这一侧没手，也没识别到任何东西：不占版面
                continue
            label = GESTURE_NAMES.get(shape, "手型未识别") if shape else "手型未识别"
            detail = " ".join(f"{value:.2f}" for value in curls)
            source = sources.get(side)
            if source == "pixels":
                detail += "；二维像素（读数可能被压扁）"
            elif source == "world":
                detail += "；世界坐标"
            parts.append(f"{who} {label}（食/中/无名/小/拇 {detail}）")
        if not parts:
            return "没读到手指弯曲度（手可能没进画面）"
        return "；".join(parts)

    def _on_record_pose_gesture(self) -> None:
        """录制自定义手势：抓当前动捕姿势 -> 起名 -> 存进当前模型的配置。"""
        capture = getattr(self, "motion_capture", None)
        if capture is None:
            return
        if not capture.is_running():
            show_warning(self, "星弦", "请先点「开始动捕」，把手摆成想要的姿势，再录制手势。")
            return
        if not capture.hand_detected():
            show_warning(self, "星弦", "画面里没有检测到手部，请把手放进画面再录制。")
            return
        current = capture.current_pose()
        if pose_gesture.is_blank(current):
            show_warning(self, "星弦", "这一帧没有读到手臂姿势，请把手抬起来一点再录。")
            return

        rows = self._gesture_rows()
        custom_count = sum(1 for row in rows if row.get("kind") == "custom")
        dialog = PoseGestureDialog(
            self, current, pose_gesture.summarize(current), f"我的手势 {custom_count + 1}",
            self._hand_shape_text(current),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.result_payload()
        entry = pose_gesture.make_custom_gesture(
            payload["name"], current, existing_ids=[row.get("id") for row in rows],
            tolerance=payload["tolerance"],
        )
        rows.append(entry)
        self._gesture_rows_cache = rows
        self._persist_gesture_rows(rebuild=True)

    def _on_reset_gesture_rows(self) -> None:
        """把内置的七条默认手势补回列表。

        只**补缺失的**，已经在列表里的保持原样（用户改过的动作不会被冲掉），
        自定义手势也全部保留——「恢复默认」不该顺手删掉用户自己录的东西，
        要删有每行末尾的「×」。
        """
        rows = self._gesture_rows()
        existing = {str(row.get("id")): row for row in rows}
        defaults = {
            row["id"]: row for row in pose_gesture.default_rows(self.gesture_actions)
        }
        merged: list[dict] = []
        for key in pose_gesture.BUILTIN_GESTURE_ORDER:
            merged.append(existing.get(key) or defaults[key])
        merged += [
            row for row in rows
            if str(row.get("id")) not in pose_gesture.BUILTIN_GESTURE_ORDER
        ]
        self._gesture_rows_cache = merged
        self._persist_gesture_rows(rebuild=True)

    def _delete_gesture_row(self, gesture_id: str, ask: bool = True) -> None:
        """删掉一条手势（默认手势也能删）。

        自定义手势删掉后姿势模板就没了，所以默认弹一次确认；自检里传
        ``ask=False`` 直接删，免得要模拟点击。
        """
        rows = [row for row in self._gesture_rows() if row.get("id") != gesture_id]
        if len(rows) == len(self._gesture_rows()):
            return
        target = next(
            (row for row in self._gesture_rows() if row.get("id") == gesture_id), None
        )
        if ask and target is not None and target.get("kind") == "custom":
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("删除自定义手势")
            box.setText(f"删除「{target.get('name')}」？录下来的姿势模板会一起丢掉。")
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return
        self._gesture_rows_cache = rows
        self._persist_gesture_rows(rebuild=True)

    def _on_delete_gesture_row(self, gesture_id: str) -> None:
        self._delete_gesture_row(gesture_id, ask=True)

    def _on_pose_gesture_changed(self, gesture_id: str) -> None:
        """动捕线程确认某个自定义姿势手势成立（或解除）时触发动作。"""
        if not gesture_id:
            self._pose_gesture_state["id"] = ""
            self._refresh_gesture_status()
            return
        if gesture_id == self._pose_gesture_state.get("id"):
            return
        self._pose_gesture_state["id"] = gesture_id
        self._refresh_gesture_status()
        self._trigger_gesture_action(self._action_for_gesture(gesture_id))

    def _available_actions(self, view=None) -> list[tuple[str, str]]:
        """当前模型支持的动作 / 表情菜单项，``[(动作 id, 显示名), ...]``。"""
        view = view if view is not None else self._active_model_view()
        menu: list[tuple[str, str]] = []
        getter = getattr(view, "available_actions", None)
        if getter is not None:
            try:
                menu = [(str(a), str(l)) for a, l in getter()]
            except Exception:
                menu = []
        if not menu or menu[0][0] != model_actions.ACTION_NONE:
            menu.insert(0, (model_actions.ACTION_NONE, "不响应"))
        return menu

    @staticmethod
    def _capabilities_from_menu(menu) -> model_actions.ModelCapabilities:
        """从菜单项反推能力清单。

        直接由菜单反推而不是另外问一次模型，能保证「菜单里有的」和
        「能解析的」永远一致——否则会出现下拉框列着某动作、选中却解析失败。
        """
        caps = model_actions.ModelCapabilities()
        for action, _label in menu:
            kind, name = model_actions.split_action(action)
            if not isinstance(name, str):
                continue
            if kind == "motion":
                caps.motions.append(name)
            elif kind == "expression":
                caps.expressions.append(name)
        return caps

    def _resolve_row_action(self, row: dict, caps, defaults: dict) -> str:
        """把一条手势行绑的动作落到当前模型的真名上。

        解析不出来时：默认手势换成按模型能力推导的默认动作（用户看到一个
        能用的动作总比点了没反应强），自定义手势退回「不响应」——它是个新
        概念，没有可以推导的历史默认值。
        """
        current = str(row.get("action") or model_actions.ACTION_NONE)
        is_builtin = str(row.get("kind") or "builtin") == "builtin"
        if current == model_actions.ACTION_NONE:
            # 用户显式选的「不响应」是一种选择，不是失效
            return current
        resolved = model_actions.resolve_action(current, caps)
        if resolved is None:
            return defaults.get(row.get("id"), model_actions.ACTION_NONE) if is_builtin \
                else model_actions.ACTION_NONE
        # 解析得出来也要**规范化成前缀形式**：老配置里存的是 ``wave`` /
        # ``expression_smile``，而下拉框里的数据是 ``motion:wave``，不换写法
        # findData 会失配，界面就显示回「不响应」了——看着像没生效。
        kind, name = resolved
        prefix = (
            model_actions.PREFIX_MOTION
            if kind == "motion"
            else model_actions.PREFIX_EXPRESSION
        )
        return prefix + name

    def _sync_gesture_grid(self, rows: list[dict]) -> None:
        """按手势行重建网格控件；没有界面（自检里绕开 __init__）时自动跳过。"""
        grid = getattr(self, "gesture_grid", None)
        if grid is None:
            return
        for widgets in getattr(self, "_gesture_row_widgets", {}).values():
            for widget in widgets.values():
                # 必须先 removeWidget 再删：只调 setParent(None) 的话布局项还挂在
                # 网格里，重建几次就会在新行位置上叠出一堆看不见的旧行（格子越来
                # 越多、行距被撑开）。表头两个标签不在这里，所以不会被误删。
                grid.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
        self._gesture_row_widgets = {}
        self.gesture_combos = {}

        for index, row in enumerate(rows, start=1):
            gesture_id = str(row.get("id"))
            name = QLabel(self._gesture_row_label(row))
            name.setObjectName("hintText")
            if row.get("pose"):
                name.setToolTip("自定义姿势手势：" + pose_gesture.summarize(row["pose"]))
            grid.addWidget(name, index, 0)

            combo = ArrowComboBox()
            combo.setObjectName("inputBox")
            combo.currentIndexChanged.connect(
                lambda _=0, k=gesture_id, c=combo: self._on_gesture_action_changed(k, c)
            )
            grid.addWidget(combo, index, 1)
            self.gesture_combos[gesture_id] = combo

            # 专用紧凑样式：`ghostButton` 的样式表写死了 `min-width: 96px` /
            # `min-height: 32px`，而 Qt 里**样式表的 min-width 会盖过 setFixedWidth**，
            # 于是这个「×」被撑成一个 96×32 的大方块。换成 padding:0 / min-*:0 的
            # 专用 objectName，尺寸才真的听 setFixedSize 的。
            remove = QPushButton("×")
            remove.setObjectName("rowRemoveButton")
            remove.setFixedSize(24, 24)
            remove.setToolTip("删除这个手势")
            remove.clicked.connect(
                lambda _=0, k=gesture_id: self._on_delete_gesture_row(k)
            )
            # 垂直居中对齐：同行的下拉框比它高时，24px 的方按钮不该被顶到格子顶部
            grid.addWidget(remove, index, 2, Qt.AlignVCenter)
            self._gesture_row_widgets[gesture_id] = {
                "name": name, "combo": combo, "remove": remove,
            }

    @staticmethod
    def _gesture_row_label(row: dict) -> str:
        """行首显示什么：默认手势用中文名，自定义手势加个记号。"""
        name = str(row.get("name") or row.get("id"))
        if str(row.get("kind") or "builtin") == "custom":
            return f"{name}（自定义）"
        return GESTURE_NAMES.get(str(row.get("id")), name)

    def _rebuild_gesture_menus(self) -> None:
        """按当前模型重建手势列表与每一行的动作下拉框。

        这是「模型的手势动作，每个模型单独配置保存」的落点：列表内容（有哪些
        手势、默认的保留还是删掉、自定义的录了什么）和每行绑的动作都按模型
        各存一份；选项本身来自模型真正拥有的动作组和表情名。换模型时旧映射
        多半已经不存在了（Live2D 的表情叫「生气」「爱心」，VRM 叫 happy/angry，
        两套名字毫无交集），所以顺带把失效的选择回退成按新模型能力推导的
        默认动作，免得用户对着一个点了没反应的选项发呆。

        两条不能踩的线：

        * 用户显式选的「不响应」要保留——那是一种选择，不是失效；
        * **模型还没加载时绝不改写已存的映射**。构造界面时手上还没有模型，
          这时若把七个手势全刷成「不响应」，用户上次配好的映射就白丢了
          （等模型加载完会再重建一次，那时按真能力迁移才是有意义的）。
        """
        rows = self._gesture_rows()
        menu = self._available_actions()
        caps = self._capabilities_from_menu(menu)

        changed = False
        if not caps.is_empty():
            builtin_ids = [str(row.get("id")) for row in rows
                           if str(row.get("kind") or "builtin") == "builtin"]
            defaults = model_actions.default_actions(caps, tuple(builtin_ids))
            for row in rows:
                resolved = self._resolve_row_action(row, caps, defaults)
                if resolved != row.get("action"):
                    row["action"] = resolved
                    changed = True

        self._gesture_rows_cache = rows
        self._sync_gesture_grid(rows)
        # 先把迁移结果落盘再配下拉框：`_action_for_gesture` 对默认手势是查
        # `gesture_actions` 的（那是模型未加载时的兜底），这时它还是老的写死 id
        # （``wave``），而菜单里放的是 ``motion:wave``，不先同步就会 findData 失配、
        # 界面显示回「不响应」。
        if not caps.is_empty() and changed:
            self._persist_gesture_rows()
        for gesture_id, combo in self.gesture_combos.items():
            combo.blockSignals(True)
            combo.clear()
            for action, label in menu:
                combo.addItem(label, action)
            index = combo.findData(self._action_for_gesture(gesture_id))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        self._gesture_menu_model = [action for action, _ in menu]
        # 自定义手势模板要立刻推给动捕线程，否则刚录的手势要等下次开动捕才生效
        self._sync_pose_gestures()
        hint = getattr(self, "gesture_menu_hint", None)
        if hint is not None:
            hint.setText(self._gesture_menu_hint())

    def _gesture_menu_hint(self) -> str:
        """给手势那一栏的副标题，说明当前选项是从哪来的。"""
        rows = getattr(self, "_gesture_rows_cache", []) or []
        custom = [row for row in rows if row.get("kind") == "custom"]
        pose_note = f"，{len(custom)} 个自定义手势（按姿势自动触发）" if custom else ""
        if not rows:
            return "手势列表是空的，点「＋ 录制自定义手势」或「恢复默认手势」开始配置"
        view = self._active_model_view()
        if view is None:
            return f"共 {len(rows)} 个手势{pose_note}；尚未加载模型，暂无可触发的动作"
        caps = self._capabilities_from_menu(self._available_actions())
        if caps.is_empty():
            return f"共 {len(rows)} 个手势{pose_note}；当前模型没有可用的动作 / 表情"
        return (
            f"共 {len(rows)} 个手势{pose_note}｜"
            f"当前模型支持 {len(caps.motions)} 个动作、{len(caps.expressions)} 个表情"
        )

    def _refresh_gesture_ui(self) -> None:
        """手势下拉只在「手部驱动 + 手势触发」都开着时可编辑。"""
        usable = bool(self.motion_settings.get("hand_enabled", True)) and bool(
            self.motion_settings.get("gesture_enabled", True)
        )
        for combo in getattr(self, "gesture_combos", {}).values():
            combo.setEnabled(usable)
        for button in (getattr(self, "gesture_record_button", None),
                       getattr(self, "gesture_reset_button", None)):
            if button is not None:
                button.setEnabled(usable)
        self._refresh_hands_status()

    def _pose_gesture_display_name(self) -> str:
        """当前命中的自定义姿势手势名（没有命中就是空串）。"""
        pose_id = (getattr(self, "_pose_gesture_state", None) or {}).get("id")
        return self._gesture_display_name(pose_id) if pose_id else ""

    def _hands_status_line(self) -> str:
        """「手部驱动」卡片里那一行状态文字该显示什么。

        **手势优先、手型垫底**：

        * 自定义姿势手势命中 -> ``手势：<你给它起的名字>``；
        * 内置手型已稳定触发 -> ``手势：左手 握拳``（内置那七种同样会触发动作）；
        * 都没触发 -> ``手型：左手 握拳`` / ``手部：未检测到``。

        以前这一行直接转动手型链路的原始文字（光写「左手 握拳」），于是做自定义
        手势时用户会以为系统把自己的手势认成了握拳——其实动作是对的，只是这行字
        报的是**另一条链路**（手型分类）的结论。现在两条链路各带名字，一眼分得清。
        """
        pose_name = self._pose_gesture_display_name()
        if pose_name:
            return f"手势：{pose_name}"
        builtin = str(getattr(self, "_gesture_active_label", "") or "")
        if builtin:
            return f"手势：{builtin}"
        raw = str(getattr(self, "_hand_status_text", "") or "")
        if not raw:
            return "手部：未检测到"
        if raw.startswith("手部："):
            return raw
        # 手在画面、但还没触发任何手势：这是手型识别的原始结果，标明「手型」，
        # 免得又被读成「系统认为你做的手势是握拳」。
        return f"手型：{raw}"

    def _refresh_hands_status(self) -> None:
        """重画「手部驱动」卡片里那一行状态（找不到识别模型时给的是安装提示）。"""
        label = getattr(self, "hands_status_label", None)
        if label is None:
            return
        capture = getattr(self, "motion_capture", None)
        getter = getattr(capture, "gesture_available", None)
        available = True
        if getter is not None:
            try:
                available = bool(getter())
            except Exception:
                available = True
        if not available:
            label.setText("未找到 hand_landmarker.task，手势识别不可用（放到 client-python/models/ 下）")
            return
        label.setText(self._hands_status_line())

    def _refresh_gesture_status(self) -> None:
        """刷新「识别手势」那一行：内置手型与自定义姿势手势各报各的。

        两条链路是独立的（手型和手臂姿势可以同时成立），所以这里两个都显示，
        用户能一眼看出到底是哪条在触发——调试自己的自定义手势时这是最关键的
        信息。
        """
        label = getattr(self, "gesture_value_label", None)
        if label is not None:
            parts: list[str] = []
            builtin = getattr(self, "_gesture_active_label", "")
            if builtin:
                parts.append(builtin)
            pose_name = self._pose_gesture_display_name()
            if pose_name:
                parts.append(f"手势：{pose_name}")
            label.setText("　".join(parts) if parts else "—")
        # 操作区那一行也跟着走：自定义手势命中 / 解除都要立刻反映出来
        self._refresh_hands_status()

    def _on_hands_status_changed(self, text: str) -> None:
        # 动捕线程给的只是**手型**链路的结论，先存下来，再由 :meth:`_hands_status_line`
        # 和自定义手势名合成后写进标签。
        self._hand_status_text = str(text or "")
        self._refresh_hands_status()

    def _on_gesture_changed(self, side: str, gesture: str) -> None:
        """某一侧手的手势变为稳定状态（或解除）时触发对应动作。"""
        who = "左手" if side == "l" else "右手"
        self._gesture_active_label = f"{who} {gesture_name(gesture)}" if gesture else ""
        self._refresh_gesture_status()
        if not gesture:
            return
        self._trigger_gesture_action(self._action_for_gesture(gesture))

    def _trigger_gesture_action(self, action: str | None) -> None:
        """执行手势绑定的动作。

        动作 id 由菜单给出（``motion:<真名>`` / ``expression:<真名>``），触发时
        直接拿这个名字去调模型，不再靠候选名猜测；老配置里写死的
        ``wave`` / ``expression_smile`` 也仍然解析得了（见 ``split_action``）。
        """
        if not action or action == model_actions.ACTION_NONE:
            return
        view = self._active_model_view()
        if view is None:
            return
        caps = self._capabilities_from_menu(self._available_actions())
        resolved = model_actions.resolve_action(action, caps)
        if resolved is None:
            return
        kind, name = resolved
        if kind == "expression":
            self._set_model_expression(name)
            return
        try:
            view.play_motion(name)
        except Exception:
            pass

    def _set_model_expression(self, name: str) -> None:
        """设置表情，几秒后自动复原；模型没有该表情时退化为播放动作。"""
        view = self._active_model_view()
        setter = getattr(view, "set_expression", None)
        if view is None or setter is None:
            return
        ok = False
        try:
            ok = bool(setter(name))
        except Exception:
            ok = False
        if not ok:
            # 表情真设不上（模型没这个表情）就退一步播个动作，
            # 总比手势过去了模型一动不动强。
            caps = self._capabilities_from_menu(self._available_actions())
            if caps.motions:
                try:
                    view.play_motion(caps.motions[0])
                except Exception:
                    pass
            return
        self._gesture_expression["kind"] = name
        timer = getattr(self, "_gesture_expression_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._clear_model_expression)
            self._gesture_expression_timer = timer
        timer.start(3000)

    def _clear_model_expression(self) -> None:
        self._gesture_expression["kind"] = ""
        view = self._active_model_view()
        if view is not None and hasattr(view, "clear_expression"):
            try:
                view.clear_expression()
            except Exception:
                pass

    def _on_motion_start(self) -> None:
        self._apply_motion_settings()
        self._avatar_running_before_capture = getattr(self, "_avatar_running", False)
        if self.motion_capture.start():
            self._motion_running = True
            self._reset_motion_preview("正在启动摄像头…")
            home_stack = getattr(self, "home_motion_stack", None)
            if home_stack is not None:
                home_stack.setCurrentIndex(1)
            self.motion_status.setText("动捕运行中")
            # 动捕期间让头像保持显示并可被驱动；若此前未启动，结束后回退
            self._avatar_running = True
            model_type = self._current_avatar_kind()
            if model_type in ("live2d", "vrm"):
                self._refresh_model_list(model_type)
            self._sync_preview_views()
            if getattr(self, "live2d_view", None) is not None:
                self.live2d_view.set_auto_features(blink=False, breath=True)
                self.live2d_view.stop_motions()
            # 放在 _avatar_running 置位**之后**：四个入口（含虚拟形象页）要一起重画
            self._refresh_runtime_controls()

    def _on_motion_stop(self) -> None:
        self.motion_capture.stop()
        self._motion_running = False
        home_stack = getattr(self, "home_motion_stack", None)
        if home_stack is not None:
            home_stack.setCurrentIndex(0)
        self._reset_motion_preview()
        self.motion_status.setText("动捕已停止")
        # 若动捕前模型未启动，则停止后回退到未启动状态
        if not getattr(self, "_avatar_running_before_capture", False):
            self._avatar_running = False
            self._sync_live2d_views()
        self._sync_preview_views()
        if getattr(self, "live2d_view", None) is not None:
            self.live2d_view.set_auto_features(blink=True, breath=True)
            self.live2d_view.reset_drive()
            self.live2d_view.start_idle()
        self._refresh_runtime_controls()

    def _refresh_runtime_controls(self) -> None:
        """把「动捕 / 形象」的启停入口按当前状态**整体重画**一遍。

        同一件事在**四个地方**都有入口，每个入口还各有自己的开始/停止按钮、
        状态文字和两态容器：

        * 视频动捕页：``motion_start_button`` / ``motion_stop_button``
        * 首页「动捕控制」卡：``home_motion_start_button`` / ``home_motion_stop_button``
        * 首页「虚拟形象预览」：``home_preview_start_button`` / ``home_preview_stop_button``
          —— 这两者靠 ``home_preview_stack`` 在「模型列表」与「画面」之间切换
        * 虚拟形象页：``avatar_start_button`` / ``avatar_stop_button``

        以前是**谁触发谁只改自己那一处**，于是「在动捕页开始动捕、切到虚拟形象页，
        按钮还停留在『启动』」——模型其实已经在跑了（``_avatar_running`` 早就是
        True），只是那几行字没人负责更新。现在统一按 ``_motion_running`` /
        ``_avatar_running`` 两个标志重画，**任何一处改了标志都调它**，切页时也调。

        状态文字各自带模型名（「已启动：XXX」），不适合在这里统一，仍由各自的
        方法写；这里只管按钮显隐、两态容器和列表里的「[使用中]」。
        """
        motion_running = bool(getattr(self, "_motion_running", False))
        avatar_running = bool(getattr(self, "_avatar_running", False))

        for start_attr, stop_attr in (
            ("motion_start_button", "motion_stop_button"),
            ("home_motion_start_button", "home_motion_stop_button"),
        ):
            start = getattr(self, start_attr, None)
            if start is not None:
                start.setVisible(not motion_running)
            stop = getattr(self, stop_attr, None)
            if stop is not None:
                stop.setVisible(motion_running)

        avatar_start = getattr(self, "avatar_start_button", None)
        if avatar_start is not None:
            avatar_start.setVisible(not avatar_running)
        avatar_stop = getattr(self, "avatar_stop_button", None)
        if avatar_stop is not None:
            avatar_stop.setVisible(avatar_running)

        # 首页形象预览：未启动看模型列表（含「启动预览」），启动后看画面（含「停止」）
        home_stack = getattr(self, "home_preview_stack", None)
        if home_stack is not None:
            home_stack.setCurrentIndex(1 if avatar_running else 0)

        # 模型列表里的「[使用中]」同样吃 _avatar_running，不刷它就一直不出现
        for refresh in (self._refresh_avatar_model_list, self._refresh_home_model_list):
            try:
                refresh()
            except Exception:
                # 页面还没建好 / 自检里只搭了部分属性，刷新不到就跳过
                pass

    def _on_motion_frame(self, image) -> None:
        if not getattr(self, "_motion_running", False):
            return
        source = QPixmap.fromImage(image)
        for label in (getattr(self, "motion_preview", None), getattr(self, "home_motion_preview", None)):
            if label is None:
                continue
            width = label.width()
            height = label.height()
            if width > 0 and height > 0:
                pixmap = source.scaled(
                    width,
                    height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                pixmap = source
            label.setPixmap(pixmap)

    def _reset_motion_preview(self, text: str = "动捕未开启") -> None:
        """清空上一帧画面，恢复为未开启提示。"""
        for attr in ("motion_preview", "home_motion_preview"):
            label = getattr(self, attr, None)
            if label is None:
                continue
            label.clear()
            label.setText(text)

    def _on_motion_drive(self, drive: dict) -> None:
        # 语音驱动口型启用时，嘴型以声音包络为准，覆盖摄像头给出的 jawOpen，
        # 否则「看画面」和「听声音」两路会互相打架。
        if self._voice_lipsync.is_enabled():
            mouth, form, _level = self._voice_lipsync.read()
            drive["mouth_open"] = mouth
            drive["mouth_form"] = form
        # 根据当前模型类型传递动捕数据
        model_type = self._current_avatar_kind()
        
        if model_type == "live2d":
            if getattr(self, "live2d_view", None) is not None:
                self.live2d_view.apply_drive(**drive)
            elif getattr(self, "avatar_live2d_view", None) is not None:
                self.avatar_live2d_view.apply_drive(**drive)
        elif model_type == "vrm":
            if getattr(self, "avatar_vrm_view", None) is not None:
                self.avatar_vrm_view.set_drive_params(**drive)
        
        for key, label in getattr(self, "motion_value_labels", {}).items():
            label.setText(f"{drive.get(key, 0.0):.1f}")

    def _on_motion_status(self, text: str) -> None:
        if getattr(self, "motion_status", None) is not None:
            self.motion_status.setText(text)
        if getattr(self, "home_motion_status", None) is not None:
            self.home_motion_status.setText(text)

    def cfg_camera_changed(self, index: int) -> None:
        camera_index = self.cfg_camera_combo.currentData()
        if camera_index is None:
            return
        self.motion_settings["camera_index"] = int(camera_index)
        self.motion_capture.set_camera_index(int(camera_index))
        self._save_motion_settings()
        self._sync_camera_combos()

    def cfg_engine_changed(self, index: int) -> None:
        engine = ("hybrid", "face", "yolo")[min(index, 2)]
        self.motion_settings["engine"] = engine
        self.motion_capture.set_engine(engine)
        self._save_motion_settings()

    def cfg_mirror_changed(self, checked: bool) -> None:
        self.motion_settings["mirror"] = checked
        self.motion_capture.set_mirror(checked)
        self._save_motion_settings()

    def cfg_sensitivity_changed(self, value: float) -> None:
        self.motion_settings["sensitivity"] = value
        self.motion_capture.set_sensitivity(value)
        self._save_motion_settings()

    def cfg_drive_changed(self, checked: bool) -> None:
        self.motion_settings["drive_enabled"] = checked
        self.motion_capture.set_drive_enabled(checked)
        self._save_motion_settings()
        if not checked and getattr(self, "live2d_view", None) is not None:
            self.live2d_view.reset_drive()

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str) -> None:
        for i in range(combo.count()):
            if combo.itemText(i) == text:
                combo.setCurrentIndex(i)
                return

    def cfg_scheme_name_changed(self, text: str) -> None:
        self.system_settings["scheme_name"] = text.strip()
        self._update_scheme_label()

    def cfg_resolution_changed(self, index: int) -> None:
        self.system_settings["video_resolution"] = self.cfg_resolution.currentText()
        self._save_system_settings()

    def cfg_fps_changed(self, value: int) -> None:
        self.system_settings["video_fps"] = value
        self._save_system_settings()

    def cfg_sample_rate_changed(self, index: int) -> None:
        self.system_settings["audio_sample_rate"] = self.cfg_sample_rate.currentText()
        self._save_system_settings()

    def cfg_audio_engine_changed(self, index: int) -> None:
        self.system_settings["audio_engine"] = self.cfg_audio_engine.currentText()
        self._save_system_settings()

    def _on_save_system_settings(self) -> None:
        name = self.cfg_scheme_name.text().strip()
        if not name:
            show_info(self, "星弦", "请输入配置方案名称")
            return
        self.system_settings["scheme_name"] = name
        self._save_system_settings()
        show_info(self, "星弦", f"已保存方案：{name}")

    def _save_system_settings(self) -> None:
        self._update_scheme_label()
        self.settings_store.save_system(self.system_settings)

    def _update_scheme_label(self) -> None:
        label = getattr(self, "scheme_label", None)
        if label is None:
            return
        name = self.system_settings.get("scheme_name") or "未命名方案"
        label.setText(f"配置：{name}")

    def _refresh_system_settings_view(self) -> None:
        if getattr(self, "cfg_scheme_name", None) is None:
            return
        self.cfg_scheme_name.setText(self.system_settings.get("scheme_name", "日常直播"))
        self._set_combo_text(
            self.cfg_resolution, self.system_settings.get("video_resolution", "1080P")
        )
        self.cfg_fps.setValue(int(self.system_settings.get("video_fps", 60)))
        self._set_combo_text(
            self.cfg_sample_rate, self.system_settings.get("audio_sample_rate", "48000 Hz")
        )
        self._set_combo_text(
            self.cfg_audio_engine, self.system_settings.get("audio_engine", "RVC")
        )

    def _start_server_monitor(self) -> None:
        if self.offline:
            self._on_server_status_changed(False, "离线模式")
            return
        self._check_server_async()
        self._server_timer = QTimer(self)
        self._server_timer.setInterval(15000)
        self._server_timer.timeout.connect(self._check_server_async)
        self._server_timer.start()

    def _check_server_async(self) -> None:
        def worker() -> None:
            connected, detail = check_server()
            self.server_status_changed.emit(connected, detail)

        threading.Thread(target=worker, daemon=True).start()

    def _on_server_status_changed(self, connected: bool, detail: str) -> None:
        if getattr(self, "_closing", False):
            return
        label = getattr(self, "server_status_label", None)
        if label is None:
            return
        if self.offline:
            label.setText("服务器：离线模式")
            label.setStyleSheet("color: #FFC36B; font-size: 12px;")
            return
        if connected:
            label.setText(f"服务器：{detail}")
            label.setStyleSheet("color: #7EE7FF; font-size: 12px;")
        else:
            label.setText("服务器：未连接")
            label.setStyleSheet("color: #FF7E7E; font-size: 12px;")

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 20, 24, 24)
        page_layout.setSpacing(0)

        self.home_area = QWidget()
        grid = QGridLayout(self.home_area)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        self._home_grid = grid
        self.home_focus_key = None
        self.home_cards: dict = {}
        self.home_card_scrolls: dict = {}
        self.home_card_pos = {
            "avatar": (0, 0, 2, 1),
            "motion": (0, 1, 1, 1),
            "rvc": (0, 2, 1, 1),
            "live": (1, 1, 1, 2),
        }

        avatar_card, avatar_box = self._make_home_card("虚拟形象预览", "avatar")
        self.home_cards["avatar"] = avatar_card

        # 模型类型 Tabs（替代下拉菜单）
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(self._form_label("模型类型"))
        self.home_type_tabs = QTabBar()
        self.home_type_tabs.setObjectName("avatarTypeTabs")
        self.home_type_tabs.addTab("Live2D")
        self.home_type_tabs.addTab("VRM")
        self.home_type_tabs.currentChanged.connect(self._on_home_type_changed)
        self.home_type_tabs.blockSignals(True)
        self.home_type_tabs.setCurrentIndex(0)
        self.home_type_tabs.blockSignals(False)
        type_row.addWidget(self.home_type_tabs)
        type_row.addStretch()
        avatar_box.addLayout(type_row)

        # 两态容器：未启动显示模型列表，启动后显示预览框
        self.home_preview_stack = QStackedWidget()

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        self.home_model_list = QListWidget()
        self.home_model_list.setObjectName("modelList")
        self.home_model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.home_model_list.currentItemChanged.connect(self._on_home_model_selected)
        list_layout.addWidget(self.home_model_list, 1)
        start_row = QHBoxLayout()
        start_row.addStretch()
        self.home_preview_start_button = QPushButton("启动预览")
        self.home_preview_start_button.setObjectName("actionButton")
        self.home_preview_start_button.clicked.connect(self._on_home_preview_start)
        start_row.addWidget(self.home_preview_start_button)
        start_row.addStretch()
        list_layout.addLayout(start_row)
        self.home_preview_stack.addWidget(list_page)

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)

        self.home_preview_holder = QFrame()
        self.home_preview_holder.setObjectName("stagePanel")
        holder_layout = QVBoxLayout(self.home_preview_holder)
        holder_layout.setContentsMargins(8, 8, 8, 8)
        holder_layout.setSpacing(0)
        self.live2d_view = Live2DView()
        self.live2d_view.model_loaded.connect(self._on_live2d_loaded)
        self.live2d_view.model_error.connect(self._on_live2d_error)
        holder_layout.addWidget(self.live2d_view, 1)
        preview_layout.addWidget(self.home_preview_holder, 1)

        # 左右标签切换模型
        switch_row = QHBoxLayout()
        switch_row.setSpacing(8)
        self.home_prev_button = QPushButton("‹")
        self.home_prev_button.setObjectName("smallGhostButton")
        self.home_prev_button.setFixedSize(40, 28)
        self.home_prev_button.clicked.connect(self._on_home_prev_model)
        switch_row.addWidget(self.home_prev_button)
        self.home_current_model_label = QLabel("--")
        self.home_current_model_label.setAlignment(Qt.AlignCenter)
        self.home_current_model_label.setObjectName("infoValue")
        switch_row.addWidget(self.home_current_model_label, 1)
        self.home_next_button = QPushButton("›")
        self.home_next_button.setObjectName("smallGhostButton")
        self.home_next_button.setFixedSize(40, 28)
        self.home_next_button.clicked.connect(self._on_home_next_model)
        switch_row.addWidget(self.home_next_button)
        preview_layout.addLayout(switch_row)

        stop_row = QHBoxLayout()
        stop_row.addStretch()
        self.home_preview_stop_button = QPushButton("停止")
        self.home_preview_stop_button.setObjectName("ghostButton")
        self.home_preview_stop_button.clicked.connect(self._on_home_preview_stop)
        stop_row.addWidget(self.home_preview_stop_button)
        stop_row.addStretch()
        preview_layout.addLayout(stop_row)

        self.home_preview_stack.addWidget(preview_page)
        self.home_preview_stack.setCurrentIndex(0)

        avatar_box.addWidget(self.home_preview_stack, 1)
        self.home_avatar_status = QLabel("")
        self.home_avatar_status.setObjectName("panelBody")
        avatar_box.addWidget(self.home_avatar_status)
        grid.addWidget(avatar_card, *self.home_card_pos["avatar"])

        camera_card, camera_box = self._make_home_card("动捕控制", "motion")
        self.home_cards["motion"] = camera_card

        self.home_motion_stack = QStackedWidget()

        motion_device_page = QWidget()
        motion_device_layout = QVBoxLayout(motion_device_page)
        motion_device_layout.setContentsMargins(0, 0, 0, 0)
        motion_device_layout.setSpacing(8)
        motion_device_layout.addWidget(self._form_label("摄像头设备"))
        self.home_motion_camera_combo = ArrowComboBox()
        self.home_motion_camera_combo.setObjectName("inputBox")
        self._configure_device_combo(self.home_motion_camera_combo, 160, 320)
        self.home_motion_camera_combo.currentIndexChanged.connect(
            self._on_home_motion_camera_changed
        )
        motion_device_layout.addWidget(self.home_motion_camera_combo)
        home_cam_refresh = QPushButton("刷新设备")
        home_cam_refresh.setObjectName("smallGhostButton")
        home_cam_refresh.clicked.connect(lambda: self._refresh_camera_devices(force=True))
        motion_device_layout.addWidget(home_cam_refresh)
        motion_device_layout.addStretch()
        self._populate_camera_combo(self.home_motion_camera_combo)
        self.home_motion_stack.addWidget(motion_device_page)

        motion_preview_page = QWidget()
        motion_preview_layout = QVBoxLayout(motion_preview_page)
        motion_preview_layout.setContentsMargins(0, 0, 0, 0)
        self.home_motion_preview = QLabel("动捕未开启")
        self.home_motion_preview.setAlignment(Qt.AlignCenter)
        self.home_motion_preview.setStyleSheet(
            "background-color: #0A142A; border: 1px solid #284064; border-radius: 8px; color: #A9C3E2;"
        )
        self.home_motion_preview.setMinimumSize(180, 110)
        self.home_motion_preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        motion_preview_layout.addWidget(self.home_motion_preview, 1)
        self.home_motion_stack.addWidget(motion_preview_page)
        self.home_motion_stack.setCurrentIndex(0)
        camera_box.addWidget(self.home_motion_stack, 1)

        self.home_motion_status = QLabel("设备：未连接")
        self.home_motion_status.setObjectName("panelBody")
        camera_box.addWidget(self.home_motion_status)
        motion_controls = QHBoxLayout()
        motion_controls.setSpacing(8)
        self.home_motion_start_button = QPushButton("开始动捕")
        self.home_motion_start_button.setObjectName("actionButton")
        self.home_motion_start_button.clicked.connect(self._on_motion_start)
        self.home_motion_stop_button = QPushButton("停止动捕")
        self.home_motion_stop_button.setObjectName("ghostButton")
        self.home_motion_stop_button.clicked.connect(self._on_motion_stop)
        self.home_motion_stop_button.hide()
        motion_controls.addWidget(self.home_motion_start_button)
        motion_controls.addWidget(self.home_motion_stop_button)
        camera_box.addLayout(motion_controls)
        grid.addWidget(camera_card, *self.home_card_pos["motion"])

        voice_card, voice_box = self._make_home_card("音频变声（RVC）", "rvc")
        self.home_cards["rvc"] = voice_card
        voice_box.addWidget(self._form_label("模型选择"))
        self.home_rvc_model_combo = ArrowComboBox()
        self.home_rvc_model_combo.setObjectName("inputBox")
        self.home_rvc_model_combo.setMaximumWidth(200)
        self.home_rvc_model_combo.currentIndexChanged.connect(self._on_home_rvc_model_changed)
        voice_box.addWidget(self.home_rvc_model_combo)

        self.home_rvc_stack = QStackedWidget()
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(8)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._form_label("输入设备"))
        self.home_rvc_input_device = ArrowComboBox()
        self.home_rvc_input_device.setObjectName("inputBox")
        self._configure_device_combo(self.home_rvc_input_device, 150, 260)
        self.home_rvc_input_device.currentIndexChanged.connect(self._on_home_rvc_input_changed)
        input_row.addWidget(self.home_rvc_input_device, 1)
        device_layout.addLayout(input_row)
        output_row = QHBoxLayout()
        output_row.setSpacing(8)
        output_row.addWidget(self._form_label("输出设备"))
        self.home_rvc_output_device = ArrowComboBox()
        self.home_rvc_output_device.setObjectName("inputBox")
        self._configure_device_combo(self.home_rvc_output_device, 150, 260)
        self.home_rvc_output_device.currentIndexChanged.connect(self._on_home_rvc_output_changed)
        output_row.addWidget(self.home_rvc_output_device, 1)
        device_layout.addLayout(output_row)
        refresh_row = QHBoxLayout()
        refresh_row.setSpacing(8)
        self.home_rvc_refresh_button = QPushButton("刷新设备")
        self.home_rvc_refresh_button.setObjectName("smallGhostButton")
        self.home_rvc_refresh_button.clicked.connect(self._refresh_rvc_devices_from_home)
        refresh_row.addWidget(self.home_rvc_refresh_button)
        refresh_row.addStretch()
        device_layout.addLayout(refresh_row)
        device_layout.addStretch()
        self.home_rvc_stack.addWidget(device_page)

        self.home_volume_meter = self._build_vertical_meter("home_rvc", compact=True)
        meter_page = QWidget()
        meter_layout = QVBoxLayout(meter_page)
        meter_layout.setContentsMargins(0, 0, 0, 0)
        meter_layout.addStretch(1)
        meter_layout.addWidget(self.home_volume_meter)
        meter_layout.addStretch(1)
        self.home_rvc_stack.addWidget(meter_page)
        self.home_rvc_stack.setCurrentIndex(0)
        voice_box.addWidget(self.home_rvc_stack)

        self.home_rvc_status = QLabel("当前模型：未选择")
        self.home_rvc_status.setObjectName("infoValue")
        voice_box.addWidget(self.home_rvc_status)
        rvc_controls = QHBoxLayout()
        rvc_controls.setSpacing(8)
        self.home_rvc_start_button = QPushButton("启动变声")
        self.home_rvc_start_button.setObjectName("actionButton")
        self.home_rvc_start_button.clicked.connect(
            lambda: self._on_rvc_start(self.home_rvc_model_combo)
        )
        self.home_rvc_stop_button = QPushButton("停止变声")
        self.home_rvc_stop_button.setObjectName("ghostButton")
        self.home_rvc_stop_button.clicked.connect(self._on_rvc_stop)
        self.home_rvc_stop_button.hide()
        rvc_controls.addWidget(self.home_rvc_start_button)
        rvc_controls.addWidget(self.home_rvc_stop_button)
        voice_box.addLayout(rvc_controls)
        voice_box.addStretch()
        grid.addWidget(voice_card, *self.home_card_pos["rvc"])

        live_card, live_box = self._make_home_card("直播输出（虚拟摄像头）", "live")
        self.home_cards["live"] = live_card

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(self._form_label("设备名称"))
        self.vcam_name_label = QLabel(VIRTUAL_CAMERA_NAME)
        self.vcam_name_label.setObjectName("infoValue")
        name_row.addWidget(self.vcam_name_label, 1)
        live_box.addLayout(name_row)

        video_row = QHBoxLayout()
        video_row.setSpacing(8)
        video_row.addWidget(self._form_label("分辨率"))
        self.vcam_resolution_combo = ArrowComboBox()
        self.vcam_resolution_combo.setObjectName("inputBox")
        self.vcam_resolution_combo.addItems(["1280 x 720", "1920 x 1080"])
        video_row.addWidget(self.vcam_resolution_combo, 1)
        video_row.addWidget(self._form_label("帧率"))
        self.vcam_fps_spin = ArrowSpinBox()
        self.vcam_fps_spin.setObjectName("inputBox")
        self.vcam_fps_spin.setRange(10, 60)
        self.vcam_fps_spin.setValue(30)
        video_row.addWidget(self.vcam_fps_spin, 1)
        live_box.addLayout(video_row)

        vcam_buttons = QHBoxLayout()
        vcam_buttons.setSpacing(8)
        self.vcam_start_button = QPushButton("启动虚拟摄像头")
        self.vcam_start_button.setObjectName("actionButton")
        self.vcam_start_button.clicked.connect(self._toggle_virtual_camera)
        self.vcam_install_button = QPushButton("安装/修复驱动")
        self.vcam_install_button.setObjectName("ghostButton")
        self.vcam_install_button.clicked.connect(self._install_virtual_camera_driver)
        vcam_buttons.addWidget(self.vcam_start_button)
        vcam_buttons.addWidget(self.vcam_install_button)
        vcam_buttons.addStretch()
        live_box.addLayout(vcam_buttons)

        self.vcam_key_toggle = QCheckBox("仅输出虚拟形象（透明背景，不带背景）")
        self.vcam_key_toggle.setObjectName("toggle")
        self.vcam_key_toggle.toggled.connect(self._on_vcam_key_toggled)
        live_box.addWidget(self.vcam_key_toggle)

        self.vcam_status = QLabel(
            f"启动后，在直播伴侣的摄像头列表里选择「{VIRTUAL_CAMERA_NAME}」即可；"
            "首次使用若列表里没有该设备，点“安装/修复驱动”。"
        )
        self.vcam_status.setObjectName("hintText")
        self.vcam_status.setWordWrap(True)
        live_box.addWidget(self.vcam_status)
        live_box.addStretch()
        grid.addWidget(live_card, *self.home_card_pos["live"])

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)

        self.home_focus_layer = QWidget(self.home_area)
        self.home_focus_layer.setStyleSheet("background-color: #0A1020;")
        self.home_focus_layer.setVisible(False)
        page_layout.addWidget(self.home_area, 1)

        self._refresh_home_model_list()
        self._refresh_home_rvc_model_list()
        self._refresh_home_rvc_devices()
        return page

    def _build_live2d_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title_label = QLabel("虚拟形象")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        self.avatar_status = QLabel("")
        self.avatar_status.setObjectName("panelBody")
        layout.addWidget(self.avatar_status)

        content = QHBoxLayout()
        content.setSpacing(14)

        stage = QFrame()
        stage.setObjectName("stagePanel")
        stage.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(16, 14, 16, 14)
        stage_layout.setSpacing(8)

        stage_title = QLabel("虚拟形象预览")
        stage_title.setObjectName("panelTitle")
        stage_layout.addWidget(stage_title)

        self.avatar_preview_holder = QFrame()
        self.avatar_preview_holder.setObjectName("stagePanel")
        avatar_holder_layout = QVBoxLayout(self.avatar_preview_holder)
        avatar_holder_layout.setContentsMargins(8, 8, 8, 8)
        avatar_holder_layout.setSpacing(0)
        
        # Live2D 视图
        self.avatar_live2d_view = Live2DView()
        self.avatar_live2d_view.model_loaded.connect(self._on_avatar_live2d_loaded)
        self.avatar_live2d_view.model_error.connect(self._on_avatar_live2d_error)
        avatar_holder_layout.addWidget(self.avatar_live2d_view, 1)
        self.avatar_live2d_view.hide()  # 始终隐藏，避免与共享 Live2D 视图叠显
        
        # VRM 视图
        self.avatar_vrm_view = VRMView()
        self.avatar_vrm_view.model_loaded.connect(self._on_avatar_vrm_loaded)
        self.avatar_vrm_view.model_error.connect(self._on_avatar_vrm_error)
        avatar_holder_layout.addWidget(self.avatar_vrm_view, 1)
        self.avatar_vrm_view.hide()  # 默认隐藏
        
        stage_layout.addWidget(self.avatar_preview_holder, 1)
        content.addWidget(stage, 2)

        picker = QFrame()
        picker.setObjectName("panel")
        picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(16, 14, 16, 14)
        picker_layout.setSpacing(10)

        picker_title = QLabel("模型选择")
        picker_title.setObjectName("panelTitle")
        picker_layout.addWidget(picker_title)
        
        # 模型类型切换器
        model_type_layout = QHBoxLayout()
        model_type_layout.setSpacing(8)
        self.avatar_type_tabs = QTabBar()
        self.avatar_type_tabs.setObjectName("avatarTypeTabs")
        self.avatar_type_tabs.addTab("Live2D")
        self.avatar_type_tabs.addTab("VRM")
        self.avatar_type_tabs.currentChanged.connect(self._on_avatar_model_type_changed)
        model_type_layout.addWidget(QLabel("模型类型："))
        model_type_layout.addWidget(self.avatar_type_tabs, 1)
        model_type_layout.addStretch()
        picker_layout.addLayout(model_type_layout)

        self.avatar_model_combo = QComboBox()
        self.avatar_model_combo.setObjectName("inputBox")
        picker_layout.addWidget(self.avatar_model_combo)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.avatar_start_button = QPushButton("启动")
        self.avatar_start_button.setObjectName("actionButton")
        self.avatar_start_button.clicked.connect(lambda _=False: self._start_avatar())
        self.avatar_stop_button = QPushButton("停止")
        self.avatar_stop_button.setObjectName("actionButton")
        self.avatar_stop_button.clicked.connect(lambda _=False: self._stop_avatar())
        self.avatar_stop_button.hide()  # 未启动时只显示“启动”
        reload_button = QPushButton("重新加载")
        reload_button.setObjectName("actionButton")
        reload_button.clicked.connect(lambda _=False: self._reload_live2d())
        buttons.addWidget(self.avatar_start_button)
        buttons.addWidget(self.avatar_stop_button)
        buttons.addWidget(reload_button)
        buttons.addStretch()
        picker_layout.addLayout(buttons)
        content.addLayout(self._build_live2d_right_column(picker))

        layout.addLayout(content, 1)

        self._refresh_live2d_page()
        return page

    def _build_live2d_right_column(self, picker: QFrame) -> QVBoxLayout:
        right_column = QVBoxLayout()
        right_column.setSpacing(14)
        right_column.addWidget(picker)
        self.drive_params_card_holder = QWidget()
        holder_layout = QVBoxLayout(self.drive_params_card_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)
        holder_layout.addWidget(self._build_drive_params_card(), 1)
        right_column.addWidget(self.drive_params_card_holder, 1)
        return right_column

    def _active_live2d_entry(self):
        for entry in self.model_entries:
            if entry.kind == "live2d" and entry.active:
                return entry
        return None

    def _on_live2d_loaded(self, ok: bool) -> None:
        active = self._active_live2d_entry()
        name = active.name if active else "模型"
        text = f"正在显示：{name}" if ok else "当前未显示模型"
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(text)
        # 模型加载后更新参数面板
        if ok:
            self._sync_preview_views()
            self._refresh_drive_params_card()
            # 换模型了，手势菜单要按新模型支持的动作 / 表情重建
            self._rebuild_gesture_menus()

    def _on_live2d_error(self, message: str) -> None:
        text = f"模型加载失败：{message}"
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(text)

    def _on_vrm_loaded(self, ok: bool) -> None:
        active = self._active_vrm_entry()
        name = active.name if active else "VRM模型"
        text = f"正在显示：{name}" if ok else "当前未显示VRM模型"
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(text)
        # 模型加载后更新参数面板
        if ok:
            self._sync_preview_views()
            self._refresh_drive_params_card()
            self._rebuild_gesture_menus()

    def _on_vrm_error(self, message: str) -> None:
        text = f"VRM模型加载失败：{message}"
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(text)

    def _active_vrm_entry(self):
        for entry in self.model_entries:
            if entry.kind == "vrm" and entry.active:
                return entry
        return None

    def _active_rvc_entry(self):
        for entry in self.model_entries:
            if entry.kind == "rvc" and entry.active:
                return entry
        return None

    def _sync_live2d_views(self) -> None:
        active = self._active_live2d_entry()
        path = active.path if active else None
        name = active.name if active else ""
        view = getattr(self, "live2d_view", None)
        if view is not None:
            if path and getattr(self, "_avatar_running", False):
                # 检查文件格式，防止 VRM 文件被 Live2D 加载器处理
                if path.lower().endswith('.vrm'):
                    # VRM 文件应该使用 VRM 视图，这里清空 Live2D 视图
                    view.clear_model()
                    text = f"检测到 VRM 模型文件，请使用 VRM 视图加载：{name}"
                else:
                    try:
                        view.load_model(path)
                        text = f"当前模型：{name}"
                    except Exception as e:
                        # 加载失败时安全回退到空白预览
                        view.clear_model()
                        text = f"模型加载失败：{e}"
            else:
                view.clear_model()
                text = ("已停止" if not getattr(self, "_avatar_running", False)
                        else "暂无模型，请先在模型管理中导入并启用 Live2D 模型")
        else:
            text = "暂无模型，请先在模型管理中导入并启用 Live2D 模型"
        
        for status_attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, status_attr, None)
            if label is not None:
                label.setText(text)

    def _refresh_avatar_model_list(self) -> None:
        """按当前模型类型刷新虚拟形象页模型下拉；仅模型已启动时标记[使用中]。"""
        if getattr(self, "avatar_model_combo", None) is None:
            return
        self.avatar_model_combo.clear()
        model_type = self._current_avatar_kind()
        running = getattr(self, "_avatar_running", False)
        for entry in self.model_entries:
            if entry.kind != model_type:
                continue
            suffix = " [使用中]" if (entry.active and running) else ""
            self.avatar_model_combo.addItem(f"{entry.name}{suffix}", entry.name)

    def _refresh_live2d_page(self) -> None:
        self._refresh_avatar_model_list()
        self._sync_live2d_views()

    def _start_avatar(self) -> None:
        """启动并显示当前选中的模型，预览不再自动加载，需手动启动。"""
        model_type = self._current_avatar_kind()
        if self.avatar_model_combo.currentIndex() < 0 or self.avatar_model_combo.currentData() is None:
            show_info(self, "星弦", "暂无该类型模型，请先在模型管理中导入并启用")
            return
        name = self.avatar_model_combo.currentData()
        self._avatar_running = True

        if model_type == "live2d":
            self.model_entries = self.model_store.set_active("live2d", name)
            self._refresh_model_list("live2d")
        elif model_type == "vrm":
            self.model_entries = self.model_store.set_active("vrm", name)
            self._refresh_model_list("vrm")

        self._sync_preview_views()
        # 两个页面的状态文字一起写（以前只写形象页，首页那份一直停在旧文字）
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(f"已启动：{name}")
        # 首页预览切到画面那一态、两处模型列表的「[使用中]」一起刷新
        self._refresh_runtime_controls()

    def _stop_avatar(self) -> None:
        """停止模型预览，清除视图并隐藏，不再一直显示。"""
        self._avatar_running = False
        for view in (
            getattr(self, "live2d_view", None),
            getattr(self, "avatar_vrm_view", None),
            getattr(self, "avatar_live2d_view", None),
        ):
            if view is not None:
                try:
                    view.clear_model()
                except Exception:
                    pass
        self._refresh_avatar_model_list()
        self._sync_preview_views()
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText("已停止")
        self._refresh_runtime_controls()

    def _reload_live2d(self) -> None:
        if not getattr(self, "_avatar_running", False):
            show_info(self, "星弦", "请先启动模型")
            return
        active = self._active_live2d_entry()
        if active is None:
            show_info(self, "星弦", "当前没有可显示的模型")
            return
        self._sync_live2d_views()
        self.avatar_status.setText(f"正在重新加载：{active.name}")

    def _current_avatar_kind(self) -> str:
        """返回虚拟形象页当前选中的模型类型（live2d / vrm）。"""
        return self._avatar_kind

    def _on_avatar_model_type_changed(self, index: int) -> None:
        """左右标签页切换模型类型回调"""
        self._avatar_kind = "live2d" if index <= 0 else "vrm"
        self._refresh_avatar_model_list()
        self._sync_preview_views()
        self._refresh_drive_params_card()
        # 换了模型类型就是换了模型，手势菜单得跟着换一套
        self._rebuild_gesture_menus()

    def _on_home_type_changed(self, index: int) -> None:
        """首页模型类型左右标签切换回调"""
        self._avatar_kind = "live2d" if index <= 0 else "vrm"
        self._refresh_home_model_list()
        self._rebuild_gesture_menus()
        if getattr(self, "_avatar_running", False):
            active = (
                self._active_live2d_entry()
                if self._avatar_kind == "live2d"
                else self._active_vrm_entry()
            )
            if active is None:
                self._on_home_preview_stop()
                return
            self._start_home_model(active.name)
        else:
            self._sync_preview_views()

    def _refresh_home_model_list(self) -> None:
        model_list = getattr(self, "home_model_list", None)
        if model_list is None:
            return
        model_list.clear()
        kind = self._current_avatar_kind()
        running = getattr(self, "_avatar_running", False)
        for entry in self.model_entries:
            if entry.kind != kind:
                continue
            suffix = " [使用中]" if (entry.active and running) else ""
            item = QListWidgetItem(f"{entry.name}{suffix}")
            item.setData(Qt.UserRole, entry.name)
            model_list.addItem(item)
        active = (
            self._active_live2d_entry()
            if kind == "live2d"
            else self._active_vrm_entry()
        )
        if active is not None:
            for i in range(model_list.count()):
                if model_list.item(i).data(Qt.UserRole) == active.name:
                    model_list.setCurrentRow(i)
                    break

    def _on_home_model_selected(self, current, previous) -> None:
        label = getattr(self, "home_avatar_status", None)
        if label is not None and current is not None:
            label.setText(f"已选择：{current.data(Qt.UserRole) or current.text()}")

    def _on_home_preview_start(self) -> None:
        if self.home_model_list.currentRow() < 0:
            show_info(self, "星弦", "请先在列表中选择一个模型")
            return
        item = self.home_model_list.currentItem()
        name = item.data(Qt.UserRole) or item.text()
        self._start_home_model(name)

    def _start_home_model(self, name: str, kind: str | None = None) -> None:
        kind = kind or self._current_avatar_kind()
        self.model_entries = self.model_store.set_active(kind, name)
        self._avatar_running = True
        self._refresh_home_model_list()
        self._refresh_model_list(kind)
        self.home_current_model_label.setText(name)
        # 两个页面的状态文字一起写；栈与按钮显隐交给 _refresh_runtime_controls
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(f"已启动：{name}")
        self._sync_preview_views()
        self._refresh_runtime_controls()

    def _on_home_preview_stop(self) -> None:
        self._avatar_running = False
        for view in (
            getattr(self, "live2d_view", None),
        ):
            if view is not None:
                try:
                    view.clear_model()
                except Exception:
                    pass
        self.home_current_model_label.setText("--")
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText("已停止")
        self._refresh_home_model_list()
        self._sync_preview_views()
        self._refresh_runtime_controls()

    def _on_home_prev_model(self) -> None:
        self._cycle_home_model(-1)

    def _on_home_next_model(self) -> None:
        self._cycle_home_model(1)

    def _cycle_home_model(self, step: int) -> None:
        kind = self._current_avatar_kind()
        entries = [entry for entry in self.model_entries if entry.kind == kind]
        if not entries:
            return
        active = (
            self._active_live2d_entry()
            if kind == "live2d"
            else self._active_vrm_entry()
        )
        current_name = active.name if active else entries[0].name
        idx = next(
            (i for i, entry in enumerate(entries) if entry.name == current_name),
            0,
        )
        idx = (idx + step) % len(entries)
        self._start_home_model(entries[idx].name, kind)

    def _refresh_home_rvc_model_list(self) -> None:
        combo = getattr(self, "home_rvc_model_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        for entry in self.model_entries:
            if entry.kind == "rvc":
                combo.addItem(entry.name, entry.name)
        combo.blockSignals(False)
        active = self._active_rvc_entry()
        if active is not None:
            index = combo.findData(active.name)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._on_home_rvc_model_changed(combo.currentIndex())

    def _on_home_rvc_model_changed(self, index: int) -> None:
        name = self.home_rvc_model_combo.currentText()
        if getattr(self, "home_rvc_status", None) is not None:
            self.home_rvc_status.setText(f"当前模型：{name}")

    def _toggle_virtual_camera(self) -> None:
        if self.virtual_camera.running:
            self._stop_virtual_camera()
            return
        self._apply_vcam_key_background(
            self.vcam_key_toggle.isChecked() if hasattr(self, "vcam_key_toggle") else False
        )
        width, height = self._selected_vcam_size()
        self.virtual_camera.width = width
        self.virtual_camera.height = height
        self.virtual_camera.fps = int(self.vcam_fps_spin.value())
        try:
            self.virtual_camera.start()
        except VirtualCameraError as error:
            show_warning(
                self,
                "星弦",
                f"无法启动虚拟摄像头：{error}\n"
                "请点“安装/修复驱动”，并在系统弹窗中允许管理员权限。",
            )
            return
        self._stream_timer.start()
        self.vcam_start_button.setText("停止虚拟摄像头")
        self.vcam_status.setText(
            f"虚拟摄像头已启动（{self.virtual_camera.active_device}）。"
            f"在直播伴侣中把摄像头选为「{VIRTUAL_CAMERA_NAME}」。"
        )

    def _stop_virtual_camera(self) -> None:
        self._stream_timer.stop()
        self.virtual_camera.stop()
        if hasattr(self, "vcam_start_button"):
            self.vcam_start_button.setText("启动虚拟摄像头")
        if hasattr(self, "vcam_status"):
            self.vcam_status.setText(
                f"在直播伴侣中把摄像头选为「{VIRTUAL_CAMERA_NAME}」。"
            )

    def _selected_vcam_size(self) -> tuple[int, int]:
        combo = getattr(self, "vcam_resolution_combo", None)
        text = combo.currentText() if combo is not None else "1280 x 720"
        if "1920" in text:
            return 1920, 1080
        return 1280, 720

    def _apply_vcam_key_background(self, enabled: bool) -> None:
        """把透明背景模式同步到两个模型视图（Live2D / VRM）。"""
        for view in (
            getattr(self, "live2d_view", None),
            getattr(self, "avatar_vrm_view", None),
        ):
            if view is None:
                continue
            try:
                view.set_transparent_background(enabled)
            except Exception:
                pass

    def _on_vcam_key_toggled(self, checked: bool) -> None:
        self._apply_vcam_key_background(checked)
        if not hasattr(self, "vcam_status"):
            return
        if checked:
            self.vcam_status.setText(
                "已开启透明背景：虚拟摄像头只输出虚拟形象。"
                "若直播软件支持透明通道（ARGB/Alpha）会直接显示为无背景；"
                "不支持时会显示为黑色背景。"
            )
        else:
            self.vcam_status.setText(
                f"已关闭透明背景（输出含背景）。在直播伴侣中把摄像头选为「{VIRTUAL_CAMERA_NAME}」。"
            )

    def _install_virtual_camera_driver(self) -> None:
        if not driver_files_present():
            show_warning(
                self, "星弦", "未找到虚拟摄像头驱动文件（resources/virtualcam）。"
            )
            return
        self.vcam_status.setText("正在安装虚拟摄像头驱动，请在系统弹窗中允许管理员权限…")

        def worker() -> None:
            try:
                ok, message = install_driver()
            except Exception as error:  # noqa: BLE001
                ok, message = False, str(error)
            self.vcam_install_done.emit(ok, message)

        threading.Thread(target=worker, daemon=True).start()

    def _on_vcam_install_done(self, ok: bool, message: str) -> None:
        if getattr(self, "_closing", False):
            return
        if ok:
            self.vcam_status.setText(
                f"{message}。现在可以点“启动虚拟摄像头”，"
                f"并在直播伴侣里选择「{VIRTUAL_CAMERA_NAME}」。"
            )
        else:
            self.vcam_status.setText("驱动安装失败。")
            show_warning(self, "星弦", f"虚拟摄像头驱动安装失败：{message}")

    def _push_stream_frame(self) -> None:
        camera = getattr(self, "virtual_camera", None)
        if camera is None or not camera.running:
            return
        kind = self._current_avatar_kind()
        view = (
            getattr(self, "avatar_vrm_view", None)
            if kind == "vrm"
            else getattr(self, "live2d_view", None)
        )
        if view is None or not view.isVisible():
            return
        try:
            image = view.grabFramebuffer()
        except Exception:
            image = None
        if image is None or image.isNull():
            return
        frame = self._qimage_to_rgba_array(image, camera.width, camera.height)
        if frame is not None:
            camera.send(frame)

    @staticmethod
    def _qimage_to_rgba_array(image: QImage, width: int, height: int):
        if image.width() != width or image.height() != height:
            image = image.scaled(
                width,
                height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        buffer = rgba.constBits()
        array = np.frombuffer(buffer, dtype=np.uint8, count=rgba.sizeInBytes())
        array = array.reshape((rgba.height(), rgba.bytesPerLine()))[:, : width * 4]
        return array.reshape((height, width, 4)).copy()

    def _on_home_rvc_input_changed(self, index: int) -> None:
        self._sync_home_device_selection("input")

    def _on_home_rvc_output_changed(self, index: int) -> None:
        self._sync_home_device_selection("output")

    def _sync_home_device_selection(self, which: str) -> None:
        """首页设备发生变化时同步到音频变声页，保证启动使用同一设备。"""
        home = getattr(self, f"home_rvc_{which}_device", None)
        page = getattr(self, f"rvc_{which}_device", None)
        if home is None:
            return
        name = home.currentText()
        if page is not None:
            page.blockSignals(True)
            for i in range(page.count()):
                if page.itemText(i) == name:
                    page.setCurrentIndex(i)
                    break
            page.blockSignals(False)
        rvc = self.settings_store.load_rvc()
        rvc[f"{which}_device_name"] = name
        self.settings_store.save_rvc(rvc)

    def _sync_home_devices_from_page(self) -> None:
        """从音频变声页回首页时，把页面已选设备同步到首页下拉。"""
        for page_name, home_name in (
            ("rvc_input_device", "home_rvc_input_device"),
            ("rvc_output_device", "home_rvc_output_device"),
        ):
            page = getattr(self, page_name, None)
            home = getattr(self, home_name, None)
            if page is None or home is None or page.count() == 0:
                continue
            if home.currentText() == page.currentText():
                continue
            name = page.currentText()
            home.blockSignals(True)
            for i in range(home.count()):
                if home.itemText(i) == name:
                    home.setCurrentIndex(i)
                    break
            home.blockSignals(False)

    def _refresh_home_rvc_devices(self) -> None:
        in_combo = getattr(self, "home_rvc_input_device", None)
        out_combo = getattr(self, "home_rvc_output_device", None)
        if in_combo is None or out_combo is None:
            return
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except ImportError:
            return
        except Exception:
            return
        input_map, output_map = self._device_maps(devices)
        rvc = self.settings_store.load_rvc()
        self._populate_device_combo(in_combo, input_map, rvc.get("input_device_name", ""))
        self._populate_device_combo(out_combo, output_map, rvc.get("output_device_name", ""))

    def _refresh_rvc_devices_from_home(self) -> None:
        self._refresh_audio_devices()

    @staticmethod
    def _device_maps(devices) -> tuple[dict[str, int], dict[str, int]]:
        """把设备列表按输入/输出归类去重，返回 (in_map, out_map)。"""
        filter_keywords = [
            "mapper", "映射器",
            "primary", "主声音",
            "stereo mix", "立体声混音",
            "loopback", "环回",
            "wave", "streaming", "steam",
            "message", "系统声音",
        ]
        output_hints = ["扬声器", "speaker", "耳机", "headphone", "hd audio output", "output"]
        input_hints = ["麦克风", "microphone", "mic", "input", "line in"]
        virtual_cable_hints = ["vb-audio", "vb cable", "virtual cable", "voice meeter", "cable"]
        input_map: dict[str, int] = {}
        output_map: dict[str, int] = {}
        for i in range(len(devices)):
            device = devices[i]
            device_name = str(device["name"]).strip()
            if not device_name or device_name.endswith("()"):
                continue
            if any(keyword in device_name.lower() for keyword in filter_keywords):
                continue
            is_virtual_cable = any(k in device_name.lower() for k in virtual_cable_hints)
            is_output_like = (
                not is_virtual_cable
                and any(k in device_name.lower() for k in output_hints)
            )
            is_input_like = (
                not is_virtual_cable
                and any(k in device_name.lower() for k in input_hints)
            )
            if (
                device["max_input_channels"] > 0
                and not is_output_like
                and device_name not in input_map
            ):
                input_map[device_name] = i
            if (
                device["max_output_channels"] > 0
                and not is_input_like
                and device_name not in output_map
            ):
                output_map[device_name] = i
        return input_map, output_map

    @staticmethod
    def _populate_device_combo(
        combo,
        mapping: dict[str, int],
        restore_name: str,
    ) -> None:
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        for name, idx in mapping.items():
            combo.addItem(name, idx)
        combo.blockSignals(False)
        if restore_name:
            for i in range(combo.count()):
                if combo.itemText(i) == restore_name:
                    combo.setCurrentIndex(i)
                    break

    @staticmethod
    def _configure_device_combo(
        combo,
        min_width: int = 180,
        max_width: int = 520,
    ) -> None:
        """设备下拉按可用宽度展开，避免过窄导致弹出列表溢出页面。"""
        if combo is None:
            return
        combo.setMinimumWidth(min_width)
        combo.setMaximumWidth(max_width)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _build_vertical_meter(self, prefix: str, compact: bool = False) -> QFrame:
        """构建竖向音量监听表，并把进度条/数值挂到 self.<prefix>_* 上。"""
        meter = QFrame()
        meter.setObjectName("panel")
        if compact:
            meter.setFixedHeight(146)
            bar_width, bar_height = 22, 68
        else:
            meter.setFixedHeight(196)
            bar_width, bar_height = 30, 100
        meter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box = QVBoxLayout(meter)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(8)
        title = QLabel("音量监控")
        title.setObjectName("panelTitle")
        box.addWidget(title)
        bars = QHBoxLayout()
        bars.setSpacing(30)
        bars.addStretch(1)
        for key, label in (("input", "输入"), ("output", "输出")):
            col = QVBoxLayout()
            col.setSpacing(4)
            bar = QProgressBar()
            bar.setObjectName("volumeBar")
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setOrientation(Qt.Orientation.Vertical)
            bar.setFixedWidth(bar_width)
            bar.setFixedHeight(bar_height)
            col.addWidget(bar, 0, Qt.AlignHCenter)
            value_label = QLabel("0%")
            value_label.setObjectName("infoValue")
            value_label.setAlignment(Qt.AlignCenter)
            col.addWidget(value_label)
            name_label = QLabel(label)
            name_label.setObjectName("hintText")
            name_label.setAlignment(Qt.AlignCenter)
            col.addWidget(name_label)
            bars.addLayout(col)
            setattr(self, f"{prefix}_{key}_volume_bar", bar)
            setattr(self, f"{prefix}_{key}_volume_label", value_label)
        bars.addStretch(1)
        box.addLayout(bars, 1)
        return meter

    # ------------------------------------------------------------------
    # 调音台（独立弹窗，见 app/ui/mixer_dialog.py）
    # ------------------------------------------------------------------

    def _on_mixer_clicked(self) -> None:
        dlg = getattr(self, "_mixer_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        try:
            from app.ui.mixer_dialog import MixerDialog
        except ImportError as e:
            show_info(self, "星弦", f"调音台不可用：{e}")
            return
        dlg = MixerDialog(self, self.settings_store)
        dlg.finished.connect(lambda _=0: setattr(self, "_mixer_dialog", None))
        self._mixer_dialog = dlg
        dlg.show()

    def _shutdown_mixer(self) -> None:
        dlg = getattr(self, "_mixer_dialog", None)
        if dlg is not None:
            dlg.shutdown_monitor()
            dlg.close()
            self._mixer_dialog = None

    def _on_avatar_live2d_loaded(self, ok: bool) -> None:
        """Live2D 模型加载成功回调"""
        active = self._active_live2d_entry()
        name = active.name if active else "Live2D模型"
        text = f"当前 Live2D 模型：{name}" if ok else "当前未显示 Live2D 模型"
        self.avatar_status.setText(text)
        if ok:
            self._sync_preview_views()
            self._refresh_drive_params_card()

    def _on_avatar_live2d_error(self, message: str) -> None:
        """Live2D 模型加载失败回调"""
        self.avatar_status.setText(f"Live2D 模型加载失败：{message}")

    def _on_avatar_vrm_loaded(self, ok: bool) -> None:
        """VRM 模型加载成功回调"""
        active = self._active_vrm_entry()
        name = active.name if active else "VRM模型"
        text = f"当前 VRM 模型：{name}" if ok else "当前未显示 VRM 模型"
        self.avatar_status.setText(text)
        if ok:
            self._sync_preview_views()
            self._refresh_drive_params_card()
            self._rebuild_gesture_menus()

    def _on_avatar_vrm_error(self, message: str) -> None:
        """VRM 模型加载失败回调"""
        self.avatar_status.setText(f"VRM 模型加载失败：{message}")

    def _build_drive_params_card(self) -> QFrame:
        card, box = _make_card("模型参数设置")
        hint = QLabel("仅显示当前模型支持的参数；幅度越大动作越明显。")
        hint.setObjectName("hintText")
        box.addWidget(hint)

        self.drive_param_spins: dict[str, QDoubleSpinBox] = {}
        self.drive_param_inverts: dict[str, QCheckBox] = {}
        params = self.motion_settings.get("params", {})
        supported = self._supported_params_for_current()

        # 不支持的参数不显示，避免白白调整无效项
        no_invert = {"eye_open_l", "eye_open_r", "mouth_open", "eye", "mouth"}
        rows = [(p.name, p.id, p.id not in no_invert) for p in supported]

        # 状态与刷新：方便确认当前模型已识别出哪些可调参数
        refresh_row = QHBoxLayout()
        refresh_row.setSpacing(8)
        self.drive_params_status = QLabel(
            f"已检测到 {len(rows)} 个可调参数" if rows
            else "未检测到可调参数，请先启动模型"
        )
        self.drive_params_status.setObjectName("hintText")
        self.drive_params_status.setWordWrap(True)
        refresh_row.addWidget(self.drive_params_status, 1)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("smallGhostButton")
        refresh_button.setFixedSize(56, 26)
        refresh_button.clicked.connect(self._on_drive_params_refresh)
        refresh_row.addWidget(refresh_button)
        box.addLayout(refresh_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        if rows:
            for col, text in enumerate(("参数", "幅度", "反转")):
                head = QLabel(text)
                head.setObjectName("hintText")
                grid.addWidget(head, 0, col)

            for row, (label, key, has_invert) in enumerate(rows, start=1):
                name = QLabel(label)
                name.setObjectName("hintText")
                grid.addWidget(name, row, 0)
                mult = float(params.get(key, {}).get("mult", 1.0))
                amp = QWidget()
                amp_layout = QHBoxLayout(amp)
                amp_layout.setContentsMargins(0, 0, 0, 0)
                amp_layout.setSpacing(4)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setObjectName("rvcSlider")
                slider.setRange(0, 30)  # 0.0 ~ 3.0，步进 0.1
                slider.setSingleStep(1)
                slider.setPageStep(5)
                slider.setValue(int(round(mult * 10.0)))
                value_label = QLabel(f"{mult:.2f}")
                value_label.setObjectName("infoValue")
                value_label.setFixedWidth(40)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                def _on_slider(value: int, k: str = key, lbl: QLabel = value_label) -> None:
                    lbl.setText(f"{value / 10.0:.2f}")
                    self._on_drive_param_mult(k, value / 10.0)

                slider.valueChanged.connect(_on_slider)
                amp_layout.addWidget(slider, 1)
                amp_layout.addWidget(value_label)
                grid.addWidget(amp, row, 1)
                self.drive_param_spins[key] = slider
                if has_invert:
                    invert = QCheckBox()
                    invert.setObjectName("toggle")
                    invert.setChecked(bool(params.get(key, {}).get("invert", False)))
                    invert.toggled.connect(lambda checked, k=key: self._on_drive_param_invert(k, checked))
                    grid.addWidget(invert, row, 2)
                    self.drive_param_inverts[key] = invert
                else:
                    grid.addWidget(QLabel(""), row, 2)
        else:
            empty = QLabel("该模型暂无已识别的驱动参数，请先启动模型以自动检测。")
            empty.setObjectName("hintText")
            empty.setWordWrap(True)
            grid.addWidget(empty, 0, 0, 1, 3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        content = QWidget()
        content.setLayout(grid)
        scroll.setWidget(content)
        box.addWidget(scroll, 1)
        box.addStretch()
        return card

    def _supported_params_for_current(self) -> list:
        """按当前模型类型，从实际加载的模型视图中读取其支持的参数。"""
        model_type = self._current_avatar_kind()
        if model_type == "live2d":
            view = getattr(self, "live2d_view", None)
        elif model_type == "vrm":
            view = getattr(self, "avatar_vrm_view", None)
        else:
            view = None
        if view is None:
            return []
        try:
            params = view.get_supported_params()
            if isinstance(params, list):
                return params
        except Exception:
            return []
        return []

    def _on_drive_params_refresh(self) -> None:
        """手动刷新参数面板，重新检测当前模型支持的参数。"""
        self._refresh_drive_params_card()

    def _refresh_drive_params_card(self) -> None:
        """刷新参数面板，根据当前模型支持的参数重新生成"""
        holder = getattr(self, "drive_params_card_holder", None)
        if holder is None:
            return
        layout = holder.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        layout.addWidget(self._build_drive_params_card(), 1)

    def _on_drive_param_mult(self, key: str, value: float) -> None:
        params = self.motion_settings.setdefault("params", {})
        params.setdefault(key, {})["mult"] = value
        self.motion_capture.set_drive_params(params)
        self._save_motion_settings()

    def _on_drive_param_invert(self, key: str, checked: bool) -> None:
        params = self.motion_settings.setdefault("params", {})
        params.setdefault(key, {})["invert"] = checked
        self.motion_capture.set_drive_params(params)
        self._save_motion_settings()

    @staticmethod
    def _form_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintText")
        return label

    @staticmethod
    def _make_rvc_slider(
        label_text: str,
        min_val: int,
        max_val: int,
        default: int,
        *,
        is_int: bool = True,
        display_fmt=None,
    ) -> QWidget:
        """创建一个 RVC 风格的滑条控件：标签 | 滑条 | 数值显示。"""
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        label = QLabel(label_text)
        label.setFixedWidth(100)
        h.addWidget(label)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default)
        slider.setObjectName("rvcSlider")
        h.addWidget(slider, 1)

        value_label = QLabel()
        value_label.setFixedWidth(50)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(value_label)

        # 存储格式化函数
        if display_fmt is None:
            if is_int:
                display_fmt = lambda v: str(v)
            else:
                display_fmt = lambda v: f"{v:.2f}"

        def on_value_changed(val):
            value_label.setText(display_fmt(val))

        slider.valueChanged.connect(on_value_changed)
        on_value_changed(default)

        # 在 widget 上挂载 slider 引用，方便后续读取
        widget.slider = slider  # type: ignore[attr-defined]
        widget._display_fmt = display_fmt  # type: ignore[attr-defined]
        widget.value = lambda: slider.value()  # type: ignore[attr-defined]

        return widget

    def _build_personal_center_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("个人中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(14)

        account_card, account_box = _make_card("账户信息")
        avatar = QLabel(self.account[:1] or "星")
        avatar.setFixedSize(58, 58)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "border-radius: 29px; background: #4AA9E8; color: #FFFFFF; font-size: 26px; font-weight: 600;"
        )
        avatar_row = QHBoxLayout()
        avatar_row.setSpacing(12)
        avatar_row.addWidget(avatar)
        username = QLabel(self.account)
        username.setObjectName("panelTitle")
        avatar_row.addWidget(username)
        avatar_row.addStretch()
        account_box.addLayout(avatar_row)

        self.profile_stack = QStackedWidget()
        account_box.addWidget(self.profile_stack)

        # --- read-only view ---
        view_widget = QWidget()
        view_layout = QVBoxLayout(view_widget)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(10)
        view_layout.addWidget(self._form_label("昵称"))
        self.profile_nickname_value = QLabel("-")
        self.profile_nickname_value.setObjectName("infoValue")
        view_layout.addWidget(self.profile_nickname_value)
        view_layout.addWidget(self._form_label("手机号"))
        self.profile_phone_value = QLabel("-")
        self.profile_phone_value.setObjectName("infoValue")
        view_layout.addWidget(self.profile_phone_value)
        view_layout.addWidget(self._form_label("邮箱"))
        self.profile_email_value = QLabel("-")
        self.profile_email_value.setObjectName("infoValue")
        view_layout.addWidget(self.profile_email_value)
        edit_button = QPushButton("修改信息")
        edit_button.setObjectName("ghostButton")
        edit_button.clicked.connect(self._enter_profile_edit)
        view_layout.addWidget(edit_button)
        view_layout.addStretch()

        # --- edit mode ---
        edit_widget = QWidget()
        edit_layout = QVBoxLayout(edit_widget)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(10)
        edit_layout.addWidget(self._form_label("昵称"))
        self.profile_nickname_edit = QLineEdit()
        self.profile_nickname_edit.setObjectName("inputBox")
        self.profile_nickname_edit.setPlaceholderText("未设置")
        edit_layout.addWidget(self.profile_nickname_edit)
        edit_layout.addWidget(self._form_label("手机号"))
        self.profile_phone_edit = QLineEdit()
        self.profile_phone_edit.setObjectName("inputBox")
        self.profile_phone_edit.setPlaceholderText("未绑定")
        edit_layout.addWidget(self.profile_phone_edit)
        edit_layout.addWidget(self._form_label("邮箱"))
        self.profile_email_edit = QLineEdit()
        self.profile_email_edit.setObjectName("inputBox")
        self.profile_email_edit.setPlaceholderText("未绑定")
        edit_layout.addWidget(self.profile_email_edit)
        edit_buttons = QHBoxLayout()
        save_button = QPushButton("保存")
        save_button.setObjectName("actionButton")
        save_button.clicked.connect(self._save_profile)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("ghostButton")
        cancel_button.clicked.connect(self._cancel_profile_edit)
        edit_buttons.addWidget(save_button)
        edit_buttons.addWidget(cancel_button)
        edit_buttons.addStretch()
        edit_layout.addLayout(edit_buttons)

        self.profile_stack.addWidget(view_widget)
        self.profile_stack.addWidget(edit_widget)
        self.profile_status = QLabel("")
        self.profile_status.setObjectName("hintText")
        account_box.addWidget(self.profile_status)
        account_box.addStretch()
        body.addWidget(account_card, 1)

        security_card, security_box = _make_card("账号安全")
        security_hint = QLabel("定期修改密码，保护账号安全")
        security_hint.setObjectName("hintText")
        security_box.addWidget(security_hint)
        change_password = QPushButton("修改密码")
        change_password.setObjectName("ghostButton")
        change_password.clicked.connect(lambda: show_info(self, "星弦", "修改密码功能开发中"))
        security_box.addWidget(change_password)
        security_box.addStretch()
        logout = QPushButton("退出登录")
        logout.setObjectName("ghostButton")
        logout.clicked.connect(self.logout_requested.emit)
        security_box.addWidget(logout)
        body.addWidget(security_card, 1)

        layout.addLayout(body, 1)

        stats_card, stats_box = _make_card("数据概览")
        live2d_count = sum(1 for entry in self.model_entries if entry.kind == "live2d")
        rvc_count = sum(1 for entry in self.model_entries if entry.kind == "rvc")
        stats = QHBoxLayout()
        stats.setSpacing(16)
        for label, value in (
            ("直播场次", "0"),
            ("累计时长", "0 分钟"),
            ("Live2D 模型", str(live2d_count)),
            ("RVC 模型", str(rvc_count)),
        ):
            column = QVBoxLayout()
            value_label = QLabel(value)
            value_label.setObjectName("panelTitle")
            value_label.setAlignment(Qt.AlignCenter)
            caption = QLabel(label)
            caption.setObjectName("hintText")
            caption.setAlignment(Qt.AlignCenter)
            column.addWidget(value_label)
            column.addWidget(caption)
            stats.addLayout(column, 1)
        stats_box.addLayout(stats)
        layout.addWidget(stats_card)
        return page

    def _set_profile_status(self, text: str, ok: bool = True) -> None:
        label = getattr(self, "profile_status", None)
        if label is None:
            return
        label.setText(text)
        label.setStyleSheet("color: #7EE7FF;" if ok else "color: #FF7E7E;")

    def _load_profile(self) -> None:
        username = self.account
        if not username:
            return
        if self.offline:
            self._set_profile_status("离线模式，使用本地配置")
            return
        self._set_profile_status("正在加载个人信息...")

        def worker() -> None:
            try:
                data = get_profile(username)
            except LoginError as error:
                self.profile_load_error.emit(str(error))
            else:
                self.profile_loaded.emit(data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_profile_loaded(self, data: dict) -> None:
        self.profile_data = dict(data)
        self._apply_profile_to_view()
        self._apply_profile_to_edit()
        self._set_profile_status("个人信息已加载")

    def _on_profile_load_error(self, message: str) -> None:
        self._set_profile_status(f"加载失败：{message}", ok=False)

    def _apply_profile_to_view(self) -> None:
        data = self.profile_data
        for attr, key in (
            ("profile_nickname_value", "nickname"),
            ("profile_phone_value", "phone"),
            ("profile_email_value", "email"),
        ):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(str(data.get(key, "") or "-"))

    def _apply_profile_to_edit(self) -> None:
        data = self.profile_data
        if getattr(self, "profile_nickname_edit", None) is None:
            return
        self.profile_nickname_edit.setText(str(data.get("nickname", "")))
        self.profile_phone_edit.setText(str(data.get("phone", "")))
        self.profile_email_edit.setText(str(data.get("email", "")))

    def _enter_profile_edit(self) -> None:
        self._apply_profile_to_edit()
        if getattr(self, "profile_stack", None) is not None:
            self.profile_stack.setCurrentIndex(1)
        self._set_profile_status("编辑中，修改后点击保存")

    def _cancel_profile_edit(self) -> None:
        if getattr(self, "profile_stack", None) is not None:
            self.profile_stack.setCurrentIndex(0)
        self._set_profile_status("")

    def _save_profile(self) -> None:
        if getattr(self, "profile_nickname_edit", None) is None:
            return
        if self.offline:
            self._set_profile_status("离线模式使用独立本地配置，不修改在线账户信息", ok=False)
            return
        username = self.account
        nickname = self.profile_nickname_edit.text().strip()
        phone = self.profile_phone_edit.text().strip()
        email = self.profile_email_edit.text().strip()
        if not nickname:
            show_info(self, "星弦", "昵称不能为空")
            return
        self._set_profile_status("正在保存...")

        def worker() -> None:
            try:
                data = update_profile(username, nickname, phone, email)
            except LoginError as error:
                self.profile_save_error.emit(str(error))
            else:
                self.profile_saved.emit(data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_profile_saved(self, data: dict) -> None:
        self.profile_data = dict(data)
        self._apply_profile_to_view()
        self._apply_profile_to_edit()
        if getattr(self, "profile_stack", None) is not None:
            self.profile_stack.setCurrentIndex(0)
        self._set_profile_status("保存成功")
        show_info(self, "星弦", "个人信息已保存")

    def _on_profile_save_error(self, message: str) -> None:
        self._set_profile_status(f"保存失败：{message}", ok=False)
        show_warning(self, "星弦", message)

    def _build_system_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("系统设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        scheme_card, scheme_box = _make_card("配置方案")
        scheme_row = QHBoxLayout()
        scheme_row.addWidget(self._form_label("方案名称"))
        self.cfg_scheme_name = QLineEdit()
        self.cfg_scheme_name.setObjectName("inputBox")
        self.cfg_scheme_name.setPlaceholderText("为当前设置命名，例如：日常直播")
        self.cfg_scheme_name.setText(self.system_settings.get("scheme_name", "日常直播"))
        self.cfg_scheme_name.textChanged.connect(self.cfg_scheme_name_changed)
        scheme_row.addWidget(self.cfg_scheme_name, 1)
        scheme_box.addLayout(scheme_row)
        scheme_box.addWidget(
            self._form_label("保存后，左下角将显示当前方案名称，并随账户独立保存。")
        )
        layout.addWidget(scheme_card)

        motion_card, motion_box = _make_card("动捕设置")
        cam_row = QHBoxLayout()
        cam_row.addWidget(self._form_label("摄像头设备"))
        self.cfg_camera_combo = ArrowComboBox()
        self.cfg_camera_combo.setObjectName("inputBox")
        self._configure_device_combo(self.cfg_camera_combo, 160, 320)
        self.cfg_camera_combo.currentIndexChanged.connect(self.cfg_camera_changed)
        cam_row.addWidget(self.cfg_camera_combo, 1)
        cfg_cam_refresh = QPushButton("刷新")
        cfg_cam_refresh.setObjectName("smallGhostButton")
        cfg_cam_refresh.clicked.connect(lambda: self._refresh_camera_devices(force=True))
        cam_row.addWidget(cfg_cam_refresh)
        self._populate_camera_combo(self.cfg_camera_combo)
        cam_row.addWidget(self._form_label("动捕引擎"))
        self.cfg_engine_combo = ArrowComboBox()
        self.cfg_engine_combo.setObjectName("inputBox")
        self.cfg_engine_combo.addItems(["混合 (YOLO + 人脸)", "仅人脸", "仅 YOLO"])
        engine_map = {"hybrid": 0, "face": 1, "yolo": 2}
        self.cfg_engine_combo.setCurrentIndex(engine_map.get(self.motion_settings.get("engine", "hybrid"), 0))
        self.cfg_engine_combo.currentIndexChanged.connect(self.cfg_engine_changed)
        cam_row.addWidget(self.cfg_engine_combo, 1)
        motion_box.addLayout(cam_row)

        self.cfg_mirror = QCheckBox("镜像画面")
        self.cfg_mirror.setObjectName("toggle")
        self.cfg_mirror.setChecked(bool(self.motion_settings.get("mirror", True)))
        self.cfg_mirror.toggled.connect(self.cfg_mirror_changed)
        motion_box.addWidget(self.cfg_mirror)

        sens_row = QHBoxLayout()
        sens_row.addWidget(self._form_label("灵敏度"))
        self.cfg_sensitivity = ArrowDoubleSpinBox()
        self.cfg_sensitivity.setObjectName("inputBox")
        self.cfg_sensitivity.setRange(0.1, 3.0)
        self.cfg_sensitivity.setSingleStep(0.1)
        self.cfg_sensitivity.setValue(float(self.motion_settings.get("sensitivity", 1.0)))
        self.cfg_sensitivity.valueChanged.connect(self.cfg_sensitivity_changed)
        sens_row.addWidget(self.cfg_sensitivity, 1)
        motion_box.addLayout(sens_row)

        self.cfg_drive = QCheckBox("开启动捕驱动 Live2D 联动")
        self.cfg_drive.setObjectName("toggle")
        self.cfg_drive.setChecked(bool(self.motion_settings.get("drive_enabled", True)))
        self.cfg_drive.toggled.connect(self.cfg_drive_changed)
        motion_box.addWidget(self.cfg_drive)
        layout.addWidget(motion_card)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(14)

        video_card, video_box = _make_card("视频输出")
        video_box.addWidget(self._form_label("输出分辨率"))
        self.cfg_resolution = ArrowComboBox()
        self.cfg_resolution.setObjectName("inputBox")
        self.cfg_resolution.addItems(["1080P", "720P", "4K"])
        self._set_combo_text(self.cfg_resolution, self.system_settings.get("video_resolution", "1080P"))
        self.cfg_resolution.currentIndexChanged.connect(self.cfg_resolution_changed)
        video_box.addWidget(self.cfg_resolution)
        video_box.addWidget(self._form_label("帧率"))
        self.cfg_fps = ArrowSpinBox()
        self.cfg_fps.setObjectName("inputBox")
        self.cfg_fps.setRange(24, 120)
        self.cfg_fps.setValue(int(self.system_settings.get("video_fps", 60)))
        self.cfg_fps.valueChanged.connect(self.cfg_fps_changed)
        video_box.addWidget(self.cfg_fps)
        video_box.addStretch()
        settings_row.addWidget(video_card, 1)

        audio_card, audio_box = _make_card("音频设置")
        audio_box.addWidget(self._form_label("采样率"))
        self.cfg_sample_rate = ArrowComboBox()
        self.cfg_sample_rate.setObjectName("inputBox")
        self.cfg_sample_rate.addItems(["44100 Hz", "48000 Hz", "96000 Hz"])
        self._set_combo_text(self.cfg_sample_rate, self.system_settings.get("audio_sample_rate", "48000 Hz"))
        self.cfg_sample_rate.currentIndexChanged.connect(self.cfg_sample_rate_changed)
        audio_box.addWidget(self.cfg_sample_rate)
        audio_box.addWidget(self._form_label("变声引擎"))
        self.cfg_audio_engine = ArrowComboBox()
        self.cfg_audio_engine.setObjectName("inputBox")
        self.cfg_audio_engine.addItems(["RVC", "未启用"])
        self._set_combo_text(self.cfg_audio_engine, self.system_settings.get("audio_engine", "RVC"))
        self.cfg_audio_engine.currentIndexChanged.connect(self.cfg_audio_engine_changed)
        audio_box.addWidget(self.cfg_audio_engine)
        audio_box.addStretch()
        settings_row.addWidget(audio_card, 1)

        layout.addLayout(settings_row, 1)

        save_button = QPushButton("保存为方案")
        save_button.setObjectName("actionButton")
        save_button.clicked.connect(self._on_save_system_settings)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(save_button)
        layout.addLayout(save_row)
        return page

    def _build_lipsync_card(self) -> QFrame:
        """语音驱动口型控制卡：让嘴型跟着声音走，而不是跟着摄像头画面走。"""
        card, box = _make_card("语音驱动口型")
        hint = QLabel(
            "从变声链路的输入电平提取包络驱动嘴型，说话即张嘴、停顿即收口；"
            "需要先启动变声。"
        )
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        box.addWidget(hint)

        self.lipsync_toggle = QCheckBox("启用语音驱动口型")
        self.lipsync_toggle.setObjectName("toggle")
        self.lipsync_toggle.setChecked(bool(self.lipsync_settings.get("enabled", False)))
        self.lipsync_toggle.toggled.connect(self._on_lipsync_toggled)
        box.addWidget(self.lipsync_toggle)

        self.lipsync_form_toggle = QCheckBox("同时驱动口型形状")
        self.lipsync_form_toggle.setObjectName("toggle")
        self.lipsync_form_toggle.setChecked(bool(self.lipsync_settings.get("form_enabled", True)))
        self.lipsync_form_toggle.setToolTip("按频谱亮度区分扁口与圆唇，模型需支持嘴巴形状参数")
        self.lipsync_form_toggle.toggled.connect(self._on_lipsync_form_toggled)
        box.addWidget(self.lipsync_form_toggle)

        gain_row = QHBoxLayout()
        gain_row.setSpacing(8)
        gain_row.addWidget(self._form_label("灵敏度"))
        self.lipsync_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.lipsync_gain_slider.setObjectName("rvcSlider")
        self.lipsync_gain_slider.setRange(50, 300)  # 0.50 ~ 3.00
        self.lipsync_gain_slider.setValue(
            int(round(float(self.lipsync_settings.get("gain", 1.4)) * 100))
        )
        self.lipsync_gain_slider.valueChanged.connect(self._on_lipsync_gain_changed)
        gain_row.addWidget(self.lipsync_gain_slider, 1)
        self.lipsync_gain_value = QLabel(f"{self.lipsync_gain_slider.value() / 100:.2f}")
        self.lipsync_gain_value.setObjectName("infoValue")
        self.lipsync_gain_value.setFixedWidth(40)
        self.lipsync_gain_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gain_row.addWidget(self.lipsync_gain_value)
        box.addLayout(gain_row)

        self.lipsync_meter = QProgressBar()
        self.lipsync_meter.setObjectName("volumeBar")
        self.lipsync_meter.setRange(0, 100)
        self.lipsync_meter.setValue(0)
        self.lipsync_meter.setTextVisible(False)
        self.lipsync_meter.setFixedHeight(14)
        box.addWidget(self.lipsync_meter)

        self.lipsync_status = QLabel("未启用")
        self.lipsync_status.setObjectName("hintText")
        self.lipsync_status.setWordWrap(True)
        box.addWidget(self.lipsync_status)
        return card

    def _set_lipsync_controls(self, enabled: bool) -> None:
        for attr in ("lipsync_gain_slider", "lipsync_form_toggle"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(bool(enabled))

    def _on_lipsync_toggled(self, checked: bool) -> None:
        self.lipsync_settings["enabled"] = bool(checked)
        self._voice_lipsync.set_enabled(bool(checked))
        if checked:
            self._lipsync_timer.start()
            self.lipsync_status.setText("已启用：启动变声后说话即可看到口型")
        else:
            self._lipsync_timer.stop()
            self._voice_lipsync.reset()
            if getattr(self, "lipsync_meter", None) is not None:
                self.lipsync_meter.setValue(0)
            self.lipsync_status.setText("未启用")
        self._set_lipsync_controls(checked)
        self._save_lipsync_settings()

    def _on_lipsync_form_toggled(self, checked: bool) -> None:
        self.lipsync_settings["form_enabled"] = bool(checked)
        self._save_lipsync_settings()

    def _on_lipsync_gain_changed(self, value: int) -> None:
        gain = value / 100.0
        self.lipsync_settings["gain"] = gain
        self._voice_lipsync.set_gain(gain)
        if getattr(self, "lipsync_gain_value", None) is not None:
            self.lipsync_gain_value.setText(f"{gain:.2f}")
        self._save_lipsync_settings()

    def _save_lipsync_settings(self) -> None:
        try:
            self.settings_store.save_lipsync(self.lipsync_settings)
        except Exception as error:  # noqa: BLE001
            print(f"保存语音口型设置失败: {error}")

    def _on_lipsync_tick(self) -> None:
        """把语音包络写进当前显示中的模型视图。

        只写嘴部参数，不整帧下发 ``apply_drive``，否则会把动捕正在驱动的
        头部/手臂一起归零。
        """
        if not self._voice_lipsync.is_enabled():
            return
        mouth, form, level = self._voice_lipsync.read()
        if getattr(self, "lipsync_meter", None) is not None:
            self.lipsync_meter.setValue(int(max(0.0, min(1.0, level)) * 100))
        if mouth <= 0.01 and not getattr(self, "_lipsync_was_active", False):
            return
        self._lipsync_was_active = mouth > 0.01
        view = self._active_model_view()
        if view is None:
            return
        shape = form if self.lipsync_settings.get("form_enabled", True) else None
        try:
            view.set_mouth(mouth, shape)
        except Exception:
            pass

    def _active_model_view(self):
        """返回当前页面/模型类型下真正在显示的那个模型视图。"""
        kind = self._current_avatar_kind()
        if kind == "vrm":
            return getattr(self, "avatar_vrm_view", None)
        return getattr(self, "live2d_view", None)

    def _build_rvc_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title_label = QLabel("音频变声")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        # 主内容区域：左右布局
        content = QHBoxLayout()
        content.setSpacing(14)

        # 左侧：模型选择和参数设置
        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 14, 16, 14)
        left_layout.setSpacing(12)

        # 模型选择区域
        model_title = QLabel("RVC 模型选择")
        model_title.setObjectName("panelTitle")
        left_layout.addWidget(model_title)

        self.rvc_model_combo = QComboBox()
        self.rvc_model_combo.setObjectName("inputBox")
        left_layout.addWidget(self.rvc_model_combo)

        # 参数设置区域
        params_title = QLabel("变声参数设置")
        params_title.setObjectName("panelTitle")
        left_layout.addWidget(params_title)

        params_form = QGridLayout()
        params_form.setSpacing(8)

        # 音调变换 (整数滑条: -24 ~ 24)
        self.rvc_pitch_shift = self._make_rvc_slider(
            "音调变换 (半音)", -24, 24, 0, is_int=True
        )
        params_form.addWidget(self.rvc_pitch_shift, 0, 0, 1, 2)

        # 索引比例 (滑条: 0 ~ 100, 显示 0.00 ~ 1.00)
        self.rvc_index_rate = self._make_rvc_slider(
            "索引比例", 0, 100, 75, is_int=True, display_fmt=lambda v: f"{v / 100:.2f}"
        )
        params_form.addWidget(self.rvc_index_rate, 1, 0, 1, 2)

        # 滤波半径 (整数滑条: 0 ~ 7)
        self.rvc_filter_radius = self._make_rvc_slider(
            "滤波半径", 0, 7, 3, is_int=True
        )
        params_form.addWidget(self.rvc_filter_radius, 2, 0, 1, 2)

        # RMS混合比例 (滑条: 0 ~ 100, 显示 0.00 ~ 1.00)
        self.rvc_rms_mix_rate = self._make_rvc_slider(
            "RMS混合比例", 0, 100, 25, is_int=True, display_fmt=lambda v: f"{v / 100:.2f}"
        )
        params_form.addWidget(self.rvc_rms_mix_rate, 3, 0, 1, 2)

        # 输出阈值：低于该音量视为静音，不输出（避免底噪一直响）
        self.rvc_gate_threshold = self._make_rvc_slider(
            "输出阈值 (0=关闭)", 0, 100, 0, is_int=True
        )
        params_form.addWidget(self.rvc_gate_threshold, 4, 0, 1, 2)

        left_layout.addLayout(params_form)

        # 音高提取方法 (单选按钮组)
        f0_title = QLabel("音高提取算法")
        f0_title.setObjectName("panelBody")
        left_layout.addWidget(f0_title)

        f0_group = QButtonGroup(self)
        f0_layout = QHBoxLayout()
        f0_layout.setSpacing(6)
        self.rvc_f0_buttons: dict[str, QCheckBox] = {}
        for method in ["rmvpe", "crepe", "harvest", "fcpe"]:
            btn = QCheckBox(method)
            btn.setObjectName("toggle")
            f0_group.addButton(btn)
            f0_layout.addWidget(btn)
            self.rvc_f0_buttons[method] = btn
            if method == "harvest":
                btn.setChecked(True)
        f0_layout.addStretch()
        left_layout.addLayout(f0_layout)

        # ComboBox 设置区域
        combo_form = QGridLayout()
        combo_form.setSpacing(8)

        # 音高提取方法（下拉框）
        combo_form.addWidget(self._form_label("音高提取方法"), 0, 0)
        self.rvc_f0_method = ArrowComboBox()
        self.rvc_f0_method.setObjectName("inputBox")
        self.rvc_f0_method.addItems(["rmvpe", "crepe", "harvest", "pm", "mangio-crepe"])
        self.rvc_f0_method.setCurrentText("rmvpe")
        combo_form.addWidget(self.rvc_f0_method, 0, 1)

        # 重采样率
        combo_form.addWidget(self._form_label("重采样率"), 1, 0)
        self.rvc_resample_sr = ArrowComboBox()
        self.rvc_resample_sr.setObjectName("inputBox")
        self.rvc_resample_sr.addItems(["0", "40000", "48000"])
        self.rvc_resample_sr.setCurrentText("0")
        combo_form.addWidget(self.rvc_resample_sr, 1, 1)

        left_layout.addLayout(combo_form)

        # 复选框设置
        check_layout = QHBoxLayout()
        check_layout.setSpacing(12)
        self.rvc_protect_voiceless = QCheckBox("保护无音节")
        self.rvc_protect_voiceless.setObjectName("toggle")
        self.rvc_protect_voiceless.setChecked(True)
        check_layout.addWidget(self.rvc_protect_voiceless)

        self.rvc_is_half = QCheckBox("半精度(FP16)")
        self.rvc_is_half.setObjectName("toggle")
        self.rvc_is_half.setChecked(True)
        check_layout.addWidget(self.rvc_is_half)

        self.rvc_denoise = QCheckBox("降噪")
        self.rvc_denoise.setObjectName("toggle")
        check_layout.addWidget(self.rvc_denoise)
        check_layout.addStretch()
        left_layout.addLayout(check_layout)
        left_layout.addStretch()

        # 右侧：设备选择和控制
        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(12)

        # 音频设备选择区域（始终显示）
        device_title = QLabel("音频设备选择")
        device_title.setObjectName("panelTitle")
        right_layout.addWidget(device_title)
        input_device_layout = QHBoxLayout()
        input_device_layout.setSpacing(8)
        input_device_layout.addWidget(self._form_label("输入设备："))
        self.rvc_input_device = ArrowComboBox()
        self.rvc_input_device.setObjectName("inputBox")
        self._configure_device_combo(self.rvc_input_device, 200, 720)
        input_device_layout.addWidget(self.rvc_input_device, 1)
        right_layout.addLayout(input_device_layout)
        output_device_layout = QHBoxLayout()
        output_device_layout.setSpacing(8)
        output_device_layout.addWidget(self._form_label("输出设备："))
        self.rvc_output_device = ArrowComboBox()
        self.rvc_output_device.setObjectName("inputBox")
        self._configure_device_combo(self.rvc_output_device, 200, 720)
        output_device_layout.addWidget(self.rvc_output_device, 1)
        right_layout.addLayout(output_device_layout)
        refresh_devices_button = QPushButton("刷新设备列表")
        refresh_devices_button.setObjectName("ghostButton")
        refresh_devices_button.clicked.connect(self._refresh_audio_devices)
        right_layout.addWidget(refresh_devices_button)
        setup_virtual_button = QPushButton("一键启用虚拟声卡")
        setup_virtual_button.setObjectName("actionButton")
        setup_virtual_button.clicked.connect(self._setup_virtual_audio)
        right_layout.addWidget(setup_virtual_button)
        self.rvc_audio_hint = QLabel(
            "回音提示：直播/通话软件里的“麦克风”请选虚拟声卡的输出端（如 CABLE Output），"
            "不要直接选物理麦克风，否则原声和变声会同时被采集，听起来像回声。"
        )
        self.rvc_audio_hint.setObjectName("hintText")
        self.rvc_audio_hint.setWordWrap(True)
        right_layout.addWidget(self.rvc_audio_hint)

        # 变声控制区域
        control_title = QLabel("变声控制")
        control_title.setObjectName("panelTitle")
        right_layout.addWidget(control_title)
        self.rvc_status = QLabel("状态：未启动")
        self.rvc_status.setObjectName("infoValue")
        right_layout.addWidget(self.rvc_status)
        self.rvc_current_model = QLabel("当前模型：未选择")
        self.rvc_current_model.setObjectName("panelBody")
        right_layout.addWidget(self.rvc_current_model)

        # 开始/停止按钮
        control_buttons = QHBoxLayout()
        control_buttons.setSpacing(12)
        self.rvc_start_button = QPushButton("开始变声")
        self.rvc_start_button.setObjectName("actionButton")
        self.rvc_start_button.clicked.connect(self._on_rvc_start)
        self.rvc_stop_button = QPushButton("停止变声")
        self.rvc_stop_button.setObjectName("ghostButton")
        self.rvc_stop_button.clicked.connect(self._on_rvc_stop)
        self.rvc_stop_button.hide()  # 未开始变声只显示“开始变声”
        control_buttons.addWidget(self.rvc_start_button)
        control_buttons.addWidget(self.rvc_stop_button)
        self.rvc_mixer_button = QPushButton("调音台")
        self.rvc_mixer_button.setObjectName("ghostButton")
        self.rvc_mixer_button.clicked.connect(self._on_mixer_clicked)
        control_buttons.addWidget(self.rvc_mixer_button)
        control_buttons.addStretch()
        right_layout.addLayout(control_buttons)

        # 变声控制下方：语音驱动口型
        right_layout.addWidget(self._build_lipsync_card())

        # 变声控制下方：竖向音量监听（调音台为独立弹窗）
        right_layout.addSpacing(10)
        self.rvc_volume_meter = self._build_vertical_meter("rvc")
        right_layout.addWidget(self.rvc_volume_meter)
        right_layout.addStretch()

        content.addWidget(left_panel, 1)
        content.addWidget(right_panel, 2)
        layout.addLayout(content, 1)

        # 初始化
        self._refresh_rvc_model_list()
        self._rvc_running = False

        # 加载上次保存的 RVC 设置
        self._load_rvc_settings()

        # 参数变化时自动保存
        self.rvc_pitch_shift.slider.valueChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_index_rate.slider.valueChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_filter_radius.slider.valueChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_rms_mix_rate.slider.valueChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_f0_method.currentIndexChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_resample_sr.currentIndexChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_protect_voiceless.stateChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_is_half.stateChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_gate_threshold.slider.valueChanged.connect(self._on_rvc_gate_changed)
        self.rvc_denoise.stateChanged.connect(self._on_rvc_denoise_changed)
        self.rvc_input_device.currentIndexChanged.connect(lambda _: self._save_rvc_settings())
        self.rvc_output_device.currentIndexChanged.connect(lambda _: self._save_rvc_settings())

        return page

    def _build_model_page(self, kind: str, title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)
        layout.addWidget(self._build_model_tab(kind), 1)
        return page

    def _build_model_tab(self, kind: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.model_lists = getattr(self, "model_lists", {})
        model_list = QListWidget()
        model_list.setObjectName("modelList")
        model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.model_lists[kind] = model_list
        layout.addWidget(model_list, 1)

        buttons = QHBoxLayout()
        import_button = QPushButton("导入模型")
        import_button.setObjectName("navButton")
        import_button.clicked.connect(lambda _=False, k=kind: self._import_model(k))
        rename_button = QPushButton("重命名")
        rename_button.setObjectName("navButton")
        rename_button.clicked.connect(lambda _=False, k=kind: self._rename_model(k))
        use_button = QPushButton("使用")
        use_button.setObjectName("navButton")
        use_button.clicked.connect(lambda _=False, k=kind: self._use_model(k))
        delete_button = QPushButton("删除")
        delete_button.setObjectName("navButton")
        delete_button.clicked.connect(lambda _=False, k=kind: self._delete_model(k))
        buttons.addWidget(import_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(use_button)
        buttons.addWidget(delete_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._refresh_model_list(kind)
        return tab

    def _build_model_management_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title_label = QLabel("模型管理")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        tabs = QTabWidget()
        tabs.setObjectName("modelTabs")
        for kind, label in (("live2d", "Live2D 模型"), ("vrm", "VRM 模型"), ("rvc", "RVC 模型")):
            tabs.addTab(self._build_model_tab(kind), label)
        layout.addWidget(tabs, 1)
        return page

    def _build_cloud_management_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title_label = QLabel("云端管理")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        self.cloud_all_models: list[dict] = []
        self.cloud_models: list[dict] = []
        self.cloud_presets: list[dict] = []
        self.cloud_status = QLabel("")
        self.cloud_status.setObjectName("panelBody")
        self.cloud_status.setWordWrap(True)
        layout.addWidget(self.cloud_status)

        if self.offline:
            offline_hint = QLabel("当前为离线模式，无法访问云端，联网登录后可上传 / 下载模型。")
            offline_hint.setObjectName("hintText")
            offline_hint.setWordWrap(True)
            layout.addWidget(offline_hint)

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self.cloud_tabs = QTabBar()
        self.cloud_tabs.setObjectName("avatarTypeTabs")
        self.cloud_tabs.addTab("云模型")
        self.cloud_tabs.addTab("云端方案")
        self.cloud_tabs.currentChanged.connect(self._on_cloud_tab_changed)
        self.cloud_tabs.blockSignals(True)
        self.cloud_tabs.setCurrentIndex(0)
        self.cloud_tabs.blockSignals(False)
        tabs_row.addWidget(self.cloud_tabs)
        tabs_row.addStretch()
        layout.addLayout(tabs_row)

        self.cloud_stack = QStackedWidget()
        self.cloud_stack.addWidget(self._build_cloud_model_tab())
        self.cloud_stack.addWidget(self._build_cloud_preset_tab())
        layout.addWidget(self.cloud_stack, 1)
        return page

    def _on_cloud_tab_changed(self, index: int) -> None:
        stack = getattr(self, "cloud_stack", None)
        if stack is not None:
            stack.setCurrentIndex(index)

    def _build_cloud_model_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.cloud_kind_tabs = QTabBar()
        self.cloud_kind_tabs.setObjectName("avatarTypeTabs")
        for label in ("Live2D", "VRM", "RVC"):
            self.cloud_kind_tabs.addTab(label)
        self.cloud_kind_tabs.blockSignals(True)
        self.cloud_kind_tabs.setCurrentIndex(0)
        self.cloud_kind_tabs.blockSignals(False)
        self.cloud_kind_tabs.currentChanged.connect(self._on_cloud_kind_changed)
        toolbar.addWidget(self.cloud_kind_tabs)
        upload_button = QPushButton("上传模型")
        upload_button.setObjectName("smallActionButton")
        upload_button.clicked.connect(self._upload_cloud_model)
        toolbar.addWidget(upload_button)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("smallGhostButton")
        refresh_button.clicked.connect(self._refresh_cloud_models)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.cloud_model_list = QListWidget()
        self.cloud_model_list.setObjectName("modelList")
        self.cloud_model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.cloud_model_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        download_button = QPushButton("下载")
        download_button.setObjectName("smallActionButton")
        download_button.clicked.connect(lambda _=False: self._cloud_action("download"))
        enable_button = QPushButton("启用")
        enable_button.setObjectName("smallActionButton")
        enable_button.clicked.connect(lambda _=False: self._cloud_action("enable"))
        delete_button = QPushButton("删除")
        delete_button.setObjectName("smallGhostButton")
        delete_button.clicked.connect(lambda _=False: self._cloud_action("delete"))
        actions.addWidget(download_button)
        actions.addWidget(enable_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        layout.addLayout(actions)

        return tab

    def _build_cloud_preset_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.preset_kind_tabs = QTabBar()
        self.preset_kind_tabs.setObjectName("avatarTypeTabs")
        for label in ("模型参数方案", "完整配置方案"):
            self.preset_kind_tabs.addTab(label)
        self.preset_kind_tabs.blockSignals(True)
        self.preset_kind_tabs.setCurrentIndex(0)
        self.preset_kind_tabs.blockSignals(False)
        self.preset_kind_tabs.currentChanged.connect(self._on_preset_kind_changed)
        toolbar.addWidget(self.preset_kind_tabs)

        self.preset_name_edit = QLineEdit()
        self.preset_name_edit.setObjectName("inputBox")
        self.preset_name_edit.setPlaceholderText("方案名称")
        self.preset_name_edit.setFixedWidth(160)
        toolbar.addWidget(self.preset_name_edit)

        upload_button = QPushButton("上传当前方案")
        upload_button.setObjectName("smallActionButton")
        upload_button.clicked.connect(self._upload_current_preset)
        toolbar.addWidget(upload_button)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("smallGhostButton")
        refresh_button.clicked.connect(self._refresh_cloud_presets)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.cloud_preset_list = QListWidget()
        self.cloud_preset_list.setObjectName("modelList")
        self.cloud_preset_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.cloud_preset_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        apply_button = QPushButton("下载应用")
        apply_button.setObjectName("smallActionButton")
        apply_button.clicked.connect(self._apply_cloud_preset)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("smallGhostButton")
        delete_button.clicked.connect(self._delete_cloud_preset)
        actions.addWidget(apply_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        layout.addLayout(actions)

        return tab

    def _refresh_cloud_models(self) -> None:
        if getattr(self, "cloud_model_list", None) is None:
            return
        if self.offline:
            self._set_cloud_status("离线模式，无法访问云端", ok=False)
            return
        self._set_cloud_status("正在获取云端模型...")

        def worker() -> None:
            try:
                data = list_cloud_models(self.account)
            except CloudApiError as error:
                self.cloud_models_error.emit(str(error))
            else:
                self.cloud_models_loaded.emit(data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cloud_models_loaded(self, data: list) -> None:
        self.cloud_all_models = list(data)
        self._render_cloud_models()

    def _render_cloud_models(self) -> None:
        """按当前模型类型过滤并刷新云端模型列表。"""
        kind = self._current_cloud_kind()
        self.cloud_models = [item for item in self.cloud_all_models if item.get("kind") == kind]
        self.cloud_model_list.clear()
        if not self.cloud_models:
            total = len(self.cloud_all_models)
            if total == 0:
                self._set_cloud_status("云端暂无模型")
            else:
                self._set_cloud_status(f"当前类型暂无云端模型（共 {total} 个）")
            return
        for item in self.cloud_models:
            size_kb = float(item.get("size", 0)) / 1024.0
            self.cloud_model_list.addItem(
                f"{item.get('name', '')}  [{item.get('kind', '')}]  {size_kb:.1f} KB"
            )
        total = len(self.cloud_all_models)
        if total != len(self.cloud_models):
            self._set_cloud_status(f"显示 {len(self.cloud_models)} 个，共 {total} 个云端模型")
        else:
            self._set_cloud_status(f"共 {len(self.cloud_models)} 个云端模型")

    def _on_cloud_kind_changed(self, index: int) -> None:
        self._render_cloud_models()

    def _current_cloud_kind(self) -> str:
        tabs = getattr(self, "cloud_kind_tabs", None)
        if tabs is None or tabs.currentIndex() < 0:
            return "live2d"
        return ("live2d", "vrm", "rvc")[min(tabs.currentIndex(), 2)]

    def _on_cloud_models_error(self, message: str) -> None:
        self._set_cloud_status(f"获取云端模型失败：{message}", ok=False)

    def _on_cloud_action_done(self, message: str) -> None:
        self._set_cloud_status(message)
        self._refresh_cloud_models()
        self._refresh_cloud_presets()

    def _on_cloud_action_error(self, message: str) -> None:
        self._set_cloud_status(message, ok=False)

    @staticmethod
    def _preset_kind_value(label: str) -> str:
        return {
            "模型参数方案": "param",
            "完整配置方案": "config",
            "系统设置方案": "system",  # 兼容旧方案
        }.get(label, "config")

    def _current_preset_kind(self) -> str:
        tabs = getattr(self, "preset_kind_tabs", None)
        if tabs is None or tabs.currentIndex() < 0:
            return "param"
        return self._preset_kind_value(tabs.tabText(tabs.currentIndex()))

    def _refresh_cloud_presets(self) -> None:
        if getattr(self, "cloud_preset_list", None) is None:
            return
        if self.offline:
            self._set_cloud_status("离线模式，无法访问云端", ok=False)
            return
        kind = self._current_preset_kind()
        self._set_cloud_status("正在获取云端方案...")

        def worker() -> None:
            try:
                data = list_cloud_presets(self.account, kind)
            except CloudApiError as error:
                self.cloud_presets_error.emit(str(error))
            else:
                self.cloud_presets_loaded.emit(data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cloud_presets_loaded(self, data: list) -> None:
        self.cloud_presets = list(data)
        self._render_cloud_presets()

    def _render_cloud_presets(self) -> None:
        self.cloud_preset_list.clear()
        if not self.cloud_presets:
            self._set_cloud_status("云端暂无该类型方案")
            return
        for item in self.cloud_presets:
            self.cloud_preset_list.addItem(item.get("name", ""))
        total = len(self.cloud_presets)
        self._set_cloud_status(f"共 {total} 个云端方案")

    def _on_cloud_presets_error(self, message: str) -> None:
        self._set_cloud_status(f"获取云端方案失败：{message}", ok=False)

    def _on_preset_kind_changed(self, index: int) -> None:
        self._refresh_cloud_presets()

    def _build_preset_content(self, kind: str) -> dict:
        motion = self.motion_settings
        if kind == "param":
            return {"params": motion.get("params", {})}
        # 完整配置方案：动捕设置 + 系统设置
        content = dict(motion)
        content.update(
            {
                "scheme_name": self.system_settings.get("scheme_name", ""),
                "video_resolution": self.system_settings.get("video_resolution", ""),
                "video_fps": self.system_settings.get("video_fps", 60),
                "audio_sample_rate": self.system_settings.get("audio_sample_rate", ""),
                "audio_engine": self.system_settings.get("audio_engine", ""),
            }
        )
        return content

    def _upload_current_preset(self) -> None:
        if self.offline:
            self._set_cloud_status("离线模式，无法上传", ok=False)
            return
        name = self.preset_name_edit.text().strip()
        if not name:
            show_info(self, "星弦", "请输入方案名称")
            return
        kind = self._current_preset_kind()
        content = self._build_preset_content(kind)
        payload = json.dumps(content, ensure_ascii=False)
        self._set_cloud_status(f"正在上传方案 {name}...")

        def worker() -> None:
            try:
                upload_cloud_preset(self.account, kind, name, payload)
            except CloudApiError as error:
                self.cloud_action_error.emit(str(error))
            else:
                self.cloud_action_done.emit(f"已上传方案：{name}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_cloud_preset(self) -> None:
        if self.offline:
            self._set_cloud_status("离线模式，无法操作云端", ok=False)
            return
        index = self.cloud_preset_list.currentRow()
        if index < 0 or index >= len(self.cloud_presets):
            show_info(self, "星弦", "请先选择一个云端方案")
            return
        preset = self.cloud_presets[index]
        name = preset.get("name", "")
        try:
            content = json.loads(preset.get("content", "{}"))
        except (json.JSONDecodeError, TypeError):
            show_warning(self, "星弦", "方案内容损坏，无法应用")
            return
        kind = preset.get("kind", "config")
        self._apply_preset_content(kind, content)
        show_info(self, "星弦", f"已应用方案：{name}")

    def _apply_preset_content(self, kind: str, content: dict) -> None:
        motion = self.motion_settings
        if not isinstance(content, dict):
            content = {}
        if kind == "param":
            motion["params"] = content.get("params", {})
        elif kind == "system":
            for key in ("camera_index", "mirror", "lr_mirror", "sensitivity", "engine", "drive_enabled"):
                if key in content:
                    motion[key] = content[key]
            for key in ("scheme_name", "video_resolution", "video_fps", "audio_sample_rate", "audio_engine"):
                if key in content:
                    self.system_settings[key] = content[key]
        else:
            for key, value in content.items():
                if key in ("camera_index", "mirror", "lr_mirror", "sensitivity", "engine", "drive_enabled"):
                    motion[key] = value
                elif key in ("scheme_name", "video_resolution", "video_fps", "audio_sample_rate", "audio_engine"):
                    self.system_settings[key] = value
                else:
                    motion[key] = value
        self._save_motion_settings()
        self._save_system_settings()
        self.motion_capture.set_drive_params(motion.get("params", {}))
        self.motion_capture.set_hand_enabled(bool(motion.get("hand_enabled", True)))
        self.motion_capture.set_gesture_enabled(bool(motion.get("gesture_enabled", True)))
        self._refresh_drive_params_card()
        self._refresh_system_settings_view()
        self._refresh_gesture_ui()
        self._sync_camera_combos()

    def _delete_cloud_preset(self) -> None:
        if self.offline:
            self._set_cloud_status("离线模式，无法操作云端", ok=False)
            return
        index = self.cloud_preset_list.currentRow()
        if index < 0 or index >= len(self.cloud_presets):
            show_info(self, "星弦", "请先选择一个云端方案")
            return
        preset = self.cloud_presets[index]
        name = preset.get("name", "")
        answer = QMessageBox.question(
            self,
            "星弦",
            f"确认删除云端方案 {name}？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_cloud_status(f"正在删除方案 {name}...")

        def worker() -> None:
            try:
                delete_cloud_preset(preset.get("id"), self.account)
            except CloudApiError as error:
                self.cloud_action_error.emit(str(error))
            else:
                self.cloud_action_done.emit(f"已删除方案：{name}")

        threading.Thread(target=worker, daemon=True).start()

    def _set_cloud_status(self, text: str, ok: bool = True) -> None:
        label = getattr(self, "cloud_status", None)
        if label is not None:
            label.setText(text)
            label.setStyleSheet("color: #7EE7FF;" if ok else "color: #FF7E7E;")

    def _upload_cloud_model(self) -> None:
        if self.offline:
            self._set_cloud_status("离线模式，无法上传", ok=False)
            return
        kind = self._current_cloud_kind()
        filters = {
            "live2d": "Live2D (*.model3.json *.zip);;所有文件 (*)",
            "vrm": "VRM (*.vrm);;所有文件 (*)",
            "rvc": "RVC (*.pth *.index *.json);;所有文件 (*)",
        }
        path, _ = QFileDialog.getOpenFileName(
            self,
            "上传模型到云端",
            "",
            filters.get(kind, "所有文件 (*)"),
        )
        if not path:
            return
        name = Path(path).stem
        self._set_cloud_status("正在上传模型...")

        def worker() -> None:
            try:
                upload_cloud_model(self.account, kind, name, path)
            except CloudApiError as error:
                self.cloud_action_error.emit(str(error))
            else:
                self.cloud_action_done.emit(f"已上传：{name}")

        threading.Thread(target=worker, daemon=True).start()

    def _cloud_action(self, action: str) -> None:
        if self.offline:
            self._set_cloud_status("离线模式，无法操作云端", ok=False)
            return
        index = self.cloud_model_list.currentRow()
        if index < 0 or index >= len(self.cloud_models):
            show_info(self, "星弦", "请先选择一个云端模型")
            return
        model = self.cloud_models[index]
        model_id = model.get("id")
        name = model.get("name", "")

        if action == "delete":
            answer = QMessageBox.question(
                self,
                "星弦",
                f"确认删除云端模型 {name}？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._set_cloud_status(f"正在删除 {name}...")

            def delete_worker() -> None:
                try:
                    delete_cloud_model(model_id, self.account)
                except CloudApiError as error:
                    self.cloud_action_error.emit(str(error))
                else:
                    self.cloud_action_done.emit(f"已删除：{name}")

            threading.Thread(target=delete_worker, daemon=True).start()
            return

        if action == "download":
            self._set_cloud_status(f"正在下载 {name}...")
            self._download_and_import_cloud(model, enable=False)
        elif action == "enable":
            self._set_cloud_status(f"正在下载并启用 {name}...")
            self._download_and_import_cloud(model, enable=True)

    def _download_and_import_cloud(self, model: dict, enable: bool) -> None:
        kind = model.get("kind", "")
        original = model.get("originalFilename", "")
        model_id = model.get("id")

        def worker() -> None:
            try:
                content = download_cloud_model(model_id, self.account)
            except CloudApiError as error:
                self.cloud_action_error.emit(str(error))
                return
            try:
                suffix = Path(original).suffix
            except Exception:
                suffix = ""
            tmp = Path(self.model_store.models_dir) / f"_cloud_{model_id}{suffix}"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            try:
                tmp.write_bytes(content)
                if kind == "live2d":
                    entry = self.model_store.import_live2d(tmp)
                elif kind == "vrm":
                    entry = self.model_store.import_vrm(tmp)
                elif kind == "rvc":
                    entry = self.model_store.import_rvc([tmp])
                else:
                    self.cloud_action_error.emit("不支持的模型类型")
                    return
            except Exception as error:
                self.cloud_action_error.emit(f"导入本地模型失败：{error}")
                return
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

            self.model_entries = self.model_store.load()
            if enable:
                self.model_entries = self.model_store.set_active(kind, entry.name)
            self._refresh_model_list(kind)
            action_word = "启用" if enable else "下载"
            self.cloud_action_done.emit(f"已{action_word}：{entry.name}")

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_model_list(self, kind: str) -> None:
        model_list = getattr(self, "model_lists", {}).get(kind)
        if model_list is not None:
            model_list.clear()
            entries = [entry for entry in self.model_entries if entry.kind == kind]
            running = getattr(self, "_avatar_running", False)
            for entry in entries:
                suffix = " [使用中]" if (entry.active and running) else ""
                model_list.addItem(f"{entry.name}{suffix}")
        if kind == "live2d":
            self._refresh_live2d_page()
        elif kind == "vrm":
            self._refresh_vrm_page()
        elif kind == "rvc":
            # 导入/删除 RVC 模型后，同步刷新音频变声页与首页的模型下拉
            self._refresh_rvc_model_list()

    def _refresh_vrm_page(self) -> None:
        """刷新 VRM 页面的模型列表"""
        self._refresh_avatar_model_list()
        # 只有在模型已启动时才加载到视图，否则清除避免残留显示
        active = self._active_vrm_entry()
        if active and hasattr(self, "avatar_vrm_view") and getattr(self, "_avatar_running", False):
            self.avatar_vrm_view.load_model(active.path)
        elif hasattr(self, "avatar_vrm_view"):
            self.avatar_vrm_view.clear_model()

    def _import_model(self, kind: str) -> None:
        if kind == "live2d":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 Live2D 模型",
                "",
                "Live2D (*.model3.json *.zip);;所有文件 (*)",
            )
            if not path:
                return
            self.model_store.import_live2d(Path(path))
        elif kind == "vrm":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 VRM 模型",
                "",
                "VRM (*.vrm);;所有文件 (*)",
            )
            if not path:
                return
            # 添加 VRM 导入方法（需要在 ModelStore 中实现）
            if hasattr(self.model_store, 'import_vrm'):
                self.model_store.import_vrm(Path(path))
            else:
                show_warning(self, "功能提示", "VRM 导入功能正在开发中")
        else:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "选择 RVC 模型文件",
                "",
                "RVC (*.pth *.index *.json);;所有文件 (*)",
            )
            if not paths:
                return
            self.model_store.import_rvc([Path(path) for path in paths])

        self.model_entries = self.model_store.load()
        self._refresh_model_list(kind)

    def _use_model(self, kind: str) -> None:
        model_list = getattr(self, "model_lists", {}).get(kind)
        if model_list is None or model_list.currentItem() is None:
            show_info(self, "星弦", "请先选择一个模型")
            return
        name = model_list.currentItem().text().split(" [")[0]
        self.model_entries = self.model_store.set_active(kind, name)
        self._refresh_model_list(kind)
        show_info(self, "星弦", f"已选择：{name}")

    def _rename_model(self, kind: str) -> None:
        model_list = getattr(self, "model_lists", {}).get(kind)
        if model_list is None or model_list.currentItem() is None:
            show_info(self, "星弦", "请先选择一个模型")
            return
        old_name = model_list.currentItem().text().split(" [")[0]
        new_name, ok = QInputDialog.getText(
            self,
            "重命名模型",
            "新的模型名称：",
            text=old_name,
        )
        if not ok or not new_name or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        self.model_entries = self.model_store.rename(kind, old_name, new_name)
        self._refresh_model_list(kind)
        show_info(self, "星弦", f"已重命名为：{new_name}")

    def _delete_model(self, kind: str) -> None:
        model_list = getattr(self, "model_lists", {}).get(kind)
        if model_list is None or model_list.currentItem() is None:
            show_info(self, "星弦", "请先选择一个模型")
            return
        name = model_list.currentItem().text().split(" [")[0]
        self.model_entries = self.model_store.remove(name)
        self._refresh_model_list(kind)

    # ---- RVC 变声功能 ----

    def _load_rvc_settings(self) -> None:
        """从持久化存储加载 RVC 设置并应用到 UI 控件"""
        try:
            rvc = self.settings_store.load_rvc()
        except Exception:
            return

        # 滑条控件
        self.rvc_pitch_shift.slider.setValue(int(rvc.get("pitch_shift", 0)))
        self.rvc_index_rate.slider.setValue(int(rvc.get("index_rate", 75)))
        self.rvc_filter_radius.slider.setValue(int(rvc.get("filter_radius", 3)))
        self.rvc_rms_mix_rate.slider.setValue(int(rvc.get("rms_mix_rate", 25)))
        gate = int(rvc.get("gate_threshold", 0))
        self.rvc_gate_threshold.slider.setValue(gate)
        self._rvc_gate_threshold = gate

        # 下拉框
        f0_method = rvc.get("f0_method", "pm")
        # harvest 在实时场景过慢（转换跟不上会丢字/卡顿）；rmvpe/crepe 依赖
        # 未安装时会静默回退，这里统一映射到当前环境可用且快的 pm
        if f0_method in ("harvest", "rmvpe", "crepe", "mangio-crepe", "fcpe"):
            from app.services.rvc_service import f0_method_available
            if not f0_method_available(f0_method):
                f0_method = "pm"
        idx = self.rvc_f0_method.findText(f0_method)
        if idx >= 0:
            self.rvc_f0_method.setCurrentIndex(idx)

        resample_sr = str(rvc.get("resample_sr", "0"))
        idx = self.rvc_resample_sr.findText(resample_sr)
        if idx >= 0:
            self.rvc_resample_sr.setCurrentIndex(idx)

        # 复选框
        self.rvc_protect_voiceless.setChecked(bool(rvc.get("protect_voiceless", True)))
        self.rvc_is_half.setChecked(bool(rvc.get("is_half", True)))
        denoise = bool(rvc.get("denoise", False))
        self.rvc_denoise.setChecked(denoise)
        self._rvc_denoise = denoise

        # 音频设备（按名称匹配）
        input_name = rvc.get("input_device_name", "")
        output_name = rvc.get("output_device_name", "")
        if input_name:
            for i in range(self.rvc_input_device.count()):
                if self.rvc_input_device.itemText(i) == input_name:
                    self.rvc_input_device.setCurrentIndex(i)
                    break
        if output_name:
            for i in range(self.rvc_output_device.count()):
                if self.rvc_output_device.itemText(i) == output_name:
                    self.rvc_output_device.setCurrentIndex(i)
                    break

    def _save_rvc_settings(self) -> None:
        """将当前 RVC UI 控件的值保存到持久化存储"""
        try:
            input_name = self.rvc_input_device.currentText() if self.rvc_input_device.count() > 0 else ""
            output_name = self.rvc_output_device.currentText() if self.rvc_output_device.count() > 0 else ""

            rvc = {
                "pitch_shift": self.rvc_pitch_shift.value(),
                "f0_method": self.rvc_f0_method.currentText(),
                "index_rate": self.rvc_index_rate.value(),
                "filter_radius": self.rvc_filter_radius.value(),
                "rms_mix_rate": self.rvc_rms_mix_rate.value(),
                "resample_sr": self.rvc_resample_sr.currentText(),
                "protect_voiceless": self.rvc_protect_voiceless.isChecked(),
                "is_half": self.rvc_is_half.isChecked(),
                "gate_threshold": self.rvc_gate_threshold.value(),
                "denoise": self.rvc_denoise.isChecked(),
                "input_device_name": input_name,
                "output_device_name": output_name,
            }
            self.settings_store.save_rvc(rvc)
        except Exception as e:
            print(f"保存RVC设置失败: {e}")

    def _on_rvc_gate_changed(self, value: int) -> None:
        self._rvc_gate_threshold = int(value)
        self._save_rvc_settings()

    def _on_rvc_denoise_changed(self, state) -> None:
        self._rvc_denoise = bool(state)
        self._save_rvc_settings()

    def _refresh_rvc_model_list(self) -> None:
        combo = getattr(self, "rvc_model_combo", None)
        if combo is not None:
            combo.clear()
            rvc_models = [entry for entry in self.model_entries if entry.kind == "rvc"]
            for model in rvc_models:
                status = "●" if model.active else ""
                display_text = f"{model.name} {status}"
                combo.addItem(display_text, model.name)
        self._refresh_home_rvc_model_list()

    def _refresh_audio_devices(self) -> None:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            # 记住当前已选设备，刷新后恢复，避免重新选择
            input_name = (
                self.rvc_input_device.currentText()
                if self.rvc_input_device.count() > 0
                else ""
            )
            output_name = (
                self.rvc_output_device.currentText()
                if self.rvc_output_device.count() > 0
                else ""
            )
            if not input_name or not output_name:
                rvc = self.settings_store.load_rvc()
                input_name = input_name or rvc.get("input_device_name", "")
                output_name = output_name or rvc.get("output_device_name", "")

            input_map, output_map = self._device_maps(devices)

            # 刷新期间阻止触发保存，避免清空已选设备
            self._populate_device_combo(self.rvc_input_device, input_map, input_name)
            self._populate_device_combo(self.rvc_output_device, output_map, output_name)
            self._populate_device_combo(
                getattr(self, "home_rvc_input_device", None), input_map, input_name
            )
            self._populate_device_combo(
                getattr(self, "home_rvc_output_device", None), output_map, output_name
            )
            self._save_rvc_settings()

        except ImportError:
            pass
        except Exception as e:
            pass

    def _setup_virtual_audio(self) -> None:
        """一键启用虚拟声卡：检测到就自动配置；没检测到就引导安装内置的 VB-Cable。"""
        self._refresh_audio_devices()
        found = self._find_virtual_cable_index()
        if found >= 0:
            device_name = self.rvc_output_device.itemText(found)
            self.rvc_output_device.setCurrentIndex(found)
            self._save_rvc_settings()
            self._set_audio_hint(
                f"已把输出设备设为：{device_name}。回到要实时变声的软件里，"
                "把它的麦克风选成同一个虚拟声卡的输出端（如 CABLE Output），别人即可听到变声。"
            )
            return

        # 已装驱动但设备未生效（往往需重启），不要重复启动安装程序，避免“Remove Driver”循环
        if self._is_vbcable_installed():
            self._set_audio_hint(
                "VB-Cable 驱动已安装，但设备尚未生效。请先重启系统，"
                "重启后设备会出现在列表里；之后点“一键启用虚拟声卡”即可自动配置。"
            )
            return

        installer = self._prepare_vbcable_installer()
        if installer is None:
            self._set_audio_hint(
                "未检测到虚拟声卡，且未找到内置的 VB-Cable 安装包。请联网后重试，"
                "或手动下载 VB-Cable 后再次点击。",
                ok=False,
            )
            return

        if self._launch_elevated(installer):
            self._set_audio_hint(
                "已启动 VB-Cable 安装程序。请按提示完成安装（可能需要管理员权限，个别情况需重启），"
                "完成后回来点一下“一键启用虚拟声卡”即可自动配置。"
            )
        else:
            self._set_audio_hint(
                "无法自动启动 VB-Cable 安装程序，请手动以管理员身份运行安装包。",
                ok=False,
            )

    def _find_virtual_cable_index(self) -> int:
        """在输出设备里查找虚拟声卡（VB-Cable / VoiceMeeter 等）。"""
        target_names = [
            "cable input", "cable a", "cable b",
            "vb-audio", "vb cable", "virtual cable", "voice meeter",
        ]
        for i in range(self.rvc_output_device.count()):
            name = self.rvc_output_device.itemText(i).lower()
            if any(target in name for target in target_names):
                return i
        return -1

    def _is_vbcable_installed(self) -> bool:
        """检查系统是否已安装 VB-Cable 驱动（驱动仓库或驱动目录）。"""
        try:
            system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            # Windows 驱动仓库里会出现 vbMmeCable / vbaudio / vbcable 的驱动包
            file_repo = system_root / "System32" / "DriverStore" / "FileRepository"
            if file_repo.exists():
                for child in file_repo.iterdir():
                    name = child.name.lower()
                    if "vbmmecable" in name or "vbaudio" in name or "vbcable" in name:
                        return True
            # 驱动目录里已落盘的 sys 文件
            drivers_dir = system_root / "System32" / "drivers"
            for name in ("vbMmeCable64_win10.sys", "vbaudio_cable64_win10.sys", "vbaudio_cable_win7.sys"):
                if (drivers_dir / name).exists():
                    return True
            return False
        except Exception:
            return False

    def _prepare_vbcable_installer(self) -> Path | None:
        """把随应用打包的 VB-Cable 安装程序解压出来，返回其路径。"""
        candidates = [
            RESOURCES_DIR / "vbcable" / "VBCABLE_Driver_Pack45.zip",
            Path(__file__).resolve().parents[2] / "resources" / "vbcable" / "VBCABLE_Driver_Pack45.zip",
        ]
        zip_path = next((candidate for candidate in candidates if candidate.exists()), None)
        if zip_path is None:
            return None
        try:
            import struct
            import zipfile
            is_64 = struct.calcsize("P") * 8 == 64
            setup_name = "VBCABLE_Setup_x64.exe" if is_64 else "VBCABLE_Setup.exe"
            target_dir = Path.home() / ".star_string" / "vbcable"
            target_dir.mkdir(parents=True, exist_ok=True)
            # 安装程序需要同目录下的 .inf/.sys/.cat 驱动文件，必须解压整个驱动包
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(target_dir)
            setup_path = target_dir / setup_name
            return setup_path if setup_path.exists() else None
        except Exception:
            return None

    @staticmethod
    def _launch_elevated(exe: Path) -> bool:
        """以管理员权限启动安装程序（Windows）。"""
        try:
            import ctypes
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(exe), None, None, 1
            )
            return result > 32
        except Exception:
            return False

    def _set_audio_hint(self, text: str, ok: bool = True) -> None:
        label = getattr(self, "rvc_audio_hint", None)
        if label is not None:
            label.setText(text)
            label.setStyleSheet("color: #7EE7FF;" if ok else "color: #FFC36B;")

    def _set_rvc_mode(self, running: bool) -> None:
        """首页 RVC：未启动显示设备选择，运行中切换为音量监听。"""
        stack = getattr(self, "home_rvc_stack", None)
        if stack is not None:
            stack.setCurrentIndex(1 if running else 0)

    def _on_rvc_status_changed(self, text: str, running: bool) -> None:
        """工作线程通过信号更新 RVC 状态与按钮（主线程执行）。"""
        self._set_rvc_mode(running)
        label = getattr(self, "rvc_status", None)
        if label is not None:
            label.setText(text)
        home_status = getattr(self, "home_rvc_status", None)
        if home_status is not None:
            home_status.setText(text)
        if hasattr(self, "rvc_start_button"):
            self.rvc_start_button.show() if not running else self.rvc_start_button.hide()
        if hasattr(self, "rvc_stop_button"):
            self.rvc_stop_button.hide() if not running else self.rvc_stop_button.show()
        home_start = getattr(self, "home_rvc_start_button", None)
        if home_start is not None:
            home_start.show() if not running else home_start.hide()
        home_stop = getattr(self, "home_rvc_stop_button", None)
        if home_stop is not None:
            home_stop.hide() if not running else home_stop.show()

    def _on_rvc_start(self, combo: QComboBox | None = None) -> None:
        try:
            combo = combo or self.rvc_model_combo
            if combo.currentIndex() < 0 or combo.currentData() is None:
                show_info(self, "星弦", "请先选择一个RVC模型")
                return

            model_name = combo.currentData()

            # 首次启动时自动刷新设备，避免未进入音频变声页就无设备可选
            if (
                getattr(self, "rvc_input_device", None) is not None
                and self.rvc_input_device.count() == 0
                and getattr(self, "rvc_output_device", None) is not None
                and self.rvc_output_device.count() == 0
            ):
                self._refresh_audio_devices()

            # 检查设备选择，如果设备列表为空则提示刷新
            if self.rvc_input_device.count() == 0 or self.rvc_output_device.count() == 0:
                show_info(self, "星弦", "请先刷新设备列表")
                return

            input_device_idx = self.rvc_input_device.currentData()
            output_device_idx = self.rvc_output_device.currentData()

            if input_device_idx is None or output_device_idx is None:
                show_info(self, "星弦", "请选择输入和输出设备")
                return

            # 查找模型文件路径
            model_entry = None
            for entry in self.model_entries:
                if entry.kind == "rvc" and entry.name == model_name:
                    model_entry = entry
                    break
            if model_entry is None:
                show_info(self, "星弦", "未找到所选模型")
                return

            model_path = model_entry.path
            index_path = model_entry.extra_path or None
            # If extra_path points to a .json config, ignore it for index
            if index_path and not index_path.endswith(".index"):
                index_path = None

            # 获取参数（从滑条控件读取）
            pitch_shift = self.rvc_pitch_shift.value()
            f0_method = self.rvc_f0_method.currentText()
            index_rate = self.rvc_index_rate.value() / 100.0  # 滑条 0-100 -> 0.0-1.0
            filter_radius = self.rvc_filter_radius.value()
            rms_mix_rate = self.rvc_rms_mix_rate.value() / 100.0  # 滑条 0-100 -> 0.0-1.0
            resample_sr = int(self.rvc_resample_sr.currentText())
            is_half = self.rvc_is_half.isChecked()

            # 保存当前设置
            self._save_rvc_settings()

            # 更新UI状态
            self._rvc_running = True
            self.rvc_status.setText("状态：加载模型中...")
            self.rvc_current_model.setText(f"当前模型：{model_name}")
            self.rvc_start_button.hide()
            self.rvc_stop_button.show()
            self._set_rvc_mode(True)
            if hasattr(self, "home_rvc_status"):
                self.home_rvc_status.setText(f"状态：加载模型中...")
            home_start = getattr(self, "home_rvc_start_button", None)
            if home_start is not None:
                home_start.hide()
            home_stop = getattr(self, "home_rvc_stop_button", None)
            if home_stop is not None:
                home_stop.show()

            # 启动音频处理线程（传递所有RVC参数）
            self._start_audio_processing(
                input_device_idx, output_device_idx,
                model_path=model_path,
                index_path=index_path,
                pitch_shift=pitch_shift,
                f0_method=f0_method,
                index_rate=index_rate,
                filter_radius=filter_radius,
                rms_mix_rate=rms_mix_rate,
                resample_sr=resample_sr,
                is_half=is_half,
            )

        except Exception as e:
            show_info(self, "星弦", f"启动失败：{str(e)}")
            self._rvc_running = False
            self.rvc_status.setText("状态：启动失败")
            self.rvc_start_button.show()
            self.rvc_stop_button.hide()
            self._set_rvc_mode(False)
            if hasattr(self, "home_rvc_status"):
                self.home_rvc_status.setText("状态：启动失败")
            home_start = getattr(self, "home_rvc_start_button", None)
            if home_start is not None:
                home_start.show()
            home_stop = getattr(self, "home_rvc_stop_button", None)
            if home_stop is not None:
                home_stop.hide()

    def _on_rvc_stop(self) -> None:
        self._save_rvc_settings()
        self._rvc_running = False
        self.rvc_status.setText("状态：停止中...")
        self._stop_audio_processing()
        self.rvc_status.setText("状态：已停止")
        self.rvc_current_model.setText("当前模型：未选择")
        self.rvc_start_button.show()
        self.rvc_stop_button.hide()
        self._set_rvc_mode(False)
        if hasattr(self, "home_rvc_status"):
            self.home_rvc_status.setText("状态：已停止")
        home_start = getattr(self, "home_rvc_start_button", None)
        if home_start is not None:
            home_start.show()
        home_stop = getattr(self, "home_rvc_stop_button", None)
        if home_stop is not None:
            home_stop.hide()

    def _start_audio_processing(
        self,
        input_device_idx: int,
        output_device_idx: int,
        model_path: str = "",
        index_path: str | None = None,
        pitch_shift: int = 0,
        f0_method: str = "pm",
        index_rate: float = 0.75,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        resample_sr: int = 0,
        is_half: bool = False,
    ) -> None:
        """启动音频处理线程"""
        try:
            import sounddevice as sd

            self._rvc_audio_thread = threading.Thread(
                target=self._audio_worker,
                args=(input_device_idx, output_device_idx),
                kwargs=dict(
                    model_path=model_path,
                    index_path=index_path,
                    pitch_shift=pitch_shift,
                    f0_method=f0_method,
                    index_rate=index_rate,
                    filter_radius=filter_radius,
                    rms_mix_rate=rms_mix_rate,
                    resample_sr=resample_sr,
                    is_half=is_half,
                ),
                daemon=True,
            )
            self._rvc_audio_thread.start()
        except ImportError:
            show_info(self, "星弦", "需要安装 sounddevice 库")
        except Exception as e:
            show_info(self, "星弦", f"音频处理启动失败：{str(e)}")

    def _stop_audio_processing(self) -> None:
        """停止音频处理"""
        self._rvc_running = False
        # 音频流停了就不会再有新的包络输入，先收口避免嘴一直张着
        if getattr(self, "_voice_lipsync", None) is not None:
            self._voice_lipsync.reset()
        if hasattr(self, '_rvc_audio_thread') and self._rvc_audio_thread is not None:
            self._rvc_audio_thread.join(timeout=3.0)
            self._rvc_audio_thread = None

    def _audio_worker(
        self,
        input_device_idx: int,
        output_device_idx: int,
        model_path: str = "",
        index_path: str | None = None,
        pitch_shift: int = 0,
        f0_method: str = "pm",
        index_rate: float = 0.75,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        resample_sr: int = 0,
        is_half: bool = False,
    ) -> None:
        """音频处理工作线程 — 使用RVC引擎进行实时变声"""
        import queue

        try:
            import sounddevice as sd

            # 引擎复用：上次因设备/流问题启动失败后再次点击，不再重新加载模型
            use_half = bool(is_half)
            try:
                import torch

                # CPU 上不做半精度：又慢又容易产生杂音/失真
                use_half = use_half and torch.cuda.is_available()
            except Exception:
                use_half = False
            cache_key = (model_path, index_path or "", use_half)
            engine = getattr(self, "_rvc_engine", None)
            if engine is None or getattr(self, "_rvc_engine_key", None) != cache_key:
                engine = RVCEngine()
                try:
                    engine.load_model(
                        model_path=model_path,
                        index_path=index_path,
                        is_half=use_half,
                    )
                except Exception as e:
                    print(f"RVC模型加载失败: {e}")
                    self.rvc_status_changed.emit("状态：模型加载失败", False)
                    return
                self._rvc_engine = engine
                self._rvc_engine_key = cache_key
            self._noise_floor = None

            sample_rate = engine.sample_rate
            # 设备可能已被拔出/禁用：建流前校验索引，失效则回退系统默认设备
            input_device_idx = self._resolve_device_index(
                sd, input_device_idx, "input"
            )
            output_device_idx = self._resolve_device_index(
                sd, output_device_idx, "output"
            )
            stream_rate = self._pick_stream_rate(
                sd, input_device_idx, output_device_idx, sample_rate
            )
            # 处理窗取 3 个 gram，按 50% 重叠推进（每步只输出后半段）：
            # 短块会让 RVC 特征不稳、端部产生伪影，重叠处理后吐字明显更清楚。
            window = _gram_sample_length(sample_rate) * 3
            hop = max(1, window // 2)
            chunk_size = window
            stream_chunk = max(1, int(round(hop * stream_rate / sample_rate)))

            # 预热：首次推理要加载 hubert/f0 模型并做 CUDA 初始化（可能数秒），
            # 不预热的话启动后的第一批音频会断/杂。
            self.rvc_status_changed.emit("状态：预热模型中…", True)
            try:
                warm_t = np.arange(chunk_size, dtype=np.float32) / float(sample_rate)
                warm_audio = (0.1 * np.sin(2.0 * np.pi * 200.0 * warm_t)).astype(
                    np.float32
                )
                engine.convert_chunk(
                    warm_audio,
                    pitch_shift=0,
                    f0_method=f0_method,
                    index_rate=0.0,
                    rms_mix_rate=0.5,
                    resample_sr=0,
                    filter_radius=filter_radius,
                )
            except Exception as error:  # noqa: BLE001
                print(f"RVC预热失败: {error}")

            # 通过信号在主线更新状态
            self.rvc_status_changed.emit("状态：运行中", True)

            input_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=2)
            output_q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=2)

            crossfade = max(1, int(sample_rate * 0.02))  # 20ms 输出交叉淡化
            previous = {"tail": None}

            def convert_worker() -> None:
                buffer = np.zeros(0, dtype=np.float32)
                while self._rvc_running:
                    try:
                        new_audio = input_q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    except Exception:
                        break
                    buffer = (
                        np.concatenate([buffer, new_audio])
                        if buffer.size
                        else np.asarray(new_audio, dtype=np.float32)
                    )
                    while buffer.size >= window and self._rvc_running:
                        segment = buffer[:window].copy()
                        buffer = buffer[hop:]
                        try:
                            if getattr(self, "_rvc_denoise", False):
                                segment = self._denoise_audio(segment)
                            audio_out = engine.convert_chunk(
                                segment,
                                pitch_shift=pitch_shift,
                                f0_method=f0_method,
                                index_rate=index_rate,
                                rms_mix_rate=rms_mix_rate,
                                # 实时链路固定按模型采样率输出，交给输出流统一重采样，
                                # 否则返回的采样率与播放采样率不一致会造成变调/卡顿。
                                resample_sr=0,
                                filter_radius=filter_radius,
                            )
                        except Exception as e:
                            print(f"RVC处理异常: {e}")
                            audio_out = segment
                        audio_out = np.asarray(audio_out, dtype=np.float32)
                        # 取后半段输出（前一半是重叠区，端部伪影不进结果）
                        if len(audio_out) >= hop * 2:
                            piece = audio_out[hop : hop * 2].copy()
                        else:
                            piece = audio_out[hop:].copy()
                        if piece.size == 0:
                            continue
                        tail = previous.get("tail")
                        if tail is not None and len(piece) > crossfade:
                            fade = np.linspace(0.0, 1.0, crossfade, dtype=np.float32)
                            piece[:crossfade] = (
                                piece[:crossfade] * fade + tail * (1.0 - fade)
                            )
                        if len(piece) >= crossfade:
                            previous["tail"] = piece[-crossfade:].copy()
                        try:
                            output_q.get_nowait()  # 丢弃最旧，保证实时
                        except queue.Empty:
                            pass
                        try:
                            output_q.put_nowait(piece)
                        except queue.Full:
                            pass

            conv_thread = threading.Thread(target=convert_worker, daemon=True)
            conv_thread.start()

            volumes = {"in": 0, "out": 0, "speaking": True}
            gate = {"gain": 1.0, "target": 1.0}

            def push_input(audio: np.ndarray) -> None:
                try:
                    input_q.put_nowait(audio)
                except queue.Full:
                    try:
                        input_q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        input_q.put_nowait(audio)
                    except queue.Full:
                        pass

            def input_callback(indata, frames, time_info, status):
                if status:
                    print(f"音频输入状态: {status}")
                if not self._rvc_running:
                    return
                audio_in = indata[:, 0].copy().astype(np.float32)
                try:
                    volumes["in"] = min(int(np.sqrt(np.mean(audio_in ** 2)) * 100), 100)
                except Exception:
                    volumes["in"] = 0
                # 语音驱动口型：直接用输入电平取包络，与变声链路是否被门限
                # 静音无关，说话就张嘴、停下就收口
                self._voice_lipsync.feed(audio_in, stream_rate)
                threshold = int(getattr(self, "_rvc_gate_threshold", 0) or 0)
                if threshold <= 0 or volumes["in"] >= threshold:
                    gate["target"] = 1.0
                    speaking = True
                elif gate["gain"] > 0.01:
                    # 正在释放尾音：继续送入，保证平滑收尾
                    gate["target"] = 0.0
                    speaking = True
                else:
                    gate["target"] = 0.0
                    speaking = False
                volumes["speaking"] = speaking
                if speaking:
                    push_input(
                        self._resample_audio(audio_in, stream_rate, sample_rate)
                    )
                self._update_volume_display(volumes["in"], volumes["out"])

            def mixer_output_gain() -> float:
                """调音台弹窗打开时，按实际输出设备查询通道增益/静音。"""
                dlg = getattr(self, "_mixer_dialog", None)
                if dlg is None:
                    return 1.0
                try:
                    name = ""
                    try:
                        name = str(sd.query_devices(output_stream.device)["name"])
                    except Exception:
                        name = str(sd.query_devices(output_device_idx)["name"])
                    return float(dlg.current_output_gain(name))
                except Exception:
                    return 1.0

            def output_callback(outdata, frames, time_info, status):
                if status:
                    print(f"音频输出状态: {status}")
                if not self._rvc_running:
                    outdata.fill(0.0)
                    return
                try:
                    audio_out = output_q.get_nowait()
                except queue.Empty:
                    outdata.fill(0.0)
                    volumes["out"] = 0
                    self._update_volume_display(volumes["in"], volumes["out"])
                    return
                audio_out = self._resample_audio(audio_out, sample_rate, stream_rate)
                out_len = len(audio_out)
                # 平滑门限增益：快开慢关，逐样本渐变，避免断续和咔哒声
                gain0 = gate["gain"]
                target = gate["target"]
                step = 0.45 if target > gain0 else 0.15
                gain1 = (gain0 + (target - gain0) * step) * mixer_output_gain()
                ramp = np.linspace(gain0 * mixer_output_gain(), gain1, frames, dtype=np.float32)
                if out_len >= frames:
                    outdata[:, 0] = audio_out[:frames] * ramp
                else:
                    outdata[:out_len, 0] = audio_out * ramp[:out_len]
                    outdata[out_len:, 0] = 0.0
                gate["gain"] = gain1
                try:
                    volumes["out"] = min(int(np.sqrt(np.mean(outdata[:, 0] ** 2)) * 100), 100)
                except Exception:
                    volumes["out"] = 0
                self._update_volume_display(volumes["in"], volumes["out"])

            # 只填 1 帧静音：缓冲越少延迟/回音越短
            for _ in range(1):
                output_q.put(np.zeros(hop, dtype=np.float32))

            # 输入/输出分开建流：避免不同设备无法组成全双工流（PaErrorCode -9993）
            input_stream = self._open_stream(
                sd,
                sd.InputStream,
                input_device_idx,
                channels=1,
                samplerate=stream_rate,
                blocksize=stream_chunk,
                dtype="float32",
                callback=input_callback,
            )
            output_stream = self._open_stream(
                sd,
                sd.OutputStream,
                output_device_idx,
                channels=1,
                samplerate=stream_rate,
                blocksize=stream_chunk,
                dtype="float32",
                callback=output_callback,
            )
            input_stream.start()
            output_stream.start()
            try:
                while self._rvc_running:
                    sd.sleep(100)
            finally:
                for stream in (input_stream, output_stream):
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass

            conv_thread.join(timeout=1.0)

        except Exception as e:
            print(f"音频处理错误: {str(e)}")
            self.rvc_status_changed.emit(f"状态：音频流启动失败：{str(e)[:80]}", False)

    @staticmethod
    def _resolve_device_index(sd, idx, kind: str):
        """校验设备索引是否仍然有效；失效时回退到系统默认设备。

        设备下拉框里的索引可能是旧快照（设备已拔出/禁用/虚拟声卡卸载），
        直接传给 PortAudio 会得到 Invalid device(-9996) 甚至 host error(-9999)。
        """
        def _valid(i) -> bool:
            try:
                info = sd.query_devices(i)
            except Exception:
                return False
            return bool(info.get(f"max_{kind}_channels", 0))

        if _valid(idx):
            return idx
        try:
            defaults = sd.query_devices(kind=kind)
            default_idx = int(defaults["index"])
            if _valid(default_idx):
                print(f"RVC: {kind} 设备 {idx!r} 已失效，回退默认设备 {default_idx} ({defaults.get('name')})")
                return default_idx
        except Exception:
            pass
        # 最后手段：扫描第一个支持该方向的设备
        try:
            for i, info in enumerate(sd.query_devices()):
                if _valid(i):
                    print(f"RVC: {kind} 设备 {idx!r} 失效，改用设备 {i} ({info.get('name')})")
                    return i
        except Exception:
            pass
        return idx

    @staticmethod
    def _open_stream(sd, stream_cls, dev_idx: int, **kw):
        """打开音频流，失败时逐级回退。

        Windows 上同一物理设备会同时出现在 MME / DirectSound / WASAPI 等接口下，
        MME 报 -9999 host error（蓝牙耳机、虚拟声卡常见）时 WASAPI 往往正常；
        设备被拔出/禁用则索引直接 -9996 invalid device。
        顺序：原索引 → 同名/前缀匹配的其他接口条目（优先 WASAPI）→ 系统默认设备。
        注意 MME 设备名会被截断到 31 字符，因此用前缀匹配。
        """
        attempts: list[int] = []
        try:
            if dev_idx is not None and dev_idx >= 0:
                attempts.append(int(dev_idx))
                name = str(sd.query_devices(int(dev_idx)).get("name", ""))[:24]
                if name:
                    ranked = []
                    for i, info in enumerate(sd.query_devices()):
                        if i in attempts:
                            continue
                        if str(info.get("name", ""))[:24] == name:
                            # WASAPI（通常排在后、独占共享混合模式最稳）优先尝试
                            ranked.append((1, i))
                        else:
                            continue
                    attempts.extend(i for _, i in sorted(ranked, key=lambda t: -t[1]))
        except Exception:
            pass
        attempts.append(-1)  # 系统默认设备
        last_err: Exception | None = None
        for cand in attempts:
            try:
                return stream_cls(device=None if cand == -1 else cand, **kw)
            except Exception as err:
                last_err = err
                print(f"RVC: 音频设备 {cand} 打开失败({err})，尝试回退…")
                continue
        raise last_err

    @staticmethod
    def _pick_stream_rate(sd, input_device_idx, output_device_idx, preferred: int) -> int:
        """选择输入/输出设备都支持的采样率，避免采样率不匹配导致建流失败。"""
        candidates: list[int] = []
        # 优先设备原生采样率（48k/44.1k），由本程序做高质量重采样；
        # 直接用非标采样率（如 40000）时部分后端会做低质量重采样，导致发闷/杂音。
        for rate in (48000, 44100, preferred):
            if rate and int(rate) not in candidates:
                candidates.append(int(rate))
        for rate in candidates:
            try:
                sd.check_input_settings(
                    device=input_device_idx,
                    channels=1,
                    samplerate=rate,
                    dtype="float32",
                )
                sd.check_output_settings(
                    device=output_device_idx,
                    channels=1,
                    samplerate=rate,
                    dtype="float32",
                )
                return rate
            except Exception:
                continue
        try:
            info = sd.query_devices(input_device_idx)
            default_rate = int(info.get("default_samplerate") or preferred)
            if default_rate:
                return default_rate
        except Exception:
            pass
        return int(preferred)

    @staticmethod
    def _resample_audio(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        """在音频流采样率与模型采样率之间转换。"""
        if src_rate == dst_rate or audio.size == 0:
            return audio
        try:
            from math import gcd
            from scipy.signal import resample_poly

            divisor = gcd(int(src_rate), int(dst_rate))
            return resample_poly(
                audio,
                int(dst_rate) // divisor,
                int(src_rate) // divisor,
            ).astype(np.float32)
        except Exception:
            return audio

    def _denoise_audio(self, audio: np.ndarray) -> np.ndarray:
        """轻量谱减降噪：抑制较稳定的背景底噪（如风扇、电流声）。"""
        try:
            from scipy.signal import istft, stft
        except Exception:
            return audio
        try:
            nperseg = 256
            noverlap = nperseg * 3 // 4
            _, _, spec = stft(audio, nperseg=nperseg, noverlap=noverlap)
            magnitude = np.abs(spec)
            current = magnitude.mean(axis=1, keepdims=True)
            floor = getattr(self, "_noise_floor", None)
            if floor is None or getattr(floor, "shape", None) != current.shape:
                floor = current
            else:
                # 只在安静帧更新底噪，避免把说话声当成噪声
                quiet = current < (floor * 2.0 + 1e-6)
                floor = np.where(quiet, 0.9 * floor + 0.1 * current, floor)
            self._noise_floor = floor
            # 保守掩码：最多衰减到 20%，避免把语音也一起削掉导致听不清
            reduced = np.maximum(magnitude - floor, 0.0)
            mask = np.clip(reduced / (magnitude + 1e-9), 0.2, 1.0)
            _, cleaned = istft(spec * mask, nperseg=nperseg, noverlap=noverlap)
            cleaned = np.asarray(cleaned, dtype=np.float32)[: len(audio)]
            if len(cleaned) < len(audio):
                cleaned = np.pad(cleaned, (0, len(audio) - len(cleaned)))
            return cleaned
        except Exception:
            return audio

    def _update_volume_display(self, input_volume: int, output_volume: int) -> None:
        """更新音量显示：做快升慢降平滑并限帧，避免音量条一顿一顿。"""
        now = time.monotonic()
        self._smooth_in = self._approach(self._smooth_in, input_volume)
        self._smooth_out = self._approach(self._smooth_out, output_volume)
        if now - self._last_volume_emit < 0.06:
            return
        self._last_volume_emit = now
        self.rvc_volume_updated.emit(
            int(round(self._smooth_in)),
            int(round(self._smooth_out)),
        )

    @staticmethod
    def _approach(current: float, target: float) -> float:
        """上升快、下降慢，让音量表更平滑。"""
        if target >= current:
            return current + (target - current) * 0.55
        return current + (target - current) * 0.18

    def _on_rvc_volume_updated(self, input_volume: int, output_volume: int) -> None:
        """在主线程中更新所有音量监听表（音频页 + 首页）。"""
        for prefix in ("rvc", "home_rvc"):
            in_bar = getattr(self, f"{prefix}_input_volume_bar", None)
            if in_bar is not None:
                in_bar.setValue(input_volume)
            in_label = getattr(self, f"{prefix}_input_volume_label", None)
            if in_label is not None:
                in_label.setText(f"{input_volume}%")
            out_bar = getattr(self, f"{prefix}_output_volume_bar", None)
            if out_bar is not None:
                out_bar.setValue(output_volume)
            out_label = getattr(self, f"{prefix}_output_volume_label", None)
            if out_label is not None:
                out_label.setText(f"{output_volume}%")
