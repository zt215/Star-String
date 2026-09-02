from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app.services.account_store import Account, AccountStore
from app.services.auth_service import LoginError, login as remote_login, register as remote_register
from app.ui.dialogs import show_info, show_warning
RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
BACKGROUND_PATH = RESOURCES_DIR / "backgrounds" / "anime_starfield.jpg"
LOGO_PATH = RESOURCES_DIR / "images" / "star_logo.png"
ICON_PATH = RESOURCES_DIR / "images" / "star_logo.ico"
EYE_SHOW_PATH = RESOURCES_DIR / "images" / "eye.png"
EYE_HIDE_PATH = RESOURCES_DIR / "images" / "eye_off.png"


STYLE_SHEET = """
QWidget {
    font-family: "Microsoft YaHei";
    color: #F2F6FF;
    font-size: 14px;
}

QWidget#background {
    background-color: #0A1122;
}

QWidget#overlay {
    background-color: rgba(5, 10, 24, 92);
}

QFrame#loginCard {
    background-color: rgba(12, 20, 42, 172);
    border: 1px solid rgba(130, 190, 255, 72);
    border-radius: 16px;
}

QLabel#brandSubtitle {
    font-size: 12px;
    color: rgba(220, 234, 255, 176);
    letter-spacing: 4px;
}

QLabel#brandTitle {
    font-size: 26px;
    font-weight: 600;
    color: #EAF6FF;
}

QPushButton#backButton {
    background: transparent;
    border: 1px solid rgba(130, 190, 255, 80);
    border-radius: 10px;
    color: #7EE7FF;
    font-size: 20px;
}

QPushButton#backButton:hover {
    background-color: rgba(255, 255, 255, 18);
    border-color: rgba(126, 231, 255, 180);
}

QLineEdit {
    background-color: rgba(255, 255, 255, 24);
    border: 1px solid rgba(155, 205, 255, 72);
    border-radius: 8px;
    padding: 12px 14px;
    color: #F2F6FF;
    selection-background-color: #2E8FE8;
}

QLineEdit:hover {
    border-color: rgba(120, 220, 255, 150);
    background-color: rgba(255, 255, 255, 34);
}

QLineEdit:focus {
    border-color: #7EE7FF;
    background-color: rgba(255, 255, 255, 42);
}

QComboBox {
    background-color: rgba(255, 255, 255, 24);
    border: 1px solid rgba(155, 205, 255, 72);
    border-radius: 8px;
    padding: 10px 12px;
    color: #F2F6FF;
}

QComboBox:hover {
    border-color: rgba(120, 220, 255, 150);
    background-color: rgba(255, 255, 255, 34);
}

QComboBox:focus {
    border-color: #7EE7FF;
    background-color: rgba(255, 255, 255, 42);
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox::down-arrow {
    width: 16px;
    height: 16px;
}

QCheckBox {
    color: rgba(225, 238, 255, 220);
    font-size: 13px;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid rgba(155, 205, 255, 110);
    border-radius: 4px;
    background-color: rgba(255, 255, 255, 18);
}

QCheckBox::indicator:checked {
    background-color: #55D1F7;
    border-color: #7EE7FF;
}

QListView#accountPopup {
    background-color: #101A33;
    border: 1px solid rgba(130, 190, 255, 80);
    border-radius: 6px;
}

QListView#accountPopup::item {
    background-color: #101A33;
}

QPushButton#accountItemButton {
    background: transparent;
    border: none;
    color: #EAF6FF;
    font-size: 14px;
    padding: 4px 6px;
    text-align: left;
}

QPushButton#accountItemButton:hover {
    color: #7EE7FF;
    background-color: rgba(255, 255, 255, 14);
    border-radius: 4px;
}

QPushButton#accountDeleteButton {
    background: transparent;
    border: none;
    color: rgba(255, 160, 160, 200);
    font-size: 16px;
    font-weight: 600;
}

QPushButton#accountDeleteButton:hover {
    color: #FF5A5A;
    background-color: rgba(255, 80, 80, 40);
    border-radius: 4px;
}

QPushButton#loginButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #2E7FD9,
        stop: 1 #55D1F7
    );
    border: none;
    border-radius: 8px;
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
    padding: 12px;
}

QPushButton#loginButton:hover {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #3A92EA,
        stop: 1 #6EDCFF
    );
}

QPushButton#loginButton:pressed {
    background-color: #2568B7;
}

QPushButton#linkButton {
    background: transparent;
    border: none;
    color: rgba(160, 210, 255, 210);
    font-size: 13px;
    padding: 4px;
}

QPushButton#linkButton:hover {
    color: #7EE7FF;
}

QMessageBox {
    background-color: #FFFFFF;
}

QMessageBox QLabel {
    color: #1E6FD9;
    font-size: 14px;
}

QMessageBox QPushButton {
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #2E7FD9,
        stop: 1 #55D1F7
    );
    border: none;
    border-radius: 6px;
    color: #FFFFFF;
    min-width: 72px;
    padding: 8px 18px;
}

QMessageBox QPushButton:hover {
    background-color: #57C9FF;
}

QFrame#loadingOverlay {
    background-color: rgba(10, 16, 32, 225);
}

QLabel#loadingText {
    color: #7EE7FF;
    font-size: 15px;
}

QProgressBar#loadingProgress {
    border: none;
    border-radius: 3px;
    background-color: #16223F;
}

QProgressBar#loadingProgress::chunk {
    border-radius: 3px;
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #2E7FD9,
        stop: 1 #7EE7FF
    );
}
"""


