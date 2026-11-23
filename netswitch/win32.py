"""Windows 底层小工具：只用标准库 + ctypes。

这里集中放置 DPI、Known Folder、管理员检测、pythonw 路径等基础能力。
项目不写任何日志文件；诊断信息只在显式 --debug 时输出到控制台。
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

if sys.platform != "win32":
    raise RuntimeError("本工具只支持 Windows 10/11")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
wlanapi = ctypes.WinDLL("wlanapi", use_last_error=True)

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

CREATE_NO_WINDOW = 0x08000000
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_RESTORE = 9
ERROR_ALREADY_EXISTS = 183
ERROR_CANCELLED = 1223


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def guid_from_string(text: str) -> GUID:
    """把 {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX} 解析成 GUID。"""
    text = text.strip().strip("{}")
    parts = text.split("-", 3)
    if len(parts) != 4:
        raise ValueError(f"无效 GUID：{text!r}")
    g = GUID()
    g.Data1 = int(parts[0], 16)
    g.Data2 = int(parts[1], 16)
    g.Data3 = int(parts[2], 16)
    tail = bytes.fromhex(parts[3].replace("-", ""))
    if len(tail) != 8:
        raise ValueError(f"无效 GUID：{text!r}")
    for i, b in enumerate(tail):
        g.Data4[i] = b
    return g


FOLDERID_Desktop = guid_from_string("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
FOLDERID_Startup = guid_from_string("B97D20BB-F46A-4C97-BA10-5E3608430854")


def set_dpi_aware() -> None:
    """在创建 Tk 窗口前启用 Per-Monitor V2，避免字体和托盘图标发虚。"""
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [wintypes.HANDLE]
        fn.restype = wintypes.BOOL
        if fn(wintypes.HANDLE(-4)):
            return
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        fn = shcore.SetProcessDpiAwareness
        fn.argtypes = [ctypes.c_int]
        fn.restype = ctypes.c_long
        fn(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def get_dpi_for_system() -> int:
    try:
        fn = user32.GetDpiForSystem
        fn.restype = wintypes.UINT
        return max(96, int(fn()))
    except Exception:
        return 96


def known_folder(folder_id: GUID) -> str:
    try:
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        ptr = ctypes.c_wchar_p()
        fn = shell32.SHGetKnownFolderPath
        fn.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        fn.restype = ctypes.c_long
        hr = fn(ctypes.byref(folder_id), 0, None, ctypes.byref(ptr))
        if hr == 0 and ptr.value:
            value = ptr.value
            ole32.CoTaskMemFree(ptr)
            return value
    except Exception:
        pass
    return ""


def desktop_dir() -> str:
    value = known_folder(FOLDERID_Desktop)
    if value:
        return value
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")


def startup_dir() -> str:
    value = known_folder(FOLDERID_Startup)
    if value:
        return value
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )


def pythonw_path() -> str:
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base == "python.exe":
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(candidate):
            return candidate
    return exe


APP_EXE_NAME = "网络快捷切换.exe"


def ensure_app_executable() -> str:
    """在 Python 目录创建名为“网络快捷切换.exe”的硬链接/副本。

    Windows 任务管理器的进程名来自可执行文件名。硬链接与 pythonw.exe
    同目录，Python 仍能找到 DLL 和标准库；无权限时退回 pythonw.exe。
    """
    base = pythonw_path()
    folder = os.path.dirname(os.path.abspath(base))
    target = os.path.join(folder, APP_EXE_NAME)
    if os.path.normcase(os.path.abspath(base)) == os.path.normcase(os.path.abspath(target)):
        return target
    try:
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
    except OSError:
        pass
    try:
        if os.path.exists(target):
            os.unlink(target)
        os.link(base, target)
        return target
    except OSError:
        pass
    try:
        import shutil

        shutil.copy2(base, target)
        return target
    except OSError:
        return base


def python_script() -> str:
    """返回 GUI 入口脚本的绝对路径（供快捷方式/提权子进程使用）。"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "net_switch.py")


def asset_path(*parts: str) -> str:
    """返回项目 assets 目录下的文件路径。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", *parts)


def app_icon_path() -> str:
    """返回自定义 .ico；资源缺失时返回空字符串，调用方回退到 exe 图标。"""
    path = asset_path("app.ico")
    return path if os.path.isfile(path) else ""


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_app_user_model_id(app_id: str) -> None:
    try:
        fn = shell32.SetCurrentProcessExplicitAppUserModelID
        fn.argtypes = [wintypes.LPCWSTR]
        fn.restype = ctypes.c_long
        fn(app_id)
    except Exception:
        pass


def loword(value: int) -> int:
    return int(value) & 0xFFFF


def win_error_text(code: int | None = None) -> str:
    if code is None:
        code = ctypes.get_last_error()
    try:
        return ctypes.FormatError(int(code)).strip()
    except Exception:
        return f"WinError {code}"


def work_area() -> tuple[int, int, int, int]:
    """返回物理像素的工作区 (left, top, right, bottom)。"""
    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rect = _RECT()
    try:
        fn = user32.SystemParametersInfoW
        fn.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        fn.restype = wintypes.BOOL
        if fn(0x0030, 0, ctypes.byref(rect), 0) and rect.right > rect.left:
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        pass
    return 0, 0, int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def center_window(win, width: int, height: int) -> None:
    """把 Toplevel 放到当前显示器工作区中间（物理像素）。"""
    try:
        win.update_idletasks()
        left, top, right, bottom = work_area()
        avail_w = max(320, right - left)
        avail_h = max(240, bottom - top)
        width = min(int(width), avail_w - 16)
        height = min(int(height), avail_h - 16)
        x = left + max(0, (avail_w - width) // 2)
        y = top + max(0, (avail_h - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        win.geometry(f"{width}x{height}")


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)
