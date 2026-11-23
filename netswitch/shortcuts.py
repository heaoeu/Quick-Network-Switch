"""启动文件夹快捷方式、StartupApproved 状态、桌面快捷方式。

纯 ctypes + COM 调 IShellLinkW / IPersistFile。桌面入口使用真正的 .lnk
快捷方式，不再对启动器做硬链接/符号链接，因此项目文件夹可以放在任意
盘位；移动后重新运行一次 --install 即可刷新快捷方式。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import winreg
from ctypes import wintypes
from pathlib import Path

from .win32 import (
    APP_EXE_NAME,
    CREATE_NO_WINDOW,
    GUID,
    app_icon_path,
    ensure_app_executable,
    guid_from_string,
    ole32,
    startup_dir,
)

CLSID_ShellLink = guid_from_string("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = guid_from_string("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = guid_from_string("0000010B-0000-0000-C000-000000000046")

CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
STGM_READ = 0

SL_GETPATH = 3
SL_GETWORKINGDIRECTORY = 8
SL_SETWORKINGDIRECTORY = 9
SL_GETARGUMENTS = 10
SL_SETARGUMENTS = 11
SL_SETDESCRIPTION = 7
SL_GETICONLOCATION = 16
SL_SETICONLOCATION = 17
SL_SETPATH = 20

PF_LOAD = 5
PF_SAVE = 6

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

APP_NAME = "网络快捷切换"
STARTUP_LNK_NAME = APP_NAME + ".lnk"
DESKTOP_DIR_NAME = APP_NAME + "项目"
DESKTOP_FILE_NAME = APP_NAME + ".lnk"
LEGACY_DESKTOP_FILE_NAME = APP_NAME + ".pyw"
LAUNCHER_NAME = "启动.pyw"

_ole_initialized = False


class ShortcutError(OSError):
    pass


def _ensure_ole() -> None:
    global _ole_initialized
    if _ole_initialized:
        return
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if hr not in (0, 1) and (hr & 0xFFFFFFFF) != 0x80010106:
        raise ShortcutError(f"CoInitializeEx failed: 0x{hr & 0xFFFFFFFF:08X}")
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _ole_initialized = True


def _vtable_method(ptr, index: int, restype, argtypes):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _release(ptr) -> None:
    if not ptr:
        return
    try:
        fn = _vtable_method(ptr, 2, wintypes.ULONG, [])
        fn(ptr)
    except Exception:
        pass


def _create_shell_link():
    ptr = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_ShellLink),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_IShellLinkW),
        ctypes.byref(ptr),
    )
    if hr != 0 or not ptr:
        raise ShortcutError(f"CoCreateInstance(CLSID_ShellLink) failed: 0x{hr & 0xFFFFFFFF:08X}")
    return ptr


def create_shortcut(
    lnk_path: str | os.PathLike[str],
    target: str,
    arguments: str = "",
    working_directory: str = "",
    description: str = "",
    icon_location: str = "",
) -> None:
    _ensure_ole()
    lnk = str(Path(lnk_path).resolve())
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    link = _create_shell_link()
    persist = ctypes.c_void_p()
    try:
        _vtable_method(link, SL_SETPATH, ctypes.c_long, [wintypes.LPCWSTR])(link, str(target))
        if arguments:
            _vtable_method(link, SL_SETARGUMENTS, ctypes.c_long, [wintypes.LPCWSTR])(link, str(arguments))
        if working_directory:
            _vtable_method(link, SL_SETWORKINGDIRECTORY, ctypes.c_long, [wintypes.LPCWSTR])(
                link, str(working_directory)
            )
        if description:
            _vtable_method(link, SL_SETDESCRIPTION, ctypes.c_long, [wintypes.LPCWSTR])(link, str(description))
        if icon_location:
            _vtable_method(link, SL_SETICONLOCATION, ctypes.c_long, [wintypes.LPCWSTR, ctypes.c_int])(
                link, str(icon_location), 0
            )
        query = _vtable_method(
            link,
            0,
            ctypes.c_long,
            [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
        )
        hr = query(link, ctypes.byref(IID_IPersistFile), ctypes.byref(persist))
        if hr != 0 or not persist:
            raise ShortcutError(f"QueryInterface(IPersistFile) failed: 0x{hr & 0xFFFFFFFF:08X}")
        save = _vtable_method(persist, PF_SAVE, ctypes.c_long, [wintypes.LPCWSTR, wintypes.BOOL])
        hr = save(persist, lnk, True)
        if hr != 0:
            raise ShortcutError(f"IPersistFile::Save failed: 0x{hr & 0xFFFFFFFF:08X}")
    finally:
        _release(persist)
        _release(link)


def read_shortcut(lnk_path: str | os.PathLike[str]) -> dict[str, object]:
    _ensure_ole()
    link = _create_shell_link()
    persist = ctypes.c_void_p()
    try:
        query = _vtable_method(
            link,
            0,
            ctypes.c_long,
            [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
        )
        hr = query(link, ctypes.byref(IID_IPersistFile), ctypes.byref(persist))
        if hr != 0 or not persist:
            raise ShortcutError(f"QueryInterface(IPersistFile) failed: 0x{hr & 0xFFFFFFFF:08X}")
        load = _vtable_method(persist, PF_LOAD, ctypes.c_long, [wintypes.LPCWSTR, wintypes.DWORD])
        hr = load(persist, str(lnk_path), STGM_READ)
        if hr != 0:
            raise ShortcutError(f"IPersistFile::Load failed: 0x{hr & 0xFFFFFFFF:08X}")

        path_buf = ctypes.create_unicode_buffer(32768)
        _vtable_method(
            link,
            SL_GETPATH,
            ctypes.c_long,
            [wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
        )(link, path_buf, len(path_buf), None, 0)

        args_buf = ctypes.create_unicode_buffer(32768)
        _vtable_method(link, SL_GETARGUMENTS, ctypes.c_long, [wintypes.LPWSTR, ctypes.c_int])(
            link, args_buf, len(args_buf)
        )

        wd_buf = ctypes.create_unicode_buffer(32768)
        _vtable_method(link, SL_GETWORKINGDIRECTORY, ctypes.c_long, [wintypes.LPWSTR, ctypes.c_int])(
            link, wd_buf, len(wd_buf)
        )

        icon_buf = ctypes.create_unicode_buffer(32768)
        icon_index = ctypes.c_int(0)
        _vtable_method(
            link,
            SL_GETICONLOCATION,
            ctypes.c_long,
            [wintypes.LPWSTR, ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
        )(link, icon_buf, len(icon_buf), ctypes.byref(icon_index))
        return {
            "target": path_buf.value,
            "arguments": args_buf.value,
            "working_directory": wd_buf.value,
            "icon_location": icon_buf.value,
            "icon_index": int(icon_index.value),
        }
    finally:
        _release(persist)
        _release(link)


def notify_shell_changed() -> None:
    """让 Explorer 刷新快捷方式图标缓存。"""
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SHChangeNotify.restype = None
        shell32.SHChangeNotify.argtypes = [
            wintypes.LONG,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


def _read_approved_raw() -> bytes | None:
    path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
            data, _ = winreg.QueryValueEx(key, STARTUP_LNK_NAME)
            return bytes(data)
    except OSError:
        return None


def _write_approved_raw(data: bytes | None) -> None:
    path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
        if data is None:
            try:
                winreg.DeleteValue(key, STARTUP_LNK_NAME)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, STARTUP_LNK_NAME, 0, winreg.REG_BINARY, data)


def _approved_state(raw: bytes | None) -> str:
    if not raw:
        return "default"
    if len(raw) >= 4:
        state = int.from_bytes(raw[:4], "little")
        if state == 2:
            return "enabled"
        if state == 3:
            return "disabled"
        if state == 6:
            return "enabled"
        return "unknown"
    return "unknown"


def startup_shortcut_path() -> Path:
    return Path(startup_dir()) / STARTUP_LNK_NAME


def startup_state(script_path: str) -> dict:
    lnk = startup_shortcut_path()
    raw = _read_approved_raw()
    approved = _approved_state(raw)
    exists = lnk.is_file()
    target = arguments = ""
    target_ok = args_ok = False
    read_error = ""
    if exists:
        try:
            info = read_shortcut(lnk)
            target = info.get("target", "")
            arguments = info.get("arguments", "")
            target_base = os.path.normcase(os.path.basename(target))
            target_ok = target_base in {
                os.path.normcase("pythonw.exe"),
                os.path.normcase(APP_EXE_NAME),
            }
            norm_script = os.path.normcase(os.path.abspath(script_path))
            args_text = os.path.normcase(arguments)
            args_ok = norm_script in args_text and "--tray" in arguments
        except Exception as exc:
            read_error = str(exc)
    return {
        "path": str(lnk),
        "exists": exists,
        "approved": approved,
        "approved_raw": raw.hex(" ") if raw else "",
        "enabled": exists and approved != "disabled",
        "target": target,
        "arguments": arguments,
        "target_ok": target_ok,
        "args_ok": args_ok,
        "read_error": read_error,
        "task_manager_visible": exists,
    }


def set_startup_enabled(
    enabled: bool,
    project_dir: str,
    script_path: str,
    description: str = APP_NAME,
    force: bool = False,
) -> dict:
    """用户主动勾选/取消勾选时才写入；程序启动时不自动修复。"""
    lnk = startup_shortcut_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    state = startup_state(script_path)
    exe = ensure_app_executable()
    args = f'"{script_path}" --tray'
    wanted_target = os.path.normcase(os.path.abspath(exe))
    current_target = os.path.normcase(os.path.abspath(state.get("target", "")))
    if force or not state["exists"] or current_target != wanted_target or not state["args_ok"]:
        create_shortcut(
            lnk,
            exe,
            arguments=args,
            working_directory=project_dir,
            description=description,
            icon_location=app_icon_path() or exe,
        )
    if enabled:
        _write_approved_raw(b"\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    else:
        _write_approved_raw(b"\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    return startup_state(script_path)


def remove_startup_shortcut() -> None:
    lnk = startup_shortcut_path()
    try:
        if lnk.is_file():
            lnk.unlink()
    except OSError:
        pass
    try:
        _write_approved_raw(None)
    except OSError:
        pass


def write_launcher(project_dir: str, script_path: str, mode: str = "--manage") -> Path:
    """写项目内的启动器；只使用自身所在目录，可随项目整体移动。"""
    path = Path(project_dir) / LAUNCHER_NAME
    content = (
        "# -*- coding: utf-8 -*-\n"
        "# 由 --install 生成；路径相对于本文件，移动项目后仍可用。\n"
        "import os\n"
        "import runpy\n"
        "import subprocess\n"
        "import sys\n"
        "sys.dont_write_bytecode = True\n"
        "PROJECT = os.path.dirname(os.path.abspath(__file__))\n"
        'SCRIPT = os.path.join(PROJECT, "net_switch.py")\n'
        f"MODE = {mode!r}\n"
        "os.chdir(PROJECT)\n"
        "sys.path.insert(0, PROJECT)\n"
        "APP_EXE = ''\n"
        "try:\n"
        "    from netswitch.win32 import ensure_app_executable\n"
        "    APP_EXE = ensure_app_executable()\n"
        "except Exception:\n"
        "    pass\n"
        "if APP_EXE and os.path.isfile(APP_EXE) and os.path.normcase(os.path.abspath(APP_EXE)) != os.path.normcase(os.path.abspath(sys.executable)):\n"
        "    try:\n"
        "        subprocess.Popen([APP_EXE, SCRIPT, MODE], cwd=PROJECT, creationflags=0x08000000, close_fds=True)\n"
        "        raise SystemExit(0)\n"
        "    except SystemExit:\n"
        "        raise\n"
        "    except Exception:\n"
        "        pass\n"
        "sys.argv = [SCRIPT, MODE]\n"
        "runpy.run_path(SCRIPT, run_name='__main__')\n"
    )
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _run_mklink_junction(link: str, target: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", link, target],
            capture_output=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        text = proc.stdout.decode("mbcs", "replace") + proc.stderr.decode("mbcs", "replace")
        return proc.returncode == 0, text
    except Exception as exc:
        return False, str(exc)


def _same_target(link: str, target: str) -> bool:
    try:
        return os.path.samefile(link, target)
    except OSError:
        return False


def _remove_broken_link(link: Path) -> None:
    try:
        if link.is_symlink():
            link.unlink()
        elif _is_directory_link(link):
            link.rmdir()
    except OSError:
        pass


def _is_directory_link(link: Path) -> bool:
    try:
        if link.is_symlink():
            return True
        is_junction = getattr(link, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return False


def _remove_directory_link(link: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        link.rmdir()


def ensure_directory_link(link: Path, target: Path) -> str:
    link = Path(link)
    target = Path(target)
    if link.exists() or link.is_symlink() or _is_directory_link(link):
        if _same_target(str(link), str(target)):
            try:
                return "symlink" if link.is_symlink() else "junction"
            except OSError:
                return "junction"
        if _is_directory_link(link):
            # 项目换盘后，旧的 junction/symlink 指向已失效；替换为新的。
            _remove_directory_link(link)
        else:
            raise FileExistsError(f"桌面已存在同名项目，但它不是指向本项目的链接：{link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        if _same_target(str(link), str(target)):
            return "symlink"
    except OSError:
        pass
    _remove_broken_link(link)
    ok, output = _run_mklink_junction(str(link), str(target))
    if not ok or not _same_target(str(link), str(target)):
        raise OSError(f"创建目录链接失败：{output.strip() or 'mklink /J 失败'}")
    return "junction"
