"""通知区域托盘：一个隐藏 Win32 窗口 + Shell_NotifyIcon + 右键菜单。

线程模型：
- 托盘线程拥有隐藏窗口和消息循环，不碰 Tk；
- Tk 主线程只通过 queue 收事件；
- 网络读取在独立后台线程完成，界面线程永不做阻塞 IO。
"""
from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes

from . import icons
from .win32 import kernel32, shell32, user32

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_NULL = 0x0000
WM_APP = 0x8000
WM_APP_STATE = WM_APP + 1
WM_APP_SHOW_MANAGER = WM_APP + 3
WM_APP_SHOW_COMPACT = WM_APP + 4
WM_APP_QUIT = WM_APP + 5
WM_APP_NOTIFY = WM_APP + 6
WM_APP_TRAY_CALLBACK = WM_APP + 10
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIF_SHOWTIP = 0x00000080

NIIF_INFO = 0x00000001
NIIF_ERROR = 0x00000003
NOTIFYICON_VERSION_4 = 4
WS_EX_TOOLWINDOW = 0x00000080

MF_STRING = 0x00000000
MF_GRAYED = 0x00000001
MF_CHECKED = 0x00000008
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

MENU_MANAGER = 1
MENU_COMPACT = 2
MENU_REFRESH = 3
MENU_RESTORE = 4
MENU_QUIT = 5
MENU_MORE = 6
MENU_PROFILE_BASE = 1000
MAX_MENU_PROFILES = 10

CLASS_NAME = "NetSwitchTrayWindow_v1"
MUTEX_NAME = "Local\\NetSwitchTray_v1"

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    ctypes.c_void_p,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PostQuitMessage.restype = None
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.CreatePopupMenu.argtypes = []
user32.AppendMenuW.restype = wintypes.BOOL
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
user32.TrackPopupMenuEx.restype = wintypes.UINT
user32.TrackPopupMenuEx.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    ctypes.c_void_p,
]
user32.DestroyMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]


