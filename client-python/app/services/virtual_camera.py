from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

import numpy as np


VIRTUAL_CAMERA_NAME = "星弦虚拟摄像头"
UNITY_CAPTURE_CLSID = "{5C2CD55C-92AD-4999-8666-912BD3E70010}"


class VirtualCameraError(Exception):
    pass


def _bundled_virtualcam_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "app" / "resources" / "virtualcam"
    return Path(__file__).resolve().parent.parent / "resources" / "virtualcam"


def virtualcam_dir() -> Path:
    """优先使用随程序安装的驱动目录，其次使用打包内置资源。"""
    exe_dir = Path(sys.executable).resolve().parent
    for candidate in (exe_dir / "virtualcam", _bundled_virtualcam_dir()):
        if (candidate / "UnityCaptureFilter64.dll").exists():
            return candidate
    return _bundled_virtualcam_dir()


def driver_files() -> tuple[Path, Path]:
    base = virtualcam_dir()
    return base / "UnityCaptureFilter32.dll", base / "UnityCaptureFilter64.dll"


def driver_files_present() -> bool:
    return all(path.exists() for path in driver_files())


def install_dir() -> Path:
    """驱动安装目录：必须为纯 ASCII 路径，否则 ANSI 注册会截断路径。"""
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(base) / "StarString" / "virtualcam"


def installed_driver_files() -> tuple[Path, Path]:
    base = install_dir()
    return base / "UnityCaptureFilter32.dll", base / "UnityCaptureFilter64.dll"


def registered_server_path() -> str:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            rf"CLSID\{UNITY_CAPTURE_CLSID}\InprocServer32",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
        return str(value)
    except OSError:
        return ""


def driver_registered() -> bool:
    path = registered_server_path()
    if not path:
        return False
    candidate = Path(path)
    if candidate.suffix.lower() != ".dll" or not candidate.is_file():
        return False
    try:
        str(candidate).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _run_elevated(command: str, timeout_ms: int = 120000) -> bool:
    """以管理员权限运行命令并等待完成（会弹 UAC），返回是否成功。"""
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "cmd.exe"
    info.lpParameters = f"/c {command}"
    info.nShow = 0  # 隐藏窗口，避免闪 cmd
    try:
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            return False
    except Exception:
        return False
    if not info.hProcess:
        return True
    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, timeout_ms)
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(
            info.hProcess, ctypes.byref(code)
        )
        return code.value == 0
    except Exception:
        return False
    finally:
        try:
            ctypes.windll.kernel32.CloseHandle(info.hProcess)
        except Exception:
            pass


def install_driver(name: str = VIRTUAL_CAMERA_NAME) -> tuple[bool, str]:
    """把驱动复制到纯英文目录并注册为 ``name``（需要管理员权限）。"""
    src32, src64 = driver_files()
    if not (src32.exists() and src64.exists()):
        return False, "未找到虚拟摄像头驱动文件"
    dst32, dst64 = installed_driver_files()
    target = install_dir()
    command = (
        f'mkdir "{target}" 2>nul'
        f' & copy /y "{src32}" "{dst32}" >nul'
        f' & copy /y "{src64}" "{dst64}" >nul'
        f' & regsvr32 /s "{dst64}" "/i:UnityCaptureName={name}"'
        f' & regsvr32 /s "{dst32}" "/i:UnityCaptureName={name}"'
    )
    if not _run_elevated(command):
        return False, "未获得管理员权限，或驱动注册失败"
    if driver_registered():
        return True, "驱动已安装"
    return False, f"注册未生效（{registered_server_path() or '未写入注册表'}）"


def uninstall_driver() -> bool:
    """注销虚拟摄像头驱动（需要管理员权限）。"""
    dst32, dst64 = installed_driver_files()
    if not (dst32.exists() and dst64.exists()):
        return False
    command = (
        f'regsvr32 /u /s "{dst64}"'
        " & "
        f'regsvr32 /u /s "{dst32}"'
    )
    return _run_elevated(command)


def probe_driver(name: str = VIRTUAL_CAMERA_NAME) -> tuple[bool, str]:
    """尝试创建一次虚拟摄像头，判断驱动与后端是否可用。"""
    try:
        import pyvirtualcam
    except ImportError:
        return False, "缺少 pyvirtualcam 依赖"
    try:
        # 用自动选择：部分驱动在枚举时读不到设备名，按名字匹配会失败。
        camera = pyvirtualcam.Camera(
            width=64,
            height=64,
            fps=1,
            fmt=pyvirtualcam.PixelFormat.RGBA,
            backend="unitycapture",
        )
    except Exception as error:  # noqa: BLE001 - 后端异常类型由驱动决定
        return False, str(error)
    try:
        camera.close()
    except Exception:
        pass
    return True, "已安装"


class VirtualCameraOutput:
    """把画面推送到系统虚拟摄像头设备。"""

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        device: str = VIRTUAL_CAMERA_NAME,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.device = device
        self._camera = None

    @property
    def running(self) -> bool:
        return self._camera is not None

    @property
    def active_device(self) -> str:
        # 后端枚举到的名字可能为空，这里统一显示注册时使用的设备名。
        return self.device

    def start(self) -> None:
        if self._camera is not None:
            return
        try:
            import pyvirtualcam
        except ImportError as error:
            raise VirtualCameraError("缺少 pyvirtualcam 依赖") from error
        try:
            self._camera = pyvirtualcam.Camera(
                width=self.width,
                height=self.height,
                fps=self.fps,
                fmt=pyvirtualcam.PixelFormat.RGBA,
                backend="unitycapture",
                print_fps=False,
            )
        except Exception as error:  # noqa: BLE001
            self._camera = None
            raise VirtualCameraError(str(error)) from error

    def send(self, frame_rgb: np.ndarray) -> None:
        if self._camera is None:
            return
        self._camera.send(frame_rgb)

    def stop(self) -> None:
        camera = self._camera
        self._camera = None
        if camera is not None:
            try:
                camera.close()
            except Exception:
                pass
