from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.services.auth_service import LoginError, get_profile, update_profile
from app.services.model_store import ModelStore
from app.services.motion_capture import MotionCapture
from app.services.settings_store import SettingsStore
from app.ui.dialogs import show_info, show_warning
from app.ui.live2d_view import Live2DView


RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
LOGO_PATH = RESOURCES_DIR / "images" / "star_logo.png"
ICON_PATH = RESOURCES_DIR / "images" / "star_logo.ico"

NAV_ITEMS = ["首页", "视频动捕", "音频变声", "虚拟形象", "直播互动", "模型管理", "系统设置"]


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


class HomeWindow(QMainWindow):
    logout_requested = Signal()
    profile_loaded = Signal(dict)
    profile_load_error = Signal(str)
    profile_saved = Signal(dict)
    profile_save_error = Signal(str)

    def __init__(self, account: str | None = None) -> None:
        super().__init__()
        self.account = account or ""
        self.setWindowTitle("星弦")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 800)
        self.setStyleSheet(STYLE_SHEET)
        self.model_store = ModelStore(self.account)
        self.model_entries = self.model_store.load()
        self.settings_store = SettingsStore(self.account)
        self.motion_settings = self.settings_store.load_motion()
        self.motion_capture = MotionCapture()
        self.motion_capture.frame_ready.connect(self._on_motion_frame)
        self.motion_capture.drive_changed.connect(self._on_motion_drive)
        self.motion_capture.status_changed.connect(self._on_motion_status)
        self.motion_capture.set_engine(self.motion_settings.get("engine", "hybrid"))
        self.motion_capture.set_drive_params(self.motion_settings.get("params", {}))
        self.profile_data: dict = {}
        self.personal_page_index = 0

        icon_path = ICON_PATH if ICON_PATH.exists() else LOGO_PATH
        self.setWindowIcon(QIcon(str(icon_path)))
        self.setCentralWidget(self._build_ui())
        self.profile_loaded.connect(self._on_profile_loaded)
        self.profile_load_error.connect(self._on_profile_load_error)
        self.profile_saved.connect(self._on_profile_saved)
        self.profile_save_error.connect(self._on_profile_save_error)

    def closeEvent(self, event: QCloseEvent) -> None:
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

        profile = QLabel("配置：日常直播")
        profile.setStyleSheet("color: #9DB5D8; font-size: 12px;")
        layout.addWidget(profile)

        status = QLabel("服务器已连接")
        status.setStyleSheet("color: #9DB5D8; font-size: 12px;")
        layout.addWidget(status)
        return sidebar

    def _build_pages(self) -> QStackedWidget:
        return self.pages

    def _open_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_group.setExclusive(False)
        for button in self.nav_group.buttons():
            button.setChecked(False)
        if index < len(NAV_ITEMS):
            self.nav_group.buttons()[index].setChecked(True)
        self.nav_group.setExclusive(True)
        self._place_live2d_for_page(index)
        if index == self.personal_page_index:
            self._load_profile()

    def _place_live2d_for_page(self, index: int) -> None:
        view = getattr(self, "live2d_view", None)
        if view is None:
            return
        if index == 0:
            holder = getattr(self, "home_preview_holder", None)
        elif index == 1:
            holder = getattr(self, "motion_avatar_holder", None)
        elif index == 3:
            holder = getattr(self, "avatar_preview_holder", None)
        else:
            return
        if holder is None:
            return
        current = view.parentWidget()
        if current is holder:
            return
        if current is not None and current.layout() is not None:
            current.layout().removeWidget(view)
        view.setParent(holder)
        holder.layout().addWidget(view)
        view.update()

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
        cam_row.addWidget(self._form_label("摄像头编号"))
        self.motion_camera_spin = ArrowSpinBox()
        self.motion_camera_spin.setObjectName("inputBox")
        self.motion_camera_spin.setRange(0, 9)
        self.motion_camera_spin.setValue(int(self.motion_settings.get("camera_index", 0)))
        self.motion_camera_spin.valueChanged.connect(self._on_motion_camera_changed)
        cam_row.addWidget(self.motion_camera_spin, 1)
        controls_box.addLayout(cam_row)

        self.motion_mirror = QCheckBox("镜像画面")
        self.motion_mirror.setObjectName("toggle")
        self.motion_mirror.setChecked(bool(self.motion_settings.get("mirror", True)))
        self.motion_mirror.toggled.connect(self._on_motion_mirror_changed)
        controls_box.addWidget(self.motion_mirror)

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
        stop_button = QPushButton("停止")
        stop_button.setObjectName("ghostButton")
        stop_button.clicked.connect(self._on_motion_stop)
        start_stop.addWidget(self.motion_start_button)
        start_stop.addWidget(stop_button)
        start_stop.addStretch()
        controls_box.addLayout(start_stop)
        controls_box.addStretch()
        self.motion_controls_card = controls_card

        values_card, values_box = self._make_clickable_card("驱动数值", "values")
        self.motion_value_labels: dict[str, QLabel] = {}
        for cap, key in (("头部左右", "angle_x"), ("头部上下", "angle_y"), ("头部翻转", "angle_z")):
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

    def _apply_motion_settings(self) -> None:
        self.motion_capture.set_camera_index(int(self.motion_settings.get("camera_index", 0)))
        self.motion_capture.set_mirror(bool(self.motion_settings.get("mirror", True)))
        self.motion_capture.set_sensitivity(float(self.motion_settings.get("sensitivity", 1.0)))
        self.motion_capture.set_drive_enabled(bool(self.motion_settings.get("drive_enabled", True)))

    def _save_motion_settings(self) -> None:
        self.settings_store.save_motion(self.motion_settings)

    def _on_motion_camera_changed(self, value: int) -> None:
        self.motion_settings["camera_index"] = value
        self.motion_capture.set_camera_index(value)
        self._save_motion_settings()

    def _on_motion_mirror_changed(self, checked: bool) -> None:
        self.motion_settings["mirror"] = checked
        self.motion_capture.set_mirror(checked)
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

    def _on_motion_start(self) -> None:
        self._apply_motion_settings()
        if self.motion_capture.start():
            self.motion_start_button.setEnabled(False)
            self.motion_status.setText("动捕运行中")
            if getattr(self, "live2d_view", None) is not None:
                self.live2d_view.set_auto_features(blink=False, breath=True)
                self.live2d_view.stop_motions()

    def _on_motion_stop(self) -> None:
        self.motion_capture.stop()
        self.motion_start_button.setEnabled(True)
        self.motion_status.setText("动捕已停止")
        if getattr(self, "live2d_view", None) is not None:
            self.live2d_view.set_auto_features(blink=True, breath=True)
            self.live2d_view.reset_drive()
            self.live2d_view.start_idle()

    def _on_motion_frame(self, image) -> None:
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

    def _on_motion_drive(self, drive: dict) -> None:
        if getattr(self, "live2d_view", None) is not None:
            self.live2d_view.apply_drive(**drive)
        for key, label in getattr(self, "motion_value_labels", {}).items():
            label.setText(f"{drive.get(key, 0.0):.1f}")

    def _on_motion_status(self, text: str) -> None:
        if getattr(self, "motion_status", None) is not None:
            self.motion_status.setText(text)
        if getattr(self, "home_motion_status", None) is not None:
            self.home_motion_status.setText(text)

    def cfg_camera_spin_changed(self, value: int) -> None:
        self.motion_settings["camera_index"] = value
        self.motion_capture.set_camera_index(value)
        self._save_motion_settings()

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

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(24, 20, 24, 24)
        grid.setSpacing(14)

        avatar_card, avatar_box = _make_card("虚拟形象实时预览")
        self.home_preview_holder = QFrame()
        self.home_preview_holder.setObjectName("stagePanel")
        home_holder_layout = QVBoxLayout(self.home_preview_holder)
        home_holder_layout.setContentsMargins(8, 8, 8, 8)
        home_holder_layout.setSpacing(0)
        self.live2d_view = Live2DView()
        self.live2d_view.model_loaded.connect(self._on_live2d_loaded)
        self.live2d_view.model_error.connect(self._on_live2d_error)
        home_holder_layout.addWidget(self.live2d_view, 1)
        avatar_box.addWidget(self.home_preview_holder, 1)
        self.home_avatar_status = QLabel("")
        self.home_avatar_status.setObjectName("panelBody")
        avatar_box.addWidget(self.home_avatar_status)
        grid.addWidget(avatar_card, 0, 0, 2, 1)

        camera_card, camera_box = _make_card("动捕画面 / 关键点")
        self.home_motion_preview = QLabel("摄像头未连接")
        self.home_motion_preview.setAlignment(Qt.AlignCenter)
        self.home_motion_preview.setStyleSheet(
            "background-color: #0A142A; border: 1px solid #284064; border-radius: 8px; color: #A9C3E2;"
        )
        self.home_motion_preview.setMinimumSize(260, 180)
        self.home_motion_preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        camera_box.addWidget(self.home_motion_preview, 1)
        self.home_motion_status = QLabel("设备：未连接")
        self.home_motion_status.setObjectName("panelBody")
        camera_box.addWidget(self.home_motion_status)
        camera_box.addStretch()
        grid.addWidget(camera_card, 0, 1)

        active_rvc = self._active_rvc_entry()
        rvc_name = active_rvc.name if active_rvc else "未选择"
        voice_card, voice_box = _make_card("音频变声控制")
        voice_status = QLabel(f"当前模型：{rvc_name}")
        voice_status.setObjectName("infoValue")
        voice_box.addWidget(voice_status)
        voice_toggle = QCheckBox("启用 RVC 变声")
        voice_toggle.setObjectName("toggle")
        voice_box.addWidget(voice_toggle)
        voice_box.addStretch()
        grid.addWidget(voice_card, 0, 2)

        live_card, live_box = _make_card("直播互动")
        live_hint = QLabel("弹幕 / 礼物 / 互动动作接入位")
        live_hint.setObjectName("panelBody")
        live_box.addWidget(live_hint)
        live_box.addStretch()
        grid.addWidget(live_card, 1, 1, 1, 2)

        output_card, output_box = _make_card("视频输出设置")
        output_info = QLabel("输出分辨率 1080P · 帧率 60 · RTMP 推流地址待配置")
        output_info.setObjectName("infoValue")
        output_box.addWidget(output_info)
        output_box.addStretch()
        grid.addWidget(output_card, 2, 0, 1, 3)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
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

        self.avatar_model_list = QListWidget()
        self.avatar_model_list.setObjectName("modelList")
        self.avatar_model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        picker_layout.addWidget(self.avatar_model_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        show_button = QPushButton("显示")
        show_button.setObjectName("actionButton")
        show_button.clicked.connect(lambda _=False: self._show_avatar_model())
        reload_button = QPushButton("重新加载")
        reload_button.setObjectName("actionButton")
        reload_button.clicked.connect(lambda _=False: self._reload_live2d())
        buttons.addWidget(show_button)
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
        right_column.addWidget(self._build_drive_params_card(), 1)
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
            self._refresh_drive_params_card()

    def _on_live2d_error(self, message: str) -> None:
        text = f"模型加载失败：{message}"
        for attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(text)

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
            if path:
                view.load_model(path)
            else:
                view.clear_model()
        text = f"当前模型：{name}" if path else "暂无模型，请先在模型管理中导入并启用 Live2D 模型"
        for status_attr in ("home_avatar_status", "avatar_status"):
            label = getattr(self, status_attr, None)
            if label is not None:
                label.setText(text)

    def _refresh_live2d_page(self) -> None:
        if getattr(self, "avatar_model_list", None) is None:
            return
        self.avatar_model_list.clear()
        for entry in self.model_entries:
            if entry.kind != "live2d":
                continue
            suffix = " [使用中]" if entry.active else ""
            self.avatar_model_list.addItem(f"{entry.name}{suffix}")
        self._sync_live2d_views()

    def _show_avatar_model(self) -> None:
        if self.avatar_model_list.currentItem() is None:
            show_info(self, "星弦", "请先选择一个模型")
            return
        name = self.avatar_model_list.currentItem().text().split(" [")[0]
        self.model_entries = self.model_store.set_active("live2d", name)
        self._refresh_model_list("live2d")

    def _reload_live2d(self) -> None:
        active = self._active_live2d_entry()
        if active is None:
            show_info(self, "星弦", "当前没有可显示的模型")
            return
        self._sync_live2d_views()
        self.avatar_status.setText(f"正在重新加载：{active.name}")

    def _build_drive_params_card(self) -> QFrame:
        card, box = _make_card("模型参数设置")
        hint = QLabel("幅度越大动作越明显；勾选反转可颠倒方向。")
        hint.setObjectName("hintText")
        box.addWidget(hint)

        self.drive_param_spins: dict[str, QDoubleSpinBox] = {}
        self.drive_param_inverts: dict[str, QCheckBox] = {}
        params = self.motion_settings.get("params", {})

        # 获取当前模型支持的参数
        supported_params = []
        if hasattr(self, "home_live2d_view") and self.home_live2d_view is not None:
            supported_params = self.home_live2d_view.get_supported_params()
        elif hasattr(self, "avatar_live2d_view") and self.avatar_live2d_view is not None:
            supported_params = self.avatar_live2d_view.get_supported_params()

        # 如果没有模型支持参数，使用默认参数列表
        if not supported_params:
            rows = [
                ("头部左右", "angle_x", True),
                ("头部上下", "angle_y", True),
                ("头部翻转", "angle_z", True),
                ("身体左右", "body_angle_x", True),
                ("身体前后", "body_angle_y", True),
                ("左臂", "arm_l", True),
                ("右臂", "arm_r", True),
                ("眼睛", "eye", False),
                ("嘴型", "mouth", False),
                ("眼球左右", "eye_x", True),
                ("眼球上下", "eye_y", True),
            ]
        else:
            # 根据模型支持的参数生成行
            rows = []
            for param in supported_params:
                rows.append((param.name, param.id, True))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for col, text in enumerate(("参数", "幅度", "反转")):
            head = QLabel(text)
            head.setObjectName("hintText")
            grid.addWidget(head, 0, col)

        for row, (label, key, has_invert) in enumerate(rows, start=1):
            name = QLabel(label)
            name.setObjectName("hintText")
            grid.addWidget(name, row, 0)
            spin = QDoubleSpinBox()
            spin.setObjectName("paramSpin")
            spin.setRange(0.0, 3.0)
            spin.setSingleStep(0.1)
            spin.setValue(float(params.get(key, {}).get("mult", 1.0)))
            spin.valueChanged.connect(lambda value, k=key: self._on_drive_param_mult(k, value))
            grid.addWidget(spin, row, 1)
            self.drive_param_spins[key] = spin
            if has_invert:
                invert = QCheckBox()
                invert.setObjectName("toggle")
                invert.setChecked(bool(params.get(key, {}).get("invert", False)))
                invert.toggled.connect(lambda checked, k=key: self._on_drive_param_invert(k, checked))
                grid.addWidget(invert, row, 2)
                self.drive_param_inverts[key] = invert
            else:
                grid.addWidget(QLabel(""), row, 2)
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

    def _refresh_drive_params_card(self) -> None:
        """刷新参数面板，根据当前模型支持的参数重新生成"""
        # 保存当前参数值
        current_params = self.motion_settings.get("params", {})
        
        # 重新构建参数面板
        if hasattr(self, "drive_params_card_holder"):
            # 清除旧的参数面板
            layout = self.drive_params_card_holder.layout()
            if layout:
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                layout.addWidget(self._build_drive_params_card())

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

        motion_card, motion_box = _make_card("动捕设置")
        cam_row = QHBoxLayout()
        cam_row.addWidget(self._form_label("摄像头编号"))
        self.cfg_camera_spin = ArrowSpinBox()
        self.cfg_camera_spin.setObjectName("inputBox")
        self.cfg_camera_spin.setRange(0, 9)
        self.cfg_camera_spin.setValue(int(self.motion_settings.get("camera_index", 0)))
        self.cfg_camera_spin.valueChanged.connect(self.cfg_camera_spin_changed)
        cam_row.addWidget(self.cfg_camera_spin, 1)
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
        resolution = ArrowComboBox()
        resolution.setObjectName("inputBox")
        resolution.addItems(["1080P", "720P", "4K"])
        video_box.addWidget(resolution)
        video_box.addWidget(self._form_label("帧率"))
        fps = ArrowSpinBox()
        fps.setObjectName("inputBox")
        fps.setRange(24, 120)
        fps.setValue(60)
        video_box.addWidget(fps)
        video_box.addStretch()
        settings_row.addWidget(video_card, 1)

        audio_card, audio_box = _make_card("音频设置")
        audio_box.addWidget(self._form_label("采样率"))
        sample = ArrowComboBox()
        sample.setObjectName("inputBox")
        sample.addItems(["44100 Hz", "48000 Hz", "96000 Hz"])
        audio_box.addWidget(sample)
        audio_box.addWidget(self._form_label("变声引擎"))
        engine = ArrowComboBox()
        engine.setObjectName("inputBox")
        engine.addItems(["RVC", "未启用"])
        audio_box.addWidget(engine)
        audio_box.addStretch()
        settings_row.addWidget(audio_card, 1)

        layout.addLayout(settings_row, 1)

        save_button = QPushButton("保存设置")
        save_button.setObjectName("actionButton")
        save_button.clicked.connect(lambda: show_info(self, "星弦", "设置保存功能待接入"))
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(save_button)
        layout.addLayout(save_row)
        return page

    def _build_rvc_page(self) -> QWidget:
        return self._build_model_page("rvc", "音频变声")

    def _build_model_page(self, kind: str, title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

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
        use_button = QPushButton("使用")
        use_button.setObjectName("navButton")
        use_button.clicked.connect(lambda _=False, k=kind: self._use_model(k))
        delete_button = QPushButton("删除")
        delete_button.setObjectName("navButton")
        delete_button.clicked.connect(lambda _=False, k=kind: self._delete_model(k))
        buttons.addWidget(import_button)
        buttons.addWidget(use_button)
        buttons.addWidget(delete_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._refresh_model_list(kind)
        return page

    def _build_model_management_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title_label = QLabel("模型管理")
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)
        layout.addWidget(self._build_model_page("live2d", "Live2D 模型"))
        layout.addWidget(self._build_model_page("rvc", "RVC 模型"))
        return page

    def _refresh_model_list(self, kind: str) -> None:
        model_list = getattr(self, "model_lists", {}).get(kind)
        if model_list is not None:
            model_list.clear()
            entries = [entry for entry in self.model_entries if entry.kind == kind]
            for entry in entries:
                suffix = " [使用中]" if entry.active else ""
                model_list.addItem(f"{entry.name}{suffix}")
        if kind == "live2d":
            self._refresh_live2d_page()

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

    def _delete_model(self, kind: str) -> None:
        model_list = getattr(self, "model_lists", {}).get(kind)
        if model_list is None or model_list.currentItem() is None:
            show_info(self, "星弦", "请先选择一个模型")
            return
        name = model_list.currentItem().text().split(" [")[0]
        self.model_entries = self.model_store.remove(name)
        self._refresh_model_list(kind)