class TrayThread(threading.Thread):
    def __init__(self, events: queue.Queue):
        super().__init__(name="net-switch-tray", daemon=True)
        self.events = events
        self.hwnd = 0
        self.error = ""
        self.icon_error = ""
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._profiles: list[tuple[str, str]] = []
        self._selected_id: str | None = None
        self._tooltip = "网络快捷切换"
        self._pending_notify: tuple[str, str, bool] | None = None
        self._menu_open = False
        self._class_atom = 0
        self._taskbar_created = 0
        self._hicon = 0
        self._icon_added = False
        self._wndproc_ref = WNDPROC(self._wndproc)

    # ---- public API -----------------------------------------------------
    def start_and_wait(self, timeout: float = 4.0) -> bool:
        self.start()
        return self._ready.wait(timeout) and not self.error

    def set_state(self, profiles: list[tuple[str, str]], selected_id: str | None, tooltip: str) -> None:
        with self._lock:
            self._profiles = list(profiles)
            self._selected_id = selected_id
            self._tooltip = (tooltip or "网络快捷切换")[:120]
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_STATE, 0, 0)

    def notify(self, title: str, text: str, error: bool = False) -> None:
        with self._lock:
            self._pending_notify = (title[:63], text[:255], bool(error))
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_NOTIFY, 0, 0)

    def show_manager(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_SHOW_MANAGER, 0, 0)

    def show_compact(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_SHOW_COMPACT, 0, 0)

    def request_quit(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_QUIT, 0, 0)

    def stop(self, wait: float = 3.0) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self._stopped.wait(max(0.0, wait))

    # ---- thread body ----------------------------------------------------
    def run(self) -> None:
        try:
            self._create_window()
            if not self.hwnd:
                self.error = self.error or "CreateWindowExW failed"
                self._ready.set()
                return
            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            self._add_icon()
            self._apply_tooltip()
            self._ready.set()
            msg = MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.error = f"托盘线程异常：{exc}"
            self._ready.set()
        finally:
            try:
                if self.hwnd:
                    self._delete_icon()
                    user32.DestroyWindow(self.hwnd)
                    self.hwnd = 0
                if self._class_atom:
                    user32.UnregisterClassW(CLASS_NAME, kernel32.GetModuleHandleW(None))
            except Exception:
                pass
            self._stopped.set()

    def _create_window(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = 0
        wc.hCursor = 0
        wc.hbrBackground = 0
        wc.lpszMenuName = None
        wc.lpszClassName = CLASS_NAME
        self._class_atom = user32.RegisterClassW(ctypes.byref(wc))
        if not self._class_atom:
            self.error = f"RegisterClassW failed ({ctypes.get_last_error()})"
            return
        self.hwnd = int(
            user32.CreateWindowExW(
                WS_EX_TOOLWINDOW,
                CLASS_NAME,
                "网络快捷切换 TrayHost",
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                hinst,
                None,
            )
            or 0
        )
        if not self.hwnd:
            self.error = f"CreateWindowExW failed ({ctypes.get_last_error()})"

    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uCallbackMessage = WM_APP_TRAY_CALLBACK
        return nid

    def _add_icon(self) -> None:
        if not self._hicon:
            self._hicon = icons.create_tray_icon()
        if not self._hicon:
            self.icon_error = "创建托盘图标失败"
            return
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        nid.hIcon = self._hicon
        nid.szTip = self._tooltip
        ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if not ok:
            for _ in range(8):
                time.sleep(0.15)
                if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                    ok = True
                    break
        if not ok:
            self.icon_error = "Shell_NotifyIconW(NIM_ADD) 失败（Explorer 可能未运行）"
            return
        self._icon_added = True
        version = self._nid()
        version.uFlags = 0
        version.uTimeout = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(version))
        self._apply_tooltip()

    def _delete_icon(self) -> None:
        if self._icon_added and self.hwnd:
            nid = self._nid()
            try:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
        self._icon_added = False
        if self._hicon:
            icons.destroy_icon(self._hicon)
            self._hicon = 0

    def _apply_tooltip(self) -> None:
        if not self.hwnd or not self._icon_added:
            return
        nid = self._nid()
        nid.uFlags = NIF_TIP | NIF_SHOWTIP
        nid.szTip = self._tooltip[:120]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _show_balloon(self) -> None:
        with self._lock:
            payload = self._pending_notify
            self._pending_notify = None
        if not payload or not self.hwnd or not self._icon_added:
            return
        title, text, is_error = payload
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title
        nid.szInfo = text
        nid.dwInfoFlags = NIIF_ERROR if is_error else NIIF_INFO
        nid.uTimeout = 6000
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _show_context_menu(self) -> None:
        if self._menu_open or not self.hwnd:
            return
        self._menu_open = True
        menu = 0
        try:
            with self._lock:
                profiles = list(self._profiles)
                selected = self._selected_id
            visible_profiles = profiles[:MAX_MENU_PROFILES]
            menu = user32.CreatePopupMenu()
            if not menu:
                return
            user32.AppendMenuW(menu, MF_STRING, MENU_MANAGER, "打开主界面")
            user32.AppendMenuW(menu, MF_STRING, MENU_COMPACT, "打开简洁面板")
            user32.AppendMenuW(menu, MF_STRING, MENU_REFRESH, "立即刷新")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            if not profiles:
                user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, "（暂无方案）")
            for index, (pid, name) in enumerate(visible_profiles):
                flags = MF_STRING | (MF_CHECKED if pid == selected else 0)
                # 菜单文本里的 & 是 accelerator 前缀，需要双写。
                user32.AppendMenuW(menu, flags, MENU_PROFILE_BASE + index, name[:80].replace("&", "&&"))
            if len(profiles) > MAX_MENU_PROFILES:
                user32.AppendMenuW(menu, MF_STRING, MENU_MORE, f"更多方案…（共 {len(profiles)} 个）")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_RESTORE, "恢复默认（自动获取）")
            user32.AppendMenuW(menu, MF_STRING, MENU_QUIT, "退出程序")
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self.hwnd)
            command = int(
                user32.TrackPopupMenuEx(
                    menu,
                    TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
                    point.x,
                    point.y,
                    self.hwnd,
                    None,
                )
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            if command == MENU_MANAGER:
                self.events.put(("open_manager",))
            elif command == MENU_COMPACT:
                self.events.put(("open_compact",))
            elif command == MENU_REFRESH:
                self.events.put(("refresh",))
            elif command == MENU_RESTORE:
                self.events.put(("restore",))
            elif command == MENU_QUIT:
                self.events.put(("quit",))
            elif command == MENU_MORE:
                self.events.put(("open_manager",))
            elif MENU_PROFILE_BASE <= command < MENU_PROFILE_BASE + len(visible_profiles):
                pid = visible_profiles[command - MENU_PROFILE_BASE][0]
                self.events.put(("apply", pid))
        except Exception:
            pass
        finally:
            if menu:
                user32.DestroyMenu(menu)
            self._menu_open = False

    def _on_callback(self, lparam: int) -> None:
        event = int(lparam) & 0xFFFF
        if event in (WM_LBUTTONUP, NIN_SELECT, NIN_KEYSELECT):
            self.events.put(("open_compact",))
        elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
            self._show_context_menu()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_DESTROY:
                self._delete_icon()
                user32.PostQuitMessage(0)
                self._stopped.set()
                self.events.put(("tray_closed",))
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_APP_STATE:
                with self._lock:
                    self._tooltip = self._tooltip[:120]
                self._apply_tooltip()
                return 0
            if msg == WM_APP_NOTIFY:
                self._show_balloon()
                return 0
            if msg == WM_APP_SHOW_MANAGER:
                self.events.put(("open_manager",))
                return 0
            if msg == WM_APP_SHOW_COMPACT:
                self.events.put(("open_compact",))
                return 0
            if msg == WM_APP_QUIT:
                self.events.put(("quit",))
                return 0
            if msg == WM_APP_TRAY_CALLBACK:
                self._on_callback(int(lparam))
                return 0
            if self._taskbar_created and msg == self._taskbar_created:
                # Explorer 重启后任务栏图标丢失，重新 NIM_ADD；HICON 不重建。
                self._icon_added = False
                self._add_icon()
                return 0
            if msg == WM_QUERYENDSESSION:
                return 1
            if msg == WM_ENDSESSION:
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            return 0


def find_tray_window() -> int:
    try:
        return int(user32.FindWindowW(CLASS_NAME, None) or 0)
    except Exception:
        return 0


def notify_existing_instance(mode: str = "manager", timeout: float = 2.5) -> bool:
    deadline = time.monotonic() + timeout
    message = WM_APP_SHOW_COMPACT if mode == "compact" else WM_APP_SHOW_MANAGER
    while time.monotonic() < deadline:
        hwnd = find_tray_window()
        if hwnd:
            user32.PostMessageW(hwnd, message, 0, 0)
            return True
        time.sleep(0.1)
    return False


class SingleInstance:
    def __init__(self, name: str = MUTEX_NAME):
        self.handle = kernel32.CreateMutexW(None, False, name)
        self.already_exists = ctypes.get_last_error() == 183
        self.name = name

    def close(self) -> None:
        if self.handle:
            try:
                kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = 0

    def __del__(self):
        self.close()
