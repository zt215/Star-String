from app import main
from app.ui.login_window import BACKGROUND_PATH, LOGO_PATH


def test_main_module_is_importable() -> None:
    assert callable(main.main)


def test_login_resources_exist() -> None:
    assert BACKGROUND_PATH.exists()
    assert LOGO_PATH.exists()
