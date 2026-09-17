"""调音台独立弹窗：OBS 式表格布局的多设备音量监控。

- 每个设备一列：彩色表头、声道/偏移/音频监听/输出音轨/降噪/平衡设置行、
  竖向 dB VU 电平表 + 推子 + 静音按钮。
- 🎤输入设备直接采集；🔊输出设备走 WASAPI Loopback 回环，监听"系统正在播放
  的声音"，用于排查输出通道是否有声音。
- 输出通道的推子/静音会作用到实时变声输出增益（home_window 查询
  current_output_gain）。
- 通道配置随账号持久化；关闭弹窗即停止全部采集线程。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_HEADER_COLORS = ["#5F8570", "#5B7089", "#8A5F63", "#8A7A55", "#6B5F85", "#55807F"]
_DB_TICKS = (0, -5, -10, -15, -20, -25, -30, -35, -40, -45, -50, -55, -60)
_MONITOR_MODES = ["仅监听（输出静音）", "禁止监听和输出", "仅输出（不监听）"]
_CHANNEL_MODES = ["双声道", "单声道"]
_TRACK_MODES = ["系统默认"]
_DENOISE_MODES = ["关闭", "基础降噪"]


def _rms_to_pct(rms: float) -> float:
    """RMS(0..1) 映射到 0..100 电平百分比（-60dBFS 起，与 VU 刻度一致）。"""
    if rms <= 1e-6:
        return 0.0
    db = 20.0 * math.log10(rms)
    return max(0.0, min(100.0, (db + 60.0) * 100.0 / 60.0))


class VUMeter(QWidget):
    """竖向 dBFS 电平表：绿→黄→红渐变，左侧 dB 刻度。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 240)
        self._level = 0.0  # 0..1

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        scale_w, gap, bar_w = 18, 3, 12
        x0, y0 = 0, 4
        bh = h - 8
        p.setPen(QPen(QColor("#1E2A44")))
        p.setBrush(QColor("#060B18"))
        p.drawRect(x0, y0, scale_w, bh)
        bar_x = x0 + scale_w + gap
        p.drawRect(bar_x, y0, bar_w, bh)
        p.setFont(QFont("Microsoft YaHei", 7))
        p.setPen(QColor("#8FA8CC"))
        for db in _DB_TICKS:
            y = y0 + bh * (1.0 - (db + 60.0) / 60.0)
            p.drawText(
                QRectF(0, y - 6, scale_w, 12), Qt.AlignRight | Qt.AlignVCenter, str(db)
            )
            p.drawLine(bar_x - 1, int(y), bar_x + 1, int(y))
        fill_h = int(bh * self._level)
        if fill_h > 0:
            grad = QLinearGradient(0, y0, 0, y0 + bh)
            grad.setColorAt(0.0, QColor("#E84855"))
            grad.setColorAt(0.18, QColor("#F9A03F"))
            grad.setColorAt(0.38, QColor("#C8D64A"))
            grad.setColorAt(1.0, QColor("#3FA45B"))
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawRect(bar_x, y0 + bh - fill_h, bar_w, fill_h)
        p.end()


class _ChannelColumn:
    """一个设备通道的全部控件与状态。"""

    def __init__(self, cid: str, device, color: str) -> None:
        self.id = cid
        self.device = device
        self.kind = device.kind
        self.name = device.name
        self.gain = 1.0
        self.muted = False
        self.smooth = 0.0
        self.color = color
        self.widgets: list[QWidget] = []
        self.meter: VUMeter | None = None
        self.mute_button: QPushButton | None = None
        self.status_label: QLabel | None = None


