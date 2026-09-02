from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


STYLE_SHEET = """
QMessageBox {
    background-color: #FFFFFF;
    border: 1px solid #B3CDEB;
}
QMessageBox QLabel {
    color: #1E6FD9;
    font-size: 14px;
}
QMessageBox QPushButton {
    color: #0A1020;
    background-color: #E8F2FF;
    border: 1px solid #B3CDEB;
    border-radius: 6px;
    padding: 6px 18px;
}
QMessageBox QPushButton:hover {
    background-color: #D9E9FF;
}
QMessageBox QPushButton:pressed {
    background-color: #C5DDF7;
}
"""


def show_message(
    parent: QWidget,
    title: str,
    text: str,
    icon: QMessageBox.Icon = QMessageBox.Information,
) -> None:
    box = QMessageBox(
        icon,
        title,
        text,
        standardButtons=QMessageBox.Ok,
        parent=parent,
    )
    box.setStyleSheet(STYLE_SHEET)
    box.exec()


def show_info(parent: QWidget, title: str, text: str) -> None:
    show_message(parent, title, text, QMessageBox.Information)


def show_warning(parent: QWidget, title: str, text: str) -> None:
    show_message(parent, title, text, QMessageBox.Warning)
