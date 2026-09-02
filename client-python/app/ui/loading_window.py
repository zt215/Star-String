from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
LOGO_PATH = RESOURCES_DIR / "images" / "star_logo.png"
ICON_PATH = RESOURCES_DIR / "images" / "star_logo.ico"


class LoadingWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("星弦")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(360, 190)
        self.setStyleSheet(
            """
            QWidget {
                background-color: #0D1730;
                border: 1px solid #284064;
                border-radius: 14px;
                font-family: "Microsoft YaHei";
            }
            QLabel#loadingBrand {
                color: #EAF6FF;
                font-size: 20px;
                font-weight: 600;
                letter-spacing: 2px;
            }
            QLabel#loadingText {
                color: #9DB5D8;
                font-size: 13px;
            }
            QProgressBar#loadingProgress {
                border: none;
                border-radius: 3px;
                background: #16223F;
            }
            QProgressBar#loadingProgress::chunk {
                border-radius: 3px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #2E7FD9,
                    stop: 1 #7EE7FF
                );
            }
            """
        )

        icon_path = ICON_PATH if ICON_PATH.exists() else LOGO_PATH
        self.setWindowIcon(QIcon(str(icon_path)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignCenter)

        brand = QLabel("✦ 星弦")
        brand.setObjectName("loadingBrand")
        brand.setAlignment(Qt.AlignCenter)
        layout.addWidget(brand)

        text = QLabel("正在登录...")
        text.setObjectName("loadingText")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)

        progress = QProgressBar()
        progress.setObjectName("loadingProgress")
        progress.setRange(0, 0)
        progress.setFixedSize(260, 6)
        layout.addWidget(progress)

        self.center_on_screen()

    def center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            area.center().y() - self.height() // 2,
        )