class MixerDialog(QDialog):
    """调音台窗口（modeless）。"""

    level_received = Signal(str, float)

    def __init__(self, parent, settings_store) -> None:
        super().__init__(parent)
        self.setWindowTitle("调音台")
        self.setModal(False)
        self.resize(1080, 720)
        self._settings = settings_store
        self._columns: dict[str, _ChannelColumn] = {}
        self._monitor = None
        self._color_i = 0
        self._labels_done = False

        self.level_received.connect(self._on_level)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        add_btn = QPushButton("＋ 添加音频源")
        add_btn.setObjectName("actionButton")
        add_btn.clicked.connect(self._on_add_device)
        bar.addWidget(add_btn)
        for label in ("音频美化", "音频闪避", "录制音轨"):
            btn = QPushButton(label)
            btn.setObjectName("ghostButton")
            btn.setEnabled(False)
            btn.setToolTip("敬请期待")
            bar.addWidget(btn)
        bar.addStretch()
        root.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self._grid = QGridLayout(host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        self._empty = QLabel("尚未添加监控设备：点击「＋ 添加音频源」选择麦克风或扬声器")
        self._empty.setObjectName("hintText")
        self._empty.setAlignment(Qt.AlignCenter)
        self._grid.addWidget(self._empty, 0, 1, 11, 3)

        self._restore_channels()

    # ------------------------------------------------------------------
    # 布局骨架
    # ------------------------------------------------------------------

    def _grid_col(self) -> int:
        return len(self._columns) + 1

    def _clear_channel_widgets(self) -> None:
        for col in self._columns.values():
            for w in col.widgets:
                w.setParent(None)
                w.deleteLater()
            col.widgets.clear()
            col.meter = None
            col.mute_button = None
            col.status_label = None
        # 清空网格中所有残留项（行标签会在重建时重新添加）
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            lay = item.layout()
            if w is not None:
                if w is not self._empty:
                    w.setParent(None)
                    w.deleteLater()
            elif lay is not None:
                while lay.count():
                    sub = lay.takeAt(0)
                    sw = sub.widget()
                    if sw is not None:
                        sw.setParent(None)
                        sw.deleteLater()

    def _ensure_row_labels(self) -> None:
        if self._labels_done:
            return
        self._labels_done = True
        labels = {
            0: "设备",
            2: "声道",
            3: "偏移",
            4: "音频监听",
            5: "输出音轨",
            6: "降噪",
            7: "平衡",
            8: "音量",
        }
        for row, text in labels.items():
            lab = QLabel(text)
            lab.setObjectName("panelBody")
            lab.setAlignment(Qt.AlignCenter)
            lab.setFixedWidth(76)
            self._grid.addWidget(lab, row, 0, Qt.AlignCenter)

    def _next_color(self) -> str:
        color = _HEADER_COLORS[self._color_i % len(_HEADER_COLORS)]
        self._color_i += 1
        return color

    def _make_combo(self, items: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("inputBox")
        combo.addItems(items)
        return combo

    def _populate_column(self, col: _ChannelColumn, c: int) -> None:
        header = QLabel(col.name)
        header.setAlignment(Qt.AlignCenter)
        header.setFixedHeight(34)
        header.setStyleSheet(
            f"background-color:{col.color};color:#F2F6FF;border-radius:8px;"
            f"font-weight:600;padding:0 10px;"
        )
        menu_btn = QPushButton("⋮")
        menu_btn.setFixedSize(18, 34)
        menu_btn.setCursor(Qt.PointingHandCursor)
        menu_btn.setStyleSheet("background:transparent;border:none;color:#DDE7F5;")
        menu_btn.clicked.connect(lambda _=False, i=col.id: self._on_channel_menu(i))
        hwrap = QWidget()
        hlayout = QHBoxLayout(hwrap)
        hlayout.setContentsMargins(0, 0, 0, 0)
        hlayout.setSpacing(2)
        hlayout.addWidget(header, 1)
        hlayout.addWidget(menu_btn)
        self._grid.addWidget(hwrap, 0, c)
        col.widgets.append(hwrap)

        status = QLabel(f"{'●' if col.kind == 'input' else '●'} {col.name[:18]}")
        status.setObjectName("infoValue")
        status.setAlignment(Qt.AlignCenter)
        self._grid.addWidget(status, 1, c)
        col.widgets.append(status)
        col.status_label = status

        channel_combo = self._make_combo(_CHANNEL_MODES)
        self._grid.addWidget(channel_combo, 2, c)
        col.widgets.append(channel_combo)

        offset = QDoubleSpinBox()
        offset.setRange(-5000.0, 5000.0)
        offset.setSuffix(" ms")
        offset.setButtonSymbols(QDoubleSpinBox.NoButtons)
        offset.setObjectName("inputBox")
        self._grid.addWidget(offset, 3, c)
        col.widgets.append(offset)

        monitor_combo = self._make_combo(_MONITOR_MODES)
        self._grid.addWidget(monitor_combo, 4, c)
        col.widgets.append(monitor_combo)

        track_combo = self._make_combo(_TRACK_MODES)
        self._grid.addWidget(track_combo, 5, c)
        col.widgets.append(track_combo)

        den_box = QVBoxLayout()
        den_box.setSpacing(4)
        den_combo = self._make_combo(_DENOISE_MODES)
        den_box.addWidget(den_combo)
        den_slider = QSlider(Qt.Horizontal)
        den_slider.setRange(0, 100)
        den_slider.setValue(50)
        den_box.addWidget(den_slider)
        self._grid.addLayout(den_box, 6, c)
        col.widgets.extend([den_combo, den_slider])

        pan_row = QHBoxLayout()
        pan_row.setSpacing(6)
        left = QLabel("左")
        left.setObjectName("panelBody")
        pan_val = QLabel("0")
        pan_val.setObjectName("infoValue")
        pan_val.setAlignment(Qt.AlignCenter)
        pan_val.setFixedWidth(24)
        right = QLabel("右")
        right.setObjectName("panelBody")
        pan = QSlider(Qt.Horizontal)
        pan.setRange(-100, 100)
        pan.valueChanged.connect(lambda v, lab=pan_val: lab.setText(str(v)))
        pan_row.addWidget(left)
        pan_row.addWidget(pan_val)
        pan_row.addWidget(right)
        pan_row.addWidget(pan, 1)
        self._grid.addLayout(pan_row, 7, c)
        col.widgets.extend([left, pan_val, right, pan])

        meter = VUMeter()
        fader = QSlider(Qt.Vertical)
        fader.setRange(0, 150)
        fader.setValue(int(round(col.gain * 100)))
        fader.setMinimumHeight(240)
        pct = QLabel(str(int(round(col.gain * 100))))
        pct.setObjectName("infoValue")
        pct.setAlignment(Qt.AlignCenter)
        fader.valueChanged.connect(lambda v, lab=pct: lab.setText(str(v)))
        fader.valueChanged.connect(lambda v, col=col: setattr(col, "gain", v / 100.0))
        fader.valueChanged.connect(lambda _=False: self._persist())
        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        vol_row.addStretch()
        vol_row.addWidget(meter)
        vol_row.addWidget(fader)
        vol_row.addWidget(pct)
        vol_row.addStretch()
        self._grid.addLayout(vol_row, 8, c)
        col.widgets.extend([meter, fader, pct])
        col.meter = meter

        mute = QPushButton("🔇 已静音" if col.muted else "🎙 静音")
        mute.setObjectName("ghostButton")
        mute.setCheckable(True)
        mute.setChecked(col.muted)
        mute.toggled.connect(lambda on, col=col: self._set_muted(col, on))
        self._grid.addWidget(mute, 9, c)
        col.widgets.append(mute)
        col.mute_button = mute

        remove = QPushButton("移除监控")
        remove.setObjectName("ghostButton")
        remove.clicked.connect(lambda _=False, i=col.id: self._remove_channel(i))
        self._grid.addWidget(remove, 10, c)
        col.widgets.append(remove)

    def _set_muted(self, col: _ChannelColumn, on: bool) -> None:
        col.muted = on
        if col.mute_button is not None:
            col.mute_button.setText("🔇 已静音" if on else "🎙 静音")
        self._persist()

    # ------------------------------------------------------------------
    # 通道增删
    # ------------------------------------------------------------------

    def _all_devices(self) -> list:
        try:
            from app.services.mixer_monitor import (
                list_input_devices,
                list_loopback_devices,
            )

            return list_input_devices() + list_loopback_devices()
        except Exception as e:
            print(f"MixerDialog: 枚举设备失败 {e}")
            return []

    def _on_add_device(self) -> None:
        devices = [
            d for d in self._all_devices() if f"{d.kind}:{d.index}" not in self._columns
        ]
        if not devices:
            QMessageBox.information(
                self, "调音台", "没有可添加的设备（全部已在监控，或未检测到音频设备）"
            )
            return
        labels = [f"{'🎤' if d.kind == 'input' else '🔊'} {d.name}" for d in devices]
        choice, ok = QInputDialog.getItem(
            self, "添加音频源", "选择要监控的设备：", labels, 0, False
        )
        if not ok or not choice:
            return
        self._add_channel(devices[labels.index(choice)])
        self._persist()

    def _rebuild_grid(self) -> None:
        self._clear_channel_widgets()
        self._labels_done = False
        if not self._columns:
            self._empty.setVisible(True)
            self._grid.addWidget(self._empty, 0, 1, 11, 3)
            return
        self._empty.setVisible(False)
        for i, col in enumerate(self._columns.values()):
            self._populate_column(col, i + 1)

    def _add_channel(self, device) -> None:
        cid = f"{device.kind}:{device.index}"
        if cid in self._columns:
            return
        col = _ChannelColumn(cid, device, self._next_color())
        self._columns[cid] = col
        self._rebuild_grid()
        self._start_monitor()
        if self._monitor is not None:
            self._monitor.add_channel(cid, device)

    def _on_channel_menu(self, cid: str) -> None:
        choice, ok = QInputDialog.getItem(
            self, "通道菜单", "操作：", ["移除监控"], 0, False
        )
        if ok and choice == "移除监控":
            self._remove_channel(cid)

    def _remove_channel(self, cid: str) -> None:
        col = self._columns.pop(cid, None)
        if col is None:
            return
        if self._monitor is not None:
            self._monitor.remove_channel(cid)
        self._empty.setText(
            "尚未添加监控设备：点击「＋ 添加音频源」选择麦克风或扬声器"
        )
        self._rebuild_grid()
        self._persist()

    @staticmethod
    def _norm_name(name: str) -> str:
        """设备名归一化：小写、去掉 [Loopback] 标记和空白，方便跨枚举源匹配。"""
        s = str(name or "").lower()
        for token in ("[loopback]", "(loopback)", "（loopback）"):
            s = s.replace(token, "")
        return "".join(s.split())

    def channel_count(self) -> int:
        return len(self._columns)

    def ensure_default_channels(self, preferred_names: list) -> None:
        """第一次打开（没有任何已存通道）时，把变声正在用的设备自动加为监控。

        不加的话调音台打开是一片空白，用户会以为「实时音量没有」——其实只是
        还没有任何监控通道。匹配不上就不加，仍然走手动「＋ 添加音频源」；
        匹配顺序：归一化后相等 → 互相包含（兼容回环名里的 [Loopback] 后缀）。
        """
        if self._columns:
            return
        try:
            devices = self._all_devices()
        except Exception:
            return
        taken: set[int] = set()
        for want_name in preferred_names:
            want = self._norm_name(want_name)
            if not want:
                continue
            device = None
            for d in devices:
                if d.index in taken:
                    continue
                got = self._norm_name(d.name)
                if got == want or want in got or got in want:
                    device = d
                    break
            if device is not None:
                taken.add(device.index)
                self._add_channel(device)

    # ------------------------------------------------------------------
    # 采集与电平
    # ------------------------------------------------------------------

    def _start_monitor(self) -> None:
        if self._monitor is not None:
            return
        try:
            from app.services.mixer_monitor import MixerMonitor
        except ImportError:
            self._empty.setText(
                "需要安装 PyAudioWPatch 才能启用设备监控（pip install pyaudiowpatch）"
            )
            self._empty.setVisible(True)
            return
        self._monitor = MixerMonitor(listener=self._on_level_thread)

    def _on_level_thread(self, cid: str, rms: float) -> None:
        # 采集线程 → 队列信号转主线程
        self.level_received.emit(cid, rms)

    def _on_level(self, cid: str, rms: float) -> None:
        col = self._columns.get(cid)
        if col is None:
            return
        if rms < 0:
            if col.meter is not None:
                col.meter.set_level(0.0)
            if col.status_label is not None:
                col.status_label.setText("⚠ 设备不可用")
            return
        if col.meter is None:
            return
        pct = _rms_to_pct(rms)
        col.smooth = col.smooth + (pct - col.smooth) * (0.6 if pct > col.smooth else 0.18)
        col.meter.set_level(col.smooth / 100.0)

    # ------------------------------------------------------------------
    # 与实时变声链路的联动
    # ------------------------------------------------------------------

    def current_output_gain(self, device_name: str) -> float:
        """实时链路查询：匹配输出设备名的通道增益（静音=0，无匹配=1）。"""
        target = str(device_name or "")
        for col in self._columns.values():
            if col.kind != "loopback":
                continue
            a, b = col.name, target
            if a and b and (a in b or b in a):
                return 0.0 if col.muted else col.gain
        return 1.0

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _channel_state(self, col: _ChannelColumn) -> dict:
        return {
            "id": col.id,
            "kind": col.kind,
            "index": col.device.index,
            "name": col.name,
            "gain": int(col.gain * 100),
            "muted": bool(col.muted),
        }

    def _persist(self) -> None:
        try:
            self._settings.save_mixer(
                [self._channel_state(c) for c in self._columns.values()]
            )
        except Exception as e:
            print(f"保存调音台通道失败: {e}")

    def _restore_channels(self) -> None:
        try:
            channels = self._settings.load_mixer()
        except Exception:
            channels = []
        if not channels:
            return
        catalog = {f"{d.kind}:{d.index}": d for d in self._all_devices()}
        added = False
        for ch in channels:
            cid = str(ch.get("id", ""))
            device = catalog.get(cid)
            if device is None:
                continue
            if cid in self._columns:
                continue
            col = _ChannelColumn(cid, device, self._next_color())
            col.gain = float(ch.get("gain", 100)) / 100.0
            col.muted = bool(ch.get("muted", False))
            self._columns[cid] = col
            self._start_monitor()
            if self._monitor is not None:
                self._monitor.add_channel(cid, device)
            added = True
        if added:
            self._rebuild_grid()
        self._persist()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def shutdown_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.shutdown()
            self._monitor = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown_monitor()
        super().closeEvent(event)