def _cover_rect(pixmap_size: QSize, target_size: QSize) -> QRect:
    if pixmap_size.isEmpty() or target_size.isEmpty():
        return QRect(target_size)

    scale = max(
        target_size.width() / pixmap_size.width(),
        target_size.height() / pixmap_size.height(),
    )
    width = round(pixmap_size.width() * scale)
    height = round(pixmap_size.height() * scale)
    x = (target_size.width() - width) // 2
    y = (target_size.height() - height) // 2
    return QRect(x, y, width, height)


class NoTextDelegate(QStyledItemDelegate):
    def paint(self, painter: object, option: object, index: object) -> None:
        del painter, option, index

    def sizeHint(self, option: object, index: object) -> QSize:
        del option, index
        return QSize(324, 48)


class StyledComboBox(QComboBox):
    def paintEvent(self, event: object) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#8FD0FF"))

        center_y = self.rect().center().y()
        start_x = self.width() - 22
        half_w = 5.0
        half_h = 3.5
        points = [
            QPointF(start_x, center_y - half_h),
            QPointF(start_x + half_w * 2, center_y - half_h),
            QPointF(start_x + half_w, center_y + half_h),
        ]
        painter.drawPolygon(QPolygonF(points))
        painter.end()


class StaticBackground(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("background")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._pixmap = QPixmap(str(BACKGROUND_PATH))

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._pixmap.isNull():
            painter.drawPixmap(
                _cover_rect(self._pixmap.size(), self.size()),
                self._pixmap,
            )
        painter.end()


class LoginWindow(QMainWindow):
    login_success = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("星弦")
        self.setMinimumSize(960, 600)
        self.resize(1280, 800)
        self.setStyleSheet(STYLE_SHEET)

        icon_path = ICON_PATH if ICON_PATH.exists() else LOGO_PATH
        self.setWindowIcon(QIcon(str(icon_path)))

        self.account_store = AccountStore()
        self.accounts = self.account_store.load()
        self.last_username = self.account_store.load_last_username()

        central = QWidget(self)
        layout = QGridLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.background = StaticBackground(central)
        overlay = QLabel(central)
        overlay.setObjectName("overlay")

        self.login_card = QFrame(central)
        self.login_card.setObjectName("loginCard")
        self.login_card.setFixedWidth(400)
        self._build_login_card(self.login_card)

        self.register_card = QFrame(central)
        self.register_card.setObjectName("loginCard")
        self.register_card.setFixedWidth(400)
        self._build_register_card(self.register_card)

        shadow = QGraphicsDropShadowEffect(self.login_card)
        shadow.setBlurRadius(38)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.login_card.setGraphicsEffect(shadow)

        register_shadow = QGraphicsDropShadowEffect(self.register_card)
        register_shadow.setBlurRadius(38)
        register_shadow.setOffset(0, 10)
        register_shadow.setColor(QColor(0, 0, 0, 150))
        self.register_card.setGraphicsEffect(register_shadow)

        self.pages = QStackedWidget(central)
        self.pages.setFixedWidth(400)
        self.pages.addWidget(self.login_card)
        self.pages.addWidget(self.register_card)

        self._restore_last_account()

        layout.addWidget(self.background, 0, 0)
        layout.addWidget(overlay, 0, 0)
        layout.addWidget(self.pages, 0, 0, Qt.AlignCenter)
        self.loading_overlay = self._build_loading_overlay()
        layout.addWidget(self.loading_overlay, 0, 0)
        self.setCentralWidget(central)

    def _build_login_card(self, card: QFrame) -> None:
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(38, 34, 38, 34)
        card_layout.setSpacing(14)

        logo = QLabel(card)
        logo.setObjectName("brandLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(180, 180)
        pixmap = QPixmap(str(LOGO_PATH))
        logo.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        card_layout.addWidget(logo, alignment=Qt.AlignCenter)

        subtitle = QLabel("STAR STRING", card)
        subtitle.setObjectName("brandSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(10)

        self.account_combo = StyledComboBox(card)
        self.account_combo.setEditable(True)
        self.account_combo.setInsertPolicy(QComboBox.NoInsert)
        self.account_combo.setPlaceholderText("选择或输入账号")
        self.account_combo.lineEdit().setPlaceholderText("选择或输入账号")
        self.account_combo.activated.connect(self._load_selected_account)
        self.account_view = QListView(card)
        self.account_view.setObjectName("accountPopup")
        self.account_view.setModel(self.account_combo.model())
        self.account_view.setItemDelegate(NoTextDelegate(self.account_view))
        self.account_combo.setView(self.account_view)
        self._reload_account_combo()
        card_layout.addWidget(self.account_combo)

        self.password_edit = QLineEdit(card)
        self.password_edit.setPlaceholderText("密码")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self._add_password_toggle(self.password_edit)
        card_layout.addWidget(self.password_edit)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        self.remember_checkbox = QCheckBox("记住密码", card)
        self.auto_login_checkbox = QCheckBox("自动登录", card)
        options_row.addWidget(self.remember_checkbox)
        options_row.addStretch()
        options_row.addWidget(self.auto_login_checkbox)
        self.auto_login_checkbox.toggled.connect(self._on_auto_login_toggled)
        self.remember_checkbox.toggled.connect(self._on_remember_toggled)
        card_layout.addLayout(options_row)

        login_button = QPushButton("登 录", card)
        login_button.setObjectName("loginButton")
        login_button.setCursor(Qt.PointingHandCursor)
        login_button.setFixedHeight(44)
        login_button.clicked.connect(self._save_current_account)
        card_layout.addWidget(login_button)

        links_row = QHBoxLayout()
        links_row.setSpacing(12)
        forgot_button = QPushButton("忘记密码", card)
        forgot_button.setObjectName("linkButton")
        forgot_button.setCursor(Qt.PointingHandCursor)
        forgot_button.clicked.connect(
            lambda: show_info(self, "星弦", "忘记密码功能待接入服务端")
        )
        register_button = QPushButton("注册", card)
        register_button.setObjectName("linkButton")
        register_button.setCursor(Qt.PointingHandCursor)
        register_button.clicked.connect(
            lambda: self.pages.setCurrentWidget(self.register_card)
        )
        links_row.addWidget(forgot_button)
        links_row.addStretch()
        links_row.addWidget(register_button)
        card_layout.addLayout(links_row)

    def _build_register_card(self, card: QFrame) -> None:
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(38, 28, 38, 28)
        card_layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(0)
        back_button = QPushButton("←", card)
        back_button.setObjectName("backButton")
        back_button.setFixedSize(38, 38)
        back_button.setCursor(Qt.PointingHandCursor)
        back_button.setToolTip("返回登录")
        back_button.clicked.connect(
            lambda: self.pages.setCurrentWidget(self.login_card)
        )
        top_row.addWidget(back_button)
        top_row.addStretch()
        card_layout.addLayout(top_row)

        title = QLabel("注册账号", card)
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title)
        card_layout.addSpacing(4)

        self.register_username = QLineEdit(card)
        self.register_username.setPlaceholderText("账户名")
        self.register_username.setClearButtonEnabled(True)
        card_layout.addWidget(self.register_username)

        self.register_nickname = QLineEdit(card)
        self.register_nickname.setPlaceholderText("昵称")
        self.register_nickname.setClearButtonEnabled(True)
        card_layout.addWidget(self.register_nickname)

        self.register_phone = QLineEdit(card)
        self.register_phone.setPlaceholderText("手机号")
        self.register_phone.setClearButtonEnabled(True)
        card_layout.addWidget(self.register_phone)

        self.register_email = QLineEdit(card)
        self.register_email.setPlaceholderText("邮箱")
        self.register_email.setClearButtonEnabled(True)
        card_layout.addWidget(self.register_email)

        self.register_password = QLineEdit(card)
        self.register_password.setPlaceholderText("密码")
        self.register_password.setEchoMode(QLineEdit.Password)
        self._add_password_toggle(self.register_password)
        card_layout.addWidget(self.register_password)

        self.register_confirm_password = QLineEdit(card)
        self.register_confirm_password.setPlaceholderText("确认密码")
        self.register_confirm_password.setEchoMode(QLineEdit.Password)
        self._add_password_toggle(self.register_confirm_password)
        card_layout.addWidget(self.register_confirm_password)

        register_button = QPushButton("注 册", card)
        register_button.setObjectName("loginButton")
        register_button.setCursor(Qt.PointingHandCursor)
        register_button.setFixedHeight(44)
        register_button.clicked.connect(self._register_account)
        card_layout.addWidget(register_button)

    def _build_loading_overlay(self) -> QFrame:
        overlay = QFrame()
        overlay.setObjectName("loadingOverlay")
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        text = QLabel("正在登录...")
        text.setObjectName("loadingText")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)

        progress = QProgressBar()
        progress.setObjectName("loadingProgress")
        progress.setRange(0, 0)
        progress.setFixedSize(280, 6)
        layout.addWidget(progress, alignment=Qt.AlignCenter)

        overlay.hide()
        return overlay

    def _add_password_toggle(self, editor: QLineEdit) -> None:
        show_icon = QIcon(str(EYE_SHOW_PATH))
        hide_icon = QIcon(str(EYE_HIDE_PATH))
        action = editor.addAction(hide_icon, QLineEdit.TrailingPosition)
        action.setToolTip("显示密码")

        def toggle(checked: bool = False) -> None:
            del checked
            if editor.echoMode() == QLineEdit.Password:
                editor.setEchoMode(QLineEdit.Normal)
                action.setIcon(show_icon)
                action.setToolTip("隐藏密码")
            else:
                editor.setEchoMode(QLineEdit.Password)
                action.setIcon(hide_icon)
                action.setToolTip("显示密码")

        action.triggered.connect(toggle)

    def _register_account(self) -> None:
        username = self.register_username.text().strip()
        nickname = self.register_nickname.text().strip()
        phone = self.register_phone.text().strip()
        email = self.register_email.text().strip()
        password = self.register_password.text()

        if not username or not nickname or not phone or not email or not password:
            show_warning(self, "星弦", "请填写完整的注册信息")
            return
        if password != self.register_confirm_password.text():
            show_warning(self, "星弦", "两次输入的密码不一致")
            return

        try:
            remote_register(username, nickname, phone, email, password)
        except LoginError as error:
            show_warning(self, "星弦", str(error))
            return

        self.register_username.clear()
        self.register_nickname.clear()
        self.register_phone.clear()
        self.register_email.clear()
        self.register_password.clear()
        self.register_confirm_password.clear()
        self.pages.setCurrentWidget(self.login_card)
        self.account_combo.setCurrentText(username)
        show_info(self, "星弦", "注册成功，请登录")

    def _reload_account_combo(self) -> None:
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for account in self.accounts:
            self.account_combo.addItem(account.username)
        self.account_combo.blockSignals(False)
        self._populate_account_view()
        row_height = 46
        popup_height = min(max(64, (len(self.accounts) or 1) * row_height + 12), 360)
        self.account_view.setFixedHeight(popup_height)

    def _populate_account_view(self) -> None:
        model = self.account_combo.model()
        for row, account in enumerate(self.accounts):
            index = model.index(row, 0)
            self.account_view.setIndexWidget(index, self._make_account_row(account))

    def _make_account_row(self, account: Account) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background-color: #101A33;")
        row.setMinimumWidth(324)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 7, 8, 7)
        row_layout.setSpacing(8)

        username_button = QPushButton(account.username, row)
        username_button.setObjectName("accountItemButton")
        username_button.setFixedHeight(34)
        username_button.setCursor(Qt.PointingHandCursor)
        username_button.clicked.connect(
            lambda _=False, username=account.username: self._select_account(username)
        )

        delete_button = QPushButton("×", row)
        delete_button.setObjectName("accountDeleteButton")
        delete_button.setToolTip(f"删除 {account.username}")
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setFixedSize(26, 26)
        delete_button.clicked.connect(
            lambda _=False, username=account.username: self._delete_account(username)
        )

        row_layout.addWidget(username_button, 1)
        row_layout.addWidget(delete_button)
        return row

    def _select_account(self, username: str) -> None:
        self.account_combo.setCurrentText(username)
        self._load_account_by_name(username)
        self.account_combo.hidePopup()

    def _load_selected_account(self, index: int = -1) -> None:
        del index
        self._load_account_by_name(self.account_combo.currentText().strip())

    def _load_account_by_name(self, username: str) -> None:
        account = next(
            (item for item in self.accounts if item.username == username),
            None,
        )
        if account is None:
            self.password_edit.clear()
            self.remember_checkbox.setChecked(False)
            self.auto_login_checkbox.setChecked(False)
            return

        self.password_edit.clear()
        self.remember_checkbox.setChecked(account.remember_password)
        self.auto_login_checkbox.setChecked(False)
        if account.remember_password:
            self.password_edit.setText(account.password)

    def _on_auto_login_toggled(self, checked: bool) -> None:
        if checked:
            self.remember_checkbox.setChecked(True)

    def _on_remember_toggled(self, checked: bool) -> None:
        if not checked:
            self.auto_login_checkbox.setChecked(False)

    def _delete_account(self, username: str) -> None:
        if not username:
            return

        was_current = self.account_combo.currentText().strip() == username
        self.accounts = [item for item in self.accounts if item.username != username]
        if self.last_username == username:
            self.last_username = ""
        self.account_store.save(self.accounts, last_username=self.last_username)
        self._reload_account_combo()
        if was_current:
            self.account_combo.setCurrentText("")
            self.password_edit.clear()
            self.remember_checkbox.setChecked(False)
            self.auto_login_checkbox.setChecked(False)

    def _restore_last_account(self) -> None:
        if not self.last_username:
            return
        self.account_combo.setCurrentText(self.last_username)
        self._load_account_by_name(self.last_username)

    def _save_current_account(self) -> None:
        username = self.account_combo.currentText().strip()
        if not username:
            return
        if not self.password_edit.text().strip():
            show_warning(self, "星弦", "请输入密码")
            return

        self.loading_overlay.show()
        self.loading_overlay.raise_()
        QTimer.singleShot(
            1200,
            lambda: self._finish_login(username, self.password_edit.text()),
        )

    def _finish_login(self, username: str, password: str) -> None:

        try:
            remote_login(username, password)
        except LoginError as error:
            self.loading_overlay.hide()
            show_warning(self, "星弦", str(error))
            return

        remember_password = self.remember_checkbox.isChecked()
        auto_login = self.auto_login_checkbox.isChecked()
        if auto_login:
            remember_password = True
            self.remember_checkbox.setChecked(True)
        password = (
            self.password_edit.text()
            if remember_password or auto_login
            else ""
        )
        account = Account(
            username=username,
            password=password,
            remember_password=remember_password,
            auto_login=auto_login,
        )

        for index, item in enumerate(self.accounts):
            if item.username == username:
                self.accounts[index] = account
                break
        else:
            self.accounts.append(account)

        self.last_username = username
        self.account_store.save(self.accounts, last_username=self.last_username)
        self._reload_account_combo()
        self.account_combo.setCurrentText(username)
        self.loading_overlay.hide()
        self.login_success.emit(username)
        self.close()
