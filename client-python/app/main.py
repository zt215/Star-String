from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from app.services.account_store import AccountStore
from app.services.auth_service import LoginError, login as remote_login
from app.services.model_store import LOCAL_PROFILE_DISPLAY
from app.ui.home_window import HomeWindow
from app.ui.loading_window import LoadingWindow
from app.ui.login_window import LoginWindow


def _apply_dark_palette(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0A1020"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0A142A"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#111B33"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#111B33"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#EAF6FF"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#EAF6FF"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#EAF6FF"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#111B33"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#EAF6FF"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FF5555"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2F80E6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#A9C3E2"))
    app.setPalette(palette)


def main() -> int:
    # 虚拟摄像头透明背景需要 OpenGL 表面带 alpha 通道，必须在创建窗口前设置。
    surface_format = QSurfaceFormat()
    surface_format.setAlphaBufferSize(8)
    surface_format.setDepthBufferSize(24)
    surface_format.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QApplication(sys.argv)
    app.setApplicationName("星弦")
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    current = {"window": None}

    def open_home(username: str | None = None, offline: bool = False) -> None:
        if offline:
            # Offline mode always uses the separate local profile, never the
            # account that happens to be selected in the login form.
            username = LOCAL_PROFILE_DISPLAY
        home = HomeWindow(username, offline)
        home.logout_requested.connect(show_login)
        home.show()
        if current["window"] is not None:
            current["window"].close()
        current["window"] = home

    def show_login() -> None:
        login = LoginWindow()
        login.login_success.connect(open_home)
        login.show()
        if current["window"] is not None:
            current["window"].close()
        current["window"] = login

    store = AccountStore()
    accounts = store.load()
    last_username = store.load_last_username()
    account = next(
        (
            item
            for item in accounts
            if item.username == last_username and item.auto_login and item.password
        ),
        None,
    )

    if account is None:
        show_login()
    else:
        loading = LoadingWindow()
        loading.show()

        def finish_auto_login() -> None:
            if account.offline:
                loading.close()
                open_home(None, True)
                return
            try:
                remote_login(account.username, account.password)
            except LoginError:
                loading.close()
                show_login()
                return
            loading.close()
            open_home(account.username, False)

        QTimer.singleShot(1200, finish_auto_login)

    exit_code = app.exec()
    os._exit(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
